# cli.py
#
# Copyright (c) 2026 Markus Binsteiner
# All rights reserved.
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License

"""Command-line interface for Berlin Events Explorer."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import click
import httpx
from rich.console import Console

from berlin_events_explorer.augment import AugmentError, augment_events
from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.webapp import run_server
from berlin_events_explorer.sync import (
    SyncError,
    clear_sync_cache,
    open_sync_cache,
    sync_source,
)

console = Console()


@click.group()
def cli() -> None:
    """Parse, enrich, and query Berlin events."""


@cli.command()
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option(
    "--cache-dir",
    type=click.Path(path_type=Path),
    default=None,
    show_default=False,
    help="Disk cache directory for sync metadata and payloads.",
)
@click.option(
    "--clear-cache",
    is_flag=True,
    default=False,
    help="Clear sync on-disk cache before syncing.",
)
def sync(database: Path, cache_dir: Path | None, clear_cache: bool) -> None:
    """Synchronize events from configured sources."""
    store = EventStore(database)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        try:
            with open_sync_cache(cache_dir) as cache:
                if clear_cache:
                    clear_sync_cache(cache)
                    console.print("[yellow]Sync cache cleared[/yellow]")
                result = sync_source(
                    MyTrueIntentSource(), store, client, http_cache=cache
                )
        except SyncError as exc:
            raise click.ClickException(str(exc))
        except httpx.RequestError as exc:
            raise click.ClickException(f"Network error: {exc}")

    state = "downloaded" if result.downloaded else "not modified"
    console.print(
        f"[bold]Sync complete[/bold] ({state}): "
        f"{result.created} created, {result.updated} updated, "
        f"{result.unchanged} unchanged, {result.errors} errors logged"
    )


@cli.command()
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
def augment(database: Path) -> None:
    """Run local augmentation against all stored events."""
    store = EventStore(database)
    try:
        result = augment_events(store)
    except AugmentError as exc:
        raise click.ClickException(str(exc))

    console.print(
        f"[bold]Augment complete[/bold]: "
        f"{result.updated} updated, {result.unchanged} unchanged, "
        f"{result.processed} processed"
    )


@cli.command()
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=click.IntRange(min=1, max=65535), default=8000)
@click.option(
    "--reload", is_flag=True, default=False, help="Auto-reload when files change"
)
@click.option(
    "--sync-interval-minutes",
    type=click.IntRange(min=0),
    default=60,
    show_default=True,
    help="Automatic sync interval; use 0 to disable scheduled syncing.",
)
def web(
    database: Path,
    host: str,
    port: int,
    reload: bool,
    sync_interval_minutes: int,
) -> None:
    """Run the Litestar web UI."""

    sync_interval = (
        timedelta(minutes=sync_interval_minutes) if sync_interval_minutes else None
    )
    run_server(
        database=database,
        host=host,
        port=port,
        reload=reload,
        sync_interval=sync_interval,
    )


if __name__ == "__main__":
    cli()
