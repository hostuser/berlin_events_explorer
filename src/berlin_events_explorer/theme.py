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

Phase 1 (consolidation) keeps the pre-migration rendering: token names follow
design_language.md §3 but carry the previous app-shell values, and one-off hex
literals that had no token role are ported verbatim. Phase 2 replaces both
with the Fahrplan palette, after which a hex literal outside the tokens layer
is a defect (§3.4).
"""

from hashlib import sha256

# Phase 1 interim values: the current app-shell vocabulary under the §3 token
# names. Phase 2 swaps these for the Fahrplan palette.
_TOKENS = """
:root {
  --color-bg: #f6f7fb;
  --color-surface: #ffffff;
  --color-surface-sunken: #f3f5f9;
  --color-text: #0f172a;
  --color-text-muted: #64748b;
  --color-line: #d5dbe8;
  --color-edge: #b9c2d0;
  --color-accent: #2563eb;
  --color-accent-wash: #eff6ff;
  --color-danger: #b42318;
  --color-danger-strong: #8c1d13;
  --color-danger-wash: #fee4e2;
  --color-success: #047857;
  --color-success-wash: #dcfce7;
  --color-warn: #6e5200;
  --color-warn-wash: #faf0cf;
  --color-focus: #bfdbfe;
  --radius-lg: .85rem;
}
"""

_BASE = """
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; color: var(--color-text);
  font-family: Inter, "Segoe UI", Roboto, sans-serif;
  background: linear-gradient(180deg, #f6f7fb 0%, #eef2ff 45%, #f8fafc 100%); }
a { color: var(--color-accent); }
input:focus, select:focus, a:focus, button:focus, [tabindex="0"]:focus {
  outline: 3px solid var(--color-focus); outline-offset: 2px; }
"""

# Ordered to mirror the pre-consolidation concatenation on app-shell pages
# (app shell, event shell, venue shell, approval, event table) so conflicting
# same-specificity rules keep resolving exactly as they did per page.
_COMPONENTS = """
/* --- application shell --- */
.events-app { max-width: 1100px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }
.events-header { margin-bottom: 1rem; }
.page-kicker { display: inline-block; margin: 0 0 .3rem; color: var(--color-accent);
  font-size: .85rem; font-weight: 650; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: .2rem 0 .5rem; font-size: clamp(1.5rem, 2.6vw, 2.15rem); line-height: 1.2; }
.toolbar { display: flex; justify-content: space-between; align-items: center;
  gap: .75rem; flex-wrap: wrap; }
.toolbar-actions { display: flex; align-items: center; gap: .55rem; }
.settings-link { display: inline-flex; align-items: center; min-height: 2.35rem;
  padding: .45rem .75rem; border: 1px solid var(--color-line); border-radius: var(--radius-lg);
  color: var(--color-text); background: var(--color-surface); text-decoration: none; font-weight: 600; }
.settings-link:hover { border-color: #93c5fd; background: #eff6ff; }
.sync-button { border: 1px solid transparent; padding: .5rem 1rem;
  border-radius: var(--radius-lg); background: linear-gradient(180deg, #2563eb 0%, #1d4ed8 100%);
  color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
.sync-button:disabled { filter: grayscale(.25); cursor: not-allowed; }
.sync-error { min-height: 1.1rem; margin: .5rem 0; color: var(--color-danger); font-weight: 500; }
.sync-progress { display: grid; gap: .45rem; margin: .75rem 0; color: var(--color-text-muted); font-size: .92rem; }
.sync-progress p { margin: 0; }
.sync-progress progress { width: min(34rem, 100%); height: .65rem; accent-color: var(--color-accent); }
.tabs { display: flex; gap: .35rem; align-items: center; margin: 1.25rem 0;
  border-bottom: 1px solid var(--color-line); overflow-x: auto; }
.tab { color: var(--color-text-muted); padding: .65rem .85rem; text-decoration: none;
  border-bottom: 3px solid transparent; font-weight: 600; white-space: nowrap; }
.tab:hover, .tab.active { color: var(--color-accent); border-bottom-color: var(--color-accent); }
#tab-content { view-transition-name: tab-content; }

/* --- events view --- */
.recent-settings { display: flex; align-items: flex-end; justify-content: flex-end; gap: .5rem;
  margin: 0; color: var(--color-text-muted); font-size: .9rem; }
.recent-settings label { white-space: nowrap; }
.recent-settings select { border: 1px solid var(--color-line); border-radius: .45rem; padding: .35rem .5rem;
  background: var(--color-surface); color: var(--color-text); }
.filter-bar { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 1rem;
  margin: 1.25rem 0 .8rem; }
.filter-label { display: grid; gap: .35rem; color: #334155; font-size: .85rem; font-weight: 700;
  width: min(28rem, 100%); }
.filter-input { width: 100%; padding: .72rem .8rem; border: 1px solid var(--color-edge);
  border-radius: .65rem; color: var(--color-text); background: var(--color-surface); font: inherit; }
.filter-wrapper { position: relative; }
.filter-clear { position: absolute; right: .5rem; top: 50%; transform: translateY(-50%);
  display: flex; align-items: center; justify-content: center; width: 1.4rem; height: 1.4rem;
  border: 0; border-radius: 50%; background: #e2e8f0; color: #475569; cursor: pointer; padding: 0; }
.result-count, .meta { color: var(--color-text-muted); font-size: .9rem; margin: 0; }
#events-panel { margin-top: .5rem; background: var(--color-surface); border: 1px solid var(--color-line);
  border-radius: var(--radius-lg); padding: .9rem; box-shadow: 0 16px 40px rgba(15, 23, 42, .07); }
.table-scroll { height: var(--table-view-height); overflow: auto; }
.table-footer { display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  min-height: 2.5rem; margin-top: .55rem; }
.pagination { display: flex; align-items: center; gap: .75rem; margin: 0; }
.pagination-link { border-radius: 999px; border: 1px solid var(--color-line); color: var(--color-text);
  text-decoration: none; padding: .35rem .85rem; font-size: .9rem; background: var(--color-surface-sunken); }
.pagination-link.disabled { color: #94a3b8; pointer-events: none; background: #f8fafc; }

/* --- venues view --- */
#venue-panel { margin-top: .5rem; background: var(--color-surface); border: 1px solid var(--color-line);
  border-radius: var(--radius-lg); padding: .9rem; box-shadow: 0 16px 40px rgba(15, 23, 42, .07); }
.venue-row { cursor: pointer; }
.venue-row:hover td, .venue-row:focus td { background: #f8fafc; }
.empty-state { color: var(--color-text-muted); margin: .35rem 0; }

/* --- approval workflow (queue tab + editor pages) --- */
.approval-page main { max-width: 1100px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }
.kicker { color: var(--color-accent); text-transform: uppercase; letter-spacing: .08em;
  font-size: .82rem; font-weight: 700; }
.muted { color: var(--color-text-muted); }
.card { background: var(--color-surface); border: 1px solid var(--color-line); border-radius: .85rem;
  padding: 1rem; box-shadow: 0 16px 40px rgba(15, 23, 42, .06); }
.card table { width: 100%; border-collapse: collapse; }
.card th, .card td { text-align: left; padding: .7rem .55rem; border-bottom: 1px solid var(--color-line); }
.card th { color: #334155; font-size: .86rem; }
.status { display: inline-block; padding: .18rem .55rem; border-radius: 999px;
  background: #e0e7ff; color: #3730a3; font-size: .78rem; }
.suggestions { display: grid; gap: .7rem; margin: 1rem 0; }
.suggestion { display: block; border: 1px solid var(--color-line); border-radius: .7rem;
  padding: .85rem; text-decoration: none; color: var(--color-text); background: var(--color-surface); }
.suggestion.selected { border-color: var(--color-accent); box-shadow: 0 0 0 2px var(--color-focus); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .85rem; }
.field-wide { grid-column: 1 / -1; }
.app-page label, .approval-page label { display: block; color: #334155; font-size: .85rem;
  font-weight: 650; }
.app-page input, .approval-page input { width: 100%; margin-top: .3rem; padding: .65rem .7rem;
  border: 1px solid var(--color-line); border-radius: .55rem; color: var(--color-text);
  background: var(--color-surface); }
.actions { display: flex; flex-wrap: wrap; gap: .65rem; margin-top: 1rem; }
.app-page button, .app-page .button,
.approval-page button, .approval-page .button { border: 0; border-radius: .6rem;
  padding: .65rem .95rem; font-weight: 700; cursor: pointer; background: var(--color-accent);
  color: #fff; }
.app-page .button, .approval-page .button { display: inline-block; text-decoration: none; }
.app-page button.secondary, .app-page .button.secondary,
.approval-page button.secondary, .approval-page .button.secondary { background: #e2e8f0;
  color: var(--color-text); }
.error { color: var(--color-danger); background: var(--color-danger-wash);
  border-radius: .55rem; padding: .7rem; }
.notice { padding: .8rem 1rem; border-radius: .7rem; font-weight: 650; }
.notice.success { color: var(--color-success); background: var(--color-success-wash); }
.notice.error { color: var(--color-danger); background: var(--color-danger-wash); }
.events-section { margin-top: 1.5rem; }
.events-card { max-height: 23rem; overflow: auto; padding: 0 1rem 1rem; }
.events-card .event-table { display: table; }
.events-card .event-table thead { display: table-header-group; position: sticky; top: 0;
  z-index: 1; background: var(--color-surface); }
.events-card .event-table tbody { display: table-row-group; }
.events-card .event-table tr { display: table-row; }
.events-card .event-table th,
.events-card .event-table td { display: table-cell; }
.events-card .event-table tbody tr td::before { content: none; display: none; }

/* --- event table --- */
.event-table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
.event-table thead th { font-weight: 650; color: #334155; text-align: left;
  border-bottom: 1px solid var(--color-line); padding: 0.65rem 0.5rem; }
.event-table th,
.event-table td { text-align: left; vertical-align: top; padding: 0.6rem 0.5rem;
  border-bottom: 1px solid var(--color-line); }
.event-table tbody tr:hover td { background: #f8fafc; }
.event-table tbody tr:last-child td { border-bottom: none; }
.event-table .date-link { white-space: nowrap; font-variant-numeric: tabular-nums; }

@media (max-width: 720px) {
  .events-app { padding: 1rem .75rem 2rem; }
  .toolbar { align-items: stretch; }
  .toolbar-actions { flex-wrap: wrap; }
  .filter-bar { grid-template-columns: minmax(0, 1fr); gap: .55rem; }
  .filter-label { width: auto; min-width: 0; }
  .recent-settings { display: grid; justify-items: end; gap: .35rem; }
  .table-footer { align-items: flex-start; flex-direction: column; }
  .pagination { flex-wrap: wrap; }
  .approval-page main { padding: 1rem .75rem 2rem; }
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
    border-radius: 0.7rem; overflow: hidden; }
  .event-table tbody tr td { padding: 0.45rem 0.65rem; border-bottom: 1px solid var(--color-line); }
  .event-table tbody tr td::before { content: attr(data-label); display: block;
    color: var(--color-text-muted); font-size: 0.78rem; margin-bottom: 0.2rem;
    letter-spacing: 0.04em; text-transform: uppercase; }
  .event-table tbody tr td:last-child { border-bottom: none; }
}
"""

_VIEWS = """
/* --- login --- */
.login-page { background: var(--color-bg); }
.login-page main { width: min(26rem, calc(100% - 2rem)); margin: 14vh auto 0; }
.login-page .card { padding: 1.5rem; border: 1px solid var(--color-line); border-radius: 1rem;
  background: var(--color-surface); box-shadow: 0 18px 50px rgba(15, 23, 42, .06); }
.login-page h1 { margin: 0 0 .3rem; font-size: 1.4rem; }
.login-page p { color: var(--color-text-muted); }
.login-page label { display: block; margin-top: 1rem; font-weight: 700; }
.login-page input { display: block; width: 100%; margin: .4rem 0 .3rem; padding: .72rem .8rem;
  border: 1px solid var(--color-edge); border-radius: .65rem; font: inherit; }
.login-page button { margin-top: .9rem; padding: .72rem 1rem; border: 0; border-radius: .65rem;
  background: var(--color-accent); color: #fff; font: inherit; font-weight: 750; cursor: pointer; }
.login-page .back-link { display: inline-block; margin-top: 1rem; color: var(--color-accent); }

/* --- settings --- */
.settings-page { background: var(--color-bg); }
.settings-page main { width: min(760px, calc(100% - 2rem)); margin: 0 auto; padding: 2rem 0 4rem; }
.settings-header { display: flex; justify-content: space-between; align-items: flex-start;
  gap: 1rem; margin-bottom: 1.5rem; }
.settings-page .kicker, .section-label { margin: 0 0 .35rem; color: var(--color-text-muted);
  font-size: .76rem; font-weight: 750; letter-spacing: .09em; text-transform: uppercase; }
.settings-page h1 { margin: 0; font-size: clamp(2rem, 6vw, 3.2rem); letter-spacing: -.045em; }
.settings-page h2 { margin: .1rem 0 .55rem; font-size: 1.25rem; }
.settings-page .back-link { white-space: nowrap; margin-top: .4rem; }
.settings-stack { display: grid; gap: 1rem; }
.settings-card { padding: 1.25rem; border: 1px solid var(--color-line); border-radius: 1rem;
  background: var(--color-surface); box-shadow: 0 18px 50px rgba(15, 23, 42, .06); }
.settings-page label { display: block; margin-top: 1rem; font-weight: 700; }
.settings-page input { display: block; width: min(14rem, 100%); margin: .4rem 0 .3rem;
  padding: .72rem .8rem; border: 1px solid var(--color-edge); border-radius: .65rem; font: inherit; }
.hint, .settings-card p { color: var(--color-text-muted); line-height: 1.55; }
.settings-page button { margin-top: .8rem; padding: .72rem 1rem; border: 0; border-radius: .65rem;
  background: var(--color-accent); color: #fff; font: inherit; font-weight: 750; cursor: pointer; }
.danger-zone { border-color: #f4b8b3; background: #fff1f0; }
.danger-zone .section-label, .danger-zone h2 { color: var(--color-danger); }
.settings-page .danger-button { background: var(--color-danger); }
@media (max-width: 560px) {
  .settings-header { display: block; }
  .settings-page .back-link { display: inline-block; margin-top: 1rem; }
}

/* --- venue & artist detail --- */
.detail-page { background: var(--color-bg); }
.detail-page main { max-width: 760px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }
.detail-page .card { padding: 1.25rem; box-shadow: none; }
.detail-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.detail-header h1 { margin: .2rem 0 0; }
.detail-actions { display: flex; flex-wrap: wrap; gap: .65rem; margin-top: 1.25rem; }
.action-button { display: inline-flex; align-items: center; justify-content: center;
  min-height: 2.4rem; padding: .6rem .9rem; border: 1px solid var(--color-accent);
  border-radius: .6rem; background: var(--color-accent); color: #fff;
  font: inherit; font-weight: 700; text-decoration: none; cursor: pointer; }
.action-button.secondary { border-color: #cbd5e1; background: #e2e8f0; color: var(--color-text); }
.artist-links { display: flex; flex-wrap: wrap; gap: .35rem .75rem; }
.venue-map { margin-top: 1.5rem; }
.venue-map h2 { margin-bottom: .65rem; }
.venue-map iframe { display: block; width: 100%; min-height: 22rem;
  border: 1px solid var(--color-line); border-radius: .85rem; }
.venue-map p { margin: .6rem 0 0; }
.detail-page dt { color: var(--color-text-muted); margin-top: 1rem; font-size: .85rem;
  text-transform: uppercase; }
.detail-page dd { margin: .25rem 0 0; }
.detail-page .events-card { background: var(--color-surface); border: 1px solid var(--color-line);
  border-radius: .85rem; padding: .9rem; box-shadow: 0 16px 40px rgba(15, 23, 42, .07);
  max-height: none; overflow: visible; }
@media (max-width: 560px) {
  .detail-header { display: block; }
  .detail-header .action-button { margin-top: .9rem; }
}

/* --- events-on-date --- */
.date-page main { max-width: 1100px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }
.date-page .page-kicker { margin: 0 0 .3rem; font-size: .82rem; font-weight: 700; }
.date-page h1 { margin: 0; font-size: clamp(1.8rem, 4vw, 2.6rem); letter-spacing: -.04em; }
.date-page .back-link { display: inline-block; margin-bottom: 1.25rem; }
.date-page .meta { font-size: .95rem; margin: .55rem 0 1.1rem; }
.date-page .card { padding: .9rem; box-shadow: 0 16px 40px rgba(15, 23, 42, .07); }
@media (max-width: 720px) {
  .date-page main { padding: 1rem .75rem 2rem; }
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
