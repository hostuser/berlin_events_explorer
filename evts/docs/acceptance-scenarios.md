# Acceptance scenarios

These scenarios are the requirements gate. A specification or implementation is
incomplete while any expected behavior is undefined, contradicted elsewhere, or
unverifiable.

## Acquisition and source lifecycle

### ACQ-001 — Same occurrence, several sources

Two Configured Sources publish differently worded records for the same concert.
Both immutable source histories remain. Resolution produces one Event with two
supporting source relationships and one stable public identity.

### ACQ-002 — Complete snapshot absence

A previously observed Source Record is absent from a succeeded complete
snapshot. It becomes Unlisted for that source. The Event remains published and
is not marked cancelled.

### ACQ-003 — Partial and failed runs

A paginated import stops early, or record enumeration becomes unreliable. The
run ends partial or failed. No unseen Source Record becomes Unlisted.

### ACQ-004 — Invalid known record

A snapshot contains a known source key with malformed new content. The record
counts as observed, diagnostics are retained, and its last valid Claims continue
until corrected evidence arrives.

### ACQ-005 — Explicit cancellation

One source explicitly marks a record cancelled while another still lists it.
The cancellation becomes a Claim. Effective policy selects or reviews lifecycle
state without conflating listing presence with cancellation.

### ACQ-006 — Stable retry

The same run batch is retried after interruption. It creates no duplicate Source
Record Versions, Claims, Decisions, review tasks, or first-publication times.

## Identity and chronology

### ID-001 — Reschedule and Venue change

Evidence connects an occurrence moved to a new date and Venue. The Event keeps
its ID, schedule/location history remains inspectable, public feeds update, and
Saved Events still point to it.

### ID-002 — Replacement occurrence

A cancelled Event is replaced by a newly scheduled occurrence that sources
identify as a replacement rather than a reschedule. The replacement receives a
new ID and typed relation; both pages remain available.

### ID-003 — Recurring Series

Three weekly occurrences belong to one Event Series. Cancelling one does not
affect the other Events or Series identity.

### ID-004 — Overnight, multi-day, and unknown end

The model distinguishes an overnight timed Event, a multi-day date-range Event,
a known single-day Event, and an Event whose end is unknown. No missing value is
silently converted to midnight or same-day.

### ID-005 — DST ambiguity

A source supplies a local time during a timezone transition without enough
evidence to resolve an Instant. The local Claim is preserved and review or
reduced precision occurs; the system does not guess an offset.

### ID-006 — Entity continuity

A Venue relocates and rebrands, and a Participant changes name. Evidence of
real-world continuity preserves each ID while names, address, and validity
history change.

## Resolution and review

### REV-001 — Quick suggestion

One safe Venue suggestion is unambiguous. An Editor approves it from the queue
with one action, receives confirmation/Undo, and the full Decision audit and
dependencies are recorded.

### REV-002 — Ambiguous Event identity

One Source Record plausibly matches two Events. It is not published as a
duplicate and is not auto-linked. Review shows both candidates, contradictions,
policy rationale, and public impact.

### REV-003 — Manual Decision becomes stale

New source evidence materially contradicts a Manual Decision. The Decision
remains effective, a stale review task explains the changed dependencies, and
automation cannot replace it.

### REV-004 — Manual correction and replay

An Editor enters a corrected Participant Claim, previews affected Event pages
and feeds, supplies a reason, and applies it. Only dependency descendants
recompute.

### REV-005 — Published merge and Split

Two published Events are merged into a survivor. The retired URL redirects and
bookmarks resolve. Later evidence proves they were distinct; Split restores
identities and relationships without losing history or silently misassigning
ambiguous bookmarks.

### REV-006 — Plugin or policy upgrade

A new Resolver release or policy version changes proposed Decisions. A dry-run
reports changed Claims, automatic Decisions, review volume, and public diffs.
Activation reprocesses only affected descendants and remains reproducible.

## Publication and discovery

### PUB-001 — Minimum publishable Event

An unambiguous source supplies title, date, Venue-TBA location mode, and evidence
but no Participants or end time. The Event publishes with explicit unknowns.

### PUB-002 — Unresolved labels

A valid Event has unresolved Venue and Participant Claims. Their source wording
appears as plain text and does not link to guessed canonical entities.

