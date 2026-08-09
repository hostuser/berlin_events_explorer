---
name: working-with-evts-domain
description: Maintain the evts ubiquitous language and logical model. Use when changing domain terminology, canonical entities, identity, provenance, lifecycle or publication states, relationships, resolution decisions, context boundaries, or ADR-worthy architecture.
---

# Working with the evts domain

## Ground the change

1. Read [the context map](../../../CONTEXT-MAP.md) and every Context touched by
   the request.
2. Read [the logical data model](../../../docs/logical-data-model.md) and relevant
   [ADRs](../../../docs/adr/).
3. Find every requirement, interface, workflow, and acceptance scenario using
   the affected concept.

Grounding is complete when every current definition and invariant affected by
the change is accounted for.

## Keep the language sharp

- Assign each term to Acquisition/Evidence, Catalog/Resolution, or
  Discovery/Accounts.
- Use **Source Record** for a source-local item and **Event** only for the
  canonical occurrence.
- Use **Claim** for a disputable assertion, **Decision** for a selection, and
  **Projection** for derived current state.
- Keep lifecycle, admission, and publication as independent Event state axes.
- Treat external identifiers, normalized names, and scores as evidence rather
  than canonical identity.

Update the relevant Context immediately when a term changes. Context definitions
describe what a concept is in one or two sentences and contain no implementation
details. Pick one canonical term and list misleading alternatives under Avoid.

## Propagate a model change

Update, in order:

1. Context definition and context-map relationship;
2. logical entities, cardinalities, invariants, and history;
3. pipeline or interface behavior;
4. public/editorial consequences;
5. security, retention, and operational consequences;
6. acceptance scenarios that prove the new behavior.

The change is complete when no document uses the old meaning and at least one
scenario distinguishes the new rule from plausible alternatives.

## Record architecture sparingly

Add an ADR only when the decision is hard to reverse, surprising without
context, and arose from a real trade-off. Keep the ADR short; requirements and
model details remain in their authoritative specifications.

## Review invariants

Before finishing, verify that:

- source disappearance cannot imply cancellation;
- mutable data cannot define a canonical ID;
- Manual Decisions cannot be silently overwritten;
- merge/split and aliases preserve history and public references;
- absent, unknown, unresolved, and inapplicable remain distinct;
- documents remain technology-neutral and self-contained within evts.
