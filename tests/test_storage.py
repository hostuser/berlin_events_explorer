"""Tests for SQLite event and application-log persistence."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from berlin_events_explorer.models import (
    ArtistCandidate,
    ArtistRecord,
    ArtistStatus,
    Event,
    EventSourceRef,
    Performer,
    Venue,
    VenueCandidate,
    VenueMetadata,
    UserRole,
    VenueRecord,
    VenueStatus,
)
from berlin_events_explorer.storage import EventStore


def test_store_persists_structured_logs_at_supported_levels(tmp_path) -> None:
    """Application diagnostics should retain their level, message, and context."""

    store = EventStore(tmp_path / "events.sqlite")
    store.log(
        level="info",
        event="sync_started",
        message="Starting source synchronization.",
        context={"provider": "mytrueintent"},
    )
    store.log(
        level="debug",
        event="source_response_received",
        message="Received source payload.",
        context={"status_code": 200},
    )

    logs = store.list_logs()

    assert [entry.level for entry in logs] == ["info", "debug"]
    assert logs[0].event == "sync_started"
    assert logs[0].context == {"provider": "mytrueintent"}
    assert logs[1].context == {"status_code": 200}


def _event(event_id: str = "event-1") -> Event:
    """Build an event that can be associated with a canonical venue."""

    return Event(
        id=event_id,
        source=EventSourceRef(
            provider="test",
            source_url="https://example.test",
            source_record_hash=event_id,
        ),
        start_date=date(2026, 8, 1),
        title="Example event",
    )


def _venue() -> VenueRecord:
    """Build an independently stored canonical venue."""

    return VenueRecord(
        id="berghain",
        name="Berghain",
        normalized_name="berghain",
        status=VenueStatus.UNRESOLVED,
    )


def test_store_persists_application_setting(tmp_path) -> None:
    """Web configuration survives reopening the SQLite store."""

    database = tmp_path / "events.sqlite"
    EventStore(database).set_setting("auto_approve_threshold", 0.94)

    assert EventStore(database).get_setting("auto_approve_threshold") == 0.94


def test_clear_application_data_preserves_settings(tmp_path) -> None:
    """A development reset removes content but retains configured settings."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.set_setting("auto_approve_threshold", 0.94)
    store.upsert(_event())
    store.upsert_venue(_venue())
    store.link_event_venue("event-1", "berghain", source_name="Berghain")

    store.clear_application_data()

    assert list(store.list_events()) == []
    assert store.list_venues() == []
    assert store.get_setting("auto_approve_threshold") == 0.94


def test_store_upserts_canonical_venue_and_metadata(tmp_path) -> None:
    """Canonical venue details and per-field provenance survive round trips."""

    store = EventStore(tmp_path / "events.sqlite")
    venue = _venue()

    stored = store.upsert_venue(venue, now=datetime(2026, 7, 30, tzinfo=UTC))
    updated = store.upsert_venue(
        venue.model_copy(
            update={
                "address": "Am Wriezener Bahnhof, 10243 Berlin",
                "status": VenueStatus.VERIFIED,
            }
        ),
        now=datetime(2026, 7, 31, tzinfo=UTC),
    )
    store.save_venue_metadata(
        VenueMetadata(
            venue_id="berghain",
            field="address",
            value="Am Wriezener Bahnhof, 10243 Berlin",
            provider="openstreetmap",
            source_url="https://www.openstreetmap.org/node/1",
            confidence=0.98,
            retrieved_at=datetime(2026, 7, 31, tzinfo=UTC),
        )
    )

    persisted = store.get_venue("berghain")

    assert stored.status is VenueStatus.UNRESOLVED
    assert updated.status is VenueStatus.VERIFIED
    assert persisted is not None
    assert persisted.address == "Am Wriezener Bahnhof, 10243 Berlin"
    assert persisted.status is VenueStatus.VERIFIED
    assert store.list_venue_metadata("berghain")[0].field == "address"


