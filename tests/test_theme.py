"""Tests for the consolidated Fahrplan stylesheet and its delivery."""

import re

import pytest
from litestar.testing import TestClient

from berlin_events_explorer import theme
from berlin_events_explorer.webapp import create_app


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(color_a: str, color_b: str) -> float:
    brighter, darker = sorted(
        (_relative_luminance(color_a), _relative_luminance(color_b)), reverse=True
    )
    return (brighter + 0.05) / (darker + 0.05)


def test_token_pairs_meet_wcag_contrast() -> None:
    """Every §3.3 light-theme pair meets its WCAG 2.2 AA requirement."""

    for name_a, name_b, minimum in theme.CONTRAST_PAIRS:
        ratio = _contrast(theme._TOKEN_VALUES[name_a], theme._TOKEN_VALUES[name_b])
        assert ratio >= minimum, f"{name_a} on {name_b}: {ratio:.2f} < {minimum}"


def test_dark_token_pairs_meet_wcag_contrast() -> None:
    """Every §3.3 dark-theme pair meets its WCAG 2.2 AA requirement."""

    for name_a, name_b, minimum in theme.CONTRAST_PAIRS_DARK:
        ratio = _contrast(
            theme._DARK_TOKEN_VALUES[name_a], theme._DARK_TOKEN_VALUES[name_b]
        )
        assert ratio >= minimum, f"dark {name_a} on {name_b}: {ratio:.2f} < {minimum}"


def test_stylesheet_ships_both_themes() -> None:
    """Dark tokens activate via media query and can be forced via data-theme."""

    css = theme.stylesheet()
    assert "@media (prefers-color-scheme: dark)" in css
    assert '[data-theme="dark"]' in css
    assert '[data-theme="light"]' in css


def test_no_hex_literals_outside_token_layer() -> None:
    """A hex literal outside the tokens layer is a defect (§3.4)."""

    css = theme.stylesheet()
    body = css.split("@layer base", 1)[1]
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", body)


@pytest.mark.parametrize("path", ["/", "/login"])
def test_every_page_offers_a_skip_link(tmp_path, path) -> None:
    """The first focusable element jumps to #main (§8.4)."""

    app = create_app(tmp_path / "events.sqlite")
    with TestClient(app=app) as client:
        response = client.get(path, follow_redirects=True)
    assert 'class="skip-link" href="#main"' in response.text
    assert 'id="main"' in response.text


def test_venue_rows_keep_table_semantics(tmp_path) -> None:
    """Rows must not carry role=link/tabindex — the cell's <a> is the link (§7.2)."""

    app = create_app(tmp_path / "events.sqlite")
    with TestClient(app=app) as client:
        response = client.get("/?tab=venues", follow_redirects=True)
    assert 'role="link"' not in response.text
    assert (
        "<tr" not in response.text
        or 'tr class="venue-row" tabindex' not in response.text
    )


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
