"""Tests for SQLite event and application-log persistence."""

from datetime import UTC, date, datetime

from berlin_events_explorer.models import (
    ArtistCandidate,
    ArtistRecord,
    ArtistStatus,
    Event,
    EventSourceRef,
    VenueCandidate,
    VenueMetadata,
    VenueRecord,
    VenueStatus,
)
from berlin_events_explorer.storage import EventStore


def test_store_persists_structured_logs_at_supported_levels(tmp_path) -> None:
    """Application diagnostics should retain their level, message, and context."""

    store = EventStore(tmp_path / "events.sqlite")
    store.log(
        level="info",
        event="sync_started",
        message="Starting source synchronization.",
        context={"provider": "mytrueintent"},
    )
    store.log(
        level="debug",
        event="source_response_received",
        message="Received source payload.",
        context={"status_code": 200},
    )

    logs = store.list_logs()

    assert [entry.level for entry in logs] == ["info", "debug"]
    assert logs[0].event == "sync_started"
    assert logs[0].context == {"provider": "mytrueintent"}
    assert logs[1].context == {"status_code": 200}


def _event(event_id: str = "event-1") -> Event:
    """Build an event that can be associated with a canonical venue."""

    return Event(
        id=event_id,
        source=EventSourceRef(
            provider="test",
            source_url="https://example.test",
            source_record_hash=event_id,
        ),
        start_date=date(2026, 8, 1),
        title="Example event",
    )


def _venue() -> VenueRecord:
    """Build an independently stored canonical venue."""

    return VenueRecord(
        id="berghain",
        name="Berghain",
        normalized_name="berghain",
        status=VenueStatus.UNRESOLVED,
    )


def test_store_persists_application_setting(tmp_path) -> None:
    """Web configuration survives reopening the SQLite store."""

    database = tmp_path / "events.sqlite"
    EventStore(database).set_setting("auto_approve_threshold", 0.94)

    assert EventStore(database).get_setting("auto_approve_threshold") == 0.94


