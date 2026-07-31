"""Tests for the consolidated Fahrplan stylesheet and its delivery."""

import pytest
from litestar.testing import TestClient

from berlin_events_explorer import theme
from berlin_events_explorer.webapp import create_app


@pytest.mark.parametrize(
    "path",
    ["/", "/?tab=venues", "/login", "/dates/2026-08-01"],
)
def test_pages_link_stylesheet_and_carry_no_style_blocks(tmp_path, path) -> None:
    app = create_app(tmp_path / "events.sqlite")
    with TestClient(app=app) as client:
        response = client.get(path, follow_redirects=True)
    assert response.status_code == 200
    assert "/static/app.css?v=" in response.text
    assert "<style" not in response.text


def test_stylesheet_declares_cascade_layers() -> None:
    css = theme.stylesheet()
    assert "@layer tokens, base, components, views;" in css
    assert "--color-text" in css
    assert "--color-surface" in css


def test_stylesheet_href_carries_content_hash() -> None:
    assert theme.STYLESHEET_HREF.startswith("/static/app.css?v=")
    assert len(theme.STYLESHEET_HREF.split("v=")[1]) == 12


@pytest.mark.parametrize(
    "font_path",
    ["/static/fonts/inter-var.woff2", "/static/fonts/d-din-condensed-bold.woff2"],
)
def test_vendored_fonts_are_served(tmp_path, font_path) -> None:
    app = create_app(tmp_path / "events.sqlite")
    with TestClient(app=app) as client:
        response = client.get(font_path)
    assert response.status_code == 200
    assert response.content[:4] == b"wOF2"


def test_app_css_is_served_with_far_future_caching(tmp_path) -> None:
    app = create_app(tmp_path / "events.sqlite")
    with TestClient(app=app) as client:
        response = client.get("/static/app.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "immutable" in response.headers["cache-control"]
    assert "--color-text" in response.text
