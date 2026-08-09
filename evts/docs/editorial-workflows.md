# Editorial workflows

## Permissions

| Action | User | Editor | Administrator | Operator |
|---|---:|---:|---:|---:|
| Save Events and searches | yes | yes | yes | through an account |
| Review and correct catalog Decisions | no | yes | yes | no |
| Merge, Split, suppress, and restore | no | yes | yes | no |
| Manage accounts and roles | no | no | yes | no |
| Configure installed capabilities and policy | no | no | yes | no |
| Enable or disable Configured Sources | no | no | yes | no |
| Install code, manage secrets/schedules/backups | no | no | no | yes |

Permissions are enforced on every interface, including API-like actions and
background invocations. Hidden navigation is not authorization.

## Review queue

The queue combines identity, field conflict, stale Manual Decision, merge/split,
rights, and publication work. Each row shows:

- entity kind and concise subject label;
- reason for review and best suggestion;
- risk/public-impact level;
- number of affected public fields and relationships;
- age, source, policy, and assignment;
- quick accept, reject, or open-detail action when safe.

Default ordering is public impact, risk, then oldest first. Editors can filter by
task kind, entity kind, source, Geographic Area, age, assignee, and policy
version. Empty, loading, partial-failure, and permission states are explicit.

## Quick resolution

The common case requires one focused suggestion and one Approve action, usable
with keyboard or pointer. Quick resolution is available only when:

- the action and downstream impact fit on the queue row or compact preview;
- no active Manual Decision would be superseded;
- no merge, split, suppression, rights conflict, or multi-entity ambiguity is
  involved;
- the effective policy permits that Decision kind.

Success advances focus predictably to the next task and offers Undo. The audit
record is identical in quality to a detail-page Decision.

## Detailed resolution

The detail view presents:

1. current public Projection and relevant history;
2. source-native evidence and Claims, grouped by source and time;
3. candidates with supporting and contradictory evidence;
4. effective policy and human-readable rationale;
5. field and relationship diff;
6. downstream Publications, Saved Events, feeds, and review tasks affected;
7. select, reject, manual Claim, defer, suppress, merge, split, and undo actions
   allowed for this task.

Consequential actions require a concise reason. Raw evidence access is separately
authorized and clearly distinguished from publication-safe content.

## Manual correction

An Editor:

1. enters a typed manual Claim with optional language/validity;
2. sees validation and the proposed Decision;
3. previews downstream changes;
4. supplies a reason;
5. applies atomically or receives no change.

New evidence can flag the Decision stale and explain why. It remains active
until the Editor supersedes or undoes it.

## Merge and split

Merge requires survivor selection and a preview of:

- conflicting selected values;
- moved source links, Participants, Venues, Series membership, and Event
  relationships;
- URL redirects;
- Saved Events, Saved Searches, and feeds;
- review tasks and policy effects.

Split starts from a prior Merge, proposes restoration, and highlights anything
that became ambiguous afterward. Both operations are resumable and leave public
URLs resolvable throughout.

## Publication controls

Editors can suppress or restore an entity with reason and optional validity.
Suppression removes it from ordinary discovery and public APIs while preserving
evidence, Decisions, and an appropriate public response for previously published
URLs. It is distinct from cancellation and archive.

Rights review can publish structured facts while withholding one Content Item
or Link. It does not require suppressing the Event.

## Configured Sources and policy

Administrators can:

- create or update Configured Source settings for an installed Connector;
- test validation without persisting source observations;
- enable or disable the source;
- inspect Import Runs, checkpoints, safe diagnostics, and effective policy;
- request a bounded run or replay through the Operator-provided execution
  mechanism;
- configure versioned catalog, capability, entity/field, Geographic Area, and
  source policy layers;
- preview changed automatic Decisions and review volume before activating
  policy.

Scheduling, Plugin installation, raw secrets, backup, and deployment controls
remain Operator responsibilities.

## Accounts

Administrators can activate/deactivate accounts, assign Editor or Administrator
roles, inspect security-relevant audit entries, and change the registration
enabled setting. The one-time first-Administrator flow appears only while the
account count is zero and closes atomically on success.

Account deletion removes or anonymizes personal data according to governance
policy without attributing past catalog Decisions to another person. A durable
non-personal actor tombstone may remain.

## Audit

Searchable audit records cover authentication and role changes, source and
policy configuration, every Decision, replay, publication, and raw-evidence
access. Audit views never reveal credentials or unnecessarily reproduce
restricted payloads.
