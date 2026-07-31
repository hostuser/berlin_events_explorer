"""Tests for the versioned Atlas SQLite migration workflow."""

import sqlite3

from click.testing import CliRunner

from berlin_events_explorer.cli import cli
from berlin_events_explorer.migrations import migrate_database


def test_migrate_database_creates_current_schema_and_records_revision(tmp_path) -> None:
    """A new database should be initialized solely by the committed Atlas migration."""

    database = tmp_path / "events.sqlite"

    migrate_database(database)

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {"events", "venues", "artists", "atlas_schema_revisions"} <= tables


def test_database_migrate_command_applies_pending_migrations(tmp_path) -> None:
    """Operators should have an explicit command for migrating a database."""

    database = tmp_path / "events.sqlite"

    result = CliRunner().invoke(
        cli, ["database", "migrate", "--database", str(database)]
    )

    assert result.exit_code == 0, result.output
    assert "Database migrations complete" in result.output
