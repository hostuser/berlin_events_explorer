"""Controlled external discovery of venue metadata candidates."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from berlin_events_explorer.models import VenueCandidate, VenueRecord
from berlin_events_explorer.venues import normalize_venue_name

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = (
    "BerlinEventsExplorer/0.1 (+https://github.com/hostuser/berlin_events_explorer)"
)
DEFAULT_AUTO_APPROVE_THRESHOLD = 0.9


def deduplicate_venue_candidates(
    candidates: list[VenueCandidate],
) -> list[VenueCandidate]:
    """Collapse provider records describing the same normalized venue and address."""

    unique: dict[tuple[str, str, str, str], VenueCandidate] = {}
    for candidate in candidates:
        identity = (
            candidate.venue_id,
            candidate.provider,
            normalize_venue_name(candidate.display_name),
            normalize_venue_name(candidate.address or ""),
        )
        existing = unique.get(identity)
        if existing is None or _candidate_quality(candidate) > _candidate_quality(
            existing
        ):
            unique[identity] = candidate
    return list(unique.values())


def _candidate_quality(candidate: VenueCandidate) -> tuple[float, bool, bool]:
    """Prefer confidence, then candidates carrying richer public metadata."""

    return (
        candidate.confidence,
        candidate.website is not None,
        candidate.address is not None,
    )


def auto_approval_candidate(
    candidates: list[VenueCandidate],
    *,
    threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
) -> VenueCandidate | None:
    """Select one unambiguous candidate meeting the automatic approval threshold."""

    if not 0 <= threshold <= 1:
        raise ValueError("auto-approval threshold must be between 0 and 1")
    eligible = deduplicate_venue_candidates(
        [candidate for candidate in candidates if candidate.confidence >= threshold]
    )
    return eligible[0] if len(eligible) == 1 else None


class VenueDiscoveryError(RuntimeError):
    """Raised when a venue discovery provider cannot return usable candidates."""


class NominatimVenueProvider:
    """Small policy-compliant adapter for manually triggered Nominatim lookups."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    def discover(
        self, venue: VenueRecord, *, now: datetime | None = None
    ) -> list[VenueCandidate]:
        """Find up to five reviewable Berlin candidates for a canonical venue."""

        self._wait_for_rate_limit()
        try:
            response = self._client.get(
                NOMINATIM_SEARCH_URL,
                params={
                    "q": f"{venue.name}, Berlin, Germany",
                    "format": "jsonv2",
                    "addressdetails": "1",
                    "extratags": "1",
                    "limit": "5",
                    "countrycodes": "de",
                },
                headers={"User-Agent": NOMINATIM_USER_AGENT, "Accept-Language": "en"},
                timeout=20.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise VenueDiscoveryError(
                f"Nominatim lookup failed for {venue.name}: {exc}"
            ) from exc
        finally:
            self._last_request_at = self._monotonic()

        try:
            payload = response.json()
        except ValueError as exc:
            raise VenueDiscoveryError("Nominatim returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise VenueDiscoveryError(
                "Nominatim returned an unexpected response payload"
            )

        retrieved_at = now or datetime.now(timezone.utc)
        candidates = [
            candidate
            for item in payload
            if isinstance(item, dict)
            and (
                candidate := _candidate_from_payload(
                    venue, item, retrieved_at=retrieved_at
                )
            )
            is not None
        ]
        return deduplicate_venue_candidates(candidates)

    def _wait_for_rate_limit(self) -> None:
        """Keep public Nominatim requests at or below one per second."""

        if self._last_request_at is None:
            return
        remaining = 1.0 - (self._monotonic() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)


def _candidate_from_payload(
    venue: VenueRecord, payload: dict[str, Any], *, retrieved_at: datetime
) -> VenueCandidate | None:
    """Convert one Nominatim response object into a safe candidate."""

    osm_type = payload.get("osm_type")
    osm_id = payload.get("osm_id")
    display_name = payload.get("display_name")
    if not all(
        isinstance(value, str | int) for value in (osm_type, osm_id, display_name)
    ):
        return None

    address_data = payload.get("address")
    if not isinstance(address_data, dict):
        address_data = {}
    address = _format_address(address_data)
    extratags = payload.get("extratags")
    website = (
        _safe_website(extratags.get("website")) if isinstance(extratags, dict) else None
    )
    latitude = _float_or_none(payload.get("lat"))
    longitude = _float_or_none(payload.get("lon"))
    source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
    return VenueCandidate(
        venue_id=venue.id,
        provider="nominatim",
        source_url=source_url,
        osm_type=str(osm_type),
        osm_id=str(osm_id),
        display_name=str(display_name),
        address=address,
        postal_code=_string_or_none(address_data.get("postcode")),
        district=_district_from_address(address_data),
        website=website,
        latitude=latitude,
        longitude=longitude,
        confidence=_confidence(venue, str(display_name), address_data),
        retrieved_at=retrieved_at,
    )


def _format_address(address: dict[str, Any]) -> str | None:
    """Render only supplied address components without filling gaps."""

    street = " ".join(
        part
        for part in (
            _string_or_none(address.get("road")),
            _string_or_none(address.get("house_number")),
        )
        if part
    )
    locality = _string_or_none(
        address.get("city") or address.get("town") or address.get("village")
    )
    postal_code = _string_or_none(address.get("postcode"))
    city_line = " ".join(part for part in (postal_code, locality) if part)
    parts = [part for part in (street, city_line) if part]
    return ", ".join(parts) or None


def _district_from_address(address: dict[str, Any]) -> str | None:
    """Return the most specific district-like locality from Nominatim data."""

    return next(
        (
            value.strip()
            for key in ("city_district", "borough", "suburb")
            if isinstance(value := address.get(key), str) and value.strip()
        ),
        None,
    )


def _safe_website(value: object) -> str | None:
    """Accept only public HTTP(S) web URLs supplied by OSM tags."""

    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _confidence(
    venue: VenueRecord, display_name: str, address: dict[str, Any]
) -> float:
    """Score direct name/city agreement without treating weak matches as verified."""

    candidate_name = normalize_venue_name(display_name.split(",", 1)[0])
    city = normalize_venue_name(str(address.get("city") or address.get("town") or ""))
    return 1.0 if candidate_name == venue.normalized_name and city == "berlin" else 0.5


def _float_or_none(value: object) -> float | None:
    if not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
