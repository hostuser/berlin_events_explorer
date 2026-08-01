# Account menu + settings shell — design

**Date:** 2026-08-01
**Status:** Approved for planning

## Problem

Two issues with the signed-in chrome in `webapp.py`:

1. The toolbar exposes three separate account controls side by side: a standalone
   **⚙ Settings** link, a **display-name** link (→ `/account`), and a **Log out**
   form/button. These should collapse into one account menu.
2. `/account` ("Your account") and `/settings` ("Settings") — and the admin
   pages reached from Site settings — render through `_render_app_page`, so the
   main-app heading *and* the application tab bar (`_render_app_nav`) still appear
   on them. The pages read as if they were app tabs and cannot be "closed". The
   `active_tab="account"`/`"admin"`/`"settings"` values are a workaround: non-tab
   pages fed through a tab-shaped shell that renders "no current marker".

## Goals

- Replace the ⚙ Settings link + name link + Log out button with a single account
  menu whose trigger is `👤 <name> ▾`.
- Menu items: **Account settings** (→ `/account`), **Site settings** (→ `/settings`,
  admin only), **Log out** (POST `/logout`).
- Give the settings-area pages a dedicated shell with no app tabs and a close (✕)
  control that returns to the main page (`/`).

## Non-goals

- No modal-overlay presentation; pages remain full-page server-rendered navigations.
- Approval pages (venue/artist review, reached from the "Awaiting approval" tab) and
  detail pages (venue/artist/date) stay on the app shell with tabs — they belong there.
- No new design tokens; reuse existing `--color-*`, `--space-*`, `--radius-*`, `--text-*`.

## Component A — Account menu

Location: `_render_app_page` toolbar (`src/berlin_events_explorer/webapp.py`, the
`account_html` / `settings_link` construction around lines 4062–4075).

When `user is not None`, render a native disclosure widget:

```html
<details class="account-menu">
  <summary class="account-menu-trigger">
    <span class="account-menu-icon" aria-hidden="true">👤</span>
    <span class="account-menu-name">{display_name}</span>
    <span class="account-menu-caret" aria-hidden="true">▾</span>
  </summary>
  <div class="account-menu-panel" role="menu">
    <a role="menuitem" href="/account">Account settings</a>
    <!-- Site settings: only when ROLE_ORDER[user.role] >= ROLE_ORDER[ADMIN] -->
    <a role="menuitem" href="/settings">Site settings</a>
    <form method="post" action="/logout" class="account-menu-logout">
      {csrf_input}
      <button role="menuitem" type="submit">Log out</button>
    </form>
  </div>
</details>
```

When `user is None`, keep the existing `Log in` link unchanged.

Decisions:
- **`<details>`/`<summary>`**, not a Datastar signal: keyboard-accessible, Escape
  closes it, `open` state managed by the browser with zero JS state.
- Add a ~5-line inline script (alongside the existing `popstate` script at the end
  of the shell) that closes any open `<details.account-menu>` when a click lands
  outside it — the one behavior `<details>` does not provide natively.
- Remove the standalone **⚙ Settings** link. Its function now lives in the menu.
- Remove the `show_settings_link` parameter of `_render_app_page` — it becomes unused
  once the standalone link is gone and the settings pages leave the app shell.
- The **Sync now** button (`sync_button`) is unchanged and stays in the toolbar; it is
  a primary action, not account chrome.

## Component B — Settings shell

New helper `_render_settings_shell(*, title, heading, kicker, content, close_href="/",
csrf_token=None)` renders a full HTML document that reuses `theme.head_assets()` but
**omits** the app nav tabs and the sync/heading toolbar. Structure:

```html
<body class="settings-page">
  <a class="skip-link" href="#main">Skip to content</a>
  <main id="main" class="settings-shell">
    <header class="settings-shell-header">
      <div>
        <p class="page-kicker">{kicker}</p>
        <h1>{heading}</h1>
      </div>
      <a class="settings-close" href="{close_href}" aria-label="Close settings">✕</a>
    </header>
    {content}
  </main>
</body>
```

`close_href` defaults to `/` for every settings-area page, matching the stated
requirement that closing returns to the main page. The settings shell needs no
Datastar signals (its forms are plain POSTs), so it omits the `data-signals` machinery.

### Pages that adopt the settings shell

Switch these five render sites from `_render_app_page` to `_render_settings_shell`,
dropping their `active_tab`/`show_sync` arguments:

| Function / route | title | heading | kicker |
|---|---|---|---|
| `_render_account_page` (`/account`) | Account · … | Account settings¹ | Account |
| site settings page (`/settings`, ~line 2821) | Settings · … | Settings | Application controls |
| `_render_user_management_page` (`/admin/users`, ~line 722) | … | User management | Administration |
| invite-created page (~line 461) | Invite · … | Invitation | User management |
| `_render_reset_link_page` (~line 584) | Password reset link · … | Password reset link | User management |

¹ Heading changes from "Your account" to "Account settings" to match the menu item.

Pages **not** touched: `/` (events), venue/artist/date detail pages, and the
approval pages — all keep `_render_app_page` and its tabs.

## Component C — Theme / CSS (`theme.py`, single stylesheet)

- `.account-menu` — `position: relative` wrapper so the panel can drop beneath the trigger.
- `.account-menu > summary` (`.account-menu-trigger`) — reuse `.settings-link` visual
  language (bordered, sunken surface, `min-height` match); `list-style: none` and
  `::-webkit-details-marker { display: none }` to drop the native triangle; flex row
  with gap for icon/name/caret.
- `.account-menu-panel` — absolutely positioned dropdown card (surface, border,
  `--radius-md`, subtle shadow), right-aligned under the trigger, sensible `min-width`
  and `z-index`. Items (`a`, `button`) are full-width rows sharing one hover treatment
  (`--color-accent-wash`); the logout `<button>` is restyled to a menu row (no separate
  button chrome), and `.account-menu-logout` has no margin.
- `.settings-shell` — max-width container mirroring `.settings-stack` width.
- `.settings-shell-header` — flex row: kicker+heading left, ✕ right, border-bottom rule.
- `.settings-close` — square bordered control sized like `.settings-link`,
  `--color-accent-wash` on hover.

## Component D — Testing

Follow the existing HTTP-level webapp test style (assertions against rendered HTML):

- **Menu:** a signed-in page contains `class="account-menu"` with "Account settings"
  and "Log out"; **"Site settings" present for an admin, absent for a non-admin**;
  the standalone "⚙ Settings" link no longer appears; logged-out state still shows
  "Log in".
- **Shell:** `GET /account`, `GET /settings`, `GET /admin/users` render the settings
  shell (contain `settings-close` / close link to `/`) and **do not** contain the app
  tab bar (`aria-label="Application views"`).
- **Regression:** `/settings` still enforces `requires_admin`; POST `/logout` still
  clears the session and redirects.

## Risks / notes

- `_render_app_page` currently receives `user=` on the settings pages so it can gate
  the sync button and approvals nav. The settings shell drops that logic entirely, so
  confirm no settings-area page depended on the app nav being present.
- Removing `show_settings_link` requires updating every `_render_app_page` call site
  that passes it (currently only the site-settings page passes `show_settings_link=False`).
