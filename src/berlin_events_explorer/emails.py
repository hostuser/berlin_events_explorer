"""Outgoing email configuration and the account-lifecycle messages.

Backends are selected through the environment so one binary serves every
deployment: ``console`` (default) for development, ``memory`` for tests, and
``smtp`` for production relays such as Scaleway TEM or Postmark.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from litestar_email import EmailConfig, EmailMessage, SMTPConfig

if TYPE_CHECKING:
    from datetime import datetime

    from berlin_events_explorer.models import UserRole

EMAIL_BACKEND_ENV_VAR = "BERLIN_EVENTS_EMAIL_BACKEND"
_KNOWN_BACKENDS = {"console", "memory", "smtp"}
_TLS_MODES = {"starttls", "ssl", "none"}


def email_config_from_env() -> EmailConfig:
    """Build the sending configuration from environment variables."""

    backend_name = os.environ.get(EMAIL_BACKEND_ENV_VAR, "console").strip().lower()
    if backend_name not in _KNOWN_BACKENDS:
        raise ValueError(
            f"Unsupported email backend {backend_name!r}; "
            f"expected one of {sorted(_KNOWN_BACKENDS)}"
        )
    backend: str | SMTPConfig = backend_name
    if backend_name == "smtp":
        tls_mode = os.environ.get("BERLIN_EVENTS_SMTP_TLS", "starttls").strip().lower()
        if tls_mode not in _TLS_MODES:
            raise ValueError(
                f"Unsupported SMTP TLS mode {tls_mode!r}; "
                f"expected one of {sorted(_TLS_MODES)}"
            )
        backend = SMTPConfig(
            host=os.environ.get("BERLIN_EVENTS_SMTP_HOST", "localhost"),
            port=int(os.environ.get("BERLIN_EVENTS_SMTP_PORT", "587")),
            username=os.environ.get("BERLIN_EVENTS_SMTP_USERNAME") or None,
            password=os.environ.get("BERLIN_EVENTS_SMTP_PASSWORD") or None,
            use_tls=tls_mode == "starttls",
            use_ssl=tls_mode == "ssl",
        )
    return EmailConfig(
        backend=backend,
        from_email=os.environ.get("BERLIN_EVENTS_EMAIL_FROM", "noreply@localhost"),
        from_name=os.environ.get(
            "BERLIN_EVENTS_EMAIL_FROM_NAME", "Berlin Events Explorer"
        ),
    )


async def send_invite_email(
    config: EmailConfig,
    *,
    to: str,
    invite_url: str,
    role: UserRole,
    expires_at: datetime,
) -> None:
    """Send one invite link to a future account holder."""

    body = (
        "Hello,\n"
        "\n"
        "you have been invited to Berlin Events Explorer with the "
        f"{role.value} role.\n"
        "\n"
        "Open this link to choose your password and activate the account:\n"
        "\n"
        f"    {invite_url}\n"
        "\n"
        f"The link can be used once and expires on {expires_at.date().isoformat()}.\n"
    )
    message = EmailMessage(
        subject="Your Berlin Events Explorer invitation",
        body=body,
        to=[to],
    )
    async with config.provide_service() as mailer:
        await mailer.send_message(message)


async def send_password_reset_email(
    config: EmailConfig,
    *,
    to: str,
    reset_url: str,
    expires_at: datetime,
) -> None:
    """Send one password-reset link to an account's address."""

    body = (
        "Hello,\n"
        "\n"
        "a password reset was requested for your Berlin Events Explorer "
        "account.\n"
        "\n"
        "Open this link to choose a new password:\n"
        "\n"
        f"    {reset_url}\n"
        "\n"
        f"The link can be used once and expires at "
        f"{expires_at.strftime('%Y-%m-%d %H:%M %Z')}.\n"
        "\n"
        "If you did not request this, you can ignore this email; your "
        "password is unchanged.\n"
    )
    message = EmailMessage(
        subject="Reset your Berlin Events Explorer password",
        body=body,
        to=[to],
    )
    async with config.provide_service() as mailer:
        await mailer.send_message(message)
