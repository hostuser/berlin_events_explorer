# Account Menu + Settings Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three separate signed-in toolbar controls (⚙ Settings link, name link, Log out button) with one account dropdown menu, and give the settings-area pages a dedicated shell with no app tabs and a close (✕) control that returns to the main page.

**Architecture:** All rendering lives in `src/berlin_events_explorer/webapp.py`; the single stylesheet lives in `src/berlin_events_explorer/theme.py`. Task 1 rewrites the account controls inside `_render_app_page` into a native `<details>` disclosure menu. Task 2 adds a new `_render_settings_shell` helper and switches the five settings-area render sites off `_render_app_page` onto it, so the app tab bar no longer appears on those pages.

**Tech Stack:** Litestar (server-rendered HTML f-strings), Datastar (app shell only), pytest + `litestar.testing.TestClient`, ruff, ty.

## Global Constraints

- Line length 88; ruff (black-compatible) formatting; Google-style docstrings.
- All user-derived strings passed through `html.escape` (`escape(...)`, `quote=True` inside attributes) — follow the existing pattern in `webapp.py`.
- No new CSS design tokens: reuse existing `--color-*`, `--space-*`, `--radius-*`, `--shadow-overlay`. Confirmed available: `--radius-sm`, `--radius-md`, `--space-1`..`--space-7`, `--color-surface`, `--color-surface-sunken`, `--color-accent-wash`, `--color-edge`, `--color-line`, `--color-text`, `--color-text-muted`, `--shadow-overlay`.
- Admin gate uses the existing idiom: `ROLE_ORDER[user.role] >= ROLE_ORDER[UserRole.ADMIN]`.
- Run tests with `uv run pytest tests -s` (or `just test <pattern>`); type-check with `just typecheck`; lint/format with `just lint` / `just format`.
- Commit after each task with a conventional-commit message ending:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1: Account dropdown menu in the app shell

Replace the standalone ⚙ Settings link + display-name link + Log out button in `_render_app_page` with a single `<details>` disclosure menu. Remove the now-unused `show_settings_link` parameter and its one call-site argument. Add the click-outside-to-close script and the menu CSS.

**Files:**
- Modify: `src/berlin_events_explorer/webapp.py`
  - `_render_app_page` signature (`~line 3995`), `settings_link`/`account_html` construction (`~lines 4062–4075`), toolbar-actions block (`~lines 4098–4102`), inline scripts (`~line 4109`).
  - Site-settings page call site (`~line 2828`): drop the `show_settings_link=False` argument.
- Modify: `src/berlin_events_explorer/theme.py` (append account-menu CSS near `.settings-link` rules, `~line 212`).
- Test: `tests/test_webapp.py`, `tests/test_account.py`.

**Interfaces:**
- Consumes: `escape`, `_csrf_input`, `ROLE_ORDER`, `UserRole`, `UserRecord` (all already imported in `webapp.py`).
- Produces: signed-in pages render `<details class="account-menu">` containing `<a href="/account">Account settings</a>`, a `<a href="/settings">Site settings</a>` item **only for admins**, and a `<form action="/logout"><button>Log out</button></form>`. The `show_settings_link` parameter of `_render_app_page` no longer exists.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_webapp.py` (uses the existing `_login` admin helper and `create_app`):

```python
def test_account_menu_replaces_separate_controls(tmp_path) -> None:
    """Admins get one dropdown with account, site settings, and logout."""
    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        _login(client)  # admin
        page = client.get("/").text

    assert 'class="account-menu"' in page
    assert '<a role="menuitem" href="/account">Account settings</a>' in page
    assert '<a role="menuitem" href="/settings">Site settings</a>' in page
    assert 'action="/logout"' in page
    # The old standalone gear link is gone; /settings now only appears in the menu.
    assert 'aria-label="Open settings"' not in page
    assert page.count('href="/settings"') == 1


def test_account_menu_hides_site_settings_for_non_admins(tmp_path) -> None:
    """Only admins see the Site settings item."""
    from conftest import login_as

    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        login_as(client, role="user")
        page = client.get("/").text

    assert 'class="account-menu"' in page
    assert 'href="/account"' in page  # Account settings present for everyone
    assert 'href="/settings"' not in page  # Site settings admin-only
    assert 'action="/logout"' in page


