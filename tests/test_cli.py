"""Tests for the command-line interface."""

from datetime import timedelta
from pathlib import Path

from click.testing import CliRunner

from berlin_events_explorer.cli import cli


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
        ],
    )

    assert result.exit_code == 0
    assert received["database"] == Path(tmp_path / "events.sqlite")
    assert received["sync_interval"] == timedelta(minutes=15)


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
