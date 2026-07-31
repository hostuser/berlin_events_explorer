# User Accounts

The web UI uses per-user accounts with three roles:

| Role     | Can do |
|----------|--------|
| `user`   | Log in, manage their own profile/password, set personal preferences (rows per table). Future: subscriptions. |
| `editor` | Everything `user` can, plus the approval queue (venues/artists) and manual sync. |
| `admin`  | Everything `editor` can, plus operational settings (`/settings`) and user management (`/admin/users`): invites, role changes, deactivation, password-reset links. |

Login is email + password (Argon2id hashes in the `users` table). Sessions are
server-side, stored in a `<database>.sessions/` directory next to the SQLite
file, and survive restarts. Role changes and deactivation take effect on the
target's next request — no re-login needed.

## Registration model

There is no open signup. Admins create **single-use invite links** (via
`/admin/users` or the copyable URL shown after creation). Invites expire after
7 days; the invitee picks their own display name and password. Tokens are
stored hashed, so a link is shown exactly once — regenerate if lost.

Password resets are self-service via "Forgot password?" on the login page
(2-hour single-use token, response never reveals whether an address has an
account), or admin-generated from `/admin/users`.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `BERLIN_EVENTS_SECRET_KEY` | production: **yes** | CSRF token signing. Startup fails without it in production; development falls back to a per-process key. |
| `BERLIN_EVENTS_BASE_URL` | production: **yes** | Absolute base for invite/reset links in emails (e.g. `https://events.example.org`) — the app itself sits behind Caddy on 127.0.0.1. |
| `BERLIN_EVENTS_EMAIL_BACKEND` | no (default `console`) | `console` (print, dev), `memory` (tests), `smtp`. |
| `BERLIN_EVENTS_SMTP_HOST` / `_PORT` | smtp only | Relay host/port (port defaults to 587). |
| `BERLIN_EVENTS_SMTP_USERNAME` / `_PASSWORD` | smtp only | Relay credentials. |
| `BERLIN_EVENTS_SMTP_TLS` | smtp only | `starttls` (default), `ssl`, or `none`. |
| `BERLIN_EVENTS_EMAIL_FROM` | recommended | Sender address (default `noreply@localhost`). |
| `BERLIN_EVENTS_EMAIL_FROM_NAME` | no | Sender display name. |
| `BERLIN_EVENTS_EDITOR_PASSWORD` | **removed** | The shared editor password is gone — delete it from env files. |

Scaleway TEM and Postmark both work through the `smtp` backend with their
relay credentials.

The systemd units load `~/.config/berlin-events/web.env` (optional file,
`EnvironmentFile=-`), which should contain at least:

```ini
BERLIN_EVENTS_SECRET_KEY=<long random string>
BERLIN_EVENTS_BASE_URL=https://events.example.org
BERLIN_EVENTS_EMAIL_BACKEND=smtp
BERLIN_EVENTS_SMTP_HOST=smtp.tem.scw.cloud
BERLIN_EVENTS_SMTP_USERNAME=<username>
BERLIN_EVENTS_SMTP_PASSWORD=<password>
BERLIN_EVENTS_EMAIL_FROM=events@example.org
```

## Bootstrap runbook

1. Deploy and migrate as usual (the `users`, `auth_tokens`, and
   `user_settings` tables are created by the Atlas migration on first store
   open).
2. On the host, create the first administrator:

   ```console
   $ berlin-events users create-admin --database /path/to/events.sqlite
   Email: you@example.org
   Password: ********
   Repeat for confirmation: ********
   Administrator you@example.org created
   ```

3. Log in at `/login`, open **Settings → Manage users**, and invite the rest
   of the team with appropriate roles.

`berlin-events users list --database ...` shows accounts, roles, and last
logins.

## Notes and known limitations

- Account existence is not revealed by login or reset flows (identical
  responses, timing-safe dummy password verification).
- The session id is not rotated on login (Litestar server-side sessions
  don't expose rotation); cookies are HttpOnly/SameSite=Lax.
- The reset-request endpoint has no rate limiting yet; the identical-response
  design already blocks enumeration, and the instance is single-node and
  low-traffic. Revisit if abused.
- Editorial actions (venue/artist approvals) and admin actions write
  structured log rows (`store.log`) including the acting account's email.
