# Flutter SDK + Android emulator for end-to-end tests (needs /dev/kvm).
FROM ghcr.io/cirruslabs/flutter:3.35.7
RUN yes | sdkmanager --sdk_root=$ANDROID_HOME "emulator" "system-images;android-34;google_apis;x86_64" >/dev/null \
 && echo no | avdmanager create avd -n fl -k "system-images;android-34;google_apis;x86_64" -d pixel_6
