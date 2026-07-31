# Design Language — Berlin Events Explorer

Status: **proposed** · Scope: the Litestar web UI (`src/berlin_events_explorer/webapp.py`)
· Audience: anyone (human or agent) implementing or reviewing UI changes.

This document is the single source of truth for how the Berlin Events Explorer UI
looks, reads, and behaves. It defines the design direction, the token system
(color, type, space, motion), component rules, and binding standards for
accessibility and internationalization. A follow-up task will migrate the
existing UI to this language; the migration plan at the end maps each phase onto
the current code.

---

## 1. Context and current state

The UI is server-rendered HTML built from Python f-strings in `webapp.py`, made
interactive with [Datastar](https://data-star.dev/). There is no template engine,
no CSS framework, and no build step — a deliberate simplicity this document
preserves. The audit that motivated this strategy found:

| Finding | Evidence |
|---|---|
| Three parallel token vocabularies | Settings page uses `--ink`/`--paper`, approvals and app shell use `--text`/`--surface`, with different values for the same roles (`#111827` vs `#0f172a`, `#dbe1ea` vs `#d5dbe8`) |
| 36 distinct hex colors, ad hoc | Mostly hand-picked Tailwind slate/blue values; three different danger reds (`#b42318`, `#b91c1c`, `#dc2626`), two primary blues (`#1d4ed8`, `#2563eb`) |
| Declared font never loaded | Every page declares `font-family: Inter, "Segoe UI", sans-serif` but no webfont is served; fractional weights (`650`, `750`) only render as intended with variable Inter installed locally |
| Styles duplicated per page | ~8 full-page documents each carry their own `<style>` block; shared helpers (`_approval_styles`, `_app_shell_styles`, `_event_shell_styles`, `_venue_shell_styles`, `_event_table_styles`) partially overlap and have drifted |
| No dark theme, no motion guard | No `prefers-color-scheme`, no `prefers-reduced-motion` despite view transitions on tab switches |
| Good a11y baseline, with gaps | `aria-label`/`aria-live`/`aria-current` used, keyboard-operable rows, visible focus — but the focus ring (`#bfdbfe` on white) fails non-text contrast, there is no skip link, and `role="link"` on `<tr>` destroys table row semantics |
| Machine dates shown to humans | `start_date.isoformat()` rendered directly; no `<time>` elements, no weekday, no locale decision |
| External CDN dependencies | Datastar is loaded from jsdelivr; problematic for GDPR posture, offline dev, and version pinning |

The current look — Tailwind blue on white with unloaded Inter — is the default
answer any tool produces for "event explorer web app". The direction below
replaces it with something grounded in what this application actually is.

---

## 2. Design direction: **Fahrplan**

Berlin Events Explorer is a working instrument: a registry of concerts, venues,
and artists with an editorial approval queue. Its closest visual relatives in
the subject's own world are Berlin's civic information surfaces — the U-Bahn
departure board, the BVG timetable column, the stamped guest list at a club
door. All of them share three traits this UI should adopt:

1. **Ink on paper, flat.** Print-like surfaces separated by rules and borders,
   not floating cards with large blur shadows. Information is arranged, not
   decorated.
2. **One signal color.** German transit signage achieves hierarchy with a single
   high-visibility accent — black on signal yellow — against an otherwise
   monochrome scheme. We use exactly that: ink, paper, and one yellow.
3. **Dates are the lead instrument.** Like a departure board, every event row
   leads with a compact, tabular, condensed date block. Time data is set in
   figures that align vertically.

**The signature element** is the black-on-yellow signal accent: the active tab
marker, the primary action button, the row-hover highlight, and the date-stamp
block all use ink-on-yellow, exactly like BVG signage. Everything else stays
quiet — paper, ink, hairlines. Boldness is spent in one place.

**Voice of the theme in one sentence:** a Berlin timetable you can search.

### Design principles

1. **Data first, chrome last.** The tables are the product. Nothing may compete
   with them for attention; decoration that does not encode information is cut.
2. **Signal, not palette.** One accent color, used only where the user should
   look or act. If two things on a screen are yellow, one of them is wrong.
3. **Flat and printed.** Elevation comes from borders and background steps, not
   shadows. Overlays (if ever introduced) are the only layer allowed a shadow.
4. **Every state is designed.** Empty, loading, error, and zero-results states
   are written and styled deliberately — an empty screen is an invitation to act.
5. **The floor is AA.** WCAG 2.2 AA is a build requirement, not a review step.
   Tokens are pre-verified for contrast; components ship keyboard-first.

---

## 3. Color tokens

Tokens are semantic (named for role, not hue) and themed via CSS custom
properties. The light theme is default; the dark theme activates via
`@media (prefers-color-scheme: dark)` and can be forced with
`[data-theme="dark"]` / `[data-theme="light"]` on `<html>` if a toggle is added
later.

### 3.1 Light theme ("paper")

| Token | Value | Role |
|---|---|---|
| `--color-bg` | `#F4F4F1` | App background (concrete white, cool-neutral) |
| `--color-surface` | `#FFFFFF` | Tables, cards, inputs |
| `--color-surface-sunken` | `#ECEDE9` | Table headers, secondary buttons, wells |
| `--color-text` | `#1A1C1E` | Primary text ("ink") |
| `--color-text-muted` | `#52565C` | Secondary text, hints, meta lines |
| `--color-line` | `#D8D9D4` | Decorative rules, table row borders |
| `--color-edge` | `#6F747B` | Borders that must be perceived: inputs, controls |
| `--color-accent` | `#F0D722` | Signal yellow — markers, highlights, primary button fill |
| `--color-accent-wash` | `#FAF5D7` | Row hover, selected-suggestion background |
| `--color-danger` | `#B42318` | Destructive actions, error text |
| `--color-danger-strong` | `#8C1D13` | Error text on `--color-danger-wash` |
| `--color-danger-wash` | `#FCEBE8` | Error notice background |
| `--color-success` | `#1E6A42` | Success text |
| `--color-success-wash` | `#E7F2EA` | Success notice background |
| `--color-warn` | `#6E5200` | Warning text (pending/attention states) |
| `--color-warn-wash` | `#FAF0CF` | Warning notice background |
| `--color-focus` | `#1A1C1E` | Focus ring (ink on light theme) |

### 3.2 Dark theme ("night bus")

Charcoal and off-white — asphalt, not pure black — with the same signal yellow,
which on dark surfaces is strong enough to carry text and markers by itself.

| Token | Value | Role |
|---|---|---|
| `--color-bg` | `#141518` | App background |
| `--color-surface` | `#1C1E21` | Tables, cards, inputs |
| `--color-surface-sunken` | `#24262A` | Table headers, wells |
| `--color-text` | `#E9EAE5` | Primary text |
| `--color-text-muted` | `#A9ADB2` | Secondary text |
| `--color-line` | `#33363A` | Decorative rules |
| `--color-edge` | `#8A8F96` | Perceivable borders |
| `--color-accent` | `#F0D722` | Signal yellow (may be text on dark) |
| `--color-accent-wash` | `#2C2A1A` | Row hover, selection |
| `--color-danger` | `#F2988F` | Error text |
| `--color-danger-wash` | `#3A1712` | Error notice background |
| `--color-success` | `#7FCB9C` | Success text |
| `--color-success-wash` | `#15291D` | Success notice background |
| `--color-warn` | `#E5C95B` | Warning text |
| `--color-warn-wash` | `#2E2812` | Warning notice background |
| `--color-focus` | `#E9EAE5` | Focus ring (off-white on dark) |

### 3.3 Verified contrast

All ratios below were computed (WCAG 2.x relative-luminance formula), not
estimated. AA requires 4.5:1 for text, 3:1 for large text and non-text UI.

| Pair | Ratio | Requirement |
|---|---|---|
| text / bg (light) | 15.5:1 | 4.5:1 ✓ |
| text-muted / surface (light) | 7.4:1 | 4.5:1 ✓ |
| text / accent (ink on yellow) | 11.8:1 | 4.5:1 ✓ |
| danger / surface (light) | 6.6:1 | 4.5:1 ✓ |
| danger-strong / danger-wash (light) | 7.9:1 | 4.5:1 ✓ |
| success / success-wash (light) | 5.7:1 | 4.5:1 ✓ |
| warn / warn-wash (light) | 6.4:1 | 4.5:1 ✓ |
| edge / surface (light) | 4.7:1 | 3:1 ✓ |
| accent / surface (light) | **1.45:1** | see rule below |
| text / surface (dark) | 13.8:1 | 4.5:1 ✓ |
| text-muted / surface (dark) | 7.4:1 | 4.5:1 ✓ |
| accent / surface (dark) | 11.5:1 | 4.5:1 ✓ |
| danger / surface (dark) | 7.7:1 | 4.5:1 ✓ |
| edge / surface (dark) | 5.1:1 | 3:1 ✓ |

### 3.4 Binding color rules

- **The yellow rule.** On the light theme, `--color-accent` fails contrast
  against white (1.45:1) and against yellow-blind vision. It must therefore
  never appear alone: always ink text *on* yellow, or a yellow underline/marker
  *beneath* ink text, or a yellow block *with* an ink border. On the dark theme
  it may stand alone. Meaning is never encoded in color only — every status
  also has a text label.
- **No new colors.** Extend the system by adding a semantic role, never by
  inlining a hex value in a component. A hex literal outside the token block is
  a defect.
- **Links are ink, not blue.** In a UI where nearly every table cell is a link,
  blue link text turns the product into a wall of blue. Links are
  `--color-text` with a visible underline (`text-decoration-color:
  var(--color-accent)`, `text-underline-offset: 0.15em`); hover fills
  `--color-accent-wash`. The underline (a non-color cue) is what marks a link,
  satisfying WCAG 1.4.1.

---

## 4. Typography

### 4.1 Families

| Role | Stack | Loaded |
|---|---|---|
| Display | `"D-DIN Condensed", "Archivo Narrow", "Arial Narrow", sans-serif` | self-hosted woff2 (Bold) |
| Body / UI | `"Inter", "Segoe UI", "Helvetica Neue", sans-serif` | self-hosted variable woff2 |
| Data / technical | `ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, monospace` | system only, zero bytes |

- **D-DIN Condensed** (SIL OFL) is a faithful derivative of **DIN 1451** — the
  letterform standard of German road and rail signage, i.e. the actual typeface
  of Berlin's streets and U-Bahn. It is used *only* at display sizes: the H1,
  page kickers, tab labels, and the date-stamp block. This is where the
  product's personality lives.
- **Inter** stays as the body face — the code already declares it; now it is
  actually served. As a variable font it provides real weights and full
  OpenType numeric features at ~100 KB for one file. Subset to
  `latin` + `latin-ext` (German umlauts and ß are Latin-1, but artist and venue
  names routinely include Polish, Turkish, and Czech characters — latin-ext is
  required, not optional).
- **Monospace** is reserved for machine-flavored values: OSM ids, providers,
  version strings, raw timestamps in the approval detail views. System stack
  only; do not ship a mono webfont.

Loading: self-hosted from the package's `resources/` directory (see §10),
`font-display: swap`, `<link rel="preload" as="font">` for the two files.
**No font CDN, ever** — German case law (LG München, 2022) treats Google Fonts
embedding as a GDPR violation, and this is a Berlin product; self-hosting is a
correctness requirement here, not an optimization.

### 4.2 Scale and weights

A compact scale tuned for data density, defined as tokens:

| Token | Size | Use |
|---|---|---|
| `--text-xs` | 0.75rem (12px) | Kickers, stamp labels, mobile cell labels |
| `--text-sm` | 0.85rem (13.6px) | Table meta, hints, pagination |
| `--text-base` | 0.95rem (15.2px) | Body, table cells, inputs |
| `--text-md` | 1.1rem (17.6px) | Section headings (h2 in cards) |
| `--text-lg` | 1.35rem (21.6px) | Page section titles |
| `--text-display` | `clamp(1.6rem, 2.6vw, 2.4rem)` | H1, display face |

- Weights: **400** (body), **600** (emphasis, labels, active tab), **700**
  (buttons, display). Retire the fractional `650`/`750` weights — standard
  weights render identically everywhere and survive font fallback.
- Line height: `1.55` for prose, `1.35` for table cells and controls.
- Letterspacing: kickers and stamps `+0.08em` uppercase; display face `-0.01em`;
  body untouched.

### 4.3 Numerics — the timetable rule

Everything that is a figure aligns like a departure board:

```css
.event-table td, time, .pagination, .result-count, .stamp {
  font-variant-numeric: tabular-nums;
}
```

Dates in tables render as a **date stamp**: weekday abbreviation over
`DD Mon` in the display face, tabular, inside the row's lead cell (see §7.2).
This is the one place display type appears inside data.

---

## 5. Space, radius, elevation

- **Spacing scale** (4px base): `--space-1` 0.25rem · `--space-2` 0.5rem ·
  `--space-3` 0.75rem · `--space-4` 1rem · `--space-5` 1.5rem · `--space-6`
  2rem · `--space-7` 3rem. No raw margins/paddings outside the scale.
- **Radius**: `--radius-sm` 4px (stamps, inline chips) · `--radius-md` 8px
  (inputs, buttons) · `--radius-lg` 12px (cards, panels) · `--radius-full`
  for the pagination pills. Replaces today's eight ad hoc radii (.45–1rem).
- **Elevation**: none by default. Surfaces separate with `1px solid
  var(--color-line)` and background steps (`bg` → `surface` → `surface-sunken`).
  The current `box-shadow: 0 16–18px 40–50px …` floating-card look is removed.
  Only true overlays (dropdown, dialog — none exist today) may use
  `--shadow-overlay: 0 8px 24px rgb(0 0 0 / 0.16)`.
- **The page**: content column `max-width: 1100px` (unchanged), page gutter
  `--space-5` desktop / `--space-3` mobile. The settings page joins the same
  shell and column instead of its own 760px layout.

---

## 6. Motion

- Durations: `--motion-fast: 120ms` (hover, focus) and `--motion-base: 200ms`
  (tab content swaps, notice appearance). Easing `ease-out`. Nothing longer;
  nothing decorative or ambient.
- The existing view transition on tab switches (`view-transition-name:
  tab-content`) is kept — it is the product's one orchestrated moment — as a
  quick crossfade, not a slide.
- **Binding rule:** all transitions and view transitions are wrapped in a
  reduced-motion guard; this is currently missing entirely.

```css
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after { transition: none !important; animation: none !important; }
  ::view-transition-group(*), ::view-transition-old(*), ::view-transition-new(*) {
    animation: none !important;
  }
}
```

- The sync progress bar may animate (it reports real work); it must also make
  sense frozen, which `<progress>` already does.

---

## 7. Components

The existing class inventory maps onto this catalog; names in parentheses are
current classes that the component replaces or absorbs.

### 7.1 Application shell (`events-app`, `tabs`, `toolbar`)

- One shared shell for **every** page — events, venues, approvals, settings,
  and the venue/artist detail pages, which today each carry their own page
  skeleton. Header: kicker + H1 in display type, toolbar right-aligned.
- Tabs are the primary navigation. Active tab: ink text, `3px` solid
  `--color-accent` underline (the signal marker), plus `aria-current="page"` —
  the marker is never the only cue. Inactive: `--color-text-muted`. Keep the
  existing `overflow-x: auto` for narrow screens.
- First element in `<body>`: a skip link (`.skip-link`) that becomes visible on
  focus and jumps to `#main`.

### 7.2 Event table (`event-table`, `table-scroll`, `table-panel`)

The centerpiece. Flat surface, sticky header row on `--color-surface-sunken`,
`1px` `--color-line` row rules, row hover `--color-accent-wash` (not gray).

- **Date stamp cell**: lead cell renders `<time datetime="2026-03-12">` with
  weekday abbreviation + `12 Mar` in D-DIN Condensed, tabular. Today's raw
  `isoformat()` output is retired from all human-facing positions (§9).
- The fixed-slot height mechanism (`--table-view-height`,
  `TABLE_ROW_SLOT_REM`) is kept — stable pagination is good UX — and the inner
  scroll viewport must remain keyboard-scrollable (`tabindex="0"` with an
  `aria-label` on the scroll region).
- **Row-link fix**: drop `role="link"` and `tabindex="0"` on `<tr>`
  (`venue-row`) — a `<tr>` with `role="link"` loses its row semantics for
  screen readers. Instead the row's primary cell keeps its real `<a>`, and the
  whole-row click affordance stays as a JS convenience on top of intact
  semantics.
- Mobile (`< 720px`): keep the proven card transform (`display: block` +
  `data-label` pseudo-labels), restyled with tokens.

### 7.3 Buttons (`sync-button`, `action-button`, `secondary`, `danger-button`)

| Variant | Style |
|---|---|
| Primary | `--color-accent` fill, `--color-text` label, `1px` ink border — the BVG move. One per view. |
| Secondary | `--color-surface-sunken` fill, ink label, `--color-edge` border |
| Danger | `--color-danger` fill, white label; destructive forms only |
| Quiet | borderless, ink label, underline on hover (e.g. "Clear filter") |

Minimum target size 24×24 px (WCAG 2.5.8; today's `filter-clear` is 22.4px —
bump it). Labels are verbs that name the outcome: "Save settings",
"Sync events", "Approve venue" (§10 voice). Disabled buttons keep 3:1 against
their background where feasible and always retain their label.

### 7.4 Status stamp (`status`)

Replaces the indigo pill. Approval states render as **stamps**: uppercase
`--text-xs`, letterspaced, `1.5px` solid border, `--radius-sm`, transparent
fill — like an ink stamp on a guest list.

| State | Border/text color |
|---|---|
| Verified | `--color-success` |
| Pending / auto-matched | `--color-warn` |
| Rejected / failed | `--color-danger` |
| Neutral (entity kind: "Venue", "Artist") | `--color-text-muted` |

Each stamp is text + color, never color alone.

### 7.5 Forms (`form-grid`, `filter-input`, `filter-clear`, settings inputs)

- Inputs: `--color-surface` fill, `1px` `--color-edge` border (perceivable at
  3:1 — today's `#b9c2d0` border fails this), `--radius-md`, `--text-base`.
- Every input keeps a programmatically associated `<label>` (already mostly
  true). Hints connect via `aria-describedby`. Validation errors: message
  adjacent to the field, `--color-danger` text plus an icon or prefix
  ("Error:") so color is not the only signal.
- The search filter keeps its debounced Datastar behavior; the clear button
  grows to 24px and keeps its `aria-label`.

### 7.6 Notices (`notice`, `error`, `sync-error`)

Wash background + strong text from the semantic triads (§3), `--radius-md`,
with a `4px` solid left border in the strong color as the non-color cue.
Notices state what happened and what to do next; they never apologize (§10).

### 7.7 Suggestion cards (`suggestion`, `suggestions`)

Approval-queue candidates: flat `--color-surface` cards, `--color-line`
border. Selected: `2px` ink border **plus** a "Selected" stamp — replacing
today's blue glow, and readable without color. Confidence values render in
tabular figures.

### 7.8 Pagination & meta (`pagination`, `pagination-link`, `result-count`, `meta`)

Pill links with `--color-edge` borders; disabled state keeps 3:1 text where
possible and drops the underline. "Page 3 of 12" and "Showing 21 to 40 of 480"
stay `aria-live="polite"` (already correct — keep it) and tabular.

### 7.9 Empty states (`empty-state`)

Every table's empty state names the situation and the action:
"No events yet. Sync to pull the current Berlin listings." — with the relevant
action nearby. Zero-results-from-filter is a distinct message from
never-synced.

---

## 8. Accessibility standard (binding)

Target: **WCAG 2.2 AA**. The floor, not the ceiling.

1. **Contrast**: only token pairs from §3.3. New pairs must be verified before
   merge (keep `contrast.py` or equivalent alongside the stylesheet).
2. **Keyboard**: every interaction reachable and operable by keyboard; focus
   order follows visual order; no traps. The Datastar in-place navigation must
   keep real `<a href>`s underneath (it does today — preserve this so
   middle-click, cmd-click, and no-JS all work).
3. **Focus visibility**: `:focus-visible` with `2px solid var(--color-focus)`
   `outline-offset: 2px` on all interactive elements. Replaces the current
   `#bfdbfe` ring, which fails 3:1 on white.
4. **Skip link** to `#main` on every page.
5. **Target size**: ≥ 24×24 px for all controls (2.5.8).
6. **Semantics**: tables stay tables (see the `role="link"` fix, §7.2); tabs
   as links carry `aria-current="page"`; live regions (`aria-live="polite"`)
   announce result-count changes after Datastar swaps — never announce entire
   table bodies.
7. **Motion**: reduced-motion guard as specified in §6.
8. **Color independence**: every state readable with color removed (stamps have
   text, notices have borders + text, links have underlines).
9. **Zoom & reflow**: layouts survive 200% zoom and 320px width (the existing
   720px card transform covers this; keep it working).
10. **Dark mode is not optional**: both themes ship together; every component
    is reviewed in both.

---

## 9. Internationalization

The product is English-language UI over German-language content. Decisions:

1. **UI locale: English (`en`)** — `<html lang="en">` stays. When source
   material is rendered in German (event descriptions, venue blurbs pulled
   from providers), wrap it in `lang="de"` so screen readers switch
   pronunciation and hyphenation behaves.
2. **Dates**: humans never see `isoformat()`. Human-facing format is
   `Thu 12 Mar 2026` (weekday first — this is a schedule), short form
   `Thu 12 Mar` inside tables, always inside
   `<time datetime="2026-03-12">…</time>` so the machine value survives. The
   ISO form remains correct for URLs (`/dates/2026-03-12`) and titles where it
   already is one. Implement one helper (`_format_date` /
   `_render_date_stamp`) — no scattered `strftime` calls.
3. **Times & zone**: all wall-clock times are **Europe/Berlin**, displayed
   24-hour (`20:00`, never 8 PM — Berlin convention even in English). Storage
   stays UTC; conversion happens at render time only.
4. **Text handling**: UTF-8 throughout (already true); `html.escape` on all
   interpolated content (already the convention — keep it absolute).
   Filtering uses `casefold()` (correctly folds `ß`→`ss`); as an enhancement,
   fold diacritics too (NFKD-strip) so "Sääl" matches "Saal" — worth a note in
   the search helpers, not a blocker.
5. **Sorting**: naive Unicode sort misplaces umlauts (Ä after Z). Acceptable
   today; if venue lists become primarily alphabetical, adopt DIN 5007
   collation (locale-aware or a small key function).
6. **Translation readiness, not translation**: no gettext machinery now. But:
   no mid-sentence string concatenation of UI text, pluralization kept in
   helper functions (the `"suggestion" if n == 1 else "suggestions"` pattern —
   centralize it), and user-facing strings kept whole so a future extraction
   is mechanical.
7. **Text expansion tolerance**: German UI text runs ~30% longer than English.
   No fixed-width buttons or truncating labels; tabs scroll; the layout must
   already tolerate a future language switch.
8. **Font coverage**: `latin-ext` subset required (Polish, Czech, Turkish,
   Hungarian names appear routinely in Berlin lineups).

---

## 10. Content & voice

Words are design material. Register: a competent dispatcher — plain, specific,
unhurried.

- **Verbs name outcomes**: "Sync events", "Save settings", "Approve venue",
  "Discard suggestion". The button that says "Approve" yields a message that
  says "Approved". Never "Submit", "OK", or "Click here".
- **Sentence case everywhere** except stamps and kickers (which are styled
  uppercase via CSS, not typed uppercase).
- **Errors say what and how**: "MusicBrainz did not respond. Try again in a
  minute." Never vague ("Something went wrong"), never apologetic.
- **Empty states invite**: name the situation, offer the action (§7.9).
- **User vocabulary, not system vocabulary**: "suggestions", not "candidates";
  "checked", not "enriched"; provider names (MusicBrainz, OpenStreetMap) are
  fine — they're user-meaningful sources here.
- **The name of the city is the brand.** The H1 "Berlin Events Explorer" in
  DIN-lineage condensed type *is* the logo; no icon, no wordmark art.

---

## 11. CSS & asset architecture

1. **One stylesheet.** All CSS consolidates into a single string assembled in
   one module (e.g. `theme.py` or a `_stylesheet()` function), served once at
   `/static/app.css` with far-future caching + a version query param, replacing
   the per-page `<style>` blocks and the five overlapping style helpers. The
   per-page duplication is what allowed three token vocabularies to drift apart;
   the fix is structural, not disciplinary.
2. **Cascade layers** keep specificity honest:
   `@layer tokens, base, components, views;` — tokens (custom properties +
   themes), base (element defaults, focus, reduced-motion), components (§7),
   views (the rare page-specific rule). No `!important` outside the
   reduced-motion guard.
3. **Vendor everything.** Datastar moves from jsdelivr to a pinned local copy
   under `src/berlin_events_explorer/resources/static/` (the `resources/`
   directory exists and is empty), served by the app. Fonts likewise
   (`fonts/inter-var.woff2`, `fonts/d-din-condensed-bold.woff2`). Zero
   third-party requests: GDPR-clean, offline-capable, reproducible.
4. **No framework.** The f-string + Datastar approach stays. A utility-class
   framework (Tailwind et al.) would bloat every Python string literal and add
   a build step for no gain at this scale. Semantic classes + tokens fit the
   architecture the project already chose.
5. **Token discipline in Python**: the handful of style-adjacent constants in
   `webapp.py` (`TABLE_ROW_SLOT_REM`, `TABLE_HEADER_SLOT_REM`) stay in Python
   (they drive layout math) but must mirror the stylesheet's row metrics —
   note the coupling in both places.

---

## 12. Migration plan (the follow-up task)

Five phases, each independently shippable and verifiable. Do not combine the
mechanical phase with the visual one — reviewability depends on it.

**Phase 1 — Consolidate (no visual change).**
Extract every `<style>` block and style helper into the single stylesheet;
unify the three token vocabularies onto §3 *names* while keeping current
values; serve `/static/app.css`; vendor Datastar and fonts into `resources/`.
Old→new token mapping: `--ink`/`--text` → `--color-text` · `--paper`/`--surface(-soft)`
→ `--color-bg`/`--color-surface(-sunken)` · `--line` → `--color-line` ·
`--blue`/`--primary` → (interim) `--color-accent` · `--danger` (3 values) →
`--color-danger`. Verify: every page renders identically; zero external requests.

**Phase 2 — Re-theme.**
Swap token values to §3, load the two typefaces, apply §4 scale/weights,
§5 space/radius/flat elevation, §6 motion + reduced-motion guard, link
treatment, focus ring. This is the visible re-skin of the shared shell,
events, and venues views.

**Phase 3 — Unify the outliers.**
Settings, approvals (including `_legacy_render_approval_queue` and the
review/detail pages), and venue/artist detail pages move onto the shared shell
and component catalog. Delete `_approval_styles` and per-page skeletons.
Retire remaining legacy render paths where the new shell covers them.

**Phase 4 — Dark theme + a11y sweep.**
Ship the dark palette; add skip links; fix `role="link"` rows, 24px targets,
`:focus-visible` ring everywhere; verify both themes against §8's checklist.

**Phase 5 — Content & i18n polish.**
Date-stamp component + `_format_date` helper (kill human-facing `isoformat()`),
`<time>` elements, `lang="de"` wrapping, empty-state and notice copy pass per
§10, pluralization helper.

Each phase ends with: `just tests`, a keyboard-only walkthrough of every view,
and a screenshot review at 360px / 768px / 1280px in both themes (from Phase 4).

---

## 13. Decisions & alternatives considered

| Decision | Alternative rejected | Why |
|---|---|---|
| Signal yellow accent | Keep Tailwind blue | Blue-on-white with Inter is the template default this redesign exists to escape; yellow is grounded in Berlin's actual civic signage and pairs with ink at 11.8:1 |
| Ink links + accent underline | Blue link text | Nearly every cell is a link; colored link text at this density is noise |
| D-DIN Condensed display | A serif display face; Space Grotesk | DIN 1451 lineage is *the* Berlin letterform; serif reads editorial-magazine, not instrument; Space Grotesk is the current AI-default display face |
| Keep Inter for body | Wholesale font swap | It's already the declared intent, excels at data-UI sizes, has the numeric features §4.3 needs; the display face carries the personality |
| Flat, border-based elevation | Current soft-shadow cards | Timetable aesthetic; cheaper to render; dark-theme shadows barely read anyway |
| One stylesheet, `@layer` | Per-page inline styles (status quo) | Inline styles caused the drift documented in §1; caching wins besides |
| No CSS framework | Tailwind / Pico / Open Props | f-string architecture makes utility classes painful; tokens give the same discipline without a build step |
| English UI, Berlin conventions (24h, Europe/Berlin) | Full German UI or full en-US formats | Matches the actual audience: English-reading Berliners; keeps translation open via §9.6 |
| Both themes from Phase 4 | Light-only | Night-time event browsing is a core use case for a concert tool; the palette was designed dark-first-class |

Open questions for the implementer (defaults chosen, overridable):
- Theme toggle UI, or `prefers-color-scheme` only? **Default: media query only;**
  add a toggle later if wanted (tokens already support `data-theme`).
- Weekday language in date stamps once German events dominate — `Thu` vs `Do`?
  **Default: English (`Thu`), consistent with UI locale.**
