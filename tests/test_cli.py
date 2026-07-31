"""Tests for the command-line interface."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from click.testing import CliRunner

from berlin_events_explorer.cli import cli
from berlin_events_explorer.models import (
    Event,
    EventSourceRef,
    Performer,
    Venue,
    VenueCandidate,
    VenueRecord,
    VenueStatus,
)
from berlin_events_explorer.storage import EventStore


def test_web_passes_configured_sync_interval_to_server(monkeypatch, tmp_path) -> None:
    """The web command should configure its in-process sync interval in minutes."""

    received: dict[str, object] = {}

    def _fake_run_server(**kwargs: object) -> None:
        received.update(kwargs)

    monkeypatch.setattr("berlin_events_explorer.cli.run_server", _fake_run_server)

    result = CliRunner().invoke(
        cli,
        [
            "web",
            "--database",
            str(tmp_path / "events.sqlite"),
            "--sync-interval-minutes",
            "15",
            "--auto-approve-threshold",
            "0.95",
            "--environment",
            "development",
        ],
    )

    assert result.exit_code == 0
    assert received["database"] == Path(tmp_path / "events.sqlite")
    assert received["sync_interval"] == timedelta(minutes=15)
    assert received["auto_approve_threshold"] == 0.95
    assert received["environment"] == "development"


def test_web_disables_scheduled_sync_for_zero_interval(monkeypatch, tmp_path) -> None:
    """The web command should use None to explicitly disable the scheduler."""

    received: dict[str, object] = {}

    def _fake_run_server(**kwargs: object) -> None:
        received.update(kwargs)

    monkeypatch.setattr("berlin_events_explorer.cli.run_server", _fake_run_server)

    result = CliRunner().invoke(
        cli,
        [
            "web",
            "--database",
            str(tmp_path / "events.sqlite"),
            "--sync-interval-minutes",
            "0",
        ],
    )

    assert result.exit_code == 0
    assert received["sync_interval"] is None


def test_venues_bootstrap_creates_catalog_records(tmp_path) -> None:
    """The venue CLI bootstraps canonical records from stored source labels."""

    database = tmp_path / "events.sqlite"
    EventStore(database).upsert(
        Event(
            id="event-1",
            source=EventSourceRef(
                provider="test",
                source_url="https://example.test",
                source_record_hash="event-1",
            ),
            start_date=date(2026, 8, 1),
            title="Example event",
            venue=Venue(name="Berghain"),
        )
    )

    result = CliRunner().invoke(
        cli, ["venues", "bootstrap", "--database", str(database)]
    )

    assert result.exit_code == 0
    assert "1 venue created" in result.output
    assert EventStore(database).get_venue("berghain") is not None


def test_artists_bootstrap_creates_catalog_records(tmp_path) -> None:
    """The artist CLI creates local records without any MusicBrainz request."""

    database = tmp_path / "events.sqlite"
    EventStore(database).upsert(
        Event(
            id="event-1",
            source=EventSourceRef(
                provider="test",
                source_url="https://example.test",
                source_record_hash="event-1",
            ),
            start_date=date(2026, 8, 1),
            title="Example event",
            performers=[Performer(name="Die Ärzte", billing_order=1)],
        )
    )

    result = CliRunner().invoke(
        cli, ["artists", "bootstrap", "--database", str(database)]
    )

    assert result.exit_code == 0
    assert "1 artist created" in result.output
    assert EventStore(database).get_artist("die-arzte") is not None


def test_artists_homepage_enrichment_command_is_available() -> None:
    """The CLI exposes a separate bounded homepage enrichment workflow."""

    result = CliRunner().invoke(cli, ["artists", "enrich-homepages", "--help"])

    assert result.exit_code == 0
    assert "verified artist" in result.output.lower()
    assert "--limit" in result.output


def test_venues_discover_keeps_high_confidence_candidate_for_manual_review(
    monkeypatch, tmp_path
) -> None:
    """Explicit batch discovery never invokes the new-venue auto-approval path."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert_venue(
        VenueRecord(
            id="example-club",
            name="Example Club",
            normalized_name="example club",
        )
    )
    suggestion = VenueCandidate(
        venue_id="example-club",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/123",
        osm_type="node",
        osm_id="123",
        display_name="Example Club, Berlin, Germany",
        address="Suggested Street 1, 10115 Berlin",
        confidence=0.96,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    monkeypatch.setattr(
        "berlin_events_explorer.cli.NominatimVenueProvider.discover",
        lambda self, venue: [suggestion],
    )

    result = CliRunner().invoke(
        cli,
        [
            "venues",
            "discover",
            "--database",
            str(database),
            "--limit",
            "1",
        ],
    )

    pending = store.get_venue("example-club")
    assert result.exit_code == 0
    assert "1 awaiting review" in result.output
    assert pending is not None
    assert pending.status is VenueStatus.CANDIDATE
    assert pending.address is None
