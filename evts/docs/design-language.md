# Design language: Fahrplan

Fahrplan is the adopted visual and interaction language for every evts surface.
It treats the catalog as a Berlin timetable: dense, flat, date-led, and marked
by one signal-yellow accent.

## Principles

1. **Data first, chrome last.** Listings and evidence are the product.
2. **Signal, not palette.** Yellow marks the current focus or primary action.
3. **Flat and printed.** Borders and background steps establish structure;
   ordinary content does not float on shadows.
4. **Dates lead.** Schedule is the strongest repeated visual landmark.
5. **Every state is designed.** Loading, empty, partial, stale, error, and
   permission states have purposeful copy and layout.
6. **AA is the floor.** WCAG 2.2 AA is a component requirement.

## Color

### Light theme

| Token | Value | Use |
|---|---|---|
| background | #F4F4F1 | App background |
| surface | #FFFFFF | Tables, panels, inputs |
| surface-sunken | #ECEDE9 | Headers and wells |
| text | #1A1C1E | Primary ink |
| text-muted | #52565C | Secondary copy |
| line | #D8D9D4 | Decorative rules |
| edge | #6F747B | Perceivable control borders |
| accent | #F0D722 | Signal yellow |
| accent-wash | #FAF5D7 | Hover and selection |
| danger | #B42318 | Destructive/error text |
| danger-wash | #FCEBE8 | Error surface |
| success | #1E6A42 | Success text |
| success-wash | #E7F2EA | Success surface |
| warning | #6E5200 | Warning text |
| warning-wash | #FAF0CF | Warning surface |
| focus | #1A1C1E | Focus indicator |

### Dark theme

| Token | Value |
|---|---|
| background | #141518 |
| surface | #1C1E21 |
| surface-sunken | #24262A |
| text | #E9EAE5 |
| text-muted | #A9ADB2 |
| line | #33363A |
| edge | #8A8F96 |
| accent | #F0D722 |
| accent-wash | #2C2A1A |
| danger | #F2988F |
| danger-wash | #3A1712 |
| success | #7FCB9C |
| success-wash | #15291D |
| warning | #E5C95B |
| warning-wash | #2E2812 |
| focus | #E9EAE5 |

Signal yellow on a light surface must carry ink text, an ink border, or an
equivalent non-color cue; yellow alone lacks sufficient contrast. Meaning always
has text or shape in addition to color. Links are ink with a signal-yellow
underline, not a second accent color.

## Typography

- **Display:** D-DIN Condensed Bold, with a metrically compatible condensed
  sans-serif fallback. Use for page titles, navigation labels, and date stamps.
- **Body/UI:** Inter variable, with a high-quality system sans-serif fallback.
- **Technical data:** system monospace for source keys, versions, hashes, and
  raw timestamps.

Use appropriately licensed, self-hosted font assets. Body sizes begin near
0.95rem with 1.5 line height; supporting data may use 0.75–0.85rem without
becoming essential low-contrast microcopy. Use weights 400, 600, and 700.
Uppercase display labels use modest tracking. Dates, times, counts, prices, and
confidence values use tabular numerals.

## Space and shape

- Use a four-pixel spacing base with steps equivalent to 4, 8, 12, 16, 24, 32,
  and 48 pixels.
- Use 4-pixel radii for stamps, 8 pixels for controls, and 12 pixels for panels.
- Separate ordinary surfaces with one-pixel rules and background steps.
- Reserve shadows for true overlays.
- Use a dense content width around 1100 pixels with 24-pixel desktop and
  12-pixel mobile gutters.
- Keep page title/actions, a short gap, one compact toolbar, and the main data
  surface close together.

## Shared shell

Every public, account, editorial, and administrative page uses one shell:

- skip link;
- compact product header;
- primary navigation with a strong current marker;
- optional contextual actions;
- main landmark;
- restrained footer containing legal, API/feed, and language links.

Navigation labels use user vocabulary. Public Users do not see editorial
destinations; authorization still applies independently.

## Event listings

