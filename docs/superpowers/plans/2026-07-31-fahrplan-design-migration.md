# Fahrplan Design-Language Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the Litestar web UI in `src/berlin_events_explorer/webapp.py` to the "Fahrplan" design language specified in `docs/design_language.md`, executing all five phases of §12.

**Architecture:** All CSS consolidates into a new `theme.py` module served once at `/static/app.css` (cascade layers: tokens → base → components → views). Renderers in `webapp.py` swap inline `<style>` blocks for one `<link>`. Phase 1 is mechanical (no visual change), Phase 2 swaps the look, Phase 3 folds outlier pages onto the shared shell, Phase 4 ships dark theme + a11y fixes, Phase 5 replaces machine dates with a `<time>`-based date-stamp component.

**Tech Stack:** Python 3.14 / Litestar 2.x, f-string HTML, Datastar (vendored), no build step, no CSS framework. Fonts self-hosted woff2. Tests: pytest via `just tests`; type check `just typecheck`; lint `just lint`.

## Global Constraints

Copied from `docs/design_language.md` (binding):

- **The yellow rule** (§3.4): on light theme `--color-accent` (`#F0D722`, 1.45:1 on white) never appears alone — always ink *on* yellow, yellow underline *beneath* ink, or yellow block *with* ink border. Meaning never in color only.
- **No new colors** (§3.4): a hex literal outside the token block is a defect (enforced by test from Phase 2 on).
- **Links are ink** (§3.4): `--color-text` with `text-decoration-color: var(--color-accent)`, `text-underline-offset: 0.15em`; hover fills `--color-accent-wash`.
- **Weights** (§4.2): 400/600/700 only; retire fractional 650/750.
- **Timetable numerics** (§4.3): `font-variant-numeric: tabular-nums` on table cells, `time`, pagination, result counts, stamps.
- **Spacing scale** (§5): 4px base, `--space-1`…`--space-7`; radii `--radius-sm` 4px / `--radius-md` 8px / `--radius-lg` 12px / `--radius-full`; **no box shadows** (flat, border-based elevation).
- **Motion** (§6): `--motion-fast: 120ms`, `--motion-base: 200ms`, ease-out; reduced-motion guard is the only permitted `!important`.
- **A11y floor** (§8): WCAG 2.2 AA; `:focus-visible` 2px `var(--color-focus)` offset 2px; skip link to `#main` on every page; ≥24px targets; tables stay tables.
- **Dates** (§9.2): humans never see `isoformat()`; format `Thu 12 Mar 2026` (short `Thu 12 Mar`) inside `<time datetime="...">`; ISO stays in URLs and `<title>`s that already use it.
- **Voice** (§10): verbs name outcomes, sentence case (uppercase via CSS only), errors say what and how, empty states name the situation + action.
- **CLAUDE.md**: ruff format (88 cols), Google docstrings, `ty` for types.
- Each phase ends with `just tests`, a keyboard-only walkthrough, and screenshot review at 360/768/1280px (both themes from Phase 4).

## Resolved Decisions (deviations & defaults)

