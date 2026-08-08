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

from datetime import datetime, timedelta
import os
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.table import Table

from berlin_events_explorer.artist_enrichment import (
    DEFAULT_ARTIST_AUTO_APPROVE_THRESHOLD,
    DEFAULT_MUSICBRAINZ_REQUEST_INTERVAL_SECONDS,
    MAX_MUSICBRAINZ_FETCH_LIMIT,
    MusicBrainzArtistProvider,
    open_musicbrainz_cache,
)
from berlin_events_explorer.artist_homepage_ingestion import enrich_artist_homepages
from berlin_events_explorer.artist_ingestion import enrich_artists
from berlin_events_explorer.artists import bootstrap_artist_catalog
from berlin_events_explorer.augment import AugmentError, augment_events
from berlin_events_explorer.ai_event_research import (
    SearxngEventResearcher,
    create_event_research_agent,
)
from berlin_events_explorer.event_details_augmentation import (
    augment_event_details,
    augment_ticketmaster_event_details,
)
from berlin_events_explorer.event_research_augmentation import augment_event_research
from berlin_events_explorer.performer_title_augmentation import (
    augment_existing_event_performers,
    performer_extractor_from_environment,
)
from berlin_events_explorer.searxng import SearxngClient
from berlin_events_explorer.migrations import (
    AtlasMigrationError,
    migrate_database,
    migration_status,
)
from berlin_events_explorer.models import ArtistStatus, VenueStatus
from berlin_events_explorer.sources.mytrueintent import MyTrueIntentSource
from berlin_events_explorer.auth import hash_password
from berlin_events_explorer.models import UserRole
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.ticketmaster import TicketmasterDiscoveryClient
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
    try:
        performer_extractor = performer_extractor_from_environment()
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
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
                    performer_extractor=performer_extractor,
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


@cli.command("augment-performers")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option(
    "--from-date",
    type=click.DateTime(formats=("%Y-%m-%d",)),
    default=None,
    help="Inclusive first event date (YYYY-MM-DD).",
)
@click.option(
    "--to-date",
    type=click.DateTime(formats=("%Y-%m-%d",)),
    default=None,
    help="Inclusive last event date (YYYY-MM-DD).",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1, max=1000),
    default=100,
    show_default=True,
    help="Maximum existing events to process after date filtering.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Run model extraction but do not write performer records or logs.",
)
def augment_performers_command(
    database: Path,
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int,
    dry_run: bool,
) -> None:
    """Extract safe performer lists from titles of existing, dated events."""

    try:
        extractor = performer_extractor_from_environment(require_enabled=False)
        if extractor is None:
            raise ValueError("No title performer extractor is configured")
        result = augment_existing_event_performers(
            EventStore(database),
            extractor,
            from_date=from_date.date() if from_date else None,
            to_date=to_date.date() if to_date else None,
            limit=limit,
            dry_run=dry_run,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    mode = "would update" if dry_run else "updated"
    console.print(
        f"[bold]Performer title augmentation complete[/bold]: "
        f"{result.extracted} {mode}, {result.no_match} no match, "
        f"{result.errors} errors, {result.considered} considered"
    )


@cli.command("augment-event-details")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1, max=1000),
    default=100,
    show_default=True,
    help="Maximum stale or unobserved events to process.",
)
@click.option(
    "--provider",
    type=click.Choice(
        ["source-links", "ticketmaster-discovery", "searxng-pydantic-ai"]
    ),
    default="source-links",
    show_default=True,
    help="The explicitly selected event-details provider.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report external-provider matches without writing observations.",
)
def augment_event_details_command(
    database: Path, limit: int, provider: str, dry_run: bool
) -> None:
    """Augment a bounded batch with the selected safe event-details provider."""

    store = EventStore(database)
    if provider == "source-links":
        if dry_run:
            raise click.ClickException(
                "--dry-run is available for ticketmaster-discovery only"
            )
        result = augment_event_details(store, limit=limit)
        console.print(
            f"[bold]Event details augment complete[/bold]: "
            f"{result.updated} updated, {result.considered} considered"
        )
        return

    if provider == "searxng-pydantic-ai":
        searxng_url = os.environ.get("BERLIN_EVENTS_SEARXNG_URL", "").strip()
        model = os.environ.get("BERLIN_EVENTS_EVENT_RESEARCH_MODEL", "").strip()
        if not searxng_url:
            raise click.ClickException(
                "Set BERLIN_EVENTS_SEARXNG_URL before using searxng-pydantic-ai"
            )
        if not model:
            raise click.ClickException(
                "Set BERLIN_EVENTS_EVENT_RESEARCH_MODEL before using searxng-pydantic-ai"
            )
        zai_api_key = os.environ.get("ZAI_API_KEY", "").strip()
        if model.startswith("zai:") and not zai_api_key:
            raise click.ClickException(
                "Set ZAI_API_KEY before using a zai: event research model"
            )
        try:
            with httpx.Client(
                timeout=10.0,
                follow_redirects=False,
                headers={"User-Agent": "BerlinEventsExplorer/1.0"},
            ) as http_client:
                researcher = SearxngEventResearcher(
                    SearxngClient(searxng_url, http_client),
                    agent=create_event_research_agent(
                        model, zai_api_key=zai_api_key or None
                    ),
                )
                result = augment_event_research(
                    store, researcher, limit=limit, dry_run=dry_run
                )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        table = Table(title="SearXNG + Pydantic AI research results")
        table.add_column("Event ID")
        table.add_column("Decision")
        table.add_column("Evidence")
        for outcome in result.outcomes:
            table.add_row(
                outcome.event_id,
                outcome.decision,
                outcome.evidence_url or "—",
            )
        console.print(table)
        mode = "would update" if dry_run else "updated"
        console.print(
            f"[bold]AI event research complete[/bold]: {result.matched} matched, "
            f"{result.updated} {mode}, {result.considered} considered"
        )
        return

    api_key = os.environ.get("BERLIN_EVENTS_TICKETMASTER_API_KEY", "").strip()
    if not api_key:
        raise click.ClickException(
            "Set BERLIN_EVENTS_TICKETMASTER_API_KEY before using ticketmaster-discovery"
        )
    with httpx.Client(timeout=10.0, follow_redirects=False) as http_client:
        result = augment_ticketmaster_event_details(
            store,
            TicketmasterDiscoveryClient(api_key, http_client),
            limit=limit,
            dry_run=dry_run,
        )
    table = Table(title="Ticketmaster Discovery results")
    table.add_column("Event ID")
    table.add_column("Decision")
    table.add_column("Provider event")
    table.add_column("Evidence")
    for outcome in result.outcomes:
        table.add_row(
            outcome.event_id,
            outcome.decision,
            outcome.provider_event_id or "—",
            ", ".join(outcome.rationale) or "—",
        )
    console.print(table)
    mode = "would update" if dry_run else "updated"
    console.print(
        f"[bold]Ticketmaster event-details augment complete[/bold]: "
        f"{result.matched} matched, {result.updated} {mode}, "
        f"{result.considered} considered"
    )


