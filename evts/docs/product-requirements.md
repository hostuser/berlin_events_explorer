# Product requirements

## Purpose

evts turns incomplete, inconsistent, and overlapping source data into a useful
public catalog of scheduled events. It must preserve what each source said,
explain how canonical entities were selected, let Editors correct decisions,
and safely propagate corrections.

The product is generic across scheduled-event domains. The first vertical is
live and music events, so Participants and Venues are prominent without being
mandatory for every Event.

## Catalog shape

- **PR-001** One installation owns one editorial catalog covering one or many
  cities and regions.
- **PR-002** Multi-tenancy and federation are outside the first release.
- **PR-003** The design target is hundreds of Configured Sources, millions of
  historical Events, tens of millions of evidence records, concurrent imports,
  and hundreds of active users.
- **PR-004** A new implementation must need no source code, schema, or
  documentation outside this directory to understand the product.
- **PR-005** Technology selection begins after the requirements gate; these
  documents choose no language, framework, database, or deployment product.

## Actors

- **Visitor** browses public listings, detail pages, archives, APIs, and feeds.
- **User** also owns Saved Events and Saved Searches.
- **Editor** resolves review work and corrects catalog data.
- **Administrator** manages accounts, Configured Sources, installed Plugin
  configuration, layered policy, and application controls.
- **Operator** installs code, manages secrets and schedules, deploys the system,
  and owns backup and runtime health.
- **Plugin Developer** implements versioned capabilities against the contracts.

## Catalog construction

- **PR-010** A Configured Source can be enabled or disabled. Several sources may
  use the same Connector.
- **PR-011** Every Import Run declares its scope and snapshot, partial, or delta
  semantics before processing.
- **PR-012** Native Source Record Versions, hashes, run membership, and lineage
  are retained. A changed record creates a new version.
- **PR-013** Claims, Decisions, and Projections remain distinct and traceable.
- **PR-014** A complete successful snapshot may mark absent Source Records
  Unlisted. Absence alone never cancels or deletes an Event.
- **PR-015** Explicit source cancellation is a Claim evaluated with other
  evidence.
- **PR-016** Automatic resolution uses domain-specific, versioned policies.
  Scores from unrelated capabilities are not globally ranked.
- **PR-017** Only unambiguous policy outcomes resolve automatically. Ambiguous
  identity, merge, or material conflict creates review work.
- **PR-018** Manual Decisions remain active until an Editor explicitly
  supersedes or undoes them. New evidence may mark them stale, but cannot
  overwrite them.
- **PR-019** Changes invalidate a versioned dependency graph and can be previewed
  and deterministically recomputed without rebuilding unrelated data.

## Canonical catalog

- **PR-020** An Event represents one real-world occurrence and has an immutable
  opaque identity independent of source, title, date, Venue, or Participant.
- **PR-021** Many Source Records may support one Event.
- **PR-022** An Event may belong to an Event Series, but each occurrence remains
  independently scheduled, resolved, published, cancelled, and bookmarked.
- **PR-023** Event continuity may survive correction, postponement,
  rescheduling, cancellation, or Venue change when evidence identifies the same
  occurrence. A replacement or genuinely new occurrence receives a new ID and
  an explicit relationship.
- **PR-024** Published duplicate entities merge into one survivor with stable
  redirects, complete history, and an audited Split or undo path.
- **PR-025** Participants are people, groups, or organizations related through
  roles. Venue and Geographic Area are separate canonical concepts.
- **PR-026** Canonical entities retain aliases, localized names, historical
  attributes, and multiple external identifiers without making any external
  authority canonical.
- **PR-027** Curated hierarchical Event Types support stable filtering. Tags add
  flexible classification. Source categories remain Claims mapped through
  policy.

## Event publication

- **PR-030** A newly publishable Event has a nonblank title, at least day-level
  start knowledge, an explicit location mode, one supporting source, and no
  active suppression Decision. A previously published Event may retain its page
  with schedule-to-be-announced after postponement.
- **PR-031** Unambiguous Events publish promptly. Ambiguous Event identity waits
  for review.
- **PR-032** Unresolved Venue or Participant wording may appear as a source label
  without a canonical link.
- **PR-033** Lifecycle, admission, and publication are independent state axes
  with provenance and history.
- **PR-034** Past, cancelled, replaced, and merged public URLs remain available
  and clearly labeled.
- **PR-035** First public publication defines “added to the catalog.” First
  observation, canonical creation, later update, and last observation are
  separate timestamps.
- **PR-036** Original-language content is preserved. Localized variants are
  optional, provenance-backed, and never fabricated as source text.
- **PR-037** Descriptions and media publish only when their rights and
  attribution data permit it.
- **PR-038** Ticket information is evidence-backed and freshness-aware. evts
  never reserves, sells, or purchases admission.

## Public product and accounts

- **PR-040** Visitors can browse upcoming and past listings and search by text,
  schedule, first-publication date, Geographic Area, Event Type, Venue, and
  Participant.
- **PR-041** Events, Event Series, Venues, Participants, and Geographic Areas
  have stable detail resources when publishable.
- **PR-042** A versioned public read API and calendar/feed output expose only
  publication-safe fields and stable identities.
- **PR-043** Users can privately save Events and Saved Searches. Outbound
  notifications are deferred.
- **PR-044** Self-registration is enabled by default and can be disabled.
- **PR-045** An installation with no accounts allows one first Administrator to
  be created exactly once. Normal registration policy applies afterward.
- **PR-046** Accounts support address ownership verification, recovery, privacy
  preferences, data export, and deletion.

## Editorial product

- **PR-050** Review queues are prioritized by ambiguity, public impact, age, and
  policy-defined risk.
- **PR-051** The common action is quick keyboard or pointer selection of a
  suggestion.
- **PR-052** Review shows evidence, alternatives, policy rationale, affected
  fields and relationships, and a downstream diff before a material Decision.
- **PR-053** Editors can select, reject, enter a manual Claim, merge, split,
  suppress, undo, and explicitly supersede prior Decisions.
- **PR-054** Consequential Decisions require a reason and record actor, time,
  evidence, policy and capability versions, previous Decision, and impact.
- **PR-055** Direct canonical editing is expressed as manual Claims and
  Decisions; it never bypasses provenance.

## Explicitly deferred

- Technology and deployment-product choices
- Multi-tenant catalogs and federation
- Untrusted or Administrator-uploaded executable plugins
- In-product plugin package discovery or installation
- Notifications and messaging delivery
- Ticket checkout, inventory, seating, or payment
- Social features, comments, and public user profiles
