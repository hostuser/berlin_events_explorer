"""Bounded, operator-invoked orchestration for AI-assisted event research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from berlin_events_explorer.ai_event_research import EventResearchObservation
from berlin_events_explorer.models import Event
from berlin_events_explorer.storage import EventStore

DEFAULT_EVENT_RESEARCH_REFRESH = timedelta(days=7)


class EventResearcher(Protocol):
    """The minimal researched-event lookup interface used by batch orchestration."""

    def lookup(self, event: Event, *, now: datetime) -> EventResearchObservation | None:
        """Return a validated research observation, or no result."""
        ...


@dataclass(frozen=True)
class EventResearchOutcome:
    """A compact, redacted review result for one event."""

    event_id: str
    decision: Literal["matched", "no_match", "provider_error"]
    evidence_url: str | None = None


@dataclass(frozen=True)
class EventResearchAugmentResult:
    """Summary and review outcomes for one bounded research batch."""

    considered: int
    matched: int
    updated: int
    outcomes: tuple[EventResearchOutcome, ...]


def augment_event_research(
    store: EventStore,
    researcher: EventResearcher,
    *,
    limit: int,
    now: datetime | None = None,
    refresh_after: timedelta = DEFAULT_EVENT_RESEARCH_REFRESH,
    dry_run: bool = False,
) -> EventResearchAugmentResult:
    """Research only missing/stale events and persist validated observations."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    now = now or datetime.now(timezone.utc)
    events = store.list_events_needing_event_research(
        checked_before=now - refresh_after, limit=limit
    )
    outcomes: list[EventResearchOutcome] = []
    matched = 0
    updated = 0
    for event in events:
        try:
            research = researcher.lookup(event, now=now)
        except Exception:
            outcomes.append(EventResearchOutcome(event.id, "provider_error"))
            continue
        if research is None:
            outcomes.append(EventResearchOutcome(event.id, "no_match"))
            continue
        matched += 1
        outcomes.append(
            EventResearchOutcome(
                event.id, "matched", evidence_url=research.evidence_url
            )
        )
        if not dry_run:
            store.save_event_research(research)
            updated += 1
    return EventResearchAugmentResult(
        considered=len(events),
        matched=matched,
        updated=updated,
        outcomes=tuple(outcomes),
    )
