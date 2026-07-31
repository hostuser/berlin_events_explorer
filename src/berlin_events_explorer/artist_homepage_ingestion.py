"""Bounded official-homepage enrichment for verified artists."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from berlin_events_explorer.artist_enrichment import ArtistHomepage, ArtistLinks
from berlin_events_explorer.models import ArtistMetadata, ArtistRecord
from berlin_events_explorer.storage import EventStore


_METADATA_FIELDS = ("official_homepage", "spotify", "youtube_music")
_PROVIDER = "musicbrainz"


class ArtistHomepageProvider(Protocol):
    """Minimal provider contract for a verified artist homepage lookup."""

    def discover_official_homepage(
        self, artist: ArtistRecord, *, refresh: bool = False
    ) -> ArtistHomepage | None:
        """Return a trusted official homepage relation, if the provider exposes one."""
        ...


class ArtistLinksProvider(Protocol):
    """Provider contract for one combined artist URL-relations lookup."""

    def discover_artist_links(
        self, artist: ArtistRecord, *, refresh: bool = False
    ) -> ArtistLinks:
        """Return all supported public artist platform links."""
        ...


@dataclass(frozen=True)
class ArtistHomepageEnrichmentResult:
    """Summary of one bounded verified-artist homepage pass."""

    checked: int
    found: int
    no_homepage: int
    errors: int
    remaining: int
    spotify_found: int = 0
    youtube_music_found: int = 0


def enrich_artist_homepages(
    store: EventStore,
    provider: ArtistHomepageProvider | ArtistLinksProvider,
    *,
    limit: int,
    refresh: bool = False,
) -> ArtistHomepageEnrichmentResult:
    """Cache homepage checks for a bounded group of verified MusicBrainz artists."""

    artists = store.list_verified_artists_missing_any_metadata(
        _METADATA_FIELDS, _PROVIDER, limit=limit
    )
    checked = found = no_homepage = errors = spotify_found = youtube_music_found = 0
    for artist in artists:
        try:
            discover_links = getattr(provider, "discover_artist_links", None)
            if callable(discover_links):
                links = cast(ArtistLinksProvider, provider).discover_artist_links(
                    artist, refresh=refresh
                )
            else:
                homepage = cast(
                    ArtistHomepageProvider, provider
                ).discover_official_homepage(artist, refresh=refresh)
                links = ArtistLinks(
                    official_homepage=homepage.url if homepage else None,
                    spotify=None,
                    youtube_music=None,
                    source_url=homepage.source_url
                    if homepage
                    else artist.musicbrainz_url or "",
                    retrieved_at=homepage.retrieved_at
                    if homepage
                    else datetime.now(UTC),
                )
        except Exception:
            errors += 1
            continue
        checked += 1
        if links.official_homepage is None:
            no_homepage += 1
        else:
            found += 1
        if links.spotify is not None:
            spotify_found += 1
        if links.youtube_music is not None:
            youtube_music_found += 1
        values = {
            "official_homepage": links.official_homepage,
            "spotify": links.spotify,
            "youtube_music": links.youtube_music,
        }
        for field, value in values.items():
            store.save_artist_metadata(
                ArtistMetadata(
                    artist_id=artist.id,
                    field=field,
                    value=value,
                    provider=_PROVIDER,
                    source_url=links.source_url or artist.musicbrainz_url,
                    confidence=1.0 if value is not None else None,
                    retrieved_at=links.retrieved_at,
                )
            )
    return ArtistHomepageEnrichmentResult(
        checked=checked,
        found=found,
        no_homepage=no_homepage,
        errors=errors,
        remaining=store.count_verified_artists_missing_any_metadata(
            _METADATA_FIELDS, _PROVIDER
        ),
        spotify_found=spotify_found,
        youtube_music_found=youtube_music_found,
    )
