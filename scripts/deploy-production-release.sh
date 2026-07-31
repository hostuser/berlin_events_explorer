#!/usr/bin/env sh

# Deploy exactly one immutable, locally available Git tag to production.
set -eu

TAG="${1:?usage: deploy-production-release.sh <tag>}"
case "$TAG" in
  *[!0-9A-Za-z._-]* | '')
    printf '%s\n' "Invalid release tag: $TAG" >&2
    exit 2
    ;;
esac

REPO_ROOT="$(git rev-parse --show-toplevel)"
TAG_COMMIT="$(git -C "$REPO_ROOT" rev-parse --verify "${TAG}^{commit}")"
if ! git -C "$REPO_ROOT" tag --points-at "$TAG_COMMIT" | grep -Fx "$TAG" >/dev/null; then
  printf '%s\n' "Production releases must be Git tags: $TAG" >&2
  exit 2
fi

RELEASES_DIR="$HOME/.local/share/berlin-events-explorer/releases"
RELEASE_DIR="$RELEASES_DIR/$TAG"
RELEASE_CURRENT="$RELEASES_DIR/current"
UNITS_DIR="$HOME/.config/systemd/user"
UV="${UV:-$HOME/.local/bin/uv}"
SYSTEMCTL="/usr/bin/systemctl"

mkdir -p "$RELEASES_DIR" "$UNITS_DIR"
if [ -e "$RELEASE_DIR" ]; then
  RELEASE_COMMIT="$(git -C "$RELEASE_DIR" rev-parse HEAD)"
  if [ "$RELEASE_COMMIT" != "$TAG_COMMIT" ]; then
    printf '%s\n' "Existing release directory does not match tag $TAG" >&2
    exit 2
  fi
else
  git -C "$REPO_ROOT" worktree add --detach "$RELEASE_DIR" "$TAG_COMMIT"
fi

if ! git -C "$RELEASE_DIR" tag --points-at HEAD | grep -Fx "$TAG" >/dev/null; then
  printf '%s\n' "Release checkout is not at tag $TAG" >&2
  exit 2
fi
if [ -n "$(git -C "$RELEASE_DIR" status --porcelain)" ]; then
  printf '%s\n' "Release checkout is dirty: $RELEASE_DIR" >&2
  exit 2
fi

"$UV" sync --directory "$RELEASE_DIR" --frozen --no-dev
systemd-analyze --user verify \
  "$RELEASE_DIR/deploy/berlin-events-production.service" \
  "$RELEASE_DIR/deploy/berlin-events-worker-production.service" \
  "$RELEASE_DIR/deploy/berlin-events-worker-production.timer"

NEW_CURRENT="${RELEASE_CURRENT}.new.$$"
ln -s "$RELEASE_DIR" "$NEW_CURRENT"
mv -Tf "$NEW_CURRENT" "$RELEASE_CURRENT"

install -Dm644 "$RELEASE_DIR/deploy/berlin-events-production.service" \
  "$UNITS_DIR/berlin-events-webfrontend.service"
install -Dm644 "$RELEASE_DIR/deploy/berlin-events-worker-production.service" \
  "$UNITS_DIR/berlin-events-worker-production.service"
install -Dm644 "$RELEASE_DIR/deploy/berlin-events-worker-production.timer" \
  "$UNITS_DIR/berlin-events-worker-production.timer"
"$SYSTEMCTL" --user daemon-reload
"$SYSTEMCTL" --user enable --now berlin-events-worker-production.timer
"$SYSTEMCTL" --user restart berlin-events-webfrontend.service

printf '%s\n' "Production deployed from tag $TAG ($TAG_COMMIT)"