1. **Vendored assets stay in `src/berlin_events_explorer/static/`**, not the doc's `resources/static/` — commit 0558d03 already established `static/` + the `/static` router + CSP before the doc merged; moving would be churn with zero benefit. Fonts go to `static/fonts/`.
2. **Datastar vendoring (§12 Phase 1) is already done** (`static/datastar.js`, pinned v1.0.0-RC.7). No action.
3. **Phase 1 interim token values** come from the app-shell vocabulary (`#0f172a` text, `#64748b` muted, `#d5dbe8` line, `#fff` surface, `#f3f5f9` sunken, `#2563eb` accent, `#b42318` danger) — the most widely used of the three drifted sets. Login/settings shift a few hex steps; that drift is exactly what §1's audit called a defect.
4. **`/static/app.css` is an explicit route handler** registered alongside the static-files router (exact segment beats the catch-all in Litestar's trie). Far-future `Cache-Control: public, max-age=31536000, immutable`; pages reference `/static/app.css?v=<sha256[:12] of css>`.
5. **Stray hex literals inside component rules survive Phase 1 untouched** (consolidation is mechanical); Phase 2 tokenizes them and turns on the no-hex test.
6. **Settings/detail/approval pages get the shell without the sync button** — sync's SSE stream patches `#tab-content` per `$appView`, which would clobber non-tab content. `_render_app_page` gains `show_sync: bool = True` / `show_filter_state` handled per page.
7. **Active tab on shell for outlier pages:** venue detail → `venues`; artist detail, date page, settings, approval forms → no active tab (nav renders, nothing marked current). `_render_app_nav` stops coercing unknown tabs to `upcoming` for the *marker* (signals still default `eventTab` to `upcoming`).
8. **`lang="de"` wrapping (§12 Phase 5) is a documented no-op**: the UI renders no provider prose (descriptions/blurbs); names/titles are not reliably language-tagged. Noted in the code where descriptions would render.
9. **Fonts**: Inter variable woff2 from rsms/inter (OFL) — full file (covers latin-ext), no subsetting step. D-DIN Condensed Bold (OFL) from Font Squirrel's D-DIN family, converted OTF→woff2 with fonttools+brotli. **Fallback if D-DIN is unobtainable:** Archivo Narrow Bold woff2 from google/fonts (OFL) — already second in the §4.1 stack; keep the file name role-based (`display-bold.woff2`? No — keep the doc's names; if fallback used, name it `archivo-narrow-bold.woff2` and adjust `@font-face` family accordingly). OFL license files are committed next to the fonts.
10. **Commits use explicit paths** (`git commit -- <files>`) — the user has an unrelated staged `.gitignore` change that must not ride along.
11. **CSP keeps `style-src 'unsafe-inline'`** — `style="--table-view-height:…"` attributes and Datastar remain; only `<style>` *elements* disappear.

## Current-State Inventory (what moves where)

