# Catalog and Resolution

This context owns stable real-world identities, decisions about evidence, and
the current catalog projection.

## Language

**Event**:
One scheduled real-world occurrence, even when its exact time or physical venue
is not yet known.
_Avoid_: Listing, source event, event instance

**Event Series**:
A stable recurring or branded concept whose members are distinct Events.
_Avoid_: Recurrence, parent event

**Participant**:
A person, group, or organization related to an Event through a role.
_Avoid_: Artist, performer

**Participation**:
The relationship between an Event and a Participant, including role, billing
order, and source wording.
_Avoid_: Performer field

**Venue**:
A real-world named place that hosts Events and has identity independent of one
address or source spelling.
_Avoid_: Location, venue string

**Geographic Area**:
A canonical locality, administrative region, or country used to organize
Venues and Events.
_Avoid_: City string, region string

**Event Location**:
The Event-specific location statement: a Venue, venue-to-be-announced, online,
or hybrid.
_Avoid_: Venue

**Canonical Entity**:
An Event, Event Series, Participant, Venue, or Geographic Area with an immutable
internal identity.
_Avoid_: Database row, matched record

**External Identifier**:
A versioned identifier assigned by another authority. No External Identifier
alone defines canonical identity.
_Avoid_: Canonical ID

**Decision**:
An auditable selection, rejection, identity resolution, merge, split, or
suppression supported by evidence and policy.
_Avoid_: Edit, override

**Manual Decision**:
A Decision made by an Editor. It remains authoritative until explicitly
superseded or undone.
_Avoid_: Hard-coded value, manual override

**Resolution Policy**:
Versioned rules that decide when Claims are selected automatically, rejected,
or sent to review.
_Avoid_: Threshold, plugin priority

**Projection**:
The current derived representation of Canonical Entities after applying active
Decisions.
_Avoid_: Source record, truth table

**Projection Revision**:
One immutable materialization of a Projection and the Decisions and dependencies
that produced it.
_Avoid_: Entity version

**Dependency Edge**:
A recorded relationship from a derived output to an input Claim, Decision,
policy, Capability, or revision it used.
_Avoid_: Processing metadata

**Merge**:
A reversible Decision that identifies two Canonical Entities as one and selects
a surviving identity.
_Avoid_: Deduplication, delete duplicate

**Split**:
A reversible Decision that restores identities or relationships combined by an
incorrect Merge.
_Avoid_: Unmerge

**Alias**:
A retired identity or historical name that continues to resolve to its
surviving Canonical Entity.
_Avoid_: Duplicate

**Lifecycle State**:
An Event's real-world schedule condition, such as scheduled, postponed, or
cancelled.
_Avoid_: Publication status, availability

**Admission State**:
Current knowledge about entry, such as unknown, available, limited, sold out, or
not applicable.
_Avoid_: Event status

**Publication State**:
The catalog's decision to review, publish, suppress, or archive a Projection.
_Avoid_: Event status

**Event Type**:
A stable catalog-managed category in a curated hierarchy used for discovery.
_Avoid_: Source category

**Tag**:
A flexible canonical label that supplements Event Type without defining a
closed taxonomy.
_Avoid_: Event type

**Content Item**:
A provenance- and rights-aware description, image, or other publishable content
associated with a Canonical Entity.
_Avoid_: Raw content

**Ticket Offer**:
Freshness-aware evidence about admission price, availability, sale period, and
public ticket link; it is not inventory or a purchase.
_Avoid_: Ticket, checkout

**Review Task**:
A durable unit of ambiguous, stale, or consequential catalog work presented to
an Editor.
_Avoid_: Error, approval row
