"""Tests for canonical artist catalogue helpers."""

from datetime import date

from berlin_events_explorer.models import ArtistStatus, Event, EventSourceRef, Performer
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.artists import (
    bootstrap_artist_catalog,
    classify_artist_label,
    normalize_artist_name,
)


def _event(event_id: str, *performers: str) -> Event:
    """Build an event with source performer labels."""

    return Event(
        id=event_id,
        source=EventSourceRef(
            provider="test",
            source_url="https://example.test/events.csv",
            source_record_hash=event_id,
        ),
        start_date=date(2026, 8, 1),
        title=f"Event {event_id}",
        performers=[
            Performer(name=name, billing_order=index)
            for index, name in enumerate(performers, start=1)
        ],
    )


def test_normalize_artist_name_collapses_unicode_case_and_whitespace() -> None:
    """Source spelling variants share one conservative identity key."""

    assert normalize_artist_name("  DIE\u00a0\u00c4rzte  ") == "die \u00e4rzte"


def test_classify_artist_label_excludes_obvious_non_artist_programme_labels() -> None:
    """URLs and festival/programme labels never consume provider request capacity."""

    assert classify_artist_label("TBA") is ArtistStatus.NOT_AN_ARTIST
    assert (
        classify_artist_label("https://zigzag-jazzfestival.de/")
        is ArtistStatus.NOT_AN_ARTIST
    )
    assert (
        classify_artist_label("The Zig Zag Jazz Festival - Day 1")
        is ArtistStatus.NOT_AN_ARTIST
    )


def test_bootstrap_catalog_links_source_billings_without_splitting_composites(
    tmp_path,
) -> None:
    """Every source billing is retained while simple variants share one record."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one", "Die \u00c4rzte", "Sido + Kool Savas"))
    store.upsert(_event("two", "  die \u00e4rzte  ", "TBA"))

    result = bootstrap_artist_catalog(store)

    artists = store.list_artists()
    assert result.created == 3
    assert result.linked == 4
    assert [artist.normalized_name for artist in artists] == [
        "die \u00e4rzte",
        "sido + kool savas",
        "tba",
    ]
    assert store.get_artist_ids_for_event_performers(["one", "two"]) == {
        ("one", 1): "die-arzte",
        ("one", 2): "sido-kool-savas",
        ("two", 1): "die-arzte",
        ("two", 2): "tba",
    }


def test_bootstrap_catalog_is_idempotent(tmp_path) -> None:
    """A repeated local catalogue pass does not create duplicate records or links."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(_event("one", "Belcea Quartet"))

    first = bootstrap_artist_catalog(store)
    second = bootstrap_artist_catalog(store)

    assert (first.created, first.linked) == (1, 1)
    assert (second.created, second.linked) == (0, 0)
