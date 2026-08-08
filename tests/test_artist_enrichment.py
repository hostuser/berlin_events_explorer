"""Tests for policy-compliant MusicBrainz artist discovery."""

from datetime import UTC, datetime

import sqlite3

import diskcache
import httpx
import pytest

from berlin_events_explorer.artist_enrichment import (
    DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    MusicBrainzArtistProvider,
    MusicBrainzConfigurationError,
    auto_approval_candidate,
)
from berlin_events_explorer.models import ArtistRecord


def _artist() -> ArtistRecord:
    return ArtistRecord(
        id="die-arzte",
        name="Die Ärzte",
        normalized_name="die ärzte",
        musicbrainz_id="11111111-1111-1111-1111-111111111111",
        musicbrainz_url="https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111",
    )


def test_musicbrainz_provider_uses_identified_json_request_and_caches_response(
    tmp_path,
) -> None:
    """A valid search is identified, parsed, and reused without a second request."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "artists": [
                    {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "name": "Die Ärzte",
                        "type": "Group",
                        "country": "DE",
                        "score": 100,
                        "tags": [{"name": "punk rock"}],
                    }
                ]
            },
        )

    with diskcache.Cache(tmp_path / "cache") as cache:
        provider = MusicBrainzArtistProvider(
            httpx.Client(transport=httpx.MockTransport(handler)), cache=cache
        )
        first = provider.discover(_artist(), now=datetime(2026, 7, 30, tzinfo=UTC))
        second = provider.discover(_artist(), now=datetime(2026, 7, 31, tzinfo=UTC))

    assert len(requests) == 1
    assert requests[0].url.params["query"] == 'artist:"Die Ärzte"'
    assert requests[0].url.params["fmt"] == "json"
    assert requests[0].headers["accept"] == "application/json"
    assert requests[0].headers["user-agent"].startswith("BerlinEventsExplorer/")
    assert first[0].display_name == "Die Ärzte"
    assert first[0].provider_score == 100
    assert first == second


def test_musicbrainz_provider_recovers_from_a_pre_reboot_pacing_value(tmp_path) -> None:
    """A persisted monotonic-clock value must never delay a fresh boot for days."""

    requests: list[httpx.Request] = []
    cache_path = tmp_path / "cache"
    with diskcache.Cache(cache_path) as cache:
        pacer_path = cache_path / "pacer.sqlite"
        with sqlite3.connect(pacer_path) as connection:
            connection.execute(
                "CREATE TABLE provider_pacing (provider TEXT PRIMARY KEY, next_request_at REAL NOT NULL)"
            )
            connection.execute(
                "INSERT INTO provider_pacing VALUES (?, ?)",
                ("musicbrainz", 1_878_883.0),
            )

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"artists": []})

        sleeps: list[float] = []
        provider = MusicBrainzArtistProvider(
            httpx.Client(transport=httpx.MockTransport(handler)),
            cache=cache,
            clock=lambda: 1_786_190_000.0,
            sleep=sleeps.append,
        )
        provider.discover(_artist())

    assert len(requests) == 1
    assert sleeps == []


def test_musicbrainz_provider_extracts_streaming_platform_links(tmp_path) -> None:
    """MusicBrainz URL relations expose Spotify and YouTube Music links when present."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "relations": [
                    {
                        "type": "streaming music",
                        "url": {"resource": "https://open.spotify.com/artist/abc123"},
                    },
                    {
                        "type": "streaming music",
                        "url": {"resource": "https://music.youtube.com/channel/UC123"},
                    },
                    {
                        "type": "social network",
                        "url": {"resource": "https://example.com/not-a-platform"},
                    },
                ]
            },
        )

    with diskcache.Cache(tmp_path / "cache") as cache:
        provider = MusicBrainzArtistProvider(
            httpx.Client(transport=httpx.MockTransport(handler)), cache=cache
        )
        links = provider.discover_artist_links(_artist())

    assert links.spotify == "https://open.spotify.com/artist/abc123"
    assert links.youtube_music == "https://music.youtube.com/channel/UC123"


def test_musicbrainz_provider_rejects_interval_below_public_limit() -> None:
    """The public API client cannot be configured above MusicBrainz's rate limit."""

    with pytest.raises(MusicBrainzConfigurationError, match="at least 1.0"):
        MusicBrainzArtistProvider(httpx.Client(), request_interval_seconds=0.99)

    assert DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS == 1.1


def test_auto_approval_requires_one_exact_unique_threshold_match() -> None:
    """Only a unique exact 100-score artist candidate bypasses manual review."""

    now = datetime(2026, 7, 30, tzinfo=UTC)
    provider = MusicBrainzArtistProvider(httpx.Client())
    candidates = provider._candidates_from_payload(
        _artist(),
        {
            "artists": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "name": "Die Ärzte",
                    "score": 100,
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "name": "Die Ärzte",
                    "score": 99,
                },
            ]
        },
        retrieved_at=now,
    )

    selected = auto_approval_candidate(_artist(), candidates, threshold=1.0)

    assert selected is not None
    assert selected.musicbrainz_id == "11111111-1111-1111-1111-111111111111"
