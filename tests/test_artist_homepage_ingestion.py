"""Tests for recording cached official artist homepage metadata."""

from datetime import UTC, datetime

from berlin_events_explorer.artist_enrichment import ArtistHomepage
from berlin_events_explorer.artist_homepage_ingestion import enrich_artist_homepages
from berlin_events_explorer.models import ArtistRecord, ArtistStatus
from berlin_events_explorer.storage import EventStore


class _HomepageProvider:
    def discover_official_homepage(self, artist, *, refresh=False):
        assert artist.id == "die-arzte"
        return ArtistHomepage(
            url="https://www.bademeister.com/",
            source_url="https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111",
            retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
        )


def test_homepage_enrichment_persists_official_url_and_skips_checked_artists(
    tmp_path,
) -> None:
    """A verified artist receives a public homepage and an explicit cached-check marker."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_artist(
        ArtistRecord(
            id="die-arzte",
            name="Die Ärzte",
            normalized_name="die ärzte",
            musicbrainz_id="11111111-1111-1111-1111-111111111111",
            musicbrainz_url="https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111",
            status=ArtistStatus.VERIFIED,
        )
    )

    first = enrich_artist_homepages(store, _HomepageProvider(), limit=10)
    second = enrich_artist_homepages(store, _HomepageProvider(), limit=10)

    assert (first.checked, first.found, first.remaining) == (1, 1, 0)
    assert (second.checked, second.found, second.remaining) == (0, 0, 0)
    assert (
        store.get_artist_official_homepage("die-arzte")
        == "https://www.bademeister.com/"
    )
