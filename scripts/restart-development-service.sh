#!/usr/bin/env sh

set -eu

SYSTEMCTL="/usr/bin/systemctl"
SERVICE="berlin-events-development.service"

if [ -x "$SYSTEMCTL" ]; then
  "$SYSTEMCTL" --user restart "$SERVICE" \
    >/tmp/berlin-events-development-restart.log 2>&1 || true
fi
