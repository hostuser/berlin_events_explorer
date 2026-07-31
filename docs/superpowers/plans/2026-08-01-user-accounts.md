# User Accounts for Berlin Events Explorer

## Context

The app currently has a single shared editor password (`BERLIN_EVENTS_EDITOR_PASSWORD` → session flag `is_editor`, guard `_require_editor` at `webapp.py:150`). Markus wants real user accounts: per-user settings now, subscriptions to events/tags later, and roles — at least an editor role for the existing venue/artist approval flow. Sessions today are a `MemoryStore` (lost on restart); there is no user model or password hashing.

**Decisions made with the user (do not relitigate):**
1. Registration via **single-use invite links** (no open signup yet).
2. Login via **email + password**, Argon2id (`argon2-cffi`).
3. **Email flows included now** — invite + self-service password-reset emails via `litestar-email>=0.4.0` (console default, memory in tests, SMTP covers Scaleway TEM / Postmark; provider backends addable later).
4. **Fixed role column**: `user < editor < admin`, hierarchical guard factory. Approvals/sync stay editor+; global/operational settings page and user management become **admin-only**; logged-in users get per-user settings.
5. Shared editor password is **replaced** (not kept). `BERLIN_EVENTS_SECRET_KEY` becomes standalone-required in production for CSRF. First admin bootstrapped via CLI.

**Architecture (verified against code):**
- Identity loading: custom `AbstractAuthenticationMiddleware` subclass reading `user_id` from the session, loading the user fresh from DB once per request (`to_thread`), setting `scope["user"]` (None for anonymous — never raises; site is mostly public). Verified: litestar 2.24 permits `AuthenticationResult(user=None)`. Guards do authorization only: `NotAuthorizedException` (401 → existing login-redirect handler) when anonymous, `PermissionDeniedException` (403) when role insufficient. Fresh-per-request load means role changes/deactivation apply on the next request — no session-revocation machinery.
- Guards must read `connection.scope.get("user")`, NOT `connection.user` (which raises `ImproperlyConfiguredException` when the key is absent, e.g. on excluded paths).
- Sessions: litestar `FileStore(f"{database}.sessions", create_directories=True)` replaces `MemoryStore` (zero-code, persistent, stable path in prod since the DB lives outside `releases/current`); `delete_expired()` on startup via a small lifespan. A custom SQLite store was rejected: async Store interface × sync engine = a `to_thread` hop per session-carrying request.
- Email: build `EmailConfig` in `create_app`, use `async with email_config.provide_service() as mailer` directly in handler closures (litestar-email supports standalone lifecycle; the codebase uses no plugins/DI — stay consistent).
- Module layout: new `src/berlin_events_explorer/auth.py` (hashing, tokens, middleware, guard factory — no webapp/storage imports; middleware gets a loader callable from `app.state`), new `src/berlin_events_explorer/emails.py` (config-from-env + two send functions). `UserRole`/`UserRecord` (Pydantic, no `password_hash` field) in `models.py`. Handlers/renderers stay in `webapp.py` — the thread-discipline test (`test_webapp.py:1983`) only scans `berlin_events_explorer.webapp` handlers, and renderer helpers would circular-import.

## Schema — one Atlas migration, three tables

`users` (Integer PK like `worker_runs`; email unique lowercased; password_hash; display_name; role; is_active; created_at/updated_at/last_login_at) · `auth_tokens` (purpose `invite|password_reset`, token_hash = sha256 of `secrets.token_urlsafe(32)`, email, role [invites], user_id [resets], created_by, expires_at, used_at; unique index on token_hash) · `user_settings` (user_id FK CASCADE, key, value_json, updated_at, PK(user_id,key) — mirrors global `settings`).

Workflow: `just db-new add_user_accounts` → paste SQL → `atlas migrate hash --dir file://src/berlin_events_explorer/db_migrations` → `just db-validate`. (Skipping the hash step breaks every `EventStore.__init__` and thus the whole suite.)

## Stages

Each stage leaves the suite green; Stage 3 is the single breaking cutover.

