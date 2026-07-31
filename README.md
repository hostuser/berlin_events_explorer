[![PyPI status](https://img.shields.io/pypi/status/berlin_events_explorer.svg)](https://pypi.python.org/pypi/berlin_events_explorer/)
[![PyPI version](https://img.shields.io/pypi/v/berlin_events_explorer.svg)](https://pypi.python.org/pypi/berlin_events_explorer/)
[![PyPI pyversions](https://img.shields.io/pypi/pyversions/berlin_events_explorer.svg)](https://pypi.python.org/pypi/berlin_events_explorer/)
[![Build Status](https://img.shields.io/endpoint.svg?url=https%3A%2F%2Factions-badge.atrox.dev%2Fhostuser%berlin_events_explorer%2Fbadge%3Fref%3Ddevelop&style=flat)](https://actions-badge.atrox.dev/hostuser/berlin_events_explorer/goto?ref=develop)
[![Coverage Status](https://coveralls.io/repos/github/hostuser/berlin_events_explorer/badge.svg?branch=develop)](https://coveralls.io/github/hostuser/berlin_events_explorer?branch=develop)
[![Code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)

# Berlin Events Explorer

Parse and explore Berlin music events with enriched venue and performer metadata.

 - Documentation: [https://hostuser.github.io/berlin_events_explorer](https://hostuser.github.io/berlin_events_explorer)
 - Code: [https://github.com/hostuser/berlin_events_explorer](https://github.com/hostuser/berlin_events_explorer)

## Description

TODO

## Development

### Requirements

- uv ( https://docs.astral.sh/uv/ )
- git
- make (on Linux / Mac OS X -- optional)
- just (optional)

### Check out the source code & enter the project directory

```
git clone https://github.com/hostuser/berlin_events_explorer
cd berlin_events_explorer
```

### Running pre-defined development-related tasks (using `just`)

The included `Makefile` file includes some useful tasks that help with development. This requires `uv` and the `make` tool to be
installed, which should be the case for Linux & Mac OS X systems.

- `just tests`: runs all unit tests
- `just test <pattern>`: runs all unit tests whose name matches the given pattern
- `just typecheck`: run type-checker
- `just lint`: run the `ruff` linter on the source code
- `just format`: run the `ruff` formatter on the source code (similar to `black`)
- `just db-validate`: validate the committed Atlas migration history
- `just db-new <name>`: create a timestamped Atlas migration stub

### Database schema and migrations

SQLite schema changes are managed with [Atlas](https://atlasgo.io/) versioned migrations.
The committed migration directory is `src/berlin_events_explorer/db_migrations/`; its
`atlas.sum` checksum file is part of the migration history and must be committed with every
new migration. Install the Atlas CLI before running the application or tests:

```bash
curl -sSf https://atlasgo.sh | sh
```

Every `EventStore` applies pending migrations before opening SQLite, so normal CLI and web
commands are safe to run against a fresh database. Operators can also run migrations
explicitly or inspect their state:

```bash
uv run berlin-events database migrate --database events.sqlite
uv run berlin-events database status --database events.sqlite
```

For future schema work, add a new migration (never edit an applied migration), implement the
matching SQLAlchemy table definition in `storage.py`, then validate and test it:

```bash
just db-new add_event_field
# edit the generated SQL migration
just db-validate
just tests
```

### Web UI

Run the new Litestar web interface to browse synced events:

```
uv run berlin-events web --database events.sqlite --host 127.0.0.1 --port 8000
```

### Automatic synchronization

The web service runs an in-process background sync by default, without a separate
worker. It waits for the configured interval before the first run, then synchronizes
sequentially; a slow sync never overlaps a second sync. The default is one hour:

```
uv run berlin-events web --database events.sqlite --sync-interval-minutes 60
```

Set `--sync-interval-minutes 0` to disable the scheduled sync. The existing **Sync now**
control remains available for an immediate manual refresh.

The UI renders the local SQLite event list and includes a **Sync now** control. Each
complete, downloaded source snapshot is reconciled with its provider's stored events, so
source rows that disappear or duplicate rows that map to the same event are removed. Rows
that cannot be parsed are logged and skipped; a structurally invalid source fails before
the database transaction begins.
Clicking it now triggers an in-page Datastar action that runs synchronization and updates the table without
reloading the full page. During a fresh sync, the page first reports event import, then shows
the current venue, a completed/total counter, and a progress bar while Nominatim enrichment
runs.

### Venue metadata

Venue names link to stable detail pages after the local venue catalog is bootstrapped. The
catalog is deliberately separate from source event JSON so every address and homepage can
retain its own provenance.

```bash
# Create canonical venue records and event links.
uv run berlin-events venues bootstrap --database events.sqlite

# Query a small, rate-limited Nominatim batch for manual review.
uv run berlin-events venues discover --database events.sqlite --limit 10
uv run berlin-events venues review --database events.sqlite

# Promote one explicitly reviewed candidate to public metadata.
uv run berlin-events venues accept --database events.sqlite \
  --venue 8mm-bar --candidate node/4172803384
```

Regular synchronization creates canonical records for venue names it sees for the first
time and immediately runs one rate-limited Nominatim lookup for each new venue. A new venue
bypasses the approval queue only when exactly one distinct candidate meets the automatic
threshold (0.90 by default). Configure it with `--auto-approve-threshold`, for example
`0.95`, on `sync` or `web`. Duplicate OSM objects for the same normalized name and address
are deduplicated before storage. New venues with no qualifying candidate, or with multiple
distinct qualifying candidates, remain in the approval queue.

Explicit `venues discover` calls and **Find or refresh suggestions** in the approval UI
never auto-approve, regardless of confidence. They only replace the stored reviewable
suggestions; the editor makes the final decision.

Use **Settings** in the event-page header to change the automatic approval threshold. The
value is stored in SQLite and applies to the next manual or scheduled sync without a server
restart. Start the web command with `--environment development` to expose the development-
only **Clear development database** action. That action removes synchronized content and
review data while retaining application settings; production mode does not expose it.

The web UI provides the same editorial workflow under **Awaiting approval**:

1. Open an unresolved venue from the type-aware approval queue.
2. Select **Find or refresh suggestions** to request Nominatim candidates for that venue.
3. Select a candidate or enter the details manually, edit any fields as needed, then use
   the single **Approve** button to apply the form's current values.

Only canonical entity types with review persistence appear in the queue. Venues are
supported now; performers remain embedded event data until a canonical performer catalog
and performer-specific discovery provider are added.

Alternatively, if you don't have the `just` command available, you can use `uv` directly to run those tasks:

- `uv run pytest tests`
- `uv run mypy src/`
- `uv run ruff check --fix src/`
- `uv run ruff format src/`

## Copyright & license

Copyright (c) 2026 - Markus Binsteiner


This project is published under the MIT license, for the license text please check the [LICENSE](/LICENSE) file in this repository.
