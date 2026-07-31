"""Policy-compliant MusicBrainz artist candidate discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import random
import sqlite3
import time
from typing import Any, Callable
from urllib.parse import quote, urlparse

import diskcache
import httpx

from berlin_events_explorer._version import version
from berlin_events_explorer.artists import normalize_artist_name
from berlin_events_explorer.models import ArtistCandidate, ArtistRecord

MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_ARTIST_SEARCH_URL = f"{MUSICBRAINZ_BASE_URL}/artist"
MUSICBRAINZ_USER_AGENT = (
    f"BerlinEventsExplorer/{version} "
    "(https://github.com/hostuser/berlin_events_explorer)"
)
DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS = 1.1
DEFAULT_MUSICBRAINZ_FETCH_LIMIT = 200
MAX_MUSICBRAINZ_FETCH_LIMIT = 10000
DEFAULT_ARTIST_AUTO_APPROVE_THRESHOLD = 1.0
DEFAULT_MUSICBRAINZ_CACHE_DIR = (
    Path.home() / ".cache" / "berlin-events-explorer" / "musicbrainz"
)
_CACHE_PREFIX = "musicbrainz:artist-search:v1"
_HOMEPAGE_CACHE_PREFIX = "musicbrainz:artist-url-rels:v1"


@dataclass(frozen=True)
class ArtistHomepage:
    """An official homepage relation supplied by MusicBrainz."""

    url: str
    source_url: str
    retrieved_at: datetime


@dataclass(frozen=True)
class ArtistLinks:
    """Public platform links discovered from one MusicBrainz URL response."""

    official_homepage: str | None
    spotify: str | None
    youtube_music: str | None
    source_url: str
    retrieved_at: datetime


class ArtistDiscoveryError(RuntimeError):
    """Raised when MusicBrainz cannot return a usable artist response."""


class MusicBrainzConfigurationError(ValueError):
    """Raised for unsafe public MusicBrainz client configuration."""


class _RequestPacer:
    """Reserve provider request slots across processes sharing one cache directory."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "pacer.sqlite"
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_pacing (
                    provider TEXT PRIMARY KEY,
                    next_request_at REAL NOT NULL
                )
                """
            )

    def reserve(self, provider: str, interval: float, now: float) -> float:
        """Transactionally allocate the next provider request and return wait seconds."""

        with sqlite3.connect(self.path, timeout=30, isolation_level=None) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT next_request_at FROM provider_pacing WHERE provider = ?",
                (provider,),
            ).fetchone()
            scheduled_at = max(now, float(row[0])) if row else now
            connection.execute(
                """
                INSERT INTO provider_pacing(provider, next_request_at) VALUES (?, ?)
                ON CONFLICT(provider) DO UPDATE SET next_request_at = excluded.next_request_at
                """,
                (provider, scheduled_at + interval),
            )
            connection.execute("COMMIT")
        return scheduled_at - now


def open_musicbrainz_cache(cache_dir: Path | None = None) -> diskcache.Cache:
    """Open the shared cross-environment MusicBrainz response cache."""

    return diskcache.Cache(str(cache_dir or DEFAULT_MUSICBRAINZ_CACHE_DIR))


def clear_musicbrainz_cache(cache: diskcache.Cache) -> None:
    """Clear cached MusicBrainz responses and pacing state intentionally."""

    cache.clear()
    pacer_path = Path(cache.directory) / "pacer.sqlite"
    pacer_path.unlink(missing_ok=True)


def auto_approval_candidate(
    artist: ArtistRecord,
    candidates: list[ArtistCandidate],
    *,
    threshold: float,
) -> ArtistCandidate | None:
    """Return one unambiguous exact artist candidate meeting the configured threshold."""

    if not 0 <= threshold <= 1:
        raise ValueError("artist auto-approval threshold must be between 0 and 1")
    eligible = [
        candidate
        for candidate in candidates
        if normalize_artist_name(candidate.display_name) == artist.normalized_name
        and candidate.confidence >= threshold
    ]
    return eligible[0] if len(eligible) == 1 else None


class MusicBrainzArtistProvider:
    """Discover reviewable MusicBrainz artist candidates safely and sequentially."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        cache: diskcache.Cache | None = None,
        cache_dir: Path | None = None,
        request_interval_seconds: float = DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        random_float: Callable[[], float] = random.random,
    ) -> None:
        if not 1.0 <= request_interval_seconds <= 300.0:
            raise MusicBrainzConfigurationError(
                "MusicBrainz request interval must be at least 1.0 and at most 300 seconds"
            )
        self._client = client
        self._cache = cache
        directory = cache_dir or (
            Path(cache.directory)
            if cache is not None
            else DEFAULT_MUSICBRAINZ_CACHE_DIR
        )
        self._pacer = _RequestPacer(directory)
        self._interval = request_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._random_float = random_float

    def discover(
        self,
        artist: ArtistRecord,
        *,
        now: datetime | None = None,
        refresh: bool = False,
    ) -> list[ArtistCandidate]:
        """Search MusicBrainz once, preferring a validated cached response."""

        cache_key = _cache_key(artist.normalized_name)
        cached = (
            self._cache.get(cache_key)
            if self._cache is not None and not refresh
            else None
        )
        if isinstance(cached, dict) and isinstance(cached.get("payload"), dict):
            retrieved_at = _parse_cached_datetime(cached.get("retrieved_at"))
            if retrieved_at is not None:
                return self._candidates_from_payload(
                    artist, cached["payload"], retrieved_at=retrieved_at
                )

        payload, retrieved_at = self._request_with_retry(artist)
        if self._cache is not None:
            self._cache.set(
                cache_key,
                {"payload": payload, "retrieved_at": retrieved_at.isoformat()},
            )
        return self._candidates_from_payload(artist, payload, retrieved_at=retrieved_at)

    def discover_official_homepage(
        self,
        artist: ArtistRecord,
        *,
        now: datetime | None = None,
        refresh: bool = False,
    ) -> ArtistHomepage | None:
        """Return a cached verified artist's MusicBrainz official homepage, if listed."""

        links = self.discover_artist_links(artist, now=now, refresh=refresh)
        if links.official_homepage is None:
            return None
        return ArtistHomepage(
            url=links.official_homepage,
            source_url=links.source_url,
            retrieved_at=links.retrieved_at,
        )

    def discover_artist_links(
        self,
        artist: ArtistRecord,
        *,
        now: datetime | None = None,
        refresh: bool = False,
    ) -> ArtistLinks:
        """Return cached official and streaming URLs for a verified artist."""

        if artist.musicbrainz_id is None:
            raise ValueError("artist must have a verified MusicBrainz ID")
        cache_key = _homepage_cache_key(artist.musicbrainz_id)
        cached = (
            self._cache.get(cache_key)
            if self._cache is not None and not refresh
            else None
        )
        if isinstance(cached, dict) and isinstance(cached.get("payload"), dict):
            retrieved_at = _parse_cached_datetime(cached.get("retrieved_at"))
            if retrieved_at is not None:
                return _artist_links_from_payload(
                    artist.musicbrainz_id, cached["payload"], retrieved_at
                )

        payload, retrieved_at = self._request_homepage_with_retry(artist)
        if self._cache is not None:
            self._cache.set(
                cache_key,
                {"payload": payload, "retrieved_at": retrieved_at.isoformat()},
            )
        return _artist_links_from_payload(artist.musicbrainz_id, payload, retrieved_at)

    def _request_homepage_with_retry(
        self, artist: ArtistRecord
    ) -> tuple[dict[str, Any], datetime]:
        """Fetch one artist's URL relations while applying the shared rate limit."""

        assert artist.musicbrainz_id is not None
        artist_url = (
            f"{MUSICBRAINZ_BASE_URL}/artist/{quote(artist.musicbrainz_id, safe='')}"
        )
        for attempt in range(3):
            self._reserve_slot()
            try:
                response = self._client.get(
                    artist_url,
                    params={"inc": "url-rels", "fmt": "json"},
                    headers={
                        "User-Agent": MUSICBRAINZ_USER_AGENT,
                        "Accept": "application/json",
                    },
                    timeout=20.0,
                )
            except httpx.RequestError as exc:
                if attempt == 2:
                    raise ArtistDiscoveryError(
                        f"MusicBrainz homepage lookup failed for {artist.name}: {exc}"
                    ) from exc
                self._sleep(_retry_delay(None, attempt, self._random_float))
                continue
            if response.status_code in {429, 503}:
                if attempt == 2:
                    raise ArtistDiscoveryError(
                        f"MusicBrainz throttled homepage lookup for {artist.name}"
                    )
                self._sleep(_retry_delay(response, attempt, self._random_float))
                continue
            try:
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPStatusError, ValueError) as exc:
                raise ArtistDiscoveryError(
                    f"MusicBrainz homepage lookup failed for {artist.name}"
                ) from exc
            if not isinstance(payload, dict) or not isinstance(
                payload.get("relations"), list
            ):
                raise ArtistDiscoveryError(
                    "MusicBrainz returned an unexpected artist relations payload"
                )
            return payload, datetime.now(UTC)
        raise AssertionError("unreachable")

    def _request_with_retry(
        self, artist: ArtistRecord
    ) -> tuple[dict[str, Any], datetime]:
        for attempt in range(3):
            self._reserve_slot()
            try:
                response = self._client.get(
                    MUSICBRAINZ_ARTIST_SEARCH_URL,
                    params={
                        "query": _search_query(artist.name),
                        "fmt": "json",
                        "limit": "5",
                    },
                    headers={
                        "User-Agent": MUSICBRAINZ_USER_AGENT,
                        "Accept": "application/json",
                    },
                    timeout=20.0,
                )
            except httpx.RequestError as exc:
                if attempt == 2:
                    raise ArtistDiscoveryError(
                        f"MusicBrainz lookup failed for {artist.name}: {exc}"
                    ) from exc
                self._sleep(_retry_delay(None, attempt, self._random_float))
                continue

            if response.status_code in {429, 503}:
                if attempt == 2:
                    raise ArtistDiscoveryError(
                        f"MusicBrainz throttled lookup for {artist.name}"
                    )
                self._sleep(_retry_delay(response, attempt, self._random_float))
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ArtistDiscoveryError(
                    f"MusicBrainz lookup failed for {artist.name}: HTTP {response.status_code}"
                ) from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise ArtistDiscoveryError("MusicBrainz returned invalid JSON") from exc
            if not isinstance(payload, dict) or not isinstance(
                payload.get("artists"), list
            ):
                raise ArtistDiscoveryError(
                    "MusicBrainz returned an unexpected response payload"
                )
            return payload, datetime.now(UTC)
        raise AssertionError("unreachable")

    def _reserve_slot(self) -> None:
        delay = self._pacer.reserve("musicbrainz", self._interval, self._monotonic())
        if delay > 0:
            self._sleep(delay)

    def _candidates_from_payload(
        self,
        artist: ArtistRecord,
        payload: dict[str, Any],
        *,
        retrieved_at: datetime,
    ) -> list[ArtistCandidate]:
        """Convert the limited MusicBrainz search response into typed candidates."""

        candidates: dict[str, ArtistCandidate] = {}
        for item in payload.get("artists", []):
            if not isinstance(item, dict):
                continue
            musicbrainz_id = item.get("id")
            display_name = item.get("name")
            if not isinstance(musicbrainz_id, str) or not isinstance(display_name, str):
                continue
            score = _score(item.get("score"))
            candidate = ArtistCandidate(
                artist_id=artist.id,
                provider="musicbrainz",
                source_url=(
                    f"https://musicbrainz.org/artist/{quote(musicbrainz_id, safe='')}"
                ),
                musicbrainz_id=musicbrainz_id,
                display_name=display_name,
                artist_type=_string_or_none(item.get("type")),
                country=_string_or_none(item.get("country")),
                disambiguation=_string_or_none(item.get("disambiguation")),
                genres=_tag_names(item.get("tags")),
                provider_score=score,
                confidence=(score or 0) / 100,
                retrieved_at=retrieved_at,
            )
            existing = candidates.get(musicbrainz_id)
            if existing is None or candidate.confidence > existing.confidence:
                candidates[musicbrainz_id] = candidate
        return list(candidates.values())