### Stage 1 — Schema + storage
Files: new migration + `atlas.sum`; `storage.py`; `models.py`; `tests/test_storage.py`, `test_migrations.py`.
- `models.py`: `UserRole(str, Enum)`, frozen `UserRecord` (no password_hash; email lowercase validator).
- `storage.py`: three `Table` defs; dataclasses `UserCredentials(user, password_hash)`, `AuthToken`; `EventStore` methods (sync, house style): `create_user` (IntegrityError → ValueError on dup email), `get_user`, `get_user_credentials(email)`, `list_users`, `count_admins`, `update_user` (partial, bumps updated_at), `record_user_login`, `create_auth_token`, `get_auth_token(token_hash, purpose=)`, `mark_auth_token_used`, `delete_auth_tokens(purpose=, email=/user_id=)`, `list_pending_invites`, `get_user_setting`/`set_user_setting`/`delete_user_setting` (copy the `set_setting` upsert at `storage.py:396-410`). `clear_application_data`: preserve users/user_settings (like settings), clear auth_tokens.
- Tests: migration table-set assertion; CRUD roundtrips; dup email; token consume/expiry; clear preserves users.

### Stage 2 — Auth core (`auth.py`) + deps
Files: new `auth.py`; `pyproject.toml` (`argon2-cffi>=23.1`, `litestar-email[smtp]>=0.4.0`); unit tests.
- `ROLE_ORDER`; module-level `PASSWORD_HASHER = PasswordHasher()` (tests monkeypatch a cheap one); `hash_password`/`verify_password` (catch VerifyMismatchError/InvalidHashError); `generate_token() -> (raw, sha256hex)`/`hash_token`; `SESSION_USER_KEY`; `INVITE_TTL=7d`, `RESET_TTL=2h`.
- `SessionUserAuthMiddleware.authenticate_request`: `user_id = connection.scope.get("session", {}).get(SESSION_USER_KEY)`; non-int or missing/inactive user → `AuthenticationResult(user=None, auth=None)`; loader from `connection.app.state.load_user` via `to_thread.run_sync`.
- `require_role(minimum)` guard factory (+ `requires_user/editor/admin`) reading `scope.get("user")`.
- Tests: hash/verify matrix; guard matrix per role incl. anonymous; middleware with stub loader (found/missing/inactive); one un-monkeypatched test asserting `$argon2id$` prefix.

### Stage 3 — Cutover: middleware wiring, login rework, session persistence
Files: `webapp.py`; `cli.py`; `tests/conftest.py`, `test_auth.py` (rewrite), `test_webapp.py` (helper body only).
- `create_app`: drop `editor_password` (delete block at 499-504); add `base_url: str | None = None`, `email_config: EmailConfig | None = None` (default from env).
- `_resolve_csrf_secret` rework: env var, else production → raise ValueError at startup; development → random + warning. Remove editor-password fallback.
- `stores={"sessions": FileStore(Path(f"{database}.sessions"), create_directories=True)}`; startup `delete_expired()` lifespan alongside `periodic_sync_lifespan`.
- `Litestar(..., state=State({"store": store, "load_user": store.get_user}))` — needed by middleware AND test helper.
- `middleware=[session_config.middleware, DefineMiddleware(SessionUserAuthMiddleware, exclude=["^/static", "^/health", "^/schema"])]` (session middleware outermost hydrates session first — verified).
- Login rework (`webapp.py:524-576`): email+password form; `do_login` async + to_thread: lookup credentials; unknown email → dummy `verify_password` against a pre-hashed constant (timing-safe, no enumeration); inactive → same generic error; success → `record_user_login`, `set_session({SESSION_USER_KEY: user.id})`, redirect `_safe_next_target`.
- Replace all `guards=[_require_editor]` → `guards=[requires_editor]`, EXCEPT `/settings`, `/settings` POST, `/settings/clear-database` → `guards=[requires_admin]`. Delete `_require_editor`, `_SESSION_EDITOR_KEY`, `EDITOR_PASSWORD_ENV_VAR`.
- `index` approvals gate (`webapp.py:589`): session-flag check → `scope.get("user")` + role rank.
- Exception handlers: keep `NotAuthorizedException` handler; add `PermissionDeniedException` → generic styled 403 (also styles CSRF failures — existing CSRF tests assert status only, safe).
- Shell (`_render_app_page`, webapp.py:2677): optional `user` param → "Log in" link or display-name → `/account` + logout POST form (with `_csrf_input`); thread `user=request.scope.get("user")` through top-level render calls like `csrf_token` is today.
- Tests: conftest — delete `_editor_password` autouse fixture; add `TEST_PASSWORD`, autouse cheap-Argon2 monkeypatch (default costs ~50-100ms × ~40 logins), autouse `BERLIN_EVENTS_EMAIL_BACKEND=memory` + `InMemoryBackend.clear()` around each test; helpers `seed_user(store, ...)` and `login_as(client, role=..., ...)` (seeds via `client.app.state.store`, posts /login with CSRF header). `test_webapp.py`: only `_login` body changes → `login_as(client, role="editor")`; sweep for `/settings`-hitting tests that now need `role="admin"` (e.g. `test_slow_settings_render_does_not_block_other_requests`). `test_auth.py` rewrite: login paths, logout, 303/401 anonymous, 403 role matrix, CSRF, and a session-survives-restart test (two `create_app` on same tmp DB, reuse cookies — proves FileStore).

