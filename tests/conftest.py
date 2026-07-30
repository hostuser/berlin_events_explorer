"""Pytest configuration and shared fixtures for Berlin Events Explorer tests."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests against asyncio only."""

    return "asyncio"


@pytest.fixture
def sample_fixture():
    """Example fixture that can be used across test modules."""
    return {"key": "value", "project": "Berlin Events Explorer"}
