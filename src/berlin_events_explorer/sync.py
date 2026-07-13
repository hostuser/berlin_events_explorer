"""Source synchronization orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from berlin_events_explorer.sources.base import EventSource
from berlin_events_explorer.storage import EventStore


@dataclass(frozen=True)
class SyncResult:
    """Summary of one source synchronization."""

    downloaded: bool
    created: int
    updated: int
    unchanged: int


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

    response = client.get(source.url, headers=headers)
    if response.status_code == 304:
        return SyncResult(
            downloaded=False,
            created=0,
            updated=0,
            unchanged=store.count_events(source.name),
        )
    response.raise_for_status()

    events = {
        event.id: event
        for event in source.parse(response.text, fetched_at=datetime.now(timezone.utc))
    }
    created = updated = unchanged = 0
    for event in events.values():
        result = store.upsert(event)
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
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
        content_hash=content_hash,
    )
    return SyncResult(
        downloaded=True,
        created=created,
        updated=updated,
        unchanged=unchanged,
    )