### Stage 4 — Email plumbing (`emails.py`)
- `email_config_from_env()`: `BERLIN_EVENTS_EMAIL_BACKEND` ∈ {console (default), memory, smtp}; SMTP from `BERLIN_EVENTS_SMTP_HOST/PORT/USERNAME/PASSWORD/TLS` (starttls/ssl/none); sender `BERLIN_EVENTS_EMAIL_FROM(_NAME)`.
- `send_invite_email` / `send_password_reset_email`: plain-text `EmailMessage`, `async with config.provide_service()`; callers catch `EmailError` — a failed send never fails the request.
- `_absolute_url(request, base_url, path)`: configured `BERLIN_EVENTS_BASE_URL` else `request.base_url` (app sits behind Caddy in prod).
- Tests: env matrix; outbox assertions (recipient, URL in body).

### Stage 5 — Invites
- `POST /admin/invites` (admin): validate role/email-not-taken; invalidate prior invites for email; create token; build URL; attempt email (catch `EmailError`); **always render the copyable invite URL** to the admin (only hash is stored — the URL exists only in this response; say so in UI copy, offer regenerate).
- `GET/POST /invites/{token:str}` (public, async+to_thread): validate (used/expired/missing → one generic "invalid or expired" page); form = read-only email, display name, password ×2 (min 10); create user with invite's role, mark token used, log in, redirect `/`. Standalone card page (invitee is anonymous), login-page style.
- Tests: happy path incl. role honored; expired/reused; existing-email rejected; outbox; email-failure still returns URL; non-admin → 403.

### Stage 6 — Password reset
- `GET/POST /password-reset` (public): request form; response **byte-identical** whether the email exists (assert `resp_a.text == resp_b.text` in tests); if existing+active: invalidate prior reset tokens, create (2h TTL), send email (swallow errors). Login page gets "Forgot password?" link.
- `GET/POST /password-reset/{token:str}`: validate → new-password form → `update_user(password_hash=...)`, mark used, redirect `/login?reset=1` (no auto-login).
- No rate limiting yet (identical-response blocks enumeration; single-instance, low traffic) — noted follow-up.
- Tests: identical bodies; old password stops working / new works; single-use + expiry; inactive user sends nothing.

### Stage 7 — Account page + per-user settings
- `GET/POST /account` (`requires_user`, shell page): `action` discriminator form (matches venue-approval pattern): profile (display name), password (verify current first), preferences (`default_table_size` override, empty = site default).
- `_get_default_table_size(store, user=None)` (`webapp.py:1387`): user override → global setting → constant; update call sites (index ~594, settings, `_event_listing_data`), passing `request.scope.get("user")`.
- Tests: name change reflected; password change gated on current; per-user page size isolated between two clients; anonymous redirected.

