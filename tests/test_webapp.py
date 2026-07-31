"""Tests for the Litestar web UI."""

import asyncio
import inspect
import threading
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from diskcache import Cache
from litestar import Response
from litestar.testing import TestClient

from berlin_events_explorer import webapp
from berlin_events_explorer.models import (
    ArtistCandidate,
    ArtistMetadata,
    ArtistRecord,
    ArtistStatus,
    Event,
    EventSourceRef,
    Performer,
    Venue,
    VenueCandidate,
    VenueRecord,
    VenueStatus,
)
from berlin_events_explorer.storage import EventStore, VenueSummary
from berlin_events_explorer.webapp import (
    _get_app_version,
    _events_on_date,
    _get_default_table_size,
    _paginate_events,
    _paginate_venues,
    _recent_events,
    _periodic_sync,
    _render_events_panel,
    _render_venues_content,
    _render_venues_page,
    _upcoming_events,
    _sse_event,
    _sorted_events,
    create_app,
    render_events_page,
)


def _post(client: TestClient, url: str, **kwargs):
    """POST with the double-submit CSRF header for the client's cookie."""

    headers = dict(kwargs.pop("headers", None) or {})
    token = client.cookies.get("csrftoken")
    if token:
        headers["x-csrftoken"] = token
    return client.post(url, headers=headers, **kwargs)


