"""Persistence tests for independently refreshed event details."""

from datetime import UTC, datetime

from berlin_events_explorer.event_details import EventDetails
from berlin_events_explorer.models import Event, EventSourceRef
from berlin_events_explorer.storage import EventStore


def _event(event_id: str = "event-1") -> Event:
    return Event(
        id=event_id,
        source=EventSourceRef(
            provider="test",
            source_url="https://source.example/events",
            source_record_hash=event_id,
        ),
        title="Example event",
    )


def _details(event_id: str = "event-1") -> EventDetails:
    return EventDetails(
        event_id=event_id,
        provider="source-links",
        event_url="https://source.example/events",
        checked_at=datetime(2026, 8, 2, tzinfo=UTC),
    )


def test_event_details_round_trip_without_modifying_source_payload(tmp_path) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    source_event = _event()
    store.upsert(source_event)

    store.save_event_details(_details())

    assert store.get_event("event-1") == source_event
    assert store.get_event_details("event-1") == _details()


def test_event_details_survive_source_event_resync(tmp_path) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event())
    store.save_event_details(_details())

    store.upsert(_event().model_copy(update={"title": "Corrected event title"}))

    assert store.get_event_details("event-1") == _details()


def test_event_details_candidates_include_missing_and_stale_events(tmp_path) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("missing"))
    store.upsert(_event("stale"))
    store.upsert(_event("fresh"))
    store.save_event_details(
        _details("stale").model_copy(
            update={"checked_at": datetime(2026, 7, 1, tzinfo=UTC)}
        )
    )
    store.save_event_details(_details("fresh"))

    events = store.list_events_needing_event_details(
        "source-links", checked_before=datetime(2026, 8, 1, tzinfo=UTC), limit=10
    )

    assert [event.id for event in events] == ["missing", "stale"]
