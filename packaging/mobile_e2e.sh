#!/usr/bin/env bash
# Android end-to-end test on an emulator against the e2e server container `fl-e2e-api`
# (start it with packaging/mobile_e2e_server.py). Needs /dev/kvm.
set -euo pipefail
cd "$(dirname "$0")/.."
DSN="host=127.0.0.1 port=55432 user=fl password=fl dbname=fl"
docker rm -f fl-emu >/dev/null 2>&1 || true
docker run -d --name fl-emu --device /dev/kvm --network host -v "$PWD":/w -w /w/${FL_APP:-android} \
  -v fl-pub-cache:/root/.pub-cache -v fl-gradle-cache:/root/.gradle financial-lens-android-emu \
  bash -c '$ANDROID_HOME/emulator/emulator -avd fl -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -no-snapshot' >/dev/null
trap 'docker exec fl-emu chown -R '"$(id -u):$(id -g)"' /w/android /w/mobile >/dev/null 2>&1; docker rm -f fl-emu >/dev/null' EXIT
docker exec fl-emu bash -c 'adb wait-for-device; for i in $(seq 1 150); do [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d "\r")" = 1 ] && exit 0; sleep 3; done; exit 1'
echo "emulator booted"
docker exec fl-emu bash -c './gradlew --no-daemon -q assembleDebug assembleDebugAndroidTest >/dev/null 2>&1' || true
URI=$(docker exec fl-e2e-api sh -c "python packaging/mobile_e2e_offer.py \"$DSN\" 10.0.2.2:8766 \$(cat /tmp/fl-data)")
echo "fresh one-time offer created"
docker exec -e FL_PAIR_URI="$URI" fl-emu bash -c \
  './gradlew --no-daemon -q connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.pairUri="$FL_PAIR_URI" 2>&1; rc=$?; adb logcat -d -s System.out:I | grep "E2E OK"; exit $rc' \
  | grep -vE '^\s*$' | tail -25
