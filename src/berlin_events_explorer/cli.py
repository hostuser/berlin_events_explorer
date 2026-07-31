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
from rich.table import Table

from berlin_events_explorer.artist_enrichment import (
    DEFAULT_ARTIST_AUTO_APPROVE_THRESHOLD,
    DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    MusicBrainzArtistProvider,
    open_musicbrainz_cache,
)
from berlin_events_explorer.artist_homepage_ingestion import enrich_artist_homepages
from berlin_events_explorer.artist_ingestion import enrich_artists
from berlin_events_explorer.artists import bootstrap_artist_catalog
from berlin_events_explorer.augment import AugmentError, augment_events
from berlin_events_explorer.migrations import (
    AtlasMigrationError,
    migrate_database,
    migration_status,
)
from berlin_events_explorer.models import ArtistStatus, VenueStatus
from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.venue_enrichment import (
    DEFAULT_AUTO_APPROVE_THRESHOLD,
    NominatimVenueProvider,
    VenueDiscoveryError,
)
from berlin_events_explorer.venue_ingestion import sync_source_and_ingest_venues
from berlin_events_explorer.venues import bootstrap_venue_catalog
from berlin_events_explorer.webapp import run_server
from berlin_events_explorer.worker import run_default_worker
from berlin_events_explorer.sync import (
    SyncError,
    clear_sync_cache,
    open_sync_cache,
)

console = Console()


@click.group()
def cli() -> None:
    """Parse, enrich, and query Berlin events."""


@cli.group()
def database() -> None:
    """Inspect and apply Atlas-managed SQLite schema migrations."""


@database.command("migrate")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
def database_migrate(database: Path) -> None:
    """Apply pending Atlas migrations to a SQLite database."""

    try:
        migrate_database(database)
    except AtlasMigrationError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("[bold]Database migrations complete[/bold]")


