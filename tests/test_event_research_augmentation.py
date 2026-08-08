"""Bounded persistence orchestration for AI-assisted event research."""

from datetime import UTC, date, datetime

from berlin_events_explorer.ai_event_research import EventResearchObservation
from berlin_events_explorer.event_research_augmentation import augment_event_research
from berlin_events_explorer.models import Event, EventSourceRef
from berlin_events_explorer.storage import EventStore


class _Researcher:
    def lookup(self, event: Event, *, now: datetime) -> EventResearchObservation | None:
        return EventResearchObservation(
            event_id=event.id,
            event_url="https://events.example/example-show",
            ticket_url="https://tickets.example/example-show",
            evidence_url="https://events.example/example-show",
            summary="Example Show is listed by the organiser.",
            checked_at=now,
        )


def _event() -> Event:
    return Event(
        id="example-show",
        source=EventSourceRef(
            provider="test-source",
            source_url="https://source.example/events",
            source_record_hash="example-show",
        ),
        title="Example Show",
        start_date=date(2026, 9, 15),
    )


def test_augmentation_persists_a_bounded_research_result(tmp_path) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event())

    result = augment_event_research(
        store,
        _Researcher(),
        limit=1,
        now=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert result.considered == 1
    assert result.matched == 1
    assert result.updated == 1
    assert store.get_event_research("example-show") is not None


def test_dry_run_reports_match_without_writing_research(tmp_path) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event())

    result = augment_event_research(
        store,
        _Researcher(),
        limit=1,
        now=datetime(2026, 8, 2, tzinfo=UTC),
        dry_run=True,
    )

    assert result.matched == 1
    assert result.updated == 0
    assert store.get_event_research("example-show") is None
