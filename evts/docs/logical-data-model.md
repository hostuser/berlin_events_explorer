# Logical data model

This is a normative, technology-neutral model. Storage implementations may
normalize or project it differently, but must preserve every stated identity,
relationship, invariant, and history.

## Conventions

- **ID** is an opaque immutable identifier. Human-readable slugs are aliases,
  never identity.
- **Instant** is timezone-aware. Audit instants are comparable globally.
- **Local date/time** is paired with an IANA timezone when it describes a
  physical occurrence.
- **Language** uses a standard language tag.
- **URI** is an absolute public or internal resource identifier as appropriate.
- Every immutable item has a creation Instant and creator kind.
- Every selected value can be traced through a Decision to one or more Claims
  and Evidence References.
- Secret values are referenced through secret handles and never copied into
  evidence, logs, diffs, or projections.

## Acquisition and Evidence

### Plugin Release

| Field | Requirement |
|---|---|
| plugin key, version | Together identify immutable installed code |
| manifest digest | Verifies the manifest used by runs |
| capabilities | Versioned Connector, Extractor/Normalizer, Resolver, or Enricher descriptors |
| compatibility range | Supported core contract versions |
| installed at | Audit Instant |

A Plugin Release is immutable. Upgrade installs another release; existing runs
continue to identify the exact release used.

### Configured Source

| Field | Requirement |
|---|---|
| source ID | Stable internal identity |
| name | Editor-facing unique label |
| connector capability | Installed Connector key and compatible version |
| enabled | The only application lifecycle flag |
| scope configuration | Non-secret source/feed parameters |
| credential reference | Optional secret handle |
| policy references | Effective layered policy overrides |
| created/updated audit | Actor and Instants |

Configuration revisions are auditable. Scheduling, dry-run, and retirement are
Operator concerns rather than additional Configured Source states.

### Import Run

| Field | Requirement |
|---|---|
| run ID, source ID | Stable identity and owner |
| run semantics | snapshot, partial, or delta |
| declared scope | Machine-readable coverage boundary |
| capability and policy versions | Exact versions used |
| started/finished at | Instants |
| outcome | running, succeeded, partial, failed, or cancelled |
| checkpoint | Opaque resumability value when supported |
| counters and diagnostics | Seen, changed, invalid, skipped, and error totals |

Only a succeeded snapshot can infer Unlisted within its declared scope. Partial,
failed, cancelled, or validation-rejected runs cannot infer absence.

### Source Record

| Field | Requirement |
|---|---|
| source record ID | Stable internal identity |
| source ID, source key | Unique source-local identity pair |
| first/last observed at | Instants |
| listing state | observed or unlisted |
| current version ID | Latest accepted observation |

A Source Record is not an Event. A source key may not be reused for a different
real-world item without an explicit source-key-reuse diagnostic and review.

### Source Record Version

| Field | Requirement |
|---|---|
| version ID, source record ID, run ID | Lineage |
| observed at | Instant |
| source revision/updated value | Optional native marker |
| content digest and digest algorithm version | Deterministic change detection |
| native payload | Retained source-native content, or a redaction tombstone |
| retrieval metadata | Public evidence URI and non-secret response metadata |

Versions are immutable and unique per Source Record plus content digest unless
the source's semantics require repeated identical observations to be recorded.
Run membership still records every observation.

### Claim

| Field | Requirement |
|---|---|
| claim ID | Stable identity |
| subject | Source Record Version or Canonical Entity |
| claim type and path | Versioned semantic meaning |
| value | Typed value; absent and unknown remain distinct |
| language and validity interval | Optional |
| capability release | Producer |
| confidence and rationale | Optional, capability-local |
| created at | Instant |

Claims are immutable. Corrections produce new Claims and Decisions, not edits.
An Enricher Claim may have a freshness or expiry Instant.

### Evidence Reference

Evidence References form a many-to-many relation from Claims and Decisions to
Source Record Versions, external evidence URIs, prior Decisions, and capability
or policy versions. A reference records retrieval time, permitted retention,
and any rights or attribution metadata.

## Catalog and Resolution

### Canonical Entity

Event, Event Series, Participant, Venue, and Geographic Area share:

| Field | Requirement |
|---|---|
| entity ID and kind | Immutable identity |
| created at | Canonical creation Instant |
| current projection revision | Selected public/editorial view |
| merge status | active or alias of survivor |
| review summary | Derived unresolved/stale/risk counts |

Creation does not imply publication. Canonical entities are never physically
removed merely because source evidence disappears.

### Event

| Field | Requirement |
|---|---|
| event ID | Canonical Entity ID |
| series ID | Optional Event Series membership |
| title selection | Required to publish |
| type selection | Optional curated Event Type |
| schedule | Required for initial publication at day precision or better; may later become to-be-announced |
| location | Required explicit mode |
| lifecycle state | scheduled, postponed, rescheduled, cancelled, or unknown |
| admission state | unknown, available, limited, sold out, not applicable |
| publication state | review, published, suppressed, archived |
| first observed/created/published/updated | Separate Instants |

#### Schedule

| Field | Requirement |
|---|---|
| schedule state | known or to-be-announced |
| start local date | Required when schedule state is known |
| start local time | Optional |
| end local date/time | Optional |
| end semantics | same-start-day, explicit, or unknown |
| timezone | IANA zone when an Instant can be resolved |
| precision | day, date range, or date-time |
| resolved start/end Instants | Derived when unambiguous |

An end date of absent does not mean single-day; end semantics carries that
meaning. End cannot precede start. Overnight and multi-day intervals are valid.
DST ambiguity remains reviewable when source evidence cannot resolve it. A
previously published postponed Event may have schedule state to-be-announced;
its last announced schedule remains in history and is not presented as current.