def test_logged_out_shell_shows_login_not_menu(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        page = client.get("/").text

    assert 'class="account-menu"' not in page
    assert '>Log in</a>' in page
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_webapp.py -s -k "account_menu or logged_out_shell"`
Expected: FAIL — `class="account-menu"` not found (current shell renders the old controls).

- [ ] **Step 3: Rewrite the account controls in `_render_app_page`**

In `src/berlin_events_explorer/webapp.py`, remove the `show_settings_link: bool = True` parameter from the `_render_app_page` signature (`~line 4006`).

Delete the `settings_link = ( ... )` assignment block (`~lines 4062–4066`).

Replace the `if user is None: ... else: account_html = (...)` block (`~lines 4067–4075`) with:

```python
    if user is None:
        account_html = '<a class="settings-link" href="/login">Log in</a>'
    else:
        site_settings_item = (
            '<a role="menuitem" href="/settings">Site settings</a>'
            if ROLE_ORDER[user.role] >= ROLE_ORDER[UserRole.ADMIN]
            else ""
        )
        account_html = (
            '<details class="account-menu">'
            '<summary class="account-menu-trigger">'
            '<span class="account-menu-icon" aria-hidden="true">👤</span>'
            f'<span class="account-menu-name">{escape(user.display_name)}</span>'
            '<span class="account-menu-caret" aria-hidden="true">▾</span>'
            "</summary>"
            '<div class="account-menu-panel" role="menu">'
            '<a role="menuitem" href="/account">Account settings</a>'
            f"{site_settings_item}"
            '<form method="post" action="/logout" class="account-menu-logout">'
            f"{_csrf_input(csrf_token)}"
            '<button role="menuitem" type="submit">Log out</button>'
            "</form>"
            "</div>"
            "</details>"
        )
```

In the toolbar-actions block (`~lines 4098–4102`), remove the `{settings_link}` line so only `{sync_button}` and `{account_html}` remain:

```python
          <div class="toolbar-actions">
            {sync_button}
            {account_html}
          </div>
```

- [ ] **Step 4: Add the click-outside-to-close script**

In `_render_app_page`, replace the single trailing script line (`~line 4109`) with both scripts:

```html
    <script>window.addEventListener('popstate', () => window.location.reload())</script>
    <script>
document.addEventListener('click', (event) => {
  document.querySelectorAll('details.account-menu[open]').forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute('open');
  });
});
    </script>
```

- [ ] **Step 5: Drop the removed argument at the site-settings call site**

In the site-settings render (`~line 2821–2831`), delete the `show_settings_link=False,` line so the call no longer passes the removed parameter. (This page stays on `_render_app_page` until Task 2.)

- [ ] **Step 6: Add the account-menu CSS**

In `src/berlin_events_explorer/theme.py`, after the `.settings-link:hover` rule (`~line 212`), add:

```css
/* --- account menu (toolbar disclosure) --- */
.account-menu { position: relative; }
.account-menu > summary { display: inline-flex; align-items: center; gap: var(--space-1);
  min-height: 2.35rem; padding: .45rem .75rem; border: 1px solid var(--color-edge);
  border-radius: var(--radius-md); background: var(--color-surface-sunken);
  color: var(--color-text); font-weight: 600; cursor: pointer; list-style: none; }
.account-menu > summary::-webkit-details-marker { display: none; }
.account-menu > summary:hover,
.account-menu[open] > summary { background: var(--color-accent-wash); }
.account-menu-caret { font-size: .8em; color: var(--color-text-muted); }
.account-menu-panel { position: absolute; right: 0; top: calc(100% + var(--space-1));
  z-index: 20; min-width: 12rem; display: grid; padding: var(--space-1);
  background: var(--color-surface); border: 1px solid var(--color-edge);
  border-radius: var(--radius-md); box-shadow: var(--shadow-overlay); }
.account-menu-panel a, .account-menu-panel button { display: block; width: 100%;
  text-align: left; padding: .5rem .65rem; border: none; border-radius: var(--radius-sm);
  background: none; color: var(--color-text); font: inherit; font-weight: 600;
  text-decoration: none; cursor: pointer; }
