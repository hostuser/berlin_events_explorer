"""Tests for the account page: profile, password change, and preferences."""

from pathlib import Path

from litestar.testing import TestClient

from berlin_events_explorer.webapp import create_app

from conftest import TEST_PASSWORD, login_as


def _app(tmp_path: Path):
    return create_app(tmp_path / "events.sqlite", sync_interval=None)


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("csrftoken")
    return {"x-csrftoken": token} if token else {}


def _post_account(client: TestClient, **data: str):
    return client.post(
        "/account",
        data=data,
        headers=_csrf_headers(client),
        follow_redirects=False,
    )


def test_account_page_requires_login(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/account", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")


def test_any_role_can_open_its_account_page(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        user = login_as(client, role="user")
        response = client.get("/account")
        assert response.status_code == 200
        assert user.email in response.text


def test_profile_updates_the_display_name(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        user = login_as(client, role="user")

        response = _post_account(client, action="profile", display_name="New Name")

        assert response.status_code == 303
        refreshed = client.app.state.store.get_user(user.id)
        assert refreshed is not None
        assert refreshed.display_name == "New Name"
        assert "New Name" in client.get("/").text


def test_blank_display_names_are_rejected(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        user = login_as(client, role="user")

        response = _post_account(client, action="profile", display_name="   ")

        assert response.status_code == 400
        refreshed = client.app.state.store.get_user(user.id)
        assert refreshed is not None
        assert refreshed.display_name == user.display_name


def test_password_change_requires_the_current_password(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        user = login_as(client, role="user")

        rejected = _post_account(
            client,
            action="password",
            current_password="not-the-password",
            password="a-brand-new-password",
            password_repeat="a-brand-new-password",
        )
        assert rejected.status_code == 400

        accepted = _post_account(
            client,
            action="password",
            current_password=TEST_PASSWORD,
            password="a-brand-new-password",
            password_repeat="a-brand-new-password",
        )
        assert accepted.status_code == 303

    with TestClient(_app(tmp_path)) as fresh:
        fresh.get("/login")
        old = fresh.post(
            "/login",
            data={"email": user.email, "password": TEST_PASSWORD},
            headers=_csrf_headers(fresh),
            follow_redirects=False,
        )
        assert old.status_code == 400
        new = fresh.post(
            "/login",
            data={"email": user.email, "password": "a-brand-new-password"},
            headers=_csrf_headers(fresh),
            follow_redirects=False,
        )
        assert new.status_code == 303


def test_table_size_preference_applies_only_to_its_owner(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as owner:
        user = login_as(owner, role="user", email="owner@example.test")
        response = _post_account(owner, action="preferences", default_table_size="7")
        assert response.status_code == 303
        assert app.state.store.get_user_setting(user.id, "default_table_size") == 7
        assert "page_size=7" in owner.get("/").text

    with TestClient(app) as visitor:
        assert "page_size=7" not in visitor.get("/").text


def test_clearing_the_preference_restores_the_site_default(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        user = login_as(client, role="user")
        _post_account(client, action="preferences", default_table_size="7")

        response = _post_account(client, action="preferences", default_table_size="")

        assert response.status_code == 303
        store = client.app.state.store
        assert store.get_user_setting(user.id, "default_table_size") is None
        assert "page_size=7" not in client.get("/").text


def test_invalid_table_sizes_are_rejected(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="user")
        for value in ("0", "9999", "not-a-number"):
            response = _post_account(
                client, action="preferences", default_table_size=value
            )
            assert response.status_code == 400, value


def test_shell_links_to_the_account_page(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="user")
        assert 'href="/account"' in client.get("/").text
