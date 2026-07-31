"""Local canonical venue catalog helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from collections.abc import Iterable

from berlin_events_explorer.models import VenueRecord, VenueStatus
from berlin_events_explorer.storage import EventStore

_PLACEHOLDER_NAMES = {"", "tba", "several locations"}


@dataclass(frozen=True)
class VenueCatalogResult:
    """Summary of a canonical venue catalog bootstrap pass."""

    created: int
    linked: int
    unchanged: int


def normalize_venue_name(value: str) -> str:
    """Normalize a source label for exact, non-fuzzy identity matching."""

    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def bootstrap_venue_catalog(store: EventStore) -> VenueCatalogResult:
    """Create canonical records and event links from existing raw event venues."""

    venues_by_normalized_name = {
        venue.normalized_name: venue for venue in store.list_venues()
    }
    events = store.list_events()
    event_venue_ids = store.get_venue_ids_for_events([event.id for event in events])
    created = linked = unchanged = 0

    for event in events:
        if event.venue is None:
            continue
        source_name = event.venue.name.strip()
        normalized_name = normalize_venue_name(source_name)
        venue = venues_by_normalized_name.get(normalized_name)
        if venue is None:
            venue_id = _unique_venue_id(
                normalized_name, venues_by_normalized_name.values()
            )
            status = (
                VenueStatus.NOT_A_VENUE
                if normalized_name in _PLACEHOLDER_NAMES
                else VenueStatus.UNRESOLVED
            )
            venue = store.upsert_venue(
                VenueRecord(
                    id=venue_id,
                    name=source_name or "TBA",
                    normalized_name=normalized_name,
                    status=status,
                )
            )
            venues_by_normalized_name[normalized_name] = venue
            created += 1

        if event_venue_ids.get(event.id) == venue.id:
            unchanged += 1
            continue
        store.link_event_venue(event.id, venue.id, source_name=source_name)
        event_venue_ids[event.id] = venue.id
        linked += 1

    return VenueCatalogResult(created=created, linked=linked, unchanged=unchanged)


def _unique_venue_id(normalized_name: str, venues: Iterable[VenueRecord]) -> str:
    """Return a stable unused route slug for a new canonical venue."""

    existing_ids = {venue.id for venue in venues if isinstance(venue, VenueRecord)}
    base_id = _slugify(normalized_name) or "venue"
    venue_id = base_id
    suffix = 2
    while venue_id in existing_ids:
        venue_id = f"{base_id}-{suffix}"
        suffix += 1
    return venue_id


def _slugify(value: str) -> str:
    """Create a conservative ASCII route slug from a normalized source name."""

    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_value)).strip("-")
