.PHONY: default typecheck lint format tests test

default:
	@make -s help

help:
	@echo "Available targets:"
	@echo "  typecheck - Run type checking"
	@echo "  lint      - Run linting with auto-fix"
	@echo "  format    - Run code formatting"
	@echo "  tests     - Run all tests"
	@echo "  test      - Run tests matching a pattern (use: make test pattern=your_pattern)"

typecheck:
	uv run ty check --python=.venv/ src/berlin_events_explorer

lint:
	uv run ruff check src . --fix

format:
	uv run ruff format src .

tests:
	uv run pytest tests -s

test:
	uv run pytest tests -s -k $(pattern)
