"""Tests for Pydantic AI decisions constrained to SearXNG result URLs."""

from datetime import UTC, date, datetime

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel

from berlin_events_explorer.ai_event_research import (
    EventResearchDecision,
    SearxngEventResearcher,
    create_event_research_model,
)
from berlin_events_explorer.models import Event, EventSourceRef, Venue
from berlin_events_explorer.searxng import SearxngResult


class _SearchClient:
    def search(self, query: str, *, limit: int) -> list[SearxngResult]:
        assert query == '"Example Show" Berlin 2026-09-15 "Lido"'
        assert limit == 5
        return [
            SearxngResult(
                title="Example Show | Lido Berlin",
                url="https://lido-berlin.de/events/example-show",
                snippet="Official listing for Example Show.",
            ),
            SearxngResult(
                title="Example Show tickets",
                url="https://tickets.example/example-show",
                snippet="Tickets for Example Show.",
            ),
        ]


def _event() -> Event:
    return Event(
        id="example-show",
        source=EventSourceRef(
            provider="test-source",
            source_url="https://source.example/events",
            source_record_hash="example-show",
        ),
        title="Example Show",
        start_date=date(2026, 9, 15),
        venue=Venue(name="Lido"),
    )


def test_zai_model_uses_the_openai_compatible_zai_endpoint() -> None:
    model = create_event_research_model("zai:glm-5-turbo", zai_api_key="test-key")

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "glm-5-turbo"
    assert str(model._provider.base_url) == "https://api.z.ai/api/coding/paas/v4/"


def test_researcher_returns_only_urls_that_appeared_in_search_results() -> None:
    agent = Agent[object, EventResearchDecision](
        TestModel(
            custom_output_args={
                "matched": True,
                "event_url": "https://lido-berlin.de/events/example-show",
                "ticket_url": "https://tickets.example/example-show",
                "evidence_url": "https://lido-berlin.de/events/example-show",
                "summary": "Example Show is listed at Lido Berlin.",
            }
        ),
        output_type=EventResearchDecision,
    )
    researcher = SearxngEventResearcher(_SearchClient(), agent=agent)

    research = researcher.lookup(_event(), now=datetime(2026, 8, 2, tzinfo=UTC))

    assert research is not None
    assert research.event_url == "https://lido-berlin.de/events/example-show"
    assert research.ticket_url == "https://tickets.example/example-show"
    assert research.summary == "Example Show is listed at Lido Berlin."


def test_researcher_rejects_urls_not_returned_by_searxng() -> None:
    agent = Agent[object, EventResearchDecision](
        TestModel(
            custom_output_args={
                "matched": True,
                "event_url": "https://unrelated.example/fake-event",
                "evidence_url": "https://unrelated.example/fake-event",
                "summary": "This must not be persisted.",
            }
        ),
        output_type=EventResearchDecision,
    )
    researcher = SearxngEventResearcher(_SearchClient(), agent=agent)

    assert researcher.lookup(_event(), now=datetime(2026, 8, 2, tzinfo=UTC)) is None
