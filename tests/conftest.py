"""Pytest configuration and shared fixtures for Berlin Events Explorer tests."""

from collections.abc import Iterator

import pytest
from argon2 import PasswordHasher
from litestar.testing import TestClient
from litestar_email.backends import InMemoryBackend

from berlin_events_explorer import auth
from berlin_events_explorer.models import UserRecord, UserRole
from berlin_events_explorer.storage import EventStore

TEST_PASSWORD = "test-password-123"
TEST_SECRET_KEY = "test-csrf-secret-key"


@pytest.fixture(autouse=True)
def _secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test app the CSRF secret production would require."""

    monkeypatch.setenv("BERLIN_EVENTS_SECRET_KEY", TEST_SECRET_KEY)


@pytest.fixture(autouse=True)
def _cheap_password_hasher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap in minimal Argon2 parameters; production cost would add ~100ms per login."""

    monkeypatch.setattr(
        auth,
        "PASSWORD_HASHER",
        PasswordHasher(time_cost=1, memory_cost=8, parallelism=1),
    )


@pytest.fixture(autouse=True)
def _memory_email_outbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Capture outgoing mail in memory and isolate the shared outbox per test."""

    monkeypatch.setenv("BERLIN_EVENTS_EMAIL_BACKEND", "memory")
    InMemoryBackend.clear()
    yield
    InMemoryBackend.clear()


def seed_user(
    store: EventStore,
    *,
    email: str,
    role: UserRole,
    password: str = TEST_PASSWORD,
    display_name: str | None = None,
) -> UserRecord:
    """Create an account directly in the store, reusing it if already seeded."""

    credentials = store.get_user_credentials(email)
    if credentials is not None:
        return credentials.user
    return store.create_user(
        email=email,
        password_hash=auth.hash_password(password),
        display_name=display_name or email.split("@")[0].title(),
        role=role,
    )


def login_as(
    client: TestClient,
    *,
    role: str = "editor",
    email: str | None = None,
    password: str = TEST_PASSWORD,
) -> UserRecord:
    """Seed an account of the given role on the client's app and log it in."""

    role_value = UserRole(role)
    email = email or f"{role_value.value}@example.test"
    user = seed_user(client.app.state.store, email=email, role=role_value)
    client.get("/login")
    token = client.cookies.get("csrftoken")
    headers = {"x-csrftoken": token} if token else {}
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return user


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests against asyncio only."""

    return "asyncio"


@pytest.fixture
def sample_fixture():
    """Example fixture that can be used across test modules."""
    return {"key": "value", "project": "Berlin Events Explorer"}
