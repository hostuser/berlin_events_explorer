"""Create canonical venues and enrich only records first seen in this pass."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Protocol

import httpx
from diskcache import Cache

from berlin_events_explorer.models import VenueCandidate, VenueRecord, VenueStatus
from berlin_events_explorer.performer_title_augmentation import (
    PerformerExtractor,
    ingest_new_event_performers,
)
from berlin_events_explorer.sources.base import EventSource
from berlin_events_explorer.storage import EventStore
from berlin_events_explorer.sync import SyncResult, sync_source
from berlin_events_explorer.venue_enrichment import (
    DEFAULT_AUTO_APPROVE_THRESHOLD,
    NominatimVenueProvider,
    VenueDiscoveryError,
    auto_approval_candidate,
)
from berlin_events_explorer.artists import bootstrap_artist_catalog
from berlin_events_explorer.venues import bootstrap_venue_catalog


class VenueCandidateProvider(Protocol):
    """Provider capable of proposing metadata for one canonical venue."""

    def discover(self, venue: VenueRecord) -> list[VenueCandidate]: ...


VenueProgress = tuple[int, int, str | None]
VenueProgressCallback = Callable[[VenueProgress], None]


@dataclass(frozen=True)
class VenueIngestionResult:
    """Summary of catalog and enrichment work for newly created venues."""

    created: int
    linked: int
    unchanged: int
    auto_approved: int
    awaiting_approval: int
    errors: int


def sync_source_and_ingest_venues(
    source: EventSource,
    store: EventStore,
    client: httpx.Client,
    *,
    http_cache: Cache | None = None,
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
    progress: VenueProgressCallback | None = None,
    performer_extractor: PerformerExtractor | None = None,
) -> tuple[SyncResult, VenueIngestionResult]:
    """Synchronize events, extract new billed performers, then ingest new venues."""

    sync_result = sync_source(source, store, client, http_cache=http_cache)
    if performer_extractor is not None and sync_result.created_event_ids:
        performer_result = ingest_new_event_performers(
            store, performer_extractor, event_ids=sync_result.created_event_ids
        )
        sync_result = replace(
            sync_result,
            performer_extracted=performer_result.extracted,
            performer_no_match=performer_result.no_match,
            performer_errors=performer_result.errors,
        )
    venue_result = ingest_new_event_venues(
        store,
        NominatimVenueProvider(client),
        auto_approve_threshold=auto_approve_threshold,
        progress=progress,
    )
    bootstrap_artist_catalog(store)
    return sync_result, venue_result


def ingest_new_event_venues(
    store: EventStore,
    provider: VenueCandidateProvider,
    *,
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD,
    progress: VenueProgressCallback | None = None,
) -> VenueIngestionResult:
    """Catalog event venues and discover metadata only for newly created records."""

    existing_ids = {venue.id for venue in store.list_venues()}
    catalog = bootstrap_venue_catalog(store)
    new_venues = [
        venue
        for venue in store.list_venues()
        if venue.id not in existing_ids and venue.status is not VenueStatus.NOT_A_VENUE
    ]
    auto_approved = awaiting_approval = errors = 0
    total = len(new_venues)
    for completed, venue in enumerate(new_venues):
        if progress is not None:
            progress((completed, total, venue.name))
        try:
            candidates = provider.discover(venue)
        except VenueDiscoveryError:
            errors += 1
            awaiting_approval += 1
            continue
        store.record_venue_candidates(candidates)
        selected = auto_approval_candidate(candidates, threshold=auto_approve_threshold)
        if selected is not None:
            store.select_venue_candidate(
                venue.id, selected.provider, selected.osm_type, selected.osm_id
            )
            auto_approved += 1
            continue
        if candidates:
            store.upsert_venue(
                venue.model_copy(update={"status": VenueStatus.CANDIDATE})
            )
        awaiting_approval += 1

    if progress is not None:
        progress((total, total, None))

    return VenueIngestionResult(
        created=catalog.created,
        linked=catalog.linked,
        unchanged=catalog.unchanged,
        auto_approved=auto_approved,
        awaiting_approval=awaiting_approval,
        errors=errors,
    )
