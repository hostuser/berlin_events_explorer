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
import hashlib
import json
import logging
import os
import secrets
import subprocess
from functools import cache
from queue import Queue
from threading import Lock, Thread
from collections.abc import Mapping
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Annotated, AsyncIterator
import math
from urllib.parse import quote_plus, urlparse

import httpx
from anyio import to_thread
from litestar import Litestar, Request, get, post
from litestar.config.csrf import CSRFConfig
from litestar.connection import ASGIConnection
from litestar.enums import RequestEncodingType
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler
from litestar.middleware.session.server_side import ServerSideSessionConfig
from litestar.datastructures import ResponseHeader
from litestar.params import Body, FromPath, FromQuery, QueryParameter
from litestar.response import Redirect, Response, Stream
from litestar.static_files import create_static_files_router
from litestar.stores.memory import MemoryStore
from litestar.utils.scope.state import ScopeState
from pydantic import ValidationError

from berlin_events_explorer.artist_enrichment import (
    DEFAULT_MUSICBRAINZ_FETCH_LIMIT,
    DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    MAX_MUSICBRAINZ_FETCH_LIMIT,
    MusicBrainzArtistProvider,
    open_musicbrainz_cache,
)
from berlin_events_explorer._version import version as PACKAGE_VERSION
from berlin_events_explorer.models import (
    ArtistCandidate,
    ArtistMetadata,
    ArtistRecord,
    ArtistStatus,
    Event,
    VenueCandidate,
    VenueMetadata,
    VenueRecord,
    VenueStatus,
    event_search_text,
)
from berlin_events_explorer import theme
from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.storage import EventStore, VenueSummary
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
from berlin_events_explorer.artists import normalize_artist_name

# Vendored pinned build (v1.0.0-RC.7); served same-origin so the strict CSP
# below can forbid third-party script hosts entirely.
DATASTAR_SCRIPT = "/static/datastar.js"
STATIC_DIRECTORY = Path(__file__).parent / "static"
# Datastar compiles expressions with the Function constructor and the UI uses
# inline <script>/<style>, so script-src needs 'unsafe-inline' 'unsafe-eval'.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src https://www.openstreetmap.org; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'"
)
DEFAULT_PAGE_SIZE = 50
DEFAULT_TABLE_SIZE = 20
MAX_PAGE_SIZE = 200
# Reserve a stable visual slot for each configured row. Content that needs more
# room remains available inside the scroll viewport instead of moving pagination.
TABLE_ROW_SLOT_REM = 2.75
TABLE_HEADER_SLOT_REM = 2.4
DEFAULT_SYNC_INTERVAL = timedelta(hours=1)
_SYNC_LOCK = Lock()
EDITOR_PASSWORD_ENV_VAR = "BERLIN_EVENTS_EDITOR_PASSWORD"
SECRET_KEY_ENV_VAR = "BERLIN_EVENTS_SECRET_KEY"
CSRF_HEADER_NAME = "x-csrftoken"
_SESSION_EDITOR_KEY = "is_editor"
logger = logging.getLogger(__name__)


def _csrf_token_from(request: Request) -> str | None:
    """Return the CSRF token the middleware issued for this request."""

    token = ScopeState.from_scope(request.scope).csrf_token
    return token if isinstance(token, str) else None


def _csrf_input(csrf_token: str | None) -> str:
    """Render the hidden double-submit field for one HTML form."""

    if not csrf_token:
        return ""
    return (
        '<input type="hidden" name="_csrf_token" '
        f'value="{escape(csrf_token, quote=True)}" />'
    )


def _resolve_csrf_secret(editor_password: str | None) -> str:
    """Choose a restart-stable HMAC secret for CSRF token signing."""

    configured = os.environ.get(SECRET_KEY_ENV_VAR)
    if configured:
        return configured
    if editor_password:
        return hashlib.sha256(f"csrf::{editor_password}".encode()).hexdigest()
    return secrets.token_hex(32)