def _search_query(name: str) -> str:
    """Quote user-provided names for the MusicBrainz Lucene query parameter."""

    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return 'artist:"' + escaped + '"'


def _cache_key(normalized_name: str) -> str:
    return f"{_CACHE_PREFIX}:{normalized_name}:limit=5"


def _homepage_cache_key(musicbrainz_id: str) -> str:
    """Use the immutable MusicBrainz ID for a reusable URL-relations cache entry."""

    return f"{_HOMEPAGE_CACHE_PREFIX}:{musicbrainz_id}"


def _artist_links_from_payload(
    musicbrainz_id: str, payload: dict[str, Any], retrieved_at: datetime
) -> ArtistLinks:
    """Select trusted homepage, Spotify, and YouTube Music relations."""

    official_homepage: str | None = None
    spotify: str | None = None
    youtube_music: str | None = None
    for relation in payload.get("relations", []):
        if not isinstance(relation, dict):
            continue
        url = relation.get("url")
        resource = url.get("resource") if isinstance(url, dict) else None
        if not isinstance(resource, str):
            continue
        parsed = urlparse(resource)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        hostname = (parsed.hostname or "").lower()
        if relation.get("type") == "official homepage" and official_homepage is None:
            official_homepage = resource
        elif (
            spotify is None
            and hostname in {"open.spotify.com", "spotify.com"}
            and parsed.path.startswith("/artist/")
        ):
            spotify = resource
        elif youtube_music is None and hostname == "music.youtube.com":
            youtube_music = resource

    return ArtistLinks(
        official_homepage=official_homepage,
        spotify=spotify,
        youtube_music=youtube_music,
        source_url=f"https://musicbrainz.org/artist/{quote(musicbrainz_id, safe='')}",
        retrieved_at=retrieved_at,
    )


def _parse_cached_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo is not None else result.replace(tzinfo=UTC)


def _retry_delay(
    response: httpx.Response | None, attempt: int, random_float: Callable[[], float]
) -> float:
    if response is not None:
        raw_retry_after = response.headers.get("Retry-After")
        if raw_retry_after is not None:
            try:
                retry_after = float(raw_retry_after)
            except ValueError:
                retry_after = 0
            if retry_after > 0:
                return retry_after
    return min(60.0, 5.0 * (2**attempt)) + random_float()


def _score(value: object) -> int | None:
    if isinstance(value, int) and 0 <= value <= 100:
        return value
    if isinstance(value, str) and value.isdigit() and 0 <= int(value) <= 100:
        return int(value)
    return None


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _tag_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            name.strip()
            for item in value
            if isinstance(item, dict)
            and isinstance(name := item.get("name"), str)
            and name.strip()
        }
    )
