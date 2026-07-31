"""SQLite persistence for events, source snapshots, and audit records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Connection,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)

from berlin_events_explorer.migrations import migrate_database
from berlin_events_explorer.models import (
    ArtistCandidate,
    ArtistMetadata,
    ArtistRecord,
    ArtistStatus,
    Event,
    VenueCandidate,
    VenueMetadata,
    VenueRecord,
    VenueStatus,
)


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
venues_table = Table(
    "venues",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("name", String(500), nullable=False),
    Column("normalized_name", String(500), nullable=False, index=True),
    Column("city", String(100)),
    Column("country", String(10)),
    Column("address", Text),
    Column("postal_code", String(30)),
    Column("latitude", String(30)),
    Column("longitude", String(30)),
    Column("website", Text),
    Column("osm_type", String(30)),
    Column("osm_id", String(100)),
    Column("status", String(30), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("last_checked_at", DateTime(timezone=True)),
    UniqueConstraint("osm_type", "osm_id", name="uq_venues_osm_identity"),
)
venue_metadata_table = Table(
    "venue_metadata",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "venue_id", String(100), ForeignKey("venues.id"), nullable=False, index=True
    ),
    Column("field", String(100), nullable=False),
    Column("value_json", JSON, nullable=False),
    Column("provider", String(100), nullable=False),
    Column("source_url", Text),
    Column("confidence", String(30)),
    Column("retrieved_at", DateTime(timezone=True)),
    UniqueConstraint(
        "venue_id",
        "field",
        "provider",
        "source_url",
        name="uq_venue_metadata_field_source",
    ),
)
venue_candidates_table = Table(
    "venue_candidates",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "venue_id", String(100), ForeignKey("venues.id"), nullable=False, index=True
    ),
    Column("provider", String(100), nullable=False),
    Column("source_url", Text, nullable=False),
    Column("osm_type", String(30), nullable=False),
    Column("osm_id", String(100), nullable=False),
    Column("display_name", Text, nullable=False),
    Column("address", Text),
    Column("postal_code", String(30)),
    Column("website", Text),
    Column("latitude", String(30)),
    Column("longitude", String(30)),
    Column("confidence", String(30), nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "venue_id",
        "provider",
        "osm_type",
        "osm_id",
        name="uq_venue_candidate_identity",
    ),
)
event_venues_table = Table(
    "event_venues",
    metadata,
    Column("event_id", String(64), ForeignKey("events.id"), primary_key=True),
    Column(
        "venue_id", String(100), ForeignKey("venues.id"), nullable=False, index=True
    ),
    Column("source_name", String(500), nullable=False),
)
artists_table = Table(
    "artists",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("name", String(500), nullable=False),
    Column("normalized_name", String(500), nullable=False, index=True),
    Column("artist_type", String(100)),
    Column("country", String(10)),
    Column("disambiguation", Text),
    Column("musicbrainz_id", String(36), unique=True),
    Column("musicbrainz_url", Text),
    Column("genres_json", JSON, nullable=False),
    Column("status", String(30), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("last_checked_at", DateTime(timezone=True)),
)
artist_metadata_table = Table(
    "artist_metadata",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "artist_id", String(100), ForeignKey("artists.id"), nullable=False, index=True
    ),
    Column("field", String(100), nullable=False),
    Column("value_json", JSON, nullable=False),
    Column("provider", String(100), nullable=False),
    Column("source_url", Text),
    Column("confidence", String(30)),
    Column("retrieved_at", DateTime(timezone=True)),
    UniqueConstraint(
        "artist_id",
        "field",
        "provider",
        "source_url",
        name="uq_artist_metadata_field_source",
    ),
)
artist_candidates_table = Table(
    "artist_candidates",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "artist_id", String(100), ForeignKey("artists.id"), nullable=False, index=True
    ),
    Column("provider", String(100), nullable=False),
    Column("source_url", Text, nullable=False),
    Column("musicbrainz_id", String(36), nullable=False),
    Column("display_name", Text, nullable=False),
    Column("artist_type", String(100)),
    Column("country", String(10)),
    Column("disambiguation", Text),
    Column("genres_json", JSON, nullable=False),
    Column("provider_score", Integer),
    Column("confidence", String(30), nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "artist_id",
        "provider",
        "musicbrainz_id",
        name="uq_artist_candidate_identity",
    ),
)
event_artists_table = Table(
    "event_artists",
    metadata,
    Column("event_id", String(64), ForeignKey("events.id"), primary_key=True),
    Column("billing_order", Integer, primary_key=True),
    Column(
        "artist_id", String(100), ForeignKey("artists.id"), nullable=False, index=True
    ),
    Column("source_name", String(500), nullable=False),
    Column("role", String(100)),
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
logs_table = Table(
    "log",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("level", String(20), nullable=False, index=True),
    Column("event", String(100), nullable=False, index=True),
    Column("message", Text, nullable=False),
    Column("context_json", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)
worker_runs_table = Table(
    "worker_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("started_at", DateTime(timezone=True), nullable=False, index=True),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", String(30), nullable=False, index=True),
    Column("error", Text),
    Column("summary_json", JSON, nullable=False),
)
settings_table = Table(
    "settings",
    metadata,
    Column("key", String(100), primary_key=True),
    Column("value_json", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
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
class LogEntry:
    """One structured application diagnostic stored in SQLite."""

    level: str
    event: str
    message: str
    context: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class WorkerRun:
    """One bounded background-worker invocation and its visible outcome."""

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    error: str | None
    summary: dict[str, Any]


@dataclass(frozen=True)
class UpsertResult:
    """Result of storing one canonical event."""

    action: str
    changes: dict[str, Any]


class EventStore:
    """Persist canonical events and synchronization metadata in SQLite."""

    def __init__(self, path: str | Path) -> None:
        migrate_database(path)
        self.engine: Engine = create_engine(f"sqlite:///{Path(path)}")

    def get_setting(self, key: str) -> Any | None:
        """Return one persisted application setting, if configured."""

        with self.engine.connect() as connection:
            return connection.execute(
                select(settings_table.c.value_json).where(settings_table.c.key == key)
            ).scalar_one_or_none()

    def set_setting(self, key: str, value: Any) -> None:
        """Persist one application setting as a JSON-compatible value."""

        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(settings_table.c.key).where(settings_table.c.key == key)
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(
                    insert(settings_table).values(
                        key=key, value_json=value, updated_at=now
                    )
                )
            else:
                connection.execute(
                    update(settings_table)
                    .where(settings_table.c.key == key)
                    .values(value_json=value, updated_at=now)
                )

    def start_worker_run(self) -> WorkerRun:
        """Record a worker invocation before it begins its first external phase."""

        started_at = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            result = connection.execute(
                insert(worker_runs_table).values(
                    started_at=started_at,
                    finished_at=None,
                    status="running",
                    error=None,
                    summary_json={},
                )
            )
        primary_key = result.inserted_primary_key
        if primary_key is None or not primary_key:
            raise RuntimeError("SQLite did not return a worker run ID")
        run_id = primary_key[0]
        if not isinstance(run_id, int):
            raise RuntimeError("SQLite did not return a worker run ID")
        return WorkerRun(
            id=run_id,
            started_at=started_at,
            finished_at=None,
            status="running",
            error=None,
            summary={},
        )

    def finish_worker_run(
        self,
        run_id: int,
        *,
        status: str,
        summary: dict[str, Any],
        error: str | None = None,
    ) -> WorkerRun:
        """Persist a terminal worker-run outcome and return its current record."""

        if status not in {"succeeded", "failed"}:
            raise ValueError("worker run status must be succeeded or failed")
        finished_at = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            connection.execute(
                update(worker_runs_table)
                .where(worker_runs_table.c.id == run_id)
                .values(
                    finished_at=finished_at,
                    status=status,
                    error=error,
                    summary_json=summary,
                )
            )
        run = self.get_worker_run(run_id)
        if run is None:
            raise ValueError(f"Unknown worker run: {run_id}")
        return run

    def get_worker_run(self, run_id: int) -> WorkerRun | None:
        """Return one worker-run record by its database ID."""

        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(worker_runs_table).where(worker_runs_table.c.id == run_id)
                )
                .mappings()
                .one_or_none()
            )
        return _worker_run_from_row(row) if row is not None else None

    def latest_worker_run(self) -> WorkerRun | None:
        """Return the newest background-worker run for operational status displays."""

        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(worker_runs_table)
                    .order_by(worker_runs_table.c.id.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _worker_run_from_row(row) if row is not None else None

    def clear_application_data(self) -> None:
        """Delete synchronized content while preserving application settings."""

        with self.engine.begin() as connection:
            for table in (
                artist_metadata_table,
                artist_candidates_table,
                event_artists_table,
                venue_metadata_table,
                venue_candidates_table,
                event_venues_table,
                audit_table,
                logs_table,
                snapshots_table,
                events_table,
                artists_table,
                venues_table,
            ):
                connection.execute(delete(table))

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
        checked_at: datetime | None = None,
        connection: Connection | None = None,
    ) -> None:
        values = {
            "provider": provider,
            "url": url,
            "etag": etag,
            "last_modified": last_modified,
            "content_hash": content_hash,
            "checked_at": checked_at or datetime.now(timezone.utc),
        }
        if connection is None:
            with self.engine.begin() as conn:
                self._save_snapshot(conn, values)
        else:
            self._save_snapshot(connection, values)

    def _save_snapshot(self, connection: Connection, values: dict[str, Any]) -> None:
        existing = connection.execute(
            select(snapshots_table.c.provider).where(
                snapshots_table.c.provider == values["provider"]
            )
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(insert(snapshots_table).values(**values))
        else:
            connection.execute(
                update(snapshots_table)
                .where(snapshots_table.c.provider == values["provider"])
                .values(**values)
            )

    def upsert(
        self,
        event: Event,
        *,
        connection: Connection | None = None,
        now: datetime | None = None,
    ) -> UpsertResult:
        now = now or datetime.now(timezone.utc)
        if connection is None:
            with self.engine.begin() as conn:
                return self._upsert(event, conn, now=now)
        return self._upsert(event, connection, now=now)

    def _upsert(
        self,
        event: Event,
        connection: Connection,
        now: datetime,
    ) -> UpsertResult:
        payload = event.model_dump(mode="json")
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
                _comparison_payload(old_payload),
                _comparison_payload(payload),
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

    def upsert_artist(
        self,
        artist: ArtistRecord,
        *,
        now: datetime | None = None,
        connection: Connection | None = None,
    ) -> ArtistRecord:
        """Create or update one canonical artist and return its persisted form."""

        now = now or datetime.now(timezone.utc)
        if connection is None:
            with self.engine.begin() as conn:
                return self.upsert_artist(artist, now=now, connection=conn)
        existing = (
            connection.execute(
                select(artists_table).where(artists_table.c.id == artist.id)
            )
            .mappings()
            .one_or_none()
        )
        values = artist.model_dump(mode="python")
        values["genres_json"] = values.pop("genres")
        if existing is None:
            values["created_at"] = artist.created_at or now
            values["updated_at"] = artist.updated_at or now
            connection.execute(insert(artists_table).values(**values))
        else:
            values["created_at"] = existing["created_at"]
            values["updated_at"] = now
            connection.execute(
                update(artists_table)
                .where(artists_table.c.id == artist.id)
                .values(**values)
            )
        row = (
            connection.execute(
                select(artists_table).where(artists_table.c.id == artist.id)
            )
            .mappings()
            .one()
        )
        return _artist_from_row(row)

    def get_artist(self, artist_id: str) -> ArtistRecord | None:
        """Return one canonical artist by stable identifier."""

        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(artists_table).where(artists_table.c.id == artist_id)
                )
                .mappings()
                .one_or_none()
            )
        return _artist_from_row(row) if row is not None else None

    def list_artists(self) -> list[ArtistRecord]:
        """Return canonical artists ordered for predictable review output."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                artists_table.select().order_by(artists_table.c.name)
            )
            return [_artist_from_row(row) for row in rows.mappings()]

    def list_verified_artists_missing_metadata(
        self, field: str, provider: str, *, limit: int
    ) -> list[ArtistRecord]:
        """Return bounded verified artists without one provider metadata check."""

        checked_artist_ids = select(artist_metadata_table.c.artist_id).where(
            artist_metadata_table.c.field == field,
            artist_metadata_table.c.provider == provider,
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(artists_table)
                .where(
                    artists_table.c.status == ArtistStatus.VERIFIED.value,
                    artists_table.c.musicbrainz_id.is_not(None),
                    artists_table.c.id.not_in(checked_artist_ids),
                )
                .order_by(artists_table.c.name)
                .limit(limit)
            ).mappings()
            return [_artist_from_row(row) for row in rows]

    def count_verified_artists_missing_metadata(self, field: str, provider: str) -> int:
        """Count verified artists still lacking a provider metadata check."""

        checked_artist_ids = select(artist_metadata_table.c.artist_id).where(
            artist_metadata_table.c.field == field,
            artist_metadata_table.c.provider == provider,
        )
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count())
                    .select_from(artists_table)
                    .where(
                        artists_table.c.status == ArtistStatus.VERIFIED.value,
                        artists_table.c.musicbrainz_id.is_not(None),
                        artists_table.c.id.not_in(checked_artist_ids),
                    )
                ).scalar_one()
            )

    def get_artist_official_homepage(self, artist_id: str) -> str | None:
        """Return a selected official homepage URL, if MusicBrainz supplied one."""

        with self.engine.connect() as connection:
            value = connection.execute(
                select(artist_metadata_table.c.value_json)
                .where(
                    artist_metadata_table.c.artist_id == artist_id,
                    artist_metadata_table.c.field == "official_homepage",
                    artist_metadata_table.c.provider == "musicbrainz",
                )
                .order_by(artist_metadata_table.c.id.desc())
            ).scalar_one_or_none()
        return value if isinstance(value, str) else None

    def save_artist_metadata(
        self, artist_metadata: ArtistMetadata, *, connection: Connection | None = None
    ) -> None:
        """Persist or replace field provenance for a canonical artist."""

        if connection is None:
            with self.engine.begin() as conn:
                self.save_artist_metadata(artist_metadata, connection=conn)
            return
        values = artist_metadata.model_dump(mode="python")
        values["value_json"] = values.pop("value")
        existing = connection.execute(
            select(artist_metadata_table.c.id).where(
                artist_metadata_table.c.artist_id == artist_metadata.artist_id,
                artist_metadata_table.c.field == artist_metadata.field,
                artist_metadata_table.c.provider == artist_metadata.provider,
                artist_metadata_table.c.source_url == artist_metadata.source_url,
            )
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(insert(artist_metadata_table).values(**values))
        else:
            connection.execute(
                update(artist_metadata_table)
                .where(artist_metadata_table.c.id == existing)
                .values(**values)
            )

    def list_artist_metadata(self, artist_id: str) -> list[ArtistMetadata]:
        """Return selected provenance records for one artist."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                select(artist_metadata_table)
                .where(artist_metadata_table.c.artist_id == artist_id)
                .order_by(artist_metadata_table.c.id)
            ).mappings()
            return [
                ArtistMetadata(
                    artist_id=row["artist_id"],
                    field=row["field"],
                    value=row["value_json"],
                    provider=row["provider"],
                    source_url=row["source_url"],
                    confidence=float(row["confidence"])
                    if row["confidence"] is not None
                    else None,
                    retrieved_at=row["retrieved_at"],
                )
                for row in rows
            ]

    def record_artist_candidates(self, candidates: list[ArtistCandidate]) -> None:
        """Persist reviewable artist candidates without selecting any of them."""

        with self.engine.begin() as connection:
            scopes = {
                (candidate.artist_id, candidate.provider) for candidate in candidates
            }
            for artist_id, provider in scopes:
                connection.execute(
                    delete(artist_candidates_table).where(
                        artist_candidates_table.c.artist_id == artist_id,
                        artist_candidates_table.c.provider == provider,
                    )
                )
            for candidate in candidates:
                values = candidate.model_dump(mode="python")
                values["genres_json"] = values.pop("genres")
                values["confidence"] = str(values["confidence"])
                connection.execute(insert(artist_candidates_table).values(**values))

    def list_artist_candidates(self, artist_id: str) -> list[ArtistCandidate]:
        """Return cached external candidates for explicit editorial review."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                select(artist_candidates_table)
                .where(artist_candidates_table.c.artist_id == artist_id)
                .order_by(artist_candidates_table.c.confidence.desc())
            ).mappings()
            return [_artist_candidate_from_row(row) for row in rows]

    def select_artist_candidate(
        self, artist_id: str, provider: str, musicbrainz_id: str
    ) -> ArtistRecord:
        """Promote one reviewed artist candidate and record provenance atomically."""

        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(artist_candidates_table).where(
                        artist_candidates_table.c.artist_id == artist_id,
                        artist_candidates_table.c.provider == provider,
                        artist_candidates_table.c.musicbrainz_id == musicbrainz_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError(
                    f"Unknown artist candidate: {artist_id}/{provider}/{musicbrainz_id}"
                )
            current = self.get_artist(artist_id)
            if current is None:
                raise ValueError(f"Unknown artist: {artist_id}")
            candidate = _artist_candidate_from_row(row)
            selected = self.upsert_artist(
                current.model_copy(
                    update={
                        "artist_type": candidate.artist_type,
                        "country": candidate.country,
                        "disambiguation": candidate.disambiguation,
                        "musicbrainz_id": candidate.musicbrainz_id,
                        "musicbrainz_url": candidate.source_url,
                        "genres": candidate.genres,
                        "status": ArtistStatus.VERIFIED,
                        "last_checked_at": candidate.retrieved_at,
                    }
                ),
                connection=connection,
            )
            for field, value in {
                "artist_type": candidate.artist_type,
                "country": candidate.country,
                "disambiguation": candidate.disambiguation,
                "musicbrainz_id": candidate.musicbrainz_id,
                "musicbrainz_url": candidate.source_url,
                "genres": candidate.genres,
            }.items():
                if value not in (None, []):
                    self.save_artist_metadata(
                        ArtistMetadata(
                            artist_id=artist_id,
                            field=field,
                            value=value,
                            provider=provider,
                            source_url=candidate.source_url,
                            confidence=candidate.confidence,
                            retrieved_at=candidate.retrieved_at,
                        ),
                        connection=connection,
                    )
        return selected

    def link_event_artist(
        self,
        event_id: str,
        billing_order: int,
        artist_id: str,
        *,
        source_name: str,
        role: str | None = None,
    ) -> None:
        """Associate one source billing with a canonical artist idempotently."""

        with self.engine.begin() as connection:
            values = {
                "event_id": event_id,
                "billing_order": billing_order,
                "artist_id": artist_id,
                "source_name": source_name,
                "role": role,
            }
            existing = connection.execute(
                select(event_artists_table.c.event_id).where(
                    event_artists_table.c.event_id == event_id,
                    event_artists_table.c.billing_order == billing_order,
                )
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(insert(event_artists_table).values(**values))
            else:
                connection.execute(
                    update(event_artists_table)
                    .where(
                        event_artists_table.c.event_id == event_id,
                        event_artists_table.c.billing_order == billing_order,
                    )
                    .values(**values)
                )

    def get_artist_ids_for_event_performers(
        self, event_ids: list[str]
    ) -> dict[tuple[str, int], str]:
        """Return artist IDs keyed by event and source billing order."""

        if not event_ids:
            return {}
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    event_artists_table.c.event_id,
                    event_artists_table.c.billing_order,
                    event_artists_table.c.artist_id,
                )
                .join(
                    artists_table, event_artists_table.c.artist_id == artists_table.c.id
                )
                .where(event_artists_table.c.event_id.in_(event_ids))
            )
            return {(row.event_id, row.billing_order): row.artist_id for row in rows}

    def list_events_for_artist(self, artist_id: str) -> list[Event]:
        """Return all events associated with a canonical artist."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                select(events_table.c.event_json)
                .join(
                    event_artists_table,
                    event_artists_table.c.event_id == events_table.c.id,
                )
                .where(event_artists_table.c.artist_id == artist_id)
            )
        events = [Event.model_validate(row[0]) for row in rows]
        return sorted(
            events,
            key=lambda event: (
                event.start_date or datetime.max.date(),
                event.title.lower(),
            ),
        )

    def upsert_venue(
        self,
        venue: VenueRecord,
        *,
        now: datetime | None = None,
        connection: Connection | None = None,
    ) -> VenueRecord:
        """Create or update a canonical venue and return its persisted form."""

        now = now or datetime.now(timezone.utc)
        if connection is None:
            with self.engine.begin() as conn:
                return self.upsert_venue(venue, now=now, connection=conn)

        existing = (
            connection.execute(
                select(venues_table).where(venues_table.c.id == venue.id)
            )
            .mappings()
            .one_or_none()
        )
        values = venue.model_dump(mode="python")
        values["latitude"] = (
            str(values["latitude"]) if values["latitude"] is not None else None
        )
        values["longitude"] = (
            str(values["longitude"]) if values["longitude"] is not None else None
        )
        if existing is None:
            values["created_at"] = venue.created_at or now
            values["updated_at"] = venue.updated_at or now
            connection.execute(insert(venues_table).values(**values))
        else:
            values["created_at"] = existing["created_at"]
            values["updated_at"] = now
            connection.execute(
                update(venues_table)
                .where(venues_table.c.id == venue.id)
                .values(**values)
            )
        row = (
            connection.execute(
                select(venues_table).where(venues_table.c.id == venue.id)
            )
            .mappings()
            .one()
        )
        return _venue_from_row(row)

    def get_venue(self, venue_id: str) -> VenueRecord | None:
        """Return one canonical venue by its stable identifier."""

        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(venues_table).where(venues_table.c.id == venue_id)
                )
                .mappings()
                .one_or_none()
            )
        return _venue_from_row(row) if row is not None else None

    def list_venues(self) -> list[VenueRecord]:
        """Return canonical venues ordered for predictable review output."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                select(venues_table).order_by(venues_table.c.name)
            )
            return [_venue_from_row(row) for row in rows.mappings()]

    def save_venue_metadata(
        self,
        venue_metadata: VenueMetadata,
        *,
        connection: Connection | None = None,
    ) -> None:
        """Persist or replace field provenance for a canonical venue."""

        if connection is None:
            with self.engine.begin() as conn:
                self.save_venue_metadata(venue_metadata, connection=conn)
            return
        values = venue_metadata.model_dump(mode="python")
        values["value_json"] = values.pop("value")
        existing = connection.execute(
            select(venue_metadata_table.c.id).where(
                venue_metadata_table.c.venue_id == venue_metadata.venue_id,
                venue_metadata_table.c.field == venue_metadata.field,
                venue_metadata_table.c.provider == venue_metadata.provider,
                venue_metadata_table.c.source_url == venue_metadata.source_url,
            )
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(insert(venue_metadata_table).values(**values))
        else:
            connection.execute(
                update(venue_metadata_table)
                .where(venue_metadata_table.c.id == existing)
                .values(**values)
            )

    def list_venue_metadata(self, venue_id: str) -> list[VenueMetadata]:
        """Return selected provenance records for one venue."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                select(venue_metadata_table)
                .where(venue_metadata_table.c.venue_id == venue_id)
                .order_by(venue_metadata_table.c.id)
            ).mappings()
            return [
                VenueMetadata(
                    venue_id=row["venue_id"],
                    field=row["field"],
                    value=row["value_json"],
                    provider=row["provider"],
                    source_url=row["source_url"],
                    confidence=float(row["confidence"])
                    if row["confidence"] is not None
                    else None,
                    retrieved_at=row["retrieved_at"],
                )
                for row in rows
            ]

    def record_venue_candidates(self, candidates: list[VenueCandidate]) -> None:
        """Persist reviewable candidates without selecting any of them."""

        with self.engine.begin() as connection:
            scopes = {
                (candidate.venue_id, candidate.provider) for candidate in candidates
            }
            for venue_id, provider in scopes:
                connection.execute(
                    delete(venue_candidates_table).where(
                        venue_candidates_table.c.venue_id == venue_id,
                        venue_candidates_table.c.provider == provider,
                    )
                )
            for candidate in candidates:
                values = candidate.model_dump(mode="python")
                for field in ("latitude", "longitude", "confidence"):
                    if values[field] is not None:
                        values[field] = str(values[field])
                existing = connection.execute(
                    select(venue_candidates_table.c.id).where(
                        venue_candidates_table.c.venue_id == candidate.venue_id,
                        venue_candidates_table.c.provider == candidate.provider,
                        venue_candidates_table.c.osm_type == candidate.osm_type,
                        venue_candidates_table.c.osm_id == candidate.osm_id,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    connection.execute(insert(venue_candidates_table).values(**values))
                else:
                    connection.execute(
                        update(venue_candidates_table)
                        .where(venue_candidates_table.c.id == existing)
                        .values(**values)
                    )

    def list_venue_candidates(self, venue_id: str) -> list[VenueCandidate]:
        """Return cached external candidates for explicit editorial review."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                select(venue_candidates_table)
                .where(venue_candidates_table.c.venue_id == venue_id)
                .order_by(venue_candidates_table.c.confidence.desc())
            ).mappings()
            return [_candidate_from_row(row) for row in rows]

    def select_venue_candidate(
        self, venue_id: str, provider: str, osm_type: str, osm_id: str
    ) -> VenueRecord:
        """Promote one reviewed candidate and record its provenance atomically."""

        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(venue_candidates_table).where(
                        venue_candidates_table.c.venue_id == venue_id,
                        venue_candidates_table.c.provider == provider,
                        venue_candidates_table.c.osm_type == osm_type,
                        venue_candidates_table.c.osm_id == osm_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError(
                    f"Unknown venue candidate: {venue_id}/{provider}/{osm_type}/{osm_id}"
                )
            current = self.get_venue(venue_id)
            if current is None:
                raise ValueError(f"Unknown venue: {venue_id}")
            candidate = _candidate_from_row(row)
            selected = self.upsert_venue(
                current.model_copy(
                    update={
                        "address": candidate.address,
                        "postal_code": candidate.postal_code,
                        "website": candidate.website,
                        "latitude": candidate.latitude,
                        "longitude": candidate.longitude,
                        "osm_type": candidate.osm_type,
                        "osm_id": candidate.osm_id,
                        "status": VenueStatus.VERIFIED,
                        "last_checked_at": candidate.retrieved_at,
                    }
                ),
                connection=connection,
            )
            for field, value in {
                "address": candidate.address,
                "postal_code": candidate.postal_code,
                "website": candidate.website,
                "latitude": candidate.latitude,
                "longitude": candidate.longitude,
            }.items():
                if value is not None:
                    self.save_venue_metadata(
                        VenueMetadata(
                            venue_id=venue_id,
                            field=field,
                            value=value,
                            provider=provider,
                            source_url=candidate.source_url,
                            confidence=candidate.confidence,
                            retrieved_at=candidate.retrieved_at,
                        ),
                        connection=connection,
                    )
        return selected

    def link_event_venue(
        self, event_id: str, venue_id: str, *, source_name: str
    ) -> None:
        """Associate an existing event with its canonical venue idempotently."""

        with self.engine.begin() as connection:
            existing = connection.execute(
                select(event_venues_table.c.event_id).where(
                    event_venues_table.c.event_id == event_id
                )
            ).scalar_one_or_none()
            values = {
                "event_id": event_id,
                "venue_id": venue_id,
                "source_name": source_name,
            }
            if existing is None:
                connection.execute(insert(event_venues_table).values(**values))
            else:
                connection.execute(
                    update(event_venues_table)
                    .where(event_venues_table.c.event_id == event_id)
                    .values(**values)
                )

    def get_venue_for_event(self, event_id: str) -> VenueRecord | None:
        """Return the canonical venue associated with one event."""

        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(venues_table)
                    .join(
                        event_venues_table,
                        event_venues_table.c.venue_id == venues_table.c.id,
                    )
                    .where(event_venues_table.c.event_id == event_id)
                )
                .mappings()
                .one_or_none()
            )
        return _venue_from_row(row) if row is not None else None

    def get_venue_ids_for_events(self, event_ids: list[str]) -> dict[str, str]:
        """Return canonical venue IDs keyed by event ID for a rendered batch."""

        if not event_ids:
            return {}
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(event_venues_table.c.event_id, event_venues_table.c.venue_id)
                .join(
                    venues_table,
                    venues_table.c.id == event_venues_table.c.venue_id,
                )
                .where(
                    event_venues_table.c.event_id.in_(event_ids),
                    venues_table.c.status != VenueStatus.NOT_A_VENUE.value,
                )
            )
            return {row.event_id: row.venue_id for row in rows}

    def list_events_for_venue(self, venue_id: str) -> list[Event]:
        """Return all events associated with a canonical venue."""

        with self.engine.connect() as connection:
            rows = connection.execute(
                select(events_table.c.event_json)
                .join(
                    event_venues_table,
                    event_venues_table.c.event_id == events_table.c.id,
                )
                .where(event_venues_table.c.venue_id == venue_id)
            )
        events = [Event.model_validate(row[0]) for row in rows]
        return sorted(
            events,
            key=lambda event: (
                event.start_date or datetime.max.date(),
                event.title.lower(),
            ),
        )

    def count_events(self, provider: str, connection: Connection | None = None) -> int:
        query = (
            select(func.count())
            .select_from(events_table)
            .where(events_table.c.provider == provider)
        )
        if connection is None:
            with self.engine.connect() as db_connection:
                return db_connection.execute(query).scalar_one()
        return connection.execute(query).scalar_one()

    def delete_events_not_in(
        self,
        *,
        provider: str,
        event_ids: set[str],
        connection: Connection | None = None,
    ) -> int:
        """Delete provider events absent from a successfully parsed source snapshot."""

        statement = delete(events_table).where(events_table.c.provider == provider)
        if event_ids:
            statement = statement.where(events_table.c.id.not_in(event_ids))

        if connection is None:
            with self.engine.begin() as conn:
                result = conn.execute(statement)
        else:
            result = connection.execute(statement)
        return result.rowcount

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

    def log(
        self,
        *,
        level: str,
        event: str,
        message: str,
        context: dict[str, Any] | None = None,
        created_at: datetime | None = None,
        connection: Connection | None = None,
    ) -> None:
        """Persist an application diagnostic at error, info, or debug level."""

        if level not in {"debug", "info", "warning", "error"}:
            raise ValueError(f"Unsupported log level: {level!r}")
        values = {
            "level": level,
            "event": event,
            "message": message,
            "context_json": context or {},
            "created_at": created_at or datetime.now(timezone.utc),
        }
        if connection is None:
            with self.engine.begin() as conn:
                conn.execute(insert(logs_table).values(**values))
        else:
            connection.execute(insert(logs_table).values(**values))

    def list_logs(self, *, level: str | None = None) -> list[LogEntry]:
        """Return application diagnostics in insertion order."""

        query = select(logs_table).order_by(logs_table.c.id)
        if level is not None:
            query = query.where(logs_table.c.level == level)
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings()
            return [
                LogEntry(
                    level=row["level"],
                    event=row["event"],
                    message=row["message"],
                    context=row["context_json"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]


def _worker_run_from_row(row: Any) -> WorkerRun:
    """Convert SQLite worker-run data into an operational status record."""

    started_at = row["started_at"]
    finished_at = row["finished_at"]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if finished_at is not None and finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    return WorkerRun(
        id=row["id"],
        started_at=started_at,
        finished_at=finished_at,
        status=row["status"],
        error=row["error"],
        summary=row["summary_json"],
    )


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


def _artist_from_row(row: Any) -> ArtistRecord:
    """Convert a SQLite artist mapping into the canonical domain model."""

    values = dict(row)
    values["genres"] = values.pop("genres_json")
    return ArtistRecord.model_validate(values)


def _venue_from_row(row: Any) -> VenueRecord:
    """Convert a SQLite venue mapping into the canonical domain model."""

    values = dict(row)
    for field in ("latitude", "longitude"):
        if values[field] is not None:
            values[field] = float(values[field])
    return VenueRecord.model_validate(values)


def _artist_candidate_from_row(row: Any) -> ArtistCandidate:
    """Convert SQLite candidate data into a typed review record."""

    values = dict(row)
    values.pop("id", None)
    values["genres"] = values.pop("genres_json")
    values["confidence"] = float(values["confidence"])
    retrieved_at = values["retrieved_at"]
    if retrieved_at.tzinfo is None:
        values["retrieved_at"] = retrieved_at.replace(tzinfo=timezone.utc)
    return ArtistCandidate.model_validate(values)


def _candidate_from_row(row: Any) -> VenueCandidate:
    """Convert SQLite candidate data into a typed review record."""

    values = dict(row)
    values.pop("id", None)
    for field in ("latitude", "longitude", "confidence"):
        values[field] = (
            None
            if values[field] is None or values[field] == "None"
            else float(values[field])
        )
    retrieved_at = values["retrieved_at"]
    if retrieved_at.tzinfo is None:
        values["retrieved_at"] = retrieved_at.replace(tzinfo=timezone.utc)
    return VenueCandidate.model_validate(values)
