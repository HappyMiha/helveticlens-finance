#!/usr/bin/env bash
# Build/test the native Android app in the pinned SDK container. Usage: packaging/android.sh ./gradlew assembleRelease
set -euo pipefail
cd "$(dirname "$0")/.."
KEYS=()
[ -d "$HOME/.config/financial-lens/android" ] && KEYS=(-v "$HOME/.config/financial-lens/android:/k:ro")
docker run --rm -v "$PWD":/w -w /w/android -v fl-gradle-cache:/root/.gradle "${KEYS[@]}" \
  ghcr.io/cirruslabs/flutter:3.35.7 bash -c "$* ; rc=\$?; chown -R $(id -u):$(id -g) /w/android; exit \$rc"