### PUB-003 — First publication

An Event was observed Monday, created after review Tuesday, and first published
Wednesday. Public “Added” and newly-added search use Wednesday; internal
lineage retains all three Instants.

### PUB-004 — Archive states

Past, cancelled, replaced, merged, and suppressed Events leave upcoming results
appropriately. Past/cancelled/replaced/merged URLs remain informative or
redirect; suppression reveals no restricted fields.

### PUB-005 — Rights revocation

A description loses publication permission. It disappears from pages, API, and
feeds after invalidation while structured Event facts remain published and the
redaction action remains auditable.

### PUB-006 — Ticket freshness

A ticket offer expires or becomes stale. Its old availability is not presented
as current, and Event lifecycle does not change.

### PUB-007 — Localization

An original Turkish title and provenance-backed German translation coexist.
The selected UI locale chooses appropriate chrome and variant while the API
declares language and preserves original content.

### PUB-008 — API and feeds

Equivalent public filters yield stable paginated resources and calendar items.
A reschedule updates the existing item ID; cancellation/replacement is explicit.
Raw evidence and review data never appear.

## Accounts and authorization

### ACC-001 — First Administrator

With zero accounts, two concurrent bootstrap attempts occur. Exactly one creates
the first Administrator and permanently closes bootstrap.

### ACC-002 — Registration policy

Open registration supports verification and recovery. Disabling registration
blocks new ordinary accounts without affecting existing sign-in or the already
closed bootstrap.

### ACC-003 — Private discovery data

Saved Events, Saved Searches, and Feed Credentials are visible only to their
owner and authorized system processes. A credential can be rotated and revoked
without changing the Saved Search.

### ACC-004 — Role enforcement

A User cannot access editorial data through hidden routes or direct requests. An
Editor cannot manage roles, sources, policy, or plugin configuration unless also
an Administrator.

### ACC-005 — Account deletion

Deleting an account revokes sessions/feeds and removes or anonymizes personal
data. Historical catalog Decisions retain only a non-personal actor tombstone
when required for integrity.

## Security and operations

### OPS-001 — Secret safety

A Connector fails and emits verbose diagnostics. Credentials and secret values
do not appear in records, logs, evidence, UI, or audit.

### OPS-002 — Untrusted content

A source description contains active markup and instruction-like text, and a
URL redirects to a private address. Content renders inertly, cannot steer tools,
and the unsafe URL is not published or fetched outside policy.

### OPS-003 — Concurrent work

Two different sources import concurrently while a replay runs. Same-scope
overlap is prevented, independent work progresses, and Decisions/Projections
remain internally consistent.

### OPS-004 — Restore

A backup is restored into an isolated environment. Source/evidence lineage,
active Decisions, aliases, Publications, accounts, and audit reconcile with no
dangling dependencies.

### OPS-005 — Legal redaction

One native payload must be removed despite indefinite default retention. It is
replaced by a permitted tombstone, derivative content invalidates, and the audit
does not retain the prohibited payload.

## Design and accessibility

### UI-001 — Responsive Fahrplan

Listings, every detail type, account flows, review queue/detail, and source
configuration are usable at 360, 768, and 1280 CSS pixels in light and dark
themes with the date-led Fahrplan hierarchy intact.

### UI-002 — Keyboard and assistive technology

Search, pagination, registration, quick approval, detailed correction, merge,
and Split complete keyboard-only with visible focus, correct semantics, stable
focus after updates, and appropriately scoped announcements.

### UI-003 — Designed states

Every primary surface has purposeful loading, empty, zero-result, partial,
stale, error, permission, and success/Undo behavior. Meaning never depends on
color, motion, or icon alone.

## Documentation gate

Before technology selection:

- every capitalized domain term used normatively is defined in its Context;
- entity fields, cardinalities, state axes, and invariants cover every scenario;
- Plugin inputs, outputs, failures, permissions, and version behavior are
  explicit;
- requirements and scenarios contain no unresolved high-impact TODO;
- internal links resolve and the README reading order is complete;
- mirrored skills are byte-identical and validate;
- no normative document or skill depends on code or documentation outside
  evts;
- a human review signs off Acquisition/Evidence, Catalog/Resolution,
  Discovery/Accounts, security/governance, public UX, and editorial UX.
