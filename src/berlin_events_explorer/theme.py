# theme.py
#
# Copyright (c) 2026 Markus Binsteiner
# All rights reserved.
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License

"""Single consolidated stylesheet for the web UI (docs/design_language.md §11).

All CSS lives here in cascade layers (tokens, base, components, views) and is
served once at ``/static/app.css``. Pages opt into their rules through a class
on ``<body>``: the shared shell uses ``app-page``; standalone documents use
``login-page``, ``settings-page``, ``approval-page``, ``detail-page``, or
``date-page``.

Color tokens live in ``_TOKEN_VALUES`` so the contrast test can verify every
§3.3 pair against WCAG 2.2 AA. A hex literal outside the tokens layer is a
defect (§3.4) — extend the system by adding a semantic role here, never by
inlining a color in a component rule.
"""

from hashlib import sha256

# Light theme ("paper"), design_language.md §3.1.
_TOKEN_VALUES: dict[str, str] = {
    "color-bg": "#F4F4F1",
    "color-surface": "#FFFFFF",
    "color-surface-sunken": "#ECEDE9",
    "color-text": "#1A1C1E",
    "color-text-muted": "#52565C",
    "color-line": "#D8D9D4",
    "color-edge": "#6F747B",
    "color-accent": "#F0D722",
    "color-accent-wash": "#FAF5D7",
    "color-danger": "#B42318",
    "color-danger-strong": "#8C1D13",
    "color-danger-wash": "#FCEBE8",
    "color-success": "#1E6A42",
    "color-success-wash": "#E7F2EA",
    "color-warn": "#6E5200",
    "color-warn-wash": "#FAF0CF",
    "color-focus": "#1A1C1E",
}

# §3.3 verified pairs: (foreground, background, required ratio).
CONTRAST_PAIRS: list[tuple[str, str, float]] = [
    ("color-text", "color-bg", 4.5),
    ("color-text-muted", "color-surface", 4.5),
    ("color-text", "color-accent", 4.5),
    ("color-danger", "color-surface", 4.5),
    ("color-danger-strong", "color-danger-wash", 4.5),
    ("color-success", "color-success-wash", 4.5),
    ("color-warn", "color-warn-wash", 4.5),
    ("color-edge", "color-surface", 3.0),
]

_FONT_FILES = (
    "/static/fonts/inter-var.woff2",
    "/static/fonts/d-din-condensed-bold.woff2",
)


def _color_tokens() -> str:
    return "\n".join(f"  --{name}: {value};" for name, value in _TOKEN_VALUES.items())


_TOKENS = f"""
:root {{
{_color_tokens()}
  --font-display: "D-DIN Condensed", "Archivo Narrow", "Arial Narrow", sans-serif;
  --font-body: "Inter", "Segoe UI", "Helvetica Neue", sans-serif;
  --font-mono: ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, monospace;
  --text-xs: 0.75rem;
  --text-sm: 0.85rem;
  --text-base: 0.95rem;
  --text-md: 1.1rem;
  --text-lg: 1.35rem;
  --text-display: clamp(1.6rem, 2.6vw, 2.4rem);
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.5rem;
  --space-6: 2rem;
  --space-7: 3rem;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-full: 999px;
  --motion-fast: 120ms;
  --motion-base: 200ms;
  --shadow-overlay: 0 8px 24px rgb(0 0 0 / 0.16);
}}
"""

_BASE = """
@font-face {
  font-family: "Inter";
  src: url("/static/fonts/inter-var.woff2") format("woff2");
  font-weight: 100 900;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: "D-DIN Condensed";
  src: url("/static/fonts/d-din-condensed-bold.woff2") format("woff2");
  font-weight: 700;
  font-style: normal;
  font-display: swap;
}
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; color: var(--color-text);
  font-family: var(--font-body); font-size: var(--text-base); line-height: 1.55;
  background: var(--color-bg); }
/* Links are ink, marked by the accent underline — never blue (§3.4). */
a { color: var(--color-text); text-decoration: underline;
  text-decoration-color: var(--color-accent); text-decoration-thickness: 2px;
  text-underline-offset: 0.15em; }
a:hover { background: var(--color-accent-wash); }
button, input, select { line-height: 1.35; }
:focus-visible { outline: 2px solid var(--color-focus); outline-offset: 2px; }
/* The timetable rule (§4.3): figures align vertically. */
.event-table td, time, .pagination, .result-count, .meta, .stamp {
  font-variant-numeric: tabular-nums; }
a, button, .tab, .pagination-link, .settings-link {
  transition: background-color var(--motion-fast) ease-out,
    border-color var(--motion-fast) ease-out, color var(--motion-fast) ease-out; }
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after { transition: none !important; animation: none !important; }
  ::view-transition-group(*), ::view-transition-old(*), ::view-transition-new(*) {
    animation: none !important;
  }
}
"""

