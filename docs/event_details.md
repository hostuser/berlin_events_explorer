# Event detail pages and augmentation

Event pages use the stable source event ID at `/events/{event_id}`. They render
source-authoritative date, title, performers, venue, notes, and status, plus any
independently observed public links.

## Data trust model

Observed event details are stored in `event_details`, outside `events.event_json`.
A normal source sync therefore cannot erase an already verified event or ticket
link. Every overlay includes provider, evidence URL, confidence, check time, and
optional status expiry.

- Only public `http`/`https` URLs without credentials or local/private hosts are
  accepted.
- A non-unknown source status always wins over an augmented status.
- Expired augmented status is not treated as current.
- The application never purchases, reserves, signs in to, or otherwise interacts
  with ticket checkout flows.

## Ticketmaster Discovery pilot

The opt-in `ticketmaster-discovery` provider is now available for a manually
reviewed link-enrichment pilot. It requires an authorised Ticketmaster API key
in `BERLIN_EVENTS_TICKETMASTER_API_KEY` and is never invoked by default:

```bash
berlin-events augment-event-details \
  --provider ticketmaster-discovery \
  --database events.sqlite \
  --limit 25 \
  --dry-run
```

The provider only saves a Ticketmaster URL when exactly one candidate has an
exact normalized title/date/venue match. Review dry-run output before any
non-dry-run invocation. It does not yet fetch or render live availability; see
[`provider_integrations.md`](provider_integrations.md) for the required
operational approval and the provider-specific rules.

## Current source-links augmenter

```bash
berlin-events augment-event-details --database events.sqlite --limit 100
```

The default `source-links` augmenter is deliberately conservative: it records
only the source event page already present in canonical provenance. It **does
not** guess a ticket URL, event page, sold-out state, or cancellation. It
processes only missing or stale records (seven-day refresh window), bounded by
`--limit`.
