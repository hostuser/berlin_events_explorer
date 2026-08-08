"""Tests for the bounded, conservative source-link event-details augmenter."""

from datetime import UTC, datetime

from click.testing import CliRunner

from berlin_events_explorer.cli import cli
from berlin_events_explorer.event_details_augmentation import (
    augment_event_details,
    augment_ticketmaster_event_details,
)
from berlin_events_explorer.models import Event, EventSourceRef, Venue
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.ticketmaster import TicketmasterCandidate


def _event(event_id: str) -> Event:
    return Event(
        id=event_id,
        source=EventSourceRef(
            provider="test-source",
            source_url="https://source.example/events",
            source_record_hash=event_id,
        ),
        title=f"Event {event_id}",
        start_date=datetime(2026, 9, 15, tzinfo=UTC).date(),
        venue=Venue(name="Lido"),
    )


def test_source_link_augmenter_records_only_source_facts_in_bounded_batch(
    tmp_path,
) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one"))
    store.upsert(_event("two"))

    result = augment_event_details(store, limit=1, now=datetime(2026, 8, 2, tzinfo=UTC))

    assert result.considered == 1
    assert result.updated == 1
    details = store.get_event_details("one")
    assert details is not None
    assert details.event_url == "https://source.example/events"
    assert details.ticket_url is None


def test_source_link_augmenter_is_freshly_idempotent(tmp_path) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one"))
    now = datetime(2026, 8, 2, tzinfo=UTC)

    first = augment_event_details(store, limit=10, now=now)
    second = augment_event_details(store, limit=10, now=now)

    assert first.updated == 1
    assert second.considered == 0


def test_event_details_augmenter_cli_reports_bounded_summary(tmp_path) -> None:
    database = tmp_path / "events.sqlite"
    EventStore(database).upsert(_event("one"))

    result = CliRunner().invoke(
        cli, ["augment-event-details", "--database", str(database), "--limit", "1"]
    )

    assert result.exit_code == 0, result.output
    assert "Event details augment complete" in result.output
    assert "1 updated, 1 considered" in result.output


def test_ticketmaster_cli_requires_an_explicit_configured_api_key(tmp_path) -> None:
    database = tmp_path / "events.sqlite"
    EventStore(database).upsert(_event("one"))

    result = CliRunner().invoke(
        cli,
        [
            "augment-event-details",
            "--provider",
            "ticketmaster-discovery",
            "--database",
            str(database),
            "--limit",
            "1",
            "--dry-run",
        ],
        env={"BERLIN_EVENTS_TICKETMASTER_API_KEY": ""},
    )

    assert result.exit_code != 0
    assert "BERLIN_EVENTS_TICKETMASTER_API_KEY" in result.output


def test_ai_research_cli_requires_searxng_and_model_configuration(tmp_path) -> None:
    database = tmp_path / "events.sqlite"
    EventStore(database).upsert(_event("one"))

    result = CliRunner().invoke(
        cli,
        [
            "augment-event-details",
            "--provider",
            "searxng-pydantic-ai",
            "--database",
            str(database),
            "--limit",
            "1",
            "--dry-run",
        ],
        env={
            "BERLIN_EVENTS_SEARXNG_URL": "",
            "BERLIN_EVENTS_EVENT_RESEARCH_MODEL": "",
        },
    )

    assert result.exit_code != 0
    assert "BERLIN_EVENTS_SEARXNG_URL" in result.output


def test_ai_research_cli_requires_zai_key_for_a_zai_model(tmp_path) -> None:
    database = tmp_path / "events.sqlite"
    EventStore(database).upsert(_event("one"))

    result = CliRunner().invoke(
        cli,
        [
            "augment-event-details",
            "--provider",
            "searxng-pydantic-ai",
            "--database",
            str(database),
            "--limit",
            "1",
            "--dry-run",
        ],
        env={
            "BERLIN_EVENTS_SEARXNG_URL": "https://search.example",
            "BERLIN_EVENTS_EVENT_RESEARCH_MODEL": "zai:glm-5-turbo",
            "ZAI_API_KEY": "",
        },
    )

    assert result.exit_code != 0
    assert "ZAI_API_KEY" in result.output


class _MatchingTicketmasterClient:
    def find_candidates(self, event: Event) -> list[TicketmasterCandidate]:
        return [
            TicketmasterCandidate(
                provider_event_id="tm-123",
                title=event.title,
                local_date=event.start_date,
                venue_name=event.venue.name if event.venue else None,
                event_url="https://www.ticketmaster.de/event/tm-123",
            )
        ]


def test_ticketmaster_augmenter_dry_run_reports_match_without_persisting(
    tmp_path,
) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one"))

    result = augment_ticketmaster_event_details(
        store,
        _MatchingTicketmasterClient(),
        limit=1,
        now=datetime(2026, 8, 2, tzinfo=UTC),
        dry_run=True,
    )

    assert result.considered == 1
    assert result.matched == 1
    assert result.updated == 0
    assert result.outcomes[0].provider_event_id == "tm-123"
    assert store.get_event_details("one") is None


def test_ticketmaster_augmenter_persists_only_a_matched_official_url(tmp_path) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one"))

    result = augment_ticketmaster_event_details(
        store,
        _MatchingTicketmasterClient(),
        limit=1,
        now=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert result.updated == 1
    details = store.get_event_details("one")
    assert details is not None
    assert details.provider == "ticketmaster-discovery"
    assert details.event_url == "https://www.ticketmaster.de/event/tm-123"
    assert details.ticket_url == "https://www.ticketmaster.de/event/tm-123"
    assert details.details == {"provider_event_id": "tm-123"}
