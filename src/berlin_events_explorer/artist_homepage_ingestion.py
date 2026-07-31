"""Bounded official-homepage enrichment for verified artists."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from berlin_events_explorer.artist_enrichment import ArtistHomepage
from berlin_events_explorer.models import ArtistMetadata, ArtistRecord
from berlin_events_explorer.storage import EventStore


_METADATA_FIELD = "official_homepage"
_PROVIDER = "musicbrainz"


class ArtistHomepageProvider(Protocol):
    """Minimal provider contract for a verified artist homepage lookup."""

    def discover_official_homepage(
        self, artist: ArtistRecord, *, refresh: bool = False
    ) -> ArtistHomepage | None:
        """Return a trusted official homepage relation, if the provider exposes one."""


@dataclass(frozen=True)
class ArtistHomepageEnrichmentResult:
    """Summary of one bounded verified-artist homepage pass."""

    checked: int
    found: int
    no_homepage: int
    errors: int
    remaining: int


def enrich_artist_homepages(
    store: EventStore,
    provider: ArtistHomepageProvider,
    *,
    limit: int,
    refresh: bool = False,
) -> ArtistHomepageEnrichmentResult:
    """Cache homepage checks for a bounded group of verified MusicBrainz artists."""

    artists = store.list_verified_artists_missing_metadata(
        _METADATA_FIELD, _PROVIDER, limit=limit
    )
    checked = found = no_homepage = errors = 0
    for artist in artists:
        try:
            homepage = provider.discover_official_homepage(artist, refresh=refresh)
        except Exception:
            errors += 1
            continue
        checked += 1
        if homepage is None:
            no_homepage += 1
            store.save_artist_metadata(
                ArtistMetadata(
                    artist_id=artist.id,
                    field=_METADATA_FIELD,
                    value=None,
                    provider=_PROVIDER,
                    source_url=artist.musicbrainz_url,
                )
            )
            continue
        found += 1
        store.save_artist_metadata(
            ArtistMetadata(
                artist_id=artist.id,
                field=_METADATA_FIELD,
                value=homepage.url,
                provider=_PROVIDER,
                source_url=homepage.source_url,
                confidence=1.0,
                retrieved_at=homepage.retrieved_at,
            )
        )
    return ArtistHomepageEnrichmentResult(
        checked=checked,
        found=found,
        no_homepage=no_homepage,
        errors=errors,
        remaining=store.count_verified_artists_missing_metadata(
            _METADATA_FIELD, _PROVIDER
        ),
    )
