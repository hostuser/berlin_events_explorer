"""Tests for automatic enrichment when canonical venues are first created."""

from datetime import UTC, date, datetime

import httpx

from berlin_events_explorer.models import (
    Event,
    EventSourceRef,
    Venue,
    VenueCandidate,
    VenueRecord,
    VenueStatus,
)
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.venue_ingestion import (
    ingest_new_event_venues,
    sync_source_and_ingest_venues,
)


def _event(event_id: str, venue_name: str) -> Event:
    return Event(
        id=event_id,
        source=EventSourceRef(
            provider="test",
            source_url="https://example.test/events.csv",
            source_record_hash=event_id,
        ),
        start_date=date(2026, 8, 1),
        title=f"Event {event_id}",
        venue=Venue(name=venue_name),
    )


def _candidate(venue: VenueRecord, confidence: float) -> VenueCandidate:
    return VenueCandidate(
        venue_id=venue.id,
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/123",
        osm_type="node",
        osm_id="123",
        display_name=f"{venue.name}, Berlin, Germany",
        address="Example Street 1, 10115 Berlin",
        postal_code="10115",
        website="https://example.test/",
        latitude=52.5,
        longitude=13.4,
        confidence=confidence,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


class _Provider:
    def __init__(self, confidence: float) -> None:
        self.confidence = confidence
        self.seen: list[str] = []

    def discover(self, venue: VenueRecord) -> list[VenueCandidate]:
        self.seen.append(venue.id)
        return [_candidate(venue, self.confidence)]


def test_new_venue_is_auto_approved_for_one_high_confidence_candidate(tmp_path) -> None:
    """A newly created venue can bypass the queue when its match is unambiguous."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one", "Example Club"))
    provider = _Provider(0.95)

    result = ingest_new_event_venues(store, provider, auto_approve_threshold=0.9)

    venue = store.get_venue("example-club")
    assert result.created == 1
    assert result.auto_approved == 1
    assert result.awaiting_approval == 0
    assert provider.seen == ["example-club"]
    assert venue is not None
    assert venue.status is VenueStatus.VERIFIED
    assert venue.address == "Example Street 1, 10115 Berlin"


def test_new_venue_with_low_confidence_candidate_enters_approval_queue(
    tmp_path,
) -> None:
    """A new uncertain venue keeps its suggestion for an editor to decide."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one", "Example Club"))
    provider = _Provider(0.8)

    result = ingest_new_event_venues(store, provider, auto_approve_threshold=0.9)

    venue = store.get_venue("example-club")
    assert result.auto_approved == 0
    assert result.awaiting_approval == 1
    assert venue is not None
    assert venue.status is VenueStatus.CANDIDATE
    assert len(store.list_venue_candidates("example-club")) == 1


def test_existing_pending_venue_is_not_auto_approved_on_later_ingestion(
    tmp_path,
) -> None:
    """Only creation triggers automatic discovery and approval."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one", "Example Club"))
    first_provider = _Provider(0.8)
    ingest_new_event_venues(store, first_provider, auto_approve_threshold=0.9)
    store.upsert(_event("two", "Example Club"))
    second_provider = _Provider(1.0)

    result = ingest_new_event_venues(store, second_provider, auto_approve_threshold=0.9)

    venue = store.get_venue("example-club")
    assert result.created == 0
    assert second_provider.seen == []
    assert venue is not None
    assert venue.status is VenueStatus.CANDIDATE


def test_source_sync_enriches_new_venue_in_same_workflow(tmp_path) -> None:
    """The normal source-sync path immediately evaluates a newly seen venue."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.openstreetmap.org":
            return httpx.Response(
                200,
                json=[
                    {
                        "osm_type": "node",
                        "osm_id": 123,
                        "display_name": "Example Club, Berlin, Deutschland",
                        "lat": "52.5",
                        "lon": "13.4",
                        "importance": 0.95,
                        "address": {
                            "road": "Example Street",
                            "house_number": "1",
                            "postcode": "10115",
                            "city": "Berlin",
                            "country_code": "de",
                        },
                    }
                ],
            )
        return httpx.Response(
            200,
            text="Date,Note,Artist,Venue\n01.08.2026,,Artist,Example Club\n",
        )

    store = EventStore(tmp_path / "events.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        sync_result, venue_result = sync_source_and_ingest_venues(
            MyTrueIntentSource(),
            store,
            client,
            auto_approve_threshold=0.9,
        )

    venue = store.get_venue("example-club")
    assert sync_result.created == 1
    assert venue_result.auto_approved == 1
    assert venue is not None
    assert venue.status is VenueStatus.VERIFIED


def test_new_venue_ingestion_reports_each_enrichment_step(tmp_path) -> None:
    """Callers receive a completed/total update while each venue is queried."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("event-1", "First Club"))
    store.upsert(_event("event-2", "Second Club"))
    provider = _Provider(0.5)
    updates: list[tuple[int, int, str | None]] = []

    ingest_new_event_venues(store, provider, progress=updates.append)

    assert updates == [
        (0, 2, "First Club"),
        (1, 2, "Second Club"),
        (2, 2, None),
    ]
