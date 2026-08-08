"""Typed, safe event-detail observations independent from source event payloads."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from berlin_events_explorer.models import Event, EventStatus


class EventDetails(BaseModel):
    """Latest independently observed public event information with provenance."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    provider: str
    event_url: str | None = None
    ticket_url: str | None = None
    observed_status: EventStatus | None = None
    evidence_url: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    checked_at: datetime
    status_expires_at: datetime | None = None
    last_successful_at: datetime | None = None
    details: dict[str, object] = Field(default_factory=dict)

    @field_validator("event_url", "ticket_url", "evidence_url")
    @classmethod
    def url_must_be_a_safe_public_http_url(cls, value: str | None) -> str | None:
        """Accept only normalized public HTTP(S) URLs suitable for rendering."""

        if value is None:
            return None
        parsed = urlparse(value.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("URL must be a public HTTP(S) URL")
        hostname = parsed.hostname.casefold()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise ValueError("URL must be a public HTTP(S) URL")
        try:
            if not ipaddress.ip_address(hostname).is_global:
                raise ValueError("URL must be a public HTTP(S) URL")
        except ValueError as error:
            if str(error) == "URL must be a public HTTP(S) URL":
                raise
        return urlunparse(parsed._replace(fragment=""))


class EventDetailsProvider(Protocol):
    """A bounded provider that can observe public details for one event."""

    name: str

    def lookup(self, event: Event, *, now: datetime) -> EventDetails | None:
        """Return a verified observation, or None when no safe match exists."""
        ...


def effective_event_status(
    event: Event, details: EventDetails | None, *, now: datetime | None = None
) -> EventStatus:
    """Return source status first, then a non-expired external observation."""

    if event.status is not EventStatus.UNKNOWN:
        return event.status
    if details is None or details.observed_status is None:
        return EventStatus.UNKNOWN
    now = now or datetime.now(timezone.utc)
    if details.status_expires_at is not None:
        expires_at = details.status_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            return EventStatus.UNKNOWN
    return details.observed_status
