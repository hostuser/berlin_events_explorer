"""SQLite persistence for events, source snapshots, and audit records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from berlin_events_explorer.models import Event

metadata = MetaData()
events_table = Table(
    "events",
    metadata,
    # Event payload is kept as JSON so Pydantic remains the domain schema.
    # SQL columns for searchable fields can be added as query requirements emerge.
    Column("id", String(64), primary_key=True),
    Column("provider", String(100), nullable=False, index=True),
    Column("source_record_hash", String(64), nullable=False),
    Column("event_json", JSON, nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
snapshots_table = Table(
    "source_snapshots",
    metadata,
    Column("provider", String(100), primary_key=True),
    Column("url", Text, nullable=False),
    Column("etag", String(500)),
    Column("last_modified", String(500)),
    Column("content_hash", String(64)),
    Column("checked_at", DateTime(timezone=True), nullable=False),
)
audit_table = Table(
    "audit_log",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("event_id", String(64), nullable=False, index=True),
    Column("provider", String(100), nullable=False),
    Column("action", String(30), nullable=False),
    Column("changes_json", JSON, nullable=False),
    Column("changed_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class SourceSnapshot:
    """Cached HTTP metadata for one source."""

    provider: str
    url: str
    etag: str | None
    last_modified: str | None
    content_hash: str | None
    checked_at: datetime


@dataclass(frozen=True)
class AuditEntry:
    """One event change recorded by the store."""

    event_id: str
    provider: str
    action: str
    changes: dict[str, Any]
    changed_at: datetime


@dataclass(frozen=True)
class UpsertResult:
    """Result of storing one canonical event."""

    action: str
    changes: dict[str, Any]


class EventStore:
    """Persist canonical events and synchronization metadata in SQLite."""

    def __init__(self, path: str | Path) -> None:
        self.engine: Engine = create_engine(f"sqlite:///{Path(path)}")
        metadata.create_all(self.engine)

    def get_snapshot(self, provider: str) -> SourceSnapshot | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(snapshots_table).where(
                        snapshots_table.c.provider == provider
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return SourceSnapshot(**row)

    def save_snapshot(
        self,
        provider: str,
        url: str,
        etag: str | None,
        last_modified: str | None,
        content_hash: str | None,
    ) -> None:
        values = {
            "provider": provider,
            "url": url,
            "etag": etag,
            "last_modified": last_modified,
            "content_hash": content_hash,
            "checked_at": datetime.now(timezone.utc),
        }
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(snapshots_table.c.provider).where(
                    snapshots_table.c.provider == provider
                )
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(insert(snapshots_table).values(**values))
            else:
                connection.execute(
                    update(snapshots_table)
                    .where(snapshots_table.c.provider == provider)
                    .values(**values)
                )

    def upsert(self, event: Event) -> UpsertResult:
        payload = event.model_dump(mode="json")
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            existing = (
                connection.execute(
                    select(events_table).where(events_table.c.id == event.id)
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                connection.execute(
                    insert(events_table).values(
                        id=event.id,
                        provider=event.source.provider,
                        source_record_hash=event.source.source_record_hash,
                        event_json=payload,
                        first_seen_at=event.first_seen_at or now,
                        last_seen_at=event.last_seen_at or now,
                        updated_at=now,
                    )
                )
                action = "created"
                changes = {"event": {"old": None, "new": payload}}
            else:
                old_payload = existing["event_json"]
                changes = _diff_payload(
                    _comparison_payload(old_payload), _comparison_payload(payload)
                )
                if not changes:
                    connection.execute(
                        update(events_table)
                        .where(events_table.c.id == event.id)
                        .values(last_seen_at=now)
                    )
                    return UpsertResult(action="unchanged", changes={})
                connection.execute(
                    update(events_table)
                    .where(events_table.c.id == event.id)
                    .values(
                        provider=event.source.provider,
                        source_record_hash=event.source.source_record_hash,
                        event_json=payload,
                        last_seen_at=now,
                        updated_at=now,
                    )
                )
                action = "updated"

            connection.execute(
                insert(audit_table).values(
                    event_id=event.id,
                    provider=event.source.provider,
                    action=action,
                    changes_json=changes,
                    changed_at=now,
                )
            )
            return UpsertResult(action=action, changes=changes)

    def list_events(self) -> list[Event]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(events_table.c.event_json)).all()
        return [Event.model_validate(row[0]) for row in rows]

    def count_events(self, provider: str) -> int:
        from sqlalchemy import func

        with self.engine.connect() as connection:
            return connection.execute(
                select(func.count())
                .select_from(events_table)
                .where(events_table.c.provider == provider)
            ).scalar_one()

    def list_audit_log(self) -> list[AuditEntry]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(audit_table).order_by(audit_table.c.id)
            ).mappings()
            return [
                AuditEntry(
                    event_id=row["event_id"],
                    provider=row["provider"],
                    action=row["action"],
                    changes=row["changes_json"],
                    changed_at=row["changed_at"],
                )
                for row in rows
            ]


def _diff_payload(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {"old": old.get(key), "new": value}
        for key, value in new.items()
        if old.get(key) != value
    }


def _comparison_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove observation timestamps from semantic event comparisons."""
    return {
        key: value
        for key, value in payload.items()
        if key not in {"first_seen_at", "last_seen_at"}
    }
