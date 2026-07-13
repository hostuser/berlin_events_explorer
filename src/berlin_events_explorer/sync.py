"""Source synchronization orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy.exc import SQLAlchemyError

from berlin_events_explorer.sources.base import EventSource
from berlin_events_explorer.storage import EventStore


@dataclass(frozen=True)
class SyncResult:
    """Summary of one source synchronization."""

    downloaded: bool
    created: int
    updated: int
    unchanged: int


class SyncError(RuntimeError):
    """Raised when synchronization cannot complete successfully."""


def sync_source(
    source: EventSource,
    store: EventStore,
    client: httpx.Client,
) -> SyncResult:
    """Conditionally fetch a source and upsert its events."""
    snapshot = store.get_snapshot(source.name)
    headers: dict[str, str] = {}
    if snapshot and snapshot.etag:
        headers["If-None-Match"] = snapshot.etag
    if snapshot and snapshot.last_modified:
        headers["If-Modified-Since"] = snapshot.last_modified

    try:
        response = client.get(source.url, headers=headers)
    except httpx.RequestError as exc:
        raise SyncError(f"Network request failed for {source.name}: {exc}") from exc

    if response.status_code == 304:
        checked_at = datetime.now(timezone.utc)
        store.save_snapshot(
            provider=source.name,
            url=source.url,
            etag=response.headers.get("etag") or (snapshot.etag if snapshot else None),
            last_modified=response.headers.get("last-modified")
            or (snapshot.last_modified if snapshot else None),
            content_hash=snapshot.content_hash if snapshot else None,
            checked_at=checked_at,
        )
        return SyncResult(
            downloaded=False,
            created=0,
            updated=0,
            unchanged=store.count_events(source.name),
        )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SyncError(
            f"Source {source.name} responded with HTTP {response.status_code}"
        ) from exc

    try:
        events = list(
            source.parse(response.text, fetched_at=datetime.now(timezone.utc))
        )
    except ValueError as exc:
        raise SyncError(
            f"Could not parse event data from {source.name}: {exc}"
        ) from exc

    created = updated = unchanged = 0
    try:
        with store.engine.begin() as connection:
            for event in events:
                result = store.upsert(event, connection=connection)
                if result.action == "created":
                    created += 1
                elif result.action == "updated":
                    updated += 1
                else:
                    unchanged += 1

            content_hash = hashlib.sha256(response.content).hexdigest()
            store.save_snapshot(
                provider=source.name,
                url=source.url,
                etag=response.headers.get("etag")
                or (snapshot.etag if snapshot else None),
                last_modified=response.headers.get("last-modified")
                or (snapshot.last_modified if snapshot else None),
                content_hash=content_hash,
                checked_at=datetime.now(timezone.utc),
                connection=connection,
            )
    except SQLAlchemyError as exc:
        raise SyncError("Database write failed while syncing events") from exc

    return SyncResult(
        downloaded=True,
        created=created,
        updated=updated,
        unchanged=unchanged,
    )
