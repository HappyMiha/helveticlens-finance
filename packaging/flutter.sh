#!/usr/bin/env bash
# Run a Flutter command for mobile/ in the pinned SDK container. Usage: packaging/flutter.sh flutter build apk
set -euo pipefail
cd "$(dirname "$0")/.."
docker volume create fl-pub-cache >/dev/null
docker volume create fl-gradle-cache >/dev/null
KEYS=()
[ -d "$HOME/.config/financial-lens/android" ] && KEYS=(-v "$HOME/.config/financial-lens/android:/k:ro")  # release signing key, outside the repo
docker run --rm -v "$PWD":/w -w /w/mobile -v fl-pub-cache:/root/.pub-cache -v fl-gradle-cache:/root/.gradle "${KEYS[@]}" \
  ghcr.io/cirruslabs/flutter:3.35.7 bash -c "$* ; rc=\$?; chown -R $(id -u):$(id -g) /w/mobile; exit \$rc"
