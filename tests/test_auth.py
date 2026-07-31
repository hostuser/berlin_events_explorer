"""Tests for editor session authentication on the web UI."""

from pathlib import Path

import pytest
from litestar.testing import TestClient

from berlin_events_explorer.webapp import create_app

EDITOR_PASSWORD = "editor-secret"


def _app(tmp_path: Path, **kwargs):
    kwargs.setdefault("editor_password", EDITOR_PASSWORD)
    return create_app(tmp_path / "events.sqlite", sync_interval=None, **kwargs)


def login(client: TestClient, password: str = EDITOR_PASSWORD):
    """Authenticate a test client as the editor."""

    return client.post("/login", data={"password": password}, follow_redirects=False)


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


def test_guarded_post_returns_401(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        for path in (
            "/settings",
            "/sync",
            "/approvals/venues/some-venue",
            "/approvals/artists/some-artist",
            "/approvals/venues/some-venue/discover",
            "/approvals/artists/some-artist/discover",
            "/settings/clear-database",
        ):
            response = client.post(path, follow_redirects=False)
            assert response.status_code == 401, path


def test_login_with_correct_password_grants_access(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = login(client)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert client.get("/settings").status_code == 200


def test_login_redirects_to_safe_next_target(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/login",
            data={"password": EDITOR_PASSWORD, "next": "/?tab=approvals"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/?tab=approvals"


def test_login_rejects_external_next_target(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/login",
            data={"password": EDITOR_PASSWORD, "next": "https://evil.example/"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"


def test_login_rejects_protocol_relative_next_target(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/login",
            data={"password": EDITOR_PASSWORD, "next": "//evil.example/"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"


def test_login_with_wrong_password_is_rejected(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = login(client, password="wrong")
        assert response.status_code == 400
        assert client.get("/settings", follow_redirects=False).status_code == 303


def test_login_page_renders(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/login")
        assert response.status_code == 200
        assert 'name="password"' in response.text


def test_logout_clears_the_session(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        login(client)
        assert client.get("/settings").status_code == 200
        response = client.post("/logout", follow_redirects=False)
        assert response.status_code == 303
        assert client.get("/settings", follow_redirects=False).status_code == 303


def test_unconfigured_password_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BERLIN_EVENTS_EDITOR_PASSWORD", raising=False)
    app = create_app(
        tmp_path / "events.sqlite", sync_interval=None, editor_password=None
    )
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.post("/settings", follow_redirects=False).status_code == 401
        response = login(client)
        assert response.status_code == 400
        assert client.get("/settings", follow_redirects=False).status_code == 303


def test_editor_password_read_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BERLIN_EVENTS_EDITOR_PASSWORD", "env-secret")
    app = create_app(tmp_path / "events.sqlite", sync_interval=None)
    with TestClient(app) as client:
        response = login(client, password="env-secret")
        assert response.status_code == 303
        assert client.get("/settings").status_code == 200
