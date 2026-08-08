"""Bounded, source-provenance event-details augmentation.

The initial provider intentionally records only the source page already present in
canonical event provenance. It never guesses ticket URLs or availability; those
require a separately approved provider implementing ``EventDetailsProvider``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from pydantic import ValidationError

from berlin_events_explorer.event_details import EventDetails
from berlin_events_explorer.models import Event
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.ticketmaster import (
    TicketmasterCandidate,
    TicketmasterProviderError,
    match_ticketmaster_candidates,
)

SOURCE_LINKS_PROVIDER = "source-links"
DEFAULT_EVENT_DETAILS_REFRESH = timedelta(days=7)


class TicketmasterCandidateLookup(Protocol):
    """The Discovery client behavior required by the augmentation orchestrator."""

    def find_candidates(self, event: Event) -> list[TicketmasterCandidate]:
        """Return provider candidates for one source event."""
        ...


@dataclass(frozen=True)
class ProviderLookupOutcome:
    """A redacted, reviewable result for one provider lookup."""

    event_id: str
    decision: Literal["matched", "no_match", "provider_error"]
    provider_event_id: str | None = None
    confidence: float | None = None
    rationale: tuple[str, ...] = ()


@dataclass(frozen=True)
class TicketmasterEventDetailsAugmentResult:
    """Summary and review records from a bounded Discovery enrichment pass."""

    considered: int
    matched: int
    updated: int
    outcomes: tuple[ProviderLookupOutcome, ...]


@dataclass(frozen=True)
class EventDetailsAugmentResult:
    """Summary of one bounded source-link observation pass."""

    considered: int
    updated: int


def augment_event_details(
    store: EventStore,
    *,
    limit: int,
    now: datetime | None = None,
    refresh_after: timedelta = DEFAULT_EVENT_DETAILS_REFRESH,
    event_id: str | None = None,
) -> EventDetailsAugmentResult:
    """Persist source URLs for missing/stale events without inventing ticket data."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    now = now or datetime.now(timezone.utc)
    if event_id is not None:
        event = store.get_event(event_id)
        events = [] if event is None else [event]
    else:
        events = store.list_events_needing_event_details(
            SOURCE_LINKS_PROVIDER, checked_before=now - refresh_after, limit=limit
        )
    for event in events:
        store.save_event_details(
            EventDetails(
                event_id=event.id,
                provider=SOURCE_LINKS_PROVIDER,
                event_url=event.source.source_url,
                evidence_url=event.source.source_url,
                confidence=1.0,
                checked_at=now,
                last_successful_at=now,
                details={"source_provider": event.source.provider},
            )
        )
    return EventDetailsAugmentResult(considered=len(events), updated=len(events))


def augment_ticketmaster_event_details(
    store: EventStore,
    client: TicketmasterCandidateLookup,
    *,
    limit: int,
    now: datetime | None = None,
    refresh_after: timedelta = DEFAULT_EVENT_DETAILS_REFRESH,
    dry_run: bool = False,
) -> TicketmasterEventDetailsAugmentResult:
    """Persist only uniquely exact Ticketmaster Discovery matches in a bounded pass."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    now = now or datetime.now(timezone.utc)
    events = store.list_events_needing_event_details(
        "ticketmaster-discovery", checked_before=now - refresh_after, limit=limit
    )
    outcomes: list[ProviderLookupOutcome] = []
    matched = 0
    updated = 0
    for event in events:
        try:
            match = match_ticketmaster_candidates(event, client.find_candidates(event))
        except TicketmasterProviderError:
            outcomes.append(ProviderLookupOutcome(event.id, "provider_error"))
            continue
        if match is None:
            outcomes.append(ProviderLookupOutcome(event.id, "no_match"))
            continue
        matched += 1
        outcome = ProviderLookupOutcome(
            event_id=event.id,
            decision="matched",
            provider_event_id=match.candidate.provider_event_id,
            confidence=match.confidence,
            rationale=match.rationale,
        )
        outcomes.append(outcome)
        if dry_run:
            continue
        try:
            store.save_event_details(
                EventDetails(
                    event_id=event.id,
                    provider="ticketmaster-discovery",
                    event_url=match.candidate.event_url,
                    ticket_url=match.candidate.event_url,
                    evidence_url=match.candidate.event_url,
                    confidence=match.confidence,
                    checked_at=now,
                    last_successful_at=now,
                    details={"provider_event_id": match.candidate.provider_event_id},
                )
            )
        except ValidationError:
            outcomes[-1] = ProviderLookupOutcome(event.id, "no_match")
            matched -= 1
            continue
        updated += 1
    return TicketmasterEventDetailsAugmentResult(
        considered=len(events),
        matched=matched,
        updated=updated,
        outcomes=tuple(outcomes),
    )
