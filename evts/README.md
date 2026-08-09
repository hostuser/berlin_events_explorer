# evts

evts is a public event catalog for one or many cities and regions. It acquires
dirty data from independent sources, preserves the evidence, resolves duplicate
real-world entities, and publishes a searchable catalog whose decisions can be
reviewed and corrected.

This directory is the complete, technology-agnostic starting point for the
project. A new implementation must be understandable from these files alone.
Programming languages, frameworks, databases, deployment products, and code
reuse are deliberately undecided.

## Read first

1. [Product requirements](docs/product-requirements.md)
2. [Context map](CONTEXT-MAP.md) and the three linked glossaries
3. [Logical data model](docs/logical-data-model.md)
4. [Pipeline and resolution](docs/pipeline-and-resolution.md)
5. [Plugin contracts](docs/plugin-contracts.md)
6. [Editorial workflows](docs/editorial-workflows.md)
7. [Public product and API](docs/public-product-and-api.md)
8. [Design language](docs/design-language.md)
9. [Security, governance, and operations](docs/security-governance-operations.md)
10. [Acceptance scenarios](docs/acceptance-scenarios.md)

The [architecture decisions](docs/adr/) explain the few foundational choices
that should not be casually reversed.

## Specification authority

- Context files define canonical domain words.
- The logical data model defines entities, relationships, and invariants.
- Behavioral specifications define workflows and interfaces.
- ADRs explain hard-to-reverse decisions; they do not replace requirements.
- Agent skills are operational checklists that point back to these documents.

When documents disagree, stop and resolve the contradiction. Do not choose one
silently.

## Release boundary

The first release proves acquisition, resolution, editorial review, publication,
public discovery, read APIs and feeds, user registration, bookmarks, and saved
searches. Notifications, ticket sales, multi-tenancy, federation, arbitrary
plugin upload, and technology selection are outside this release.

Technology selection starts only after every requirement in
[Acceptance scenarios](docs/acceptance-scenarios.md) passes review.
