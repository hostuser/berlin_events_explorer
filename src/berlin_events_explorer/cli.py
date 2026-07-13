"""Command-line interface for Berlin Events Explorer."""

from __future__ import annotations

from pathlib import Path

import click
import httpx
from rich.console import Console

from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.sync import sync_source

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
def sync(database: Path) -> None:
    """Synchronize events from configured sources."""
    store = EventStore(database)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        result = sync_source(MyTrueIntentSource(), store, client)
    state = "downloaded" if result.downloaded else "not modified"
    console.print(
        f"[bold]Sync complete[/bold] ({state}): "
        f"{result.created} created, {result.updated} updated, "
        f"{result.unchanged} unchanged"
    )


if __name__ == "__main__":
    cli()
