#!/usr/bin/env sh

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
git -C "$REPO_ROOT" config core.hooksPath .githooks
printf '%s\n' "Git hooks enabled from $REPO_ROOT/.githooks"
