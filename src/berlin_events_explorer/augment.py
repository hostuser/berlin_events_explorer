"""Local enrichment pass for persisted events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from berlin_events_explorer.models import EnrichmentResult, Event
from berlin_events_explorer.storage import EventStore


@dataclass(frozen=True)
class AugmentResult:
    """Summary of an augmentation run."""

    processed: int
    updated: int
    unchanged: int


class AugmentError(RuntimeError):
    """Raised when local augmentation cannot complete."""


_TAG_PATTERNS: dict[str, re.Pattern[str]] = {
    "techno": re.compile(r"\btechno\b", re.IGNORECASE),
    "house": re.compile(r"\bhouse\b", re.IGNORECASE),
    "jazz": re.compile(r"\bjazz\b", re.IGNORECASE),
    "rock": re.compile(r"\brock\b", re.IGNORECASE),
    "acoustic": re.compile(r"\bacoustic\b", re.IGNORECASE),
}
_AUGMENTATION_PROVIDER = "local-rule-based-enrichment"


def augment_events(store: EventStore, *, now: datetime | None = None) -> AugmentResult:
    """Run local enrichment rules over all stored events."""

    now = now or datetime.now(timezone.utc)
    events = store.list_events()

    updated = unchanged = 0
    with store.engine.begin() as connection:
        for event in events:
            try:
                enriched = _enrich_event(event, now=now)
            except Exception as exc:
                raise AugmentError(f"Could not enrich event {event.id}") from exc

            if enriched == event:
                unchanged += 1
                continue

            result = store.upsert(enriched, connection=connection, now=now)
            if result.action == "updated":
                updated += 1
            else:
                unchanged += 1

    return AugmentResult(processed=len(events), updated=updated, unchanged=unchanged)


def _enrich_event(event: Event, *, now: datetime) -> Event:
    """Return an enriched copy of ``event`` if any local rules apply."""

    changed_fields: dict[str, object] = {}
    new_enrichments: list[EnrichmentResult] = []

    if event.venue is not None:
        normalized = _normalize_name(event.venue.name)
        if normalized and event.venue.normalized_name != normalized:
            changed_fields["venue"] = event.venue.model_copy(
                update={"normalized_name": normalized}
            )
            if not _has_existing_enrichment(
                event.enrichment,
                _AUGMENTATION_PROVIDER,
                "venue.normalized_name",
                normalized,
            ):
                new_enrichments.append(
                    EnrichmentResult(
                        field="venue.normalized_name",
                        value=normalized,
                        provider=_AUGMENTATION_PROVIDER,
                        confidence=1.0,
                        retrieved_at=now,
                        source_url=event.source.source_url,
                    )
                )

    derived_tags = _derive_tags(event.title, event.notes)
    merged_tags = sorted(set(event.tags).union(derived_tags))
    if merged_tags != event.tags:
        changed_fields["tags"] = merged_tags
        for tag in sorted(set(derived_tags) - set(event.tags)):
            if not _has_existing_enrichment(
                event.enrichment,
                _AUGMENTATION_PROVIDER,
                "tags",
                tag,
            ):
                new_enrichments.append(
                    EnrichmentResult(
                        field="tags",
                        value=tag,
                        provider=_AUGMENTATION_PROVIDER,
                        confidence=0.8,
                        retrieved_at=now,
                        source_url=event.source.source_url,
                    )
                )

    if new_enrichments:
        changed_fields["enrichment"] = [*event.enrichment, *new_enrichments]

    if not changed_fields:
        return event

    return event.model_copy(update=changed_fields)


def _normalize_name(value: str) -> str:
    """Normalize a human-readable venue name with minimal cleanup."""

    return re.sub(r"\s+", " ", value).strip()


def _derive_tags(title: str, notes: list[str]) -> list[str]:
    """Infer tags from title and notes using local text patterns."""

    text = f"{title} {' '.join(notes)}".lower()
    return [tag for tag, pattern in _TAG_PATTERNS.items() if pattern.search(text)]


def _has_existing_enrichment(
    enrichments: list[EnrichmentResult], provider: str, field: str, value: str
) -> bool:
    """Check whether an equivalent enrichment value already exists."""

    return any(
        enrichment.provider == provider
        and enrichment.field == field
        and enrichment.value == value
        for enrichment in enrichments
    )