| Today (webapp.py) | Content | Destination |
|---|---|---|
| `_render_login_page` lines ~200-220 | `--ink/--paper` token set + login card CSS | `views` layer (`.login-page`) |
| `_render_settings_page` lines ~1493-1526 | `--ink/--paper` set + settings CSS | Phase 1: `views`; Phase 3: deleted (joins shell/components) |
| `_approval_styles()` lines 1577-1634 | `--text/--surface` set + queue/form/suggestion CSS | `components` layer |
| `_render_artist_detail_page` inline lines ~1868-1881 | raw-hex detail CSS | `views` layer (`.detail-page`) |
| `_render_date_events_page` inline lines ~1917-1935 | `--text/--surface` set | `views` layer |
| `_render_venue_detail_page` inline lines ~2007-2032 | raw-hex detail CSS + map | `views` layer |
| `_event_table_styles()` lines 2334-2413 | responsive event table | `components` layer (once — today it's concatenated into 5 places) |
| `_app_shell_styles()` lines 2725-2766 | `--text/--surface-soft` set + shell/tabs/toolbar | `components` layer |
| `_event_shell_styles()` lines 3049-3085 | filter bar, panel, pagination | `components` layer |
| `_venue_shell_styles()` lines 3273-3303 | near-duplicate of event shell | merged into the same `components` rules |

Old→new token names (§12 Phase 1): `--ink`/`--text` → `--color-text` · `--muted` → `--color-text-muted` · `--paper` → `--color-bg` · `--card`/`--surface` → `--color-surface` · `--surface-soft`/`--soft` → `--color-surface-sunken` · `--line` → `--color-line` · `--blue`/`--primary` → `--color-accent` (interim blue) · `--danger` (3 values) → `--color-danger` · `--danger-soft` → `--color-danger-wash`.

---

### Task 1 (Phase 1): `theme.py` with consolidated stylesheet, served at `/static/app.css`

**Files:**
- Create: `src/berlin_events_explorer/theme.py`
- Modify: `src/berlin_events_explorer/webapp.py` (add route + import)
- Test: `tests/test_theme.py`

**Interfaces:**
- Produces: `theme.stylesheet() -> str` (full CSS, `@layer tokens, base, components, views`), `theme.STYLESHEET_HREF: str` (`/static/app.css?v=<hash>`), `theme.stylesheet_link() -> str` (returns `<link rel="stylesheet" href="...">`), route `GET /static/app.css` (200, `text/css`, immutable caching).

- [ ] **Step 1: Write failing tests** in `tests/test_theme.py`:

```python
"""Tests for the consolidated Fahrplan stylesheet and its delivery."""

from berlin_events_explorer import theme
from berlin_events_explorer.webapp import create_app
from litestar.testing import TestClient


def test_stylesheet_declares_cascade_layers() -> None:
    css = theme.stylesheet()
    assert "@layer tokens, base, components, views;" in css
    assert "--color-text" in css
    assert "--color-surface" in css


def test_stylesheet_href_carries_content_hash() -> None:
    assert theme.STYLESHEET_HREF.startswith("/static/app.css?v=")
    assert len(theme.STYLESHEET_HREF.split("v=")[1]) == 12


def test_app_css_is_served_with_far_future_caching(tmp_path) -> None:
    app = create_app(tmp_path / "events.sqlite", sync_interval=None)
    with TestClient(app=app) as client:
        response = client.get("/static/app.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "immutable" in response.headers["cache-control"]
    assert "--color-text" in response.text
```

(Match `create_app`'s real signature from `tests/test_webapp.py` fixtures before writing — reuse their construction helper if one exists.)

- [ ] **Step 2: Run tests, verify they fail** (`just test test_theme` → import error).
- [ ] **Step 3: Create `theme.py`.** Skeleton:

```python
"""Single consolidated stylesheet for the web UI (design_language.md §11).

All CSS lives here in cascade layers (tokens, base, components, views) and is
served once at /static/app.css. A hex literal outside _TOKENS is a defect
(design_language.md §3.4).
"""

from hashlib import sha256

_TOKENS = """..."""      # :root custom properties (§3 names, interim values)
_BASE = """..."""        # element defaults, box-sizing, body, focus
_COMPONENTS = """..."""  # shell, tabs, toolbar, event table, filter bar,
                         # pagination, buttons, notices, suggestions, forms
_VIEWS = """..."""       # login card, settings column, detail pages, date page


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
    """Return the <link> tag every page uses to load the stylesheet."""
    return f'<link rel="stylesheet" href="{STYLESHEET_HREF}" />'
```

Interim `_TOKENS` (Phase 1 values — current app-shell colors under §3 *names*):

```css
:root {
  --color-bg: #f6f7fb;
  --color-surface: #ffffff;
  --color-surface-sunken: #f3f5f9;
  --color-text: #0f172a;
  --color-text-muted: #64748b;
  --color-line: #d5dbe8;
  --color-edge: #b9c2d0;
  --color-accent: #2563eb;          /* interim: current primary blue */
  --color-accent-wash: #eff6ff;
  --color-danger: #b42318;
  --color-danger-strong: #8c1d13;
  --color-danger-wash: #fee4e2;
  --color-success: #047857;
  --color-success-wash: #dcfce7;
  --color-warn: #6e5200;
  --color-warn-wash: #faf0cf;
  --color-focus: #bfdbfe;           /* interim: current ring color */
  --radius-lg: .85rem;              /* interim: current radius */
}
```

Port CSS bodies mechanically per the inventory table: `_COMPONENTS` = current `_app_shell_styles` + `_event_shell_styles` + `_venue_shell_styles` (dedup: the venue variant only adds `.venue-row` rules and `#venue-panel`; identical filter/pagination rules appear once) + `_approval_styles` (minus its `:root` and `body` — body rules go to `_BASE`; scope its bare `table,th,td,label,input,button` element selectors under a `.approval-*`/existing class so they can't leak once every page shares one sheet — e.g. `.card table`, `.form-grid label`, `.suggestion`) + `_event_table_styles` once. `_VIEWS` = login, settings, artist/venue detail, date page CSS with their `:root` blocks dropped and old var names rewritten to §3 names. Rewrite every `var(--text)`/`var(--ink)`… reference per the mapping table. Leave stray hex literals as-is (Phase 2 job).

- [ ] **Step 4: Add the route in `create_app`** (webapp.py), registered in `route_handlers` right before the static-files router:

```python
from berlin_events_explorer import theme

@get("/static/app.css", sync_to_thread=False)
def app_stylesheet() -> Response:
    """Serve the consolidated stylesheet with far-future caching."""
    return Response(
        content=theme.stylesheet(),
        media_type="text/css",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
```

- [ ] **Step 5: Run `just test test_theme`** → PASS. Run `just tests` → all pass (nothing else changed yet).
- [ ] **Step 6: Commit** `feat: add consolidated stylesheet module served at /static/app.css` (paths: `src/berlin_events_explorer/theme.py src/berlin_events_explorer/webapp.py tests/test_theme.py`).

### Task 2 (Phase 1): Cut every page over to the stylesheet; delete the five style helpers

**Files:**
- Modify: `src/berlin_events_explorer/webapp.py` (all 8 page renderers; delete `_approval_styles`, `_app_shell_styles`, `_event_shell_styles`, `_venue_shell_styles`, `_event_table_styles`)
- Test: `tests/test_theme.py` (add a no-`<style>`-blocks test)

**Interfaces:**
- Consumes: `theme.stylesheet_link()` from Task 1.

- [ ] **Step 1: Add failing test:**

```python
import re

import pytest


@pytest.mark.parametrize(
    "path",
    ["/", "/?tab=venues", "/login", "/dates/2026-08-01"],
)
def test_pages_link_stylesheet_and_carry_no_style_blocks(tmp_path, path) -> None:
    app = create_app(tmp_path / "events.sqlite", sync_interval=None)
    with TestClient(app=app) as client:
        response = client.get(path, follow_redirects=True)
    assert response.status_code == 200
    assert "/static/app.css?v=" in response.text
    assert "<style" not in response.text
```

(Editor-only pages — settings, approvals — are covered indirectly: they share the same renderers being edited; add them to the parametrize list if the existing test suite has a logged-in client fixture to borrow.)

- [ ] **Step 2: Run it, verify it fails.**
- [ ] **Step 3: Replace `<style>…</style>` with `{theme.stylesheet_link()}`** in the `<head>` of: `_render_login_page`, `_render_settings_page`, `_render_venue_approval_form`, `_render_artist_approval_form`, `_render_artist_detail_page`, `_render_date_events_page`, `_render_venue_detail_page`, `_render_app_page`. Add class hooks where views-layer CSS needs a scope (e.g. `<body class="login-page">`, `<body class="settings-page">`, `<body class="detail-page">` matching the `_VIEWS` selectors written in Task 1).
- [ ] **Step 4: Delete the five style helper functions** and their call sites/f-string interpolations.
- [ ] **Step 5: `just tests` + `just lint` + `just typecheck`** → all pass.
- [ ] **Step 6: Visual check (no-change gate):** run the app, screenshot events/venues/login/settings/approvals/detail pages at 1280px, compare against pre-change screenshots — layout identical, colors within the documented token-unification drift.
- [ ] **Step 7: Commit** `refactor: serve all page styles from the consolidated stylesheet` (explicit paths).

### Task 3 (Phase 1): Vendor the two typefaces

**Files:**
- Create: `src/berlin_events_explorer/static/fonts/inter-var.woff2`, `src/berlin_events_explorer/static/fonts/d-din-condensed-bold.woff2`, `src/berlin_events_explorer/static/fonts/OFL-inter.txt`, `src/berlin_events_explorer/static/fonts/OFL-d-din.txt`
- Test: `tests/test_theme.py` (fonts served)

- [ ] **Step 1: Failing test:**

```python
@pytest.mark.parametrize(
    "font_path",
    ["/static/fonts/inter-var.woff2", "/static/fonts/d-din-condensed-bold.woff2"],
)
def test_vendored_fonts_are_served(tmp_path, font_path) -> None:
    app = create_app(tmp_path / "events.sqlite", sync_interval=None)
    with TestClient(app=app) as client:
        response = client.get(font_path)
    assert response.status_code == 200
    assert response.content[:4] == b"wOF2"
```

- [ ] **Step 2: Download + convert** (scratchpad, then copy):
  - Inter: `curl -L https://rsms.me/inter/font-files/InterVariable.woff2` (fallback: latest rsms/inter GitHub release zip → `InterVariable.woff2`). License: `https://raw.githubusercontent.com/rsms/inter/master/LICENSE.txt`.
  - D-DIN: Font Squirrel family zip `https://www.fontsquirrel.com/fonts/download/d-din` → `D-DINCondensed-Bold.otf` (+ bundled OFL txt); convert: `uv run --with fonttools --with brotli python -c "from fontTools.ttLib import TTFont; f=TTFont('D-DINCondensed-Bold.otf'); f.flavor='woff2'; f.save('d-din-condensed-bold.woff2')"`. Fallback per Resolved Decision 9.
- [ ] **Step 3: Verify magic bytes + test passes**; `just tests`.
- [ ] **Step 4: Commit** `feat: vendor Inter and D-DIN Condensed webfonts` (fonts + licenses + test).

### Task 4 (Phase 2): Re-theme — Fahrplan tokens, typography, space, motion

**Files:**
- Modify: `src/berlin_events_explorer/theme.py` (all four layers), `src/berlin_events_explorer/webapp.py` (font preloads in `<head>` of every renderer)
- Test: `tests/test_theme.py` (contrast verification + no-hex-outside-tokens)

**Interfaces:**
- Produces: final `_TOKENS` (light values, §3.1 verbatim), `theme.CONTRAST_PAIRS: list[tuple[str, str, float]]` (token-name pairs + required ratio, for the test), `theme._TOKEN_VALUES: dict[str, str]` (name → hex, single source both CSS and test read).

- [ ] **Step 1: Failing tests:**

```python
def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_token_pairs_meet_wcag_contrast() -> None:
    for name_a, name_b, minimum in theme.CONTRAST_PAIRS:
        ratio = _contrast(theme._TOKEN_VALUES[name_a], theme._TOKEN_VALUES[name_b])
        assert ratio >= minimum, f"{name_a} on {name_b}: {ratio:.2f} < {minimum}"


def test_no_hex_literals_outside_token_layer() -> None:
    css = theme.stylesheet()
    body = css.split("@layer base", 1)[1]  # everything after the tokens layer
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", body)
```

`CONTRAST_PAIRS` encodes §3.3's light-theme table: text/bg 4.5, text-muted/surface 4.5, text/accent 4.5, danger/surface 4.5, danger-strong/danger-wash 4.5, success/success-wash 4.5, warn/warn-wash 4.5, edge/surface 3.0.

- [ ] **Step 2: Build `_TOKEN_VALUES`** from §3.1 verbatim (`#F4F4F1` bg … `#1A1C1E` focus) and generate the `:root` block from it. Add non-color tokens: type scale §4.2 (`--text-xs` 0.75rem … `--text-display` clamp), `--font-display`/`--font-body`/`--font-mono` stacks §4.1, spacing §5, radii §5, `--motion-fast`/`--motion-base` §6, `--shadow-overlay` (defined, unused).
- [ ] **Step 3: `@font-face` + preload.** In `_BASE`: two `@font-face` rules (`Inter` variable `font-weight: 100 900`, `D-DIN Condensed` bold, both `font-display: swap`, `src: url("/static/fonts/…woff2") format("woff2")`). In every renderer's `<head>` (via a new `theme.font_preloads()` helper returning the two `<link rel="preload" as="font" type="font/woff2" crossorigin>` tags) — placed with `stylesheet_link()`.
- [ ] **Step 4: Rewrite `_BASE` + `_COMPONENTS` + `_VIEWS`** to the Fahrplan spec — this is the visible re-skin:
  - base: `body` bg/color/fonts; links ink + accent underline (§3.4 rule three, exact declarations from Global Constraints); `:focus-visible` 2px `var(--color-focus)` offset 2px (drop all old `:focus` outlines); tabular-nums rule (§4.3 selector list verbatim); reduced-motion guard (§6 block verbatim); line-heights 1.55 prose / 1.35 cells+controls; letterspacing rules.
  - components: tabs — display face, active = ink text + 3px solid accent underline (keep `aria-current`, `overflow-x:auto`); primary button (accent fill, ink label, 1px ink border), secondary (sunken fill, ink label, edge border), danger (danger fill, white label), quiet; all buttons ≥24px targets, weight 700; event table — sticky header on sunken, 1px line row rules, hover `--color-accent-wash`, keep the 720px card transform and `--table-view-height` mechanism; panels flat (`1px solid var(--color-line)`, **delete every box-shadow**); pagination pills `--radius-full` + edge borders; notices = wash bg + strong text + 4px solid left border (§7.6); suggestion cards flat, selected = 2px ink border (stamp text added in Phase 3); inputs = surface fill, 1px edge border, radius-md; radius audit — replace the eight ad-hoc radii with the three tokens; kickers `--text-xs` uppercase +0.08em ink-muted (no more blue).
  - Replace every stray hex from Phase 1 with the matching token; the Step-1 test enforces completeness.
- [ ] **Step 5: `just tests`** (contrast + no-hex now pass) + `just lint` + `just typecheck`.
- [ ] **Step 6: Screenshot review** at 360/768/1280 (light): events, venues, login, date page — signal yellow appears only as active-tab marker, primary button fill, row hover, link underlines.
- [ ] **Step 7: Commit** `feat: apply Fahrplan design language tokens and typography`.

### Task 5 (Phase 3): Settings joins the shared shell

**Files:**
- Modify: `src/berlin_events_explorer/webapp.py` (`_render_settings_page`, `_render_app_page`, `_render_app_nav`, settings route), `src/berlin_events_explorer/theme.py` (delete settings `views` CSS; add small `.settings-stack` component if not already covered by cards/forms)

**Interfaces:**
- Produces: `_render_app_page(..., show_sync: bool = True, active_tab: str)` where `active_tab` outside the four known tabs renders the nav with no current marker; settings content built from catalog components (`card`-equivalent flat sections, form rules, danger notice) inside the 1100px shell column.

- [ ] **Step 1:** Extend `_render_app_page` with `show_sync` (omit sync button + sync-error/progress regions when False) and make `_render_app_nav` mark no tab active for unknown `active_tab` values (signals: `appView` may stay the literal value; `eventTab` still coerces to `upcoming`).
- [ ] **Step 2:** Rebuild `_render_settings_page` as shell content: kicker "Application controls", H1 "Settings", notices per §7.6, the existing form fields (labels + hints via `aria-describedby`), primary button "Save settings", danger zone with danger button (development only). Remove its standalone skeleton; route passes `csrf_token` through as today.
- [ ] **Step 3:** `just tests` — settings tests in `test_webapp.py` keep passing (they assert content, not skeleton); fix any that asserted the old 760px wrapper.
- [ ] **Step 4:** Keyboard walkthrough + screenshots of `/settings`.
- [ ] **Step 5: Commit** `refactor: move settings onto the shared application shell`.

### Task 6 (Phase 3): Approval forms, detail pages, and date page join the shell; status stamps

**Files:**
- Modify: `src/berlin_events_explorer/webapp.py` (`_render_venue_approval_form`, `_render_artist_approval_form`, `_render_artist_detail_page`, `_render_venue_detail_page`, `_render_date_events_page`, `_approval_nav` (delete — shell nav replaces it), `_render_approval_content` (stamp markup)), `src/berlin_events_explorer/theme.py` (delete detail/date `views` CSS; add `.stamp` component per §7.4)

**Interfaces:**
- Produces: `.stamp` CSS component (uppercase `--text-xs`, +0.08em, 1.5px solid border, `--radius-sm`, transparent fill; modifiers `.stamp--success`, `.stamp--warn`, `.stamp--danger`, `.stamp--neutral`); helper `_render_stamp(label: str, tone: str) -> str` returning `<span class="stamp stamp--{tone}">{escape(label)}</span>`.

- [ ] **Step 1:** Wrap each page's content in `_render_app_page(show_sync=False, active_tab=...)` per Resolved Decision 7; drop their standalone `<head>`/`<body>` skeletons and back-link-only navigation (keep contextual back links inside content where they aid flow, e.g. "← Back to approval queue").
- [ ] **Step 2:** Replace the indigo `.status` pill in `_render_approval_content` with stamps: Type column → `_render_stamp("Venue"|"Artist", "neutral")`; Status column → tone by state (`pending`/`auto_matched` → `warn`, `verified` → `success`, `rejected`/`failed` → `danger`). Suggestion selected state gains `_render_stamp("Selected", "neutral")` next to the 2px ink border (§7.7). Confidence values wrapped in a tabular-nums span.
- [ ] **Step 3:** Delete `_approval_nav` (unused once forms use the shell) and the now-empty views CSS blocks.
- [ ] **Step 4:** `just tests` + fix structural assertions (e.g. tests matching the old pill markup), `just lint`, `just typecheck`.
- [ ] **Step 5:** Keyboard walkthrough of the full approval flow (queue → review → approve) + venue/artist detail + date page; screenshots.
- [ ] **Step 6: Commit** `refactor: unify approval and detail pages onto the shared shell`.

### Task 7 (Phase 4): Dark theme + accessibility sweep

**Files:**
- Modify: `src/berlin_events_explorer/theme.py` (dark token block, skip-link CSS, focus/target fixes), `src/berlin_events_explorer/webapp.py` (skip link + `id="main"` in every renderer incl. login; venue-row semantics fix), `tests/test_theme.py` (dark contrast pairs), `tests/test_webapp.py` (row semantics assertion updates if any)

**Interfaces:**
- Produces: `theme._DARK_TOKEN_VALUES: dict[str, str]` (§3.2 verbatim); dark block emitted twice — inside `@media (prefers-color-scheme: dark)` for `:root:not([data-theme="light"])` and unconditionally for `:root[data-theme="dark"]`; `CONTRAST_PAIRS_DARK` per §3.3 (text/surface 4.5, text-muted/surface 4.5, accent/surface 4.5, danger/surface 4.5, edge/surface 3.0).

- [ ] **Step 1: Failing test:** duplicate `test_token_pairs_meet_wcag_contrast` for `_DARK_TOKEN_VALUES` + `CONTRAST_PAIRS_DARK`; extend the no-hex test to tolerate nothing new (dark values live in the tokens layer too).
- [ ] **Step 2: Dark palette** exactly §3.2 (`#141518` bg … `#E9EAE5` focus). Verify the yellow rule inversion: accent may carry text on dark.
- [ ] **Step 3: Skip link:** first element in every `<body>`: `<a class="skip-link" href="#main">Skip to content</a>`; add `id="main"` to each page's `<main>`. CSS: visually hidden until `:focus-visible` (position absolute, on focus: fixed top-left, surface bg, ink text, 2px focus outline).
- [ ] **Step 4: Row semantics fix (§7.2):** in `_render_venues_content` drop `role="link"` and `tabindex="0"` from `<tr class="venue-row">`; keep `data-venue-row`/`data-venue-href` + the click-delegation script; delete the row `keydown` handler (the real `<a>` in the Name cell is the keyboard path); remove `.venue-row:focus` CSS.
- [ ] **Step 5: Target sizes + focus:** `.filter-clear` to 1.5rem (24px); confirm every interactive control ≥24px; confirm `:focus-visible` ring on tabs, rows' links, buttons, inputs, pagination, skip link. Add `tabindex="0"` + `role="region"` + `aria-label` to `.table-scroll` viewports (events + venues) so inner scroll stays keyboard-operable.
- [ ] **Step 6:** `just tests`, keyboard-only walkthrough of every view, screenshots 360/768/1280 in **both** themes (force via `data-theme` and emulation).
- [ ] **Step 7: Commit** `feat: ship dark theme, skip links, and a11y fixes`.

### Task 8 (Phase 5): Date stamps, `<time>`, pluralization, copy pass

**Files:**
- Modify: `src/berlin_events_explorer/webapp.py` (helpers + all render sites), `src/berlin_events_explorer/theme.py` (`.date-stamp` component), `tests/test_webapp.py` (date rendering assertions), `docs/design_language.md` (Status: proposed → adopted)
- Test: `tests/test_webapp.py` additions

**Interfaces:**
- Produces:

```python
_WEEKDAY_ABBREVIATIONS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH_ABBREVIATIONS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _format_date(value: date, *, with_year: bool = True) -> str:
    """Format a date for humans (design_language.md §9.2), locale-independent."""
    weekday = _WEEKDAY_ABBREVIATIONS[value.weekday()]
    month = _MONTH_ABBREVIATIONS[value.month - 1]
    formatted = f"{weekday} {value.day} {month}"
    return f"{formatted} {value.year}" if with_year else formatted


def _render_time(value: date, *, with_year: bool = True) -> str:
    """Render a date inside <time> so the machine value survives."""
    return (
        f'<time datetime="{value.isoformat()}">'
        f"{_format_date(value, with_year=with_year)}</time>"
    )


def _render_date_stamp(value: date | None) -> str:
    """Render the table lead cell's stamp (weekday over DD Mon, display face)."""
    if value is None:
        return '<span class="date-stamp date-stamp--tba">TBA</span>'
    weekday = _WEEKDAY_ABBREVIATIONS[value.weekday()]
    month = _MONTH_ABBREVIATIONS[value.month - 1]
    return (
        f'<time class="date-stamp" datetime="{value.isoformat()}">'
        f'<span class="date-stamp__weekday">{weekday}</span>'
        f'<span class="date-stamp__date">{value.day:02d} {month}</span></time>'
    )


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    """Return "<count> <word>" with English pluralization kept in one place."""
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"
```

- [ ] **Step 1: Failing tests:** `_format_date(date(2026, 3, 12)) == "Thu 12 Mar 2026"`; short form; `_plural(1, "event") == "1 event"` / `_plural(2, "event") == "2 events"`; event row contains `<time datetime="` and no bare isoformat in the date cell; date-page H1 contains the human form while `<title>` keeps ISO.
- [ ] **Step 2: Replace every human-facing isoformat** (audit via `grep -n "isoformat" webapp.py`): event row start-date cell → `<a class="date-link" href="/dates/{iso}">{_render_date_stamp(...)}</a>`; "Date added" cell → `_render_time(first_seen_at.date(), with_year=False)`; artist-detail event list → `_render_time`; date page H1 → `Events on {_render_time(target_date)}`; `<title>`s and URLs keep ISO (§9.2). `.date-stamp` CSS: display face bold, weekday `--text-xs` uppercase over `--text-base` date, tabular-nums, `--radius-sm`, ink on transparent (row hover supplies the wash).
- [ ] **Step 3: Centralize pluralization:** replace the three inline `"x" if n == 1 else "xs"` sites (venue events count, date-page meta, approval suggestion counts) with `_plural`.
- [ ] **Step 4: Copy pass (§7.9/§10):** events empty states — never-synced: "No events yet. Sync to pull the current Berlin listings." / filtered: "No events match this filter."; venues — "No venues yet. Venues appear after the first sync." / "No venues match this filter."; approval queue — "Nothing is waiting for approval." (unchanged, already compliant). Buttons already verb-first; check "Approve" → keep, "Find or refresh suggestions" → keep. Add the `lang="de"` no-op comment where provider prose would render (Resolved Decision 8).
- [ ] **Step 5:** `just tests` + `just lint` + `just typecheck`; screenshot the events table (the date stamp is the signature moment).
- [ ] **Step 6:** Flip `docs/design_language.md` line 3 Status to **adopted**.
- [ ] **Step 7: Commit** `feat: human date stamps, pluralization helper, and copy pass`.

### Final verification (all phases)

- [ ] `just tests`, `just typecheck`, `just lint` — clean.
- [ ] Zero external requests: grep rendered pages for `http://`/`https://` asset references (only the OSM iframe on venue detail is allowed — it is content, §1 scoped CDN removal to Datastar/fonts).
- [ ] Keyboard-only walkthrough: events (tabs, filter, pagination, rows), venues, login → settings → save, approvals → review → approve, detail pages, skip links.
- [ ] Screenshots 360/768/1280 × light/dark.

## Self-Review Notes

- Spec coverage: §3 (Tasks 1/4/7), §4 (3/4/8), §5-6 (4), §7.1-7.9 (4/5/6/8), §8 (4/7), §9.2/9.6 (8), §9.1 no-op documented, §10 (8), §11 (1/2/3), §12 phase separation preserved as commit boundaries.
- §9.4 diacritic folding and §9.5 DIN 5007 collation are explicitly non-blockers in the spec ("worth a note", "acceptable today") — out of scope.
- Types consistent: `theme.stylesheet() -> str`, `STYLESHEET_HREF`, `stylesheet_link()`, `font_preloads()`, `_render_stamp(label, tone)`, `_format_date(value, *, with_year)`, `_plural(count, singular, plural=None)` used identically across tasks.
