"""End-to-end tests for source synchronization."""

from pathlib import Path

import httpx

from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.sync import sync_source


CSV_V1 = """Date,Note,Artist,Venue
13.07.2026,,Haevn,Classic Open Air
14.07.2026,sold out,House Of Protection,Mikropol
"""
CSV_V2 = """Date,Note,Artist,Venue
13.07.2026,,Haevn,Classic Open Air
14.07.2026,cancelled,House Of Protection,Mikropol
15.07.2026,new,New Artist,Schokoladen
"""


def test_first_sync_persists_events_and_audit_log(tmp_path: Path) -> None:
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


def test_unchanged_source_uses_etag_and_skips_parsing(tmp_path: Path) -> None:
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


def test_changed_source_updates_and_creates_audit_entries(tmp_path: Path) -> None:
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
