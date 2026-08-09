# Context Map

## Contexts

- [Acquisition and Evidence](contexts/acquisition-evidence/CONTEXT.md) —
  observes source systems and preserves what they said.
- [Catalog and Resolution](contexts/catalog-resolution/CONTEXT.md) — resolves
  evidence into stable real-world entities and current catalog facts.
- [Discovery and Accounts](contexts/discovery-accounts/CONTEXT.md) — publishes
  the catalog and owns public discovery and personal user data.

## Relationships

- **Acquisition and Evidence → Catalog and Resolution**: supplies immutable
  source-record versions and derived claims. It never supplies canonical truth.
- **Catalog and Resolution → Discovery and Accounts**: supplies versioned
  canonical projections and redirects suitable for publication.
- **Discovery and Accounts → Catalog and Resolution**: references stable
  catalog IDs in bookmarks, saved searches, feeds, and public URLs. It does not
  own catalog entities.
- **Catalog and Resolution → Acquisition and Evidence**: records dependencies
  from decisions to the evidence and plugin or policy versions that supported
  them.
