"""Password hashing, single-use tokens, identity loading, and role guards.

This module has no imports from the web or storage layers: the middleware
receives its user loader through ``app.state``, so everything here is unit
testable with plain stubs.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.middleware.authentication import (
    AbstractAuthenticationMiddleware,
    AuthenticationResult,
)

from berlin_events_explorer.models import UserRole

if TYPE_CHECKING:
    from litestar.connection import ASGIConnection
    from litestar.handlers import BaseRouteHandler
    from litestar.types import Guard

SESSION_USER_KEY = "user_id"
INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=2)
ROLE_ORDER: dict[UserRole, int] = {
    UserRole.USER: 0,
    UserRole.EDITOR: 1,
    UserRole.ADMIN: 2,
}

# Module-level so tests can swap in a cheap hasher; call sites must read this
# attribute at call time rather than capturing it.
PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an Argon2id hash suitable for the users table."""

    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Check a password against a stored hash, treating corrupt rows as no."""

    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except InvalidHashError, VerificationError:
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """A hash of a random secret, verified for unknown logins.

    Running a real verification even when no account matches keeps the
    response time of ``POST /login`` independent of address existence.
    """

    return PASSWORD_HASHER.hash(secrets.token_hex(16))


def hash_token(raw: str) -> str:
    """Return the hex SHA-256 digest under which a token is stored."""

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str]:
    """Return a fresh single-use token as ``(raw secret, stored hash)``."""

    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


class SessionUserAuthMiddleware(AbstractAuthenticationMiddleware):
    """Resolve the session's account onto ``connection.user`` once per request.

    Anonymous, unknown, and deactivated sessions all proceed with
    ``user=None`` — authorization is entirely the guards' job, because most
    of the site is public.
    """

    async def authenticate_request(
        self, connection: ASGIConnection
    ) -> AuthenticationResult:
        session = connection.scope.get("session")
        user_id = session.get(SESSION_USER_KEY) if isinstance(session, dict) else None
        if not isinstance(user_id, int) or isinstance(user_id, bool):
            return AuthenticationResult(user=None, auth=None)
        load_user = connection.app.state.load_user
        user = await to_thread.run_sync(load_user, user_id)
        if user is None or not user.is_active:
            return AuthenticationResult(user=None, auth=None)
        return AuthenticationResult(user=user, auth=None)


def require_role(minimum: UserRole) -> Guard:
    """Build a guard admitting only accounts at or above one role tier."""

    def guard(connection: ASGIConnection, _: BaseRouteHandler) -> None:
        # scope.get, not connection.user: the latter raises where the auth
        # middleware is excluded.
        user = connection.scope.get("user")
        if user is None:
            raise NotAuthorizedException("Login required.")
        if ROLE_ORDER[user.role] < ROLE_ORDER[minimum]:
            raise PermissionDeniedException("Insufficient permissions.")

    return guard


requires_user = require_role(UserRole.USER)
requires_editor = require_role(UserRole.EDITOR)
requires_admin = require_role(UserRole.ADMIN)