.account-menu-panel a:hover,
.account-menu-panel button:hover { background: var(--color-accent-wash); }
.account-menu-logout { margin: 0; }
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_webapp.py tests/test_account.py -s -k "account_menu or logged_out_shell or shell_links or top_level_views or settings"`
Expected: PASS. (`test_shell_links_to_the_account_page` and `test_top_level_views_share_application_shell` still pass — the menu keeps one `href="/account"` and one `href="/settings"` on `/` for admins.)

- [ ] **Step 8: Lint, type-check, format**

Run: `just lint && just typecheck && just format`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add src/berlin_events_explorer/webapp.py src/berlin_events_explorer/theme.py tests/test_webapp.py
git commit -m "feat(webapp): consolidate account controls into a dropdown menu

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Dedicated settings shell for the settings-area pages

Add `_render_settings_shell` and switch the five settings-area render sites off `_render_app_page` onto it, so the app tab bar and main-app toolbar no longer appear on `/account`, `/settings`, `/admin/users`, the invite-created page, and the password-reset-link page. Add the shell CSS. Rename the account-page heading to "Account settings".

**Files:**
- Modify: `src/berlin_events_explorer/webapp.py`
  - Add `_render_settings_shell` (place it just above `_render_app_page`, `~line 3995`).
  - `_render_account_page` return (`~lines 541–550`).
  - Site-settings page return (`~lines 2821–2831`).
  - `_render_user_management_page` return (`~lines 720–729`).
  - Invite-created page return (`~lines 461–470`).
  - `_render_reset_link_page` return (`~lines 584–593`).
- Modify: `src/berlin_events_explorer/theme.py` (append settings-shell CSS near `.settings-stack`, `~line 415`).
- Test: `tests/test_webapp.py`, `tests/test_account.py`.

**Interfaces:**
- Consumes: `theme.head_assets()`, `escape` (already imported). Content strings are built exactly as today and passed unchanged.
- Produces: `_render_settings_shell(*, title: str, heading: str, kicker: str, content: str, close_href: str = "/") -> str`. Rendered pages contain `<main id="main" class="settings-shell">`, a `<a class="settings-close" href="{close_href}" aria-label="Close settings">✕</a>`, and **no** `<nav class="tabs" aria-label="Application views">`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_webapp.py`:

```python
@pytest.mark.parametrize("path", ["/settings", "/admin/users"])
def test_settings_area_pages_use_the_closable_shell(tmp_path, path: str) -> None:
    """Settings-area pages drop the app tabs and expose a close-to-home control."""
    with TestClient(create_app(tmp_path / "events.sqlite")) as client:
        _login(client)  # admin
        page = client.get(path).text

    assert 'class="settings-shell"' in page
    assert 'class="settings-close" href="/"' in page
    assert 'aria-label="Application views"' not in page  # no app tab bar
    assert 'id="tab-content"' not in page
```

Add to `tests/test_account.py`:

```python
def test_account_page_uses_the_closable_shell(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        login_as(client, role="user")
        page = client.get("/account").text

    assert 'class="settings-shell"' in page
    assert 'class="settings-close" href="/"' in page
    assert 'aria-label="Application views"' not in page
    assert "Account settings" in page  # renamed heading
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_webapp.py tests/test_account.py -s -k "closable_shell"`
Expected: FAIL — `class="settings-shell"` not found (pages still render through `_render_app_page`).

- [ ] **Step 3: Add the `_render_settings_shell` helper**

In `src/berlin_events_explorer/webapp.py`, immediately above `def _render_app_page(` (`~line 3995`), add:

```python
def _render_settings_shell(
    *,
    title: str,
    heading: str,
    kicker: str,
    content: str,
    close_href: str = "/",
) -> str:
    """Render a settings-area page without the app tab bar.

    Closing returns to ``close_href`` (the main page by default). Settings-area
    forms are plain POSTs, so this shell omits the Datastar signal machinery of
    the app shell.

    Args:
        title: Document ``<title>``.
        heading: Page ``<h1>`` text.
        kicker: Small uppercase label above the heading.
        content: Pre-rendered inner HTML (already escaped where needed).
        close_href: Target of the close (✕) control.

    Returns:
        A complete HTML document.
    """

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(title)}</title>
    {theme.head_assets()}
  </head>
  <body class="settings-page">
    <a class="skip-link" href="#main">Skip to content</a>
    <main id="main" class="settings-shell">
      <header class="settings-shell-header">
        <div>
          <p class="page-kicker">{escape(kicker)}</p>
          <h1>{escape(heading)}</h1>
        </div>
        <a class="settings-close" href="{escape(close_href, quote=True)}"
           aria-label="Close settings">✕</a>
      </header>
      {content}
    </main>
  </body>
</html>"""
```

- [ ] **Step 4: Switch the account page to the shell (and rename its heading)**

Replace `_render_account_page`'s return (`~lines 541–550`) with:

```python
    return _render_settings_shell(
        title="Account · Berlin Events Explorer",
        heading="Account settings",
        kicker="Account",
        content=content,
    )
```

