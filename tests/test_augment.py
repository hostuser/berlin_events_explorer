"""Tests for event augmentation."""

from datetime import date, datetime, timezone

import berlin_events_explorer.cli as cli_module
from click.testing import CliRunner

from berlin_events_explorer.augment import augment_events
from berlin_events_explorer.models import Event, EventSourceRef, Performer, Venue
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.sync import SyncResult
from berlin_events_explorer.venue_ingestion import VenueIngestionResult


def _seed_event_for_augmentation(store: EventStore) -> None:
    """Insert a single event that can be enriched by local rules."""
    event = Event(
        id="augment-1",
        source=EventSourceRef(
            provider="mytrueintent",
            source_url="https://example.test/events.csv",
            source_record_id="1",
            source_record_hash="seed-hash",
        ),
        start_date=date(2026, 7, 13),
        title="House Of Noise",
        performers=[Performer(name="DJ Example", billing_order=1)],
        venue=Venue(name="  Club   House"),
        notes=["Acoustic techno set"],
        tags=["live"],
    )
    store.upsert(event, now=datetime(2026, 7, 13, tzinfo=timezone.utc))


def test_augment_updates_events_with_local_rules(tmp_path) -> None:
    """Venue normalisation and tag enrichment should be persisted."""
    store = EventStore(tmp_path / "events.sqlite")
    _seed_event_for_augmentation(store)

    result = augment_events(store, now=datetime(2026, 7, 14, tzinfo=timezone.utc))

    events = store.list_events()
    assert len(events) == 1
    assert result.updated == 1
    assert result.unchanged == 0

    event = events[0]
    assert event.venue is not None
    assert event.venue.normalized_name == "Club House"
    assert event.tags == ["acoustic", "house", "live", "techno"]
    assert any(
        enrichment.field == "venue.normalized_name" and enrichment.value == "Club House"
        for enrichment in event.enrichment
    )
    assert any(
        enrichment.field == "tags" and enrichment.value == "techno"
        for enrichment in event.enrichment
    )


def test_augment_is_idempotent(tmp_path) -> None:
    """Running augmentation twice should not change events the second time."""
    store = EventStore(tmp_path / "events.sqlite")
    _seed_event_for_augmentation(store)

    first = augment_events(store, now=datetime(2026, 7, 14, tzinfo=timezone.utc))
    second = augment_events(store, now=datetime(2026, 7, 15, tzinfo=timezone.utc))

    assert first.updated == 1
    assert first.unchanged == 0
    assert second.updated == 0
    assert second.unchanged == 1


def test_augment_cli_command_output(tmp_path) -> None:
    """The augment CLI command should run successfully."""
    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    _seed_event_for_augmentation(store)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["augment", "--database", str(database)])

    assert result.exit_code == 0
    assert "Augment complete" in result.output
    assert "1 updated" in result.output
    assert EventStore(database).count_events("mytrueintent") == 1


def test_sync_cli_clear_cache_option(tmp_path, monkeypatch) -> None:
    """The sync command should clear on-disk cache before syncing when requested."""

    class DummyCache:
        def __init__(self) -> None:
            self.cleared = False

        def clear(self) -> None:
            self.cleared = True

        def __enter__(self) -> "DummyCache":
            return self

        def __exit__(self, *_) -> None:
            return None

    class DummyClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, *_) -> None:
            return None

    cache = DummyCache()

    def fake_open_sync_cache(*_args, **_kwargs) -> DummyCache:
        return cache

    def fake_sync_source_and_ingest_venues(
        source,
        store,
        client,
        *,
        http_cache=None,
        auto_approve_threshold=0.9,
    ) -> tuple[SyncResult, VenueIngestionResult]:
        assert http_cache is cache
        assert cache.cleared
        return (
            SyncResult(downloaded=True, created=0, updated=0, unchanged=0),
            VenueIngestionResult(0, 0, 0, 0, 0, 0),
        )

    monkeypatch.setattr(cli_module, "open_sync_cache", fake_open_sync_cache)
    monkeypatch.setattr(
        cli_module,
        "sync_source_and_ingest_venues",
        fake_sync_source_and_ingest_venues,
    )
    monkeypatch.setattr(cli_module.httpx, "Client", DummyClient)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli,
        [
            "sync",
            "--database",
            str(tmp_path / "events.sqlite"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--clear-cache",
        ],
    )

    assert result.exit_code == 0
    assert "Sync cache cleared" in result.output


def test_sync_cli_keeps_cache_by_default(tmp_path, monkeypatch) -> None:
    """No cache clear happens unless the user passes --clear-cache."""

    class DummyCache:
        def __init__(self) -> None:
            self.cleared = False

        def clear(self) -> None:
            self.cleared = True

        def __enter__(self) -> "DummyCache":
            return self

        def __exit__(self, *_) -> None:
            return None

    class DummyClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self) -> "DummyClient":
            return self

        def __exit__(self, *_) -> None:
            return None

    cache = DummyCache()

    def fake_open_sync_cache(*_args, **_kwargs) -> DummyCache:
        return cache

    def fake_sync_source_and_ingest_venues(
        source,
        store,
        client,
        *,
        http_cache=None,
        auto_approve_threshold=0.9,
    ) -> tuple[SyncResult, VenueIngestionResult]:
        assert http_cache is cache
        assert not cache.cleared
        return (
            SyncResult(downloaded=True, created=0, updated=0, unchanged=0),
            VenueIngestionResult(0, 0, 0, 0, 0, 0),
        )

    monkeypatch.setattr(cli_module, "open_sync_cache", fake_open_sync_cache)
    monkeypatch.setattr(
        cli_module,
        "sync_source_and_ingest_venues",
        fake_sync_source_and_ingest_venues,
    )
    monkeypatch.setattr(cli_module.httpx, "Client", DummyClient)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli,
        [
            "sync",
            "--database",
            str(tmp_path / "events.sqlite"),
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
    )

    assert result.exit_code == 0
    assert "Sync cache cleared" not in result.output
