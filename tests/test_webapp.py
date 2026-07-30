"""Tests for the Litestar web UI."""

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from litestar.testing import TestClient

from berlin_events_explorer.models import Event, EventSourceRef, Performer, Venue
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.webapp import (
    _paginate_events,
    _recent_events,
    _periodic_sync,
    _render_events_panel,
    _upcoming_events,
    _sse_event,
    _sorted_events,
    create_app,
    render_events_page,
)


def _seed_event() -> Event:
    """Return a representative event used in test data."""

    return Event(
        id="evt-1",
        source=EventSourceRef(
            provider="mytrueintent",
            source_url="https://example.test/events.csv",
            source_record_id="1",
            source_record_hash="hash-1",
        ),
        start_date=date.today() + timedelta(days=1),
        first_seen_at=datetime.now(UTC),
        title="House of Signals",
        performers=[Performer(name="DJ Example", billing_order=1)],
        venue=Venue(name="Example Club"),
        tags=["techno", "house"],
    )


def _seed_events(total: int) -> list[Event]:
    """Return deterministic test events with varied dates and titles."""

    events: list[Event] = []
    for index in range(total):
        events.append(
            _seed_event().model_copy(
                update={
                    "id": f"evt-{index}",
                    "title": f"Event {index:02d}",
                    "start_date": date(2026, 7, 1 + (index % 28)),
                }
            )
        )
    return events


def _render_events_page_from(
    all_events: list[Event], *, total_count: int, page: int, page_size: int
) -> str:
    """Render a page with canonical pagination metadata."""

    sorted_events = _sorted_events(all_events)
    paged_events, current_page, normalized_page_size, total_pages = _paginate_events(
        sorted_events,
        page=page,
        page_size=page_size,
    )
    return render_events_page(
        paged_events,
        total_count=total_count,
        page=current_page,
        page_size=normalized_page_size,
        total_pages=total_pages,
    )


def test_render_events_page_renders_table_rows() -> None:
    """The HTML renderer should include key event fields and Datastar wiring."""

    events = _seed_events(50)
    page = _render_events_page_from(
        events, total_count=len(events), page=1, page_size=25
    )

    assert "Event 00" in page
    assert "Example Club" in page
    assert "DJ Example" in page
    assert "techno, house" in page
    assert "Berlin Events Explorer (" in page
    assert "data-on:click=\"@post('sync?tab=upcoming&recent_days=7')\"" in page
    assert "data-signals" in page
    assert "Page 1 of 2" in page
    assert "?page=2&page_size=25" in page
    assert "Recently added" in page
    assert "Upcoming" in page


def test_render_events_panel_renders_empty_state() -> None:
    """The events panel should show a helpful empty state when no events exist."""

    html = _render_events_panel(
        [],
        total_count=0,
        page=1,
        page_size=50,
        total_pages=1,
    )

    assert "No events have been synced yet." in html
    assert "<table>" in html


def test_recent_events_panel_includes_date_added_column() -> None:
    """The recently added view should show when each event was observed."""

    event = _seed_event().model_copy(
        update={"first_seen_at": datetime(2026, 7, 12, 10, 30, tzinfo=UTC)}
    )
    html = _render_events_panel(
        [event],
        total_count=1,
        page=1,
        page_size=50,
        total_pages=1,
        tab="recent",
    )

    assert "<th>Date added</th>" in html
    assert 'data-label="Date added">2026-07-12</td>' in html


def test_paginate_events_clamps_bad_inputs() -> None:
    """Pagination should normalize bad page and page size values."""

    events = _seed_events(55)
    sorted_events = _sorted_events(events)

    _, page, normalized_size, _ = _paginate_events(
        sorted_events,
        page=0,
        page_size=0,
    )
    assert page == 1
    assert normalized_size == 50

    _, page, normalized_size, total_pages = _paginate_events(
        sorted_events,
        page=999,
        page_size=2000,
    )
    assert page == 1
    assert normalized_size == 200
    assert total_pages == 1


def test_paginate_events_slices_expected_windows() -> None:
    """Pagination should return predictable event windows and total page count."""

    events = _seed_events(55)
    sorted_events = _sorted_events(events)

    paged, page, normalized_size, total_pages = _paginate_events(
        sorted_events,
        page=2,
        page_size=20,
    )

    assert total_pages == 3
    assert page == 2
    assert normalized_size == 20
    assert len(paged) == 20
    assert paged[0].id == sorted_events[20].id
    assert paged[-1].id == sorted_events[39].id