Desktop listings use a real semantic table or an equivalently accessible grid.
The lead cell is a date stamp: weekday above day/month, with time and precision
nearby. Remaining columns prioritize title, Venue/location, Participants,
Geographic Area, lifecycle/admission state, and first-publication information.

- Entire rows may offer a large pointer target, but retain native link and row
  semantics.
- Hover and keyboard focus use accent wash plus a perceivable outline.
- Sort state is labeled and exposed to assistive technology.
- Filters live in one compact toolbar and remain visible as removable criteria.
- Pagination uses stable controls, result counts, and preserved filters.
- Unknown time says “Time TBA”; unknown Venue says “Venue TBA.”
- Cancelled and postponed rows remain readable; never rely on strikethrough or
  color alone.

At narrow widths, each Event becomes a compact bordered record with the date
stamp, title, location, key Participants, and state in that order. Secondary
metadata can wrap or disclose; essential facts cannot require horizontal
scrolling.

## Detail pages

Event detail begins with schedule stamp, lifecycle label, title, and location.
Participants and ticket actions follow; description, classification, provenance-
safe update information, related Events, and source/info Links are secondary.
First publication is labeled “Added” and cannot be confused with occurrence
date.

Venue, Participant, Area, and Series pages use the same shell and listing
components. Historical names and unresolved data are plainly labeled.

## Editorial workbench

The queue is information-dense and optimized for repeated decisions:

- reason, subject, best suggestion, risk, impact, source, age, and assignment;
- one strong Approve action when quick resolution is allowed;
- keyboard shortcuts that never replace visible controls;
- persistent success/undo feedback without moving focus unexpectedly.

The detailed comparison uses aligned current/suggested/evidence columns at wide
sizes and stacked sections at narrow sizes. Source-native evidence and machine
rationale are visually distinct. Confidence is supporting data, never the
largest element. Merge, split, suppression, and destructive actions require an
ink-bordered danger treatment and confirmation describing impact.

## Components

- **Buttons:** one signal-yellow primary action per region; neutral bordered
  secondary actions; danger actions use danger text/wash.
- **Links:** visible underline, generous focus target, external-link label when
  behavior is unexpected.
- **Inputs:** persistent labels, edge-color border, inline description/error,
  and no placeholder-only naming.
- **Stamps:** compact text labels for lifecycle, availability, publication,
  source, and review state.
- **Notices:** icon/label plus semantic tone; live status messages do not steal
  focus.
- **Dialogs/overlays:** used only for tasks requiring interruption; trap and
  restore focus correctly.
- **Evidence blocks:** technical typography, explicit source/time/language, and
  controlled expansion for native payloads.
- **Skeletons/progress:** respect reduced motion and retain stable layout.

## Content language

Use short, direct, domain-correct labels:

- “suggestion,” not “candidate,” in ordinary editorial UI;
- “source record,” not “event,” when displaying acquisition evidence;
- “not listed by source,” not “deleted” or “cancelled”;
- “Added,” “Updated,” and “Event date” as separate timestamps;
- verbs for actions: Approve, Reject, Merge, Split, Suppress, Restore.

Errors say what remained safe and what the user can do next. Dates and plural
forms use locale-aware presentation. Source text keeps its declared language.

## Accessibility and motion

- Meet WCAG 2.2 AA contrast, keyboard, focus, target-size, error, and reflow
  requirements.
- Use semantic landmarks, headings, tables, lists, links, buttons, and form
  controls before adding roles.
- Provide visible focus with at least a 3:1 non-text contrast difference.
- Maintain logical focus after filtering, pagination, quick decisions, dialogs,
  and streamed updates.
- Announce material asynchronous results through appropriately scoped live
  regions.
- Do not encode status only through color, position, icon, or motion.
- Honor reduced motion; transitions are brief and never required to understand
  state.
- Support zoom and reflow at 320 CSS pixels without loss of functionality.

## Design acceptance

Review public listings, search, every detail type, registration/account pages,
review queue/detail, source configuration, and empty/error states at 360, 768,
and 1280 CSS pixels in both themes. Complete all primary workflows keyboard-only
and with screen-reader semantics inspected. Any new token, color, component, or
interaction pattern requires an update here before broad reuse.
