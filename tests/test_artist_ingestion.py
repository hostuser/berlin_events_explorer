"""Tests for bounded artist candidate ingestion."""

from datetime import UTC, date, datetime

from berlin_events_explorer.artist_ingestion import enrich_artists
from berlin_events_explorer.artists import bootstrap_artist_catalog
from berlin_events_explorer.models import (
    ArtistCandidate,
    Event,
    EventSourceRef,
    Performer,
)
from berlin_events_explorer.storage import EventStore


class _Provider:
    def discover(self, artist, *, refresh=False):
        if artist.name == "Die Ärzte":
            return [
                ArtistCandidate(
                    artist_id=artist.id,
                    provider="musicbrainz",
                    source_url="https://musicbrainz.org/artist/11111111-1111-1111-1111-111111111111",
                    musicbrainz_id="11111111-1111-1111-1111-111111111111",
                    display_name="Die Ärzte",
                    provider_score=100,
                    confidence=1.0,
                    retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
                )
            ]
        return [
            ArtistCandidate(
                artist_id=artist.id,
                provider="musicbrainz",
                source_url="https://musicbrainz.org/artist/22222222-2222-2222-2222-222222222222",
                musicbrainz_id="22222222-2222-2222-2222-222222222222",
                display_name="Keimzeit",
                provider_score=90,
                confidence=0.9,
                retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
        ]


class _NoMatchProvider:
    def __init__(self) -> None:
        self.calls = 0

    def discover(self, artist, *, refresh=False):
        self.calls += 1
        return []


def test_enrich_artists_records_no_match_and_does_not_repeat_it(tmp_path) -> None:
    """A successful empty provider result stays retryable by refresh but skips normal batches."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(
        Event(
            id="event-1",
            source=EventSourceRef(
                provider="test",
                source_url="https://example.test",
                source_record_hash="event-1",
            ),
            start_date=date(2026, 8, 1),
            title="Example event",
            performers=[Performer(name="No Match", billing_order=1)],
        )
    )
    bootstrap_artist_catalog(store)
    provider = _NoMatchProvider()

    first = enrich_artists(store, provider, limit=10)
    second = enrich_artists(store, provider, limit=10)

    assert (first.checked, first.no_match, first.remaining) == (1, 1, 0)
    assert (second.checked, second.no_match, second.remaining) == (0, 0, 0)
    assert provider.calls == 1


def test_enrich_artists_auto_approves_exact_match_and_queues_other_candidates(
    tmp_path,
) -> None:
    """A bounded pass selects only safe matches and leaves the rest for review."""

    store = EventStore(tmp_path / "events.sqlite")
    store.upsert(
        Event(
            id="event-1",
            source=EventSourceRef(
                provider="test",
                source_url="https://example.test",
                source_record_hash="event-1",
            ),
            start_date=date(2026, 8, 1),
            title="Example event",
            performers=[
                Performer(name="Die Ärzte", billing_order=1),
                Performer(name="Keimzeit", billing_order=2),
            ],
        )
    )
    bootstrap_artist_catalog(store)

    result = enrich_artists(store, _Provider(), limit=10, auto_approve_threshold=1.0)

    assert (result.checked, result.auto_approved, result.queued) == (2, 1, 1)
    die_arzte = store.get_artist("die-arzte")
    keimzeit = store.get_artist("keimzeit")
    assert die_arzte is not None
    assert keimzeit is not None
    assert die_arzte.status.value == "verified"
    assert keimzeit.status.value == "candidate"
