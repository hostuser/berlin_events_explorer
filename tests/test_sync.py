"""End-to-end tests for source synchronization."""

import time

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.sync import SyncError, sync_source


CSV_V1 = """Date,Note,Artist,Venue
13.07.2026,,Haevn,Classic Open Air
14.07.2026,sold out,House Of Protection,Mikropol
"""
CSV_V2 = """Date,Note,Artist,Venue
13.07.2026,,Haevn,Classic Open Air
14.07.2026,cancelled,House Of Protection,Mikropol
15.07.2026,new,New Artist,Schokoladen
"""
CSV_DUPLICATE = """Date,Note,Artist,Venue
13.07.2026,,Haevn,Classic Open Air
13.07.2026,,Haevn,Classic Open Air
"""


def test_first_sync_persists_events_and_audit_log(tmp_path) -> None:
    """A first sync stores events and records their creation."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("if-none-match") is None
        return httpx.Response(200, text=CSV_V1, headers={"etag": '"v1"'})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")

    result = sync_source(MyTrueIntentSource(), store, client)

    assert result.downloaded is True
    assert result.created == 2
    assert result.updated == 0
    assert result.unchanged == 0
    assert len(store.list_events()) == 2
    assert [entry.action for entry in store.list_audit_log()] == [
        "created",
        "created",
    ]


def test_unchanged_source_uses_etag_and_skips_parsing(tmp_path) -> None:
    """A matching ETag should result in a conditional request and no changes."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"etag": '"v1"'})
        return httpx.Response(200, text=CSV_V1, headers={"etag": '"v1"'})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")
    source = MyTrueIntentSource()

    sync_source(source, store, client)
    result = sync_source(source, store, client)

    assert result.downloaded is False
    assert result.created == 0
    assert result.updated == 0
    assert result.unchanged == 2
    assert requests[1].headers["if-none-match"] == '"v1"'
    assert len(store.list_audit_log()) == 2


def test_changed_source_updates_and_creates_audit_entries(tmp_path) -> None:
    """Changed rows are updated and new rows are inserted with audit records."""
    versions = iter([CSV_V1, CSV_V2])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=next(versions), headers={"etag": '"v2"'})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")
    source = MyTrueIntentSource()

    sync_source(source, store, client)
    result = sync_source(source, store, client)

    assert result.downloaded is True
    assert result.created == 1
    assert result.updated == 1
    assert result.unchanged == 1
    assert len(store.list_events()) == 3
    assert [entry.action for entry in store.list_audit_log()] == [
        "created",
        "created",
        "updated",
        "created",
    ]


def test_304_updates_snapshot_checked_at(tmp_path) -> None:
    """A 304 response should still refresh checked_at metadata."""

    source = MyTrueIntentSource()
    path = tmp_path / "events.sqlite"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(
                304,
                headers={
                    "etag": '"v1"',
                    "Last-Modified": "Wed, 21 Oct 2015 07:28:00 GMT",
                },
            )
        return httpx.Response(
            200,
            text=CSV_V1,
            headers={"etag": '"v1"', "Last-Modified": "Wed, 21 Oct 2015 07:28:00 GMT"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(path)

    sync_source(source, store, client)
    snapshot_before = store.get_snapshot(source.name)
    assert snapshot_before is not None
    assert snapshot_before.checked_at is not None

    time.sleep(0.01)
    sync_source(source, store, client)
    snapshot_after = store.get_snapshot(source.name)

    assert snapshot_after is not None
    assert snapshot_after.etag == '"v1"'
    assert snapshot_after.last_modified == "Wed, 21 Oct 2015 07:28:00 GMT"
    assert snapshot_after.checked_at >= snapshot_before.checked_at


def test_sync_error_when_network_request_fails(tmp_path) -> None:
    """Network failures should raise SyncError with a clear message."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection unavailable", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")

    with pytest.raises(SyncError, match="Network request failed"):
        sync_source(MyTrueIntentSource(), store, client)


def test_sync_error_when_csv_is_invalid(tmp_path) -> None:
    """Malformed source payloads should surface as SyncError."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="bad,header\n1,2")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")

    with pytest.raises(SyncError, match="Could not parse event data"):
        sync_source(MyTrueIntentSource(), store, client)


def test_sync_rolls_back_on_db_error(monkeypatch, tmp_path) -> None:
    """A failed write should keep the snapshot and events unchanged."""

    source = MyTrueIntentSource()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=CSV_DUPLICATE,
            headers={"etag": '"v2"'},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")
    original_upsert = store.upsert

    calls = {"count": 0}

    def failing_upsert(event, *, connection=None, now=None):
        calls["count"] += 1
        if calls["count"] == 2:
            raise SQLAlchemyError("forced write failure")
        return original_upsert(event, connection=connection, now=now)

    monkeypatch.setattr(store, "upsert", failing_upsert)

    with pytest.raises(SyncError, match="Database write failed"):
        sync_source(source, store, client)

    assert calls["count"] == 2
    assert len(store.list_events()) == 0
    assert store.get_snapshot(source.name) is None


def test_duplicate_rows_keep_distinct_ids(tmp_path) -> None:
    """Rows with same semantic values should remain distinct if source records differ."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CSV_DUPLICATE, headers={"etag": '"v1"'})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")

    result = sync_source(MyTrueIntentSource(), store, client)
    events = store.list_events()

    assert result.created == 2
    assert len(events) == 2
    assert len({event.id for event in events}) == 2
