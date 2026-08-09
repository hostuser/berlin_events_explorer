# Pipeline and resolution

## Governing rule

The pipeline moves from observations to evidence to decisions to projections.
No stage may collapse those layers by writing a source or plugin value directly
into canonical state.

## End-to-end flow

1. **Open an Import Run.** Verify that the Configured Source is enabled, resolve
   its non-secret configuration and secret handles, pin Connector and policy
   versions, and declare run semantics and scope.
2. **Observe records.** The Connector emits stable source keys and native record
   payloads. Validate envelopes before accepting immutable Source Record
   Versions and run membership.
3. **Close source observation.** Record the exact outcome and checkpoint. Infer
   Unlisted only after a succeeded complete snapshot whose covered source keys
   were reliably enumerated.
4. **Extract and normalize Claims.** Run applicable capabilities against new or
   invalidated versions. Preserve source wording alongside typed Claims and
   diagnostics.
5. **Resolve Event identity.** Compare supported identity features with existing
   Events. Resolve an unambiguous match, create an unambiguous new Event, or
   create a Review Task. A source-derived key is never an Event ID.
6. **Resolve relationships and fields.** Resolve Venue, Geographic Area,
   Participant, Event Series, classification, schedule, state, content, Links,
   and offers through type-specific policy. Unresolved Venue and Participant
   wording may remain displayable Claims.
7. **Enrich selectively.** Run bounded Enrichers for missing, stale, or
   explicitly requested knowledge. Their outputs re-enter the Claim and
   resolution flow.
8. **Materialize a Projection Revision.** Apply all active Decisions,
   invariants, rights checks, and dependencies. Invalid projections create
   review or diagnostics; they are not published.
9. **Publish.** Publish a revision only when the minimum publication contract is
   satisfied. Record first publication separately from later updates.

Every stage is resumable and idempotent for the same inputs and versions.

## Import safety

- The source key must be stable within one Configured Source. A suspected reuse
  for different content creates review and preserves both histories.
- Identical content can reuse an existing Source Record Version while still
  recording observation in the current run.
- A malformed record whose key is known still counts as observed. Its last good
  projection remains until new valid evidence changes it.
- If a Connector cannot reliably enumerate all keys in a claimed snapshot, the
  run must end partial or failed and cannot infer Unlisted.
- Delta runs express explicit additions, changes, or removals. A removal means
  source-local Unlisted unless the record also carries an explicit lifecycle
  Claim.
- Network, credential, parsing, or storage errors never imply cancellation.
- Retries must not duplicate versions, Claims, Decisions, review tasks, or
  publication timestamps.

“Previously encountered” is derived from Source Record first/last observation
and run membership; it is not accepted as an authoritative boolean Claim.

## Resolution policies

Policy is layered in this order, with the most specific valid layer winning:

1. catalog default;
2. capability;
3. entity kind or field;
4. Geographic Area;
5. Configured Source.

An effective policy is immutable once used and has a digest/version recorded by
every automatic Decision. Invalid combinations fail validation before a run.

Each Resolver defines:

- candidate generation and blocking rules;
- required and contradictory evidence;
- capability-local confidence meaning;
- safe auto-resolution conditions;
- ambiguity and abstention conditions;
- source authority and freshness rules per field;
- tie behavior;
- material-change and staleness rules.

Policies may use confidence, but a numeric score alone cannot resolve a conflict
between unrelated capabilities. Exact external identity can be strong evidence
without becoming canonical identity.

## Event continuity

Identity resolution evaluates continuity separately from field selection.

- A title correction, Venue change, postponement, rescheduling, or cancellation
  can retain Event identity when a source or Editor explicitly connects the
  occurrence.
- Similar title, date, and Venue data can propose a match but cannot prove
  continuity in an ambiguous set.
- A replacement occurrence receives a new Event and a typed replaces/replaced-by
  relationship.
- Recurring occurrences are separate Events. Event Series membership does not
  merge them.
- Conflicting sources can support competing schedule or lifecycle Claims while
  still resolving to the same Event.

## Entity resolution

Venue, Participant, Geographic Area, and Event Series resolution follows the
same evidence/decision shape but uses type-specific policies. Normalize strings
for candidate search, not identity. Preserve:

- original and localized names;
- aliases and effective dates;
- geographic context;
- external identifiers and evidence URIs;
- negative Decisions and rejected candidates;
- continuity through rename, relocation, or rebranding where evidenced.

## Manual decisions

A Manual Decision:

- records the Editor, reason, evidence, selected or entered Claim, and impact;
- outranks automatic policy while active;
- may be marked stale by materially changed dependencies;
- remains effective until explicitly superseded or undone;
- triggers a dry-run downstream diff before consequential application;
- never mutates or deletes the Decision it replaces.

Manual entry creates a manual Claim first and selects it second.

## Merge and split

Merging published entities:

1. preview moved relationships, selected fields, conflicting Decisions, public
   URLs, bookmarks, feeds, and review tasks;
2. select a survivor and record a Merge Decision;
3. create a permanent Alias from every retired ID;
4. recompute affected projections and public redirects;
5. retain all original evidence and revisions.

Splitting or undoing a Merge uses the stored impact and dependencies to restore
identity and relationships. If an automated restoration is ambiguous, it
creates targeted review work instead of guessing.

## Invalidation and replay

Dependency Edges include Source Record Versions, Claims, effective policy,
Capability releases, Decisions, Projection Revisions, and Publications.

A change:

1. computes descendants without mutating them;
2. classifies public and editorial impact;
3. produces a deterministic dry-run diff;
4. invalidates affected outputs;
5. recomputes in dependency order with checkpoints;
6. records success, abstention, review creation, or failure per subject.

Unrelated entities are untouched. Replaying unchanged inputs with identical
versions produces equivalent Claims, Decisions, and public-field digests.

## Publication rules

Publish a new Event when:

- identity is unambiguous;
- title is nonblank;
- start is known to at least day precision;
- location mode is explicit;
- at least one active supporting source exists;
- no suppression Decision applies;
- selected public content passes rights and safety checks.

Do not unpublish solely because a source is Unlisted. A previously published
postponed Event can remain public with schedule-to-be-announced while retaining
its last announced schedule as history. Past and cancelled Events move out of
upcoming results but remain archived. A corrected publication keeps its
first-published Instant.
