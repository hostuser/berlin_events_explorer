---
name: designing-evts-ui
description: Design or review evts user interfaces with the adopted Fahrplan language. Use for public listings and detail pages, search/filter controls, accounts, editorial queues and comparisons, administrative screens, components, visual tokens, responsive behavior, copy, localization, or accessibility.
---

# Designing the evts UI

## Ground the screen

Read [the design language](../../../docs/design-language.md) completely. Then
read the relevant behavior in
[public product and API](../../../docs/public-product-and-api.md) or
[editorial workflows](../../../docs/editorial-workflows.md), plus the Context
whose words appear on screen.

List the user's goal, primary data, primary action, states, permissions, and
responsive constraints before choosing layout.

## Compose in Fahrplan

- Use the shared shell and dense, flat, date-led hierarchy.
- Use signal yellow for one current focus or primary action per region.
- Build page title/actions, a short gap, one compact toolbar, then the data
  surface.
- Use semantic tables for wide listings and compact records at narrow widths.
- Use D-DIN Condensed for display/date stamps, Inter for UI, and tabular numerals
  for data.
- Use canonical domain language and distinguish Added, Updated, and Event date.
- Keep source labels plain when Venue or Participant identity is unresolved.

## Design every state

Specify loading, empty, zero-result, partial, stale, error, permission,
success/Undo, unknown time, Venue TBA, online/hybrid, postponed, cancelled,
replaced, merged, and suppressed behavior relevant to the screen.

For editorial work, optimize the safe common case for quick selection while
keeping evidence, alternatives, policy rationale, impact, and full review one
step away.

## Bind accessibility

- Start with native landmarks, headings, tables, links, buttons, and labels.
- Preserve visible focus and predictable focus after updates.
- Expose sort, filter, validation, progress, and asynchronous results.
- Pair color, icon, and motion with text or structure.
- Honor reduced motion and reflow at 320 CSS pixels.
- Keep primary workflows useful without client-side scripting.
- Localize chrome, dates, numbers, and plural forms without altering source
  language.

## Verify

Review at 360, 768, and 1280 CSS pixels in light and dark themes. Complete the
primary workflow keyboard-only, inspect semantics and announcements, and check
all UI-001 through UI-003 scenarios in
[acceptance scenarios](../../../docs/acceptance-scenarios.md).

Finish only when no new token or pattern bypasses the design language and every
state remains understandable without color or motion.
