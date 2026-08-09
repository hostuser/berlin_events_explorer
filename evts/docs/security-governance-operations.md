# Security, governance, and operations

## Security boundaries

- Visitors and Users can access only published, publication-safe projections.
- Editors can access review evidence needed for assigned catalog work.
- Administrators manage application configuration but do not receive raw
  deployment secrets merely through that role.
- Operators control Plugin installation, secret stores, schedules, deployment,
  backups, and emergency recovery.
- Plugin code is trusted only after Operator installation and permission review.
  Source payloads, remote content, and Plugin outputs remain untrusted data.

All interfaces enforce authorization server-side and record security-relevant
actions. Least privilege applies to accounts, capabilities, workers, and data
access.

## Accounts and sessions

Requirements:

- verified address ownership before ordinary account use;
- rate-limited registration, verification, recovery, and sign-in;
- secure password or external-credential storage selected during technology
  design;
- revocable sessions and feed credentials;
- protection against cross-site request forgery, session fixation, enumeration,
  and credential stuffing;
- prompt effect for account deactivation and role removal;
- step-up confirmation for role changes, source/policy changes, and destructive
  Decisions;
- atomic one-time first-Administrator bootstrap when account count is zero.

Registration can be disabled without disabling existing accounts.

## Secrets and plugin permissions

- Secrets use opaque handles and a dedicated secret-management boundary.
- Secret values never enter Source Record payloads, Evidence References,
  Claims, diagnostics, audit, dry-run diffs, URLs, or feed credentials.
- Plugin manifests declare network destinations and sensitive capabilities.
- Runtime enforcement must be at least as restrictive as the approved manifest.
- Configuration display returns redacted presence and revision, not a secret.
- Secret rotation does not rewrite historical runs; runs identify the
  non-secret configuration and secret revision reference used.

## Untrusted data

Treat source text, descriptions, media, URLs, external search results, and model
outputs as untrusted.

- Escape content for its output context.
- Validate public URIs and block unsafe schemes, credentials, private-network
  targets where inappropriate, and redirect-based policy bypass.
- Isolate active media and never execute source-provided markup or scripts.
- Do not let imported text become instructions to automated tools.
- Bound payload size, nesting, decompression, redirects, pagination, and
  external requests.
- Preserve source text without granting it publication eligibility.

## Evidence retention and privacy

Raw Source Record Versions are retained indefinitely by default to maximize
reproducibility. This default requires:

- encryption in transit and at rest;
- access logging and separately authorized raw-payload access;
- source-specific classification of personal, sensitive, licensed, and public
  data;
- minimization of fetched data to what the catalog purpose requires;
- documented legal basis and source terms before enabling a Configured Source;
- export, deletion, and incident-response procedures.

If law, rights, or source terms require removal, replace native content with a
redaction tombstone containing only permitted digest, source/run identity,
redaction authority, reason category, and Instant. Derived Claims and public
content that reproduce removed data are invalidated. Audit preserves the fact
of the action without retaining prohibited content.

Account deletion removes or irreversibly anonymizes personal profile, sessions,
Saved Events, Saved Searches, and Feed Credentials. Historical catalog Decisions
retain a non-personal actor tombstone when audit integrity requires it.

## Content rights

Every publishable description, image, media reference, and attribution-sensitive
Link records origin, retrieval Instant, author/owner when known, license or
permission, required attribution, modification permission, validity, and
publication eligibility.

Unknown permission defaults to structured facts and outbound source linking,
not republication. Rights expiry or revocation invalidates the affected Content
Item without suppressing unrelated Event facts.

## Public API and feed protection

- Apply documented rate and result-size limits.
- Use stable cursor pagination and bounded feed windows.
- Keep private feed credentials revocable, non-enumerable, and out of referrers
  and analytics.
- Prevent query cost amplification through bounded filters and text search.
- Return only selected publication-safe fields.
- Use cache validators without allowing stale cancellation, suppression, or
  rights-revocation state to persist beyond policy.

## Operational model

Configured Sources have enabled/disabled application state. Operators choose the
scheduler and execution environment. The runtime must:

- prevent overlapping writes for the same source and scope unless the Connector
  explicitly supports them;
- allow independent sources and bounded enrichments to run concurrently;
- use leases/heartbeats so abandoned work can resume safely;
- checkpoint large runs and reprocessing;
- isolate failures per record/entity where invariants allow;
- preserve the rule that an incomplete run cannot infer absence;
- support bounded manual runs, dry-runs, cancellation, and replay;
- apply backoff, provider rate limits, and circuit breaking;
- make all external side effects explicit.

Disabling a Configured Source prevents new scheduled/manual observation but
does not delete evidence, Decisions, or Publications.

## Observability

Operators and Administrators need views appropriate to their roles for:

- Import Run and capability outcome, duration, checkpoint, scope, and counts;
- source freshness and time since last successful complete observation;
- created/updated/unlisted records and validation failures;
- automatic Decision, abstention, ambiguity, and review-task rates;
- review age, throughput, reversals, and stale Manual Decisions;
- replay backlog, failures, and changed public-field counts;
- publication volume, API/feed errors, and cache age;
- external request rate, throttling, and provider errors;
- authentication, authorization, raw-evidence access, and configuration changes.

Diagnostics use structured event names and safe identifiers. A trace can follow
one public field back through Projection Revision, Decision, Claim, capability,
Source Record Version, and Import Run.

## Service objectives

Technology selection must propose measurable objectives satisfying:

- public catalog remains readable while imports or enrichments fail;
- one failed source cannot corrupt or block unrelated sources;
- accepted Decisions and account writes are durable before success is shown;
- alias redirects and suppression propagate promptly;
- routine replay and source runs resume after interruption;
- backups cover evidence, catalog, account, configuration, and audit data;
- restore exercises prove referential, dependency, and audit integrity.

Exact latency, availability, recovery time, and recovery point targets are chosen
with the deployment design, then added without weakening these requirements.

## Technology-selection security gate

Candidate architectures must demonstrate:

- authorization and secret boundaries;
- immutable/auditable records and reversible Decisions;
- safe concurrency and idempotency;
- efficient dependency traversal and regional-growth access paths;
- encryption, backup, restore, redaction, and account deletion;
- Plugin permission enforcement;
- public API/feed abuse controls;
- a credible patch and dependency-update process.
