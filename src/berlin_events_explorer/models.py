"""Canonical event and provenance models."""

from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventStatus(str, Enum):
    """Known source-level event states."""

    CONFIRMED = "confirmed"
    NEW = "new"
    SOLD_OUT = "sold_out"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class DatePrecision(str, Enum):
    """Precision with which an event's date or time is known."""

    DAY = "day"
    DATE_RANGE = "date_range"
    DATETIME = "datetime"
    UNKNOWN = "unknown"


class LinkType(str, Enum):
    """Purpose of a URL associated with an event or entity."""

    SOURCE = "source"
    EVENT = "event"
    ARTIST = "artist"
    VENUE = "venue"
    TICKETS = "tickets"
    OTHER = "other"


class EventLink(BaseModel):
    """A URL with its relationship to an event or entity."""

    model_config = ConfigDict(frozen=True)

    url: str
    link_type: LinkType = LinkType.OTHER
    label: str | None = None


class EventSourceRef(BaseModel):
    """Provenance identifying the source record behind an event."""

    model_config = ConfigDict(frozen=True)

    provider: str
    source_url: str
    source_record_id: str | None = None
    source_record_hash: str


class Performer(BaseModel):
    """A performer associated with an event."""

    name: str
    role: str | None = None
    billing_order: int | None = Field(default=None, ge=1)
    genres: list[str] = Field(default_factory=list)
    links: list[EventLink] = Field(default_factory=list)


class Venue(BaseModel):
    """A venue, initially identified by its source-provided name."""

    name: str
    normalized_name: str | None = None
    city: str | None = "Berlin"
    country: str | None = "DE"
    address: str | None = None
    postal_code: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    website: str | None = None
    capacity: int | None = Field(default=None, ge=0)
    venue_type: str | None = None


class EnrichmentResult(BaseModel):
    """A value supplied by an external enrichment provider."""

    field: str
    value: Any
    provider: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    retrieved_at: datetime | None = None
    source_url: str | None = None


class Event(BaseModel):
    """Canonical event representation shared by all source providers."""

    id: str
    source: EventSourceRef

    start_date: date | None = None
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    timezone: str = "Europe/Berlin"
    date_precision: DatePrecision = DatePrecision.UNKNOWN

    title: str
    performers: list[Performer] = Field(default_factory=list)
    venue: Venue | None = None

    status: EventStatus = EventStatus.UNKNOWN
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    description: str | None = None
    links: list[EventLink] = Field(default_factory=list)

    raw_data: dict[str, Any] = Field(default_factory=dict)
    enrichment: list[EnrichmentResult] = Field(default_factory=list)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        """Reject events without a meaningful title."""
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value

    @field_validator("end_date")
    @classmethod
    def end_date_must_not_precede_start_date(
        cls, value: date | None, info: Any
    ) -> date | None:
        """Ensure a date range has chronological order."""
        start_date = info.data.get("start_date")
        if value is not None and start_date is not None and value < start_date:
            raise ValueError("end_date must not precede start_date")
        return value
