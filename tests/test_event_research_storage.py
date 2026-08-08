"""Persistence behavior for AI-assisted event research overlays."""

from datetime import UTC, date, datetime

from berlin_events_explorer.ai_event_research import EventResearchObservation
from berlin_events_explorer.models import Event, EventSourceRef
from berlin_events_explorer.storage import EventStore


def _event(event_id: str) -> Event:
    return Event(
        id=event_id,
        source=EventSourceRef(
            provider="test-source",
            source_url="https://source.example/events",
            source_record_hash=event_id,
        ),
        title=f"Event {event_id}",
        start_date=date(2026, 9, 15),
    )


def _research(event_id: str, *, checked_at: datetime) -> EventResearchObservation:
    return EventResearchObservation(
        event_id=event_id,
        event_url=f"https://events.example/{event_id}",
        ticket_url=f"https://tickets.example/{event_id}",
        evidence_url=f"https://events.example/{event_id}",
        summary=f"Event {event_id} is listed by the organiser.",
        checked_at=checked_at,
    )


def test_event_research_round_trips_without_replacing_source_link_details(
    tmp_path,
) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one"))
    research = _research("one", checked_at=datetime(2026, 8, 2, tzinfo=UTC))

    store.save_event_research(research)

    assert store.get_event_research("one") == research


def test_event_research_candidates_include_only_missing_or_stale_events(
    tmp_path,
) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    for event_id in ("missing", "stale", "fresh"):
        store.upsert(_event(event_id))
    store.save_event_research(
        _research("stale", checked_at=datetime(2026, 7, 1, tzinfo=UTC))
    )
    store.save_event_research(
        _research("fresh", checked_at=datetime(2026, 8, 2, tzinfo=UTC))
    )

    events = store.list_events_needing_event_research(
        checked_before=datetime(2026, 8, 1, tzinfo=UTC), limit=10
    )

    assert [event.id for event in events] == ["missing", "stale"]
