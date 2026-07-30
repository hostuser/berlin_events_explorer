"""Tests for SQLite event and application-log persistence."""

from berlin_events_explorer.storage import EventStore


def test_store_persists_structured_logs_at_supported_levels(tmp_path) -> None:
    """Application diagnostics should retain their level, message, and context."""

    store = EventStore(tmp_path / "events.sqlite")
    store.log(
        level="info",
        event="sync_started",
        message="Starting source synchronization.",
        context={"provider": "mytrueintent"},
    )
    store.log(
        level="debug",
        event="source_response_received",
        message="Received source payload.",
        context={"status_code": 200},
    )

    logs = store.list_logs()

    assert [entry.level for entry in logs] == ["info", "debug"]
    assert logs[0].event == "sync_started"
    assert logs[0].context == {"provider": "mytrueintent"}
    assert logs[1].context == {"status_code": 200}