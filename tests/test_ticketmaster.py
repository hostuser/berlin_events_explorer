"""Strict Ticketmaster Discovery candidate matching tests."""

from datetime import date

import httpx
import pytest

from berlin_events_explorer.models import Event, EventSourceRef, Venue
from berlin_events_explorer.ticketmaster import (
    TicketmasterCandidate,
    TicketmasterDiscoveryClient,
    TicketmasterProviderError,
    match_ticketmaster_candidates,
)


def _event(*, title: str = "Cassandra Jenkins", venue: str | None = "Lido") -> Event:
    return Event(
        id="event-1",
        source=EventSourceRef(
            provider="test-source",
            source_url="https://source.example/events/1",
            source_record_hash="event-1",
        ),
        title=title,
        start_date=date(2026, 9, 15),
        venue=Venue(name=venue) if venue is not None else None,
    )


def _candidate(
    *,
    event_id: str = "tm-123",
    title: str = "Cassandra Jenkins",
    event_date: date = date(2026, 9, 15),
    venue: str | None = "Lido",
) -> TicketmasterCandidate:
    return TicketmasterCandidate(
        provider_event_id=event_id,
        title=title,
        local_date=event_date,
        venue_name=venue,
        event_url="https://www.ticketmaster.de/event/tm-123",
    )


def test_match_accepts_an_exact_title_date_and_venue() -> None:
    match = match_ticketmaster_candidates(_event(), [_candidate()])

    assert match is not None
    assert match.candidate.provider_event_id == "tm-123"
    assert match.confidence == 1.0
    assert match.rationale == ("title_exact", "date_exact", "venue_exact")


def test_match_rejects_a_conflicting_event_date() -> None:
    match = match_ticketmaster_candidates(
        _event(), [_candidate(event_date=date(2026, 9, 16))]
    )

    assert match is None


def test_match_rejects_a_conflicting_venue() -> None:
    match = match_ticketmaster_candidates(_event(), [_candidate(venue="Columbiahalle")])

    assert match is None


def test_match_rejects_an_ambiguous_candidate_set() -> None:
    match = match_ticketmaster_candidates(
        _event(), [_candidate(event_id="tm-1"), _candidate(event_id="tm-2")]
    )

    assert match is None


def test_match_rejects_title_substrings() -> None:
    match = match_ticketmaster_candidates(_event(), [_candidate(title="Cassandra")])

    assert match is None


def test_discovery_client_parses_a_safe_candidate_and_scopes_the_search() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/discovery/v2/events.json"
        assert request.url.params["apikey"] == "test-key"
        assert request.url.params["city"] == "Berlin"
        assert request.url.params["countryCode"] == "DE"
        assert request.url.params["startDateTime"] == "2026-09-15T00:00:00Z"
        assert request.url.params["endDateTime"] == "2026-09-15T23:59:59Z"
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "events": [
                        {
                            "id": "tm-123",
                            "name": "Cassandra Jenkins",
                            "dates": {"start": {"localDate": "2026-09-15"}},
                            "url": "https://www.ticketmaster.de/event/tm-123",
                            "_embedded": {"venues": [{"name": "Lido"}]},
                        }
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(responder)) as http_client:
        client = TicketmasterDiscoveryClient("test-key", http_client)
        candidates = client.find_candidates(_event())

    assert candidates == [_candidate()]


def test_discovery_client_turns_unauthorized_responses_into_a_safe_error() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(401))
    ) as http_client:
        client = TicketmasterDiscoveryClient("test-key", http_client)
        with pytest.raises(TicketmasterProviderError, match="authentication"):
            client.find_candidates(_event())
