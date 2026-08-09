---
name: reviewing-evts-catalog
description: Build or assess evts editorial resolution. Use for review queues, suggestions, manual Claims and Decisions, stale overrides, evidence comparison, quick approval, merge/split, suppression, undo, impact previews, audit, and editor authorization.
---

# Reviewing the evts catalog

## Ground the task

Read [editorial workflows](../../../docs/editorial-workflows.md),
[pipeline and resolution](../../../docs/pipeline-and-resolution.md), and the
[Catalog/Resolution language](../../../contexts/catalog-resolution/CONTEXT.md).
For UI work also read [the design language](../../../docs/design-language.md).

Classify the work as identity, field selection, stale Manual Decision,
merge/split, rights, or publication review. Identify every public entity,
relationship, Saved Event, feed, and downstream task it can affect.

## Design the common path

Offer quick selection when one suggestion is safe and its impact fits in a
compact preview. Keep Approve visible and keyboard accessible; record the same
Decision quality as the detailed path; advance focus predictably and offer Undo.

Quick resolution is complete when the Editor can decide the ordinary case
without losing evidence, rationale, or audit.

## Design consequential review

Show:

1. current Projection and history;
2. source-native evidence and typed Claims;
3. alternatives and contradictions;
4. effective policy rationale;
5. field, relationship, URL, bookmark, feed, and task impact;
6. permitted select, reject, manual Claim, merge, split, suppress, and undo
   actions.

Require a reason for material decisions. A manual edit creates a Claim and then
a Decision; it never writes canonical state directly.

## Preserve decision integrity

- Keep Manual Decisions pinned until explicitly superseded.
- Mark changed dependencies stale without silently replacing the selection.
- Make merge survivor and redirects explicit.
- Make Split restoration and remaining ambiguity explicit.
- Keep cancellation, unlisting, suppression, and admission separate.
- Enforce role permissions on every action.
- Keep raw-evidence access separately authorized and audited.

## Verify

Exercise REV-001 through REV-006, PUB-002 through PUB-005, ACC-004, and UI-002
in [acceptance scenarios](../../../docs/acceptance-scenarios.md). Finish only
when each action is atomic or safely resumable, every resulting Decision is
traceable, and interruption cannot leave public state half-updated.
