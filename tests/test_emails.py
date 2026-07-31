"""Tests for email backend selection and account-lifecycle messages."""

from datetime import UTC, datetime

import pytest
from litestar_email import SMTPConfig
from litestar_email.backends import InMemoryBackend

from berlin_events_explorer.emails import (
    email_config_from_env,
    send_invite_email,
    send_password_reset_email,
)
from berlin_events_explorer.models import UserRole


def test_console_backend_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Development needs no email configuration at all."""

    monkeypatch.delenv("BERLIN_EVENTS_EMAIL_BACKEND", raising=False)

    config = email_config_from_env()

    assert config.backend == "console"
    assert config.from_email == "noreply@localhost"


def test_memory_backend_is_selected_from_env() -> None:
    """The test suite runs against the in-memory outbox."""

    assert email_config_from_env().backend == "memory"


def test_unknown_backends_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in the backend name must fail loudly, not fall back silently."""

    monkeypatch.setenv("BERLIN_EVENTS_EMAIL_BACKEND", "carrier-pigeon")

    with pytest.raises(ValueError, match="carrier-pigeon"):
        email_config_from_env()


@pytest.mark.parametrize(
    ("tls_mode", "use_tls", "use_ssl"),
    [("starttls", True, False), ("ssl", False, True), ("none", False, False)],
)
def test_smtp_backend_reads_connection_settings_from_env(
    monkeypatch: pytest.MonkeyPatch, tls_mode: str, use_tls: bool, use_ssl: bool
) -> None:
    """SMTP credentials and TLS mode come from the environment."""

    monkeypatch.setenv("BERLIN_EVENTS_EMAIL_BACKEND", "smtp")
    monkeypatch.setenv("BERLIN_EVENTS_SMTP_HOST", "smtp.example.org")
    monkeypatch.setenv("BERLIN_EVENTS_SMTP_PORT", "2525")
    monkeypatch.setenv("BERLIN_EVENTS_SMTP_USERNAME", "mailer")
    monkeypatch.setenv("BERLIN_EVENTS_SMTP_PASSWORD", "mailer-secret")
    monkeypatch.setenv("BERLIN_EVENTS_SMTP_TLS", tls_mode)
    monkeypatch.setenv("BERLIN_EVENTS_EMAIL_FROM", "events@example.org")

    config = email_config_from_env()

    backend = config.backend
    assert isinstance(backend, SMTPConfig)
    assert backend.host == "smtp.example.org"
    assert backend.port == 2525
    assert backend.username == "mailer"
    assert backend.password == "mailer-secret"
    assert backend.use_tls is use_tls
    assert backend.use_ssl is use_ssl
    assert config.from_email == "events@example.org"


def test_invalid_tls_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BERLIN_EVENTS_EMAIL_BACKEND", "smtp")
    monkeypatch.setenv("BERLIN_EVENTS_SMTP_TLS", "implicit")

    with pytest.raises(ValueError, match="implicit"):
        email_config_from_env()


@pytest.mark.anyio
async def test_invite_email_carries_the_link_and_role(anyio_backend) -> None:
    config = email_config_from_env()

    await send_invite_email(
        config,
        to="invitee@example.org",
        invite_url="https://events.example.org/invites/raw-token",
        role=UserRole.EDITOR,
        expires_at=datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
    )

    assert len(InMemoryBackend.outbox) == 1
    message = InMemoryBackend.outbox[0]
    assert message.to == ["invitee@example.org"]
    assert "https://events.example.org/invites/raw-token" in message.body
    assert "editor" in message.body
    assert "2026-08-08" in message.body


@pytest.mark.anyio
async def test_password_reset_email_carries_the_link(anyio_backend) -> None:
    config = email_config_from_env()

    await send_password_reset_email(
        config,
        to="markus@example.org",
        reset_url="https://events.example.org/password-reset/raw-token",
        expires_at=datetime(2026, 8, 1, 14, 0, tzinfo=UTC),
    )

    assert len(InMemoryBackend.outbox) == 1
    message = InMemoryBackend.outbox[0]
    assert message.to == ["markus@example.org"]
    assert "https://events.example.org/password-reset/raw-token" in message.body
    assert "ignore this email" in message.body