def _require_editor(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Allow only clients that completed the editor login."""

    if not connection.session.get(_SESSION_EDITOR_KEY):
        raise NotAuthorizedException("Editor login required.")


def _login_redirect(target: str) -> Redirect:
    """Send an unauthenticated browser to the login form, preserving intent."""

    return Redirect(f"/login?next={quote_plus(target)}", status_code=303)


def _handle_not_authorized(request: Request, _: Exception) -> Response:
    """Redirect browsers to the login form; non-GET requests get a plain 401."""

    if request.method in {"GET", "HEAD"}:
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return _login_redirect(target)
    return Response(
        content="Editor login required.",
        media_type="text/plain",
        status_code=401,
    )


def _safe_next_target(value: str) -> str:
    """Constrain post-login redirects to same-site absolute paths."""

    if value.startswith("/") and not value.startswith(("//", "/\\")):
        return value
    return "/"


def _render_login_page(
    next_target: str,
    *,
    error: str | None = None,
    csrf_token: str | None = None,
) -> str:
    """Render the editor login form."""

    error_html = f'<p class="notice error">{escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Editor login · Berlin Events Explorer</title>
    {theme.stylesheet_link()}
  </head>
  <body class="login-page">
    <main>
      <section class="card">
        <h1>Editor login</h1>
        <p>Editorial tools require the editor password.</p>
        {error_html}
        <form method="post" action="/login">
          {_csrf_input(csrf_token)}
          <input type="hidden" name="next" value="{escape(next_target, quote=True)}" />
          <label for="password">Password</label>
          <input id="password" name="password" type="password" required autofocus />
          <button type="submit">Log in</button>
        </form>
        <a class="back-link" href="/">← Back to events</a>
      </section>
    </main>
  </body>
</html>"""


class SyncInProgressError(RuntimeError):
    """Raised when a synchronization pass is already running in this process."""


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
    except OSError, subprocess.CalledProcessError:
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


@cache
def _cached_app_version() -> str:
    """Resolve the application version once; it cannot change while running."""

    return _get_app_version()


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
                "district": candidate.district,
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
            "district": _form_string(form, "district") or None,
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


def _save_edited_artist(
    store: EventStore,
    *,
    artist_id: str,
    form: Mapping[str, object],
) -> ArtistRecord:
    """Validate and persist manually edited artist fields."""

    current = store.get_artist(artist_id)
    if current is None:
        raise ValueError(f"Unknown artist: {artist_id}")
    name = _form_string(form, "name") if "name" in form else current.name
    if not name:
        raise ValueError("Artist name cannot be blank.")
    existing_homepage = store.get_artist_official_homepage(artist_id)
    homepage = (
        (_form_string(form, "official_homepage") or None)
        if "official_homepage" in form
        else existing_homepage
    )
    if homepage is not None:
        parsed = urlparse(homepage)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Official homepage must be an HTTP(S) URL.")
    genres_value = (
        _form_string(form, "genres") if "genres" in form else ", ".join(current.genres)
    )
    genres = [genre.strip() for genre in genres_value.split(",") if genre.strip()]
    values = current.model_dump(mode="python")
    values.update(
        {
            "name": name,
            "normalized_name": normalize_artist_name(name),
            "artist_type": (
                _form_string(form, "artist_type") or None
                if "artist_type" in form
                else current.artist_type
            ),
            "country": (
                _form_string(form, "country") or None
                if "country" in form
                else current.country
            ),
            "disambiguation": (
                _form_string(form, "disambiguation") or None
                if "disambiguation" in form
                else current.disambiguation
            ),
            "genres": genres,
            "status": ArtistStatus.VERIFIED,
        }
    )
    updated = store.upsert_artist(ArtistRecord.model_validate(values))
    store.save_artist_metadata(
        ArtistMetadata(
            artist_id=artist_id,
            field="official_homepage",
            value=homepage or "",
            provider="manual-review",
            confidence=1.0,
            retrieved_at=datetime.now(UTC),
        )
    )
    return updated


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
        except SyncInProgressError:
            logger.info("Skipping scheduled sync; another sync is already running")
        except Exception:
            logger.exception("Scheduled event sync failed")


def create_app(
    database: Path | str = Path("events.sqlite"),
    *,
    sync_interval: timedelta | None = DEFAULT_SYNC_INTERVAL,
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
    environment: str = "production",
    editor_password: str | None = None,
) -> Litestar:
    """Create a Litestar app that renders stored events as HTML."""

    store = EventStore(database)
    if environment not in {"development", "production"}:
        raise ValueError("environment must be 'development' or 'production'")
    editor_password = editor_password or os.environ.get(EDITOR_PASSWORD_ENV_VAR) or None
    if editor_password is None:
        logger.warning(
            "%s is not set; editorial routes will refuse all logins",
            EDITOR_PASSWORD_ENV_VAR,
        )
    if store.get_setting("auto_approve_threshold") is None:
        store.set_setting("auto_approve_threshold", auto_approve_threshold)
    if store.get_setting("musicbrainz_request_interval_seconds") is None:
        store.set_setting(
            "musicbrainz_request_interval_seconds",
            DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
        )
    if store.get_setting("musicbrainz_fetch_limit") is None:
        store.set_setting(
            "musicbrainz_fetch_limit",
            DEFAULT_MUSICBRAINZ_FETCH_LIMIT,
        )
    if store.get_setting("musicbrainz_metadata_fetch_limit") is None:
        store.set_setting(
            "musicbrainz_metadata_fetch_limit", DEFAULT_MUSICBRAINZ_FETCH_LIMIT
        )
    if store.get_setting("default_table_size") is None:
        store.set_setting("default_table_size", DEFAULT_TABLE_SIZE)

    @get("/login", sync_to_thread=False)
    def login_page(
        request: Request,
        next_target: Annotated[str | None, QueryParameter(query="next")] = None,
    ) -> Response:
        """Render the editor login form."""

        return Response(
            content=_render_login_page(
                _safe_next_target(next_target or "/"),
                csrf_token=_csrf_token_from(request),
            ),
            media_type="text/html",
        )

    @post("/login")
    async def do_login(request: Request) -> Redirect | Response:
        """Establish an editor session when the configured password matches."""

        form = await request.form()
        supplied = _form_string(form, "password")
        next_target = _safe_next_target(_form_string(form, "next") or "/")
        if editor_password is None:
            return Response(
                content=_render_login_page(
                    next_target,
                    error="Editor access is not configured on this server.",
                    csrf_token=_csrf_token_from(request),
                ),
                media_type="text/html",
                status_code=400,
            )
        if not secrets.compare_digest(
            supplied.encode("utf-8"), editor_password.encode("utf-8")
        ):
            return Response(
                content=_render_login_page(
                    next_target,
                    error="Incorrect password.",
                    csrf_token=_csrf_token_from(request),
                ),
                media_type="text/html",
                status_code=400,
            )
        request.set_session({_SESSION_EDITOR_KEY: True})
        return Redirect(next_target, status_code=303)

    @post("/logout")
    async def logout(request: Request) -> Redirect:
        """Terminate the editor session."""

        request.clear_session()
        return Redirect("/", status_code=303)

    @get("/", sync_to_thread=True)
    def index(
        request: Request,
        page: int = 1,
        page_size: int = 0,
        tab: str = "recent",
        recent_days: int = 7,
        search: str = "",
        entity_type: str = "all",
        fragment: bool = False,
    ) -> Response | Stream:
        if tab == "approvals" and not request.session.get(_SESSION_EDITOR_KEY):
            return _login_redirect("/?tab=approvals")
        if tab == "venues":
            summaries = store.list_venue_summaries()
            normalized_page_size = _normalize_page_size(
                page_size or _get_default_table_size(store)
            )
            if fragment:
                return _render_tab_fragment(
                    _render_venues_content(
                        summaries,
                        page=page,
                        page_size=normalized_page_size,
                        search=search,
                    ),
                    event_count=0,
                )
            return Response(
                content=_render_venues_page(
                    summaries,
                    page=page,
                    page_size=normalized_page_size,
                    search=search,
                    csrf_token=_csrf_token_from(request),
                ),
                media_type="text/html",
            )

        if tab == "approvals":
            pending_venues = store.list_pending_venues()
            candidate_counts = store.count_venue_candidates_by_venue()
            pending_artists = store.list_pending_artists()
            artist_candidate_counts = store.count_artist_candidates_by_artist()
            normalized_entity_type = (
                entity_type if entity_type in {"all", "venues", "artists"} else "all"
            )
            if fragment:
                return _render_tab_fragment(
                    _render_approval_content(
                        pending_venues,
                        candidate_counts,
                        pending_artists,
                        artist_candidate_counts,
                        entity_type=normalized_entity_type,
                    ),
                    event_count=0,
                )
            return Response(
                content=_render_approval_queue(
                    pending_venues,
                    candidate_counts,
                    pending_artists,
                    artist_candidate_counts,
                    entity_type=normalized_entity_type,
                    csrf_token=_csrf_token_from(request),
                ),
                media_type="text/html",
            )

        (
            paged_events,
            filtered_count,
            current_page,
            normalized_page_size,
            total_pages,
            normalized_days,
            venue_ids_by_event,
            artist_ids_by_event_performer,
        ) = _event_listing_data(
            store,
            page=page,
            page_size=page_size,
            tab=tab,
            recent_days=recent_days,
            search=search,
        )
        if fragment:
            return _render_tab_fragment(
                _render_event_content(
                    paged_events,
                    total_count=filtered_count,
                    page=current_page,
                    page_size=normalized_page_size,
                    total_pages=total_pages,
                    tab=tab if tab in {"recent", "upcoming"} else "upcoming",
                    recent_days=normalized_days,
                    search=search.strip(),
                    venue_ids_by_event=venue_ids_by_event,
                    artist_ids_by_event_performer=artist_ids_by_event_performer,
                ),
                event_count=filtered_count,
            )
        return Response(
            content=render_events_page(
                paged_events,
                total_count=filtered_count,
                page=current_page,
                page_size=normalized_page_size,
                total_pages=total_pages,
                tab=tab,
                recent_days=normalized_days,
                search=search.strip(),
                venue_ids_by_event=venue_ids_by_event,
                artist_ids_by_event_performer=artist_ids_by_event_performer,
                csrf_token=_csrf_token_from(request),
            ),
            media_type="text/html",
        )

    @get("/events/search", sync_to_thread=True)
    def search_events(
        page_size: int = 0,
        tab: str = "recent",
        recent_days: int = 7,
        search: str = "",
    ) -> Stream:
        """Return a Datastar patch for the filtered event table."""

        (
            paged_events,
            filtered_count,
            current_page,
            normalized_page_size,
            total_pages,
            normalized_days,
            venue_ids_by_event,
            artist_ids_by_event_performer,
        ) = _event_listing_data(
            store,
            page=1,
            page_size=page_size,
            tab=tab,
            recent_days=recent_days,
            search=search,
        )
        events_panel = _render_events_panel(
            paged_events,
            total_count=filtered_count,
            page=current_page,
            page_size=normalized_page_size,
            total_pages=total_pages,
            tab=tab,
            recent_days=normalized_days,
            search=search.strip(),
            venue_ids_by_event=venue_ids_by_event,
            artist_ids_by_event_performer=artist_ids_by_event_performer,
        )
        return Stream(
            content=(
                (
                    _sse_event("datastar-patch-elements", f"elements {events_panel}")
                    + _sse_event(
                        "datastar-patch-signals",
                        _signals_payload(
                            event_count=filtered_count,
                            is_syncing=False,
                            sync_error=None,
                        ),
                    )
                ),
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @get("/dates/{event_date:str}", sync_to_thread=True)
    def date_events(event_date: str) -> Response:
        """Render all events happening on one calendar date."""

        try:
            target_date = date.fromisoformat(event_date)
        except ValueError:
            return Response(
                content="<h1>Date not found</h1>",
                media_type="text/html",
                status_code=404,
            )
        events = store.list_events_on_date(target_date)
        event_ids = [event.id for event in events]
        return Response(
            content=_render_date_events_page(
                target_date,
                events,
                venue_ids_by_event=store.get_venue_ids_for_events(event_ids),
                artist_ids_by_event_performer=_verified_artist_ids_by_event_performer(
                    store, event_ids
                ),
            ),
            media_type="text/html",
        )

    @get("/venues", sync_to_thread=True)
    def venues(page: int = 1, page_size: int = 0) -> Redirect:
        """Redirect the legacy catalog path to the canonical application URL."""

        destination = "/?tab=venues"
        if page != 1:
            destination += f"&page={page}"
        if page_size:
            destination += f"&page_size={page_size}"
        return Redirect(destination, status_code=303)

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
                external_links=store.get_artist_external_links(artist_id),
            ),
            media_type="text/html",
        )

    @get("/approvals", sync_to_thread=True, guards=[_require_editor])
    def approvals(entity_type: str = "all") -> Redirect:
        """Redirect the legacy queue path to the canonical application URL."""

        destination = "/?tab=approvals"
        if entity_type != "all":
            destination += f"&entity_type={quote_plus(entity_type)}"
        return Redirect(destination, status_code=303)

    # Shared-path note: Litestar 2.24 mis-wraps a route when a handler with
    # sync_to_thread=True shares its path with another handler, so handlers on
    # shared paths stay async and push blocking work to the thread pool via
    # anyio instead.
    @get("/approvals/venues/{venue_id:str}", guards=[_require_editor])
    async def venue_approval(
        request: Request,
        venue_id: FromPath[str],
        candidate_key: FromQuery[str | None] = None,
    ) -> Response:
        """Render a venue-specific approval form and its available suggestions."""

        def _handle() -> Response:
            venue = store.get_venue(venue_id)
            if venue is None:
                return Response(
                    "<h1>Venue not found</h1>", media_type="text/html", status_code=404
                )
            candidates = store.list_venue_candidates(venue_id)
            selected = _select_candidate(candidates, candidate_key)
            return Response(
                content=_render_venue_approval_form(
                    venue,
                    candidates,
                    selected,
                    store.list_events_for_venue(venue_id),
                    csrf_token=_csrf_token_from(request),
                ),
                media_type="text/html",
            )

        return await to_thread.run_sync(_handle)

    # Shared-path note: Litestar 2.24 mis-wraps a route when both of its
    # handlers use sync_to_thread=True, so the POST siblings of threaded GET
    # handlers stay async and push their blocking work to the thread pool.
    @post("/approvals/venues/{venue_id:str}", guards=[_require_editor])
    async def approve_venue(
        request: Request,
        venue_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Redirect | Response:
        """Approve the venue using the values currently submitted by its form."""

        def _handle() -> Redirect | Response:
            form = data
            current = store.get_venue(venue_id)
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
                        "<h1>Venue not found</h1>",
                        media_type="text/html",
                        status_code=404,
                    )
                candidates = store.list_venue_candidates(venue_id)
                selected = _select_candidate(
                    candidates,
                    _candidate_key_from_parts(provider, osm_type, osm_id),
                )
                return Response(
                    content=_render_venue_approval_form(
                        venue,
                        candidates,
                        selected,
                        store.list_events_for_venue(venue_id),
                        error=str(exc),
                        csrf_token=_csrf_token_from(request),
                    ),
                    media_type="text/html",
                    status_code=400,
                )
            destination = (
                f"/venues/{venue_id}"
                if current is not None and current.status is VenueStatus.VERIFIED
                else "/approvals"
            )
            return Redirect(destination, status_code=303)

        return await to_thread.run_sync(_handle)

    @post(
        "/approvals/venues/{venue_id:str}/discover",
        sync_to_thread=True,
        guards=[_require_editor],
    )
    def discover_venue(
        request: Request, venue_id: FromPath[str]
    ) -> Redirect | Response:
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
                    store.list_events_for_venue(venue_id),
                    error=str(exc),
                    csrf_token=_csrf_token_from(request),
                ),
                media_type="text/html",
                status_code=502,
            )
        store.record_venue_candidates(candidates)
        if candidates and venue.status is not VenueStatus.VERIFIED:
            store.upsert_venue(
                venue.model_copy(update={"status": VenueStatus.CANDIDATE})
            )
        return Redirect(f"/approvals/venues/{venue_id}", status_code=303)

    @get("/approvals/artists/{artist_id:str}", guards=[_require_editor])
    async def artist_approval(request: Request, artist_id: FromPath[str]) -> Response:
        """Render a review form for one canonical artist's candidate identities."""

        def _handle() -> Response:
            artist = store.get_artist(artist_id)
            if artist is None:
                return Response(
                    "<h1>Artist not found</h1>",
                    media_type="text/html",
                    status_code=404,
                )
            return Response(
                content=_render_artist_approval_form(
                    artist,
                    store.list_artist_candidates(artist_id),
                    homepage=store.get_artist_official_homepage(artist_id),
                    csrf_token=_csrf_token_from(request),
                ),
                media_type="text/html",
            )

        return await to_thread.run_sync(_handle)

    @post("/approvals/artists/{artist_id:str}", guards=[_require_editor])
    async def approve_artist(
        request: Request,
        artist_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Redirect | Response:
        """Apply reviewed identity data and manually edited artist fields."""

        def _handle() -> Redirect | Response:
            form = data
            candidate_id = _form_string(form, "candidate")
            current = store.get_artist(artist_id)
            try:
                if candidate_id:
                    store.select_artist_candidate(
                        artist_id, "musicbrainz", candidate_id
                    )
                elif current is None or current.status is not ArtistStatus.VERIFIED:
                    raise ValueError("Select an artist candidate before approving.")
                _save_edited_artist(store, artist_id=artist_id, form=form)
            except (ValueError, ValidationError) as exc:
                artist = store.get_artist(artist_id)
                if artist is None:
                    return Response(
                        "<h1>Artist not found</h1>",
                        media_type="text/html",
                        status_code=404,
                    )
                return Response(
                    content=_render_artist_approval_form(
                        artist,
                        store.list_artist_candidates(artist_id),
                        homepage=store.get_artist_official_homepage(artist_id),
                        error=str(exc),
                        csrf_token=_csrf_token_from(request),
                    ),
                    media_type="text/html",
                    status_code=400,
                )
            destination = (
                f"/artists/{artist_id}"
                if current is not None and current.status is ArtistStatus.VERIFIED
                else "/approvals?entity_type=artists"
            )
            return Redirect(destination, status_code=303)

        return await to_thread.run_sync(_handle)

    @post(
        "/approvals/artists/{artist_id:str}/discover",
        sync_to_thread=True,
        guards=[_require_editor],
    )
    def discover_artist(
        request: Request, artist_id: FromPath[str]
    ) -> Redirect | Response:
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
                    artist,
                    store.list_artist_candidates(artist_id),
                    homepage=store.get_artist_official_homepage(artist_id),
                    error=str(exc),
                    csrf_token=_csrf_token_from(request),
                ),
                media_type="text/html",
                status_code=502,
            )
        store.record_artist_candidates(candidates)
        if candidates and artist.status is not ArtistStatus.VERIFIED:
            store.upsert_artist(
                artist.model_copy(update={"status": ArtistStatus.CANDIDATE})
            )
        return Redirect(f"/approvals/artists/{artist_id}", status_code=303)

    @post("/sync", status_code=200, sync_to_thread=True, guards=[_require_editor])
    def sync(
        page: int = 1,
        page_size: int = 0,
        tab: str = "recent",
        recent_days: int = 7,
        search: str = "",
        view: str = "events",
    ) -> Stream:
        return Stream(
            content=_perform_sync_stream(
                store,
                page=page,
                page_size=page_size or _get_default_table_size(store),
                tab=tab,
                recent_days=recent_days,
                search=search,
                view=view,
                auto_approve_threshold=_get_auto_approve_threshold(
                    store, auto_approve_threshold
                ),
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @get("/settings", guards=[_require_editor])
    async def settings(
        request: Request,
        saved: FromQuery[str | None] = None,
        cleared: FromQuery[str | None] = None,
    ) -> Response:
        """Render persisted application configuration and development tools."""

        def _handle() -> Response:
            return Response(
                content=_render_settings_page(
                    csrf_token=_csrf_token_from(request),
                    threshold=_get_auto_approve_threshold(
                        store, auto_approve_threshold
                    ),
                    musicbrainz_request_interval=_get_musicbrainz_request_interval(
                        store
                    ),
                    musicbrainz_fetch_limit=_get_musicbrainz_fetch_limit(store),
                    musicbrainz_metadata_fetch_limit=(
                        _get_musicbrainz_metadata_fetch_limit(store)
                    ),
                    default_table_size=_get_default_table_size(store),
                    environment=environment,
                    version=_cached_app_version(),
                    saved=saved == "1",
                    cleared=cleared == "1",
                ),
                media_type="text/html",
            )

        return await to_thread.run_sync(_handle)

    @post("/settings", guards=[_require_editor])
    async def save_settings(
        request: Request,
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Redirect | Response:
        """Validate and persist settings used by subsequent synchronization passes."""

        def _handle() -> Redirect | Response:
            form = data
            raw_threshold = _form_string(form, "auto_approve_threshold")
            raw_interval = _form_string(form, "musicbrainz_request_interval_seconds")
            raw_fetch_limit = _form_string(form, "musicbrainz_fetch_limit")
            raw_metadata_fetch_limit = _form_string(
                form, "musicbrainz_metadata_fetch_limit"
            )
            raw_table_size = _form_string(form, "default_table_size")
            try:
                threshold = float(raw_threshold)
                interval = (
                    float(raw_interval)
                    if raw_interval
                    else _get_musicbrainz_request_interval(store)
                )
                fetch_limit = (
                    int(raw_fetch_limit)
                    if raw_fetch_limit
                    else _get_musicbrainz_fetch_limit(store)
                )
                metadata_fetch_limit = (
                    int(raw_metadata_fetch_limit)
                    if raw_metadata_fetch_limit
                    else _get_musicbrainz_metadata_fetch_limit(store)
                )
                table_size = (
                    int(raw_table_size)
                    if raw_table_size
                    else _get_default_table_size(store)
                )
                if not math.isfinite(threshold) or not 0 <= threshold <= 1:
                    raise ValueError
                if not math.isfinite(interval) or not 1.0 <= interval <= 300:
                    raise ValueError
                if not 1 <= fetch_limit <= MAX_MUSICBRAINZ_FETCH_LIMIT:
                    raise ValueError
                if not 1 <= metadata_fetch_limit <= MAX_MUSICBRAINZ_FETCH_LIMIT:
                    raise ValueError
                if not 1 <= table_size <= MAX_PAGE_SIZE:
                    raise ValueError
            except ValueError:
                return Response(
                    content=_render_settings_page(
                        csrf_token=_csrf_token_from(request),
                        threshold=_get_auto_approve_threshold(
                            store, auto_approve_threshold
                        ),
                        musicbrainz_request_interval=_get_musicbrainz_request_interval(
                            store
                        ),
                        musicbrainz_fetch_limit=_get_musicbrainz_fetch_limit(store),
                        musicbrainz_metadata_fetch_limit=_get_musicbrainz_metadata_fetch_limit(
                            store
                        ),
                        default_table_size=_get_default_table_size(store),
                        environment=environment,
                        error="Confidence threshold must be a number between 0 and 1; MusicBrainz pacing must be 1–300 seconds; fetch count must be 1–10000; table size must be 1–200.",
                    ),
                    media_type="text/html",
                    status_code=400,
                )
            store.set_setting("auto_approve_threshold", threshold)
            store.set_setting("musicbrainz_request_interval_seconds", interval)
            store.set_setting("musicbrainz_fetch_limit", fetch_limit)
            store.set_setting("musicbrainz_metadata_fetch_limit", metadata_fetch_limit)
            store.set_setting("default_table_size", table_size)
            return Redirect("/settings?saved=1", status_code=303)

        return await to_thread.run_sync(_handle)

    @post("/settings/clear-database", sync_to_thread=True, guards=[_require_editor])
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

    @get("/static/app.css", sync_to_thread=False)
    def app_stylesheet() -> Response:
        """Serve the consolidated stylesheet with far-future caching.

        The href carries a content hash (theme.STYLESHEET_HREF), so the
        response can be immutable: a changed stylesheet gets a new URL.
        """

        return Response(
            content=theme.stylesheet(),
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

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

    session_config = ServerSideSessionConfig()
    csrf_config = CSRFConfig(
        secret=_resolve_csrf_secret(editor_password),
        header_name=CSRF_HEADER_NAME,
    )
    return Litestar(
        route_handlers=[
            index,
            search_events,
            date_events,
            venues,
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
            app_stylesheet,
            login_page,
            do_login,
            logout,
            create_static_files_router(path="/static", directories=[STATIC_DIRECTORY]),
        ],
        middleware=[session_config.middleware],
        csrf_config=csrf_config,
        stores={"sessions": MemoryStore()},
        exception_handlers={NotAuthorizedException: _handle_not_authorized},
        response_headers=[
            ResponseHeader(
                name="Content-Security-Policy",
                value=CONTENT_SECURITY_POLICY,
                documentation_only=False,
            ),
            ResponseHeader(name="X-Content-Type-Options", value="nosniff"),
            ResponseHeader(name="X-Frame-Options", value="DENY"),
            ResponseHeader(
                name="Referrer-Policy", value="strict-origin-when-cross-origin"
            ),
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


def _get_musicbrainz_fetch_limit(store: EventStore) -> int:
    """Return persisted safe MusicBrainz batch size, falling back to the default."""

    configured = store.get_setting("musicbrainz_fetch_limit")
    if (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and 1 <= configured <= MAX_MUSICBRAINZ_FETCH_LIMIT
    ):
        return configured
    return DEFAULT_MUSICBRAINZ_FETCH_LIMIT


def _get_musicbrainz_metadata_fetch_limit(store: EventStore) -> int:
    """Return persisted safe MusicBrainz metadata batch size."""

    configured = store.get_setting("musicbrainz_metadata_fetch_limit")
    if (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and 1 <= configured <= MAX_MUSICBRAINZ_FETCH_LIMIT
    ):
        return configured
    return DEFAULT_MUSICBRAINZ_FETCH_LIMIT


def _get_default_table_size(store: EventStore) -> int:
    """Return persisted default table row count, falling back to the default."""

    configured = store.get_setting("default_table_size")
    if (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and 1 <= configured <= MAX_PAGE_SIZE
    ):
        return configured
    return DEFAULT_TABLE_SIZE


def _event_listing_data(
    store: EventStore,
    *,
    page: int,
    page_size: int,
    tab: str,
    recent_days: int,
    search: str,
) -> tuple[
    list[Event],
    int,
    int,
    int,
    int,
    int,
    dict[str, str],
    dict[tuple[str, int], str],
]:
    """Build the filtered, paginated event listing and its metadata."""

    normalized_days = _normalize_recent_days(recent_days)
    normalized_page_size = _normalize_page_size(
        page_size or _get_default_table_size(store)
    )
    paged_events, filtered_count, current_page, total_pages = store.query_events(
        tab="recent" if tab == "recent" else "upcoming",
        recent_days=normalized_days,
        search=search,
        page=page,
        page_size=normalized_page_size,
    )
    event_ids = [event.id for event in paged_events]
    return (
        paged_events,
        filtered_count,
        current_page,
        normalized_page_size,
        total_pages,
        normalized_days,
        store.get_venue_ids_for_events(event_ids),
        _verified_artist_ids_by_event_performer(store, event_ids),
    )


def _render_settings_page(
    *,
    threshold: float,
    musicbrainz_request_interval: float = DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    musicbrainz_fetch_limit: int = DEFAULT_MUSICBRAINZ_FETCH_LIMIT,
    musicbrainz_metadata_fetch_limit: int = DEFAULT_MUSICBRAINZ_FETCH_LIMIT,
    default_table_size: int = DEFAULT_TABLE_SIZE,
    environment: str,
    version: str | None = None,
    saved: bool = False,
    cleared: bool = False,
    error: str | None = None,
    csrf_token: str | None = None,
) -> str:
    """Render operational settings with a development-only destructive action."""

    display_version = version or _cached_app_version()
    notices = ""
    if saved:
        notices += '<p class="notice success">Settings saved.</p>'
    if cleared:
        notices += '<p class="notice success">Development database cleared.</p>'
    if error:
        notices += f'<p class="notice error">{escape(error)}</p>'
    reset = (
        f"""
        <section class="settings-card danger-zone">
          <p class="section-label">Development tools</p>
          <h2>Clear application data</h2>
          <p>Remove events, venues, suggestions, provenance, logs, and sync state. Your settings remain.</p>
          <form method="post" action="/settings/clear-database"
            onsubmit="return confirm('Clear all development data? This cannot be undone.');">
            {_csrf_input(csrf_token)}
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
    {theme.stylesheet_link()}
  </head>
  <body class="settings-page">
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
            {_csrf_input(csrf_token)}
            <label for="threshold">Confidence threshold</label>
            <input id="threshold" name="auto_approve_threshold" type="number"
              min="0" max="1" step="0.01" required value="{threshold:g}" />
            <small class="hint">Use a value from 0 to 1. Higher values are stricter.</small>
            <label for="musicbrainz-interval">MusicBrainz request interval (seconds)</label>
            <input id="musicbrainz-interval" name="musicbrainz_request_interval_seconds" type="number"
              min="1" max="300" step="0.1" required value="{musicbrainz_request_interval:g}" />
            <small class="hint">Public MusicBrainz access requires at least one second between requests.</small>
            <label for="musicbrainz-fetch-limit">MusicBrainz artist fetches per worker run</label>
            <input id="musicbrainz-fetch-limit" name="musicbrainz_fetch_limit" type="number"
              min="1" max="10000" step="1" required value="{musicbrainz_fetch_limit}" />
            <small class="hint">Limit the number of unresolved artists checked in one background worker run.</small>
            <label for="musicbrainz-metadata-fetch-limit">MusicBrainz metadata fetches per worker run</label>
            <input id="musicbrainz-metadata-fetch-limit" name="musicbrainz_metadata_fetch_limit" type="number"
              min="1" max="10000" step="1" required value="{musicbrainz_metadata_fetch_limit}" />
            <small class="hint">Limit the number of verified artists checked for missing metadata in one background worker run.</small>
            <label for="default-table-size">Default table size (rows)</label>
            <input id="default-table-size" name="default_table_size" type="number"
              min="1" max="{MAX_PAGE_SIZE}" step="1" required value="{default_table_size}" />
            <small class="hint">How many rows are shown by default in recently added, upcoming, and venue tables.</small>
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


def _approval_nav() -> str:
    """Render the top-level views with approval state selected."""

    return (
        '<nav class="tabs" aria-label="Application views">'
        '<a class="tab" href="/?tab=recent">Recently added</a>'
        '<a class="tab" href="/?tab=upcoming">Upcoming</a>'
        '<a class="tab" href="/venues">Venues</a>'
        '<a class="tab active" href="/approvals">Awaiting approval</a>'
        "</nav>"
    )


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
    events: list[Event],
    *,
    error: str | None = None,
    csrf_token: str | None = None,
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

    upcoming_events = _upcoming_events(events)
    event_table = _render_event_table(
        upcoming_events,
        show_venue=False,
        empty_text="No upcoming events are associated with this venue.",
    )

    base_address = selected.address if selected else venue.address
    base_postal_code = selected.postal_code if selected else venue.postal_code
    base_district = selected.district if selected else venue.district
    base_website = selected.website if selected else venue.website
    hidden = (
        f'<input type="hidden" name="provider" value="{escape(selected.provider, quote=True)}" />'
        f'<input type="hidden" name="osm_type" value="{escape(selected.osm_type, quote=True)}" />'
        f'<input type="hidden" name="osm_id" value="{escape(selected.osm_id, quote=True)}" />'
        if selected
        else ""
    )

    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    back_href = (
        f"/venues/{escape(venue.id, quote=True)}"
        if venue.status is VenueStatus.VERIFIED
        else "/approvals"
    )
    back_label = (
        "Back to venue"
        if venue.status is VenueStatus.VERIFIED
        else "Back to approval queue"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Approve {escape(venue.name)} · Berlin Events Explorer</title>
{theme.stylesheet_link()}</head><body class="approval-page"><main>
<p><a href="{back_href}">← {back_label}</a></p><p class="kicker">Venue approval</p>
<h1>{escape(venue.name)}</h1><p class="muted">Choose a suggestion or enter the venue details manually, then review and approve the form.</p>
{error_html}<section class="events-section" aria-labelledby="venue-events-heading">
<h2 id="venue-events-heading">Upcoming events ({len(upcoming_events)})</h2>
<div class="card events-card">{event_table}</div>
</section>
<h2>Suggestions</h2><div class="suggestions">{suggestions}</div>
<form method="post" action="/approvals/venues/{escape(venue.id)}" class="card">
{_csrf_input(csrf_token)}{hidden}<div class="form-grid">
{_venue_field("name", "Venue name", venue.name, wide=True)}
{_venue_field("address", "Address", base_address, wide=True)}
{_venue_field("postal_code", "Postal code", base_postal_code)}
{_venue_field("district", "District", base_district)}
{_venue_field("city", "City", venue.city)}
{_venue_field("country", "Country code", venue.country)}
{_venue_field("website", "Homepage", base_website, wide=True)}
</div><div class="actions">
<button type="submit" name="action" value="approve">Approve</button>
</div></form>
<form method="post" action="/approvals/venues/{escape(venue.id)}/discover" class="actions">
{_csrf_input(csrf_token)}
<button type="submit" class="secondary">Find or refresh suggestions</button></form>
</main></body></html>"""


def _render_artist_approval_form(
    artist: ArtistRecord,
    candidates: list[ArtistCandidate],
    *,
    homepage: str | None = None,
    error: str | None = None,
    csrf_token: str | None = None,
) -> str:
    """Render candidate identity evidence and editable artist fields."""

    required = " required" if artist.status is not ArtistStatus.VERIFIED else ""
    options = (
        "".join(
            f'<label class="suggestion"><input type="radio" name="candidate" '
            f'value="{escape(candidate.musicbrainz_id, quote=True)}"{required}> '
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
    genres = ", ".join(artist.genres)
    back_href = (
        f"/artists/{escape(artist.id, quote=True)}"
        if artist.status is ArtistStatus.VERIFIED
        else "/approvals?entity_type=artists"
    )
    back_label = (
        "Back to artist"
        if artist.status is ArtistStatus.VERIFIED
        else "Back to artist queue"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Review {escape(artist.name)} · Berlin Events Explorer</title>{theme.stylesheet_link()}</head>
<body class="approval-page"><main><p><a href="{back_href}">← {back_label}</a></p>
<p class="kicker">Artist review</p><h1>{escape(artist.name)}</h1>
<p class="muted">Choose a suggestion if needed, edit the public fields, then approve the changes.</p>{error_html}
<form method="post" action="/approvals/artists/{escape(artist.id, quote=True)}" class="card">
{_csrf_input(csrf_token)}
<h2>Suggestions</h2><div class="suggestions">{options}</div>
<div class="form-grid">
<label class="field-wide">Artist name<input type="text" name="name" required value="{escape(artist.name, quote=True)}" /></label>
<label>Artist type<input type="text" name="artist_type" value="{escape(artist.artist_type or "", quote=True)}" /></label>
<label>Country<input type="text" name="country" value="{escape(artist.country or "", quote=True)}" /></label>
<label class="field-wide">Disambiguation<input type="text" name="disambiguation" value="{escape(artist.disambiguation or "", quote=True)}" /></label>
<label class="field-wide">Genres<input type="text" name="genres" value="{escape(genres, quote=True)}" /></label>
<label class="field-wide">Official homepage<input type="url" name="official_homepage" value="{escape(homepage or "", quote=True)}" /></label>
</div><div class="actions"><button type="submit">Approve changes</button></div></form>
<form method="post" action="/approvals/artists/{escape(artist.id, quote=True)}/discover" class="actions">
{_csrf_input(csrf_token)}
<button type="submit" class="secondary">Find or refresh suggestions</button></form>
</main></body></html>"""


def _render_artist_detail_page(
    artist: ArtistRecord,
    events: list[Event],
    *,
    homepage: str | None = None,
    external_links: dict[str, str] | None = None,
) -> str:
    """Render verified canonical artist metadata and associated events."""

    external_links = external_links or {}

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
    spotify_link = (
        f'<a href="{escape(external_links["spotify"], quote=True)}" target="_blank" '
        'rel="noopener noreferrer">Spotify</a>'
        if external_links.get("spotify")
        else ""
    )
    youtube_music_link = (
        f'<a href="{escape(external_links["youtube_music"], quote=True)}" target="_blank" '
        'rel="noopener noreferrer">YouTube Music</a>'
        if external_links.get("youtube_music")
        else ""
    )
    youtube_search_url = "https://www.youtube.com/results?search_query=" + quote_plus(
        artist.name
    )
    youtube_search_link = (
        f'<a href="{escape(youtube_search_url, quote=True)}" target="_blank" '
        'rel="noopener noreferrer">Search on YouTube</a>'
    )
    platform_links = " · ".join(
        link for link in (spotify_link, youtube_music_link, youtube_search_link) if link
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
<title>{escape(artist.name)} · Berlin Events Explorer</title>{theme.stylesheet_link()}</head>
<body class="detail-page"><main><p><a href="/">← Back to events</a></p><section class="card">
<div class="detail-header"><div><p>Berlin artist</p><h1>{escape(artist.name)}</h1></div>
<a class="action-button" href="/approvals/artists/{escape(artist.id, quote=True)}">Edit</a></div>
<p>{details}</p><p><strong>Genres:</strong> {genres}</p><p>{homepage_link}</p>
<p class="artist-links"><strong>Listen &amp; watch:</strong> {platform_links}</p>
<p>{identity}</p>
</section><section><h2>Events</h2><ul>{event_items}</ul></section></main></body></html>"""


def _render_date_events_page(
    target_date: date,
    events: list[Event],
    *,
    venue_ids_by_event: dict[str, str] | None = None,
    artist_ids_by_event_performer: dict[tuple[str, int], str] | None = None,
) -> str:
    """Render the complete event list for one calendar date."""

    venue_ids_by_event = venue_ids_by_event or {}
    artist_ids_by_event_performer = artist_ids_by_event_performer or {}
    event_table = _render_event_table(
        events,
        show_start_date=False,
        show_venue=True,
        venue_ids_by_event=venue_ids_by_event,
        artist_ids_by_event_performer=artist_ids_by_event_performer,
        empty_text="No events are listed for this date.",
    )
    event_label = "event" if len(events) == 1 else "events"
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Events on {target_date.isoformat()} · Berlin Events Explorer</title>
    {theme.stylesheet_link()}
  </head>
  <body class="date-page">
    <main>
      <p class="page-kicker">Berlin Events</p>
      <a class="back-link" href="/">← Back to events</a>
      <h1>Events on {target_date.isoformat()}</h1>
      <p class="meta">{len(events)} {event_label} on this date.</p>
      <section class="card" aria-label="Events on {target_date.isoformat()}">
        {event_table}
      </section>
    </main>
  </body>
</html>"""


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
    event_table = _render_event_table(
        events,
        show_venue=False,
        empty_text="No associated events yet.",
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(venue.name)} · Berlin Events Explorer</title>
    {theme.stylesheet_link()}
  </head>
  <body class="detail-page">
    <main>
      <p><a href="/venues">← Back to venues</a></p>
      <section class="card">
        <div class="detail-header"><div><p>Berlin venue</p><h1>{escape(venue.name)}</h1></div>
        <a class="action-button" href="/approvals/venues/{escape(venue.id, quote=True)}">Edit</a></div>
        {status_note}
        <dl>
          <dt>Address</dt><dd><address>{address}</address></dd>
          <dt>District</dt><dd>{escape(venue.district or "Not listed")}</dd>
          <dt>Homepage</dt><dd>{website}</dd>
        </dl>
        {map_html}
      </section>
      <section class="events-section">
        <h2>Events</h2>
        <div class="events-card">
          {event_table}
        </div>
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
    search: str = "",
    view: str = "events",
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
):
    """Run sync and emit Datastar SSE patch events."""

    normalized_days = _normalize_recent_days(recent_days)
    normalized_tab = "recent" if tab == "recent" else "upcoming"
    _, current_count, _, _ = store.query_events(
        tab=normalized_tab,
        recent_days=normalized_days,
        search=search,
        page=1,
        page_size=1,
    )
    yield _sse_event(
        "datastar-patch-signals",
        _signals_payload(event_count=current_count, is_syncing=True, sync_error=None),
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

    if isinstance(failure, SyncInProgressError):
        sync_error = str(failure)
    elif isinstance(failure, (SyncError, httpx.RequestError)):
        sync_error = f"Sync failed: {escape(str(failure))}"
        yield _sse_event(
            "datastar-patch-elements",
            f"elements {_render_sync_progress(failed=True)}",
        )
    elif failure is not None:
        raise failure
    else:
        sync_error = None

    normalized_page_size = _normalize_page_size(page_size)
    paged_events, synced_count, current_page, total_pages = store.query_events(
        tab=normalized_tab,
        recent_days=normalized_days,
        search=search,
        page=page,
        page_size=normalized_page_size,
    )
    if view == "events":
        events_panel = _render_events_panel(
            paged_events,
            total_count=synced_count,
            page=current_page,
            page_size=normalized_page_size,
            total_pages=total_pages,
            tab=tab,
            recent_days=normalized_days,
            search=search.strip(),
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
    elif view == "venues":
        yield _sse_event(
            "datastar-patch-elements",
            "elements "
            + _render_tab_content_element(
                _render_venues_content(
                    store.list_venue_summaries(),
                    page=page,
                    page_size=page_size,
                )
            ),
        )
    elif view == "approvals":
        yield _sse_event(
            "datastar-patch-elements",
            "elements "
            + _render_tab_content_element(
                _render_approval_content(
                    store.list_pending_venues(),
                    store.count_venue_candidates_by_venue(),
                    store.list_pending_artists(),
                    store.count_artist_candidates_by_artist(),
                    entity_type="all",
                )
            ),
        )
    yield _sse_event(
        "datastar-patch-signals",
        _signals_payload(
            event_count=synced_count,
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

    return store.get_artist_ids_for_event_performers(event_ids, only_verified=True)


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


def _paginate_venues(
    summaries: list[VenueSummary], *, page: int, page_size: int
) -> tuple[list[VenueSummary], int, int, int]:
    """Return one normalized page of venue summaries."""

    normalized_page = max(1, page)
    normalized_page_size = _normalize_page_size(page_size)
    total_count = len(summaries)
    total_pages = (
        max(1, math.ceil(total_count / normalized_page_size)) if total_count else 1
    )
    if normalized_page > total_pages:
        normalized_page = total_pages
    start = (normalized_page - 1) * normalized_page_size
    end = start + normalized_page_size
    return (
        summaries[start:end],
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


def _render_event_table(
    events: list[Event],
    *,
    tab: str = "upcoming",
    show_start_date: bool = True,
    show_venue: bool = True,
    empty_text: str = "No events have been synced yet.",
    venue_ids_by_event: dict[str, str] | None = None,
    artist_ids_by_event_performer: dict[tuple[str, int], str] | None = None,
) -> str:
    """Render a reusable event table with context-specific columns."""

    venue_ids_by_event = venue_ids_by_event or {}
    artist_ids_by_event_performer = artist_ids_by_event_performer or {}
    rows = "".join(
        _render_event_row(
            event,
            show_date_added=tab == "recent",
            show_start_date=show_start_date,
            show_venue=show_venue,
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
    headers = []
    if show_start_date:
        headers.append("<th>Start date</th>")
    if tab == "recent":
        headers.append("<th>Date added</th>")
    headers.append("<th>Title</th>")
    if show_venue:
        headers.append("<th>Venue</th>")
    headers.extend(("<th>Performers</th>", "<th>Tags</th>"))
    empty_state = (
        f'<p class="empty-state">{escape(empty_text)}</p>' if not events else ""
    )
    return f"""{empty_state}
          <table class="event-table">
            <thead><tr>{"".join(headers)}</tr></thead>
            <tbody>{rows}</tbody>
          </table>"""


def _render_events_panel(
    events: list[Event],
    *,
    total_count: int,
    page: int,
    page_size: int,
    total_pages: int,
    tab: str = "upcoming",
    recent_days: int = 7,
    search: str = "",
    venue_ids_by_event: dict[str, str] | None = None,
    artist_ids_by_event_performer: dict[tuple[str, int], str] | None = None,
) -> str:
    """Render the event table section used for live updates."""

    event_table = _render_event_table(
        events,
        tab=tab,
        venue_ids_by_event=venue_ids_by_event,
        artist_ids_by_event_performer=artist_ids_by_event_performer,
    )

    start_index = (page - 1) * page_size + 1 if total_count else 0
    end_index = min((page - 1) * page_size + len(events), total_count)
    has_prev = page > 1
    has_next = page < total_pages
    search_param = f"&search={quote_plus(search)}" if search else ""
    query_suffix = f"&tab={tab}&recent_days={recent_days}{search_param}"
    prev_url = (
        f"/?page={page - 1}&page_size={page_size}{query_suffix}" if has_prev else "#"
    )
    next_url = (
        f"/?page={page + 1}&page_size={page_size}{query_suffix}" if has_next else "#"
    )
    previous_link = (
        _render_in_place_link(
            prev_url,
            "Previous",
            class_name="pagination-link",
            app_view=tab,
            event_tab=tab,
        )
        if has_prev
        else '<a class="pagination-link disabled" href="#">Previous</a>'
    )
    next_link = (
        _render_in_place_link(
            next_url,
            "Next",
            class_name="pagination-link",
            app_view=tab,
            event_tab=tab,
        )
        if has_next
        else '<a class="pagination-link disabled" href="#">Next</a>'
    )

    pagination = f"""
      <footer class="table-footer">
        <p class="meta">Showing {start_index} to {end_index} of {total_count} events</p>
        <div class="pagination" aria-label="Event pagination">
          {previous_link}
          <span class="pagination-page">Page {page} of {total_pages}</span>
          {next_link}
        </div>
      </footer>
    """

    return f"""<section id=\"events-panel\">
      <div class="table-scroll" aria-label="Event results" style="--table-view-height:{_table_view_height(page_size)}">
        {event_table}
      </div>
      {pagination}
    </section>"""


def _table_view_height(page_size: int) -> str:
    """Return a stable table viewport height for one configured page."""

    height = TABLE_HEADER_SLOT_REM + page_size * TABLE_ROW_SLOT_REM
    return f"{height:.2f}rem"


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
    today = date.today()
    return sorted(
        (
            event
            for event in events
            if event.first_seen_at is not None
            and event.first_seen_at >= cutoff
            and (event.start_date is None or event.start_date >= today)
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


def _events_on_date(events: list[Event], *, target_date: date) -> list[Event]:
    """Return events whose date or date range includes the requested date."""

    return _sorted_events(
        [
            event
            for event in events
            if event.start_date is not None
            and (
                event.start_date == target_date
                or (
                    event.end_date is not None
                    and event.start_date <= target_date <= event.end_date
                )
            )
        ]
    )


def _render_tabs(*, tab: str, recent_days: int, search: str = "") -> str:
    """Render navigation and the recent-events timeframe control."""

    active_tab = tab if tab in {"recent", "upcoming"} else "upcoming"
    recent_active = "active" if active_tab == "recent" else ""
    upcoming_active = "active" if active_tab == "upcoming" else ""
    search_param = f"&search={escape(search, quote=True)}" if search else ""
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
        f'<a class="tab {recent_active}" href="?tab=recent&recent_days={recent_days}{search_param}">Recently added</a>'
        f'<a class="tab {upcoming_active}" href="?tab=upcoming&recent_days={recent_days}{search_param}">Upcoming</a>'
        '<a class="tab" href="/venues">Venues</a>'
        '<a class="tab" href="/approvals">Awaiting approval</a>'
        "</nav>"
        f"{settings}"
    )


_event_search_text = event_search_text


def _filter_events(events: list[Event], search: str) -> list[Event]:
    """Return events whose title, venue, or performers match the search term."""

    query = search.strip().casefold()
    if not query:
        return events
    return [event for event in events if query in _event_search_text(event)]


def _render_event_row(
    event: Event,
    *,
    show_date_added: bool = False,
    show_start_date: bool = True,
    show_venue: bool = True,
    venue_id: str | None = None,
    artist_ids_by_billing_order: dict[int, str] | None = None,
) -> str:
    """Render one event row for the HTML table."""

    event_date = event.start_date.isoformat() if event.start_date else "TBA"
    date_cell = (
        f'<a class="date-link" href="/dates/{event_date}">{event_date}</a>'
        if event.start_date
        else event_date
    )
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
    start_date_cell = (
        f'<td data-label="Start date">{date_cell}</td>' if show_start_date else ""
    )
    date_added_cell = (
        f'<td data-label="Date added">{date_added}</td>' if show_date_added else ""
    )
    venue_cell = f'<td data-label="Venue">{venue}</td>' if show_venue else ""
    search_attr = escape(_event_search_text(event), quote=True)

    return (
        f'<tr data-event-row data-event-search="{search_attr}">'
        f"{start_date_cell}"
        f"{date_added_cell}"
        f'<td data-label="Title">{title}</td>'
        f"{venue_cell}"
        f'<td data-label="Performers">{performers or "TBA"}</td>'
        f'<td data-label="Tags">{tags or "—"}</td>'
        "</tr>"
    )


def _fragment_url(href: str) -> str:
    """Return the fragment endpoint corresponding to a canonical application URL."""

    separator = "&" if "?" in href else "?"
    return f"{href}{separator}fragment=1"


def _js_string_escape(value: str) -> str:
    """Escape a value for embedding inside a single-quoted JS string literal."""

    return value.replace("\\", "\\\\").replace("'", "\\'")


def _in_place_navigation_action(
    href: str, *, app_view: str, event_tab: str | None = None
) -> str:
    """Build one canonical URL + Datastar fragment navigation action."""

    event_tab_assignment = f" $eventTab = '{event_tab}';" if event_tab else ""
    return (
        "evt.preventDefault(); "
        f"history.pushState(null, '', '{_js_string_escape(href)}'); "
        f"$appView = '{app_view}';"
        f"{event_tab_assignment} @get('{_js_string_escape(_fragment_url(href))}')"
    )


def _render_in_place_link(
    href: str,
    label: str,
    *,
    class_name: str,
    app_view: str,
    event_tab: str | None = None,
    current: str = "",
    attributes: str = "",
) -> str:
    """Render a progressive-enhancement link that preserves browser history."""

    action = _in_place_navigation_action(
        href,
        app_view=app_view,
        event_tab=event_tab,
    )
    return (
        f'<a class="{escape(class_name, quote=True)}" '
        f'href="{escape(href, quote=True)}"{current} {attributes}'
        f'data-on:click="{escape(action, quote=True)}">{escape(label)}</a>'
    )


def _render_app_nav(
    *,
    active_tab: str,
    recent_days: int = 7,
    search: str = "",
    page_size: int = DEFAULT_PAGE_SIZE,
) -> str:
    """Render persistent views using one URL-aware in-place navigation contract."""

    active_tab = (
        active_tab
        if active_tab in {"recent", "upcoming", "venues", "approvals"}
        else "upcoming"
    )
    encoded_search = quote_plus(search) if search else ""
    recent_search_param = (
        f"&search={encoded_search}" if encoded_search and active_tab == "recent" else ""
    )
    upcoming_search_param = (
        f"&search={encoded_search}"
        if encoded_search and active_tab == "upcoming"
        else ""
    )
    venue_search_param = (
        f"&search={encoded_search}" if encoded_search and active_tab == "venues" else ""
    )

    def link(tab: str, label: str, href: str) -> str:
        selected = " active" if active_tab == tab else ""
        current = ' aria-current="page"' if active_tab == tab else ""
        attributes = (
            f"data-class:active=\"$appView === '{tab}'\" "
            f"data-attr:aria-current=\"$appView === '{tab}' ? 'page' : null\" "
        )
        return _render_in_place_link(
            href,
            label,
            class_name=f"tab{selected}",
            current=current,
            attributes=attributes,
            app_view=tab,
            event_tab=tab if tab in {"recent", "upcoming"} else None,
        )

    recent_href = (
        f"/?tab=recent&recent_days={recent_days}&page_size={page_size}"
        f"{recent_search_param}"
    )
    upcoming_href = (
        f"/?tab=upcoming&recent_days={recent_days}&page_size={page_size}"
        f"{upcoming_search_param}"
    )
    return (
        '<nav class="tabs" aria-label="Application views">'
        + link("recent", "Recently added", recent_href)
        + link("upcoming", "Upcoming", upcoming_href)
        + link(
            "venues",
            "Venues",
            f"/?tab=venues&page_size={page_size}{venue_search_param}",
        )
        + link(
            "approvals", "Awaiting approval", f"/?tab=approvals&page_size={page_size}"
        )
        + "</nav>"
    )


def _render_app_page(
    *,
    title: str,
    active_tab: str,
    content: str,
    signals: Mapping[str, object] | None = None,
    recent_days: int = 7,
    search: str = "",
    heading: str = "Berlin Events Explorer",
    csrf_token: str | None = None,
) -> str:
    """Render the shared document shell around one tab's content fragment."""

    state: dict[str, object] = {
        "appView": active_tab,
        "eventTab": active_tab if active_tab in {"recent", "upcoming"} else "upcoming",
        "eventRecentDays": recent_days,
        "eventSearch": search if active_tab in {"recent", "upcoming"} else "",
        "venueSearch": search if active_tab == "venues" else "",
        "eventPageSize": DEFAULT_PAGE_SIZE,
        "eventCount": 0,
        "isSyncing": False,
        "syncError": None,
    }
    if signals:
        state.update(signals)
    navigation_page_size = state["eventPageSize"]
    if not isinstance(navigation_page_size, int):
        navigation_page_size = DEFAULT_PAGE_SIZE
    serialized_signals = escape(json.dumps(state), quote=True)
    sync_options = (
        f", {{headers: {{'{CSRF_HEADER_NAME}': '{csrf_token}'}}}}" if csrf_token else ""
    )
    sync_action = (
        "@post('sync?page_size=' + $eventPageSize + '&amp;tab=' + $eventTab "
        "+ '&amp;recent_days=' + $eventRecentDays + '&amp;search=' "
        f"+ encodeURIComponent($eventSearch) + '&amp;view=' + $appView{sync_options})"
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    <script type="module" src="{DATASTAR_SCRIPT}"></script>
    {theme.stylesheet_link()}
  </head>
  <body class="app-page">
    <main class="events-app" data-signals='{serialized_signals}'>
      <header class="events-header">
        <p class="page-kicker">Berlin Events</p>
        <div class="toolbar">
          <h1 data-text="$eventCount > 0 ? 'Berlin Events Explorer (' + $eventCount + ')' : 'Berlin Events Explorer'">{escape(heading)}</h1>
          <div class="toolbar-actions">
            <button type="button" class="sync-button" data-attr="{{'disabled': $isSyncing}}"
              data-text="$isSyncing ? 'Syncing...' : 'Sync now'" data-on:click="{sync_action}">Sync now</button>
            <a class="settings-link" href="/settings" aria-label="Open settings">⚙ Settings</a>
          </div>
        </div>
      </header>
      <p class="sync-error" data-show="$syncError !== null" data-text="$syncError"></p>
      <section id="sync-progress" class="sync-progress" aria-live="polite"></section>
      {_render_app_nav(active_tab=active_tab, recent_days=recent_days, search=search, page_size=navigation_page_size)}
      <section id="tab-content">{content}</section>
    </main>
    <script>window.addEventListener('popstate', () => window.location.reload())</script>
  </body>
</html>"""


def _render_tab_fragment(content: str, *, event_count: int) -> Stream:
    """Patch tab content and persistent shell signals in one Datastar response."""

    payload = _sse_event(
        "datastar-patch-elements",
        "selector #tab-content",
        "mode outer",
        f"elements {_render_tab_content_element(content)}",
    ) + _sse_event(
        "datastar-patch-signals",
        _signals_payload(
            event_count=event_count,
            is_syncing=False,
            sync_error=None,
        ),
    )
    return Stream(
        content=iter((payload,)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _render_tab_content_element(content: str) -> str:
    """Wrap tab content for a Datastar element patch event."""

    return f'<section id="tab-content">{content}</section>'


def _render_event_content(
    events: list[Event],
    *,
    total_count: int,
    page: int,
    page_size: int,
    total_pages: int,
    tab: str,
    recent_days: int,
    search: str,
    venue_ids_by_event: dict[str, str] | None = None,
    artist_ids_by_event_performer: dict[tuple[str, int], str] | None = None,
) -> str:
    """Render the events tab without the shared document shell."""

    recent_settings = ""
    if tab == "recent":
        options = "".join(
            f'<option value="{days}"{" selected" if days == recent_days else ""}>'
            f"Last {days} days</option>"
            for days in (1, 7, 14, 30, 90)
        )
        recent_settings = (
            '<form class="filter-side recent-settings" method="get">'
            '<input type="hidden" name="tab" value="recent">'
            f'<input type="hidden" name="page_size" value="{page_size}">'
            f'<input type="hidden" name="search" value="{escape(search, quote=True)}">'
            '<label for="recent-days">Added within</label>'
            '<select id="recent-days" name="recent_days" onchange="this.form.submit()">'
            f"{options}</select></form>"
        )
    events_html = _render_events_panel(
        events,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        tab=tab,
        recent_days=recent_days,
        search=search,
        venue_ids_by_event=venue_ids_by_event,
        artist_ids_by_event_performer=artist_ids_by_event_performer,
    )
    encoded_search = escape(search, quote=True)
    return f"""<section class="filter-bar" aria-labelledby="event-filter-label">
        <div class="filter-label" id="event-filter-label">
          <label for="event-filter">Filter events</label>
          <div class="filter-wrapper">
            <input class="filter-input" id="event-filter" type="search" name="search"
              data-bind="eventSearch"
              data-on:input__debounce_150ms="history.replaceState(null, '', '/?tab=' + $eventTab + '&amp;recent_days=' + $eventRecentDays + '&amp;page_size=' + $eventPageSize + '&amp;search=' + encodeURIComponent($eventSearch)); @get('/events/search?page_size=' + $eventPageSize + '&amp;tab=' + $eventTab + '&amp;recent_days=' + $eventRecentDays + '&amp;search=' + encodeURIComponent($eventSearch))"
              value="{encoded_search}" placeholder="Search by title, venue, or performers" autocomplete="off" />
            <button class="filter-clear" id="event-filter-clear" type="button" aria-label="Clear filter"
              data-attr="{{'hidden': $eventSearch.length === 0}}"
              data-on:click="$eventSearch = ''; history.replaceState(null, '', '/?tab=' + $eventTab + '&amp;recent_days=' + $eventRecentDays + '&amp;page_size=' + $eventPageSize); @get('/events/search?page_size=' + $eventPageSize + '&amp;tab=' + $eventTab + '&amp;recent_days=' + $eventRecentDays + '&amp;search=' + encodeURIComponent($eventSearch))">&times;</button>
          </div>
        </div>
        {recent_settings}
      </section>
      {events_html}"""


def _render_events_page_new(
    events: list[Event],
    *,
    total_count: int,
    page: int,
    page_size: int,
    total_pages: int,
    tab: str = "upcoming",
    recent_days: int = 7,
    search: str = "",
    venue_ids_by_event: dict[str, str] | None = None,
    artist_ids_by_event_performer: dict[tuple[str, int], str] | None = None,
    csrf_token: str | None = None,
) -> str:
    """Render the events page using the shared application shell."""

    active_tab = tab if tab in {"recent", "upcoming"} else "upcoming"
    content = _render_event_content(
        events,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        tab=active_tab,
        recent_days=recent_days,
        search=search,
        venue_ids_by_event=venue_ids_by_event,
        artist_ids_by_event_performer=artist_ids_by_event_performer,
    )
    return _render_app_page(
        title="Berlin Events Explorer",
        active_tab=active_tab,
        content=content,
        recent_days=recent_days,
        search=search,
        signals={
            "eventCount": total_count,
            "eventTab": active_tab,
            "eventRecentDays": recent_days,
            "eventSearch": search,
            "eventPageSize": page_size,
        },
        heading=f"Berlin Events Explorer ({total_count})",
        csrf_token=csrf_token,
    )


def _render_venues_content(
    summaries: list[VenueSummary],
    *,
    page: int = 1,
    page_size: int = DEFAULT_TABLE_SIZE,
    table_size: int | None = None,
    search: str = "",
) -> str:
    """Render one paginated venue catalog tab without the shared shell."""

    if table_size is not None:
        page_size = table_size
    filtered_summaries = _filter_venue_summaries(summaries, search)
    displayed_summaries, current_page, normalized_page_size, total_pages = (
        _paginate_venues(filtered_summaries, page=page, page_size=page_size)
    )
    total_venues = len(filtered_summaries)
    rows = ""
    for summary in displayed_summaries:
        venue = summary.venue
        district = venue.district or "Not listed"
        event_label = "event" if summary.event_count == 1 else "events"
        rows += (
            '<tr class="venue-row" data-venue-row '
            f'data-venue-href="/venues/{escape(venue.id, quote=True)}" '
            'tabindex="0" role="link">'
            f'<td data-label="Name"><a href="/venues/{escape(venue.id, quote=True)}">{escape(venue.name)}</a></td>'
            f'<td data-label="District">{escape(district)}</td>'
            f'<td data-label="Events">{summary.event_count} {event_label}</td>'
            "</tr>"
        )

    empty_table = (
        '<p class="empty-state">No venues have been synced yet.</p>'
        if not summaries
        else ""
    )
    start_index = (current_page - 1) * normalized_page_size + 1 if total_venues else 0
    end_index = min(
        (current_page - 1) * normalized_page_size + len(displayed_summaries),
        total_venues,
    )
    shown_text = f"Showing {start_index} to {end_index} of {total_venues} venues"
    has_prev = current_page > 1
    has_next = current_page < total_pages
    venue_search_param = (
        f"&search={quote_plus(search.strip())}" if search.strip() else ""
    )
    prev_url = (
        f"/?tab=venues&page={current_page - 1}&page_size={normalized_page_size}"
        f"{venue_search_param}"
        if has_prev
        else "#"
    )
    next_url = (
        f"/?tab=venues&page={current_page + 1}&page_size={normalized_page_size}"
        f"{venue_search_param}"
        if has_next
        else "#"
    )
    previous_link = (
        _render_in_place_link(
            prev_url,
            "Previous",
            class_name="pagination-link",
            app_view="venues",
        )
        if has_prev
        else '<a class="pagination-link disabled" href="#">Previous</a>'
    )
    next_link = (
        _render_in_place_link(
            next_url,
            "Next",
            class_name="pagination-link",
            app_view="venues",
        )
        if has_next
        else '<a class="pagination-link disabled" href="#">Next</a>'
    )
    pagination = f"""
      <div class="pagination" aria-label="Venue pagination">
        {previous_link}
        <span class="pagination-page">Page {current_page} of {total_pages}</span>
        {next_link}
      </div>
    """
    encoded_search = escape(search, quote=True)
    return f"""<section class="filter-bar" aria-labelledby="venue-filter-label">
        <label class="filter-label" id="venue-filter-label" for="venue-filter">Filter venues
          <div class="filter-wrapper">
            <input class="filter-input" id="venue-filter" type="search" name="search"
              data-bind="venueSearch"
              data-on:input__debounce_350ms="history.replaceState(null, '', '/?tab=venues&amp;page_size=' + $eventPageSize + '&amp;search=' + encodeURIComponent($venueSearch)); @get('/?tab=venues&amp;page_size=' + $eventPageSize + '&amp;search=' + encodeURIComponent($venueSearch) + '&amp;fragment=1')"
              value="{encoded_search}" placeholder="Search by venue or district" autocomplete="off" />
            <button class="filter-clear" id="venue-filter-clear" type="button" aria-label="Clear filter"
              data-attr="{{'hidden': $venueSearch.length === 0}}"
              data-on:click="$venueSearch = ''; history.replaceState(null, '', '/?tab=venues&amp;page_size=' + $eventPageSize); @get('/?tab=venues&amp;page_size=' + $eventPageSize + '&amp;fragment=1')">&times;</button>
          </div>
        </label>
      </section>
      <section id="venue-panel" class="table-panel" aria-label="Venue list" style="--table-view-height:{_table_view_height(normalized_page_size)}">
        <div class="table-scroll">
          {empty_table}
          <table class="event-table"><thead><tr><th>Name</th><th>District</th><th>Events</th></tr></thead><tbody>{rows}</tbody></table>
        </div>
        <footer class="table-footer">
          <p class="meta" id="venue-result-count" aria-live="polite">{shown_text}</p>
          {pagination}
        </footer>
      </section>
      <script>
        (() => {{
          const rows = [...document.querySelectorAll("[data-venue-row]")];
          for (const row of rows) {{ row.addEventListener("click", (event) => {{
            if (!event.target.closest("a")) window.location.assign(row.dataset.venueHref); }});
            row.addEventListener("keydown", (event) => {{ if (event.key === "Enter" || event.key === " ") {{
              event.preventDefault(); window.location.assign(row.dataset.venueHref); }} }}); }}
        }})();
      </script>"""


def _filter_venue_summaries(
    summaries: list[VenueSummary], search: str
) -> list[VenueSummary]:
    """Filter the complete venue catalog before pagination."""

    query = search.strip().casefold()
    if not query:
        return summaries
    return [
        summary
        for summary in summaries
        if query
        in f"{summary.venue.name} {summary.venue.district or 'Not listed'}".casefold()
    ]


def _render_venues_page_new(
    summaries: list[VenueSummary],
    *,
    table_size: int = DEFAULT_TABLE_SIZE,
    page: int = 1,
    page_size: int | None = None,
    search: str = "",
    csrf_token: str | None = None,
) -> str:
    """Render the venue catalog using the shared application shell."""

    normalized_page_size = _normalize_page_size(page_size or table_size)
    return _render_app_page(
        title="Venues · Berlin Events Explorer",
        active_tab="venues",
        content=_render_venues_content(
            summaries,
            page=page,
            page_size=normalized_page_size,
            search=search,
        ),
        signals={"eventPageSize": normalized_page_size, "venueSearch": search},
        csrf_token=csrf_token,
    )


def _render_approval_content(
    venues: list[VenueRecord],
    venue_candidate_counts: dict[str, int],
    artists: list[ArtistRecord],
    artist_candidate_counts: dict[str, int],
    *,
    entity_type: str,
) -> str:
    """Render the approval queue tab without the shared document shell."""

    venue_rows = "".join(
        '<tr><td><span class="status">Venue</span></td>'
        f'<td><a href="/approvals/venues/{escape(venue.id)}">{escape(venue.name)}</a></td>'
        f"<td>{escape(venue.status.value.replace('_', ' ').title())}</td>"
        f"<td>{venue_candidate_counts.get(venue.id, 0)} {'suggestion' if venue_candidate_counts.get(venue.id, 0) == 1 else 'suggestions'}</td></tr>"
        for venue in venues
    )
    artist_rows = "".join(
        '<tr><td><span class="status">Artist</span></td>'
        f'<td><a href="/approvals/artists/{escape(artist.id)}">{escape(artist.name)}</a></td>'
        f"<td>{escape(artist.status.value.replace('_', ' ').title())}</td>"
        f"<td>{artist_candidate_counts.get(artist.id, 0)} {'suggestion' if artist_candidate_counts.get(artist.id, 0) == 1 else 'suggestions'}</td></tr>"
        for artist in artists
    )
    rows = (
        venue_rows
        if entity_type == "venues"
        else artist_rows
        if entity_type == "artists"
        else venue_rows + artist_rows
    )
    tabs = "".join(
        _render_in_place_link(
            f"/?tab=approvals&entity_type={value}",
            label,
            class_name=f"tab{' active' if selected else ''}",
            app_view="approvals",
        )
        for value, label, selected in (
            ("all", "All", entity_type == "all"),
            ("venues", "Venues", entity_type == "venues"),
            ("artists", "Artists", entity_type == "artists"),
        )
    )
    empty = '<p class="muted">Nothing is waiting for approval.</p>' if not rows else ""
    return f"""<nav class="tabs" aria-label="Entity filters">{tabs}</nav>
      <section class="card">{empty}<table><thead><tr><th>Type</th><th>Name</th><th>Status</th><th>Suggestions</th></tr></thead><tbody>{rows}</tbody></table></section>"""


def _render_approval_queue_new(
    venues: list[VenueRecord],
    venue_candidate_counts: dict[str, int],
    artists: list[ArtistRecord],
    artist_candidate_counts: dict[str, int],
    *,
    entity_type: str,
    csrf_token: str | None = None,
) -> str:
    """Render the approval queue using the shared application shell."""

    return _render_app_page(
        title="Awaiting approval · Berlin Events Explorer",
        active_tab="approvals",
        content=_render_approval_content(
            venues,
            venue_candidate_counts,
            artists,
            artist_candidate_counts,
            entity_type=entity_type,
        ),
        csrf_token=csrf_token,
    )


# The public renderer names are kept stable for callers and existing tests while
# the implementations above provide the shared shell.
render_events_page = _render_events_page_new
_render_venues_page = _render_venues_page_new
_render_approval_queue = _render_approval_queue_new


def perform_sync(
    store: EventStore,
    *,
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
    progress: VenueProgressCallback | None = None,
) -> None:
    """Run one synchronization pass for the configured source."""

    if not _SYNC_LOCK.acquire(blocking=False):
        raise SyncInProgressError("A sync is already in progress.")
    try:
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
    finally:
        _SYNC_LOCK.release()


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
