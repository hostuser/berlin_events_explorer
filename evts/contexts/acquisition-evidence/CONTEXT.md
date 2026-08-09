# Acquisition and Evidence

This context records what external sources supplied and what processing derived
from it. Its language describes evidence, never catalog truth.

## Language

**Plugin**:
Operator-installed, trusted extension code that provides one or more acquisition
or processing capabilities.
_Avoid_: Add-on, uploaded script

**Plugin Release**:
One immutable, versioned publication of a Plugin and its capability manifest.
_Avoid_: Installed plugin

**Capability**:
A versioned kind of work exposed by a Plugin: Connector,
Extractor/Normalizer, Resolver, or Enricher.
_Avoid_: Plugin type, pipeline hook

**Connector**:
A Capability that observes records from one Configured Source.
_Avoid_: Importer, scraper

**Extractor/Normalizer**:
A Capability that derives typed Claims from source-native or previously derived
values.
_Avoid_: Field parser, cleaner

**Resolver**:
A Capability that proposes identity, relationship, or field Decisions from
Claims and policy.
_Avoid_: Matcher, scorer

**Enricher**:
A Capability that obtains additional evidence about a Canonical Entity.
_Avoid_: Augmenter, updater

**Configured Source**:
A durable configuration of a Connector for one feed or external collection.
Several Configured Sources may use the same Connector.
_Avoid_: Provider, plugin instance

**Import Run**:
One bounded attempt to observe a declared scope of a Configured Source.
_Avoid_: Sync, scrape

**Run Semantics**:
The declaration that an Import Run is a complete snapshot, partial observation,
or delta for its stated scope.
_Avoid_: Full sync flag

**Source Record**:
The stable source-local identity of one item supplied by a Configured Source.
_Avoid_: Event, canonical record

**Source Record Version**:
An immutable observation of a Source Record's native content during an Import
Run.
_Avoid_: Current row, raw event

**Claim**:
A typed assertion derived from evidence, such as a title, time, cancellation,
identity candidate, or relationship. A Claim may be contradicted.
_Avoid_: Fact, canonical value

**Evidence Reference**:
The lineage from a Claim or Decision to its Source Record Version, external
evidence, and producing Capability version.
_Avoid_: Metadata

**Candidate**:
One reviewable possible value, relationship, or real-world identity supported by
Claims.
_Avoid_: Match, result

**Confidence**:
A capability-local assessment of evidential support. Confidence values from
unrelated capabilities are not inherently comparable.
_Avoid_: Probability, global score

**Unlisted**:
The source-local state inferred when a successful complete snapshot no longer
contains a previously observed Source Record. It is not cancellation.
_Avoid_: Deleted, cancelled
