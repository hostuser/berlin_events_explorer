# Initial project brief

> **Status: historical input.** This file preserves the questions and early
> pipeline sketch that initiated evts. It is not an implementation
> specification. The normative, self-contained project documents are indexed in
> [README.md](README.md).

The current project 'berlin_events_explorer' is the prototype for a larger, more
generic I'm planning to build. I used it to learn lessions, get an idea what's
possible, etc. I want us to come up with a plan and specs for this project,
'evts'. We'll put all the docs and specs we create in the 'evts' folder, which
will then be used as starting point for the project. So, for example, when we
come up with a ui-design-guide, we'd put that under evts/docs, but also create a
skill under evts/.agents/skills and evts/.claude/skills. That folder should
contain everything needed for developers and/or AI agents to understand the
project, it's specs, and everything around it. There will still be room for new
details and changes, but I want a good, well-designed, well-speced, concise, and
easy to understand starting point with the data schema as well fleshed out as
possible. One thing that is out of scope: decisions which technologies
(programming languages, libraries, databases, etc.) to use. We'll decide that
once all the requirements are in place.

So, the project: a web page that contains event listings for one or multiple
cities/regions.

The events are sourced from one or multiple sources, each of
which get their own 'source plugin' which can live in the main application
repository, or be added dynamically at runtime, either via configuration or
admin UI (cli and web). The main problem, as often, is dirty data. We need
to deduplicate events, venues, and performers. And we need to match
instances to their real-life counterparts, which is sometimes easy, sometimes
hard, and always error-prone. So we'll need a review system that logs
decisions and lets us change or improve those retrospectively.

I am not 100% sure what the best design for a data pipeline for this
use-case is, so here is my current thinking, feel free to comment on it, or
suggest something completely different:

- source gets parsed, events are extracted and compared to exsiting ones
- existing events are marked as 'to-update', new ones are added
- details for new events are stored in a source-native way (mainly so we can
  compare whether something has changed), and the entry gets a hash
- event is parsed into a shared, generic event data structure that contains:
  - start-date (string or date type)
  - end-date (string or date type, optional, for multi-day events,
    NULL means
    single day)
  - start-time (string or time type, optional)
  - end-time (string or time type, optional)
  - title (string)
  - venue (as string)
  - city (as string)
  - country (as string)
  - a list of performer strings (best effort in identifying what is a
    performer as well as splitting them up)
  - whether the event was encountered in this source before (boolean, best
    effort)
- we have 'parse' plugins for every possible attribute, each of them is
  run against the value in question and returns a 'cleaned' up value along
  with a confidence score, the best confidence store wins. metadata about
  which 'parser' was used along with the source and target values are
  stored in our database
  - parsers for venue, city, country, and performers would return either
    a reference to an existing database entity, or the raw data to create a
    new one
- an event instance is assembled from all the best rated attributes,
  along with the source plugin type and import date (maybe we also have
  tiebreaker parser ratings/priorities -- or a combination of parser
  priority and confidence score?)
  - it should be possible to manually override a parse decision
    retroactively, which would change the event instance and re-run the
    following steps, to make that easier, we also store all parse results so
    the user can decide to either pick one of those, or manually enter a
    parse result
- we check if the event already exists in our database, if it does, we
  compare the new event with the existing one and update the existing one
  with the new data if it is deemed better
- newly created venues, cities, countries and performers get fed into a
  type-specific 'augmenter' pipeline, where we have plugins again that all
  get run against the value in question (along with the event context that
  can optionally be used by the augmenter plugins), similar to above, best
  confidence score (or plugin priority/score combination) wins, and that new
  instance is stored into the database (and linked to the event)
  - again, it should be possible to override this, and again we store all
    augmenter results
- we will have detail pages for all events, venues, performers, but what
  information they contain and how they are layed out is TBD
- the page should be usable without login, but provide extra functionality
  when logged in, like event notifications etc. Details about those is also TBD
- we'll have an admin role that is allowed to do administrative tasks, as
  well as editors that can override decision, or edit database instances, etc.
