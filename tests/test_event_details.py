"""Tests for safe, independently persisted event-detail observations."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from berlin_events_explorer.event_details import EventDetails, effective_event_status
from berlin_events_explorer.models import Event, EventSourceRef, EventStatus


def _event(status: EventStatus = EventStatus.UNKNOWN) -> Event:
    return Event(
        id="event-1",
        source=EventSourceRef(
            provider="test",
            source_url="https://source.example/events",
            source_record_hash="hash",
        ),
        title="Example event",
        status=status,
    )


def test_event_details_accepts_public_http_urls() -> None:
    details = EventDetails(
        event_id="event-1",
        provider="example",
        event_url="https://events.example/shows/example",
        ticket_url="https://tickets.example/buy/123",
        evidence_url="https://events.example/shows/example",
        checked_at=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert details.ticket_url == "https://tickets.example/buy/123"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "mailto:tickets@example.test",
        "https://user:password@example.test/event",
        "https://localhost/event",
        "https://127.0.0.1/event",
        "https://[::1]/event",
        "not a url",
    ],
)
def test_event_details_rejects_unsafe_external_urls(url: str) -> None:
    with pytest.raises(ValidationError, match="public HTTP"):
        EventDetails(
            event_id="event-1",
            provider="example",
            event_url=url,
            checked_at=datetime(2026, 8, 2, tzinfo=UTC),
        )


def test_source_status_wins_over_fresh_observed_status() -> None:
    details = EventDetails(
        event_id="event-1",
        provider="example",
        observed_status=EventStatus.SOLD_OUT,
        checked_at=datetime(2026, 8, 2, tzinfo=UTC),
        status_expires_at=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert (
        effective_event_status(_event(EventStatus.CANCELLED), details)
        is EventStatus.CANCELLED
    )


def test_fresh_observed_status_enriches_unknown_source_status() -> None:
    details = EventDetails(
        event_id="event-1",
        provider="example",
        observed_status=EventStatus.SOLD_OUT,
        checked_at=datetime.now(UTC),
        status_expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    assert effective_event_status(_event(), details) is EventStatus.SOLD_OUT


def test_expired_observed_status_is_not_displayed_as_current() -> None:
    now = datetime(2026, 8, 2, tzinfo=UTC)
    details = EventDetails(
        event_id="event-1",
        provider="example",
        observed_status=EventStatus.SOLD_OUT,
        checked_at=now - timedelta(days=2),
        status_expires_at=now - timedelta(days=1),
    )

    assert effective_event_status(_event(), details, now=now) is EventStatus.UNKNOWN
