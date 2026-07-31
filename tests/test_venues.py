"""Tests for canonical venue catalog bootstrap."""

from datetime import date

from berlin_events_explorer.models import Event, EventSourceRef, Venue, VenueStatus
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.venues import bootstrap_venue_catalog


def _event(event_id: str, venue_name: str) -> Event:
    """Build a source event containing only a raw venue label."""

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


def test_bootstrap_catalog_creates_one_venue_for_case_variant_labels(tmp_path) -> None:
    """Case and whitespace variants resolve to one deterministic canonical record."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one", "  LArk  "))
    store.upsert(_event("two", "lark"))

    result = bootstrap_venue_catalog(store)

    venues = store.list_venues()
    assert result.created == 1
    assert [venue.id for venue in venues] == ["lark"]
    assert venues[0].status is VenueStatus.UNRESOLVED
    assert store.get_venue_ids_for_events(["one", "two"]) == {
        "one": "lark",
        "two": "lark",
    }


def test_bootstrap_catalog_marks_placeholders_not_a_venue(tmp_path) -> None:
    """Known non-venue labels do not become enrichment candidates."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one", "TBA"))
    store.upsert(_event("two", "Several Locations"))

    bootstrap_venue_catalog(store)

    assert [venue.status for venue in store.list_venues()] == [
        VenueStatus.NOT_A_VENUE,
        VenueStatus.NOT_A_VENUE,
    ]


def test_bootstrap_catalog_is_idempotent(tmp_path) -> None:
    """Running the catalog pass twice creates no duplicate venues or links."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one", "Berghain"))

    first = bootstrap_venue_catalog(store)
    second = bootstrap_venue_catalog(store)

    assert first.created == 1
    assert first.linked == 1
    assert second.created == 0
    assert second.linked == 0
