[![PyPI status](https://img.shields.io/pypi/status/berlin_events_explorer.svg)](https://pypi.python.org/pypi/berlin_events_explorer/)
[![PyPI version](https://img.shields.io/pypi/v/berlin_events_explorer.svg)](https://pypi.python.org/pypi/berlin_events_explorer/)
[![PyPI pyversions](https://img.shields.io/pypi/pyversions/berlin_events_explorer.svg)](https://pypi.python.org/pypi/berlin_events_explorer/)
[![Build Status](https://img.shields.io/endpoint.svg?url=https%3A%2F%2Factions-badge.atrox.dev%2Fhostuser%berlin_events_explorer%2Fbadge%3Fref%3Ddevelop&style=flat)](https://actions-badge.atrox.dev/hostuser/berlin_events_explorer/goto?ref=develop)
[![Coverage Status](https://coveralls.io/repos/github/hostuser/berlin_events_explorer/badge.svg?branch=develop)](https://coveralls.io/github/hostuser/berlin_events_explorer?branch=develop)
[![Code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)

# Berlin Events Explorer

Parse and explore Berlin music events with enriched venue and performer metadata.

 - Documentation: [https://hostuser.github.io/berlin_events_explorer](https://hostuser.github.io/berlin_events_explorer)
 - Code: [https://github.com/hostuser/berlin_events_explorer](https://github.com/hostuser/berlin_events_explorer)

## Description

TODO

## Development

### Requirements

- uv ( https://docs.astral.sh/uv/ )
- git
- make (on Linux / Mac OS X -- optional)
- just (optional)

### Check out the source code & enter the project directory

```
git clone https://github.com/hostuser/berlin_events_explorer
cd berlin_events_explorer
```

### Running pre-defined development-related tasks (using `just`)

The included `Makefile` file includes some useful tasks that help with development. This requires `uv` and the `make` tool to be
installed, which should be the case for Linux & Mac OS X systems.

- `just tests`: runs all unit tests
- `just test <pattern>`: runs all unit tests whose name matches the given pattern
- `just typecheck`: run type-checker
- `just lint`: run the `ruff` linter on the source code
- `just format`: run the `ruff` formatter on the source code (similar to `black`)

Alternatively, if you don't have the `just` command available, you can use `uv` directly to run those tasks:

- `uv run pytest tests`
- `uv run mypy src/`
- `uv run ruff check --fix src/`
- `uv run ruff format src/`

## Copyright & license

Copyright (c) 2026 - Markus Binsteiner


This project is published under the MIT license, for the license text please check the [LICENSE](/LICENSE) file in this repository.