#### Location

Location mode is one of physical, venue-to-be-announced, online, hybrid, or
cancelled-location. A physical or hybrid location may select one Venue and one
primary Geographic Area. Raw Venue wording remains available when no Venue is
resolved. Online access URIs are rights- and publication-checked Links.
Cancellation does not erase the last-known location from history.

### Event Series

An Event Series has an ID, selected localized names and description, identifiers,
Links, Tags, and ordered or unordered membership relations to Events. Series
membership never supplies an Event's schedule or lifecycle state.

### Event relationships

A typed relationship connects distinct Events for replacement, continuation, or
other catalog-approved semantics and records its supporting Decision. A
reschedule that preserves one Event uses schedule history rather than creating a
self-relationship.

### Participant and Participation

A Participant has a kind of person, group, or organization; localized names and
aliases; external identifiers; Links; and historical attributes.

Participation is unique by Event, Participant, role, and billing position. It
stores a controlled role such as performer, speaker, host, organizer, or sponsor,
optional billing order, source label, and validity. One Participant may hold
several roles.

### Venue and Geographic Area

A Venue has selected localized names, aliases, type, address components,
geographic point, Links, external identifiers, and historical attributes. A
move, rename, or rebrand retains identity when continuity is evidenced.

A Geographic Area has a type such as locality, administrative region, or
country; localized names; geometry or point where available; identifiers; and
typed containment relationships. Containment supports overlap and cannot assume
one strict tree.

### Classification

Event Type is a catalog-managed hierarchy with stable IDs, localized labels,
active state, and parent relations. Tags have stable normalized identity and
localized display labels. Source classifications remain Claims and map to Types
or Tags through Decisions.

### Names, identifiers, links, content, and offers

These reusable records belong to a Canonical Entity and remain provenance-backed:

- **Name Variant**: value, language, kind, validity, selected flag.
- **External Identifier**: authority, identifier, URI, validity.
- **Link**: URI, kind, label, validity, last checked, publication eligibility.
- **Content Item**: text or media reference, language, kind, attribution,
  license/permission, validity, publication eligibility.
- **Ticket Offer**: provider, ticket URI, currency, optional minimum/maximum
  price, free-entry flag, sale window, admission Claim, checked/expiry Instants.

No remote URI, text, image, or offer becomes public solely because it was
observed.

### Decision

| Field | Requirement |
|---|---|
| decision ID and kind | select field, link identity, reject candidate, merge, split, publish, suppress, or undo |
| subject and affected paths/relations | Explicit impact boundary |
| selected/rejected Claims or entities | Decision content |
| actor kind and ID | policy, Editor, or Administrator as permitted |
| policy version | Required for automatic Decisions |
| reason and rationale | Human reason required for consequential manual actions |
| created at | Instant |
| supersedes/undoes | Optional prior Decision |
| state | active, superseded, or undone |

Decisions are immutable. Exactly one active Decision may own a single-valued
projected field. Multi-valued fields define their own uniqueness and ordering.
A Manual Decision outranks automation until explicitly superseded.

### Merge Alias, dependency, and projection revision

- **Merge Alias** maps a retired entity ID and public aliases to one survivor,
  records the Merge Decision, and remains resolvable.
- **Dependency Edge** links an output Claim, Decision, review task, or Projection
  Revision to every input it used.
- **Projection Revision** is an immutable materialization of one Canonical
  Entity, including active Decisions, dependency root, generated Instant, and
  public-field digest.

A Split produces new revisions and redirects without rewriting historical
revisions or Decisions.

### Review Task

A Review Task references the ambiguous or stale subject, candidates, effective
policy, risk and public-impact scores, reason for review, dependencies, created
and due Instants, assignment, and state. Applying a Decision resolves or replaces
the task; the task itself is retained.

## Discovery and Accounts

### Publication

A Publication references one Canonical Entity and Projection Revision and stores
first-published, current-published, updated, and optional withdrawn Instants. Its
public status is published, suppressed, or archived. New revisions do not change
first-published.

### Account and roles

An Account has an ID, normalized verified address, display preferences, active
state, privacy choices, created/updated Instants, and zero or more roles. User,
Editor, and Administrator permissions are additive. Credential representation
is selected later but must support verification, recovery, revocation, export,
and deletion.

Registration Policy has an enabled flag. When no Account exists, one
first-Administrator bootstrap may succeed atomically; it is permanently closed
after the first Account is created.

### Saved Event, Saved Search, and Feed Credential

- Saved Event is unique by Account and Event and stores creation Instant.
- Saved Search stores an owner, versioned normalized query, display name,
  creation/update Instants, and optional feed-enabled flag.
- Feed Credential stores only a verifier/digest, owner, Saved Search or public
  query reference, creation/last-used/revoked Instants, and optional expiry.

Saved objects remain private. Merged Event IDs resolve through aliases; a Split
that makes a bookmark ambiguous creates private review guidance rather than
silently choosing.

## Required indexes and access paths

Any storage design must efficiently support:

- source ID plus source key; record plus digest; run plus outcome/scope;
- active Claims and Decisions by subject, type/path, producer, and freshness;
- dependency traversal in both directions;
- review tasks by state, priority, age, entity kind, and assignee;
- Event interval overlap, first-publication time, lifecycle, admission, and
  publication state;
- text search across selected localized titles, names, aliases, Venue, and
  Participants;
- Geographic Area containment and point/geometry filtering;
- external identifier lookup and alias redirect resolution;
- Saved Events and Saved Searches by Account;
- stable cursor pagination for every public collection.