def test_clear_application_data_preserves_settings(tmp_path) -> None:
    """A development reset removes content but retains configured settings."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.set_setting("auto_approve_threshold", 0.94)
    store.upsert(_event())
    store.upsert_venue(_venue())
    store.link_event_venue("event-1", "berghain", source_name="Berghain")

    store.clear_application_data()

    assert list(store.list_events()) == []
    assert store.list_venues() == []
    assert store.get_setting("auto_approve_threshold") == 0.94


def test_store_upserts_canonical_venue_and_metadata(tmp_path) -> None:
    """Canonical venue details and per-field provenance survive round trips."""

    store = EventStore(tmp_path / "events.sqlite")
    venue = _venue()

    stored = store.upsert_venue(venue, now=datetime(2026, 7, 30, tzinfo=UTC))
    updated = store.upsert_venue(
        venue.model_copy(
            update={
                "address": "Am Wriezener Bahnhof, 10243 Berlin",
                "status": VenueStatus.VERIFIED,
            }
        ),
        now=datetime(2026, 7, 31, tzinfo=UTC),
    )
    store.save_venue_metadata(
        VenueMetadata(
            venue_id="berghain",
            field="address",
            value="Am Wriezener Bahnhof, 10243 Berlin",
            provider="openstreetmap",
            source_url="https://www.openstreetmap.org/node/1",
            confidence=0.98,
            retrieved_at=datetime(2026, 7, 31, tzinfo=UTC),
        )
    )

    persisted = store.get_venue("berghain")

    assert stored.status is VenueStatus.UNRESOLVED
    assert updated.status is VenueStatus.VERIFIED
    assert persisted is not None
    assert persisted.address == "Am Wriezener Bahnhof, 10243 Berlin"
    assert persisted.status is VenueStatus.VERIFIED
    assert store.list_venue_metadata("berghain")[0].field == "address"


def test_store_links_events_to_canonical_venues_idempotently(tmp_path) -> None:
    """Event-to-venue links retain source spelling without duplicate associations."""

    store = EventStore(tmp_path / "events.sqlite")
    event = _event()
    store.upsert(event)
    store.upsert_venue(_venue())

    store.link_event_venue(event.id, "berghain", source_name="Berghain")
    store.link_event_venue(event.id, "berghain", source_name="Berghain")

    linked_venue = store.get_venue_for_event(event.id)

    assert linked_venue is not None
    assert linked_venue.id == "berghain"
    assert store.get_venue_ids_for_events([event.id]) == {event.id: "berghain"}
    assert [
        stored_event.id for stored_event in store.list_events_for_venue("berghain")
    ] == [event.id]


def test_store_records_and_selects_artist_candidate_atomically(tmp_path) -> None:
    """A selected artist candidate publishes fields and records their provenance."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_artist(
        ArtistRecord(id="die-arzte", name="Die Ärzte", normalized_name="die ärzte")
    )
    candidate = ArtistCandidate(
        artist_id="die-arzte",
        provider="musicbrainz",
        source_url="https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111",
        musicbrainz_id="11111111-1111-1111-1111-111111111111",
        display_name="Die Ärzte",
        artist_type="Group",
        country="DE",
        genres=["punk rock"],
        provider_score=100,
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    store.record_artist_candidates([candidate])
    selected = store.select_artist_candidate(
        "die-arzte", "musicbrainz", candidate.musicbrainz_id
    )

    assert selected.status is ArtistStatus.VERIFIED
    assert selected.musicbrainz_id == candidate.musicbrainz_id
    assert selected.artist_type == "Group"
    assert selected.genres == ["punk rock"]
    assert {metadata.field for metadata in store.list_artist_metadata("die-arzte")} >= {
        "artist_type",
        "country",
        "genres",
    }


def test_store_records_and_explicitly_selects_venue_candidate(tmp_path) -> None:
    """Only explicit candidate selection promotes discovered metadata to public fields."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_venue(_venue())
    candidate = VenueCandidate(
        venue_id="berghain",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/1",
        osm_type="node",
        osm_id="1",
        display_name="Berghain, Berlin",
        address="Am Wriezener Bahnhof, 10243 Berlin",
        postal_code="10243",
        website="https://www.berghain.berlin/",
        latitude=52.5112,
        longitude=13.4437,
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    store.record_venue_candidates([candidate])
    before_selection = store.get_venue("berghain")
    selected = store.select_venue_candidate("berghain", "nominatim", "node", "1")

    assert before_selection is not None
    assert before_selection.address is None
    assert store.list_venue_candidates("berghain") == [candidate]
    assert selected.status is VenueStatus.VERIFIED
    assert selected.website == "https://www.berghain.berlin/"
    assert {metadata.field for metadata in store.list_venue_metadata("berghain")} >= {
        "address",
        "website",
    }


def test_store_selects_venue_candidate_without_coordinates(tmp_path) -> None:
    """Coordinates are optional metadata and must not block candidate approval."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_venue(_venue())
    candidate = VenueCandidate(
        venue_id="berghain",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/1",
        osm_type="node",
        osm_id="1",
        display_name="Berghain, Berlin",
        address="Am Wriezener Bahnhof, 10243 Berlin",
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    store.record_venue_candidates([candidate])

    selected = store.select_venue_candidate("berghain", "nominatim", "node", "1")

    assert selected.status is VenueStatus.VERIFIED
    assert selected.latitude is None
    assert selected.longitude is None


def test_recording_refreshed_candidates_replaces_stale_results(tmp_path) -> None:
    """A provider refresh must remove older duplicate or obsolete candidates."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_venue(_venue())
    first = VenueCandidate(
        venue_id="berghain",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/1",
        osm_type="node",
        osm_id="1",
        display_name="Berghain, Berlin",
        address="Am Wriezener Bahnhof, 10243 Berlin",
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    duplicate = first.model_copy(
        update={
            "source_url": "https://www.openstreetmap.org/node/2",
            "osm_id": "2",
        }
    )
    store.record_venue_candidates([first, duplicate])

    store.record_venue_candidates([first])

    assert store.list_venue_candidates("berghain") == [first]
