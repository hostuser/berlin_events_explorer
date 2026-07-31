"""Canonical event and provenance models."""

from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
import re
from typing import Any
from urllib.parse import urlparse

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


class VenueStatus(str, Enum):
    """Editorial state of a canonical venue record."""

    UNRESOLVED = "unresolved"
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REJECTED = "rejected"
    NOT_A_VENUE = "not_a_venue"


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


class VenueRecord(BaseModel):
    """Canonical venue metadata independent of any individual event payload."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    normalized_name: str
    city: str | None = "Berlin"
    country: str | None = "DE"
    district: str | None = None
    address: str | None = None
    postal_code: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    website: str | None = None
    osm_type: str | None = None
    osm_id: str | None = None
    status: VenueStatus = VenueStatus.UNRESOLVED
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_checked_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def id_must_be_a_slug(cls, value: str) -> str:
        """Require a stable URL-safe primary key."""

        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("id must be a lowercase slug")
        return value

    @field_validator("website")
    @classmethod
    def website_must_be_http_url(cls, value: str | None) -> str | None:
        """Allow only safe public website URLs."""

        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("website must be an HTTP(S) URL")
        return value


class ArtistStatus(str, Enum):
    """Editorial state of a canonical artist record."""

    UNRESOLVED = "unresolved"
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REJECTED = "rejected"
    NOT_AN_ARTIST = "not_an_artist"


class ArtistRecord(BaseModel):
    """Canonical artist metadata independent of any individual event payload."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    normalized_name: str
    artist_type: str | None = None
    country: str | None = None
    disambiguation: str | None = None
    musicbrainz_id: str | None = None
    musicbrainz_url: str | None = None
    genres: list[str] = Field(default_factory=list)
    status: ArtistStatus = ArtistStatus.UNRESOLVED
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_checked_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def id_must_be_a_slug(cls, value: str) -> str:
        """Require a stable URL-safe primary key."""
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("id must be a lowercase slug")
        return value

    @field_validator("musicbrainz_url")
    @classmethod
    def musicbrainz_url_must_be_http_url(cls, value: str | None) -> str | None:
        """Allow only safe public MusicBrainz URLs."""
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("musicbrainz_url must be an HTTP(S) URL")
        return value


class ArtistMetadata(BaseModel):
    """Provenance for one selected canonical artist field."""

    model_config = ConfigDict(frozen=True)

    artist_id: str
    field: str
    value: Any
    provider: str
    source_url: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    retrieved_at: datetime | None = None


class ArtistCandidate(BaseModel):
    """A reviewable external candidate for one canonical artist."""

    model_config = ConfigDict(frozen=True)

    artist_id: str
    provider: str
    source_url: str
    musicbrainz_id: str
    display_name: str
    artist_type: str | None = None
    country: str | None = None
    disambiguation: str | None = None
    genres: list[str] = Field(default_factory=list)
    provider_score: int | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    retrieved_at: datetime


class VenueMetadata(BaseModel):
    """Provenance for one selected canonical venue field."""

    model_config = ConfigDict(frozen=True)

    venue_id: str
    field: str
    value: Any
    provider: str
    source_url: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    retrieved_at: datetime | None = None


class VenueCandidate(BaseModel):
    """A reviewable external candidate for one canonical venue."""

    model_config = ConfigDict(frozen=True)

    venue_id: str
    provider: str
    source_url: str
    osm_type: str
    osm_id: str
    display_name: str
    address: str | None = None
    postal_code: str | None = None
    district: str | None = None
    website: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    confidence: float = Field(ge=0, le=1)
    retrieved_at: datetime


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


def event_search_text(event: Event) -> str:
    """Build a case-folded haystack from title, venue, and performers."""

    parts = [event.title]
    if event.venue is not None:
        parts.append(event.venue.name)
    parts.extend(performer.name for performer in event.performers)
    return " ".join(parts).casefold()


class UserRole(str, Enum):
    """Authorization tier of an account, ordered user < editor < admin."""

    USER = "user"
    EDITOR = "editor"
    ADMIN = "admin"


def normalize_email(value: str) -> str:
    """Fold an address so storage and lookups are case-insensitive."""

    value = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("email must be a valid address")
    return value


class UserRecord(BaseModel):
    """One account, without credential material."""

    model_config = ConfigDict(frozen=True)

    id: int
    email: str
    display_name: str
    role: UserRole
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None

    @field_validator("email")
    @classmethod
    def email_must_be_a_normalized_address(cls, value: str) -> str:
        """Fold addresses so lookups and uniqueness are case-insensitive."""

        return normalize_email(value)
