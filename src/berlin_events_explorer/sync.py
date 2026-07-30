"""Source synchronization orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from diskcache import Cache
from sqlalchemy.exc import SQLAlchemyError

from berlin_events_explorer.sources.base import EventSource
from berlin_events_explorer.storage import EventStore, SourceSnapshot


DEFAULT_SYNC_CACHE_DIR = Path.home() / ".cache" / "berlin-events-explorer"
_CACHE_METADATA_PREFIX = "berlin-events-source-metadata"
_CACHE_BODY_PREFIX = "berlin-events-source-body"


@dataclass(frozen=True)
class SyncResult:
    """Summary of one source synchronization."""

    downloaded: bool
    created: int
    updated: int
    unchanged: int
    errors: int = 0


class SyncError(RuntimeError):
    """Raised when synchronization cannot complete successfully."""


def open_sync_cache(cache_dir: Path | None = None) -> Cache:
    """Open the on-disk cache used for cross-database HTTP metadata."""

    return Cache(str(cache_dir or DEFAULT_SYNC_CACHE_DIR))


def clear_sync_cache(cache: Cache | None) -> None:
    """Clear all entries from the sync on-disk cache."""

    if cache is None:
        return

    cache.clear()


def sync_source(
    source: EventSource,
    store: EventStore,
    client: httpx.Client,
    *,
    http_cache: Cache | None = None,
) -> SyncResult:
    """Conditionally fetch a source and upsert its events."""
    snapshot = store.get_snapshot(source.name)
    cached_snapshot = _get_cached_snapshot(http_cache, source)

    request_snapshot = snapshot or cached_snapshot
    headers: dict[str, str] = {}
    if request_snapshot and request_snapshot.etag:
        headers["If-None-Match"] = request_snapshot.etag
    if request_snapshot and request_snapshot.last_modified:
        headers["If-Modified-Since"] = request_snapshot.last_modified

    try:
        response = client.get(source.url, headers=headers)
    except httpx.RequestError as exc:
        store.log(
            level="error",
            event="source_request_failed",
            message=f"Network request failed for {source.name}: {exc}",
            context={"provider": source.name, "url": source.url},
        )
        raise SyncError(f"Network request failed for {source.name}: {exc}") from exc

    if response.status_code == 304:
        cached_body = _get_cached_body(http_cache, source)
        if cached_body is None:
            checked_at = datetime.now(timezone.utc)
            etag = response.headers.get("etag") or (
                request_snapshot.etag if request_snapshot else None
            )
            last_modified = response.headers.get("last-modified") or (
                request_snapshot.last_modified if request_snapshot else None
            )
            store.save_snapshot(
                provider=source.name,
                url=source.url,
                etag=etag,
                last_modified=last_modified,
                content_hash=request_snapshot.content_hash
                if request_snapshot
                else None,
                checked_at=checked_at,
            )
            return SyncResult(
                downloaded=False,
                created=0,
                updated=0,
                unchanged=store.count_events(source.name),
            )

        return _sync_payload_from_text(
            source,
            store,
            cached_body,
            now=datetime.now(timezone.utc),
            response=response,
            request_snapshot=request_snapshot,
            downloaded=False,
            http_cache=http_cache,
        )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        store.log(
            level="error",
            event="source_response_failed",
            message=f"Source {source.name} responded with HTTP {response.status_code}",
            context={
                "provider": source.name,
                "url": source.url,
                "status_code": response.status_code,
            },
        )
        raise SyncError(
            f"Source {source.name} responded with HTTP {response.status_code}"
        ) from exc

    return _sync_payload_from_text(
        source,
        store,
        response.text,
        now=datetime.now(timezone.utc),
        response=response,
        request_snapshot=request_snapshot,
        downloaded=True,
        http_cache=http_cache,
    )


def _sync_payload_from_text(
    source: EventSource,
    store: EventStore,
    payload_text: str,
    *,
    now: datetime,
    response: httpx.Response,
    request_snapshot: SourceSnapshot | None,
    downloaded: bool,
    http_cache: Cache | None,
) -> SyncResult:
    try:
        parse_result = source.parse(payload_text, fetched_at=now)
    except ValueError as exc:
        store.log(
            level="error",
            event="source_payload_parse_failed",
            message=f"Could not parse event data from {source.name}: {exc}",
            context={"provider": source.name, "url": source.url},
        )
        raise SyncError(
            f"Could not parse event data from {source.name}: {exc}"
        ) from exc

    events = parse_result.events

    etag = response.headers.get("etag") or (
        request_snapshot.etag if request_snapshot else None
    )
    last_modified = response.headers.get("last-modified") or (
        request_snapshot.last_modified if request_snapshot else None
    )
    content_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()

    created = updated = unchanged = 0
    try:
        with store.engine.begin() as connection:
            for event in events:
                result = store.upsert(event, connection=connection, now=now)
                if result.action == "created":
                    created += 1
                elif result.action == "updated":
                    updated += 1
                else:
                    unchanged += 1

            for issue in parse_result.issues:
                store.log(
                    level=issue.level,
                    event=issue.event,
                    message=issue.message,
                    context=issue.context,
                    created_at=now,
                    connection=connection,
                )

            store.save_snapshot(
                provider=source.name,
                url=source.url,
                etag=etag,
                last_modified=last_modified,
                content_hash=content_hash,
                checked_at=now,
                connection=connection,
            )
    except SQLAlchemyError as exc:
        raise SyncError("Database write failed while syncing events") from exc

    if http_cache is not None:
        _save_cached_snapshot(
            http_cache,
            source,
            etag=etag,
            last_modified=last_modified,
            content_hash=content_hash,
            checked_at=now,
        )
        _save_cached_body(http_cache, source, payload_text)

    return SyncResult(
        downloaded=downloaded,
        created=created,
        updated=updated,
        unchanged=unchanged,
        errors=len(parse_result.issues),
    )


def _get_cached_snapshot(
    cache: Cache | None, source: EventSource
) -> SourceSnapshot | None:
    if cache is None:
        return None

    raw = cache.get(_cache_metadata_key(source))
    if not isinstance(raw, dict):
        return None
    if raw.get("provider") != source.name or raw.get("url") != source.url:
        return None

    checked_at = raw.get("checked_at")
    if not isinstance(checked_at, datetime):
        if isinstance(checked_at, str):
            try:
                checked_at = datetime.fromisoformat(checked_at)
            except ValueError:
                return None
        else:
            return None

    return SourceSnapshot(
        provider=raw.get("provider", source.name),
        url=raw.get("url", source.url),
        etag=raw.get("etag"),
        last_modified=raw.get("last_modified"),
        content_hash=raw.get("content_hash"),
        checked_at=checked_at,
    )


def _save_cached_snapshot(
    cache: Cache,
    source: EventSource,
    *,
    etag: str | None,
    last_modified: str | None,
    content_hash: str | None,
    checked_at: datetime,
) -> None:
    cache.set(
        _cache_metadata_key(source),
        {
            "provider": source.name,
            "url": source.url,
            "etag": etag,
            "last_modified": last_modified,
            "content_hash": content_hash,
            "checked_at": checked_at.isoformat(),
        },
    )


def _cache_metadata_key(source: EventSource) -> str:
    return f"{_CACHE_METADATA_PREFIX}:{source.name}:{source.url}"


def _get_cached_body(cache: Cache | None, source: EventSource) -> str | None:
    if cache is None:
        return None
    body = cache.get(_cache_body_key(source))
    if isinstance(body, str):
        return body
    if isinstance(body, (bytes, bytearray)):
        return body.decode("utf-8", errors="replace")
    return None


def _save_cached_body(cache: Cache, source: EventSource, body: str) -> None:
    cache.set(_cache_body_key(source), body)


def _cache_body_key(source: EventSource) -> str:
    return f"{_CACHE_BODY_PREFIX}:{source.name}:{source.url}"
