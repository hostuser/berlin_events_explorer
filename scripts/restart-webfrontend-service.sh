#!/usr/bin/env sh

set -eu

SERVICE="berlin-events-webfrontend.service"
SHELL="/usr/bin/systemctl"

if [ -x "$SHELL" ]; then
  "$SHELL" --user restart "$SERVICE" >/tmp/berlin-events-webfrontend-restart.log 2>&1 || \
    true
fi