### Stage 8 — Admin user management + actor logging
- `GET /admin/users` (admin, shell page, linked from /settings — nav tabs unchanged): users table (email, name, role, active, last login) + pending invites (regenerate → fresh URL, revoke).
- POSTs (admin, async+to_thread, CSRF, redirect-with-notice per /settings conventions): `.../role`, `.../deactivate`, `.../reactivate`, `.../reset-link` (copyable URL + email attempt), `/admin/invites`, `/admin/invites/{id}/revoke`. Self-deactivation/self-demotion blocked (removes "last admin" failure class).
- Actor logging: no audit seam exists (verified — `audit_log` has no actor column; approval handlers write no audit rows). Add explicit `store.log(..., context={"actor": user.email, ...})` calls in approve_venue/approve_artist and admin POSTs. Schema-level editorial audit = follow-up.
- Tests: role change effective on target's next request (proves per-request load); deactivate → immediately anonymous; self-lockout blocked; 403s for user/editor; reset-link URL works end-to-end.

### Stage 9 — CLI bootstrap
- `berlin-events users create-admin --database ...` (prompts, hidden+confirmed password; dup email → non-zero exit) and `users list` (rich Table, matches `venues review` style). Tests via `CliRunner` with `input=`.

### Stage 10 — Cleanup, docs, deploy
- Sweep: zero references to `BERLIN_EVENTS_EDITOR_PASSWORD` / `_require_editor` / `_SESSION_EDITOR_KEY` / password-derived CSRF secret remain.
- `deploy/berlin-events-{production,development}.service`: add `EnvironmentFile=` (e.g. `%h/.config/berlin-events/web.env`) for secrets.
- New `docs/user_accounts.md` with env-var table + bootstrap runbook (deploy → `users create-admin` on host → log in → invite others):

| Variable | Required | Notes |
|---|---|---|
| `BERLIN_EVENTS_SECRET_KEY` | prod: yes | CSRF; startup fails without it in production |
| `BERLIN_EVENTS_BASE_URL` | prod: yes | absolute invite/reset links |
| `BERLIN_EVENTS_EMAIL_BACKEND` | no (console) | console / memory / smtp |
| `BERLIN_EVENTS_SMTP_*` | smtp only | HOST/PORT/USERNAME/PASSWORD/TLS(starttls,ssl,none) |
| `BERLIN_EVENTS_EMAIL_FROM(_NAME)` | recommended | sender identity |
| `BERLIN_EVENTS_EDITOR_PASSWORD` | **removed** | delete from env files |

- Also save this plan to `docs/superpowers/plans/2026-08-01-user-accounts.md` (repo convention, cf. the fahrplan plan) at implementation start.

## Risks / gotchas (all verified in code)

1. **Litestar 2.24 shared-path bug** (comments at `webapp.py:839-842`): every new GET/POST pair sharing a path must be `async def` + `to_thread.run_sync`, never `sync_to_thread=True`. New pure handlers must be added to the `pure_handlers` set in `test_webapp.py:1987`.
2. **`atlas.sum`** must be regenerated after hand-editing the migration or the entire suite fails at `EventStore.__init__`.
3. **`connection.user` raises when scope lacks "user"** — always `scope.get("user")`; excluded paths must never touch `request.user`.
4. **`state=State({"store": ...})` is the enabling move** for the minimal test ripple — without it all ~40 `_login` call sites need changes.
5. **Argon2 cost in tests** — cheap-hasher autouse fixture keeps the suite fast; keep one real-hasher test.
6. **Raw tokens shown exactly once** (hash-only storage) — admin UI must offer regenerate, never re-display.
7. **Session-id fixation on login**: litestar server-side sessions don't rotate ids on `set_session`; mitigated by httponly/samesite=lax; documented limitation, don't patch private API.
8. **403 handler double duty** (roles + CSRF) — keep body generic.
9. **FileStore path from database path**, not CWD (prod `WorkingDirectory` is the replaced-on-deploy `releases/current`).

## Verification

- Per stage: `just tests`, `just typecheck`, `just lint`.
- End-to-end after Stage 10: create tmp DB → `berlin-events users create-admin` → `berlin-events web --environment development` → in browser: log in as admin, create invite (console backend prints email), open invite URL in a second/private session, accept, verify role=user sees no approvals tab and gets 403 on `/settings`; promote to editor via `/admin/users`, verify approvals work on next request; run password-reset flow; set per-user table size and confirm it only affects that user; restart the server and confirm the session survives (FileStore).
- Existing regression suite (~214 tests incl. `test_webapp.py`'s thread-discipline and CSRF tests) must stay green throughout.