def _login(client: TestClient) -> None:
    """Authenticate a test client as the editor."""

    from conftest import TEST_EDITOR_PASSWORD

    client.get("/login")
    response = _post(
        client,
        "/login",
        data={"password": TEST_EDITOR_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


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
    all_events: list[Event],
    *,
    total_count: int,
    page: int,
    page_size: int,
    artist_ids_by_event_performer: dict[tuple[str, int], str] | None = None,
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
        artist_ids_by_event_performer=artist_ids_by_event_performer,
    )


def test_venue_catalog_matches_event_table_pagination() -> None:
    """Venue pages should use the same table and pagination contract as events."""

    summaries = _seed_venue_summaries(3)
    page = _render_venues_content(summaries, page=2, page_size=2)

    assert 'class="event-table"' in page
    assert 'aria-label="Venue pagination"' in page
    assert "Venue 02" in page
    assert "Venue 00" not in page
    assert "Showing 3 to 3 of 3 venues" in page
    assert "Page 2 of 2" in page
    assert 'href="/?tab=venues&amp;page=1&amp;page_size=2"' in page
    assert 'class="pagination-link disabled" href="#"' in page


def test_paginate_venues_clamps_requested_page() -> None:
    """Venue pagination should clamp pages beyond the available range."""

    summaries = _seed_venue_summaries(3)
    page, current_page, page_size, total_pages = _paginate_venues(
        summaries, page=99, page_size=2
    )

    assert [summary.venue.id for summary in page] == ["venue-2"]
    assert (current_page, page_size, total_pages) == (2, 2, 2)


def test_render_events_page_renders_table_rows() -> None:
    """The HTML renderer should include key event fields and Datastar wiring."""

    events = _seed_events(50)
    page = _render_events_page_from(
        events,
        total_count=len(events),
        page=1,
        page_size=25,
        artist_ids_by_event_performer={("evt-0", 1): "dj-example"},
    )

    assert "Event 00" in page
    assert "Example Club" in page
    assert "DJ Example" in page
    assert 'href="/artists/dj-example"' in page
    assert "techno, house" in page
    assert "Berlin Events Explorer (" in page
    assert (
        "data-on:click=\"@post('sync?page_size=' + $eventPageSize + '&amp;tab='" in page
    )
    assert 'data-bind="eventSearch"' in page
    assert 'data-on:input__debounce_150ms="history.replaceState(' in page
    assert "@get('/events/search?" in page
    assert "requestSubmit" not in page
    assert "data-signals" in page
    assert "Page 1 of 2" in page
    assert "?page=2&page_size=25" in page
    assert "Recently added" in page
    assert "Upcoming" in page
    assert '<a class="date-link" href="/dates/2026-07-01">2026-07-01</a>' in page


def test_event_search_emits_its_sse_response_as_one_chunk(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Search must not make the streaming layer iterate an SSE body character by character."""

    captured: dict[str, object] = {}

    def capture_stream(*, content: object, **_kwargs: object) -> Response:
        captured["content"] = content
        return Response(content="ok", media_type="text/event-stream")

    app = create_app(tmp_path / "events.sqlite")
    monkeypatch.setattr(webapp, "Stream", capture_stream)

    with TestClient(app) as client:
        response = client.get("/events/search?tab=upcoming&search=house&page_size=20")

    assert response.text == "ok"
    assert isinstance(captured["content"], tuple)
    assert len(captured["content"]) == 1
    assert isinstance(captured["content"][0], str)


def test_events_on_date_includes_events_within_a_date_range() -> None:
    """A date view should include single-day and overlapping multi-day events."""

    single_day = _seed_event().model_copy(
        update={"id": "single", "start_date": date(2026, 7, 10)}
    )
    multi_day = _seed_event().model_copy(
        update={
            "id": "multi",
            "start_date": date(2026, 7, 9),
            "end_date": date(2026, 7, 11),
        }
    )
    other_day = _seed_event().model_copy(
        update={"id": "other", "start_date": date(2026, 7, 12)}
    )

    matching = _events_on_date(
        [other_day, multi_day, single_day], target_date=date(2026, 7, 10)
    )

    assert [event.id for event in matching] == ["multi", "single"]


def test_webapp_date_route_lists_only_events_on_requested_date(tmp_path) -> None:
    """The date route should render matching events and link back to the index."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert(
        _seed_event().model_copy(
            update={
                "id": "matching",
                "title": "Matching Event",
                "start_date": date(2026, 7, 10),
            }
        )
    )
    store.upsert(
        _seed_event().model_copy(
            update={
                "id": "earlier",
                "title": "Earlier Event",
                "start_date": date(2026, 7, 9),
            }
        )
    )
    store.upsert(
        _seed_event().model_copy(
            update={
                "id": "other",
                "title": "Other Event",
                "start_date": date(2026, 7, 11),
            }
        )
    )

    with TestClient(create_app(database)) as client:
        response = client.get("/dates/2026-07-10")
        invalid_response = client.get("/dates/not-a-date")

    assert response.status_code == 200
    assert "Events on 2026-07-10" in response.text
    assert "<th>Start date</th>" not in response.text
    assert 'data-label="Start date"' not in response.text
    assert "Matching Event" in response.text
    assert "Earlier Event" not in response.text
    assert "Other Event" not in response.text
    assert 'href="/"' in response.text
    assert invalid_response.status_code == 404


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
    assert '<table class="event-table">' in html


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


def test_event_panel_uses_stable_scroll_viewport_and_footer() -> None:
    """Event rows scroll within a stable viewport and totals share the footer."""

    html = _render_events_panel(
        [_seed_event()],
        total_count=1,
        page=1,
        page_size=20,
        total_pages=1,
        tab="recent",
    )

    assert 'class="table-scroll"' in html
    assert "--table-view-height:57.40rem" in html
    assert '<footer class="table-footer">' in html
    assert html.index("Showing 1 to 1 of 1 events") > html.index("</table>")


def test_recent_filter_control_is_in_the_shared_filter_bar() -> None:
    """The recent timeframe control sits beside, rather than above, event search."""

    html = render_events_page(
        [_seed_event()],
        total_count=1,
        page=1,
        page_size=20,
        total_pages=1,
        tab="recent",
    )

    assert '<form class="filter-side recent-settings"' in html
    assert html.index('class="filter-bar"') < html.index("Added within")
    assert 'id="event-result-count"' not in html


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
    recent_past_event = _seed_event().model_copy(
        update={
            "id": "recent-past-event",
            "first_seen_at": now - timedelta(days=2),
            "start_date": date.today() - timedelta(days=1),
        }
    )

    assert [
        event.id
        for event in _recent_events([old, recent, recent_past_event], days=7, now=now)
    ] == ["recent"]
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


@pytest.mark.parametrize("path", ["/?tab=upcoming", "/?tab=venues", "/?tab=approvals"])
def test_top_level_views_share_application_shell(tmp_path, path: str) -> None:
    """Every top-level tab exposes the persistent controls and tab target."""

    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        _login(client)
        response = client.get(path)

    assert response.status_code == 200
    assert response.text.count('class="sync-button"') == 1
    assert response.text.count('href="/settings"') == 1
    assert response.text.count('id="tab-content"') == 1
    assert response.text.count('id="sync-progress"') == 1
    assert 'data-on:click="evt.preventDefault();' in response.text


@pytest.mark.parametrize("path", ["/?tab=upcoming", "/?tab=venues", "/?tab=approvals"])
def test_datastar_tab_fragments_patch_without_blocking_view_transition(
    tmp_path, path: str
) -> None:
    """Tab actions must leave subsequent tab clicks immediately clickable."""

    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        _login(client)
        response = client.get(
            f"{path}&fragment=1" if "?" in path else f"{path}?fragment=1"
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: datastar-patch-elements" in response.text
    assert "data: selector #tab-content" in response.text
    assert "data: mode outer" in response.text
    assert "data: useViewTransition" not in response.text
    assert 'data: elements <section id="tab-content">' in response.text
    assert "<!doctype html>" not in response.text
    assert response.text.count('id="tab-content"') == 1
    assert "event: datastar-patch-signals" in response.text


def test_event_tab_fragment_patches_the_persistent_event_count(tmp_path) -> None:
    """An in-place event navigation must refresh signals outside tab-content."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert(_seed_event())

    with TestClient(create_app(database)) as client:
        response = client.get("/?tab=upcoming&fragment=1")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: datastar-patch-elements" in response.text
    assert "event: datastar-patch-signals" in response.text
    assert (
        "data: signals {eventCount: 1, isSyncing: false, syncError: null}"
        in response.text
    )


def test_application_navigation_writes_the_canonical_url(tmp_path) -> None:
    """In-place navigation must keep browser history aligned with rendered content."""

    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        response = client.get("/?tab=upcoming&page_size=10")

    assert response.status_code == 200
    assert "history.pushState(null, '', '/?tab=venues&page_size=10')" in response.text
    assert (
        "history.pushState(null, '', '/?tab=approvals&page_size=10')" in response.text
    )
    assert (
        "history.pushState(null, '', '/?tab=recent&recent_days=7&page_size=10')"
        in response.text
    )
    assert (
        "window.addEventListener('popstate', () => window.location.reload())"
        in response.text
    )


def test_event_search_stays_scoped_to_the_active_event_tab(tmp_path) -> None:
    """Switching event tabs should clear the other tab's search term."""

    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        recent_response = client.get("/?tab=recent&search=house&page_size=10")
        upcoming_response = client.get("/?tab=upcoming&search=house&page_size=10")

    assert (
        "history.pushState(null, '', '/?tab=upcoming&recent_days=7&page_size=10')"
        in recent_response.text
    )
    assert (
        "history.pushState(null, '', '/?tab=recent&recent_days=7&page_size=10')"
        in upcoming_response.text
    )
    assert (
        "history.pushState(null, '', '/?tab=upcoming&recent_days=7&page_size=10&search=house')"
        not in recent_response.text
    )
    assert (
        "history.pushState(null, '', '/?tab=recent&recent_days=7&page_size=10&search=house')"
        not in upcoming_response.text
    )


@pytest.mark.parametrize(
    ("legacy_path", "canonical_path"),
    [
        ("/venues", "/?tab=venues"),
        ("/approvals", "/?tab=approvals"),
    ],
)
def test_legacy_top_level_paths_redirect_to_canonical_tab_urls(
    tmp_path, legacy_path: str, canonical_path: str
) -> None:
    """Top-level application views have one canonical root-route URL shape."""

    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        _login(client)
        response = client.get(legacy_path, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == canonical_path


def test_event_pagination_uses_in_place_history_navigation() -> None:
    """Event pagination should patch the tab while exposing its canonical URL."""

    page = _render_events_panel(
        _seed_events(1),
        total_count=2,
        page=1,
        page_size=1,
        total_pages=2,
        tab="upcoming",
    )

    assert (
        "history.pushState(null, '', '/?page=2&page_size=1&tab=upcoming&recent_days=7')"
        in page
    )
    assert "@get('/?page=2&page_size=1&tab=upcoming&recent_days=7&fragment=1')" in page


def test_webapp_root_includes_manual_sync_trigger(tmp_path) -> None:
    """The page should expose an in-place sync trigger handled by Datastar."""

    database = tmp_path / "events.sqlite"
    app = create_app(database)
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert (
        "data-on:click=\"@post('sync?page_size=' + $eventPageSize + '&amp;tab='"
        in response.text
    )
    assert 'data-bind="eventSearch"' in response.text
    assert 'data-on:input__debounce_150ms="history.replaceState(' in response.text
    assert "@get('/events/search?" in response.text
    assert "requestSubmit" not in response.text
    assert "Sync now" in response.text
    assert 'href="/?tab=approvals&amp;page_size=' in response.text
    assert "Awaiting approval" in response.text


def test_webapp_search_endpoint_returns_datastar_event_panel_patch(tmp_path) -> None:
    """Live event search patches the table without replacing the search controls."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert(_seed_event().model_copy(update={"title": "House Signal"}))
    store.upsert(
        _seed_event().model_copy(update={"id": "evt-jazz", "title": "Jazz Signal"})
    )

    with TestClient(create_app(database)) as client:
        response = client.get("/events/search?tab=upcoming&search=house")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: datastar-patch-elements" in response.text
    assert 'data: elements <section id="events-panel">' in response.text
    assert "House Signal" in response.text
    assert "Jazz Signal" not in response.text
    assert (
        "data: signals {eventCount: 1, isSyncing: false, syncError: null}"
        in response.text
    )
    assert 'id="event-filter"' not in response.text
    assert "<!doctype html>" not in response.text


def _seed_pending_venue(store: EventStore) -> VenueCandidate:
    """Persist a pending venue with one reviewable metadata suggestion."""

    store.upsert_venue(
        VenueRecord(
            id="example-club",
            name="Example Club",
            normalized_name="example club",
            status=VenueStatus.CANDIDATE,
        )
    )
    candidate = VenueCandidate(
        venue_id="example-club",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/123",
        osm_type="node",
        osm_id="123",
        display_name="Example Club, Berlin, Germany",
        address="Suggested Street 1, 10115 Berlin",
        postal_code="10115",
        website="https://suggested.example/",
        latitude=52.5,
        longitude=13.4,
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    store.record_venue_candidates([candidate])
    return candidate


def test_approval_queue_lists_unapproved_entities_by_type(tmp_path) -> None:
    """The approval tab shows pending entities and links to type-specific forms."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    _seed_pending_venue(store)

    with TestClient(create_app(database)) as client:
        _login(client)
        response = client.get("/approvals")

    assert response.status_code == 200
    assert "Awaiting approval" in response.text
    assert "Venue" in response.text
    assert "Example Club" in response.text
    assert 'href="/approvals/venues/example-club"' in response.text
    assert "1 suggestion" in response.text


def test_venue_approval_form_offers_suggestion_and_editable_fields(tmp_path) -> None:
    """A venue approval form applies its current editable field values."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    _seed_pending_venue(store)
    upcoming_event = _seed_event().model_copy(
        update={"id": "upcoming-at-example", "title": "Future Signal"}
    )
    past_event = _seed_event().model_copy(
        update={
            "id": "past-at-example",
            "title": "Past Signal",
            "start_date": date.today() - timedelta(days=1),
        }
    )
    store.upsert(upcoming_event)
    store.upsert(past_event)
    store.link_event_venue(
        upcoming_event.id, "example-club", source_name="Example Club"
    )
    store.link_event_venue(past_event.id, "example-club", source_name="Example Club")

    with TestClient(create_app(database)) as client:
        _login(client)
        response = client.get("/approvals/venues/example-club")

    assert response.status_code == 200
    assert 'href="/approvals">← Back to approval queue' in response.text
    assert "Upcoming events (1)" in response.text
    assert "Future Signal" in response.text
    assert "Past Signal" not in response.text
    assert "max-height:23rem" in response.text
    assert "overflow:auto" in response.text
    assert "padding:0 1rem 1rem" in response.text
    assert "position:sticky" in response.text
    assert "Suggested Street 1, 10115 Berlin" in response.text
    assert 'name="address" value="Suggested Street 1, 10115 Berlin"' in response.text
    assert 'name="website" value="https://suggested.example/"' in response.text
    assert response.text.count('name="action" value="approve"') == 1
    assert "Approve suggestion" not in response.text
    assert "Approve edited fields" not in response.text


def test_venue_approval_applies_candidate_filled_form(tmp_path) -> None:
    """The single approval action persists values currently shown in the form."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    _seed_pending_venue(store)

    with TestClient(create_app(database)) as client:
        _login(client)
        response = _post(
            client,
            "/approvals/venues/example-club",
            data={
                "action": "approve",
                "provider": "nominatim",
                "osm_type": "node",
                "osm_id": "123",
                "name": "Example Club",
                "address": "Suggested Street 1, 10115 Berlin",
                "postal_code": "10115",
                "city": "Berlin",
                "country": "DE",
                "website": "https://suggested.example/",
            },
            follow_redirects=False,
        )

    approved = store.get_venue("example-club")
    assert response.status_code == 303
    assert response.headers["location"] == "/approvals"
    assert approved is not None
    assert approved.status is VenueStatus.VERIFIED
    assert approved.address == "Suggested Street 1, 10115 Berlin"
    assert approved.website == "https://suggested.example/"


def test_venue_approval_can_edit_multiple_suggested_fields(tmp_path) -> None:
    """Edited approval validates and persists all reviewer-adjusted fields."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    _seed_pending_venue(store)

    with TestClient(create_app(database)) as client:
        _login(client)
        response = _post(
            client,
            "/approvals/venues/example-club",
            data={
                "action": "approve",
                "provider": "nominatim",
                "osm_type": "node",
                "osm_id": "123",
                "name": "Example Club Berlin",
                "address": "Corrected Road 9, 10999 Berlin",
                "postal_code": "10999",
                "city": "Berlin",
                "country": "DE",
                "website": "https://corrected.example/",
            },
            follow_redirects=False,
        )

    approved = store.get_venue("example-club")
    assert response.status_code == 303
    assert approved is not None
    assert approved.name == "Example Club Berlin"
    assert approved.address == "Corrected Road 9, 10999 Berlin"
    assert approved.postal_code == "10999"
    assert approved.website == "https://corrected.example/"
    assert approved.status is VenueStatus.VERIFIED


def test_venue_approval_rejects_invalid_edits_without_publishing_candidate(
    tmp_path,
) -> None:
    """Validation failure leaves a candidate pending rather than partly approving it."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    _seed_pending_venue(store)

    with TestClient(create_app(database)) as client:
        _login(client)
        response = _post(
            client,
            "/approvals/venues/example-club",
            data={
                "action": "approve",
                "provider": "nominatim",
                "osm_type": "node",
                "osm_id": "123",
                "name": "Example Club",
                "address": "Suggested Street 1, 10115 Berlin",
                "postal_code": "10115",
                "city": "Berlin",
                "country": "DE",
                "website": "javascript:alert(1)",
            },
            follow_redirects=False,
        )

    venue = store.get_venue("example-club")
    assert response.status_code == 400
    assert venue is not None
    assert venue.status is VenueStatus.CANDIDATE
    assert venue.website is None


def test_venue_approval_can_discover_suggestions_on_demand(
    tmp_path, monkeypatch
) -> None:
    """An unresolved venue can request provider suggestions from its review form."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert_venue(
        VenueRecord(
            id="example-club",
            name="Example Club",
            normalized_name="example club",
        )
    )
    suggestion = VenueCandidate(
        venue_id="example-club",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/123",
        osm_type="node",
        osm_id="123",
        display_name="Example Club, Berlin, Germany",
        address="Suggested Street 1, 10115 Berlin",
        postal_code="10115",
        website="https://suggested.example/",
        latitude=52.5,
        longitude=13.4,
        confidence=0.8,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "berlin_events_explorer.webapp.NominatimVenueProvider.discover",
        lambda self, venue: [suggestion],
    )

    with TestClient(create_app(database)) as client:
        _login(client)
        response = _post(
            client, "/approvals/venues/example-club/discover", follow_redirects=False
        )

    venue = store.get_venue("example-club")
    assert response.status_code == 303
    assert response.headers["location"] == "/approvals/venues/example-club"
    assert venue is not None
    assert venue.status is VenueStatus.CANDIDATE
    assert store.list_venue_candidates("example-club") == [suggestion]


def test_approval_refresh_never_auto_approves_high_confidence_suggestion(
    tmp_path, monkeypatch
) -> None:
    """Manual refresh keeps even a high-confidence suggestion in the editorial queue."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert_venue(
        VenueRecord(
            id="example-club",
            name="Example Club",
            normalized_name="example club",
        )
    )
    suggestion = VenueCandidate(
        venue_id="example-club",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/123",
        osm_type="node",
        osm_id="123",
        display_name="Example Club, Berlin, Germany",
        address="Suggested Street 1, 10115 Berlin",
        postal_code="10115",
        website="https://suggested.example/",
        latitude=52.5,
        longitude=13.4,
        confidence=0.95,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "berlin_events_explorer.webapp.NominatimVenueProvider.discover",
        lambda self, venue: [suggestion],
    )

    with TestClient(create_app(database)) as client:
        _login(client)
        response = _post(
            client, "/approvals/venues/example-club/discover", follow_redirects=False
        )

    venue = store.get_venue("example-club")
    assert response.status_code == 303
    assert response.headers["location"] == "/approvals/venues/example-club"
    assert venue is not None
    assert venue.status is VenueStatus.CANDIDATE
    assert venue.address is None
    assert venue.website is None


def test_venue_table_link_and_detail_page_render_verified_metadata(tmp_path) -> None:
    """Associated venue cells lead to a detail page with verified public fields."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    event = _seed_event()
    store.upsert(event)
    store.upsert_venue(
        VenueRecord(
            id="example-club",
            name="Example Club",
            normalized_name="example club",
            address="Example Street 1, 10115 Berlin",
            website="https://example.club/",
            status=VenueStatus.VERIFIED,
        )
    )
    store.link_event_venue(event.id, "example-club", source_name="Example Club")

    app = create_app(database)
    with TestClient(app) as client:
        _login(client)
        index_response = client.get("/?tab=recent")
        detail_response = client.get("/venues/example-club")
        suggestion_response = client.get("/approvals/venues/example-club")

    assert index_response.status_code == 200
    assert 'href="/venues/example-club"' in index_response.text
    assert detail_response.status_code == 200
    assert "Example Street 1, 10115 Berlin" in detail_response.text
    assert 'href="https://example.club/"' in detail_response.text
    assert 'rel="noopener noreferrer"' in detail_response.text
    assert 'class="venue-map"' not in detail_response.text
    assert (
        "<th>Start date</th><th>Title</th><th>Performers</th><th>Tags</th>"
        in detail_response.text
    )
    assert "<th>Venue</th>" not in detail_response.text
    assert 'data-label="Venue"' not in detail_response.text
    assert 'class="date-link" href="/dates/' in detail_response.text
    assert "House of Signals" in detail_response.text
    assert "<ul>" not in detail_response.text
    assert 'href="/approvals/venues/example-club"' in detail_response.text
    assert detail_response.text.count("Find suggestions") == 0
    assert suggestion_response.status_code == 200
    assert "Suggestions" in suggestion_response.text
    assert "Find or refresh suggestions" in suggestion_response.text

    with TestClient(app) as client:
        _login(client)
        edit_response = client.get("/approvals/venues/example-club")
        save_response = _post(
            client,
            "/approvals/venues/example-club",
            data={
                "action": "approve",
                "name": "Example Club Berlin",
                "address": "Corrected Road 9, 10999 Berlin",
                "postal_code": "10999",
                "district": "Neukölln",
                "city": "Berlin",
                "country": "DE",
                "website": "https://corrected.example/",
            },
            follow_redirects=False,
        )

    edited_venue = store.get_venue("example-club")
    assert edit_response.status_code == 200
    assert 'href="/venues/example-club">← Back to venue' in edit_response.text
    assert "Back to approval queue" not in edit_response.text
    assert 'name="address" value="Example Street 1, 10115 Berlin"' in edit_response.text
    assert "Upcoming events (1)" in edit_response.text
    assert "House of Signals" in edit_response.text
    assert save_response.status_code == 303
    assert save_response.headers["location"] == "/venues/example-club"
    assert edited_venue is not None
    assert edited_venue.name == "Example Club Berlin"
    assert edited_venue.district == "Neukölln"


def test_venues_page_lists_districts_event_counts_and_case_insensitive_filter(
    tmp_path,
) -> None:
    """The venue catalog exposes summaries and progressive filter behavior."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    first_event = _seed_event()
    second_event = first_event.model_copy(
        update={
            "id": "evt-2",
            "title": "Second Signal",
            "venue": Venue(name="Example Club"),
        }
    )
    third_event = first_event.model_copy(
        update={
            "id": "evt-3",
            "title": "Third Signal",
            "venue": Venue(name="Lido"),
        }
    )
    past_event = first_event.model_copy(
        update={
            "id": "evt-past",
            "title": "Past Signal",
            "start_date": date.today() - timedelta(days=1),
            "venue": Venue(name="Example Club"),
        }
    )
    store.upsert(first_event)
    store.upsert(second_event)
    store.upsert(third_event)
    store.upsert(past_event)
    store.upsert_venue(
        VenueRecord(
            id="example-club",
            name="Example Club",
            normalized_name="example club",
            district="Kreuzberg",
        )
    )
    store.upsert_venue(
        VenueRecord(
            id="lido",
            name="Lido",
            normalized_name="lido",
            district="Friedrichshain",
        )
    )
    store.upsert_venue(
        VenueRecord(
            id="tba",
            name="TBA",
            normalized_name="tba",
            status=VenueStatus.NOT_A_VENUE,
        )
    )
    store.link_event_venue(first_event.id, "example-club", source_name="Example Club")
    store.link_event_venue(second_event.id, "example-club", source_name="Example Club")
    store.link_event_venue(third_event.id, "lido", source_name="Lido")
    store.link_event_venue(past_event.id, "example-club", source_name="Example Club")

    summaries = {
        summary.venue.id: summary.event_count
        for summary in store.list_venue_summaries()
    }
    assert summaries == {"example-club": 2, "lido": 1}

    with TestClient(create_app(database)) as client:
        response = client.get("/venues")

    assert response.status_code == 200
    assert "Venues" in response.text
    assert "Kreuzberg" in response.text
    assert "Friedrichshain" in response.text
    assert 'data-label="Events">2 events</td>' in response.text
    assert 'data-label="Events">1 event</td>' in response.text
    assert "TBA" not in response.text
    assert 'data-venue-href="/venues/example-club"' in response.text
    assert 'href="/venues/lido"' in response.text
    assert 'id="venue-filter"' in response.text
    assert "data-venue-row" in response.text
    assert 'name="search"' in response.text

    rendered_empty = _render_venues_page([])
    assert "No venues have been synced yet." in rendered_empty


def test_venues_search_filters_before_pagination(tmp_path) -> None:
    """Venue search totals and pages should describe the filtered catalog."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    for index in range(4):
        store.upsert_venue(
            VenueRecord(
                id=f"kantine-{index}",
                name=f"Kantine {index}",
                normalized_name=f"kantine {index}",
            )
        )
    store.upsert_venue(
        VenueRecord(
            id="other",
            name="Other Venue",
            normalized_name="other venue",
        )
    )

    with TestClient(create_app(database)) as client:
        response = client.get("/?tab=venues&search=KANTINE&page_size=2")

    assert response.status_code == 200
    assert "Kantine 0" in response.text
    assert "Kantine 1" in response.text
    assert "Other Venue" not in response.text
    assert "Showing 1 to 2 of 4 venues" in response.text
    assert "Page 1 of 2" in response.text
    assert (
        'href="/?tab=venues&amp;page=2&amp;page_size=2&amp;search=KANTINE"'
        in response.text
    )


def test_venues_search_resets_to_filtered_first_page(tmp_path) -> None:
    """A search submitted from a later page starts at page one of its results."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    for index in range(3):
        store.upsert_venue(
            VenueRecord(
                id=f"venue-{index}",
                name=f"Venue {index}",
                normalized_name=f"venue {index}",
            )
        )
    store.upsert_venue(
        VenueRecord(
            id="target",
            name="Target Venue",
            normalized_name="target venue",
        )
    )

    with TestClient(create_app(database)) as client:
        response = client.get("/?tab=venues&search=target&page=2&page_size=2")

    assert response.status_code == 200
    assert "Target Venue" in response.text
    assert "Showing 1 to 1 of 1 venues" in response.text
    assert "Page 1 of 1" in response.text


def test_venues_filter_has_a_datastar_clear_button(tmp_path) -> None:
    """The venue search can be cleared without manually deleting its text."""

    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        response = client.get("/?tab=venues&search=kantine")

    assert response.status_code == 200
    assert 'id="venue-filter-clear"' in response.text
    assert 'aria-label="Clear filter"' in response.text
    assert "'hidden': $venueSearch.length === 0" in response.text
    assert "$venueSearch = ''; history.replaceState" in response.text
    assert "&amp;fragment=1')" in response.text


def test_venues_tab_uses_the_shared_table_layout_without_catalog_intro() -> None:
    """The venue tab starts at the shared filter height and keeps its footer stable."""

    html = _render_venues_content(_seed_venue_summaries(1), page_size=20)

    assert "Catalog" not in html
    assert "Browse every venue in the catalog" not in html
    assert "--table-view-height:57.40rem" in html
    assert '<footer class="table-footer">' in html
    assert html.index("Showing 1 to 1 of 1 venues") > html.index("</table>")


def test_venue_detail_embeds_openstreetmap_when_coordinates_are_available(
    tmp_path,
) -> None:
    """A venue with verified coordinates displays an accessible interactive map."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert_venue(
        VenueRecord(
            id="example-club",
            name="Example Club",
            normalized_name="example club",
            latitude=52.520008,
            longitude=13.404954,
            status=VenueStatus.VERIFIED,
        )
    )

    with TestClient(create_app(database)) as client:
        response = client.get("/venues/example-club")

    assert response.status_code == 200
    assert 'class="venue-map"' in response.text
    assert 'title="Map showing Example Club"' in response.text
    assert "https://www.openstreetmap.org/export/embed.html?" in response.text
    assert "marker=52.520008%2C13.404954" in response.text
    assert (
        'href="https://www.openstreetmap.org/?mlat=52.520008&amp;mlon=13.404954'
        in response.text
    )


def test_settings_page_updates_auto_approval_threshold(tmp_path) -> None:
    """The settings page persists validated values for future syncs."""

    database = tmp_path / "events.sqlite"
    app = create_app(database, auto_approve_threshold=0.9)
    with TestClient(app) as client:
        _login(client)
        index_response = client.get("/")
        settings_response = client.get("/settings")
        save_response = _post(
            client,
            "/settings",
            data={
                "auto_approve_threshold": "0.94",
                "musicbrainz_request_interval_seconds": "1.5",
                "musicbrainz_fetch_limit": "37",
                "musicbrainz_metadata_fetch_limit": "41",
            },
            follow_redirects=False,
        )

    assert 'href="/settings"' in index_response.text
    assert 'value="0.9"' in settings_response.text
    assert 'name="musicbrainz_fetch_limit"' in settings_response.text
    assert 'name="musicbrainz_metadata_fetch_limit"' in settings_response.text
    assert 'min="1" max="10000"' in settings_response.text
    assert f"<strong>Version:</strong> {_get_app_version()}" in settings_response.text
    assert save_response.status_code == 303
    assert save_response.headers["location"] == "/settings?saved=1"
    assert EventStore(database).get_setting("auto_approve_threshold") == 0.94
    assert (
        EventStore(database).get_setting("musicbrainz_request_interval_seconds") == 1.5
    )
    assert EventStore(database).get_setting("musicbrainz_fetch_limit") == 37
    assert EventStore(database).get_setting("musicbrainz_metadata_fetch_limit") == 41


def test_development_settings_default_musicbrainz_fetch_limit_is_200(tmp_path) -> None:
    """Development settings use the shared 200-fetch default."""

    database = tmp_path / "events.sqlite"
    with TestClient(create_app(database, environment="development")) as client:
        _login(client)
        response = client.get("/settings")

    assert 'name="musicbrainz_fetch_limit"' in response.text
    assert 'value="200"' in response.text
    assert EventStore(database).get_setting("musicbrainz_fetch_limit") == 200
    assert EventStore(database).get_setting("musicbrainz_metadata_fetch_limit") == 200


def test_settings_page_rejects_musicbrainz_metadata_fetch_limit_outside_batch_range(
    tmp_path,
) -> None:
    """Unsafe metadata batch sizes are rejected without changing saved settings."""

    database = tmp_path / "events.sqlite"
    with TestClient(create_app(database)) as client:
        _login(client)
        response = _post(
            client,
            "/settings",
            data={
                "auto_approve_threshold": "0.9",
                "musicbrainz_request_interval_seconds": "1.1",
                "musicbrainz_fetch_limit": "200",
                "musicbrainz_metadata_fetch_limit": "10001",
            },
        )

    assert response.status_code == 400
    assert "fetch count must be 1–10000" in response.text
    assert EventStore(database).get_setting("musicbrainz_metadata_fetch_limit") == 200


def test_settings_page_rejects_musicbrainz_fetch_limit_outside_batch_range(
    tmp_path,
) -> None:
    """Unsafe MusicBrainz batch sizes are rejected without changing saved settings."""

    database = tmp_path / "events.sqlite"
    with TestClient(create_app(database)) as client:
        _login(client)
        response = _post(
            client,
            "/settings",
            data={
                "auto_approve_threshold": "0.9",
                "musicbrainz_request_interval_seconds": "1.1",
                "musicbrainz_fetch_limit": "10001",
            },
        )

    assert response.status_code == 400
    assert "fetch count must be 1–10000" in response.text
    assert EventStore(database).get_setting("musicbrainz_fetch_limit") == 200


def test_settings_page_rejects_threshold_outside_probability_range(tmp_path) -> None:
    """Invalid confidence thresholds are explained without replacing the setting."""

    database = tmp_path / "events.sqlite"
    with TestClient(create_app(database)) as client:
        _login(client)
        response = _post(client, "/settings", data={"auto_approve_threshold": "1.5"})

    assert response.status_code == 400
    assert "between 0 and 1" in response.text
    assert EventStore(database).get_setting("auto_approve_threshold") == 0.9


def test_app_version_prefers_exact_git_tag(monkeypatch) -> None:
    """Tagged checkouts should display the release tag over stale metadata."""

    monkeypatch.setattr(
        "berlin_events_explorer.webapp._run_git",
        lambda *args: "0.0.4" if args[0] == "describe" else "ignored",
    )

    assert _get_app_version() == "0.0.4"


def test_app_version_uses_commit_for_untagged_checkout(monkeypatch) -> None:
    """Untagged checkouts should identify the running commit."""

    monkeypatch.setattr(
        "berlin_events_explorer.webapp._run_git",
        lambda *args: None if args[0] == "describe" else "864f5f8bcf87",
    )

    assert _get_app_version() == "git:864f5f8bcf87"


def test_manual_sync_uses_threshold_saved_in_settings(tmp_path, monkeypatch) -> None:
    """A saved threshold takes effect on the next sync without restarting the app."""

    received: list[float] = []

    def _fake_sync(
        store: EventStore,
        *,
        auto_approve_threshold: float = 0.9,
        progress=None,
    ) -> None:
        received.append(auto_approve_threshold)

    monkeypatch.setattr("berlin_events_explorer.webapp.perform_sync", _fake_sync)
    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        _login(client)
        _post(client, "/settings", data={"auto_approve_threshold": "0.96"})
        response = _post(client, "/sync")

    assert response.status_code == 200
    assert received == [0.96]


def test_development_settings_can_clear_content_but_preserve_threshold(
    tmp_path,
) -> None:
    """The development-only reset empties content and keeps app configuration."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert(_seed_event())
    app = create_app(database, environment="development")
    with TestClient(app) as client:
        _login(client)
        settings_response = client.get("/settings")
        reset_response = _post(
            client, "/settings/clear-database", follow_redirects=False
        )

    assert "Clear development database" in settings_response.text
    assert reset_response.status_code == 303
    assert reset_response.headers["location"] == "/settings?cleared=1"
    assert list(store.list_events()) == []
    assert store.get_setting("auto_approve_threshold") == 0.9


def test_production_settings_do_not_expose_database_reset(tmp_path) -> None:
    """Production hides and rejects the destructive development reset action."""

    app = create_app(tmp_path / "events.sqlite", environment="production")
    with TestClient(app) as client:
        _login(client)
        settings_response = client.get("/settings")
        reset_response = _post(
            client, "/settings/clear-database", follow_redirects=False
        )

    assert "Clear development database" not in settings_response.text
    assert reset_response.status_code == 404


def test_webapp_sync_endpoint_runs_sync_and_returns_datastar_events(
    tmp_path, monkeypatch
) -> None:
    """The in-page sync handler should execute sync logic and return SSE patches."""

    database = tmp_path / "events.sqlite"

    def _fake_sync(
        store: EventStore,
        *,
        auto_approve_threshold: float = 0.9,
        progress=None,
    ) -> None:
        event = _seed_event().model_copy(update={"id": "evt-sync"})
        store.upsert(event)

    monkeypatch.setattr(
        "berlin_events_explorer.webapp.perform_sync",
        _fake_sync,
    )

    app = create_app(database)
    with TestClient(app) as client:
        _login(client)
        sync_response = _post(client, "/sync")

    assert sync_response.status_code == 200
    assert sync_response.headers["content-type"].startswith("text/event-stream")
    assert "datastar-patch-elements" in sync_response.text
    assert "House of Signals" in sync_response.text

    event_lines = sync_response.text.splitlines()
    patch_index = event_lines.index("event: datastar-patch-elements")
    assert event_lines[patch_index + 1].startswith("data: elements <section")
    assert event_lines[patch_index + 2] == ""


def test_webapp_sync_endpoint_streams_venue_enrichment_progress(
    tmp_path, monkeypatch
) -> None:
    """The manual sync stream reports venue lookup progress before completion."""

    database = tmp_path / "events.sqlite"

    def _fake_sync(
        store: EventStore,
        *,
        auto_approve_threshold: float = 0.9,
        progress=None,
    ) -> None:
        assert progress is not None
        progress((0, 2, "Berghain"))
        progress((1, 2, "Lido"))
        progress((2, 2, None))

    monkeypatch.setattr("berlin_events_explorer.webapp.perform_sync", _fake_sync)

    with TestClient(create_app(database)) as client:
        _login(client)
        response = _post(client, "/sync")

    assert "Enriching venues (0 of 2): Berghain" in response.text
    assert "Enriching venues (1 of 2): Lido" in response.text
    assert 'value="1" max="2"' in response.text
    assert "Venue enrichment complete (2 of 2)" in response.text


def test_artist_approval_queue_and_verified_public_artist_page(
    tmp_path, monkeypatch
) -> None:
    """Artists can be reviewed separately and only verified records get public pages."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert_artist(
        ArtistRecord(
            id="die-arzte",
            name="Die Ärzte",
            normalized_name="die ärzte",
            status=ArtistStatus.CANDIDATE,
        )
    )
    candidate = ArtistCandidate(
        artist_id="die-arzte",
        provider="musicbrainz",
        source_url="https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111",
        musicbrainz_id="11111111-1111-1111-1111-111111111111",
        display_name="Die Ärzte",
        artist_type="Group",
        country="DE",
        provider_score=100,
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    store.record_artist_candidates([candidate])
    store.save_artist_metadata(
        ArtistMetadata(
            artist_id="die-arzte",
            field="official_homepage",
            value="https://www.bademeister.com/",
            provider="musicbrainz",
            source_url=candidate.source_url,
            confidence=1.0,
            retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
        )
    )
    for field, value in (
        ("spotify", "https://open.spotify.com/artist/abc123"),
        ("youtube_music", "https://music.youtube.com/channel/UC123"),
    ):
        store.save_artist_metadata(
            ArtistMetadata(
                artist_id="die-arzte",
                field=field,
                value=value,
                provider="musicbrainz",
                source_url=candidate.source_url,
                confidence=1.0,
                retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
        )

    with TestClient(create_app(database)) as client:
        _login(client)
        queue = client.get("/approvals?entity_type=artists")
        form = client.get("/approvals/artists/die-arzte")
        public_before = client.get("/artists/die-arzte")
        approved = _post(
            client,
            "/approvals/artists/die-arzte",
            data={"candidate": candidate.musicbrainz_id},
            follow_redirects=False,
        )
        public_after = client.get("/artists/die-arzte")
        suggestion_response = client.get("/approvals/artists/die-arzte")

    assert queue.status_code == 200
    assert "Artists" in queue.text
    assert 'href="/approvals/artists/die-arzte"' in queue.text
    assert form.status_code == 200
    assert "MusicBrainz" in form.text
    assert public_before.status_code == 404
    assert approved.status_code == 303
    assert public_after.status_code == 200
    assert "Die Ärzte" in public_after.text
    assert "https://www.bademeister.com/" in public_after.text
    assert 'href="https://open.spotify.com/artist/abc123"' in public_after.text
    assert 'href="https://music.youtube.com/channel/UC123"' in public_after.text
    assert (
        'href="https://www.youtube.com/results?search_query=Die+%C3%84rzte"'
        in public_after.text
    )
    assert 'href="/approvals/artists/die-arzte"' in public_after.text
    assert public_after.text.count("Find suggestions") == 0
    assert suggestion_response.status_code == 200
    assert (
        "Choose a suggestion if needed, edit the public fields"
        in suggestion_response.text
    )
    assert "Find or refresh suggestions" in suggestion_response.text

    with TestClient(create_app(database)) as client:
        _login(client)
        edit_response = client.get("/approvals/artists/die-arzte")
        save_response = _post(
            client,
            "/approvals/artists/die-arzte",
            data={
                "candidate": candidate.musicbrainz_id,
                "name": "Die Ärzte Berlin",
                "artist_type": "Group",
                "country": "DE",
                "disambiguation": "German punk band",
                "genres": "punk, rock",
                "official_homepage": "https://www.bademeister.com/",
            },
            follow_redirects=False,
        )

    edited_artist = EventStore(database).get_artist("die-arzte")
    assert edit_response.status_code == 200
    assert 'name="genres"' in edit_response.text
    assert save_response.status_code == 303
    assert save_response.headers["location"] == "/artists/die-arzte"
    assert edited_artist is not None
    assert edited_artist.name == "Die Ärzte Berlin"
    assert edited_artist.genres == ["punk", "rock"]

    monkeypatch.setattr(
        "berlin_events_explorer.webapp.MusicBrainzArtistProvider.discover",
        lambda self, artist: [candidate],
    )
    with TestClient(create_app(database)) as client:
        _login(client)
        suggestion_response = _post(
            client, "/approvals/artists/die-arzte/discover", follow_redirects=False
        )

    refreshed_artist = EventStore(database).get_artist("die-arzte")
    assert suggestion_response.status_code == 303
    assert suggestion_response.headers["location"] == "/approvals/artists/die-arzte"
    assert refreshed_artist is not None
    assert refreshed_artist.status is ArtistStatus.VERIFIED


@pytest.mark.anyio
async def test_periodic_sync_repeats_until_shutdown(monkeypatch, tmp_path) -> None:
    """The in-process scheduler should run sequential syncs until it is stopped."""

    calls = 0
    completed_two_syncs = asyncio.Event()

    def _fake_sync(_: EventStore, *, auto_approve_threshold: float = 0.9) -> None:
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


def _seed_venue_summaries(total: int) -> list[VenueSummary]:
    """Return deterministic venue summaries for table-size tests."""

    summaries: list[VenueSummary] = []
    for index in range(total):
        venue = VenueRecord(
            id=f"venue-{index}",
            name=f"Venue {index:02d}",
            normalized_name=f"venue {index:02d}",
            district="Mitte",
            status=VenueStatus.VERIFIED,
        )
        summaries.append(VenueSummary(venue=venue, event_count=index + 1))
    return summaries


def test_render_venues_page_limits_rows_to_table_size() -> None:
    """The venues table should only render rows up to the configured table size."""

    summaries = _seed_venue_summaries(50)
    html = _render_venues_page(summaries, table_size=10)

    assert "Venue 09" in html
    assert "Venue 10" not in html
    assert "Showing 1 to 10 of 50 venues" in html


def test_render_venues_page_shows_all_when_under_limit() -> None:
    """No truncation text should appear when venues fit within the table size."""

    summaries = _seed_venue_summaries(5)
    html = _render_venues_page(summaries, table_size=20)

    assert "Venue 04" in html
    assert "Showing 1 to 5 of 5 venues" in html


def test_index_route_uses_default_table_size_setting(tmp_path) -> None:
    """The index route should paginate with the configured default_table_size."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    for index in range(50):
        store.upsert(
            _seed_event().model_copy(
                update={
                    "id": f"evt-{index}",
                    "title": f"Event {index:02d}",
                    "start_date": date.today() + timedelta(days=index + 1),
                }
            )
        )
    store.set_setting("default_table_size", 5)
    app = create_app(database, sync_interval=None, environment="development")
    client = TestClient(app)

    response = client.get("/?tab=upcoming")

    assert response.status_code == 200
    assert "Event 04" in response.text
    assert "Event 05" not in response.text


def test_index_route_page_size_param_overrides_setting(tmp_path) -> None:
    """An explicit page_size query param should override the stored setting."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    for index in range(50):
        store.upsert(
            _seed_event().model_copy(
                update={
                    "id": f"evt-{index}",
                    "title": f"Event {index:02d}",
                    "start_date": date.today() + timedelta(days=index + 1),
                }
            )
        )
    store.set_setting("default_table_size", 5)
    app = create_app(database, sync_interval=None, environment="development")
    client = TestClient(app)

    response = client.get("/?tab=upcoming&page_size=10")

    assert response.status_code == 200
    assert "Event 09" in response.text
    assert "Event 10" not in response.text


def test_venues_route_uses_default_table_size_setting(tmp_path) -> None:
    """The venues route should limit rows to the configured default_table_size."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    for index in range(30):
        store.upsert_venue(
            VenueRecord(
                id=f"venue-{index}",
                name=f"Venue {index:02d}",
                normalized_name=f"venue {index:02d}",
                district="Mitte",
                status=VenueStatus.VERIFIED,
            )
        )
    store.set_setting("default_table_size", 3)
    app = create_app(database, sync_interval=None, environment="development")
    client = TestClient(app)

    response = client.get("/venues")

    assert response.status_code == 200
    assert "Venue 02" in response.text
    assert "Venue 03" not in response.text
    assert "Showing 1 to 3 of 30 venues" in response.text


def test_settings_page_includes_default_table_size(tmp_path) -> None:
    """The settings form should include the default table size field with the current value."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.set_setting("default_table_size", 15)
    app = create_app(database, sync_interval=None, environment="development")
    client = TestClient(app)
    _login(client)

    response = client.get("/settings")

    assert response.status_code == 200
    assert "default_table_size" in response.text
    assert 'value="15"' in response.text


def test_save_settings_persists_default_table_size(tmp_path) -> None:
    """Saving settings should persist the default table size value."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    app = create_app(database, sync_interval=None, environment="development")
    client = TestClient(app)
    _login(client)

    response = _post(
        client,
        "/settings",
        data={
            "auto_approve_threshold": "0.9",
            "musicbrainz_request_interval_seconds": "1.5",
            "musicbrainz_fetch_limit": "10",
            "musicbrainz_metadata_fetch_limit": "10",
            "default_table_size": "25",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert store.get_setting("default_table_size") == 25


def test_create_app_initializes_default_table_size(tmp_path) -> None:
    """create_app should seed the default_table_size setting on first run."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    create_app(database, sync_interval=None, environment="development")

    assert store.get_setting("default_table_size") == 20


def test_get_default_table_size_falls_back_to_default(tmp_path) -> None:
    """_get_default_table_size should return the default when unset or invalid."""

    store = EventStore(tmp_path / "events.sqlite")
    assert _get_default_table_size(store) == 20

    store.set_setting("default_table_size", "invalid")  # type: ignore[arg-type]
    assert _get_default_table_size(store) == 20

    store.set_setting("default_table_size", 0)
    assert _get_default_table_size(store) == 20


def test_perform_sync_refuses_concurrent_runs(tmp_path, monkeypatch) -> None:
    """A second sync attempt while one is running should fail fast."""

    started = threading.Event()
    release = threading.Event()

    def fake_ingest(*_args, **_kwargs):
        started.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(webapp, "sync_source_and_ingest_venues", fake_ingest)
    monkeypatch.setattr(
        webapp, "open_sync_cache", lambda *a, **k: Cache(str(tmp_path / "cache"))
    )
    store = EventStore(tmp_path / "events.sqlite")
    worker = threading.Thread(target=webapp.perform_sync, args=(store,), daemon=True)
    worker.start()
    try:
        assert started.wait(timeout=5)
        with pytest.raises(webapp.SyncInProgressError):
            webapp.perform_sync(store)
    finally:
        release.set()
        worker.join(timeout=5)


def test_sync_endpoint_reports_sync_already_running(tmp_path, monkeypatch) -> None:
    """The manual sync stream should surface an active sync as a plain notice."""

    def _busy_sync(*_args, **_kwargs):
        raise webapp.SyncInProgressError("A sync is already in progress.")

    monkeypatch.setattr("berlin_events_explorer.webapp.perform_sync", _busy_sync)
    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        _login(client)
        response = _post(client, "/sync")

    assert response.status_code == 200
    assert "already in progress" in response.text


def test_only_pure_handlers_run_on_the_event_loop(tmp_path) -> None:
    """Handlers doing database or subprocess work must run in the thread pool."""

    app = create_app(tmp_path / "events.sqlite", sync_interval=None)
    pure_handlers = {"health", "login_page"}
    offenders = sorted(
        {
            fn.__name__
            for route in app.routes
            for handler in getattr(route, "route_handlers", [])
            if (fn := getattr(handler.fn, "func", handler.fn)).__module__
            == "berlin_events_explorer.webapp"
            and not inspect.iscoroutinefunction(fn)
            and getattr(handler, "sync_to_thread", None) is not True
            and fn.__name__ not in pure_handlers
        }
    )
    assert offenders == []


def test_slow_settings_render_does_not_block_other_requests(
    tmp_path, monkeypatch
) -> None:
    """A stalled worker-thread handler must not stop the event loop serving /health."""

    def slow_render(**_kwargs: object) -> str:
        time.sleep(1.0)
        return "settings"

    monkeypatch.setattr(webapp, "_render_settings_page", slow_render)
    app = create_app(tmp_path / "events.sqlite", sync_interval=None)
    with TestClient(app) as client:
        _login(client)
        started_slow = threading.Event()

        def fetch_settings() -> None:
            started_slow.set()
            client.get("/settings")

        worker = threading.Thread(target=fetch_settings, daemon=True)
        worker.start()
        assert started_slow.wait(timeout=5)
        time.sleep(0.2)
        started = time.perf_counter()
        assert client.get("/health").status_code == 200
        elapsed = time.perf_counter() - started
        worker.join(timeout=5)
    assert elapsed < 0.6, f"/health took {elapsed:.2f}s while /settings was busy"


def test_slow_venue_approval_post_does_not_block_other_requests(
    tmp_path, monkeypatch
) -> None:
    """Form-handling approval endpoints must not do blocking work on the loop."""

    def slow_approve(*_args: object, **_kwargs: object) -> None:
        time.sleep(1.0)
        raise ValueError("slow approval")

    monkeypatch.setattr(webapp, "_approve_edited_venue", slow_approve)
    database = tmp_path / "events.sqlite"
    EventStore(database).upsert_venue(
        VenueRecord(id="berghain", name="Berghain", normalized_name="berghain")
    )
    app = create_app(database, sync_interval=None)
    with TestClient(app) as client:
        _login(client)
        started_slow = threading.Event()

        def post_approval() -> None:
            started_slow.set()
            _post(
                client,
                "/approvals/venues/berghain",
                data={"action": "approve", "name": "Berghain"},
            )

        worker = threading.Thread(target=post_approval, daemon=True)
        worker.start()
        assert started_slow.wait(timeout=5)
        time.sleep(0.2)
        started = time.perf_counter()
        assert client.get("/health").status_code == 200
        elapsed = time.perf_counter() - started
        worker.join(timeout=5)
    assert elapsed < 0.6, f"/health took {elapsed:.2f}s while approval was busy"


def test_settings_page_uses_cached_app_version(tmp_path, monkeypatch) -> None:
    """The settings page must not shell out to git on every request."""

    calls = {"count": 0}

    def counting_git(*_args: str) -> str:
        calls["count"] += 1
        return "0.0.7"

    monkeypatch.setattr(webapp, "_run_git", counting_git)
    webapp._cached_app_version.cache_clear()
    try:
        with TestClient(create_app(tmp_path / "events.sqlite")) as client:
            _login(client)
            assert client.get("/settings").status_code == 200
            first_calls = calls["count"]
            assert client.get("/settings").status_code == 200
        assert first_calls > 0
        assert calls["count"] == first_calls
    finally:
        webapp._cached_app_version.cache_clear()


def test_approvals_tab_avoids_per_row_candidate_queries(tmp_path, monkeypatch) -> None:
    """The approval queue must not run one candidate query per pending row."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    for index in range(3):
        store.upsert_venue(
            VenueRecord(
                id=f"venue-{index}",
                name=f"Venue {index}",
                normalized_name=f"venue {index}",
            )
        )
    per_row_calls: list[str] = []
    original_venue = EventStore.list_venue_candidates
    original_artist = EventStore.list_artist_candidates
    monkeypatch.setattr(
        EventStore,
        "list_venue_candidates",
        lambda self, venue_id: (
            per_row_calls.append(venue_id) or original_venue(self, venue_id)
        ),
    )
    monkeypatch.setattr(
        EventStore,
        "list_artist_candidates",
        lambda self, artist_id: (
            per_row_calls.append(artist_id) or original_artist(self, artist_id)
        ),
    )

    with TestClient(create_app(database, sync_interval=None)) as client:
        _login(client)
        response = client.get("/?tab=approvals")

    assert response.status_code == 200
    assert "Venue 0" in response.text
    assert per_row_calls == []