@cli.group()
def users() -> None:
    """Create and inspect web UI accounts."""


@users.command("create-admin")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option("--email", prompt=True, help="Email address for the admin account.")
@click.option(
    "--display-name",
    default=None,
    help="Display name; defaults to the email's local part.",
)
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="Password (prompted interactively when omitted).",
)
def users_create_admin(
    database: Path, email: str, display_name: str | None, password: str
) -> None:
    """Create an administrator account for the web UI."""

    if len(password) < 10:
        raise click.ClickException("Choose a password of at least 10 characters.")
    store = EventStore(database)
    try:
        user = store.create_user(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name or email.split("@")[0].title(),
            role=UserRole.ADMIN,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[bold]Administrator {user.email} created[/bold]")


@users.command("change-password")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
@click.option("--email", prompt=True, help="Email address of the account.")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="New password (prompted interactively when omitted).",
)
def users_change_password(database: Path, email: str, password: str) -> None:
    """Change the password for an existing web UI account."""

    if len(password) < 10:
        raise click.ClickException("Choose a password of at least 10 characters.")

    store = EventStore(database)
    credentials = store.get_user_credentials(email)
    if credentials is None:
        raise click.ClickException(f"No user found for email {email!r}.")

    updated = store.update_user(
        credentials.user.id,
        password_hash=hash_password(password),
    )
    if updated is None:
        raise click.ClickException(
            f"No user found for email {credentials.user.email!r}."
        )
    console.print(f"[bold]Password changed for {updated.email}[/bold]")


@users.command("list")
@click.option(
    "--database",
    type=click.Path(path_type=Path),
    default=Path("events.sqlite"),
    show_default=True,
    help="SQLite database path.",
)
def users_list(database: Path) -> None:
    """List accounts, their roles, and login activity."""

    store = EventStore(database)
    table = Table("Email", "Name", "Role", "Active", "Last login")
    for account in store.list_users():
        table.add_row(
            account.email,
            account.display_name,
            account.role.value,
            "yes" if account.is_active else "no",
            account.last_login_at.date().isoformat() if account.last_login_at else "—",
        )
    console.print(table)


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
    "--artist-limit",
    type=click.IntRange(min=1, max=MAX_MUSICBRAINZ_FETCH_LIMIT),
    default=None,
    help="MusicBrainz artist fetches per worker run; defaults to the saved setting.",
)
@click.option(
    "--homepage-limit",
    type=click.IntRange(min=1, max=MAX_MUSICBRAINZ_FETCH_LIMIT),
    default=None,
    help="MusicBrainz metadata fetches per worker run; defaults to the saved setting.",
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
    artist_limit: int | None,
    homepage_limit: int | None,
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
