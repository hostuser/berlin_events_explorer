"""Public event detail page behavior."""

from datetime import UTC, date, datetime, timedelta
from threading import Event as ThreadEvent

from litestar.testing import TestClient

from berlin_events_explorer.event_details import EventDetails
from berlin_events_explorer.event_details_augmentation import EventDetailsAugmentResult
import berlin_events_explorer.webapp as webapp
from berlin_events_explorer.models import (
    ArtistMetadata,
    ArtistRecord,
    ArtistStatus,
    Event,
    EventSourceRef,
    EventStatus,
    Performer,
    Venue,
    VenueRecord,
    VenueStatus,
)
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.webapp import create_app, render_events_page


def _event(status: EventStatus = EventStatus.UNKNOWN) -> Event:
    return Event(
        id="event-detail-1",
        source=EventSourceRef(
            provider="test-source",
            source_url="https://source.example/events",
            source_record_hash="event-detail-1",
        ),
        start_date=date(2026, 8, 9),
        title="Example show",
        performers=[Performer(name="Example artist", billing_order=1)],
        venue=Venue(name="Example venue"),
        status=status,
        notes=["Doors 19:00"],
    )


def test_event_listing_titles_link_to_canonical_event_page() -> None:
    html = render_events_page(
        [_event()], total_count=1, page=1, page_size=20, total_pages=1
    )

    assert 'href="/events/event-detail-1">Example show</a>' in html


def test_event_detail_page_renders_safe_ticket_and_event_actions(tmp_path) -> None:
    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert(_event())
    store.save_event_details(
        EventDetails(
            event_id="event-detail-1",
            provider="example",
            event_url="https://events.example/example-show",
            ticket_url="https://tickets.example/example-show",
            observed_status=EventStatus.SOLD_OUT,
            evidence_url="https://events.example/example-show",
            checked_at=datetime.now(UTC),
            status_expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )

    with TestClient(create_app(database)) as client:
        response = client.get("/events/event-detail-1")

    assert response.status_code == 200
    assert "Example show" in response.text
    assert "Sold out" in response.text
    assert 'href="https://tickets.example/example-show"' in response.text
    assert "Get tickets" in response.text
    assert 'target="_blank" rel="noopener noreferrer"' in response.text


def test_event_detail_page_renders_ai_research_with_evidence_link(tmp_path) -> None:
    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert(_event())
    from berlin_events_explorer.ai_event_research import EventResearchObservation

    store.save_event_research(
        EventResearchObservation(
            event_id="event-detail-1",
            event_url="https://events.example/example-show",
            ticket_url="https://tickets.example/example-show",
            evidence_url="https://events.example/example-show",
            summary="Example Show is listed by the organiser.",
            checked_at=datetime(2026, 8, 2, tzinfo=UTC),
        )
    )

    with TestClient(create_app(database)) as client:
        response = client.get("/events/event-detail-1")

    assert response.status_code == 200
    assert "AI-assisted research" in response.text
    assert "Example Show is listed by the organiser." in response.text
    assert 'href="https://events.example/example-show"' in response.text
    assert 'href="https://tickets.example/example-show"' in response.text


def test_unaugmented_event_starts_background_fetch_and_reports_completion(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "events.sqlite"
    EventStore(database).upsert(_event())
    started = ThreadEvent()
    release = ThreadEvent()

    def fake_augment(
        store: EventStore, *, limit: int, event_id: str | None = None
    ) -> EventDetailsAugmentResult:
        assert limit == 1
        assert event_id == "event-detail-1"
        started.set()
        assert release.wait(timeout=2)
        store.save_event_details(
            EventDetails(
                event_id="event-detail-1",
                provider="source-links",
                event_url="https://source.example/events",
                evidence_url="https://source.example/events",
                checked_at=datetime(2026, 8, 2, tzinfo=UTC),
            )
        )
        return EventDetailsAugmentResult(considered=1, updated=1)

    monkeypatch.setattr(webapp, "augment_event_details", fake_augment)
    with TestClient(create_app(database)) as client:
        first_response = client.get("/events/event-detail-1")
        assert started.wait(timeout=2)
        fetching_status = client.get("/events/event-detail-1/augmentation-status")
        release.set()
        for _ in range(20):
            completed_status = client.get("/events/event-detail-1/augmentation-status")
            if completed_status.text == "ready":
                break

        completed_response = client.get("/events/event-detail-1")

    assert "Fetching information" in first_response.text
    assert fetching_status.text == "fetching"
    assert completed_status.text == "ready"
    assert "View event" in completed_response.text


def test_event_detail_page_renders_venue_map_and_verified_artist_music_data(
    tmp_path,
) -> None:
    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert(_event())
    store.upsert_venue(
        VenueRecord(
            id="example-venue",
            name="Example venue",
            normalized_name="example venue",
            status=VenueStatus.VERIFIED,
            latitude=52.520008,
            longitude=13.404954,
        )
    )
    store.link_event_venue(
        "event-detail-1", "example-venue", source_name="Example venue"
    )
    store.upsert_artist(
        ArtistRecord(
            id="example-artist",
            name="Example artist",
            normalized_name="example artist",
            status=ArtistStatus.VERIFIED,
            genres=["Ambient", "Electronic"],
        )
    )
    store.link_event_artist(
        "event-detail-1",
        1,
        "example-artist",
        source_name="Example artist",
    )
    store.save_artist_metadata(
        ArtistMetadata(
            artist_id="example-artist",
            field="official_homepage",
            value="https://example-artist.test/",
            provider="musicbrainz",
            retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
        )
    )
    store.save_artist_metadata(
        ArtistMetadata(
            artist_id="example-artist",
            field="spotify",
            value="https://open.spotify.com/artist/example",
            provider="musicbrainz",
            retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
        )
    )
    store.save_artist_metadata(
        ArtistMetadata(
            artist_id="example-artist",
            field="youtube_music",
            value="https://music.youtube.com/channel/example",
            provider="musicbrainz",
            retrieved_at=datetime(2026, 8, 2, tzinfo=UTC),
        )
    )

    with TestClient(create_app(database)) as client:
        response = client.get("/events/event-detail-1")

    assert response.status_code == 200
    assert 'href="https://example-artist.test/"' in response.text
    assert "Homepage" in response.text
    assert "event-detail-grid" in response.text
    assert "Map showing Example venue" in response.text
    assert "openstreetmap.org/export/embed.html" in response.text
    assert "Ambient, Electronic" in response.text
    assert "<dt>Genres</dt><dd>Ambient, Electronic</dd>" in response.text
    assert 'href="https://open.spotify.com/artist/example"' in response.text
    assert 'href="https://music.youtube.com/channel/example"' in response.text
    assert "Search on YouTube" in response.text

    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        response = client.get("/events/no-such-event")

    assert response.status_code == 404