_COMPONENTS = """
/* --- application shell --- */
.events-app { max-width: 1100px; margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-7); }
.events-header { margin-bottom: var(--space-4); }
.page-kicker, .kicker, .section-label { display: inline-block; margin: 0 0 var(--space-1);
  color: var(--color-text-muted); font-size: var(--text-xs); font-weight: 600;
  letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: .2rem 0 .5rem; font-family: var(--font-display);
  font-size: var(--text-display); font-weight: 700; letter-spacing: -.01em;
  line-height: 1.1; }
.toolbar { display: flex; justify-content: space-between; align-items: center;
  gap: var(--space-3); flex-wrap: wrap; }
.toolbar-actions { display: flex; align-items: center; gap: var(--space-2); }
.settings-link { display: inline-flex; align-items: center; min-height: 2.35rem;
  padding: .45rem .75rem; border: 1px solid var(--color-edge);
  border-radius: var(--radius-md); color: var(--color-text);
  background: var(--color-surface-sunken); text-decoration: none; font-weight: 600; }
.settings-link:hover { background: var(--color-accent-wash); }
/* Primary action: ink on signal yellow with an ink border — the BVG move (§7.3). */
.sync-button { border: 1px solid var(--color-text); padding: .5rem 1rem;
  border-radius: var(--radius-md); background: var(--color-accent);
  color: var(--color-text); font: inherit; font-weight: 700; cursor: pointer; }
.sync-button:hover { background: var(--color-accent-wash); }
.sync-button:disabled { background: var(--color-surface-sunken);
  color: var(--color-text-muted); border-color: var(--color-edge); cursor: not-allowed; }
.sync-error { min-height: 1.1rem; margin: var(--space-2) 0; color: var(--color-danger);
  font-weight: 500; }
.sync-progress { display: grid; gap: .45rem; margin: var(--space-3) 0;
  color: var(--color-text-muted); font-size: .92rem; }
.sync-progress p { margin: 0; }
.sync-progress progress { width: min(34rem, 100%); height: .65rem;
  accent-color: var(--color-accent); }
/* Tabs: display face; the active marker is the yellow rule beneath ink (§7.1). */
.tabs { display: flex; gap: var(--space-1); align-items: center; margin: var(--space-5) 0;
  border-bottom: 1px solid var(--color-line); overflow-x: auto; }
.tab { color: var(--color-text-muted); padding: .55rem .85rem; text-decoration: none;
  border-bottom: 3px solid transparent; font-family: var(--font-display);
  font-size: var(--text-md); letter-spacing: .02em; text-transform: uppercase;
  font-weight: 700; white-space: nowrap; }
.tab:hover { color: var(--color-text); background: var(--color-accent-wash); }
.tab.active { color: var(--color-text); border-bottom-color: var(--color-accent); }
#tab-content { view-transition-name: tab-content; }

/* --- events view --- */
.recent-settings { display: flex; align-items: flex-end; justify-content: flex-end;
  gap: var(--space-2); margin: 0; color: var(--color-text-muted); font-size: var(--text-sm); }
.recent-settings label { white-space: nowrap; }
.recent-settings select { border: 1px solid var(--color-edge);
  border-radius: var(--radius-md); padding: .35rem .5rem;
  background: var(--color-surface); color: var(--color-text); }
.filter-bar { display: grid; grid-template-columns: minmax(0, 1fr) auto;
  align-items: end; gap: var(--space-4); margin: var(--space-5) 0 var(--space-3); }
.filter-label { display: grid; gap: .35rem; color: var(--color-text);
  font-size: var(--text-sm); font-weight: 600; width: min(28rem, 100%); }
.filter-input { width: 100%; padding: .72rem .8rem; border: 1px solid var(--color-edge);
  border-radius: var(--radius-md); color: var(--color-text);
  background: var(--color-surface); font: inherit; }
.filter-wrapper { position: relative; }
.filter-clear { position: absolute; right: .5rem; top: 50%; transform: translateY(-50%);
  display: flex; align-items: center; justify-content: center; width: 1.4rem;
  height: 1.4rem; border: 0; border-radius: var(--radius-full);
  background: var(--color-surface-sunken); color: var(--color-text);
  cursor: pointer; padding: 0; }
.result-count, .meta { color: var(--color-text-muted); font-size: var(--text-sm);
  margin: 0; }
#events-panel { margin-top: var(--space-2); background: var(--color-surface);
  border: 1px solid var(--color-line); border-radius: var(--radius-lg);
  padding: .9rem; }
.table-scroll { height: var(--table-view-height); overflow: auto; }
.table-footer { display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-4); min-height: 2.5rem; margin-top: var(--space-2); }
.pagination { display: flex; align-items: center; gap: var(--space-3); margin: 0; }
.pagination-link { border-radius: var(--radius-full); border: 1px solid var(--color-edge);
  color: var(--color-text); text-decoration: none; padding: .35rem .85rem;
  font-size: var(--text-sm); background: var(--color-surface); }
.pagination-link:hover { background: var(--color-accent-wash); }
.pagination-link.disabled { color: var(--color-text-muted); pointer-events: none;
  background: var(--color-surface-sunken); border-color: var(--color-line); }

/* --- venues view --- */
#venue-panel { margin-top: var(--space-2); background: var(--color-surface);
  border: 1px solid var(--color-line); border-radius: var(--radius-lg);
  padding: .9rem; }
.venue-row { cursor: pointer; }
.venue-row:hover td, .venue-row:focus td { background: var(--color-accent-wash); }
.empty-state { color: var(--color-text-muted); margin: .35rem 0; }

/* --- approval workflow (queue tab + editor pages) --- */
.approval-page main { max-width: 1100px; margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-7); }
.muted { color: var(--color-text-muted); }
.card { background: var(--color-surface); border: 1px solid var(--color-line);
  border-radius: var(--radius-lg); padding: var(--space-4); }
.card table { width: 100%; border-collapse: collapse; }
.card th, .card td { text-align: left; padding: .7rem .55rem;
  border-bottom: 1px solid var(--color-line); }
.card th { color: var(--color-text); font-size: var(--text-sm); }
.status { display: inline-block; padding: .18rem .55rem;
  border-radius: var(--radius-sm); background: var(--color-surface-sunken);
  color: var(--color-text-muted); font-size: var(--text-xs); }
.suggestions { display: grid; gap: .7rem; margin: var(--space-4) 0; }
.suggestion { display: block; border: 1px solid var(--color-line);
  border-radius: var(--radius-lg); padding: .85rem; text-decoration: none;
  color: var(--color-text); background: var(--color-surface); }
.suggestion.selected { border-color: var(--color-text);
  box-shadow: 0 0 0 1px var(--color-text); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .85rem; }
.field-wide { grid-column: 1 / -1; }
.app-page label, .approval-page label { display: block; color: var(--color-text);
  font-size: var(--text-sm); font-weight: 600; }
.app-page input, .approval-page input { width: 100%; margin-top: .3rem;
  padding: .65rem .7rem; border: 1px solid var(--color-edge);
  border-radius: var(--radius-md); color: var(--color-text);
  background: var(--color-surface); }
.actions { display: flex; flex-wrap: wrap; gap: .65rem; margin-top: var(--space-4); }
.app-page button, .app-page .button,
.approval-page button, .approval-page .button { border: 1px solid var(--color-text);
  border-radius: var(--radius-md); padding: .6rem .95rem; font-weight: 700;
  cursor: pointer; background: var(--color-accent); color: var(--color-text); }
.app-page .button, .approval-page .button { display: inline-block;
  text-decoration: none; }
.app-page button.secondary, .app-page .button.secondary,
.approval-page button.secondary, .approval-page .button.secondary {
  background: var(--color-surface-sunken); color: var(--color-text);
  border-color: var(--color-edge); }
/* Notices: wash + strong text + solid left border as the non-color cue (§7.6). */
.error { color: var(--color-danger-strong); background: var(--color-danger-wash);
  border-left: 4px solid var(--color-danger); border-radius: var(--radius-md);
  padding: .7rem .9rem; }
.notice { padding: .8rem 1rem; border-radius: var(--radius-md); font-weight: 600;
  border-left: 4px solid transparent; }
.notice.success { color: var(--color-success); background: var(--color-success-wash);
  border-left-color: var(--color-success); }
.notice.error { color: var(--color-danger-strong); background: var(--color-danger-wash);
  border-left-color: var(--color-danger); }
.events-section { margin-top: var(--space-5); }
.events-card { max-height: 23rem; overflow: auto; padding: 0 var(--space-4) var(--space-4); }
.events-card .event-table { display: table; }
.events-card .event-table thead { display: table-header-group; }
.events-card .event-table tbody { display: table-row-group; }
.events-card .event-table tr { display: table-row; }
.events-card .event-table th,
.events-card .event-table td { display: table-cell; }
.events-card .event-table tbody tr td::before { content: none; display: none; }

/* --- event table (§7.2) --- */
.event-table { width: 100%; border-collapse: collapse; font-size: var(--text-base); }
.event-table th, .event-table td { line-height: 1.35; }
.event-table thead { display: table-header-group; position: sticky; top: 0; z-index: 1; }
.event-table thead th { font-weight: 600; color: var(--color-text);
  background: var(--color-surface-sunken); text-align: left;
  border-bottom: 1px solid var(--color-line); padding: 0.55rem 0.5rem; }
.event-table th,
.event-table td { text-align: left; vertical-align: top; padding: 0.6rem 0.5rem;
  border-bottom: 1px solid var(--color-line); }
.event-table tbody tr:hover td { background: var(--color-accent-wash); }
.event-table tbody tr:last-child td { border-bottom: none; }
.event-table .date-link { white-space: nowrap; }

@media (max-width: 720px) {
  .events-app { padding: var(--space-4) var(--space-3) var(--space-6); }
  .toolbar { align-items: stretch; }
  .toolbar-actions { flex-wrap: wrap; }
  .filter-bar { grid-template-columns: minmax(0, 1fr); gap: .55rem; }
  .filter-label { width: auto; min-width: 0; }
  .recent-settings { display: grid; justify-items: end; gap: .35rem; }
  .table-footer { align-items: flex-start; flex-direction: column; }
  .pagination { flex-wrap: wrap; }
  .approval-page main { padding: var(--space-4) var(--space-3) var(--space-6); }
  .approval-page .form-grid { grid-template-columns: 1fr; }
  .approval-page .field-wide { grid-column: auto; }
  .card table, .card thead, .card tbody, .card tr, .card th, .card td { display: block; }
  .card thead { display: none; }
  .card tr { border-bottom: 1px solid var(--color-line); padding: .5rem 0; }
  .card td { border: 0; }
  .event-table, .event-table thead, .event-table tbody, .event-table tr,
  .event-table th, .event-table td { display: block; }
  .event-table thead { display: none; }
  .event-table tbody tr { margin-bottom: 0.7rem; border: 1px solid var(--color-line);
    border-radius: var(--radius-md); overflow: hidden; }
  .event-table tbody tr td { padding: 0.45rem 0.65rem;
    border-bottom: 1px solid var(--color-line); }
  .event-table tbody tr td::before { content: attr(data-label); display: block;
    color: var(--color-text-muted); font-size: var(--text-xs); margin-bottom: 0.2rem;
    letter-spacing: 0.04em; text-transform: uppercase; }
  .event-table tbody tr td:last-child { border-bottom: none; }
}
"""

