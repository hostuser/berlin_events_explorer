# Plugin contracts

Plugins are trusted code installed and upgraded by an Operator. The core owns
configuration, evidence persistence, policy, review, decisions, projections,
authorization, and publication.

## Manifest

Every immutable Plugin Release declares:

- unique plugin key, semantic version, and package digest;
- supported core contract range;
- one or more uniquely keyed Capability descriptors;
- configuration schema with secret fields identified;
- requested permissions: network destinations, secret handles, filesystem or
  subprocess access, and data classes;
- deterministic/idempotent guarantees and known external side effects;
- supported languages, entity/Claim types, and run semantics;
- migration or compatibility notes for its own configuration;
- publisher and integrity metadata.

Installation fails closed on an incompatible manifest or unapproved permission.
An Administrator can configure and enable installed capabilities but cannot
install executable code.

## Common execution envelope

Every invocation receives:

- invocation ID and bounded work scope;
- exact Plugin Release and Capability version;
- effective non-secret configuration and opaque secret handles;
- effective policy version where applicable;
- input IDs and immutable revisions, not mutable live objects;
- deadline, cancellation, retry, and resource-limit context;
- dry-run flag when the capability can produce external side effects.

Every result returns:

- invocation ID and capability version;
- typed outputs with stable idempotency keys;
- Evidence References and rationale;
- structured diagnostics with severity and safe context;
- counters, checkpoint, and terminal outcome;
- declared external requests or side effects.

Credentials, private payloads, and unredacted secrets never appear in diagnostics
or evidence. Unknown fields and unsupported contract versions fail explicitly.

## Connector

A Connector observes one Configured Source.

### Input

- Configured Source ID and current configuration revision;
- secret handles;
- requested run semantics and scope;
- previous checkpoint and conditional retrieval metadata;
- bounded execution controls.

### Output

- Source Record envelopes containing stable source key, native payload, content
  type, observed Instant, optional native revision/updated value, and public
  evidence URI;
- optional typed source Claims whose meaning depends on source-specific
  semantics, including explicit cancellation;
- per-record validation diagnostics;
- final checkpoint and completion declaration confirming actual run semantics
  and covered scope.

A Connector must not emit Canonical Entity IDs or canonical Projections. It must
document source-key stability, pagination, deletion semantics, rate limits,
licensing, and whether identical observations need distinct versions.

## Extractor/Normalizer

An Extractor/Normalizer turns native or previously derived values into typed
Claims.

### Input

- Source Record Version or Claim IDs;
- immutable values referenced by those IDs;
- relevant source and Geographic Area context;
- requested Claim types.

### Output

- typed Claims with source wording, normalized value, language, validity,
  capability-local confidence, rationale, and evidence;
- abstentions and non-fatal diagnostics.

Normalization makes candidate search reliable; it never establishes canonical
identity. A capability may operate on a group of fields when their interpretation
depends on context.

## Resolver

A Resolver proposes Decisions for one domain boundary.

### Input

- subject and current Projection Revision;
- relevant active Claims, candidates, identifiers, negative Decisions, and
  nearby Canonical Entities;
- effective immutable Resolution Policy;
- exact dependency revisions.

### Output

- one or more proposals containing proposed Decision kind and content,
  alternatives, supporting and contradictory evidence, rationale, impact,
  capability-local confidence where meaningful, and outcome:
  auto-resolve, review, or abstain.

The core validates and records Decisions. A Resolver never writes a Projection
or silently replaces a Manual Decision.

## Enricher

An Enricher obtains additional evidence about a Canonical Entity.

### Input

- Canonical Entity ID and Projection Revision;
- allowed contextual Claims;
- missing or stale knowledge request;
- freshness target and bounded execution controls.

### Output

- Claims and Candidates with evidence URI, retrieval Instant, validity or
  expiry, rights/attribution metadata, and diagnostics;
- explicit no-result or abstention.

Enrichers never own canonical fields. Runs are bounded, rate-aware, resumable,
and safe to retry. Any external mutation must be separately declared and is out
of scope for first-release catalog Enrichers.

## Compatibility and upgrades

- Stored outputs identify the exact producing release forever.
- Installing an upgrade does not rewrite prior outputs.
- Configuration is validated against the selected release before enabling a
  Configured Source or capability.
- A new release may request a dry-run replay to show changed Claims, Decisions,
  review volume, and Publications before activation.
- Rollback selects a prior compatible release; it does not erase evidence made
  by the newer one.
- Contract-breaking Capability changes require a new major version and explicit
  migration/reprocessing plan.

## Required conformance tests

Every Plugin Release supplies contract-level examples for:

- deterministic idempotency keys and safe retry;
- malformed, partial, empty, and duplicate inputs;
- redaction of secrets and restricted source data;
- cancellation and timeout;
- declared run scope and checkpoint behavior;
- evidence completeness and rights metadata;
- version incompatibility;
- dry-run behavior and absence of undeclared side effects.
