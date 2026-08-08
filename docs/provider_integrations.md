# Ticket provider integrations

## Ticketmaster Discovery pilot

The application has an opt-in `ticketmaster-discovery` event-details provider.
It calls the official Ticketmaster Discovery search endpoint only after an
operator supplies an API key in the process environment:

```bash
export BERLIN_EVENTS_TICKETMASTER_API_KEY="..."
berlin-events augment-event-details \
  --provider ticketmaster-discovery \
  --database events.sqlite \
  --limit 25 \
  --dry-run
```

The default provider remains `source-links`; it makes no Ticketmaster request.
A Ticketmaster run must be started with `--dry-run` and manually reviewed before
a non-dry-run persistence pass is approved.

### Matching and persistence rules

- The Discovery query is bounded to Berlin, Germany, and the source event's
  exact calendar day.
- The application stores an official Ticketmaster event/purchase URL only when
  exactly one candidate has an exact normalized title, date, and (when present
  in the source) venue match.
- Conflicting facts, missing source date, malformed provider data, or multiple
  candidates fail closed and produce no stored link.
- Only the provider ID, match rationale, official URL, and check timestamps are
  retained. Raw Discovery responses and API keys are not stored or printed.
- The provider does not access checkout, reserve tickets, sign in, or purchase.

### Availability is intentionally not enabled

The first pilot does not display a sold-out/availability claim. Ticketmaster's
inventory endpoints have separate access and contractual requirements. Do not
map a generic unavailable response to `sold_out`: it can mean off-sale, a
presale window, caching, or other non-sold-out conditions. Implement availability
only after an authorised API entitlement, displayed semantics, rate limit, and
retention rules have been confirmed.

### Operations gate

Before enabling writes for a production database, an authorised operator must:

1. register/approve the Ticketmaster API application and review its current
   terms and rate limits;
2. run a bounded `--dry-run` against a staging database;
3. manually adjudicate every proposed match, including similarly named and
   recurring events; and
4. approve a bounded non-dry-run invocation only if there are no false-positive
   candidates.

## Ingestion-time AI performer extraction

Set the following alongside the configured model credential to enable title-based
performer extraction **only for newly created events**:

```dotenv
BERLIN_EVENTS_PERFORMER_TITLE_AUGMENTATION=true
# Optional; otherwise BERLIN_EVENTS_EVENT_RESEARCH_MODEL is reused.
# BERLIN_EVENTS_TITLE_PERFORMER_MODEL=zai:glm-5-turbo
```

The source title is never changed. The model runs only when the title has a
list-like suffix after ` - ` and returns two or more names. Each accepted name
must occur verbatim in that suffix; `TBA`, aggregate labels such as `more`, and
festival/event names are rejected. The result replaces only the combined source
performer label, is recorded as `pydantic-ai-title-performers`, and is then
available to the normal artist catalog pipeline. Failures and uncertain results
leave source performers unchanged and do not fail source synchronization.

For existing events, the explicit helper remains available even if automatic
new-event augmentation is disabled. Start with a bounded dry run; event-date
bounds are inclusive and include multi-day events that overlap the interval:

```bash
berlin-events augment-performers \
  --database events.sqlite \
  --from-date 2026-08-01 \
  --to-date 2026-08-31 \
  --limit 25 \
  --dry-run
```

Remove `--dry-run` only after reviewing the summary. Successful records are
idempotent: events already enriched by this provider are skipped in later runs.

## SearXNG + Pydantic AI research pilot

The opt-in `searxng-pydantic-ai` provider searches a configured SearXNG JSON
endpoint and lets Pydantic AI select an event link, optional ticket link, and a
short research note from the bounded result metadata. It is independent of the
source-link and Ticketmaster overlays, so it cannot overwrite their data.

```bash
export BERLIN_EVENTS_SEARXNG_URL="http://127.0.0.1:8080"
export BERLIN_EVENTS_EVENT_RESEARCH_MODEL="zai:glm-5-turbo"
export ZAI_API_KEY="..."
berlin-events augment-event-details \
  --provider searxng-pydantic-ai \
  --database events.sqlite \
  --limit 10 \
  --dry-run
```

The `zai:` model prefix uses Z.AI's GLM Coding Plan OpenAI-compatible endpoint
(`https://api.z.ai/api/coding/paas/v4/`) and a `ZAI_API_KEY` from that plan.

SearXNG must expose its JSON search API (`/search?q=...&format=json`). The
SearXNG endpoint is an operator configuration and may be a private/local
service; all **rendered** URLs are separately checked to be public HTTP(S).

### Safety and rollout rules

- The batch does not fetch result pages. It supplies at most five title/URL/
  snippet records to the model.
- Search results are treated as untrusted data, not instructions. The agent has
  no browser, shell, or network tool access.
- A result is persisted only when `event_url` and `evidence_url` exactly match
  public URLs supplied by SearXNG. A ticket URL, when present, must match one
  too. URLs are revalidated before storage.
- The short note is escaped at render time and is labeled **AI-assisted
  research**, with an evidence link. It does not set status, availability,
  prices, times, performers, or cancellation claims.
- The provider refreshes only missing/stale research (seven days by default)
  and runs only when an operator invokes the CLI.
- Start with `--dry-run`, manually inspect every proposed link/evidence pair,
  then approve a small non-dry-run batch. Never put model or SearXNG credentials
  on a command line.


- **visitBerlin:** pursue a written data/API and licensing agreement before
  implementing an adapter. Do not scrape the public calendar.
- **Eventbrite:** its general location event-search endpoint is retired. A
  future adapter can resolve an existing Eventbrite URL/ID only after its API
  access, attribution, future-event storage, and direct-link requirements are
  accepted.