- [ ] **Step 5: Switch the site-settings page to the shell**

Replace the site-settings return (`~lines 2821–2831`) with:

```python
    return _render_settings_shell(
        title="Settings · Berlin Events Explorer",
        heading="Settings",
        kicker="Application controls",
        content=content,
    )
```

- [ ] **Step 6: Switch the user-management page to the shell**

Replace `_render_user_management_page`'s return (`~lines 720–729`) with:

```python
    return _render_settings_shell(
        title="Users · Berlin Events Explorer",
        heading="User management",
        kicker="Administration",
        content=content,
    )
```

- [ ] **Step 7: Switch the invite-created page to the shell**

Replace the invite-created return (`~lines 461–470`) with:

```python
    return _render_settings_shell(
        title="Invite · Berlin Events Explorer",
        heading="Invitation",
        kicker="User management",
        content=content,
    )
```

- [ ] **Step 8: Switch the password-reset-link page to the shell**

Replace `_render_reset_link_page`'s return (`~lines 584–593`) with:

```python
    return _render_settings_shell(
        title="Password reset link · Berlin Events Explorer",
        heading="Password reset link",
        kicker="User management",
        content=content,
    )
```

- [ ] **Step 9: Add the settings-shell CSS**

In `src/berlin_events_explorer/theme.py`, after the `.settings-stack`/`.settings-card` rules (`~line 415–420`), add:

```css
/* --- settings shell (closable settings-area pages) --- */
.settings-shell { max-width: 820px; margin: 0 auto; padding: var(--space-6) var(--space-4); }
.settings-shell-header { display: flex; justify-content: space-between; align-items: flex-start;
  gap: var(--space-3); padding-bottom: var(--space-4); margin-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-line); }
.settings-close { display: inline-flex; align-items: center; justify-content: center;
  flex: none; width: 2.35rem; height: 2.35rem; border: 1px solid var(--color-edge);
  border-radius: var(--radius-md); background: var(--color-surface-sunken);
  color: var(--color-text); text-decoration: none; font-size: 1.1rem; line-height: 1; }
.settings-close:hover { background: var(--color-accent-wash); }
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `uv run pytest tests/test_webapp.py tests/test_account.py -s`
Expected: PASS. In particular the new `closable_shell` tests pass, and the existing settings/account/admin tests still pass (content and routes are unchanged; only the surrounding shell differs).

- [ ] **Step 11: Full suite, lint, type-check, format**

Run: `uv run pytest tests -s && just lint && just typecheck && just format`
Expected: all green.

- [ ] **Step 12: Commit**

```bash
git add src/berlin_events_explorer/webapp.py src/berlin_events_explorer/theme.py tests/test_webapp.py tests/test_account.py
git commit -m "feat(webapp): render settings-area pages in a closable shell without app tabs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Account menu replacing three controls, admin-gated Site settings, icon+name+caret trigger → Task 1. ✓
- `<details>` mechanism + click-outside script → Task 1 Steps 3–4. ✓
- Remove standalone ⚙ link and `show_settings_link` param → Task 1 Steps 3, 5. ✓
- Settings shell (no tabs, ✕ → `/`) → Task 2 Step 3. ✓
- All five settings-area pages adopt the shell (`/account`, `/settings`, `/admin/users`, invite, reset-link) → Task 2 Steps 4–8. ✓
- Account heading "Your account" → "Account settings" → Task 2 Step 4. ✓
- CSS additions, no new tokens → Task 1 Step 6, Task 2 Step 9 (all tokens verified present). ✓
- Testing (menu admin/non-admin/logged-out; shell present + no tabs; regressions) → Task 1 Step 1, Task 2 Step 1, plus existing suite in Step 11. ✓
- Approval/detail pages untouched → not modified by any task. ✓

**Placeholder scan:** No TBD/TODO; every code and CSS step has literal content.

**Type consistency:** `_render_settings_shell` keyword params (`title`, `heading`, `kicker`, `content`, `close_href`) match every call site in Steps 4–8. `ROLE_ORDER`/`UserRole.ADMIN` gate matches the spec and existing `_render_app_page` usage. The removed `show_settings_link` is dropped in the signature (Task 1 Step 3) and at its only call site (Task 1 Step 5) — no orphan references.

**Risk note:** Task 1 removes the standalone ⚙ link but leaves the settings pages on `_render_app_page` (now showing the account menu + tabs) as an intermediate state; Task 2 removes the tabs. Each task's own tests pass at its own commit.