def test_sorted_events_orders_by_date_then_title() -> None:
    """Events should display deterministically by date then case-insensitive title."""

    second = _seed_event().model_copy(update={"id": "evt-2", "title": "A later title"})
    first = _seed_event().model_copy(
        update={"id": "evt-3", "title": "Z title", "start_date": date(2026, 8, 1)}
    )

    sorted_events = _sorted_events([first, second])
    assert sorted_events[0].title == "A later title"
    assert sorted_events[1].title == "Z title"


def test_recent_events_uses_first_seen_at_and_configurable_window() -> None:
    """Recently added events should use storage observation time, not event date."""

    now = datetime.now(UTC)
    recent = _seed_event().model_copy(
        update={"id": "recent", "first_seen_at": now - timedelta(days=2)}
    )
    old = _seed_event().model_copy(
        update={"id": "old", "first_seen_at": now - timedelta(days=10)}
    )

    assert [event.id for event in _recent_events([old, recent], days=7, now=now)] == [
        "recent"
    ]
    assert [event.id for event in _recent_events([old, recent], days=14, now=now)] == [
        "recent",
        "old",
    ]


def test_upcoming_events_excludes_past_and_sorts_from_today() -> None:
    """Upcoming events should omit past dates and be ordered chronologically."""

    yesterday = _seed_event().model_copy(
        update={"id": "past", "start_date": date.today() - timedelta(days=1)}
    )
    tomorrow = _seed_event().model_copy(
        update={"id": "tomorrow", "start_date": date.today() + timedelta(days=1)}
    )
    today = _seed_event().model_copy(update={"id": "today", "start_date": date.today()})

    assert [event.id for event in _upcoming_events([yesterday, tomorrow, today])] == [
        "today",
        "tomorrow",
    ]


def test_webapp_root_route_renders_events(tmp_path) -> None:
    """The web route should return an HTML response with stored events."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    event = _seed_event()
    store.upsert(event)

    app = create_app(database)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.text.count("House of Signals") == 1
    assert "Berlin Events Explorer" in response.text


def test_webapp_root_includes_manual_sync_trigger(tmp_path) -> None:
    """The page should expose an in-place sync trigger handled by Datastar."""

    database = tmp_path / "events.sqlite"
    app = create_app(database)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "data-on:click=\"@post('sync?tab=recent&recent_days=7')\"" in response.text
    assert "Sync now" in response.text


def test_webapp_sync_endpoint_runs_sync_and_returns_datastar_events(
    tmp_path, monkeypatch
) -> None:
    """The in-page sync handler should execute sync logic and return SSE patches."""

    database = tmp_path / "events.sqlite"

    def _fake_sync(store: EventStore) -> None:
        event = _seed_event().model_copy(update={"id": "evt-sync"})
        store.upsert(event)

    monkeypatch.setattr(
        "berlin_events_explorer.webapp.perform_sync",
        _fake_sync,
    )

    app = create_app(database)
    with TestClient(app) as client:
        sync_response = client.post("/sync")

    assert sync_response.status_code == 200
    assert sync_response.headers["content-type"].startswith("text/event-stream")
    assert "datastar-patch-elements" in sync_response.text
    assert "House of Signals" in sync_response.text

    event_lines = sync_response.text.splitlines()
    patch_index = event_lines.index("event: datastar-patch-elements")
    assert event_lines[patch_index + 1].startswith("data: elements <section")
    assert event_lines[patch_index + 2] == ""


@pytest.mark.anyio
async def test_periodic_sync_repeats_until_shutdown(monkeypatch, tmp_path) -> None:
    """The in-process scheduler should run sequential syncs until it is stopped."""

    calls = 0
    completed_two_syncs = asyncio.Event()

    def _fake_sync(_: EventStore) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            completed_two_syncs.set()

    monkeypatch.setattr("berlin_events_explorer.webapp.perform_sync", _fake_sync)
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _periodic_sync(
            store=EventStore(tmp_path / "events.sqlite"),
            interval=timedelta(milliseconds=1),
            stop_event=stop_event,
        )
    )

    await asyncio.wait_for(completed_two_syncs.wait(), timeout=1)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1)

    assert calls >= 2


def test_sse_event_removes_payload_newlines() -> None:
    """SSE patch payloads should be valid Datastar tokens in a single data line."""

    sample_panel = _render_events_panel(
        [_seed_event()],
        total_count=1,
        page=1,
        page_size=50,
        total_pages=1,
    )
    payload = _sse_event("datastar-patch-elements", f"elements {sample_panel}")
    lines = payload.splitlines()

    assert len(lines) == 3
    assert lines[0] == "event: datastar-patch-elements"
    assert lines[1].startswith('data: elements <section id="events-panel">')
    assert lines[2] == ""
