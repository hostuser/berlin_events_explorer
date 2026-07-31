"""Tests for controlled Nominatim venue candidate discovery."""

from datetime import UTC, datetime

import httpx

from berlin_events_explorer.models import VenueCandidate, VenueRecord
from berlin_events_explorer.venue_enrichment import (
    NominatimVenueProvider,
    auto_approval_candidate,
)


def test_nominatim_discovery_queries_berlin_and_parses_safe_metadata() -> None:
    """The provider scopes requests and extracts address plus HTTPS homepage tags."""

    observed_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_request
        observed_request = request
        return httpx.Response(
            200,
            json=[
                {
                    "osm_type": "node",
                    "osm_id": 1,
                    "lat": "52.5112",
                    "lon": "13.4437",
                    "display_name": "Berghain, Friedrichshain-Kreuzberg, Berlin",
                    "address": {
                        "road": "Am Wriezener Bahnhof",
                        "postcode": "10243",
                        "city": "Berlin",
                    },
                    "extratags": {"website": "https://www.berghain.berlin/"},
                }
            ],
        )

    provider = NominatimVenueProvider(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    venue = VenueRecord(id="berghain", name="Berghain", normalized_name="berghain")

    candidates = provider.discover(venue, now=datetime(2026, 7, 30, tzinfo=UTC))

    assert observed_request is not None
    assert observed_request.url.params["q"] == "Berghain, Berlin, Germany"
    assert observed_request.url.params["limit"] == "5"
    assert observed_request.headers["user-agent"].startswith("BerlinEventsExplorer/")
    assert candidates[0].address == "Am Wriezener Bahnhof, 10243 Berlin"
    assert candidates[0].website == "https://www.berghain.berlin/"
    assert candidates[0].confidence == 1.0


def test_nominatim_discovery_discards_non_http_website_tags() -> None:
    """Unsupported contact links never become public homepage candidates."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "osm_type": "way",
                    "osm_id": 2,
                    "lat": "52.5",
                    "lon": "13.4",
                    "display_name": "Example Club, Berlin",
                    "address": {"city": "Berlin"},
                    "extratags": {"website": "mailto:hello@example.test"},
                }
            ],
        )

    provider = NominatimVenueProvider(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    venue = VenueRecord(
        id="example-club", name="Example Club", normalized_name="example club"
    )

    candidates = provider.discover(venue, now=datetime(2026, 7, 30, tzinfo=UTC))

    assert candidates[0].website is None


def test_nominatim_discovery_returns_one_candidate_for_duplicate_osm_objects() -> None:
    """Equivalent OSM objects must appear as one editorial suggestion."""

    def handler(_: httpx.Request) -> httpx.Response:
        common = {
            "display_name": (
                "Berghain, Am Wriezener Bahnhof, Friedrichshain, Berlin, 10243, Germany"
            ),
            "address": {
                "road": "Am Wriezener Bahnhof",
                "postcode": "10243",
                "city": "Berlin",
            },
        }
        return httpx.Response(
            200,
            json=[
                {
                    **common,
                    "osm_type": "node",
                    "osm_id": 1,
                    "lat": "52.5111",
                    "lon": "13.4430",
                },
                {
                    **common,
                    "osm_type": "node",
                    "osm_id": 2,
                    "lat": "52.5105",
                    "lon": "13.4420",
                },
            ],
        )

    provider = NominatimVenueProvider(
        httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    venue = VenueRecord(id="berghain", name="Berghain", normalized_name="berghain")

    candidates = provider.discover(venue, now=datetime(2026, 7, 30, tzinfo=UTC))

    assert len(candidates) == 1
    assert candidates[0].osm_id == "1"


def _candidate(
    osm_id: str, confidence: float, *, display_name: str = "Example Club, Berlin"
) -> VenueCandidate:
    return VenueCandidate(
        venue_id="example-club",
        provider="nominatim",
        source_url=f"https://www.openstreetmap.org/node/{osm_id}",
        osm_type="node",
        osm_id=osm_id,
        display_name=display_name,
        confidence=confidence,
        retrieved_at=datetime(2026, 7, 30, tzinfo=UTC),
    )


def test_auto_approval_selects_the_only_candidate_at_the_threshold() -> None:
    """One high-confidence match can skip manual review."""

    selected = auto_approval_candidate(
        [_candidate("1", 0.95), _candidate("2", 0.5)], threshold=0.9
    )

    assert selected is not None
    assert selected.osm_id == "1"


def test_auto_approval_keeps_multiple_high_confidence_candidates_for_review() -> None:
    """A score cannot resolve ambiguity between multiple plausible entities."""

    selected = auto_approval_candidate(
        [
            _candidate("1", 1.0, display_name="Example Club, Berlin East"),
            _candidate("2", 0.95, display_name="Example Club, Berlin West"),
        ],
        threshold=0.9,
    )

    assert selected is None


def test_auto_approval_collapses_duplicate_osm_objects_for_one_entity() -> None:
    """Equivalent node/way results should not manufacture editorial ambiguity."""

    selected = auto_approval_candidate(
        [_candidate("1", 1.0), _candidate("2", 1.0)], threshold=0.9
    )

    assert selected is not None
    assert selected.osm_id == "1"
