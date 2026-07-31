---
name: verify
description: Build, launch, and drive Berlin Events Explorer to verify changes end-to-end at the real HTTP surface.
---

# Verifying Berlin Events Explorer

## Launch

```bash
V=$(mktemp -d)   # or the session scratchpad
uv run berlin-events users create-admin --database "$V/events.sqlite" \
  --email you@example.test --display-name You   # prompts password twice via stdin
BERLIN_EVENTS_SECRET_KEY=verify-secret BERLIN_EVENTS_EMAIL_BACKEND=console \
  nohup uv run berlin-events web --database "$V/events.sqlite" --port 8971 \
  --sync-interval-minutes 0 --environment development > "$V/server.log" 2>&1 &
curl -s http://127.0.0.1:8971/health   # {"status":"ok"}
```

- `--sync-interval-minutes 0` is required — otherwise the app syncs from the
  network on startup.
- `console` email backend prints invite/reset emails into `server.log`; grep
  `/invites/[A-Za-z0-9_-]*` or `/password-reset/[A-Za-z0-9_-]*` for the links.

## Driving authenticated flows with curl

CSRF is double-submit: GET any page into a cookie jar first, then send the
`csrftoken` cookie value back as the `x-csrftoken` header on POSTs:

```bash
curl -s -c jar http://127.0.0.1:8971/login -o /dev/null
T=$(grep -m1 csrftoken jar | awk '{print $7}')
curl -s -b jar -c jar -H "x-csrftoken: $T" \
  -d "email=you@example.test&password=..." http://127.0.0.1:8971/login
```

Roles: `user` (account page only), `editor` (+approvals, sync), `admin`
(+/settings, /admin/users). Sessions live in `<database>.sessions/` — kill and
relaunch the server against the same DB to prove cookie persistence.

## Flows worth driving

- login (wrong password must render the same "Invalid email or password.")
- invite create → grab URL from server.log → accept in a fresh jar → reuse
  must show "invalid or has expired"
- password reset: known vs unknown address responses must be byte-identical
- /account preferences: `default_table_size` shows up as `page_size=N` in the
  owner's nav links only
- actor logging: admin actions write `log` rows with `context.actor`; read via
  `EventStore(...).list_logs(level="info")`
