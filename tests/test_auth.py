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