@database.command("status")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
def database_status(database: Path) -> None:
    """Show Atlas migration state for a SQLite database."""

    try:
        console.print(migration_status(database))
    except AtlasMigrationError as exc:
        raise click.ClickException(str(exc)) from exc


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
@click.option(
    "--auto-approve-threshold",
    type=click.FloatRange(min=0, max=1),
    default=DEFAULT_AUTO_APPROVE_THRESHOLD,
    show_default=True,
    help="Auto-approve one unambiguous match when a venue is first created.",
)
def sync(
    database: Path,
    cache_dir: Path | None,
    clear_cache: bool,
    auto_approve_threshold: float,
) -> None:
    """Synchronize events from configured sources."""
    store = EventStore(database)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        try:
            with open_sync_cache(cache_dir) as cache:
                if clear_cache:
                    clear_sync_cache(cache)
                    console.print("[yellow]Sync cache cleared[/yellow]")
                result, venue_result = sync_source_and_ingest_venues(
                    MyTrueIntentSource(),
                    store,
                    client,
                    http_cache=cache,
                    auto_approve_threshold=auto_approve_threshold,
                )
        except SyncError as exc:
            raise click.ClickException(str(exc))
        except httpx.RequestError as exc:
            raise click.ClickException(f"Network error: {exc}")

    state = "downloaded" if result.downloaded else "not modified"
    console.print(
        f"[bold]Sync complete[/bold] ({state}): "
        f"{result.created} created, {result.updated} updated, "
        f"{result.unchanged} unchanged, {result.deleted} removed, "
        f"{result.errors} errors logged"
    )
    console.print(
        f"[bold]Venue catalog[/bold]: {venue_result.created} created, "
        f"{venue_result.auto_approved} auto-approved, "
        f"{venue_result.awaiting_approval} awaiting approval"
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


@cli.group()
def venues() -> None:
    """Create, discover, review, and select canonical venue metadata."""


@venues.command()
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
def bootstrap(database: Path) -> None:
    """Create canonical venue records and link existing events."""

    result = bootstrap_venue_catalog(EventStore(database))
    console.print(
        f"[bold]Venue catalog complete[/bold]: {result.created} venue created, "
        f"{result.linked} event linked, {result.unchanged} unchanged"
    )


@venues.command()
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option(
    "--limit", type=click.IntRange(min=1, max=50), default=10, show_default=True
)
def discover(database: Path, limit: int) -> None:
    """Discover reviewable OSM candidates for unresolved venues."""

    store = EventStore(database)
    unresolved = [
        venue for venue in store.list_venues() if venue.status is VenueStatus.UNRESOLVED
    ][:limit]
    discovered = errors = 0
    with httpx.Client(follow_redirects=True) as client:
        provider = NominatimVenueProvider(client)
        for venue in unresolved:
            try:
                candidates = provider.discover(venue)
            except VenueDiscoveryError as exc:
                errors += 1
                console.print(f"[yellow]Skipped {venue.name}: {exc}[/yellow]")
                continue
            store.record_venue_candidates(candidates)
            if candidates:
                store.upsert_venue(
                    venue.model_copy(update={"status": VenueStatus.CANDIDATE})
                )
                discovered += 1
    console.print(
        f"[bold]Venue discovery complete[/bold]: {discovered} awaiting review, "
        f"{errors} errors, {len(unresolved)} checked"
    )


@venues.command()
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
def review(database: Path) -> None:
    """Print reviewable venue candidates and their evidence."""

    store = EventStore(database)
    table = Table("Venue", "Candidate", "Address", "Homepage", "Score", "Accept key")
    for venue in store.list_venues():
        for candidate in store.list_venue_candidates(venue.id):
            table.add_row(
                venue.name,
                candidate.display_name,
                candidate.address or "—",
                candidate.website or "—",
                f"{candidate.confidence:.2f}",
                f"{candidate.osm_type}/{candidate.osm_id}",
            )
    console.print(table)


@venues.command()
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option("--venue", "venue_id", required=True, help="Canonical venue ID.")
@click.option("--candidate", required=True, help="Candidate key in the form node/123.")
def accept(database: Path, venue_id: str, candidate: str) -> None:
    """Explicitly select a reviewed Nominatim candidate as public metadata."""

    try:
        osm_type, osm_id = candidate.split("/", maxsplit=1)
        venue = EventStore(database).select_venue_candidate(
            venue_id, "nominatim", osm_type, osm_id
        )
    except ValueError as exc:
        raise click.ClickException(str(exc))
    console.print(f"[bold]Verified venue[/bold]: {venue.name}")


@cli.group()
def artists() -> None:
    """Create, enrich, review, and approve canonical artist metadata."""


@artists.command(name="bootstrap")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
def artists_bootstrap(database: Path) -> None:
    """Create canonical artist records and link existing event billings."""

    result = bootstrap_artist_catalog(EventStore(database))
    console.print(
        f"[bold]Artist catalog complete[/bold]: {result.created} artist created, "
        f"{result.linked} billing linked, {result.unchanged} unchanged"
    )


@artists.command()
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
    help="Shared MusicBrainz response cache directory.",
)
@click.option(
    "--limit", type=click.IntRange(min=1, max=50), default=10, show_default=True
)
@click.option(
    "--request-interval-seconds",
    type=click.FloatRange(min=1.0, max=300.0),
    default=DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    show_default=True,
    help="Minimum gap between public MusicBrainz requests.",
)
@click.option(
    "--auto-approve-threshold",
    type=click.FloatRange(min=0, max=1),
    default=DEFAULT_ARTIST_AUTO_APPROVE_THRESHOLD,
    show_default=True,
    help="Select one exact, unique candidate at or above this confidence.",
)
@click.option(
    "--refresh", is_flag=True, default=False, help="Ignore cached query results."
)
def enrich(
    database: Path,
    cache_dir: Path | None,
    limit: int,
    request_interval_seconds: float,
    auto_approve_threshold: float,
    refresh: bool,
) -> None:
    """Discover MusicBrainz candidates for a bounded unresolved artist batch."""

    store = EventStore(database)
    with (
        httpx.Client(follow_redirects=True) as client,
        open_musicbrainz_cache(cache_dir) as cache,
    ):
        provider = MusicBrainzArtistProvider(
            client,
            cache=cache,
            request_interval_seconds=request_interval_seconds,
        )
        result = enrich_artists(
            store,
            provider,
            limit=limit,
            auto_approve_threshold=auto_approve_threshold,
            refresh=refresh,
        )
    console.print(
        f"[bold]Artist enrichment complete[/bold]: {result.checked} checked, "
        f"{result.auto_approved} auto-approved, {result.queued} queued, "
        f"{result.no_match} no match, {result.errors} errors, "
        f"{result.remaining} remaining"
    )


