"""MyTrueIntent published Google Sheets source adapter."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime, timezone
from typing import Iterable

from berlin_events_explorer.models import (
    DatePrecision,
    Event,
    EventSourceRef,
    EventStatus,
    Performer,
    Venue,
)
from berlin_events_explorer.sources.base import (
    RawSourceEvent,
    SourceParseIssue,
    SourceParseResult,
)


class MyTrueIntentSource:
    """Parse the published MyTrueIntent event spreadsheet CSV."""

    name = "mytrueintent"
    url = (
        "https://docs.google.com/spreadsheets/d/e/"
        "2PACX-1vQ8aY7ygJdMv7XE0fDzoMhVOy4gvWAxOpVquWAOEMGoFdduWW820R2cPskg3cykmA/"
        "pub?gid=415332589&single=true&output=csv"
    )
    required_columns = {"Date", "Note", "Artist", "Venue"}

    def parse(self, content: str, fetched_at: datetime | None = None) -> SourceParseResult:
        """Parse CSV content, retaining row diagnostics without aborting the batch."""
        fetched_at = fetched_at or datetime.now(timezone.utc)
        reader = csv.DictReader(io.StringIO(content))
        columns = set(reader.fieldnames or [])
        missing = self.required_columns - columns
        if missing:
            missing_columns = ", ".join(sorted(missing))
            raise ValueError(f"CSV is missing required columns: {missing_columns}")

        events: list[Event] = []
        issues: list[SourceParseIssue] = []
        for row_number, row in enumerate(reader, start=2):
            raw = {key: (value or "").strip() for key, value in row.items()}
            raw_date = raw["Date"]
            raw_artist = raw["Artist"]
            raw_venue = raw["Venue"]
            record_hash = hashlib.sha256(
                "|".join([raw_date, raw["Note"], raw_artist, raw_venue]).encode("utf-8")
            ).hexdigest()
            raw_event = RawSourceEvent(
                source_name=self.name,
                source_url=self.url,
                source_record_id=str(row_number),
                source_record_hash=record_hash,
                raw_date=raw_date,
                raw_note=raw["Note"],
                raw_artist=raw_artist,
                raw_venue=raw_venue,
                fetched_at=fetched_at,
                raw_data=raw,
            )
            try:
                events.append(self._to_event(raw_event))
            except ValueError as exc:
                issues.append(
                    SourceParseIssue(
                        level="error",
                        event="source_row_parse_failed",
                        message=f"Skipped source row {row_number}: {exc}",
                        context={
                            "provider": self.name,
                            "source_record_id": str(row_number),
                            "date": raw_date,
                            "artist": raw_artist,
                            "venue": raw_venue,
                            "error": str(exc),
                        },
                    )
                )
        return SourceParseResult(events=events, issues=issues)

    def _to_event(self, raw: RawSourceEvent) -> Event:
        start_date, end_date, precision = _parse_date(raw.raw_date)
        status = _parse_status(raw.raw_note)
        event_key = "|".join(
            [
                raw.source_name,
                raw.source_record_id or "",
                f"{start_date.isoformat()}..{end_date.isoformat()}"
                if end_date
                else start_date.isoformat(),
                raw.raw_artist,
                raw.raw_venue,
            ]
        )
        event_id = hashlib.sha256(event_key.encode("utf-8")).hexdigest()
        performers = [
            Performer(name=name.strip(), billing_order=index)
            for index, name in enumerate(raw.raw_artist.split("/"), start=1)
            if name.strip()
        ]
        return Event(
            id=event_id,
            source=EventSourceRef(
                provider=raw.source_name,
                source_url=raw.source_url,
                source_record_id=raw.source_record_id,
                source_record_hash=raw.source_record_hash,
            ),
            start_date=start_date,
            end_date=end_date,
            date_precision=precision,
            title=raw.raw_artist,
            performers=performers,
            venue=Venue(name=raw.raw_venue) if raw.raw_venue else None,
            status=status,
            notes=[raw.raw_note] if raw.raw_note else [],
            raw_data=raw.raw_data,
            first_seen_at=raw.fetched_at,
            last_seen_at=raw.fetched_at,
        )


def _parse_status(note: str) -> EventStatus:
    normalized = note.strip().lower()
    return {
        "new": EventStatus.NEW,
        "sold out": EventStatus.SOLD_OUT,
        "cancelled": EventStatus.CANCELLED,
    }.get(normalized, EventStatus.CONFIRMED if not normalized else EventStatus.UNKNOWN)


def _parse_date(value: str) -> tuple[date, date | None, DatePrecision]:
    value = value.strip()
    range_match = re.fullmatch(r"(\d{1,2})\.-(\d{1,2})\.(\d{1,2})\.(\d{2,4})", value)
    if range_match:
        start_day, end_day, month, year = range_match.groups()
        year = _four_digit_year(year)
        return (
            date(year, int(month), int(start_day)),
            date(year, int(month), int(end_day)),
            DatePrecision.DATE_RANGE,
        )

    for pattern in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value, pattern).date(), None, DatePrecision.DAY
        except ValueError:
            continue
    raise ValueError(f"Unsupported MyTrueIntent date: {value!r}")


def _four_digit_year(year: str) -> int:
    number = int(year)
    return number if len(year) == 4 else 2000 + number


def parse_events(content: str) -> Iterable[Event]:
    """Convenience function for parsing with the default source."""
    return MyTrueIntentSource().parse(content).events
