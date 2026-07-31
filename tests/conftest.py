"""Pytest configuration and shared fixtures for Berlin Events Explorer tests."""

import pytest

TEST_EDITOR_PASSWORD = "test-editor-password"


@pytest.fixture(autouse=True)
def _editor_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test app a known editor password."""

    monkeypatch.setenv("BERLIN_EVENTS_EDITOR_PASSWORD", TEST_EDITOR_PASSWORD)


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests against asyncio only."""

    return "asyncio"


@pytest.fixture
def sample_fixture():
    """Example fixture that can be used across test modules."""
    return {"key": "value", "project": "Berlin Events Explorer"}
