#!/usr/bin/env sh

set -eu

# Backward-compatible entry point for the development post-commit workflow.
exec "$(dirname "$0")/restart-development-service.sh"
