"""Bounded orchestration and operational records for background enrichment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from berlin_events_explorer.artist_enrichment import (
    DEFAULT_MUSICBRAINZ_FETCH_LIMIT,
    DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    MAX_MUSICBRAINZ_FETCH_LIMIT,
    MusicBrainzArtistProvider,
    open_musicbrainz_cache,
)
from berlin_events_explorer.artist_homepage_ingestion import enrich_artist_homepages
from berlin_events_explorer.artist_ingestion import enrich_artists
from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.storage import EventStore, WorkerRun
from berlin_events_explorer.sync import open_sync_cache
from berlin_events_explorer.venue_enrichment import DEFAULT_AUTO_APPROVE_THRESHOLD
from berlin_events_explorer.venue_ingestion import sync_source_and_ingest_venues

WorkerPhase = Callable[[], dict[str, Any]]


def _get_musicbrainz_fetch_limit(
    store: EventStore, fallback: int = DEFAULT_MUSICBRAINZ_FETCH_LIMIT
) -> int:
    """Return a persisted safe MusicBrainz artist batch size."""

    configured = store.get_setting("musicbrainz_fetch_limit")
    if (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and 1 <= configured <= MAX_MUSICBRAINZ_FETCH_LIMIT
    ):
        return configured
    return fallback


def _get_musicbrainz_metadata_fetch_limit(
    store: EventStore, fallback: int = DEFAULT_MUSICBRAINZ_FETCH_LIMIT
) -> int:
    """Return a persisted safe MusicBrainz metadata batch size."""

    configured = store.get_setting("musicbrainz_metadata_fetch_limit")
    if (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and 1 <= configured <= MAX_MUSICBRAINZ_FETCH_LIMIT
    ):
        return configured
    return fallback


def run_worker(
    store: EventStore,
    *,
    sync_phase: WorkerPhase,
    artist_phase: WorkerPhase,
    homepage_phase: WorkerPhase,
) -> WorkerRun:
    """Execute one serial enrichment pass and persist its terminal outcome."""

    active_run = store.start_worker_run()
    summary: dict[str, Any] = {}
    try:
        summary["sync"] = sync_phase()
        summary["artist_enrichment"] = artist_phase()
        summary["homepage_enrichment"] = homepage_phase()
    except Exception as exc:
        store.finish_worker_run(
            active_run.id,
            status="failed",
            summary=summary,
            error=str(exc),
        )
        raise
    return store.finish_worker_run(
        active_run.id,
        status="succeeded",
        summary=summary,
    )


def run_default_worker(
    store: EventStore,
    *,
    artist_limit: int | None,
    homepage_limit: int | None,
    musicbrainz_cache_dir: Path | None = None,
    musicbrainz_request_interval_seconds: float = (
        DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS
    ),
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
) -> WorkerRun:
    """Run the production worker pipeline using safe bounded provider batches."""

    artist_limit = (
        artist_limit
        if artist_limit is not None
        else _get_musicbrainz_fetch_limit(store)
    )
    homepage_limit = (
        homepage_limit
        if homepage_limit is not None
        else _get_musicbrainz_metadata_fetch_limit(store)
    )

    with (
        httpx.Client(timeout=30.0, follow_redirects=True) as client,
        open_sync_cache() as sync_cache,
        open_musicbrainz_cache(musicbrainz_cache_dir) as musicbrainz_cache,
    ):
        artist_provider = MusicBrainzArtistProvider(
            client,
            cache=musicbrainz_cache,
            request_interval_seconds=musicbrainz_request_interval_seconds,
        )

        def sync_phase() -> dict[str, Any]:
            sync_result, venue_result = sync_source_and_ingest_venues(
                MyTrueIntentSource(),
                store,
                client,
                http_cache=sync_cache,
                auto_approve_threshold=auto_approve_threshold,
            )
            return {
                "events": asdict(sync_result),
                "venues": asdict(venue_result),
            }

        def artist_phase() -> dict[str, Any]:
            return asdict(
                enrich_artists(
                    store,
                    artist_provider,
                    limit=artist_limit,
                    auto_approve_threshold=1.0,
                )
            )

        def homepage_phase() -> dict[str, Any]:
            return asdict(
                enrich_artist_homepages(
                    store,
                    artist_provider,
                    limit=homepage_limit,
                )
            )

        return run_worker(
            store,
            sync_phase=sync_phase,
            artist_phase=artist_phase,
            homepage_phase=homepage_phase,
        )
