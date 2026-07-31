"""Versioned SQLite schema migrations managed by Atlas."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


MIGRATIONS_DIRECTORY = Path(__file__).with_name("db_migrations")


class AtlasMigrationError(RuntimeError):
    """Raised when Atlas cannot bring a database to the required schema version."""


def migrate_database(database: str | Path) -> None:
    """Apply all pending Atlas migrations to a SQLite database."""

    database_path = Path(database).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    atlas = shutil.which("atlas")
    if atlas is None:
        raise AtlasMigrationError(
            "Atlas CLI is required to manage the database schema. "
            "Install it from https://atlasgo.io/getting-started"
        )

    result = subprocess.run(
        [
            atlas,
            "migrate",
            "apply",
            "--url",
            database_path.as_uri().replace("file://", "sqlite://", 1),
            "--dir",
            MIGRATIONS_DIRECTORY.resolve().as_uri(),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AtlasMigrationError(f"Atlas could not migrate {database_path}: {detail}")


def migration_status(database: str | Path) -> str:
    """Return Atlas's migration status for a SQLite database."""

    database_path = Path(database).resolve()
    atlas = shutil.which("atlas")
    if atlas is None:
        raise AtlasMigrationError(
            "Atlas CLI is required to manage the database schema. "
            "Install it from https://atlasgo.io/getting-started"
        )
    result = subprocess.run(
        [
            atlas,
            "migrate",
            "status",
            "--url",
            database_path.as_uri().replace("file://", "sqlite://", 1),
            "--dir",
            MIGRATIONS_DIRECTORY.resolve().as_uri(),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AtlasMigrationError(f"Atlas could not inspect {database_path}: {detail}")
    return result.stdout.strip()
