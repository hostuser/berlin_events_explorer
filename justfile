default:
    @just --list

typecheck:
    uv run ty check

lint:
    uv run ruff check . --fix

format:
    uv run ruff format .

pre-commit:
    uv run pre-commit run --all-files

tests:
    uv run pytest tests -s

test pattern:
    uv run pytest tests -s -k 

update-template:
    uvx --with copier-template-extensions copier update --trust -T -A
