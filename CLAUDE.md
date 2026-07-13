# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

- project_name: `Berlin Events Explorer`
- project_description: Parse and explore Berlin music events with enriched venue and performer metadata.
- python base module: `berlin_events_explorer`
- documentation: `docs` folder

## Development Commands

This project uses `uv` for dependency management and `just` as a task runner.

### Using just (preferred)
- `just tests` - Run all unit tests
- `just test <pattern>` - Run tests matching a pattern (e.g., `just test test_example`)
- `just typecheck` - Run type checker (ty)
- `just lint` - Run ruff linter with auto-fix
- `just format` - Run ruff formatter

### Using uv directly
- `uv run pytest tests -s` - Run all tests
- `uv run pytest tests -s -k <pattern>` - Run tests matching pattern
- `uv run ty check --python=.venv/ src/berlin_events_explorer` - Type check
- `uv run ruff check src . --fix` - Lint with auto-fix
- `uv run ruff format src .` - Format code

## Code Architecture

This package is created from a template project. In case you need to modify something in the generic project setup that would benefit other projects, let me know instead of changing
things in here.

### Package Structure
- Source code: `src/berlin_events_explorer/` (namespace package)
- Tests: `tests/`

### Code Style
- Formatter: ruff (black-compatible, line-length 88)
- Linter: ruff
- Type checker: ty
- Docstring convention: Google style

### Debug Utilities
The package `__init__.py` sets up several debug helpers as builtins when dev dependencies are installed:
- `dbg()` - Rich print for debugging
- `DBG()` - devtools debug
- `ic()` - icecream debugger
- `wat` / `wats` - wat inspection tool
- `insp()` - Rich inspect
- `snoop` - Function tracer (auto-installed)

## Test Markers
Tests can be marked with: `slow`, `integration`, `unit`
Example: `uv run pytest tests -m "not slow"`
