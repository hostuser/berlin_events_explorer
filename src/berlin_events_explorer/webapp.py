# webapp.py
#
# Copyright (c) 2026 Markus Binsteiner
# All rights reserved.
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License

"""Litestar web UI for Berlin Events Explorer."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from queue import Queue
from threading import Thread
from collections.abc import Mapping
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import AsyncIterator
import math

import httpx
from litestar import Litestar, Request, get, post
from litestar.params import FromPath, FromQuery
from litestar.response import Redirect, Response, Stream
from pydantic import ValidationError

from berlin_events_explorer.artist_enrichment import (
    DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    MusicBrainzArtistProvider,
    open_musicbrainz_cache,
)
from berlin_events_explorer._version import version as PACKAGE_VERSION
from berlin_events_explorer.models import (
    ArtistCandidate,
    ArtistRecord,
    ArtistStatus,
    Event,
    VenueCandidate,
    VenueMetadata,
    VenueRecord,
    VenueStatus,
)
from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.sync import SyncError, open_sync_cache
from berlin_events_explorer.venue_enrichment import (
    DEFAULT_AUTO_APPROVE_THRESHOLD,
    NominatimVenueProvider,
    VenueDiscoveryError,
)
from berlin_events_explorer.venue_ingestion import (
    VenueProgress,
    VenueProgressCallback,
    sync_source_and_ingest_venues,
)
from berlin_events_explorer.venues import normalize_venue_name

DATASTAR_SCRIPT = (
    "https://cdn.jsdelivr.net/gh/starfederation/datastar"
    "@v1.0.0-RC.7/bundles/datastar.js"
)
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
DEFAULT_SYNC_INTERVAL = timedelta(hours=1)
logger = logging.getLogger(__name__)


def _run_git(*args: str) -> str | None:
    """Return trimmed output from Git in the current source checkout."""

    repository = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _get_app_version() -> str:
    """Return the release tag or commit identity for the running application."""

    tag = _run_git("describe", "--tags", "--exact-match", "HEAD")
    if tag:
        return tag
    commit = _run_git("rev-parse", "--short=12", "HEAD")
    if commit:
        return f"git:{commit}"
    return PACKAGE_VERSION


def _form_string(form: Mapping[str, object], key: str) -> str:
    """Return a stripped string from a parsed HTML form."""

    value = form.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _candidate_key(candidate: VenueCandidate) -> str:
    """Build a stable form/query key for one cached venue suggestion."""

    return _candidate_key_from_parts(
        candidate.provider, candidate.osm_type, candidate.osm_id
    )


def _candidate_key_from_parts(provider: str, osm_type: str, osm_id: str) -> str:
    """Build a suggestion key from provider identity components."""

    return (
        f"{provider}:{osm_type}:{osm_id}" if all((provider, osm_type, osm_id)) else ""
    )


def _select_candidate(
    candidates: list[VenueCandidate], candidate_key: str | None
) -> VenueCandidate | None:
    """Select an explicit suggestion, falling back to the highest-ranked one."""

    if candidate_key:
        return next(
            (
                candidate
                for candidate in candidates
                if _candidate_key(candidate) == candidate_key
            ),
            None,
        )
    return candidates[0] if candidates else None


def _approve_edited_venue(
    store: EventStore,
    *,
    venue_id: str,
    form: Mapping[str, object],
    provider: str | None,
    osm_type: str | None,
    osm_id: str | None,
) -> VenueRecord:
    """Validate and persist reviewer-edited venue fields as approved metadata."""

    current = store.get_venue(venue_id)
    if current is None:
        raise ValueError(f"Unknown venue: {venue_id}")
    candidate: VenueCandidate | None = None
    if provider and osm_type and osm_id:
        candidate = next(
            (
                item
                for item in store.list_venue_candidates(venue_id)
                if (item.provider, item.osm_type, item.osm_id)
                == (provider, osm_type, osm_id)
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                f"Unknown venue candidate: {venue_id}/{provider}/{osm_type}/{osm_id}"
            )
        base = current.model_copy(
            update={
                "address": candidate.address,
                "postal_code": candidate.postal_code,
                "website": candidate.website,
                "latitude": candidate.latitude,
                "longitude": candidate.longitude,
                "osm_type": candidate.osm_type,
                "osm_id": candidate.osm_id,
                "last_checked_at": candidate.retrieved_at,
            }
        )
    else:
        base = current

    name = _form_string(form, "name")
    if not name:
        raise ValueError("Venue name cannot be blank.")
    values = base.model_dump(mode="python")
    values.update(
        {
            "name": name,
            "normalized_name": normalize_venue_name(name),
            "address": _form_string(form, "address") or None,
            "postal_code": _form_string(form, "postal_code") or None,
            "city": _form_string(form, "city") or None,
            "country": _form_string(form, "country") or None,
            "website": _form_string(form, "website") or None,
            "status": VenueStatus.VERIFIED,
        }
    )
    validated = VenueRecord.model_validate(values)
    if candidate is not None:
        store.select_venue_candidate(
            venue_id, provider or "", osm_type or "", osm_id or ""
        )
    approved = store.upsert_venue(validated)
    now = datetime.now(UTC)
    for field in ("name", "address", "postal_code", "city", "country", "website"):
        value = getattr(approved, field)
        if value is not None:
            store.save_venue_metadata(
                VenueMetadata(
                    venue_id=venue_id,
                    field=field,
                    value=value,
                    provider="manual-review",
                    confidence=1.0,
                    retrieved_at=now,
                )
            )
    return approved


async def _periodic_sync(
    *,
    store: EventStore,
    interval: timedelta,
    stop_event: asyncio.Event,
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
) -> None:
    """Sync periodically until the application requests shutdown."""

    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval.total_seconds())
        except TimeoutError:
            pass
        else:
            return

        try:
            await asyncio.to_thread(
                perform_sync,
                store,
                auto_approve_threshold=_get_auto_approve_threshold(
                    store, auto_approve_threshold
                ),
            )
        except Exception:
            logger.exception("Scheduled event sync failed")


def create_app(
    database: Path | str = Path("events.sqlite"),
    *,
    sync_interval: timedelta | None = DEFAULT_SYNC_INTERVAL,
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
    environment: str = "production",
) -> Litestar:
    """Create a Litestar app that renders stored events as HTML."""

    store = EventStore(database)
    if environment not in {"development", "production"}:
        raise ValueError("environment must be 'development' or 'production'")
    if store.get_setting("auto_approve_threshold") is None:
        store.set_setting("auto_approve_threshold", auto_approve_threshold)
    if store.get_setting("musicbrainz_request_interval_seconds") is None:
        store.set_setting(
            "musicbrainz_request_interval_seconds",
            DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
        )

    @get("/", sync_to_thread=True)
    def index(
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        tab: str = "recent",
        recent_days: int = 7,
    ) -> Response:
        all_events = list(store.list_events())
        normalized_days = _normalize_recent_days(recent_days)
        events = _events_for_tab(all_events, tab=tab, recent_days=normalized_days)
        paged_events, current_page, normalized_page_size, total_pages = (
            _paginate_events(events, page=page, page_size=page_size)
        )
        venue_ids_by_event = store.get_venue_ids_for_events(
            [event.id for event in paged_events]
        )
        artist_ids_by_event_performer = _verified_artist_ids_by_event_performer(
            store, [event.id for event in paged_events]
        )
        html = render_events_page(
            paged_events,
            total_count=len(events),
            page=current_page,
            page_size=normalized_page_size,
            total_pages=total_pages,
            tab=tab,
            recent_days=normalized_days,
            venue_ids_by_event=venue_ids_by_event,
            artist_ids_by_event_performer=artist_ids_by_event_performer,
        )
        return Response(content=html, media_type="text/html")

    @get("/venues/{venue_id:str}", sync_to_thread=True)
    def venue_detail(venue_id: str) -> Response:
        """Render one canonical venue and its associated events."""

        venue = store.get_venue(venue_id)
        if venue is None:
            return Response(
                content="<h1>Venue not found</h1>",
                media_type="text/html",
                status_code=404,
            )
        return Response(
            content=_render_venue_detail_page(
                venue, store.list_events_for_venue(venue_id)
            ),
            media_type="text/html",
        )

    @get("/artists/{artist_id:str}", sync_to_thread=True)
    def artist_detail(artist_id: str) -> Response:
        """Render a public artist page only after identity approval."""

        artist = store.get_artist(artist_id)
        if artist is None or artist.status is not ArtistStatus.VERIFIED:
            return Response(
                content="<h1>Artist not found</h1>",
                media_type="text/html",
                status_code=404,
            )
        return Response(
            content=_render_artist_detail_page(
                artist,
                store.list_events_for_artist(artist_id),
                homepage=store.get_artist_official_homepage(artist_id),
            ),
            media_type="text/html",
        )

    @get("/approvals", sync_to_thread=True)
    def approvals(entity_type: str = "all") -> Response:
        """Render every canonical entity still waiting for editorial approval."""

        pending_venues = [
            venue
            for venue in store.list_venues()
            if venue.status
            not in {VenueStatus.VERIFIED, VenueStatus.NOT_A_VENUE, VenueStatus.REJECTED}
        ]
        candidate_counts = {
            venue.id: len(store.list_venue_candidates(venue.id))
            for venue in pending_venues
        }
        pending_artists = [
            artist
            for artist in store.list_artists()
            if artist.status in {ArtistStatus.UNRESOLVED, ArtistStatus.CANDIDATE}
        ]
        artist_candidate_counts = {
            artist.id: len(store.list_artist_candidates(artist.id))
            for artist in pending_artists
        }
        normalized_entity_type = (
            entity_type if entity_type in {"all", "venues", "artists"} else "all"
        )
        return Response(
            content=_render_approval_queue(
                pending_venues,
                candidate_counts,
                pending_artists,
                artist_candidate_counts,
                entity_type=normalized_entity_type,
            ),
            media_type="text/html",
        )

    @get("/approvals/venues/{venue_id:str}", sync_to_thread=False)
    def venue_approval(
        venue_id: FromPath[str], candidate_key: FromQuery[str | None] = None
    ) -> Response:
        """Render a venue-specific approval form and its available suggestions."""

        venue = store.get_venue(venue_id)
        if venue is None:
            return Response(
                "<h1>Venue not found</h1>", media_type="text/html", status_code=404
            )
        candidates = store.list_venue_candidates(venue_id)
        selected = _select_candidate(candidates, candidate_key)
        return Response(
            content=_render_venue_approval_form(venue, candidates, selected),
            media_type="text/html",
        )

    @post("/approvals/venues/{venue_id:str}")
    async def approve_venue(
        venue_id: FromPath[str], request: Request
    ) -> Redirect | Response:
        """Approve the venue using the values currently submitted by its form."""

        form = await request.form()
        action = _form_string(form, "action")
        provider = _form_string(form, "provider")
        osm_type = _form_string(form, "osm_type")
        osm_id = _form_string(form, "osm_id")
        try:
            if action == "approve":
                _approve_edited_venue(
                    store,
                    venue_id=venue_id,
                    form=form,
                    provider=provider or None,
                    osm_type=osm_type or None,
                    osm_id=osm_id or None,
                )
            else:
                raise ValueError("Unsupported approval action.")
        except (ValueError, ValidationError) as exc:
            venue = store.get_venue(venue_id)
            if venue is None:
                return Response(
                    "<h1>Venue not found</h1>", media_type="text/html", status_code=404
                )
            candidates = store.list_venue_candidates(venue_id)
            selected = _select_candidate(
                candidates,
                _candidate_key_from_parts(provider, osm_type, osm_id),
            )
            return Response(
                content=_render_venue_approval_form(
                    venue, candidates, selected, error=str(exc)
                ),
                media_type="text/html",
                status_code=400,
            )
        return Redirect("/approvals", status_code=303)

    @post("/approvals/venues/{venue_id:str}/discover", sync_to_thread=True)
    def discover_venue(venue_id: FromPath[str]) -> Redirect | Response:
        """Explicitly discover candidate metadata for one pending venue."""

        venue = store.get_venue(venue_id)
        if venue is None:
            return Response(
                "<h1>Venue not found</h1>", media_type="text/html", status_code=404
            )
        try:
            with httpx.Client(follow_redirects=True) as client:
                candidates = NominatimVenueProvider(client).discover(venue)
        except VenueDiscoveryError as exc:
            return Response(
                content=_render_venue_approval_form(
                    venue,
                    store.list_venue_candidates(venue_id),
                    None,
                    error=str(exc),
                ),
                media_type="text/html",
                status_code=502,
            )
        store.record_venue_candidates(candidates)
        if candidates:
            store.upsert_venue(
                venue.model_copy(update={"status": VenueStatus.CANDIDATE})
            )
        return Redirect(f"/approvals/venues/{venue_id}", status_code=303)

    @get("/approvals/artists/{artist_id:str}", sync_to_thread=False)
    def artist_approval(artist_id: FromPath[str]) -> Response:
        """Render a review form for one canonical artist's candidate identities."""

        artist = store.get_artist(artist_id)
        if artist is None:
            return Response(
                "<h1>Artist not found</h1>", media_type="text/html", status_code=404
            )
        return Response(
            content=_render_artist_approval_form(
                artist, store.list_artist_candidates(artist_id)
            ),
            media_type="text/html",
        )

    @post("/approvals/artists/{artist_id:str}")
    async def approve_artist(
        artist_id: FromPath[str], request: Request
    ) -> Redirect | Response:
        """Select an explicitly reviewed MusicBrainz identity."""

        form = await request.form()
        candidate_id = _form_string(form, "candidate")
        try:
            if not candidate_id:
                raise ValueError("Select an artist candidate before approving.")
            store.select_artist_candidate(artist_id, "musicbrainz", candidate_id)
        except ValueError as exc:
            artist = store.get_artist(artist_id)
            if artist is None:
                return Response(
                    "<h1>Artist not found</h1>", media_type="text/html", status_code=404
                )
            return Response(
                content=_render_artist_approval_form(
                    artist, store.list_artist_candidates(artist_id), error=str(exc)
                ),
                media_type="text/html",
                status_code=400,
            )
        return Redirect("/approvals?entity_type=artists", status_code=303)

    @post("/approvals/artists/{artist_id:str}/discover", sync_to_thread=True)
    def discover_artist(artist_id: FromPath[str]) -> Redirect | Response:
        """Explicitly fetch or rehydrate candidate identities for one artist."""

        artist = store.get_artist(artist_id)
        if artist is None:
            return Response(
                "<h1>Artist not found</h1>", media_type="text/html", status_code=404
            )
        interval = _get_musicbrainz_request_interval(store)
        try:
            with (
                httpx.Client(follow_redirects=True) as client,
                open_musicbrainz_cache() as cache,
            ):
                candidates = MusicBrainzArtistProvider(
                    client, cache=cache, request_interval_seconds=interval
                ).discover(artist)
        except Exception as exc:
            return Response(
                content=_render_artist_approval_form(
                    artist, store.list_artist_candidates(artist_id), error=str(exc)
                ),
                media_type="text/html",
                status_code=502,
            )
        store.record_artist_candidates(candidates)
        if candidates:
            store.upsert_artist(
                artist.model_copy(update={"status": ArtistStatus.CANDIDATE})
            )
        return Redirect(f"/approvals/artists/{artist_id}", status_code=303)

    @post("/sync", status_code=200, sync_to_thread=True)
    def sync(
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        tab: str = "recent",
        recent_days: int = 7,
    ) -> Stream:
        return Stream(
            content=_perform_sync_stream(
                store,
                page=page,
                page_size=page_size,
                tab=tab,
                recent_days=recent_days,
                auto_approve_threshold=_get_auto_approve_threshold(
                    store, auto_approve_threshold
                ),
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @get("/settings", sync_to_thread=False)
    def settings(
        saved: FromQuery[str | None] = None,
        cleared: FromQuery[str | None] = None,
    ) -> Response:
        """Render persisted application configuration and development tools."""

        return Response(
            content=_render_settings_page(
                threshold=_get_auto_approve_threshold(store, auto_approve_threshold),
                musicbrainz_request_interval=_get_musicbrainz_request_interval(store),
                environment=environment,
                version=_get_app_version(),
                saved=saved == "1",
                cleared=cleared == "1",
            ),
            media_type="text/html",
        )

    @post("/settings")
    async def save_settings(request: Request) -> Redirect | Response:
        """Validate and persist settings used by subsequent synchronization passes."""

        form = await request.form()
        raw_threshold = _form_string(form, "auto_approve_threshold")
        raw_interval = _form_string(form, "musicbrainz_request_interval_seconds")
        try:
            threshold = float(raw_threshold)
            interval = (
                float(raw_interval)
                if raw_interval
                else _get_musicbrainz_request_interval(store)
            )
            if not math.isfinite(threshold) or not 0 <= threshold <= 1:
                raise ValueError
            if not math.isfinite(interval) or not 1.0 <= interval <= 300:
                raise ValueError
        except ValueError:
            return Response(
                content=_render_settings_page(
                    threshold=_get_auto_approve_threshold(
                        store, auto_approve_threshold
                    ),
                    environment=environment,
                    error="Confidence threshold must be a number between 0 and 1; MusicBrainz pacing must be 1–300 seconds.",
                ),
                media_type="text/html",
                status_code=400,
            )
        store.set_setting("auto_approve_threshold", threshold)
        store.set_setting("musicbrainz_request_interval_seconds", interval)
        return Redirect("/settings?saved=1", status_code=303)

    @post("/settings/clear-database", sync_to_thread=True)
    def clear_database() -> Redirect | Response:
        """Clear synchronized data when this app explicitly runs as development."""

        if environment != "development":
            return Response("Not found", status_code=404)
        store.clear_application_data()
        return Redirect("/settings?cleared=1", status_code=303)

    @get("/health", sync_to_thread=False)
    def health() -> dict[str, str]:
        """Health check endpoint for container and deployment tooling."""

        return {"status": "ok"}

    if sync_interval is not None and sync_interval <= timedelta():
        raise ValueError("sync_interval must be positive or None")

    @asynccontextmanager
    async def periodic_sync_lifespan(_: Litestar) -> AsyncIterator[None]:
        if sync_interval is None:
            yield
            return

        stop_event = asyncio.Event()
        task = asyncio.create_task(
            _periodic_sync(
                store=store,
                interval=sync_interval,
                stop_event=stop_event,
                auto_approve_threshold=auto_approve_threshold,
            ),
            name="berlin-events-periodic-sync",
        )
        try:
            yield
        finally:
            stop_event.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return Litestar(
        route_handlers=[
            index,
            venue_detail,
            artist_detail,
            approvals,
            venue_approval,
            approve_venue,
            discover_venue,
            artist_approval,
            approve_artist,
            discover_artist,
            sync,
            settings,
            save_settings,
            clear_database,
            health,
        ],
        lifespan=[periodic_sync_lifespan],
    )


def _get_auto_approve_threshold(store: EventStore, fallback: float) -> float:
    """Return the persisted threshold, falling back to process configuration."""

    configured = store.get_setting("auto_approve_threshold")
    if isinstance(configured, (int, float)) and not isinstance(configured, bool):
        threshold = float(configured)
        if math.isfinite(threshold) and 0 <= threshold <= 1:
            return threshold
    return fallback


def _get_musicbrainz_request_interval(store: EventStore) -> float:
    """Return persisted safe MusicBrainz pacing, falling back to the public default."""

    configured = store.get_setting("musicbrainz_request_interval_seconds")
    if isinstance(configured, (int, float)) and not isinstance(configured, bool):
        interval = float(configured)
        if math.isfinite(interval) and 1.0 <= interval <= 300:
            return interval
    return DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS


def _render_settings_page(
    *,
    threshold: float,
    musicbrainz_request_interval: float = DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    environment: str,
    version: str | None = None,
    saved: bool = False,
    cleared: bool = False,
    error: str | None = None,
) -> str:
    """Render operational settings with a development-only destructive action."""

    display_version = version or _get_app_version()
    notices = ""
    if saved:
        notices += '<p class="notice success">Settings saved.</p>'
    if cleared:
        notices += '<p class="notice success">Development database cleared.</p>'
    if error:
        notices += f'<p class="notice error">{escape(error)}</p>'
    reset = (
        """
        <section class="settings-card danger-zone">
          <p class="section-label">Development tools</p>
          <h2>Clear application data</h2>
          <p>Remove events, venues, suggestions, provenance, logs, and sync state. Your settings remain.</p>
          <form method="post" action="/settings/clear-database"
            onsubmit="return confirm('Clear all development data? This cannot be undone.');">
            <button class="danger-button" type="submit">Clear development database</button>
          </form>
        </section>
        """
        if environment == "development"
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Settings · Berlin Events Explorer</title>
    <style>
      :root {{ --ink:#111827; --muted:#64748b; --line:#dbe1ea; --paper:#f6f7fb;
        --card:#fff; --blue:#1d4ed8; --danger:#b42318; --danger-soft:#fff1f0; }}
      * {{ box-sizing:border-box; }}
      body {{ margin:0; color:var(--ink); background:var(--paper);
        font-family:Inter,"Segoe UI",sans-serif; }}
      main {{ width:min(760px,calc(100% - 2rem)); margin:0 auto; padding:2rem 0 4rem; }}
      a {{ color:var(--blue); }}
      .settings-header {{ display:flex; justify-content:space-between; align-items:flex-start;
        gap:1rem; margin-bottom:1.5rem; }}
      .kicker,.section-label {{ margin:0 0 .35rem; color:var(--muted); font-size:.76rem;
        font-weight:750; letter-spacing:.09em; text-transform:uppercase; }}
      h1 {{ margin:0; font-size:clamp(2rem,6vw,3.2rem); letter-spacing:-.045em; }}
      h2 {{ margin:.1rem 0 .55rem; font-size:1.25rem; }}
      .back-link {{ white-space:nowrap; margin-top:.4rem; }}
      .settings-stack {{ display:grid; gap:1rem; }}
      .settings-card {{ padding:1.25rem; border:1px solid var(--line); border-radius:1rem;
        background:var(--card); box-shadow:0 18px 50px rgba(15,23,42,.06); }}
      label {{ display:block; margin-top:1rem; font-weight:700; }}
      input {{ display:block; width:min(14rem,100%); margin:.4rem 0 .3rem; padding:.72rem .8rem;
        border:1px solid #b9c2d0; border-radius:.65rem; font:inherit; }}
      .hint,.settings-card p {{ color:var(--muted); line-height:1.55; }}
      button {{ margin-top:.8rem; padding:.72rem 1rem; border:0; border-radius:.65rem;
        background:var(--blue); color:#fff; font:inherit; font-weight:750; cursor:pointer; }}
      input:focus,a:focus,button:focus {{ outline:3px solid #bfdbfe; outline-offset:2px; }}
      .notice {{ padding:.8rem 1rem; border-radius:.7rem; font-weight:650; }}
      .notice.success {{ color:#05603a; background:#dcfce7; }}
      .notice.error {{ color:var(--danger); background:#fee4e2; }}
      .danger-zone {{ border-color:#f4b8b3; background:var(--danger-soft); }}
      .danger-zone .section-label,.danger-zone h2 {{ color:var(--danger); }}
      .danger-button {{ background:var(--danger); }}
      @media (max-width:560px) {{ .settings-header {{ display:block; }}
        .back-link {{ display:inline-block; margin-top:1rem; }} }}
    </style>
  </head>
  <body>
    <main>
      <header class="settings-header">
        <div><p class="kicker">Application controls</p><h1>Settings</h1></div>
        <a class="back-link" href="/">← Back to events</a>
      </header>
      {notices}
      <div class="settings-stack">
        <section class="settings-card">
          <p class="section-label">Venue enrichment</p>
          <h2>Automatic approval</h2>
          <p>New venues bypass editorial review only when one unambiguous suggestion meets this confidence score.</p>
          <form method="post" action="/settings">
            <label for="threshold">Confidence threshold</label>
            <input id="threshold" name="auto_approve_threshold" type="number"
              min="0" max="1" step="0.01" required value="{threshold:g}" />
            <small class="hint">Use a value from 0 to 1. Higher values are stricter.</small>
            <label for="musicbrainz-interval">MusicBrainz request interval (seconds)</label>
            <input id="musicbrainz-interval" name="musicbrainz_request_interval_seconds" type="number"
              min="1" max="300" step="0.1" required value="{musicbrainz_request_interval:g}" />
            <small class="hint">Public MusicBrainz access requires at least one second between requests.</small>
            <br /><button type="submit">Save settings</button>
          </form>
        </section>
        <section class="settings-card">
          <p class="section-label">Application info</p>
          <h2>Berlin Events Explorer</h2>
          <p><strong>Version:</strong> {escape(display_version)}</p>
        </section>
        {reset}
      </div>
    </main>
  </body>
</html>"""


def _approval_styles() -> str:
    """Return shared styles for the editorial approval workflow."""

    return """
      :root { --surface:#fff; --soft:#f3f5f9; --text:#0f172a; --muted:#64748b;
        --primary:#2563eb; --line:#d5dbe8; --success:#047857; --danger:#b91c1c; }
      * { box-sizing: border-box; }
      body { margin:0; font-family:Inter,"Segoe UI",sans-serif; color:var(--text);
        background:linear-gradient(180deg,#f6f7fb 0%,#eef2ff 45%,#f8fafc 100%); }
      main { max-width:1100px; margin:0 auto; padding:2rem 1.25rem 3rem; }
      a { color:var(--primary); }
      .kicker { color:var(--primary); text-transform:uppercase; letter-spacing:.08em;
        font-size:.82rem; font-weight:700; }
      h1 { margin:.2rem 0 .5rem; }
      .muted { color:var(--muted); }
      .tabs { display:flex; gap:.35rem; margin:1.25rem 0; border-bottom:1px solid var(--line); }
      .tab { color:var(--muted); padding:.65rem .85rem; text-decoration:none;
        border-bottom:3px solid transparent; font-weight:600; }
      .tab:hover,.tab.active { color:var(--primary); border-bottom-color:var(--primary); }
      .card { background:var(--surface); border:1px solid var(--line); border-radius:.85rem;
        padding:1rem; box-shadow:0 16px 40px rgba(15,23,42,.06); }
      table { width:100%; border-collapse:collapse; }
      th,td { text-align:left; padding:.7rem .55rem; border-bottom:1px solid var(--line); }
      th { color:#334155; font-size:.86rem; }
      .status { display:inline-block; padding:.18rem .55rem; border-radius:999px;
        background:#e0e7ff; color:#3730a3; font-size:.78rem; }
      .suggestions { display:grid; gap:.7rem; margin:1rem 0; }
      .suggestion { display:block; border:1px solid var(--line); border-radius:.7rem;
        padding:.85rem; text-decoration:none; color:var(--text); background:var(--surface); }
      .suggestion.selected { border-color:var(--primary); box-shadow:0 0 0 2px #bfdbfe; }
      .form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.85rem; }
      .field-wide { grid-column:1 / -1; }
      label { display:block; color:#334155; font-size:.85rem; font-weight:650; }
      input { width:100%; margin-top:.3rem; padding:.65rem .7rem; border:1px solid var(--line);
        border-radius:.55rem; color:var(--text); background:#fff; }
      input:focus,a:focus,button:focus { outline:3px solid #bfdbfe; outline-offset:2px; }
      .actions { display:flex; flex-wrap:wrap; gap:.65rem; margin-top:1rem; }
      button { border:0; border-radius:.6rem; padding:.65rem .95rem; font-weight:700;
        cursor:pointer; background:var(--primary); color:#fff; }
      button.secondary { background:#e2e8f0; color:#0f172a; }
      .error { color:var(--danger); background:#fee2e2; border-radius:.55rem; padding:.7rem; }
      @media (max-width:720px) { .form-grid { grid-template-columns:1fr; }
        .field-wide { grid-column:auto; } main { padding:1rem .75rem 2rem; }
        table,thead,tbody,tr,th,td { display:block; } thead { display:none; }
        tr { border-bottom:1px solid var(--line); padding:.5rem 0; } td { border:0; } }
    """


def _approval_nav() -> str:
    """Render the top-level views with approval state selected."""

    return (
        '<nav class="tabs" aria-label="Application views">'
        '<a class="tab" href="/?tab=recent">Recently added</a>'
        '<a class="tab" href="/?tab=upcoming">Upcoming</a>'
        '<a class="tab active" href="/approvals">Awaiting approval</a>'
        "</nav>"
    )


def _render_approval_queue(
    venues: list[VenueRecord],
    venue_candidate_counts: dict[str, int],
    artists: list[ArtistRecord],
    artist_candidate_counts: dict[str, int],
    *,
    entity_type: str,
) -> str:
    """Render a filterable queue of venues and artists needing review."""

    venue_rows = "".join(
        "<tr>"
        '<td><span class="status">Venue</span></td>'
        f'<td><a href="/approvals/venues/{escape(venue.id)}">{escape(venue.name)}</a></td>'
        f"<td>{escape(venue.status.value.replace('_', ' ').title())}</td>"
        f"<td>{venue_candidate_counts.get(venue.id, 0)} "
        f"{'suggestion' if venue_candidate_counts.get(venue.id, 0) == 1 else 'suggestions'}</td>"
        "</tr>"
        for venue in venues
    )
    artist_rows = "".join(
        "<tr>"
        '<td><span class="status">Artist</span></td>'
        f'<td><a href="/approvals/artists/{escape(artist.id)}">{escape(artist.name)}</a></td>'
        f"<td>{escape(artist.status.value.replace('_', ' ').title())}</td>"
        f"<td>{artist_candidate_counts.get(artist.id, 0)} "
        f"{'suggestion' if artist_candidate_counts.get(artist.id, 0) == 1 else 'suggestions'}</td>"
        "</tr>"
        for artist in artists
    )
    rows = (
        venue_rows
        if entity_type == "venues"
        else artist_rows
        if entity_type == "artists"
        else venue_rows + artist_rows
    )
    empty = '<p class="muted">Nothing is waiting for approval.</p>' if not rows else ""
    tabs = "".join(
        f'<a class="tab{" active" if selected else ""}" href="/approvals?entity_type={value}">{label}</a>'
        for value, label, selected in (
            ("all", "All", entity_type == "all"),
            ("venues", "Venues", entity_type == "venues"),
            ("artists", "Artists", entity_type == "artists"),
        )
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Awaiting approval · Berlin Events Explorer</title><style>{_approval_styles()}</style></head>
<body><main><p class="kicker">Editorial queue</p><h1>Awaiting approval</h1>
<p class="muted">Review suggested metadata before it appears as verified information.</p>
{_approval_nav()}<nav class="tabs" aria-label="Entity filters">{tabs}</nav>
<section class="card">{empty}<table><thead><tr><th>Type</th><th>Name</th>
<th>Status</th><th>Suggestions</th></tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""


def _venue_field(
    name: str, label: str, value: str | None, *, wide: bool = False
) -> str:
    """Render one safely escaped editable venue field."""

    css_class = ' class="field-wide"' if wide else ""
    input_type = "url" if name == "website" else "text"
    return (
        f"<label{css_class}>{escape(label)}"
        f'<input type="{input_type}" name="{escape(name)}" '
        f'value="{escape(value or "", quote=True)}" /></label>'
    )


def _render_venue_approval_form(
    venue: VenueRecord,
    candidates: list[VenueCandidate],
    selected: VenueCandidate | None,
    *,
    error: str | None = None,
) -> str:
    """Render candidate selection and one approval action for current form values."""

    suggestions = "".join(
        f'<a class="suggestion{" selected" if candidate == selected else ""}" '
        f'href="/approvals/venues/{escape(venue.id)}?candidate_key={escape(_candidate_key(candidate), quote=True)}">'
        f"<strong>{escape(candidate.display_name)}</strong><br>"
        f'<span class="muted">{escape(candidate.address or "No address suggested")} · '
        f"{escape(candidate.website or 'No homepage suggested')} · "
        f"confidence {candidate.confidence:.2f}</span></a>"
        for candidate in candidates
    )
    if not suggestions:
        suggestions = '<p class="muted">No suggestions have been discovered yet.</p>'

    base_address = selected.address if selected else venue.address
    base_postal_code = selected.postal_code if selected else venue.postal_code
    base_website = selected.website if selected else venue.website
    hidden = (
        f'<input type="hidden" name="provider" value="{escape(selected.provider, quote=True)}" />'
        f'<input type="hidden" name="osm_type" value="{escape(selected.osm_type, quote=True)}" />'
        f'<input type="hidden" name="osm_id" value="{escape(selected.osm_id, quote=True)}" />'
        if selected
        else ""
    )

    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Approve {escape(venue.name)} · Berlin Events Explorer</title>
<style>{_approval_styles()}</style></head><body><main>
<p><a href="/approvals">← Back to approval queue</a></p><p class="kicker">Venue approval</p>
<h1>{escape(venue.name)}</h1><p class="muted">Choose a suggestion or enter the venue details manually, then review and approve the form.</p>
{error_html}<h2>Suggestions</h2><div class="suggestions">{suggestions}</div>
<form method="post" action="/approvals/venues/{escape(venue.id)}" class="card">
{hidden}<div class="form-grid">
{_venue_field("name", "Venue name", venue.name, wide=True)}
{_venue_field("address", "Address", base_address, wide=True)}
{_venue_field("postal_code", "Postal code", base_postal_code)}
{_venue_field("city", "City", venue.city)}
{_venue_field("country", "Country code", venue.country)}
{_venue_field("website", "Homepage", base_website, wide=True)}
</div><div class="actions">
<button type="submit" name="action" value="approve">Approve</button>
</div></form>
<form method="post" action="/approvals/venues/{escape(venue.id)}/discover" class="actions">
<button type="submit" class="secondary">Find or refresh suggestions</button></form>
</main></body></html>"""


def _render_artist_approval_form(
    artist: ArtistRecord,
    candidates: list[ArtistCandidate],
    *,
    error: str | None = None,
) -> str:
    """Render candidate identity evidence with an explicit approval action."""

    options = (
        "".join(
            f'<label class="suggestion"><input type="radio" name="candidate" '
            f'value="{escape(candidate.musicbrainz_id, quote=True)}" required> '
            f"<strong>{escape(candidate.display_name)}</strong> · "
            f"{escape(candidate.artist_type or 'Unknown type')} · "
            f"{escape(candidate.country or 'Unknown country')} · score {candidate.confidence:.2f}<br>"
            f'<a href="{escape(candidate.source_url, quote=True)}" target="_blank" rel="noopener noreferrer">MusicBrainz</a>'
            "</label>"
            for candidate in candidates
        )
        or '<p class="muted">No candidates have been discovered yet.</p>'
    )
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Approve {escape(artist.name)} · Berlin Events Explorer</title><style>{_approval_styles()}</style></head>
<body><main><p><a href="/approvals?entity_type=artists">← Back to artist queue</a></p>
<p class="kicker">Artist approval</p><h1>{escape(artist.name)}</h1>
<p class="muted">Select the verified MusicBrainz identity before it appears publicly.</p>{error_html}
<form method="post" action="/approvals/artists/{escape(artist.id)}" class="card">
<div class="suggestions">{options}</div><div class="actions"><button type="submit">Approve</button></div></form>
<form method="post" action="/approvals/artists/{escape(artist.id)}/discover" class="actions">
<button type="submit" class="secondary">Find or refresh suggestions</button></form>
</main></body></html>"""


def _render_artist_detail_page(
    artist: ArtistRecord, events: list[Event], *, homepage: str | None = None
) -> str:
    """Render verified canonical artist metadata and associated events."""

    identity = (
        f'<a href="{escape(artist.musicbrainz_url, quote=True)}" target="_blank" rel="noopener noreferrer">MusicBrainz</a>'
        if artist.musicbrainz_url
        else ""
    )
    homepage_link = (
        f'<a href="{escape(homepage, quote=True)}" target="_blank" '
        'rel="noopener noreferrer">Official homepage</a>'
        if homepage
        else ""
    )
    details = (
        " · ".join(
            escape(value)
            for value in (artist.artist_type, artist.country, artist.disambiguation)
            if value
        )
        or "Verified artist"
    )
    genres = ", ".join(escape(genre) for genre in artist.genres) or "Not listed"
    event_items = (
        "".join(
            f"<li>{escape(event.start_date.isoformat() if event.start_date else 'TBA')} — {escape(event.title)}</li>"
            for event in events
        )
        or "<li>No associated events yet.</li>"
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{escape(artist.name)} · Berlin Events Explorer</title><style>
body {{ margin:0; font-family:Inter,"Segoe UI",sans-serif; background:#f6f7fb; color:#0f172a; }}
main {{ max-width:760px; margin:0 auto; padding:2rem 1.25rem 3rem; }} a {{ color:#1d4ed8; }}
.card {{ background:#fff; border:1px solid #d5dbe8; border-radius:.85rem; padding:1.25rem; }}
</style></head><body><main><p><a href="/">← Back to events</a></p><section class="card">
<p>Berlin artist</p><h1>{escape(artist.name)}</h1><p>{details}</p><p><strong>Genres:</strong> {genres}</p><p>{homepage_link}</p><p>{identity}</p>
</section><section><h2>Events</h2><ul>{event_items}</ul></section></main></body></html>"""


def render_events_page(
    events: list[Event],
    *,
    total_count: int,
    page: int,
    page_size: int,
    total_pages: int,
    tab: str = "upcoming",
    recent_days: int = 7,
    venue_ids_by_event: dict[str, str] | None = None,
    artist_ids_by_event_performer: dict[tuple[str, int], str] | None = None,
) -> str:
    """Render a full HTML page with the provided events."""

    styles = """ :root {
        --surface: #ffffff;
        --surface-soft: #f3f5f9;
        --text: #0f172a;
        --muted: #64748b;
        --primary: #3b82f6;
        --line: #d5dbe8;
        --danger: #dc2626;
        --radius-lg: 0.85rem;
      }

      body {
        margin: 0;
        min-height: 100vh;
        font-family: Inter, "Segoe UI", Roboto, sans-serif;
        background: linear-gradient(180deg, #f6f7fb 0%, #eef2ff 45%, #f8fafc 100%);
        color: var(--text);
      }

      .events-app {
        max-width: 1100px;
        margin: 0 auto;
        padding: 2rem 1.25rem 3rem;
      }

      .events-header {
        margin-bottom: 1rem;
      }

      .page-kicker {
        display: inline-block;
        margin: 0 0 0.3rem;
        font-size: 0.85rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--primary);
        font-weight: 650;
      }

      h1 {
        margin: 0;
        font-size: clamp(1.5rem, 2.6vw, 2.15rem);
        line-height: 1.2;
      }

      .toolbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.75rem;
        flex-wrap: wrap;
      }

      .toolbar-actions {
        display: flex;
        align-items: center;
        gap: 0.55rem;
      }

      .settings-link {
        display: inline-flex;
        align-items: center;
        min-height: 2.35rem;
        padding: 0.45rem 0.75rem;
        border: 1px solid var(--line);
        border-radius: var(--radius-lg);
        color: var(--text);
        background: var(--surface);
        text-decoration: none;
        font-weight: 600;
      }

      .settings-link:hover {
        border-color: #93c5fd;
        background: #eff6ff;
      }

      .sync-button {
        border: 1px solid transparent;
        padding: 0.5rem 1rem;
        border-radius: var(--radius-lg);
        background: linear-gradient(180deg, #2563eb 0%, #1d4ed8 100%);
        color: #ffffff;
        font-weight: 600;
        cursor: pointer;
        transition: transform 120ms ease, box-shadow 120ms ease;
      }

      .sync-button:hover {
        transform: translateY(-1px);
        box-shadow: 0 8px 22px rgba(37, 99, 235, 0.22);
      }

      .sync-button:disabled {
        filter: grayscale(0.25);
        cursor: not-allowed;
        box-shadow: none;
        transform: none;
      }

      .sync-error {
        color: var(--danger);
        min-height: 1.1rem;
        font-weight: 500;
      }

      .sync-progress {
        display: grid;
        gap: 0.45rem;
        margin: 0.75rem 0;
        color: var(--muted);
        font-size: 0.92rem;
      }

      .sync-progress p {
        margin: 0;
      }

      .sync-progress progress {
        width: min(34rem, 100%);
        height: 0.65rem;
        accent-color: var(--accent);
      }

      .tabs {
        display: flex;
        gap: 0.35rem;
        align-items: center;
        margin: 1.25rem 0 0.75rem;
        border-bottom: 1px solid var(--line);
      }

      .tab {
        color: var(--muted);
        padding: 0.65rem 0.85rem;
        text-decoration: none;
        border-bottom: 3px solid transparent;
        font-weight: 600;
      }

      .tab:hover,
      .tab.active {
        color: var(--primary);
        border-bottom-color: var(--primary);
      }

      .recent-settings {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin: 0 0 0.75rem;
        color: var(--muted);
        font-size: 0.9rem;
      }

      .recent-settings select {
        border: 1px solid var(--line);
        border-radius: 0.45rem;
        padding: 0.35rem 0.5rem;
        background: var(--surface);
        color: var(--text);
      }

      #events-panel {
        margin-top: 0.5rem;
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius-lg);
        padding: 0.9rem;
        box-shadow: 0 16px 40px rgba(15, 23, 42, 0.07);
      }

      .meta {
        color: var(--muted);
        font-size: 0.9rem;
        margin: 0.25rem 0 0.75rem;
      }

      .pagination {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin: 0.4rem 0 1rem;
      }

      .pagination-link {
        border-radius: 999px;
        border: 1px solid var(--line);
        color: var(--text);
        text-decoration: none;
        padding: 0.35rem 0.85rem;
        font-size: 0.9rem;
        background: var(--surface-soft);
      }

      .pagination-link:hover {
        background: #dbeafe;
      }

      .pagination-link.disabled {
        color: #94a3b8;
        pointer-events: none;
        background: #f8fafc;
      }

      .pagination-page {
        color: var(--muted);
        font-size: 0.9rem;
      }

      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.95rem;
      }

      thead th {
        font-weight: 650;
        color: #334155;
        text-align: left;
        border-bottom: 1px solid var(--line);
        padding: 0.65rem 0.5rem;
      }

      th,
      td {
        text-align: left;
        vertical-align: top;
        padding: 0.6rem 0.5rem;
        border-bottom: 1px solid var(--line);
      }

      tbody tr:hover td {
        background: #f8fafc;
      }

      tbody tr:last-child td {
        border-bottom: none;
      }

      @media (max-width: 720px) {
        .events-app {
          padding: 1rem 0.75rem 2rem;
        }

        .toolbar {
          align-items: stretch;
        }

        table,
        thead,
        tbody,
        tr,
        th,
        td {
          display: block;
        }

        thead {
          display: none;
        }

        tbody tr {
          margin-bottom: 0.7rem;
          border: 1px solid var(--line);
          border-radius: 0.7rem;
          overflow: hidden;
        }

        tbody tr td {
          padding: 0.45rem 0.65rem;
          border-bottom: 1px solid var(--line);
        }

        tbody tr td::before {
          content: attr(data-label);
          display: block;
          color: var(--muted);
          font-size: 0.78rem;
          margin-bottom: 0.2rem;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }

        tbody tr td:last-child {
          border-bottom: none;
        }
      }"""

    events_html = _render_events_panel(
        events,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        tab=tab,
        recent_days=recent_days,
        venue_ids_by_event=venue_ids_by_event,
        artist_ids_by_event_performer=artist_ids_by_event_performer,
    )

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Berlin Events Explorer</title>
    <script type="module" src="{DATASTAR_SCRIPT}"></script>
    <style>
{styles}
    </style>
  </head>
  <body>
    <main class="events-app" data-signals='{{eventCount: {total_count}, isSyncing: false, syncError: null}}'>
      <header class="events-header">
        <p class="page-kicker">Berlin Events</p>
        <div class="toolbar">
          <h1 data-text="'Berlin Events Explorer (' + $eventCount + ')'">Berlin Events Explorer</h1>
          <div class="toolbar-actions">
            <button
              type="button"
              class="sync-button"
              data-attr="{{'disabled': $isSyncing}}"
              data-text="$isSyncing ? 'Syncing...' : 'Sync now'"
              data-on:click="@post('sync?tab={tab}&recent_days={recent_days}')">
              Sync now
            </button>
            <a class="settings-link" href="/settings" aria-label="Open settings">⚙ Settings</a>
          </div>
        </div>
      </header>
      <p class="sync-error" data-show="$syncError !== null" data-text="$syncError"></p>
      <section id="sync-progress" class="sync-progress" aria-live="polite"></section>
      {_render_tabs(tab=tab, recent_days=recent_days)}
      {events_html}
    </main>
  </body>
</html>
"""


def _render_venue_detail_page(venue: VenueRecord, events: list[Event]) -> str:
    """Render a public venue page without exposing unverified candidates."""

    address = escape(venue.address) if venue.address else "Details are being verified."
    website = (
        f'<a href="{escape(venue.website, quote=True)}" target="_blank" '
        'rel="noopener noreferrer">Visit homepage</a>'
        if venue.website
        else "No website listed."
    )
    status_note = (
        ""
        if venue.status is VenueStatus.VERIFIED
        else "<p>Details are being verified.</p>"
    )
    map_html = ""
    if (
        venue.status is VenueStatus.VERIFIED
        and venue.latitude is not None
        and venue.longitude is not None
    ):
        latitude = f"{venue.latitude:.6f}"
        longitude = f"{venue.longitude:.6f}"
        west = f"{venue.longitude - 0.006:.6f}"
        south = f"{venue.latitude - 0.004:.6f}"
        east = f"{venue.longitude + 0.006:.6f}"
        north = f"{venue.latitude + 0.004:.6f}"
        map_embed_url = (
            "https://www.openstreetmap.org/export/embed.html?"
            f"bbox={west}%2C{south}%2C{east}%2C{north}"
            f"&layer=mapnik&marker={latitude}%2C{longitude}"
        )
        map_url = (
            "https://www.openstreetmap.org/?"
            f"mlat={latitude}&mlon={longitude}#map=17/{latitude}/{longitude}"
        )
        map_html = f"""
        <section class="venue-map" aria-labelledby="map-heading">
          <h2 id="map-heading">Location</h2>
          <iframe src="{escape(map_embed_url, quote=True)}"
            title="Map showing {escape(venue.name, quote=True)}" loading="lazy"
            referrerpolicy="no-referrer"></iframe>
          <p><a href="{escape(map_url, quote=True)}" target="_blank"
            rel="noopener noreferrer">View larger map</a></p>
        </section>"""
    event_items = (
        "".join(
            f"<li>{escape(event.start_date.isoformat() if event.start_date else 'TBA')} — "
            f"{escape(event.title)}</li>"
            for event in events
        )
        or "<li>No associated events yet.</li>"
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(venue.name)} · Berlin Events Explorer</title>
    <style>
      body {{ margin: 0; font-family: Inter, \"Segoe UI\", sans-serif; background: #f6f7fb; color: #0f172a; }}
      main {{ max-width: 760px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }}
      a {{ color: #1d4ed8; }}
      .card {{ background: #fff; border: 1px solid #d5dbe8; border-radius: .85rem; padding: 1.25rem; }}
      .venue-map {{ margin-top: 1.5rem; }}
      .venue-map h2 {{ margin-bottom: .65rem; }}
      .venue-map iframe {{ display: block; width: 100%; min-height: 22rem; border: 1px solid #d5dbe8; border-radius: .85rem; }}
      .venue-map p {{ margin: .6rem 0 0; }}
      dt {{ color: #64748b; margin-top: 1rem; font-size: .85rem; text-transform: uppercase; }}
      dd {{ margin: .25rem 0 0; }}
    </style>
  </head>
  <body>
    <main>
      <p><a href="/">← Back to events</a></p>
      <section class="card">
        <p>Berlin venue</p>
        <h1>{escape(venue.name)}</h1>
        {status_note}
        <dl>
          <dt>Address</dt><dd><address>{address}</address></dd>
          <dt>Homepage</dt><dd>{website}</dd>
        </dl>
        {map_html}
      </section>
      <section>
        <h2>Events</h2>
        <ul>{event_items}</ul>
      </section>
    </main>
  </body>
</html>"""


class _SyncFinished:
    """Sentinel marking completion of the manual-sync worker."""


def _render_sync_progress(
    completed: int = 0,
    total: int = 0,
    venue_name: str | None = None,
    *,
    preparing: bool = False,
    failed: bool = False,
) -> str:
    """Render the live manual-sync status patched into the page."""

    if failed:
        message = "Sync stopped before venue enrichment completed."
    elif preparing:
        message = "Downloading and importing events…"
    elif venue_name is not None:
        message = f"Enriching venues ({completed} of {total}): {venue_name}"
    elif total:
        message = f"Venue enrichment complete ({completed} of {total})"
    else:
        message = "Sync complete; no new venues required enrichment."
    progress = (
        f'<progress value="{completed}" max="{total}"></progress>' if total else ""
    )
    return (
        '<section id="sync-progress" class="sync-progress" aria-live="polite">'
        f"<p>{escape(message)}</p>{progress}</section>"
    )


def _perform_sync_stream(
    store: EventStore,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    tab: str = "upcoming",
    recent_days: int = 7,
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
):
    """Run sync and emit Datastar SSE patch events."""

    normalized_days = _normalize_recent_days(recent_days)
    current_events = _events_for_tab(
        list(store.list_events()), tab=tab, recent_days=normalized_days
    )
    yield _sse_event(
        "datastar-patch-signals",
        _signals_payload(
            event_count=len(current_events), is_syncing=True, sync_error=None
        ),
    )
    yield _sse_event(
        "datastar-patch-elements",
        f"elements {_render_sync_progress(preparing=True)}",
    )

    sync_error: str | None
    updates: Queue[VenueProgress | Exception | _SyncFinished] = Queue()
    finished = _SyncFinished()

    def run_sync() -> None:
        try:
            perform_sync(
                store,
                auto_approve_threshold=auto_approve_threshold,
                progress=updates.put,
            )
        except Exception as exc:
            updates.put(exc)
        finally:
            updates.put(finished)

    worker = Thread(target=run_sync, name="berlin-events-manual-sync", daemon=True)
    worker.start()
    failure: Exception | None = None
    while True:
        update = updates.get()
        if isinstance(update, _SyncFinished):
            break
        if isinstance(update, Exception):
            failure = update
            continue
        completed, total, venue_name = update
        yield _sse_event(
            "datastar-patch-elements",
            f"elements {_render_sync_progress(completed, total, venue_name)}",
        )
    worker.join()

    if isinstance(failure, (SyncError, httpx.RequestError)):
        sync_error = f"Sync failed: {escape(str(failure))}"
        yield _sse_event(
            "datastar-patch-elements",
            f"elements {_render_sync_progress(failed=True)}",
        )
    elif failure is not None:
        raise failure
    else:
        sync_error = None

    synced_events = _events_for_tab(
        list(store.list_events()), tab=tab, recent_days=normalized_days
    )
    paged_events, current_page, normalized_page_size, total_pages = _paginate_events(
        synced_events,
        page=page,
        page_size=page_size,
    )
    events_panel = _render_events_panel(
        paged_events,
        total_count=len(synced_events),
        page=current_page,
        page_size=normalized_page_size,
        total_pages=total_pages,
        tab=tab,
        recent_days=normalized_days,
        venue_ids_by_event=store.get_venue_ids_for_events(
            [event.id for event in paged_events]
        ),
        artist_ids_by_event_performer=_verified_artist_ids_by_event_performer(
            store, [event.id for event in paged_events]
        ),
    )
    yield _sse_event(
        "datastar-patch-elements",
        f"elements {events_panel}",
    )
    yield _sse_event(
        "datastar-patch-signals",
        _signals_payload(
            event_count=len(synced_events),
            is_syncing=False,
            sync_error=sync_error,
        ),
    )


def _signals_payload(
    *, event_count: int, is_syncing: bool, sync_error: str | None
) -> str:
    """Build a Datastar signals patch payload."""

    return (
        "signals {"
        f"eventCount: {_to_js_literal(event_count)}, "
        f"isSyncing: {_to_js_literal(is_syncing)}, "
        f"syncError: {_to_js_literal(sync_error)}"
        "}"
    )


def _to_js_literal(value: object) -> str:
    """Serialize a primitive into a Datastar-compatible JS literal."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return json.dumps(value)
    return str(value)


def _verified_artist_ids_by_event_performer(
    store: EventStore, event_ids: list[str]
) -> dict[tuple[str, int], str]:
    """Return artist links only for identities verified for public display."""

    links = store.get_artist_ids_for_event_performers(event_ids)
    artists = {artist.id: artist for artist in store.list_artists()}
    return {
        key: artist_id
        for key, artist_id in links.items()
        if artists.get(artist_id) is not None
        and artists[artist_id].status is ArtistStatus.VERIFIED
    }


def _paginate_events(
    events: list[Event], *, page: int, page_size: int
) -> tuple[list[Event], int, int, int]:
    """Return a page of events and normalized paging metadata."""

    normalized_page = max(1, page)
    normalized_page_size = _normalize_page_size(page_size)
    total_count = len(events)
    total_pages = (
        max(1, math.ceil(total_count / normalized_page_size)) if total_count else 1
    )

    if normalized_page > total_pages:
        normalized_page = total_pages

    start = (normalized_page - 1) * normalized_page_size
    end = start + normalized_page_size
    return (
        events[start:end],
        normalized_page,
        normalized_page_size,
        total_pages,
    )


def _normalize_page_size(page_size: int) -> int:
    """Normalize page size bounds to safe values for rendering."""

    if page_size <= 0:
        return DEFAULT_PAGE_SIZE
    return max(1, min(MAX_PAGE_SIZE, page_size))


def _sse_event(event_name: str, *lines: str) -> str:
    """Format an SSE event chunk for Datastar."""

    chunks: list[str] = [f"event: {event_name}"]
    for line in lines:
        payload = line.replace("\r", "").replace("\n", "") if line else ""
        chunks.append(f"data: {payload}")
    chunks.append("")
    return "\n".join(chunks) + "\n"


def _render_events_panel(
    events: list[Event],
    *,
    total_count: int,
    page: int,
    page_size: int,
    total_pages: int,
    tab: str = "upcoming",
    recent_days: int = 7,
    venue_ids_by_event: dict[str, str] | None = None,
    artist_ids_by_event_performer: dict[tuple[str, int], str] | None = None,
) -> str:
    """Render the event table section used for live updates."""

    venue_ids_by_event = venue_ids_by_event or {}
    artist_ids_by_event_performer = artist_ids_by_event_performer or {}
    rows = "".join(
        _render_event_row(
            event,
            show_date_added=tab == "recent",
            venue_id=venue_ids_by_event.get(event.id),
            artist_ids_by_billing_order={
                billing_order: artist_id
                for (
                    event_id,
                    billing_order,
                ), artist_id in artist_ids_by_event_performer.items()
                if event_id == event.id
            },
        )
        for event in events
    )
    date_added_header = "<th>Date added</th>" if tab == "recent" else ""
    empty_state = "<p>No events have been synced yet.</p>" if not events else ""

    start_index = (page - 1) * page_size + 1 if total_count else 0
    end_index = min((page - 1) * page_size + len(events), total_count)
    has_prev = page > 1
    has_next = page < total_pages
    query_suffix = f"&tab={tab}&recent_days={recent_days}"
    prev_url = (
        f"?page={page - 1}&page_size={page_size}{query_suffix}" if has_prev else "#"
    )
    next_url = (
        f"?page={page + 1}&page_size={page_size}{query_suffix}" if has_next else "#"
    )

    pagination = f"""
      <p class="meta">Showing {start_index} to {end_index} of {total_count} events</p>
      <div class="pagination" aria-label="Event pagination">
        <a class="pagination-link {"disabled" if not has_prev else ""}" href="{prev_url}">Previous</a>
        <span class="pagination-page">Page {page} of {total_pages}</span>
        <a class="pagination-link {"disabled" if not has_next else ""}" href="{next_url}">Next</a>
      </div>
    """

    return f"""<section id=\"events-panel\">
      {empty_state}
      {pagination}
      <table>
        <thead>
          <tr>
            <th>Start date</th>
            {date_added_header}
            <th>Title</th>
            <th>Venue</th>
            <th>Performers</th>
            <th>Tags</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </section>"""


def _sorted_events(events: list[Event]) -> list[Event]:
    """Return events ordered by date then title for stable display."""

    return sorted(
        events,
        key=lambda event: ((event.start_date or date.max), event.title.lower()),
    )


def _normalize_recent_days(days: int) -> int:
    """Keep the user-configurable recent-events window within safe bounds."""

    return max(1, min(365, days))


def _recent_events(
    events: list[Event], *, days: int = 7, now: datetime | None = None
) -> list[Event]:
    """Return events first observed within the requested number of days."""

    cutoff = (now or datetime.now(UTC)) - timedelta(days=_normalize_recent_days(days))
    return sorted(
        (
            event
            for event in events
            if event.first_seen_at is not None and event.first_seen_at >= cutoff
        ),
        key=lambda event: event.first_seen_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )


def _upcoming_events(events: list[Event]) -> list[Event]:
    """Return dated events occurring today or later, nearest first."""

    today = date.today()
    return _sorted_events(
        [
            event
            for event in events
            if event.start_date is not None and event.start_date >= today
        ]
    )


def _events_for_tab(events: list[Event], *, tab: str, recent_days: int) -> list[Event]:
    """Select and order the event view requested by the user."""

    if tab == "recent":
        return _recent_events(events, days=recent_days)
    return _upcoming_events(events)


def _render_tabs(*, tab: str, recent_days: int) -> str:
    """Render navigation and the recent-events timeframe control."""

    active_tab = tab if tab in {"recent", "upcoming"} else "upcoming"
    recent_active = "active" if active_tab == "recent" else ""
    upcoming_active = "active" if active_tab == "upcoming" else ""
    options = "".join(
        f'<option value="{days}"{" selected" if days == recent_days else ""}>'
        f"Last {days} days</option>"
        for days in (1, 7, 14, 30, 90)
    )
    settings = (
        '<form class="recent-settings" method="get">'
        '<input type="hidden" name="tab" value="recent">'
        '<label for="recent-days">Added within</label>'
        '<select id="recent-days" name="recent_days" onchange="this.form.submit()">'
        f"{options}</select></form>"
        if active_tab == "recent"
        else ""
    )
    return (
        '<nav class="tabs" aria-label="Event views">'
        f'<a class="tab {recent_active}" href="?tab=recent&recent_days={recent_days}">Recently added</a>'
        f'<a class="tab {upcoming_active}" href="?tab=upcoming&recent_days={recent_days}">Upcoming</a>'
        '<a class="tab" href="/approvals">Awaiting approval</a>'
        "</nav>"
        f"{settings}"
    )


def _render_event_row(
    event: Event,
    *,
    show_date_added: bool = False,
    venue_id: str | None = None,
    artist_ids_by_billing_order: dict[int, str] | None = None,
) -> str:
    """Render one event row for the HTML table."""

    event_date = event.start_date.isoformat() if event.start_date else "TBA"
    date_added = (
        event.first_seen_at.date().isoformat() if event.first_seen_at else "TBA"
    )
    title = escape(event.title)
    venue_name = escape(event.venue.name) if event.venue else "TBA"
    venue = (
        f'<a href="/venues/{escape(venue_id)}">{venue_name}</a>'
        if venue_id
        else venue_name
    )
    artist_ids_by_billing_order = artist_ids_by_billing_order or {}
    performers = ", ".join(
        f'<a href="/artists/{escape(artist_ids_by_billing_order[performer.billing_order])}">{escape(performer.name)}</a>'
        if performer.billing_order in artist_ids_by_billing_order
        else escape(performer.name)
        for performer in event.performers
    )
    tags = ", ".join(escape(tag) for tag in event.tags)
    date_added_cell = (
        f'<td data-label="Date added">{date_added}</td>' if show_date_added else ""
    )

    return (
        "<tr>"
        f'<td data-label="Start date">{event_date}</td>'
        f"{date_added_cell}"
        f'<td data-label="Title">{title}</td>'
        f'<td data-label="Venue">{venue}</td>'
        f'<td data-label="Performers">{performers or "TBA"}</td>'
        f'<td data-label="Tags">{tags or "—"}</td>'
        "</tr>"
    )


def perform_sync(
    store: EventStore,
    *,
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
    progress: VenueProgressCallback | None = None,
) -> None:
    """Run one synchronization pass for the configured source."""

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        with open_sync_cache() as cache:
            sync_source_and_ingest_venues(
                MyTrueIntentSource(),
                store,
                client,
                http_cache=cache,
                auto_approve_threshold=auto_approve_threshold,
                progress=progress,
            )


def run_server(
    *,
    database: Path,
    host: str,
    port: int,
    reload: bool = False,
    sync_interval: timedelta | None = DEFAULT_SYNC_INTERVAL,
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
    environment: str = "production",
) -> None:
    """Run the Litestar application with uvicorn."""

    import uvicorn

    app = create_app(
        database,
        sync_interval=sync_interval,
        auto_approve_threshold=auto_approve_threshold,
        environment=environment,
    )
    uvicorn.run(app, host=host, port=port, reload=reload)