_VIEWS = """
/* --- login --- */
.login-page main { width: min(26rem, calc(100% - 2rem)); margin: 14vh auto 0; }
.login-page .card { padding: var(--space-5); }
.login-page h1 { margin: 0 0 .3rem; }
.login-page p { color: var(--color-text-muted); }
.login-page label { display: block; margin-top: var(--space-4); font-weight: 600; }
.login-page input { display: block; width: 100%; margin: .4rem 0 .3rem;
  padding: .72rem .8rem; border: 1px solid var(--color-edge);
  border-radius: var(--radius-md); font: inherit; }
.login-page button { margin-top: .9rem; padding: .72rem 1rem;
  border: 1px solid var(--color-text); border-radius: var(--radius-md);
  background: var(--color-accent); color: var(--color-text); font: inherit;
  font-weight: 700; cursor: pointer; }
.login-page .back-link { display: inline-block; margin-top: var(--space-4); }

/* --- settings --- */
.settings-page main { width: min(760px, calc(100% - 2rem)); margin: 0 auto;
  padding: var(--space-6) 0 var(--space-7); }
.settings-header { display: flex; justify-content: space-between;
  align-items: flex-start; gap: var(--space-4); margin-bottom: var(--space-5); }
.settings-page .back-link { white-space: nowrap; margin-top: .4rem; }
.settings-stack { display: grid; gap: var(--space-4); }
.settings-card { padding: var(--space-5); border: 1px solid var(--color-line);
  border-radius: var(--radius-lg); background: var(--color-surface); }
.settings-page h2 { margin: .1rem 0 .55rem; font-size: var(--text-md); }
.settings-page label { display: block; margin-top: var(--space-4); font-weight: 600; }
.settings-page input { display: block; width: min(14rem, 100%); margin: .4rem 0 .3rem;
  padding: .72rem .8rem; border: 1px solid var(--color-edge);
  border-radius: var(--radius-md); font: inherit; }
.hint, .settings-card p { color: var(--color-text-muted); line-height: 1.55; }
.settings-page button { margin-top: .8rem; padding: .72rem 1rem;
  border: 1px solid var(--color-text); border-radius: var(--radius-md);
  background: var(--color-accent); color: var(--color-text); font: inherit;
  font-weight: 700; cursor: pointer; }
.danger-zone { border-color: var(--color-danger); background: var(--color-danger-wash); }
.danger-zone .section-label, .danger-zone h2 { color: var(--color-danger-strong); }
.settings-page .danger-button { background: var(--color-danger);
  color: var(--color-surface); border-color: var(--color-danger-strong); }
@media (max-width: 560px) {
  .settings-header { display: block; }
  .settings-page .back-link { display: inline-block; margin-top: var(--space-4); }
}

/* --- venue & artist detail --- */
.detail-page main { max-width: 760px; margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-7); }
.detail-page .card { padding: var(--space-5); }
.detail-header { display: flex; align-items: flex-start;
  justify-content: space-between; gap: var(--space-4); }
.detail-header h1 { margin: .2rem 0 0; }
.detail-actions { display: flex; flex-wrap: wrap; gap: .65rem;
  margin-top: var(--space-5); }
.action-button { display: inline-flex; align-items: center; justify-content: center;
  min-height: 2.4rem; padding: .6rem .9rem; border: 1px solid var(--color-text);
  border-radius: var(--radius-md); background: var(--color-accent);
  color: var(--color-text); font: inherit; font-weight: 700;
  text-decoration: none; cursor: pointer; }
.action-button.secondary { border-color: var(--color-edge);
  background: var(--color-surface-sunken); color: var(--color-text); }
.artist-links { display: flex; flex-wrap: wrap; gap: .35rem .75rem; }
.venue-map { margin-top: var(--space-5); }
.venue-map h2 { margin-bottom: .65rem; }
.venue-map iframe { display: block; width: 100%; min-height: 22rem;
  border: 1px solid var(--color-line); border-radius: var(--radius-lg); }
.venue-map p { margin: .6rem 0 0; }
.detail-page dt { color: var(--color-text-muted); margin-top: var(--space-4);
  font-size: var(--text-xs); letter-spacing: .08em; text-transform: uppercase; }
.detail-page dd { margin: .25rem 0 0; }
.detail-page .events-card { background: var(--color-surface);
  border: 1px solid var(--color-line); border-radius: var(--radius-lg);
  padding: .9rem; max-height: none; overflow: visible; }
@media (max-width: 560px) {
  .detail-header { display: block; }
  .detail-header .action-button { margin-top: .9rem; }
}

/* --- events-on-date --- */
.date-page main { max-width: 1100px; margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-7); }
.date-page h1 { margin: 0; }
.date-page .back-link { display: inline-block; margin-bottom: var(--space-5); }
.date-page .meta { font-size: var(--text-base); margin: .55rem 0 1.1rem; }
.date-page .card { padding: .9rem; }
@media (max-width: 720px) {
  .date-page main { padding: var(--space-4) var(--space-3) var(--space-6); }
}
"""


def stylesheet() -> str:
    """Assemble the complete application stylesheet."""

    return (
        "@layer tokens, base, components, views;\n"
        f"@layer tokens {{{_TOKENS}}}\n"
        f"@layer base {{{_BASE}}}\n"
        f"@layer components {{{_COMPONENTS}}}\n"
        f"@layer views {{{_VIEWS}}}\n"
    )


_CSS = stylesheet()
STYLESHEET_HREF = f"/static/app.css?v={sha256(_CSS.encode()).hexdigest()[:12]}"


def stylesheet_link() -> str:
    """Return the ``<link>`` tag every page uses to load the stylesheet."""

    return f'<link rel="stylesheet" href="{STYLESHEET_HREF}" />'


def font_preloads() -> str:
    """Return preload tags for the two self-hosted webfonts (§4.1)."""

    return "".join(
        f'<link rel="preload" href="{path}" as="font" type="font/woff2" crossorigin />'
        for path in _FONT_FILES
    )


def head_assets() -> str:
    """Return every asset tag a page's ``<head>`` needs."""

    return f"{font_preloads()}{stylesheet_link()}"
