"""Tests for the bounded background worker."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from berlin_events_explorer.cli import cli
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.worker import run_worker


def test_development_worker_units_serialize_timer_invocations() -> None:
    """The development timer should run one-shot workers without overlap."""

    root = Path(__file__).parents[1]
    service = (root / "deploy" / "berlin-events-worker-development.service").read_text()
    timer = (root / "deploy" / "berlin-events-worker-development.timer").read_text()

    assert "Type=oneshot" in service
    assert "/usr/bin/flock --nonblock --conflict-exit-code 75" in service
    assert "berlin-events worker" in service
    assert "SuccessExitStatus=75" in service
    assert "OnCalendar=*:0/30" in timer
    assert "Persistent=true" in timer
    assert "berlin-events-worker-development.service" in timer

    web_service = (root / "deploy" / "berlin-events-development.service").read_text()
    assert "--sync-interval-minutes 0" in web_service


def test_production_worker_units_run_hourly_without_web_process_sync() -> None:
    """Production should separate hourly enrichment from HTTP request serving."""

    root = Path(__file__).parents[1]
    web_service = (root / "deploy" / "berlin-events-production.service").read_text()
    worker_service = (
        root / "deploy" / "berlin-events-worker-production.service"
    ).read_text()
    timer = (root / "deploy" / "berlin-events-worker-production.timer").read_text()

    assert "--sync-interval-minutes 0" in web_service
    assert "--port 8000" in web_service
    assert "/usr/bin/flock --nonblock --conflict-exit-code 75" in worker_service
    assert (
        "--database /home/oskar-maria/projects/dev/berlin-events-explorer/events.sqlite"
        in worker_service
    )
    assert "SuccessExitStatus=75" in worker_service
    assert "OnCalendar=hourly" in timer
    assert "Persistent=true" in timer
    assert "berlin-events-worker-production.service" in timer


def test_worker_command_exposes_bounded_batch_options() -> None:
    """Operators should be able to cap worker provider work from the CLI."""

    result = CliRunner().invoke(cli, ["worker", "--help"])

    assert result.exit_code == 0, result.output
    assert "--artist-limit" in result.output
    assert "--homepage-limit" in result.output
    assert "--database" in result.output


def test_run_worker_records_successful_phases(tmp_path) -> None:
    """A completed worker pass should persist its phase summaries for operators."""

    store = EventStore(tmp_path / "events.sqlite")

    result = run_worker(
        store,
        sync_phase=lambda: {"created": 2, "updated": 1},
        artist_phase=lambda: {"checked": 3, "queued": 1},
        homepage_phase=lambda: {"checked": 1, "found": 1},
    )

    assert result.status == "succeeded"
    assert result.summary == {
        "sync": {"created": 2, "updated": 1},
        "artist_enrichment": {"checked": 3, "queued": 1},
        "homepage_enrichment": {"checked": 1, "found": 1},
    }
    assert result.finished_at is not None
    assert store.latest_worker_run() == result


def test_run_worker_records_failure_and_reraises(tmp_path) -> None:
    """A failed phase should be visible in the run history and fail the timer unit."""

    store = EventStore(tmp_path / "events.sqlite")

    def fail() -> dict[str, int]:
        raise RuntimeError("MusicBrainz unavailable")

    try:
        run_worker(
            store,
            sync_phase=lambda: {"created": 0},
            artist_phase=fail,
            homepage_phase=lambda: {"checked": 0},
        )
    except RuntimeError as exc:
        assert str(exc) == "MusicBrainz unavailable"
    else:
        raise AssertionError("The worker must fail when a phase fails.")

    run = store.latest_worker_run()
    assert run is not None
    assert run.status == "failed"
    assert run.error == "MusicBrainz unavailable"
    assert run.finished_at is not None
    assert run.summary == {"sync": {"created": 0}}
