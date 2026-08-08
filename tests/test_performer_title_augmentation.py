"""Tests for conservative AI performer extraction during event ingestion."""

from datetime import UTC, date, datetime

from pydantic_ai import Agent
from click.testing import CliRunner
from pydantic_ai.models.test import TestModel

from berlin_events_explorer import cli as cli_module
from berlin_events_explorer.cli import cli
from berlin_events_explorer.models import Event, EventSourceRef, Performer, Venue
from berlin_events_explorer.performer_title_augmentation import (
    PerformerTitleDecision,
    TitlePerformerExtractor,
    ingest_new_event_performers,
)
from berlin_events_explorer.storage import EventStore


def _event(
    title: str = "Magma Festival - Anthony Naples, Deki Alem und Joy Orbison plus more tba",
) -> Event:
    return Event(
        id="magma-festival",
        source=EventSourceRef(
            provider="test-source",
            source_url="https://source.example/events",
            source_record_hash="magma-festival",
        ),
        start_date=date(2026, 9, 15),
        title=title,
        performers=[Performer(name=title, billing_order=1)],
        venue=Venue(name="Lido"),
    )


def test_extractor_returns_ordered_performers_from_a_list_title() -> None:
    extractor = TitlePerformerExtractor(
        Agent[object, PerformerTitleDecision](
            TestModel(
                custom_output_args={
                    "performer_names": [
                        "Anthony Naples",
                        "Deki Alem",
                        "Joy Orbison",
                    ]
                }
            ),
            output_type=PerformerTitleDecision,
        )
    )

    performers = extractor.extract(_event().title)

    assert [performer.name for performer in performers] == [
        "Anthony Naples",
        "Deki Alem",
        "Joy Orbison",
    ]
    assert [performer.billing_order for performer in performers] == [1, 2, 3]


def test_extractor_rejects_names_not_written_in_the_billed_suffix() -> None:
    extractor = TitlePerformerExtractor(
        Agent[object, PerformerTitleDecision](
            TestModel(
                custom_output_args={
                    "performer_names": ["Magma Festival", "Joy Orbison"]
                }
            ),
            output_type=PerformerTitleDecision,
        )
    )

    assert extractor.extract(_event().title) == []


def test_new_event_ingestion_replaces_a_combined_source_performer_label(
    tmp_path,
) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    event = _event()
    store.upsert(event)

    class _Extractor:
        def extract(self, title: str) -> list[Performer]:
            assert title == event.title
            return [
                Performer(name="Anthony Naples", billing_order=1),
                Performer(name="Deki Alem", billing_order=2),
                Performer(name="Joy Orbison", billing_order=3),
            ]

    result = ingest_new_event_performers(
        store,
        _Extractor(),
        event_ids=[event.id],
        now=datetime(2026, 8, 8, tzinfo=UTC),
    )

    stored = store.get_event(event.id)
    assert result.extracted == 1
    assert stored is not None
    assert [performer.name for performer in stored.performers] == [
        "Anthony Naples",
        "Deki Alem",
        "Joy Orbison",
    ]
    assert stored.title == event.title
    assert stored.enrichment[-1].provider == "pydantic-ai-title-performers"


def test_new_event_ingestion_keeps_source_performers_when_ai_returns_no_safe_result(
    tmp_path,
) -> None:
    store = EventStore(tmp_path / "events.sqlite")
    event = _event()
    store.upsert(event)

    class _NoMatchExtractor:
        def extract(self, title: str) -> list[Performer]:
            return []

    result = ingest_new_event_performers(
        store, _NoMatchExtractor(), event_ids=[event.id]
    )

    stored = store.get_event(event.id)
    assert result.no_match == 1
    assert stored is not None
    assert stored.performers == event.performers


def test_existing_performer_cli_dry_run_filters_an_inclusive_event_date_range(
    monkeypatch, tmp_path
) -> None:
    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    in_range = _event()
    before_range = _event().model_copy(
        update={"id": "before-range", "start_date": date(2026, 9, 14)}
    )
    after_range = _event().model_copy(
        update={"id": "after-range", "start_date": date(2026, 9, 16)}
    )
    store.upsert(in_range)
    store.upsert(before_range)
    store.upsert(after_range)

    class _Extractor:
        def extract(self, title: str) -> list[Performer]:
            assert title == in_range.title
            return [
                Performer(name="Anthony Naples", billing_order=1),
                Performer(name="Deki Alem", billing_order=2),
                Performer(name="Joy Orbison", billing_order=3),
            ]

    monkeypatch.setattr(
        cli_module, "performer_extractor_from_environment", lambda **_: _Extractor()
    )

    result = CliRunner().invoke(
        cli,
        [
            "augment-performers",
            "--database",
            str(database),
            "--from-date",
            "2026-09-15",
            "--to-date",
            "2026-09-15",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    normalized_output = " ".join(result.output.split())
    assert "1 would update" in normalized_output
    assert "1 considered" in normalized_output
    stored = EventStore(database).get_event(in_range.id)
    assert stored is not None
    assert stored.performers == in_range.performers
