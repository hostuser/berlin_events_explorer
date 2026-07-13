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

import json
from datetime import date
from html import escape
from pathlib import Path
import math

import httpx
from litestar import Litestar, get, post
from litestar.response import Response, Stream

from berlin_events_explorer.models import Event
from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.sync import SyncError, open_sync_cache, sync_source

DATASTAR_SCRIPT = (
    "https://cdn.jsdelivr.net/gh/starfederation/datastar"
    "@v1.0.0-RC.7/bundles/datastar.js"
)
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def create_app(database: Path | str = Path("events.sqlite")) -> Litestar:
    """Create a Litestar app that renders stored events as HTML."""

    store = EventStore(database)

    @get("/", sync_to_thread=True)
    def index(page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> Response:
        events = _sorted_events(list(store.list_events()))
        paged_events, current_page, normalized_page_size, total_pages = (
            _paginate_events(
                events,
                page=page,
                page_size=page_size,
            )
        )
        html = render_events_page(
            paged_events,
            total_count=len(events),
            page=current_page,
            page_size=normalized_page_size,
            total_pages=total_pages,
        )
        return Response(content=html, media_type="text/html")

    @post("/sync", status_code=200, sync_to_thread=True)
    def sync(page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> Stream:
        return Stream(
            content=_perform_sync_stream(store, page=page, page_size=page_size),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @get("/health", sync_to_thread=False)
    def health() -> dict[str, str]:
        """Health check endpoint for container and deployment tooling."""

        return {"status": "ok"}

    return Litestar(route_handlers=[index, sync, health])


def render_events_page(
    events: list[Event],
    *,
    total_count: int,
    page: int,
    page_size: int,
    total_pages: int,
) -> str:
    """Render a full HTML page with the provided events."""

    events_html = _render_events_panel(
        events,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )

    return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Berlin Events Explorer</title>
    <script type=\"module\" src=\"{DATASTAR_SCRIPT}\"></script>
    <style>
      body {{
        font-family: Arial, sans-serif;
        margin: 1.5rem;
        color: #1f2937;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
      }}
      th,
      td {{
        padding: 0.65rem 0.5rem;
        border-bottom: 1px solid #e5e7eb;
        text-align: left;
      }}
      th {{
        color: #374151;
        font-weight: 600;
      }}
      .meta {{
        color: #4b5563;
        font-size: 0.9rem;
      }}
      .sync-error {{
        color: #b91c1c;
        min-height: 1.1rem;
      }}
      .sync-button {{
        margin-bottom: 1rem;
        padding: 0.45rem 0.9rem;
        border: 1px solid #2563eb;
        border-radius: 0.375rem;
        background-color: #2563eb;
        color: white;
        cursor: pointer;
      }}
      .sync-button:hover {{
        background-color: #1d4ed8;
      }}
      .pagination {{
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin: 0.5rem 0 0.75rem;
      }}
      .pagination-link {{
        border: 1px solid #9ca3af;
        border-radius: 0.35rem;
        color: #1f2937;
        text-decoration: none;
        padding: 0.25rem 0.6rem;
      }}
      .pagination-link:hover {{
        background: #f3f4f6;
      }}
      .pagination-link.disabled {{
        color: #9ca3af;
        pointer-events: none;
      }}
      .pagination-page {{
        font-size: 0.9rem;
      }}

  </head>
  <body>
    <main data-signals='{{eventCount: {total_count}, isSyncing: false, syncError: null}}'>
      <h1 data-text="'Berlin Events Explorer (' + $eventCount + ')'">Berlin Events Explorer</h1>
      <button
        type="button"
        class="sync-button"
        data-attr="{{'disabled': $isSyncing}}"
        data-text="$isSyncing ? 'Syncing...' : 'Sync now'"
        data-on:click="@post('sync')">

        Sync now
      </button>
      <p class="sync-error" data-show="$syncError !== null" data-text="$syncError"></p>
      {events_html}
    </main>
  </body>
</html>
"""


def _perform_sync_stream(
    store: EventStore, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
):
    """Run sync and emit Datastar SSE patch events."""

    current_events = _sorted_events(list(store.list_events()))
    yield _sse_event(
        "datastar-patch-signals",
        _signals_payload(
            event_count=len(current_events), is_syncing=True, sync_error=None
        ),
    )

    sync_error: str | None
    try:
        perform_sync(store)
        sync_error = None
    except SyncError as exc:
        sync_error = f"Sync failed: {escape(str(exc))}"
    except httpx.RequestError as exc:
        sync_error = f"Sync failed: {escape(str(exc))}"

    synced_events = _sorted_events(list(store.list_events()))
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
) -> str:
    """Render the event table section used for live updates."""

    rows = "".join(_render_event_row(event) for event in events)
    empty_state = "<p>No events have been synced yet.</p>" if not events else ""

    start_index = (page - 1) * page_size + 1 if total_count else 0
    end_index = min((page - 1) * page_size + len(events), total_count)
    has_prev = page > 1
    has_next = page < total_pages
    prev_url = f"/?page={page - 1}&page_size={page_size}" if has_prev else "#"
    next_url = f"/?page={page + 1}&page_size={page_size}" if has_next else "#"

    pagination = f"""
      <p class="meta">Showing {start_index} to {end_index} of {total_count} events</p>
      <div class="pagination" aria-label="Event pagination">
        <a class="pagination-link {'disabled' if not has_prev else ''}" href="{prev_url}">Previous</a>
        <span class="pagination-page">Page {page} of {total_pages}</span>
        <a class="pagination-link {'disabled' if not has_next else ''}" href="{next_url}">Next</a>
      </div>
    """

    return f"""<section id=\"events-panel\">
      {empty_state}
      {pagination}
      <table>
        <thead>
          <tr>
            <th>Start date</th>
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


def _render_event_row(event: Event) -> str:
    """Render one event row for the HTML table."""

    event_date = event.start_date.isoformat() if event.start_date else "TBA"
    title = escape(event.title)
    venue = escape(event.venue.name) if event.venue else "TBA"
    performers = ", ".join(escape(performer.name) for performer in event.performers)
    tags = ", ".join(escape(tag) for tag in event.tags)

    return (
        "<tr>"
        f"<td>{event_date}</td>"
        f"<td>{title}</td>"
        f"<td>{venue}</td>"
        f"<td>{performers or 'TBA'}</td>"
        f"<td>{tags or '—'}</td>"
        "</tr>"
    )


def perform_sync(store: EventStore) -> None:
    """Run one synchronization pass for the configured source."""

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        with open_sync_cache() as cache:
            sync_source(
                MyTrueIntentSource(),
                store,
                client,
                http_cache=cache,
            )


def run_server(*, database: Path, host: str, port: int, reload: bool = False) -> None:
    """Run the Litestar application with uvicorn."""

    import uvicorn

    app = create_app(database)
    uvicorn.run(app, host=host, port=port, reload=reload)
