#!/usr/bin/env sh

set -eu

npx --yes --package @commitlint/cli --package @commitlint/config-conventional \
  commitlint --edit "$1"
