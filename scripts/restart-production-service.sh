#!/usr/bin/env sh

set -eu

SYSTEMCTL="/usr/bin/systemctl"
SERVICE="berlin-events-webfrontend.service"

if [ -x "$SYSTEMCTL" ]; then
  "$SYSTEMCTL" --user restart "$SERVICE" \
    >/tmp/berlin-events-webfrontend-restart.log 2>&1 || true
fi
