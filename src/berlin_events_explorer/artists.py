"""Local canonical artist catalogue helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
import unicodedata

from berlin_events_explorer.models import ArtistRecord, ArtistStatus
from berlin_events_explorer.storage import EventStore

_PLACEHOLDER_NAMES = {"", "tba", "n/a", "various artists"}
_URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_PROGRAMME_PATTERN = re.compile(
    r"\b(?:festival|programme|program|screening|day\s*\d+|open\s+air)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ArtistCatalogResult:
    """Summary of a canonical artist catalogue bootstrap pass."""

    created: int
    linked: int
    unchanged: int


def normalize_artist_name(value: str) -> str:
    """Normalize a source label for exact, non-fuzzy identity matching."""

    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def classify_artist_label(value: str) -> ArtistStatus:
    """Classify obvious placeholders and URL-only labels without guessing identity."""

    normalized = normalize_artist_name(value)
    if (
        normalized in _PLACEHOLDER_NAMES
        or _URL_PATTERN.search(normalized)
        or _PROGRAMME_PATTERN.search(normalized)
    ):
        return ArtistStatus.NOT_AN_ARTIST
    return ArtistStatus.UNRESOLVED


def bootstrap_artist_catalog(store: EventStore) -> ArtistCatalogResult:
    """Create canonical records and event links from existing source performers."""

    artists_by_normalized_name = {
        artist.normalized_name: artist for artist in store.list_artists()
    }
    events = store.list_events()
    event_artist_ids = store.get_artist_ids_for_event_performers(
        [event.id for event in events]
    )
    created = linked = unchanged = 0

    for event in events:
        for index, performer in enumerate(event.performers, start=1):
            billing_order = performer.billing_order or index
            source_name = performer.name.strip()
            normalized_name = normalize_artist_name(source_name)
            artist = artists_by_normalized_name.get(normalized_name)
            if artist is None:
                artist = store.upsert_artist(
                    ArtistRecord(
                        id=_unique_artist_id(
                            normalized_name, artists_by_normalized_name.values()
                        ),
                        name=source_name or "TBA",
                        normalized_name=normalized_name,
                        status=classify_artist_label(source_name),
                    )
                )
                artists_by_normalized_name[normalized_name] = artist
                created += 1
            elif (
                artist.status is ArtistStatus.UNRESOLVED
                and classify_artist_label(source_name) is ArtistStatus.NOT_AN_ARTIST
            ):
                artist = store.upsert_artist(
                    artist.model_copy(update={"status": ArtistStatus.NOT_AN_ARTIST})
                )
                artists_by_normalized_name[normalized_name] = artist

            link_key = (event.id, billing_order)
            if event_artist_ids.get(link_key) == artist.id:
                unchanged += 1
                continue
            store.link_event_artist(
                event.id,
                billing_order,
                artist.id,
                source_name=source_name,
                role=performer.role,
            )
            event_artist_ids[link_key] = artist.id
            linked += 1

    return ArtistCatalogResult(created=created, linked=linked, unchanged=unchanged)


def _unique_artist_id(normalized_name: str, artists: Iterable[ArtistRecord]) -> str:
    """Return a stable unused route slug for a new canonical artist."""

    existing_ids = {artist.id for artist in artists}
    base_id = _slugify(normalized_name) or "artist"
    artist_id = base_id
    suffix = 2
    while artist_id in existing_ids:
        artist_id = f"{base_id}-{suffix}"
        suffix += 1
    return artist_id


def _slugify(value: str) -> str:
    """Create a conservative ASCII route slug from a normalized source name."""

    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_value)).strip("-")
