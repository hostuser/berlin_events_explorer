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
          <button
            type="button"
            class="sync-button"
            data-attr="{{'disabled': $isSyncing}}"
            data-text="$isSyncing ? 'Syncing...' : 'Sync now'"
            data-on:click="@post('sync')">
            Sync now
          </button>
        </div>
      </header>
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
    prev_url = f"?page={page - 1}&page_size={page_size}" if has_prev else "#"
    next_url = f"?page={page + 1}&page_size={page_size}" if has_next else "#"

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
        f"<td data-label=\"Start date\">{event_date}</td>"
        f"<td data-label=\"Title\">{title}</td>"
        f"<td data-label=\"Venue\">{venue}</td>"
        f"<td data-label=\"Performers\">{performers or 'TBA'}</td>"
        f"<td data-label=\"Tags\">{tags or '—'}</td>"
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
