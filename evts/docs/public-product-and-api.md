# Public product and API

## Public information architecture

Primary destinations:

- upcoming Events;
- newly added Events;
- past and cancelled archive;
- Event Series;
- Venues;
- Participants;
- Geographic Areas;
- Saved Events and Saved Searches for signed-in Users.

Search state is shareable through a stable public query representation. Personal
Saved Searches remain private unless accessed through a revocable Feed
Credential.

## Event discovery

Listings support:

- full-text query across selected Event title, aliases, Venue, Participants, and
  Series;
- interval-overlap date filtering, including Events already in progress;
- first-publication interval filtering and newest-added sort;
- Geographic Area and descendant-area filtering;
- Event Type and Tag;
- Venue, Participant, Event Series, lifecycle, and admission state;
- upcoming, past, cancelled, and all archive views;
- stable sort by start, first publication, or relevance;
- stable cursor pagination.

All filters combine predictably and are represented in the URL or equivalent
shareable state. Empty results retain the active criteria and offer a clear
reset.

## Detail resources

### Event

Show selected title and language, schedule or schedule-to-be-announced with
precision and timezone, lifecycle and admission labels, location, Participants
and roles, Event Type and Tags, Series, rights-approved description/media,
evidence-backed Links and Ticket Offers, first-publication date, last meaningful
update, and related replacement/reschedule history.

Unresolved source labels are visibly plain text rather than links. Cancellation,
postponement, unknown time, Venue TBA, online, hybrid, and stale admission data
use explicit wording.

### Event Series

Show selected identity/content and independently paginated past and upcoming
member Events. Series state never substitutes for occurrence state.

### Venue, Participant, and Geographic Area

Show selected localized identity, aliases where useful, rights-approved
metadata, relevant external Links, and paginated associated Events. Historical
names or addresses appear only when useful and non-misleading.

## Stable URLs and redirects

- Public resources use opaque or immutable canonical identity, optionally with a
  non-authoritative readable slug.
- A slug change cannot break identity.
- Merge Aliases redirect permanently to the survivor.
- A replaced Event remains available and links to its replacement.
- Suppressed resources return a policy-appropriate response without leaking
  restricted data.
- Deleted personal resources and legally removed content use explicit gone or
  redacted responses rather than reassignment.

## Public read API

The first stable contract is versioned and read-only. Its concrete transport is
selected later; an HTTP implementation should expose equivalent resources:

- events collection and Event detail;
- Event Series collection and detail;
- Venues, Participants, and Geographic Areas;
- Event Types and Tags;
- public search metadata needed to build filters;
- alias/redirect resolution.

Collection inputs mirror public search. Responses include:

- canonical ID, resource kind, and stable resource URI;
- current publication revision or entity version token;
- selected publication-safe fields;
- explicit schedule precision and location/state values;
- first-published and updated Instants;
- pagination links/cursors;
- rights-required attribution;
- typed related-resource links.

Responses exclude raw evidence, private Claims, confidence, internal review
state, private source configuration, personal data, and suppressed content.
Unknown and absent values are distinguishable. Clients can perform conditional
retrieval and receive consistent errors and rate-limit metadata.

Breaking changes require a new API version. Additive fields must not change the
meaning of existing values.

## Feeds

Calendar and syndication feeds represent a public query or Saved Search and:

- use stable Event IDs as item identity;
- include schedule precision rather than inventing a time;
- update an item when an Event is rescheduled, cancelled, replaced, or corrected;
- retain cancellation/replacement signals long enough for subscribers to
  reconcile;
- include a canonical public Event URI and required attribution;
- omit restricted or expired Content Items and Ticket Offers;
- support conditional retrieval and bounded result windows.

Private Saved Search feeds use revocable, unguessable credentials. Credentials
are never embedded in public page markup, referrers, logs, or analytics.

## Accounts

Self-registration requires address ownership verification. A User can:

- sign in and recover access;
- save or remove an Event;
- create, rename, edit, or delete a Saved Search;
- enable, rotate, or revoke a Saved Search feed;
- export personal data;
- delete the account.

Saved Events and Saved Searches are private. Notifications, social activity, and
public profiles are not implied.

## Localization and time

- Interface language and content language are independent.
- Original content and selected translations declare language.
- Users see localized dates and numbers while machine interfaces use stable
  standard representations.
- Event schedule is shown in the Event's timezone; an optional user-zone
  rendering is secondary and labeled.
- Date-only and uncertain times never acquire a synthetic midnight.

## Search and page quality

Public pages are indexable where rights and publication state allow, provide
canonical metadata, avoid duplicate URLs for equivalent filters, and meet the
accessibility requirements in the design language. Search and detail rendering
must remain useful without client-side scripting.
