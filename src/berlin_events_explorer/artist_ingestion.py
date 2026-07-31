"""Bounded artist discovery and approval orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from berlin_events_explorer.artist_enrichment import (
    ArtistDiscoveryError,
    auto_approval_candidate,
)
from berlin_events_explorer.models import ArtistCandidate, ArtistRecord, ArtistStatus
from berlin_events_explorer.storage import EventStore


class ArtistCandidateProvider(Protocol):
    """Provider capable of proposing metadata for one canonical artist."""

    def discover(
        self, artist: ArtistRecord, *, refresh: bool = False
    ) -> list[ArtistCandidate]: ...


@dataclass(frozen=True)
class ArtistEnrichmentResult:
    """Summary of one bounded artist enrichment pass."""

    checked: int
    auto_approved: int
    queued: int
    no_match: int
    errors: int
    remaining: int


def enrich_artists(
    store: EventStore,
    provider: ArtistCandidateProvider,
    *,
    limit: int = 10,
    auto_approve_threshold: float = 1.0,
    refresh: bool = False,
) -> ArtistEnrichmentResult:
    """Discover candidates for a small batch and queue all non-safe matches."""

    if not 1 <= limit <= 50:
        raise ValueError("artist enrichment limit must be between 1 and 50")
    artists = [
        artist
        for artist in store.list_artists()
        if artist.status is ArtistStatus.UNRESOLVED
        and (refresh or artist.last_checked_at is None)
    ][:limit]
    auto_approved = queued = no_match = errors = 0
    for artist in artists:
        try:
            candidates = provider.discover(artist, refresh=refresh)
        except ArtistDiscoveryError:
            errors += 1
            continue
        if not candidates:
            store.upsert_artist(
                artist.model_copy(update={"last_checked_at": datetime.now(UTC)})
            )
            no_match += 1
            continue
        store.record_artist_candidates(candidates)
        selected = auto_approval_candidate(
            artist, candidates, threshold=auto_approve_threshold
        )
        if selected is not None:
            store.select_artist_candidate(
                artist.id, selected.provider, selected.musicbrainz_id
            )
            auto_approved += 1
        else:
            store.upsert_artist(
                artist.model_copy(update={"status": ArtistStatus.CANDIDATE})
            )
            queued += 1
    remaining = sum(
        artist.status is ArtistStatus.UNRESOLVED
        and (refresh or artist.last_checked_at is None)
        for artist in store.list_artists()
    )
    return ArtistEnrichmentResult(
        checked=len(artists),
        auto_approved=auto_approved,
        queued=queued,
        no_match=no_match,
        errors=errors,
        remaining=remaining,
    )