def test_store_links_events_to_canonical_venues_idempotently(tmp_path) -> None:
    """Event-to-venue links retain source spelling without duplicate associations."""

    store = EventStore(tmp_path / "events.sqlite")
    event = _event()
    store.upsert(event)
    store.upsert_venue(_venue())

    store.link_event_venue(event.id, "berghain", source_name="Berghain")
    store.link_event_venue(event.id, "berghain", source_name="Berghain")

    linked_venue = store.get_venue_for_event(event.id)

    assert linked_venue is not None
    assert linked_venue.id == "berghain"
    assert store.get_venue_ids_for_events([event.id]) == {event.id: "berghain"}
    assert [
        stored_event.id for stored_event in store.list_events_for_venue("berghain")
    ] == [event.id]


def test_store_records_and_selects_artist_candidate_atomically(tmp_path) -> None:
    """A selected artist candidate publishes fields and records their provenance."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_artist(
        ArtistRecord(id="die-arzte", name="Die Ärzte", normalized_name="die ärzte")
    )
    candidate = ArtistCandidate(
        artist_id="die-arzte",
        provider="musicbrainz",
        source_url="https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111",
        musicbrainz_id="11111111-1111-1111-1111-111111111111",
        display_name="Die Ärzte",
        artist_type="Group",
        country="DE",
        genres=["punk rock"],
        provider_score=100,
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    store.record_artist_candidates([candidate])
    selected = store.select_artist_candidate(
        "die-arzte", "musicbrainz", candidate.musicbrainz_id
    )

    assert selected.status is ArtistStatus.VERIFIED
    assert selected.musicbrainz_id == candidate.musicbrainz_id
    assert selected.artist_type == "Group"
    assert selected.genres == ["punk rock"]
    assert {metadata.field for metadata in store.list_artist_metadata("die-arzte")} >= {
        "artist_type",
        "country",
        "genres",
    }


def test_store_records_and_explicitly_selects_venue_candidate(tmp_path) -> None:
    """Only explicit candidate selection promotes discovered metadata to public fields."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_venue(_venue())
    candidate = VenueCandidate(
        venue_id="berghain",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/1",
        osm_type="node",
        osm_id="1",
        display_name="Berghain, Berlin",
        address="Am Wriezener Bahnhof, 10243 Berlin",
        postal_code="10243",
        website="https://www.berghain.berlin/",
        latitude=52.5112,
        longitude=13.4437,
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    store.record_venue_candidates([candidate])
    before_selection = store.get_venue("berghain")
    selected = store.select_venue_candidate("berghain", "nominatim", "node", "1")

    assert before_selection is not None
    assert before_selection.address is None
    assert store.list_venue_candidates("berghain") == [candidate]
    assert selected.status is VenueStatus.VERIFIED
    assert selected.website == "https://www.berghain.berlin/"
    assert {metadata.field for metadata in store.list_venue_metadata("berghain")} >= {
        "address",
        "website",
    }


def test_store_selects_venue_candidate_without_coordinates(tmp_path) -> None:
    """Coordinates are optional metadata and must not block candidate approval."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_venue(_venue())
    candidate = VenueCandidate(
        venue_id="berghain",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/1",
        osm_type="node",
        osm_id="1",
        display_name="Berghain, Berlin",
        address="Am Wriezener Bahnhof, 10243 Berlin",
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    store.record_venue_candidates([candidate])

    selected = store.select_venue_candidate("berghain", "nominatim", "node", "1")

    assert selected.status is VenueStatus.VERIFIED
    assert selected.latitude is None
    assert selected.longitude is None


def test_recording_refreshed_candidates_replaces_stale_results(tmp_path) -> None:
    """A provider refresh must remove older duplicate or obsolete candidates."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_venue(_venue())
    first = VenueCandidate(
        venue_id="berghain",
        provider="nominatim",
        source_url="https://www.openstreetmap.org/node/1",
        osm_type="node",
        osm_id="1",
        display_name="Berghain, Berlin",
        address="Am Wriezener Bahnhof, 10243 Berlin",
        confidence=1.0,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    duplicate = first.model_copy(
        update={
            "source_url": "https://www.openstreetmap.org/node/2",
            "osm_id": "2",
        }
    )
    store.record_venue_candidates([first, duplicate])

    store.record_venue_candidates([first])

    assert store.list_venue_candidates("berghain") == [first]


def test_engine_enables_wal_busy_timeout_and_foreign_keys(tmp_path) -> None:
    """Concurrent readers and writers need WAL, a busy timeout, and real FKs."""

    store = EventStore(tmp_path / "events.sqlite")
    with store.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_linking_unknown_event_or_venue_is_rejected(tmp_path) -> None:
    """Foreign keys must be enforced instead of silently creating orphans."""

    store = EventStore(tmp_path / "events.sqlite")
    with pytest.raises(IntegrityError):
        store.link_event_venue("missing-event", "missing-venue", source_name="Nowhere")


def test_deleting_stale_events_also_removes_link_rows(tmp_path) -> None:
    """Removing provider events must not leave venue or artist links behind."""

    store = EventStore(tmp_path / "events.sqlite")
    event = _event()
    store.upsert(event)
    store.upsert_venue(_venue())
    store.link_event_venue(event.id, "berghain", source_name="Berghain")
    store.upsert_artist(
        ArtistRecord(id="dj-example", name="DJ Example", normalized_name="dj example")
    )
    store.link_event_artist(event.id, 1, "dj-example", source_name="DJ Example")

    deleted = store.delete_events_not_in(
        provider="test", event_ids={"some-other-event"}
    )

    assert deleted == 1
    assert store.get_venue_ids_for_events([event.id]) == {}
    assert store.get_artist_ids_for_event_performers([event.id]) == {}


def _query_event(
    event_id: str,
    *,
    title: str,
    start_date: date | None,
    end_date: date | None = None,
    first_seen_at: datetime | None = None,
    performer: str | None = None,
) -> Event:
    """Build one event for SQL query tests."""

    return Event(
        id=event_id,
        source=EventSourceRef(
            provider="test",
            source_url="https://example.test",
            source_record_hash=event_id,
        ),
        title=title,
        start_date=start_date,
        end_date=end_date,
        first_seen_at=first_seen_at,
        performers=[Performer(name=performer, billing_order=1)] if performer else [],
        venue=Venue(name="Kesselhaus"),
    )


def test_query_events_upcoming_filters_sorts_and_paginates_in_sql(tmp_path) -> None:
    """The upcoming view must come straight from SQL, not a full-table scan."""

    store = EventStore(tmp_path / "events.sqlite")
    today = date.today()
    for index, title in enumerate(["Delta", "Alpha", "Beta", "Gamma"]):
        store.upsert(
            _query_event(
                f"future-{index}",
                title=title,
                start_date=today + timedelta(days=index + 1),
            )
        )
    store.upsert(
        _query_event("past", title="Past", start_date=today - timedelta(days=1))
    )
    store.upsert(_query_event("undated", title="Undated", start_date=None))

    events, total, current_page, total_pages = store.query_events(
        tab="upcoming", recent_days=7, search="", page=2, page_size=3
    )

    assert total == 4
    assert (current_page, total_pages) == (2, 2)
    assert [event.title for event in events] == ["Gamma"]


def test_query_events_searches_performers_case_insensitively(tmp_path) -> None:
    """Search must match performers and handle non-ASCII case folding."""

    store = EventStore(tmp_path / "events.sqlite")
    today = date.today()
    store.upsert(
        _query_event(
            "match",
            title="Punk Abend",
            start_date=today + timedelta(days=1),
            performer="Die Ärzte",
        )
    )
    store.upsert(
        _query_event("other", title="Jazz Abend", start_date=today + timedelta(days=2))
    )

    events, total, _, _ = store.query_events(
        tab="upcoming", recent_days=7, search="ÄRZTE".casefold(), page=1, page_size=10
    )

    assert total == 1
    assert [event.id for event in events] == ["match"]


def test_query_events_recent_tab_returns_newest_first(tmp_path) -> None:
    """The recent view should filter by first-seen window and sort newest first."""

    store = EventStore(tmp_path / "events.sqlite")
    now = datetime.now(UTC)
    today = date.today()
    store.upsert(
        _query_event(
            "new",
            title="New",
            start_date=today + timedelta(days=1),
            first_seen_at=now - timedelta(days=1),
        )
    )
    store.upsert(
        _query_event(
            "newer",
            title="Newer",
            start_date=today + timedelta(days=1),
            first_seen_at=now - timedelta(hours=1),
        )
    )
    store.upsert(
        _query_event(
            "old",
            title="Old",
            start_date=today + timedelta(days=1),
            first_seen_at=now - timedelta(days=30),
        )
    )

    events, total, _, _ = store.query_events(
        tab="recent", recent_days=7, search="", page=1, page_size=10
    )

    assert total == 2
    assert [event.id for event in events] == ["newer", "new"]


def test_list_events_on_date_includes_range_overlaps(tmp_path) -> None:
    """A calendar date should include single-day and overlapping range events."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_query_event("single", title="Single", start_date=date(2026, 7, 10)))
    store.upsert(
        _query_event(
            "multi",
            title="Multi",
            start_date=date(2026, 7, 9),
            end_date=date(2026, 7, 11),
        )
    )
    store.upsert(_query_event("other", title="Other", start_date=date(2026, 7, 12)))

    events = store.list_events_on_date(date(2026, 7, 10))

    assert [event.id for event in events] == ["multi", "single"]


def test_search_text_is_backfilled_for_legacy_rows(tmp_path) -> None:
    """Rows written before the search column existed become searchable on open."""

    database = tmp_path / "events.sqlite"
    store = EventStore(database)
    store.upsert(
        _query_event(
            "legacy",
            title="Punk Abend",
            start_date=date.today() + timedelta(days=1),
            performer="Die Ärzte",
        )
    )
    with store.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE events SET search_text = NULL")

    reopened = EventStore(database)
    events, total, _, _ = reopened.query_events(
        tab="upcoming", recent_days=7, search="ärzte", page=1, page_size=10
    )

    assert total == 1
    assert [event.id for event in events] == ["legacy"]


def test_empty_snapshot_does_not_wipe_provider_events(tmp_path) -> None:
    """A parseable but empty source batch must not delete the whole catalog."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event())

    deleted = store.delete_events_not_in(provider="test", event_ids=set())

    assert deleted == 0
    assert [event.id for event in store.list_events()] == ["event-1"]
    assert any(
        entry.event == "empty_snapshot_deletion_skipped" and entry.level == "warning"
        for entry in store.list_logs()
    )


def test_empty_snapshot_with_no_stored_events_stays_quiet(tmp_path) -> None:
    """An empty snapshot over an empty catalog needs no warning."""

    store = EventStore(tmp_path / "events.sqlite")

    deleted = store.delete_events_not_in(provider="test", event_ids=set())

    assert deleted == 0
    assert store.list_logs() == []


def test_update_preserves_original_first_seen_timestamp(tmp_path) -> None:
    """Content changes must not reset when an event was first observed."""

    store = EventStore(tmp_path / "events.sqlite")
    first_seen = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    original = _query_event(
        "evt-first-seen",
        title="Original Title",
        start_date=date.today() + timedelta(days=3),
        first_seen_at=first_seen,
    )
    store.upsert(original)

    changed = original.model_copy(
        update={
            "title": "Changed Title",
            "first_seen_at": datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        }
    )
    result = store.upsert(changed)

    stored = store.list_events()[0]
    assert result.action == "updated"
    assert stored.title == "Changed Title"
    assert stored.first_seen_at == first_seen


def test_candidate_counts_come_from_single_grouped_queries(tmp_path) -> None:
    """Approval queues need one count query, not one query per pending row."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert_venue(_venue())
    for osm_id in ("1", "2"):
        store.record_venue_candidates(
            [
                VenueCandidate(
                    venue_id="berghain",
                    provider="nominatim",
                    source_url=f"https://www.openstreetmap.org/node/{osm_id}",
                    osm_type="node",
                    osm_id=osm_id,
                    display_name=f"Berghain {osm_id}",
                    confidence=0.9,
                    retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
                )
                for osm_id in ("1", "2")
            ]
        )
    store.upsert_artist(
        ArtistRecord(id="die-arzte", name="Die Ärzte", normalized_name="die ärzte")
    )
    store.record_artist_candidates(
        [
            ArtistCandidate(
                artist_id="die-arzte",
                provider="musicbrainz",
                source_url="https://musicbrainz.org/artist/1",
                musicbrainz_id="11111111-1111-1111-1111-111111111111",
                display_name="Die Ärzte",
                confidence=1.0,
                retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
        ]
    )

    assert store.count_venue_candidates_by_venue() == {"berghain": 2}
    assert store.count_artist_candidates_by_artist() == {"die-arzte": 1}


def test_pending_entities_are_filtered_in_sql(tmp_path) -> None:
    """Pending review listings should not load and filter full catalogs."""

    store = EventStore(tmp_path / "events.sqlite")
    for venue_id, status in (
        ("a-unresolved", VenueStatus.UNRESOLVED),
        ("b-candidate", VenueStatus.CANDIDATE),
        ("c-verified", VenueStatus.VERIFIED),
        ("d-rejected", VenueStatus.REJECTED),
        ("e-not-a-venue", VenueStatus.NOT_A_VENUE),
    ):
        store.upsert_venue(
            VenueRecord(
                id=venue_id,
                name=venue_id.title(),
                normalized_name=venue_id,
                status=status,
            )
        )
    for artist_id, artist_status in (
        ("x-unresolved", ArtistStatus.UNRESOLVED),
        ("y-candidate", ArtistStatus.CANDIDATE),
        ("z-verified", ArtistStatus.VERIFIED),
    ):
        store.upsert_artist(
            ArtistRecord(
                id=artist_id,
                name=artist_id.title(),
                normalized_name=artist_id,
                status=artist_status,
            )
        )

    assert [venue.id for venue in store.list_pending_venues()] == [
        "a-unresolved",
        "b-candidate",
    ]
    assert [artist.id for artist in store.list_pending_artists()] == [
        "x-unresolved",
        "y-candidate",
    ]


def test_event_performer_links_can_be_limited_to_verified_artists(tmp_path) -> None:
    """Public listings need verified links without loading the artist catalog."""

    store = EventStore(tmp_path / "events.sqlite")
    event = _event()
    store.upsert(event)
    store.upsert_artist(
        ArtistRecord(
            id="verified-artist",
            name="Verified",
            normalized_name="verified",
            status=ArtistStatus.VERIFIED,
        )
    )
    store.upsert_artist(
        ArtistRecord(
            id="unresolved-artist",
            name="Unresolved",
            normalized_name="unresolved",
        )
    )
    store.link_event_artist(event.id, 1, "verified-artist", source_name="Verified")
    store.link_event_artist(event.id, 2, "unresolved-artist", source_name="Unresolved")

    all_links = store.get_artist_ids_for_event_performers([event.id])
    verified_links = store.get_artist_ids_for_event_performers(
        [event.id], only_verified=True
    )

    assert all_links == {
        (event.id, 1): "verified-artist",
        (event.id, 2): "unresolved-artist",
    }
    assert verified_links == {(event.id, 1): "verified-artist"}


def _seed_user(
    store: EventStore,
    *,
    email: str = "markus@example.org",
    password_hash: str = "argon2-hash",
    display_name: str = "Markus",
    role: UserRole = UserRole.EDITOR,
):
    """Create an account with representative defaults."""

    return store.create_user(
        email=email,
        password_hash=password_hash,
        display_name=display_name,
        role=role,
    )


def test_create_user_roundtrips_and_normalizes_email(tmp_path) -> None:
    """Accounts persist with folded emails and timezone-aware timestamps."""

    store = EventStore(tmp_path / "events.sqlite")

    user = _seed_user(store, email="Markus@Example.ORG")

    assert user.email == "markus@example.org"
    assert user.role is UserRole.EDITOR
    assert user.is_active is True
    assert user.created_at.tzinfo is not None
    assert store.get_user(user.id) == user
    credentials = store.get_user_credentials("MARKUS@example.org")
    assert credentials is not None
    assert credentials.user == user
    assert credentials.password_hash == "argon2-hash"
    assert store.list_users() == [user]


def test_create_user_rejects_duplicate_email(tmp_path) -> None:
    """A second account for the same address must be refused, whatever the case."""

    store = EventStore(tmp_path / "events.sqlite")
    _seed_user(store)

    with pytest.raises(ValueError, match="already exists"):
        _seed_user(store, email="MARKUS@example.org", display_name="Impostor")


def test_update_user_applies_partial_changes(tmp_path) -> None:
    """Only supplied fields change; the update timestamp moves forward."""

    store = EventStore(tmp_path / "events.sqlite")
    user = _seed_user(store)

    updated = store.update_user(user.id, role=UserRole.ADMIN, is_active=False)

    assert updated is not None
    assert updated.role is UserRole.ADMIN
    assert updated.is_active is False
    assert updated.display_name == "Markus"
    assert updated.updated_at >= user.updated_at

    store.update_user(user.id, password_hash="new-hash")
    credentials = store.get_user_credentials(user.email)
    assert credentials is not None
    assert credentials.password_hash == "new-hash"
    assert store.update_user(9999, role=UserRole.USER) is None


def test_record_user_login_sets_last_login_at(tmp_path) -> None:
    """Successful logins leave an operational trace on the account."""

    store = EventStore(tmp_path / "events.sqlite")
    user = _seed_user(store)
    assert user.last_login_at is None

    store.record_user_login(user.id)

    refreshed = store.get_user(user.id)
    assert refreshed is not None
    assert refreshed.last_login_at is not None


def test_count_admins_counts_only_active_admins(tmp_path) -> None:
    """Lockout checks need the number of remaining usable admin accounts."""

    store = EventStore(tmp_path / "events.sqlite")
    _seed_user(store, email="editor@example.org", role=UserRole.EDITOR)
    admin = _seed_user(store, email="admin@example.org", role=UserRole.ADMIN)
    _seed_user(store, email="admin2@example.org", role=UserRole.ADMIN)

    assert store.count_admins() == 2

    store.update_user(admin.id, is_active=False)
    assert store.count_admins() == 1


def test_auth_token_lifecycle(tmp_path) -> None:
    """Tokens are stored hashed, looked up by purpose, and single-use."""

    store = EventStore(tmp_path / "events.sqlite")
    admin = _seed_user(store, email="admin@example.org", role=UserRole.ADMIN)
    expires = datetime.now(UTC) + timedelta(days=7)

    store.create_auth_token(
        purpose="invite",
        token_hash="hash-1",
        email="invitee@example.org",
        role=UserRole.USER,
        created_by=admin.id,
        expires_at=expires,
    )

    token = store.get_auth_token("hash-1", purpose="invite")
    assert token is not None
    assert token.email == "invitee@example.org"
    assert token.role is UserRole.USER
    assert token.created_by == admin.id
    assert token.used_at is None
    assert token.expires_at.tzinfo is not None
    assert store.get_auth_token("hash-1", purpose="password_reset") is None
    assert store.get_auth_token("missing", purpose="invite") is None

    assert [pending.email for pending in store.list_pending_invites()] == [
        "invitee@example.org"
    ]

    store.mark_auth_token_used(token.id)
    used = store.get_auth_token("hash-1", purpose="invite")
    assert used is not None
    assert used.used_at is not None
    assert store.list_pending_invites() == []


def test_pending_invites_exclude_expired_tokens(tmp_path) -> None:
    """An expired invite is dead; it must not linger in the admin queue."""

    store = EventStore(tmp_path / "events.sqlite")
    store.create_auth_token(
        purpose="invite",
        token_hash="hash-expired",
        email="late@example.org",
        role=UserRole.USER,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    assert store.list_pending_invites() == []


def test_delete_auth_tokens_scopes_by_purpose_and_subject(tmp_path) -> None:
    """Regenerating an invite or reset invalidates only its predecessors."""

    store = EventStore(tmp_path / "events.sqlite")
    user = _seed_user(store)
    expires = datetime.now(UTC) + timedelta(days=1)
    store.create_auth_token(
        purpose="invite",
        token_hash="invite-a",
        email="invitee@example.org",
        role=UserRole.USER,
        expires_at=expires,
    )
    store.create_auth_token(
        purpose="password_reset",
        token_hash="reset-a",
        email=user.email,
        user_id=user.id,
        expires_at=expires,
    )

    store.delete_auth_tokens(purpose="invite", email="invitee@example.org")

    assert store.get_auth_token("invite-a", purpose="invite") is None
    assert store.get_auth_token("reset-a", purpose="password_reset") is not None

    store.delete_auth_tokens(purpose="password_reset", user_id=user.id)
    assert store.get_auth_token("reset-a", purpose="password_reset") is None


def test_user_settings_upsert_and_delete(tmp_path) -> None:
    """Per-user preferences overwrite cleanly and disappear on delete."""

    store = EventStore(tmp_path / "events.sqlite")
    user = _seed_user(store)

    assert store.get_user_setting(user.id, "default_table_size") is None

    store.set_user_setting(user.id, "default_table_size", 25)
    assert store.get_user_setting(user.id, "default_table_size") == 25

    store.set_user_setting(user.id, "default_table_size", 50)
    assert store.get_user_setting(user.id, "default_table_size") == 50

    store.delete_user_setting(user.id, "default_table_size")
    assert store.get_user_setting(user.id, "default_table_size") is None


def test_clear_application_data_preserves_accounts(tmp_path) -> None:
    """Clearing synced content must never destroy accounts or their settings."""

    store = EventStore(tmp_path / "events.sqlite")
    user = _seed_user(store)
    store.set_user_setting(user.id, "default_table_size", 25)
    store.create_auth_token(
        purpose="invite",
        token_hash="hash-1",
        email="invitee@example.org",
        role=UserRole.USER,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    store.upsert(_event())

    store.clear_application_data()

    assert store.get_user(user.id) == user
    assert store.get_user_setting(user.id, "default_table_size") == 25
    assert store.get_auth_token("hash-1", purpose="invite") is None
    _events, total, _pages, _page = store.query_events(
        tab="upcoming", recent_days=7, search="", page=1, page_size=10
    )
    assert total == 0


def test_delete_auth_token_removes_exactly_one_token(tmp_path) -> None:
    """Revoking one invite must not disturb any other outstanding token."""

    store = EventStore(tmp_path / "events.sqlite")
    expires = datetime.now(UTC) + timedelta(days=1)
    store.create_auth_token(
        purpose="invite",
        token_hash="invite-a",
        email="a@example.org",
        role=UserRole.USER,
        expires_at=expires,
    )
    store.create_auth_token(
        purpose="invite",
        token_hash="invite-b",
        email="b@example.org",
        role=UserRole.USER,
        expires_at=expires,
    )
    token = store.get_auth_token("invite-a", purpose="invite")
    assert token is not None

    store.delete_auth_token(token.id)

    assert store.get_auth_token("invite-a", purpose="invite") is None
    assert store.get_auth_token("invite-b", purpose="invite") is not None
