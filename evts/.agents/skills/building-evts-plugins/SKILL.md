---
name: building-evts-plugins
description: Design or implement evts Plugin capabilities. Use for Connector, Extractor/Normalizer, Resolver, or Enricher manifests, source integrations, import semantics, plugin configuration, upgrades, permissions, idempotency, conformance tests, and evidence-producing pipeline work.
---

# Building evts plugins

## Select the capability

Read [plugin contracts](../../../docs/plugin-contracts.md),
[pipeline and resolution](../../../docs/pipeline-and-resolution.md), the
[Acquisition/Evidence language](../../../contexts/acquisition-evidence/CONTEXT.md),
and [security requirements](../../../docs/security-governance-operations.md).

Choose exactly what the capability contributes:

- **Connector** observes one Configured Source.
- **Extractor/Normalizer** derives typed Claims.
- **Resolver** proposes identity, relationship, or field Decisions.
- **Enricher** obtains additional evidence about a Canonical Entity.

Split capabilities when they require different permissions, inputs, versioning,
or failure boundaries.

## Define the contract

Specify:

1. manifest identity, compatibility, configuration, secrets, and permissions;
2. immutable inputs and bounded work scope;
3. typed outputs, Evidence References, rationale, diagnostics, and checkpoints;
4. stable idempotency keys and retry behavior;
5. partial, timeout, cancellation, and no-result semantics;
6. version upgrade, dry-run replay, and rollback behavior.

Contract definition is complete when every output can be reproduced or explained
from pinned inputs and versions without reading mutable plugin state.

## Preserve the boundary

- Emit Source Record Versions, Claims, Candidates, or Decision proposals.
- Let the core validate Decisions and materialize Projections.
- Keep confidence capability-local and permit abstention.
- Declare actual snapshot, partial, or delta scope; incomplete work cannot infer
  absence.
- Preserve source-native values and stable source keys.
- Keep credentials out of payloads, evidence, diagnostics, and URLs.
- Make external side effects explicit and dry-runnable.

## Verify

Implement the conformance cases in
[plugin contracts](../../../docs/plugin-contracts.md) and the relevant
[acceptance scenarios](../../../docs/acceptance-scenarios.md). Include malformed,
duplicate, partial, retried, cancelled, rate-limited, secret-bearing, and
incompatible-version cases.

Finish only when safe retry creates no duplicate evidence or decisions, every
error has source-safe diagnostics, and the capability cannot write canonical or
public state directly.
