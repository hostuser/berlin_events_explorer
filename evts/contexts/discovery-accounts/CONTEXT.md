# Discovery and Accounts

This context presents catalog projections to the public and owns user-specific
discovery data.

## Language

**Publication**:
The public, versioned presentation of a catalog Projection. Its first creation
defines when an Event was added to the catalog.
_Avoid_: Event creation, first seen

**Listing**:
A summary of a published Event shown in search or chronological results.
_Avoid_: Source record

**Saved Event**:
A private bookmark from a User to a stable Event identity.
_Avoid_: Favorite, subscription

**Saved Search**:
A private, reusable set of catalog search criteria owned by a User.
_Avoid_: Alert, notification

**Feed**:
A revocable, machine-readable view of published Events selected by public or
user-owned search criteria.
_Avoid_: Notification

**Account**:
The authenticated identity, roles, and private settings through which a person
uses evts.
_Avoid_: User profile

**User**:
A person with an account who can save Events and searches.
_Avoid_: Editor, administrator

**Editor**:
A privileged account that reviews evidence and makes catalog Decisions.
_Avoid_: Moderator

**Administrator**:
A privileged account that manages accounts, Configured Sources, installed
Plugins, policy configuration, and operational controls.
_Avoid_: Operator

**Operator**:
A person responsible for deployment, plugin installation, scheduling, secrets,
backups, and runtime health outside ordinary catalog editing.
_Avoid_: Administrator

**Registration Policy**:
The catalog-wide choice that allows or blocks new ordinary Accounts after the
first Administrator exists.
_Avoid_: Signup mode

**Feed Credential**:
A revocable secret granting read access to one private Saved Search feed.
_Avoid_: API key, notification token
