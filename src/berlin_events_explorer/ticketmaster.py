"""Strict, bounded matching for Ticketmaster Discovery event candidates.

This module deliberately separates parsing/matching from network access. An event
is eligible only when a single candidate exactly agrees on title, date, and venue
when source venue information is available.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from berlin_events_explorer.models import Event


@dataclass(frozen=True)
class TicketmasterCandidate:
    """The small, safe subset of a Ticketmaster Discovery event response."""

    provider_event_id: str
    title: str
    local_date: date | None
    venue_name: str | None
    event_url: str | None


class TicketmasterProviderError(RuntimeError):
    """A non-sensitive Ticketmaster API access or response error."""


class TicketmasterDiscoveryClient:
    """Small authenticated wrapper around the official Discovery search endpoint."""

    _events_url = "https://app.ticketmaster.com/discovery/v2/events.json"

    def __init__(self, api_key: str, client: httpx.Client) -> None:
        if not api_key.strip():
            raise ValueError("Ticketmaster API key must not be blank")
        self._api_key = api_key
        self._client = client

    def find_candidates(self, event: Event) -> list[TicketmasterCandidate]:
        """Return a constrained set of candidate events for an exact local date."""

        if event.start_date is None:
            return []
        target_date = event.start_date.isoformat()
        try:
            response = self._client.get(
                self._events_url,
                params={
                    "apikey": self._api_key,
                    "keyword": event.title,
                    "city": "Berlin",
                    "countryCode": "DE",
                    "startDateTime": f"{target_date}T00:00:00Z",
                    "endDateTime": f"{target_date}T23:59:59Z",
                    "size": 20,
                },
            )
        except httpx.RequestError as exc:
            raise TicketmasterProviderError("Ticketmaster request failed") from exc
        if response.status_code in {401, 403}:
            raise TicketmasterProviderError("Ticketmaster authentication failed")
        if response.status_code == 429:
            raise TicketmasterProviderError("Ticketmaster rate limit reached")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TicketmasterProviderError("Ticketmaster request failed") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise TicketmasterProviderError(
                "Ticketmaster returned invalid JSON"
            ) from exc
        return _parse_ticketmaster_candidates(payload)


def _parse_ticketmaster_candidates(payload: object) -> list[TicketmasterCandidate]:
    """Extract the minimally necessary matching fields from a Discovery response."""

    if not isinstance(payload, dict):
        return []
    embedded = payload.get("_embedded")
    if not isinstance(embedded, dict):
        return []
    events = embedded.get("events")
    if not isinstance(events, list):
        return []
    candidates = []
    for item in events:
        candidate = _parse_ticketmaster_candidate(item)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _parse_ticketmaster_candidate(item: object) -> TicketmasterCandidate | None:
    """Parse one event, excluding malformed payload objects rather than guessing."""

    if not isinstance(item, dict):
        return None
    event_id = item.get("id")
    title = item.get("name")
    if (
        not isinstance(event_id, str)
        or not event_id.strip()
        or not isinstance(title, str)
    ):
        return None
    dates = item.get("dates")
    start = dates.get("start") if isinstance(dates, dict) else None
    local_date_value = start.get("localDate") if isinstance(start, dict) else None
    if not isinstance(local_date_value, str):
        return None
    try:
        local_date = date.fromisoformat(local_date_value)
    except ValueError:
        return None
    embedded = item.get("_embedded")
    venues = embedded.get("venues") if isinstance(embedded, dict) else None
    first_venue: Any = venues[0] if isinstance(venues, list) and venues else None
    venue_name = first_venue.get("name") if isinstance(first_venue, dict) else None
    url = item.get("url")
    return TicketmasterCandidate(
        provider_event_id=event_id,
        title=title,
        local_date=local_date,
        venue_name=venue_name if isinstance(venue_name, str) else None,
        event_url=url if isinstance(url, str) else None,
    )


@dataclass(frozen=True)
class TicketmasterMatch:
    """A uniquely identified candidate with matching evidence."""

    candidate: TicketmasterCandidate
    confidence: float
    rationale: tuple[str, ...]


def normalize_match_text(value: str) -> str:
    """Normalize display text without fuzzy matching or semantic rewrites."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


def match_ticketmaster_candidates(
    event: Event, candidates: list[TicketmasterCandidate]
) -> TicketmasterMatch | None:
    """Return one exact candidate, or ``None`` for mismatch or ambiguity."""

    if event.start_date is None:
        return None

    title = normalize_match_text(event.title)
    venue = normalize_match_text(event.venue.name) if event.venue is not None else None
    matches: list[TicketmasterMatch] = []
    for candidate in candidates:
        if normalize_match_text(candidate.title) != title:
            continue
        if candidate.local_date != event.start_date:
            continue
        if venue is not None and (
            candidate.venue_name is None
            or normalize_match_text(candidate.venue_name) != venue
        ):
            continue
        rationale = ["title_exact", "date_exact"]
        if venue is not None:
            rationale.append("venue_exact")
        matches.append(
            TicketmasterMatch(
                candidate=candidate,
                confidence=1.0,
                rationale=tuple(rationale),
            )
        )

    return matches[0] if len(matches) == 1 else None
