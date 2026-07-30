# Caddy reverse proxy deployment (Cloudflare DNS-01)

This project is deployed behind Caddy for HTTPS termination and host-based reverse proxying.

## Scope

- Host: `agent.ada.x74.pw` → Hermes backend `100.117.164.104:9119`
- Host: `berlin-events.ada.x74.pw` → production web app `127.0.0.1:8000`
- Host: `berlin-events-dev.ada.x74.pw` → development web app `127.0.0.1:8001`
- TLS: automated via ACME with Cloudflare DNS-01
- Secret handling: token is loaded from `/etc/caddy/cloudflare.env`, not committed to config files

## Caddy configuration ownership

`/etc/caddy/Caddyfile` is a shared, complete host configuration that also serves other applications.
The repository `Caddyfile` is the Berlin Events reference fragment; do **not** copy it wholesale
onto the shared system configuration. Merge its Berlin Events host blocks into
`/etc/caddy/Caddyfile`, validate the complete configuration, then reload Caddy.

```caddy
{
    acme_dns cloudflare {
        api_token {env.CLOUDFLARE_API_TOKEN}
    }
}

# Hermes dashboard
agent.ada.x74.pw {
    reverse_proxy 100.117.164.104:9119
}

# Berlin Events production webapp
berlin-events.ada.x74.pw {
    reverse_proxy 127.0.0.1:8000
}

# Berlin Events development webapp
berlin-events-dev.ada.x74.pw {
    reverse_proxy 127.0.0.1:8001
}
```

> Keep only host-based routing blocks here. No path-based mounting/mapping in this file.

## Secret/config files

### `/etc/caddy/cloudflare.env`

```bash
# /etc/caddy/cloudflare.env
CLOUDFLARE_API_TOKEN=REDACTED
```

Permissions should be strict:

```bash
sudo chmod 600 /etc/caddy/cloudflare.env
sudo chown root:root /etc/caddy/cloudflare.env
```

### Environment file drop-in

```ini
# /etc/systemd/system/caddy.service.d/10-env.conf
[Service]
EnvironmentFile=/etc/caddy/cloudflare.env
```

## Caddy service unit

```ini
# /etc/systemd/system/caddy.service
[Unit]
Description=Caddy
Documentation=https://caddyserver.com/docs/
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy-cloudflare run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy-cloudflare reload --config /etc/caddy/Caddyfile --force
KillMode=process
KillSignal=SIGQUIT
TimeoutStopSec=5s
Restart=on-failure
RestartSec=2s
LimitNOFILE=1048576
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
WorkingDirectory=/var/lib/caddy

[Install]
WantedBy=multi-user.target
```

## Optional: custom Caddy binary drop-in

When using the Cloudflare DNS plugin, `/usr/local/bin/caddy-cloudflare` is used as the runtime binary:

```ini
# /etc/systemd/system/caddy.service.d/20-custom-binary.conf
[Service]
ExecStart=
ExecStart=/usr/local/bin/caddy-cloudflare run --environ --config /etc/caddy/Caddyfile
ExecReload=
ExecReload=/usr/local/bin/caddy-cloudflare reload --config /etc/caddy/Caddyfile --force
```

## Deployment flow

```bash
# 1) Edit the matching Berlin Events host block in the shared configuration.
sudoedit /etc/caddy/Caddyfile

# 2) Reload validates and applies the complete configuration atomically.
sudo systemctl reload caddy

# 3) Confirm Caddy stayed healthy.
systemctl is-active caddy
```

## Deployment automation

Git hooks are kept under `.githooks/` and enabled per checkout with:

```bash
./scripts/install-git-hooks.sh
```

- Each regular commit restarts only `berlin-events-development.service`.
- Creating a new Git tag restarts `berlin-events-webfrontend.service`, making the
  tagged checkout the production deployment.
- Moving or deleting an existing tag does not restart production.

The production and development services are intentionally independent; the development
service continues to use its persistent database at
`~/.local/share/berlin-events-explorer/development/events.sqlite`.

## Useful verification commands

```bash
systemctl is-enabled caddy.service
systemctl is-active caddy.service
systemctl show -p EnvironmentFiles caddy.service --value
systemctl status caddy --no-pager
journalctl -u caddy --no-pager -n 80
/usr/local/bin/caddy-cloudflare list-modules | grep -i cloudflare
```

```bash
curl -I https://agent.ada.x74.pw/
curl -I https://berlin-events.ada.x74.pw/
```

## Troubleshooting

- If startup fails with `connection denied: API token` / `API token '' appears invalid`, verify:
  - file `/etc/caddy/cloudflare.env` exists and is readable by root/systemd
  - token value is present and not quoted
  - token permissions are not too restrictive for the service startup path
- If Caddy is not restartable and says `Unit caddy.service is masked`, run:
  - `sudo systemctl unmask caddy.service`
  - `sudo systemctl daemon-reload`
  - `sudo systemctl restart caddy`
