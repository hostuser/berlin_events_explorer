"""Tests for password hashing, tokens, role guards, and identity loading."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.handlers import BaseRouteHandler

from berlin_events_explorer import auth
from berlin_events_explorer.models import UserRecord, UserRole

HANDLER = cast(BaseRouteHandler, None)


def _user(role: UserRole = UserRole.EDITOR, *, is_active: bool = True) -> UserRecord:
    """Return a representative account for guard and middleware checks."""

    now = datetime(2026, 8, 1, tzinfo=UTC)
    return UserRecord(
        id=1,
        email="markus@example.org",
        display_name="Markus",
        role=role,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _connection(user: UserRecord | None = None, *, with_user_key: bool = True):
    """Return a connection stub carrying only what guards read."""

    scope = {"user": user} if with_user_key else {}
    return SimpleNamespace(scope=scope)


def test_password_hash_roundtrip() -> None:
    """A stored hash verifies its own password and rejects any other."""

    hashed = auth.hash_password("correct horse battery")

    assert auth.verify_password(hashed, "correct horse battery") is True
    assert auth.verify_password(hashed, "wrong password") is False


def test_verify_password_rejects_garbage_hashes() -> None:
    """Corrupt credential rows must fail login, not crash it."""

    assert auth.verify_password("not-a-hash", "anything") is False
    assert auth.verify_password("", "anything") is False


def test_hash_password_uses_argon2id() -> None:
    """The production hasher must emit Argon2id hashes."""

    assert auth.hash_password("s3cret-enough").startswith("$argon2id$")


def test_generate_token_pairs_raw_secret_with_sha256_hash() -> None:
    """Only the hash is stored; it must deterministically match the raw token."""

    raw, hashed = auth.generate_token()
    other_raw, other_hashed = auth.generate_token()

    assert auth.hash_token(raw) == hashed
    assert len(hashed) == 64
    int(hashed, 16)
    assert raw != other_raw
    assert hashed != other_hashed


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.EDITOR, UserRole.ADMIN])
def test_requires_user_admits_every_role(role: UserRole) -> None:
    """Any authenticated account may use logged-in-only pages."""

    auth.requires_user(_connection(_user(role)), HANDLER)


def test_guards_reject_anonymous_connections() -> None:
    """Missing identity means login is required, whether the key exists or not."""

    for guard in (auth.requires_user, auth.requires_editor, auth.requires_admin):
        with pytest.raises(NotAuthorizedException):
            guard(_connection(None), HANDLER)
        with pytest.raises(NotAuthorizedException):
            guard(_connection(with_user_key=False), HANDLER)


def test_role_hierarchy_is_enforced() -> None:
    """Editors clear editor gates, admins clear all, users clear neither."""

    auth.requires_editor(_connection(_user(UserRole.EDITOR)), HANDLER)
    auth.requires_editor(_connection(_user(UserRole.ADMIN)), HANDLER)
    auth.requires_admin(_connection(_user(UserRole.ADMIN)), HANDLER)

    with pytest.raises(PermissionDeniedException):
        auth.requires_editor(_connection(_user(UserRole.USER)), HANDLER)
    with pytest.raises(PermissionDeniedException):
        auth.requires_admin(_connection(_user(UserRole.USER)), HANDLER)
    with pytest.raises(PermissionDeniedException):
        auth.requires_admin(_connection(_user(UserRole.EDITOR)), HANDLER)


def _middleware_connection(session: object, load_user):
    """Return a connection stub carrying a session and a user loader."""

    return SimpleNamespace(
        scope={"session": session},
        app=SimpleNamespace(state=SimpleNamespace(load_user=load_user)),
    )


async def _noop_asgi(scope, receive, send) -> None:
    raise AssertionError("the wrapped app must not be called by these tests")


@pytest.mark.anyio
async def test_middleware_loads_the_active_session_user(anyio_backend) -> None:
    """A session naming an active account authenticates the request."""

    user = _user()
    middleware = auth.SessionUserAuthMiddleware(app=_noop_asgi)
    connection = _middleware_connection(
        {auth.SESSION_USER_KEY: 1}, lambda user_id: user if user_id == 1 else None
    )

    result = await middleware.authenticate_request(connection)

    assert result.user == user


@pytest.mark.anyio
async def test_middleware_treats_missing_or_bogus_sessions_as_anonymous(
    anyio_backend,
) -> None:
    """No session, foreign values, or unknown IDs must all yield user=None."""

    middleware = auth.SessionUserAuthMiddleware(app=_noop_asgi)

    def _fail_loader(user_id: int) -> None:
        raise AssertionError("the loader must not run without a valid user id")

    for session in ({}, {auth.SESSION_USER_KEY: "1"}, {auth.SESSION_USER_KEY: None}):
        result = await middleware.authenticate_request(
            _middleware_connection(session, _fail_loader)
        )
        assert result.user is None

    result = await middleware.authenticate_request(
        _middleware_connection({auth.SESSION_USER_KEY: 42}, lambda user_id: None)
    )
    assert result.user is None


@pytest.mark.anyio
async def test_middleware_treats_deactivated_users_as_anonymous(anyio_backend) -> None:
    """Deactivation must lock an account out on its very next request."""

    middleware = auth.SessionUserAuthMiddleware(app=_noop_asgi)
    connection = _middleware_connection(
        {auth.SESSION_USER_KEY: 1}, lambda user_id: _user(is_active=False)
    )

    result = await middleware.authenticate_request(connection)

    assert result.user is None
