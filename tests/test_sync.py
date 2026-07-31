"""End-to-end tests for source synchronization."""

import time

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError
import diskcache

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
CSV_WITH_INVALID_ROW = """Date,Note,Artist,Venue
13.07.2026,,Haevn,Classic Open Air
not-a-date,,Broken source row,Nowhere
15.07.2026,new,New Artist,Schokoladen
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


def test_sync_skips_invalid_source_rows_and_persists_an_error_log(tmp_path) -> None:
    """One malformed row should not prevent valid source rows from syncing."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CSV_WITH_INVALID_ROW)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")

    result = sync_source(MyTrueIntentSource(), store, client)

    assert result.created == 2
    assert result.errors == 1
    assert [event.title for event in store.list_events()] == ["Haevn", "New Artist"]
    logs = store.list_logs()
    assert len(logs) == 1
    assert logs[0].level == "error"
    assert logs[0].event == "source_row_parse_failed"
    assert logs[0].context["source_record_id"] == "3"
    assert logs[0].context["date"] == "not-a-date"


def test_sync_rolls_back_on_db_error(monkeypatch, tmp_path) -> None:
    """A failed write should keep the snapshot and events unchanged."""

    source = MyTrueIntentSource()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=CSV_V1,
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


def test_duplicate_rows_collapse_to_one_semantic_event(tmp_path) -> None:
    """Identical source rows should be represented by one canonical event."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CSV_DUPLICATE, headers={"etag": '"v1"'})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")

    result = sync_source(MyTrueIntentSource(), store, client)
    events = store.list_events()

    assert result.created == 1
    assert len(events) == 1


def test_sync_reconciles_legacy_duplicate_records(tmp_path) -> None:
    """A complete source snapshot should remove legacy IDs no longer emitted."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CSV_V1, headers={"etag": '"v1"'})

    source = MyTrueIntentSource()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")
    legacy_event = (
        source.parse(CSV_V1).events[0].model_copy(update={"id": "legacy-row-based-id"})
    )
    store.upsert(legacy_event)

    result = sync_source(source, store, client)

    assert result.deleted == 1
    assert {event.title for event in store.list_events()} == {
        "Haevn",
        "House Of Protection",
    }
    assert "legacy-row-based-id" not in {event.id for event in store.list_events()}


def test_sync_reconciles_existing_events_when_source_has_invalid_rows(tmp_path) -> None:
    """Skipped bad rows should not prevent reconciliation of a downloaded snapshot."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=CSV_WITH_INVALID_ROW, headers={"etag": '"v1"'})

    source = MyTrueIntentSource()
    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = EventStore(tmp_path / "events.sqlite")
    legacy_event = (
        source.parse(CSV_V1)
        .events[1]
        .model_copy(update={"id": "not-present-in-source"})
    )
    store.upsert(legacy_event)

    result = sync_source(source, store, client)

    assert result.deleted == 1
    assert "not-present-in-source" not in {event.id for event in store.list_events()}


def test_disk_cache_backfills_new_database_on_304(tmp_path) -> None:
    """A fresh database can reconstruct events from disk-cached source payload."""

    source = MyTrueIntentSource()
    cache_path = tmp_path / "sync-cache"

    first_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=CSV_V1, headers={"etag": '"v1"'})
        )
    )
    second_requests: list[httpx.Request] = []

    def second_handler(request: httpx.Request) -> httpx.Response:
        second_requests.append(request)
        return httpx.Response(304, headers={"etag": '"v1"'})

    second_client = httpx.Client(transport=httpx.MockTransport(second_handler))

    with diskcache.Cache(cache_path) as cache:
        try:
            sync_source(
                source,
                EventStore(tmp_path / "first.sqlite"),
                first_client,
                http_cache=cache,
            )

            second_db = EventStore(tmp_path / "second.sqlite")
            result = sync_source(source, second_db, second_client, http_cache=cache)
        finally:
            first_client.close()
            second_client.close()

    assert len(second_requests) == 1
    assert second_requests[0].headers.get("if-none-match") == '"v1"'
    assert result.downloaded is False
    assert result.created == 2
    assert result.updated == 0
    assert result.unchanged == 0
    assert len(second_db.list_events()) == 2
