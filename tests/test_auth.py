"""Tests for account login, sessions, and role authorization on the web UI."""

from pathlib import Path

import pytest
from litestar.testing import TestClient

from berlin_events_explorer.models import UserRole
from berlin_events_explorer.webapp import create_app

from conftest import TEST_PASSWORD, login_as, seed_user


def _app(tmp_path: Path, **kwargs):
    kwargs.setdefault("sync_interval", None)
    return create_app(tmp_path / "events.sqlite", **kwargs)


def _csrf_headers(client: TestClient) -> dict[str, str]:
    """Return the double-submit CSRF header for the client's current cookie."""

    token = client.cookies.get("csrftoken")
    return {"x-csrftoken": token} if token else {}


def _login_post(client: TestClient, email: str, password: str):
    """Submit the login form without asserting the outcome."""

    client.get("/login")
    return client.post(
        "/login",
        data={"email": email, "password": password},
        headers=_csrf_headers(client),
        follow_redirects=False,
    )


def test_public_routes_stay_open_without_login(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 200


def test_guarded_get_redirects_to_login(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        for path in ("/settings", "/approvals/venues/some-venue"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 303, path
            assert response.headers["location"].startswith("/login"), path


def test_approvals_tab_redirects_to_login(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/?tab=approvals", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")


def test_guarded_post_without_login_returns_401(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.get("/")
        headers = _csrf_headers(client)
        for path in (
            "/settings",
            "/sync",
            "/approvals/venues/some-venue",
            "/approvals/artists/some-artist",
            "/approvals/venues/some-venue/discover",
            "/approvals/artists/some-artist/discover",
            "/settings/clear-database",
        ):
            response = client.post(path, headers=headers, follow_redirects=False)
            assert response.status_code == 401, path


def test_post_without_csrf_token_is_rejected(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="admin")
        response = client.post(
            "/settings",
            data={"auto_approve_threshold": "0.5"},
            follow_redirects=False,
        )
        assert response.status_code == 403


def test_forms_embed_csrf_token(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        assert 'name="_csrf_token"' in client.get("/login").text
        login_as(client, role="admin")
        assert 'name="_csrf_token"' in client.get("/settings").text


def test_settings_form_roundtrip_with_csrf_field(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="admin")
        token = client.cookies.get("csrftoken")
        assert token
        response = client.post(
            "/settings",
            data={"auto_approve_threshold": "0.5", "_csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 303


def test_login_with_correct_password_grants_access(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        user = login_as(client, role="admin")
        assert client.get("/settings").status_code == 200
        refreshed = client.app.state.store.get_user(user.id)
        assert refreshed is not None
        assert refreshed.last_login_at is not None


@pytest.mark.parametrize(
    ("next_target", "expected_location"),
    [
        ("/?tab=approvals", "/?tab=approvals"),
        ("https://evil.example/", "/"),
        ("//evil.example/", "/"),
    ],
)
def test_login_redirects_only_to_same_site_targets(
    tmp_path: Path, next_target: str, expected_location: str
) -> None:
    with TestClient(_app(tmp_path)) as client:
        seed_user(client.app.state.store, email="e@example.test", role=UserRole.EDITOR)
        client.get("/login")
        response = client.post(
            "/login",
            data={
                "email": "e@example.test",
                "password": TEST_PASSWORD,
                "next": next_target,
            },
            headers=_csrf_headers(client),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == expected_location


def test_login_rejections_do_not_reveal_which_field_was_wrong(
    tmp_path: Path,
) -> None:
    """Unknown addresses and wrong passwords must be indistinguishable."""

    with TestClient(_app(tmp_path)) as client:
        seed_user(client.app.state.store, email="e@example.test", role=UserRole.EDITOR)

        wrong_password = _login_post(client, "e@example.test", "wrong-password")
        unknown_email = _login_post(client, "nobody@example.test", "wrong-password")

        assert wrong_password.status_code == 400
        assert unknown_email.status_code == 400
        assert "Invalid email or password." in wrong_password.text
        assert "Invalid email or password." in unknown_email.text
        assert client.get("/settings", follow_redirects=False).status_code == 303


def test_deactivated_accounts_cannot_log_in(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        store = client.app.state.store
        user = seed_user(store, email="e@example.test", role=UserRole.EDITOR)
        store.update_user(user.id, is_active=False)

        response = _login_post(client, "e@example.test", TEST_PASSWORD)

        assert response.status_code == 400
        assert "Invalid email or password." in response.text


def test_deactivation_locks_out_an_existing_session(tmp_path: Path) -> None:
    """Role and account changes must not wait for the session to expire."""

    with TestClient(_app(tmp_path)) as client:
        user = login_as(client, role="editor")
        assert client.get("/approvals/venues/x").status_code == 404

        client.app.state.store.update_user(user.id, is_active=False)

        response = client.get("/approvals/venues/x", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")


def test_role_hierarchy_governs_route_access(tmp_path: Path) -> None:
    """Editors clear editorial routes but not admin ones; users clear neither."""

    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="user")
        assert client.get("/approvals/venues/x").status_code == 403
        assert client.get("/settings").status_code == 403

    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="editor")
        assert client.get("/approvals/venues/x").status_code == 404
        assert client.get("/settings").status_code == 403

    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="admin")
        assert client.get("/settings").status_code == 200


def test_promotion_applies_on_the_next_request(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        user = login_as(client, role="user")
        assert client.get("/settings").status_code == 403

        client.app.state.store.update_user(user.id, role=UserRole.ADMIN)

        assert client.get("/settings").status_code == 200


def test_login_page_renders(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/login")
        assert response.status_code == 200
        assert 'name="email"' in response.text
        assert 'name="password"' in response.text


def test_logout_clears_the_session(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="admin")
        assert client.get("/settings").status_code == 200
        response = client.post(
            "/logout", headers=_csrf_headers(client), follow_redirects=False
        )
        assert response.status_code == 303
        assert client.get("/settings", follow_redirects=False).status_code == 303


def test_sessions_survive_an_app_restart(tmp_path: Path) -> None:
    """The session store must persist on disk, unlike the old MemoryStore."""

    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="admin")
        assert client.get("/settings").status_code == 200
        cookies = dict(client.cookies)

    with TestClient(_app(tmp_path)) as client:
        for name, value in cookies.items():
            client.cookies.set(name, value)
        assert client.get("/settings").status_code == 200


def test_shell_shows_account_state(tmp_path: Path) -> None:
    """Anonymous visitors see a login link; accounts see their name and logout."""

    with TestClient(_app(tmp_path)) as client:
        anonymous = client.get("/").text
        assert 'href="/login"' in anonymous
        assert "Awaiting approval" not in anonymous

        login_as(client, role="editor", email="markus@example.test")
        signed_in = client.get("/").text
        assert "Markus" in signed_in
        assert 'action="/logout"' in signed_in
        assert "Awaiting approval" in signed_in


def test_production_requires_a_configured_secret_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without BERLIN_EVENTS_SECRET_KEY the production app must not start."""

    monkeypatch.delenv("BERLIN_EVENTS_SECRET_KEY", raising=False)

    with pytest.raises(ValueError, match="BERLIN_EVENTS_SECRET_KEY"):
        _app(tmp_path, environment="production")

    assert _app(tmp_path, environment="development") is not None


def _create_invite(
    client: TestClient, *, email: str = "invitee@example.test", role: str = "user"
):
    """Submit the admin invite form for an already logged-in client."""

    return client.post(
        "/admin/invites",
        data={"email": email, "role": role},
        headers=_csrf_headers(client),
        follow_redirects=False,
    )


def _invite_url_from_outbox() -> str:
    """Extract the invite path from the most recent captured email."""

    import re

    from litestar_email.backends import InMemoryBackend

    assert InMemoryBackend.outbox, "expected an invite email in the outbox"
    match = re.search(r"/invites/[A-Za-z0-9_-]+", InMemoryBackend.outbox[-1].body)
    assert match, InMemoryBackend.outbox[-1].body
    return match.group(0)


def test_admin_invite_shows_copyable_url_and_sends_email(tmp_path: Path) -> None:
    """The invite URL exists only in this response, so it must be visible."""

    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="admin")
        response = _create_invite(client, email="invitee@example.test", role="editor")

        assert response.status_code == 200
        invite_path = _invite_url_from_outbox()
        assert invite_path in response.text
        assert "invitee@example.test" in response.text


def test_invite_email_failure_still_yields_the_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken mail relay must never lose a freshly created invite."""

    from litestar_email import EmailDeliveryError

    from berlin_events_explorer import webapp

    async def _fail(*args: object, **kwargs: object) -> None:
        raise EmailDeliveryError("relay down")

    monkeypatch.setattr(webapp, "send_invite_email", _fail)

    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="admin")
        response = _create_invite(client)

        assert response.status_code == 200
        assert "/invites/" in response.text
        assert "could not be sent" in response.text


def test_accepting_an_invite_creates_the_account_with_its_role(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    with TestClient(app) as admin_client:
        login_as(admin_client, role="admin")
        _create_invite(admin_client, email="new-editor@example.test", role="editor")
        invite_path = _invite_url_from_outbox()

    with TestClient(app) as invitee:
        form_page = invitee.get(invite_path)
        assert form_page.status_code == 200
        assert "new-editor@example.test" in form_page.text

        response = invitee.post(
            invite_path,
            data={
                "display_name": "New Editor",
                "password": "a-long-enough-password",
                "password_repeat": "a-long-enough-password",
            },
            headers=_csrf_headers(invitee),
            follow_redirects=False,
        )
        assert response.status_code == 303

        assert invitee.get("/approvals/venues/x").status_code == 404
        assert invitee.get("/settings").status_code == 403


def test_invite_links_are_single_use(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as admin_client:
        login_as(admin_client, role="admin")
        _create_invite(admin_client)
        invite_path = _invite_url_from_outbox()

    with TestClient(app) as invitee:
        invitee.get(invite_path)
        invitee.post(
            invite_path,
            data={
                "display_name": "First User",
                "password": "a-long-enough-password",
                "password_repeat": "a-long-enough-password",
            },
            headers=_csrf_headers(invitee),
            follow_redirects=False,
        )

    with TestClient(app) as second:
        assert "invalid or has expired" in second.get(invite_path).text
        second.get("/login")
        retry = second.post(
            invite_path,
            data={
                "display_name": "Second User",
                "password": "a-long-enough-password",
                "password_repeat": "a-long-enough-password",
            },
            headers=_csrf_headers(second),
            follow_redirects=False,
        )
        assert retry.status_code == 400


def test_expired_invites_are_rejected(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from berlin_events_explorer import auth
    from berlin_events_explorer.models import UserRole as Role

    app = _app(tmp_path)
    with TestClient(app) as client:
        raw, hashed = auth.generate_token()
        client.app.state.store.create_auth_token(
            purpose="invite",
            token_hash=hashed,
            email="late@example.test",
            role=Role.USER,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        assert "invalid or has expired" in client.get(f"/invites/{raw}").text


def test_invites_for_registered_addresses_are_rejected(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="admin")
        seed_user(
            client.app.state.store, email="taken@example.test", role=UserRole.USER
        )

        response = _create_invite(client, email="taken@example.test")

        assert response.status_code == 400
        assert "already has an account" in response.text
        assert client.app.state.store.list_pending_invites() == []


def test_invite_creation_requires_admin(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="editor")
        assert _create_invite(client).status_code == 403


def test_invite_acceptance_validates_the_password(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as admin_client:
        login_as(admin_client, role="admin")
        _create_invite(admin_client)
        invite_path = _invite_url_from_outbox()

    with TestClient(app) as invitee:
        invitee.get(invite_path)
        for payload in (
            {"display_name": "X", "password": "short", "password_repeat": "short"},
            {
                "display_name": "X",
                "password": "a-long-enough-password",
                "password_repeat": "a-different-password",
            },
            {
                "display_name": "",
                "password": "a-long-enough-password",
                "password_repeat": "a-long-enough-password",
            },
        ):
            response = invitee.post(
                invite_path,
                data=payload,
                headers=_csrf_headers(invitee),
                follow_redirects=False,
            )
            assert response.status_code == 400, payload