@artists.command(name="enrich-homepages")
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
    help="Shared MusicBrainz response cache directory.",
)
@click.option(
    "--limit", type=click.IntRange(min=1, max=50), default=10, show_default=True
)
@click.option(
    "--request-interval-seconds",
    type=click.FloatRange(min=1.0, max=300.0),
    default=DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    show_default=True,
    help="Minimum gap between public MusicBrainz requests.",
)
@click.option(
    "--refresh", is_flag=True, default=False, help="Ignore cached relation results."
)
def enrich_homepages(
    database: Path,
    cache_dir: Path | None,
    limit: int,
    request_interval_seconds: float,
    refresh: bool,
) -> None:
    """Retrieve cached official homepages for bounded verified artist batches."""

    store = EventStore(database)
    with (
        httpx.Client(follow_redirects=True) as client,
        open_musicbrainz_cache(cache_dir) as cache,
    ):
        provider = MusicBrainzArtistProvider(
            client,
            cache=cache,
            request_interval_seconds=request_interval_seconds,
        )
        result = enrich_artist_homepages(store, provider, limit=limit, refresh=refresh)
    console.print(
        f"[bold]Artist homepage enrichment complete[/bold]: {result.checked} checked, "
        f"{result.found} found, {result.no_homepage} no homepage, "
        f"{result.errors} errors, {result.remaining} remaining"
    )


@artists.command(name="review")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
def artists_review(database: Path) -> None:
    """Print reviewable artist candidates and their identifying evidence."""

    table = Table("Artist", "Candidate", "Type", "Country", "Score", "Accept key")
    store = EventStore(database)
    for artist in store.list_artists():
        if artist.status is not ArtistStatus.CANDIDATE:
            continue
        for candidate in store.list_artist_candidates(artist.id):
            table.add_row(
                artist.name,
                candidate.display_name,
                candidate.artist_type or "—",
                candidate.country or "—",
                f"{candidate.confidence:.2f}",
                candidate.musicbrainz_id,
            )
    console.print(table)


@artists.command(name="accept")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option("--artist", "artist_id", required=True, help="Canonical artist ID.")
@click.option(
    "--candidate", "musicbrainz_id", required=True, help="MusicBrainz artist ID."
)
def artists_accept(database: Path, artist_id: str, musicbrainz_id: str) -> None:
    """Explicitly select a reviewed MusicBrainz candidate as public metadata."""

    try:
        artist = EventStore(database).select_artist_candidate(
            artist_id, "musicbrainz", musicbrainz_id
        )
    except ValueError as exc:
        raise click.ClickException(str(exc))
    console.print(f"[bold]Verified artist[/bold]: {artist.name}")


@cli.command("worker")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option(
    "--artist-limit", type=click.IntRange(min=1, max=200), default=10, show_default=True
)
@click.option(
    "--homepage-limit",
    type=click.IntRange(min=1, max=50),
    default=10,
    show_default=True,
)
@click.option(
    "--musicbrainz-cache-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Shared MusicBrainz response cache directory.",
)
@click.option(
    "--request-interval-seconds",
    type=click.FloatRange(min=1.0, max=300.0),
    default=DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    show_default=True,
    help="Minimum gap between public MusicBrainz requests.",
)
@click.option(
    "--auto-approve-threshold",
    type=click.FloatRange(min=0, max=1),
    default=DEFAULT_AUTO_APPROVE_THRESHOLD,
    show_default=True,
    help="Auto-approve one unambiguous venue candidate at or above this score.",
)
def worker(
    database: Path,
    artist_limit: int,
    homepage_limit: int,
    musicbrainz_cache_dir: Path | None,
    request_interval_seconds: float,
    auto_approve_threshold: float,
) -> None:
    """Run one bounded background sync and enrichment pass."""

    try:
        run = run_default_worker(
            EventStore(database),
            artist_limit=artist_limit,
            homepage_limit=homepage_limit,
            musicbrainz_cache_dir=musicbrainz_cache_dir,
            musicbrainz_request_interval_seconds=request_interval_seconds,
            auto_approve_threshold=auto_approve_threshold,
        )
    except Exception as exc:
        raise click.ClickException(f"Worker failed: {exc}") from exc
    console.print(f"[bold]Worker complete[/bold]: run {run.id} {run.status}")


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
@click.option(
    "--auto-approve-threshold",
    type=click.FloatRange(min=0, max=1),
    default=DEFAULT_AUTO_APPROVE_THRESHOLD,
    show_default=True,
    help="Automatically approve one unambiguous candidate at or above this score.",
)
@click.option(
    "--environment",
    type=click.Choice(["production", "development"]),
    default="production",
    show_default=True,
    help="Deployment mode; development exposes database reset controls.",
)
def web(
    database: Path,
    host: str,
    port: int,
    reload: bool,
    sync_interval_minutes: int,
    auto_approve_threshold: float,
    environment: str,
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
        auto_approve_threshold=auto_approve_threshold,
        environment=environment,
    )


if __name__ == "__main__":
    cli()
