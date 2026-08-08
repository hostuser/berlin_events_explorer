"""Small bounded client for an operator-configured SearXNG JSON endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx


class SearxngProviderError(RuntimeError):
    """A non-sensitive SearXNG request or response error."""


@dataclass(frozen=True)
class SearxngResult:
    """The small, untrusted result subset supplied to the research model."""

    title: str
    url: str
    snippet: str


class SearxngClient:
    """Query a configured SearXNG instance without fetching result pages."""

    def __init__(self, base_url: str, client: httpx.Client) -> None:
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("SearXNG URL must be an HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError("SearXNG URL must not contain credentials")
        self._base_url = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, "", "")
        ).rstrip("/")
        self._client = client

    def search(self, query: str, *, limit: int) -> list[SearxngResult]:
        """Return up to ``limit`` minimally parsed results for one query."""

        if not query.strip():
            raise ValueError("SearXNG query must not be blank")
        if not 1 <= limit <= 10:
            raise ValueError("SearXNG result limit must be between 1 and 10")
        try:
            response = self._client.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json"},
            )
            response.raise_for_status()
        except httpx.RequestError as exc:
            raise SearxngProviderError("SearXNG request failed") from exc
        except httpx.HTTPStatusError as exc:
            raise SearxngProviderError(
                f"SearXNG returned HTTP {exc.response.status_code}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise SearxngProviderError("SearXNG returned invalid JSON") from exc
        return _parse_results(payload, limit=limit)


def _parse_results(payload: object, *, limit: int) -> list[SearxngResult]:
    """Parse only well-formed search result entries, without repairing data."""

    if not isinstance(payload, dict):
        return []
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []
    results: list[SearxngResult] = []
    for result in raw_results:
        if not isinstance(result, dict):
            continue
        title = result.get("title")
        url = result.get("url")
        snippet = result.get("content", "")
        if not isinstance(title, str) or not title.strip() or not isinstance(url, str):
            continue
        if not isinstance(snippet, str):
            continue
        results.append(
            SearxngResult(title=title.strip(), url=url.strip(), snippet=snippet.strip())
        )
        if len(results) == limit:
            break
    return results
