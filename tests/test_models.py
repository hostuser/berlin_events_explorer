"""Tests for the canonical event models."""

from datetime import date

import pytest
from pydantic import ValidationError

from berlin_events_explorer.models import (
    DatePrecision,
    Event,
    EventSourceRef,
    EventStatus,
    Performer,
    Venue,
)


@pytest.fixture
def source_ref() -> EventSourceRef:
    """Return representative source provenance."""
    return EventSourceRef(
        provider="mytrueintent",
        source_url="https://example.test/events.csv",
        source_record_id="row-1",
        source_record_hash="abc123",
    )


def test_event_serializes_nested_domain_data(source_ref: EventSourceRef) -> None:
    """Nested performers and venues should serialize to JSON-compatible data."""
    event = Event(
        id="event-1",
        source=source_ref,
        start_date=date(2026, 7, 13),
        date_precision=DatePrecision.DAY,
        title="Example show",
        performers=[Performer(name="Example Artist", billing_order=1)],
        venue=Venue(name="Example Venue"),
        status=EventStatus.CONFIRMED,
    )

    data = event.model_dump(mode="json")

    assert data["start_date"] == "2026-07-13"
    assert data["performers"][0]["name"] == "Example Artist"
    assert data["venue"]["city"] == "Berlin"


def test_event_rejects_blank_title(source_ref: EventSourceRef) -> None:
    """Events must have a human-readable title."""
    with pytest.raises(ValidationError, match="title must not be blank"):
        Event(id="event-1", source=source_ref, title=" ")


def test_event_rejects_reversed_date_range(source_ref: EventSourceRef) -> None:
    """A date range must not end before it starts."""
    with pytest.raises(ValidationError, match="end_date must not precede start_date"):
        Event(
            id="event-1",
            source=source_ref,
            start_date=date(2026, 7, 14),
            end_date=date(2026, 7, 13),
            title="Example show",
        )
