"""Tests for the canonical event models."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from berlin_events_explorer.models import (
    DatePrecision,
    Event,
    EventSourceRef,
    EventStatus,
    Performer,
    UserRecord,
    UserRole,
    Venue,
    VenueCandidate,
    VenueMetadata,
    VenueRecord,
    VenueStatus,
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


def test_venue_record_preserves_verified_public_metadata() -> None:
    """Canonical venues retain independently verified public details."""

    venue = VenueRecord(
        id="berghain",
        name="Berghain",
        normalized_name="berghain",
        address="Am Wriezener Bahnhof, 10243 Berlin",
        postal_code="10243",
        latitude=52.5112,
        longitude=13.4437,
        website="https://www.berghain.berlin/",
        status=VenueStatus.VERIFIED,
    )

    assert venue.id == "berghain"
    assert venue.website == "https://www.berghain.berlin/"
    assert venue.status is VenueStatus.VERIFIED


def test_venue_metadata_records_field_level_provenance() -> None:
    """Venue metadata must retain the source that supplied each field."""

    metadata = VenueMetadata(
        venue_id="berghain",
        field="address",
        value="Am Wriezener Bahnhof, 10243 Berlin",
        provider="openstreetmap",
        source_url="https://www.openstreetmap.org/node/123",
        confidence=0.98,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    assert metadata.field == "address"
    assert metadata.confidence == 0.98


@pytest.mark.parametrize("venue_id", ["", "Berghain", "berghain!", "two words"])
def test_venue_record_rejects_non_slug_ids(venue_id: str) -> None:
    """Venue IDs are stable, route-safe lowercase slugs."""

    with pytest.raises(ValidationError, match="slug"):
        VenueRecord(id=venue_id, name="Berghain", normalized_name="berghain")


def test_venue_record_rejects_non_http_homepage() -> None:
    """Only public HTTP(S) venue homepages are accepted."""

    with pytest.raises(ValidationError, match="HTTP"):
        VenueRecord(
            id="berghain",
            name="Berghain",
            normalized_name="berghain",
            website="mailto:hello@example.test",
        )


def test_not_a_venue_record_does_not_require_public_metadata() -> None:
    """Source placeholders can be represented without inventing venue details."""

    venue = VenueRecord(
        id="tba",
        name="TBA",
        normalized_name="tba",
        status=VenueStatus.NOT_A_VENUE,
    )

    assert venue.address is None
    assert venue.website is None


def test_venue_candidate_retains_osm_identity_and_discovered_details() -> None:
    """Unselected OSM candidates remain reviewable independently of a venue."""

    candidate = VenueCandidate(
        venue_id="berghain",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/1",
        osm_type="node",
        osm_id="1",
        display_name="Berghain, Friedrichshain-Kreuzberg, Berlin, Deutschland",
        address="Am Wriezener Bahnhof, 10243 Berlin",
        website="https://www.berghain.berlin/",
        latitude=52.5112,
        longitude=13.4437,
        confidence=0.98,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    assert candidate.osm_id == "1"
    assert candidate.address == "Am Wriezener Bahnhof, 10243 Berlin"


def _user_record(**overrides) -> UserRecord:
    """Return a representative account record."""

    now = datetime(2026, 8, 1, tzinfo=UTC)
    fields = {
        "id": 1,
        "email": "markus@example.org",
        "display_name": "Markus",
        "role": UserRole.EDITOR,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }
    fields.update(overrides)
    return UserRecord(**fields)


def test_user_record_normalizes_email_to_lowercase() -> None:
    """Emails must compare case-insensitively, so records store them folded."""

    user = _user_record(email="  Markus@Example.ORG ")

    assert user.email == "markus@example.org"


def test_user_record_rejects_email_without_at_sign() -> None:
    """A user record without a deliverable address is a data error."""

    with pytest.raises(ValidationError):
        _user_record(email="not-an-email")


def test_user_record_never_carries_a_password_hash() -> None:
    """Credential material must stay out of records that reach templates."""

    assert "password_hash" not in UserRecord.model_fields
