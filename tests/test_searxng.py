"""Bounded JSON search client for the SearXNG event-details provider."""

import httpx
import pytest

from berlin_events_explorer.searxng import SearxngClient, SearxngProviderError


def test_search_requests_json_with_a_bounded_result_count() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Example Show",
                        "url": "https://venue.example/events/example-show",
                        "content": "Official event listing",
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = SearxngClient("https://search.example", http_client)
        results = client.search("Example Show Berlin 2026-09-15", limit=3)

    assert str(captured["url"]) == (
        "https://search.example/search?q=Example+Show+Berlin+2026-09-15&format=json"
    )
    assert results[0].title == "Example Show"
    assert results[0].url == "https://venue.example/events/example-show"
    assert results[0].snippet == "Official event listing"


def test_search_rejects_an_endpoint_with_embedded_credentials() -> None:
    with httpx.Client() as http_client:
        with pytest.raises(ValueError, match="must not contain credentials"):
            SearxngClient("https://user:secret@search.example", http_client)


def test_search_converts_an_invalid_json_response_to_a_safe_provider_error() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"nope")
        )
    ) as http_client:
        client = SearxngClient("https://search.example", http_client)
        with pytest.raises(SearxngProviderError, match="invalid JSON"):
            client.search("Example Show", limit=3)
