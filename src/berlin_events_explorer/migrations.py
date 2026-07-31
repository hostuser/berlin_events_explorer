"""Versioned SQLite schema migrations managed by Atlas."""

from __future__ import annotations

from pathlib import Path, PurePath
import shutil
import subprocess


MIGRATIONS_DIRECTORY = Path(__file__).with_name("db_migrations")


class AtlasMigrationError(RuntimeError):
    """Raised when Atlas cannot bring a database to the required schema version."""


def _atlas_file_url(path: PurePath) -> str:
    """Build an Atlas file URL that keeps Windows drive paths valid."""

    return f"file://{path.as_posix()}"


def _atlas_sqlite_url(path: PurePath) -> str:
    """Build an Atlas SQLite URL that keeps Windows drive paths valid."""

    return f"sqlite://{path.as_posix()}"


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
            _atlas_sqlite_url(database_path),
            "--dir",
            _atlas_file_url(MIGRATIONS_DIRECTORY.resolve()),
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
            _atlas_sqlite_url(database_path),
            "--dir",
            _atlas_file_url(MIGRATIONS_DIRECTORY.resolve()),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AtlasMigrationError(f"Atlas could not inspect {database_path}: {detail}")
    return result.stdout.strip()
