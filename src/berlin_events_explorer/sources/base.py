"""Interfaces and raw records for event sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from berlin_events_explorer.models import Event


class EventSource(Protocol):
    """Interface required by the synchronization service."""

    name: str
    url: str

    def parse(
        self, content: str, fetched_at: datetime | None = None
    ) -> "SourceParseResult":
        """Parse source content into events and non-fatal row issues."""
        ...


@dataclass(frozen=True)
class SourceParseIssue:
    """One non-fatal problem encountered while parsing a source row."""

    level: str
    event: str
    message: str
    context: dict[str, Any]


@dataclass(frozen=True)
class SourceParseResult:
    """Canonical events together with non-fatal source-row diagnostics."""

    events: list[Event]
    issues: list[SourceParseIssue]


@dataclass(frozen=True)
class RawSourceEvent:
    """A source row preserved before canonical normalization."""

    source_name: str
    source_url: str
    source_record_id: str | None
    source_record_hash: str
    raw_date: str
    raw_note: str
    raw_artist: str
    raw_venue: str
    fetched_at: datetime
    raw_data: dict[str, Any]
