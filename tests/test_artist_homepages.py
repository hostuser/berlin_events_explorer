"""Tests for cached MusicBrainz official-homepage enrichment."""

from datetime import UTC, datetime

import diskcache
import httpx

from berlin_events_explorer.artist_enrichment import MusicBrainzArtistProvider
from berlin_events_explorer.models import ArtistRecord, ArtistStatus


ARTIST_ID = "11111111-1111-1111-1111-111111111111"


def _artist() -> ArtistRecord:
    return ArtistRecord(
        id="die-arzte",
        name="Die Ärzte",
        normalized_name="die ärzte",
        musicbrainz_id=ARTIST_ID,
        musicbrainz_url=f"https://musicbrainz.org/artist/{ARTIST_ID}",
        status=ArtistStatus.VERIFIED,
    )


def test_musicbrainz_provider_selects_official_homepage_and_caches_relation_response(
    tmp_path,
) -> None:
    """Only the official-homepage relation is selected and reused from shared cache."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "relations": [
                    {
                        "type": "social network",
                        "url": {"resource": "https://social.example/dieaerzte"},
                    },
                    {
                        "type": "official homepage",
                        "url": {"resource": "https://www.bademeister.com/"},
                    },
                ]
            },
        )

    with diskcache.Cache(tmp_path / "cache") as cache:
        provider = MusicBrainzArtistProvider(
            httpx.Client(transport=httpx.MockTransport(handler)), cache=cache
        )
        first = provider.discover_official_homepage(
            _artist(), now=datetime(2026, 7, 30, tzinfo=UTC)
        )
        second = provider.discover_official_homepage(
            _artist(), now=datetime(2026, 7, 31, tzinfo=UTC)
        )

    assert len(requests) == 1
    assert requests[0].url.path == f"/ws/2/artist/{ARTIST_ID}"
    assert requests[0].url.params["inc"] == "url-rels"
    assert requests[0].url.params["fmt"] == "json"
    assert first is not None
    assert first.url == "https://www.bademeister.com/"
    assert first == second
