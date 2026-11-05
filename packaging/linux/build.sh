#!/usr/bin/env bash
# Build dist/FinancialLens-x86_64.AppImage inside Docker. Usage: packaging/linux/build.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
docker build -t financial-lens-linux-builder -f packaging/linux/Dockerfile .
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/work -w /work financial-lens-linux-builder bash -c '
  set -e
  export FL_TESSDATA=/usr/share/tesseract/tessdata
  python3.12 -m PyInstaller --noconfirm --clean --distpath build/pyi/dist --workpath build/pyi/work packaging/financial-lens.spec
  rm -rf build/AppDir && mkdir -p build/AppDir/usr
  cp -a build/pyi/dist/FinancialLens build/AppDir/usr/lib-fl
  cat > build/AppDir/AppRun <<"RUN"
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib-fl/FinancialLens" "$@"
RUN
  chmod +x build/AppDir/AppRun
  cp packaging/icon.png build/AppDir/financial-lens.png
  cat > build/AppDir/financial-lens.desktop <<"DESK"
[Desktop Entry]
Type=Application
Name=Financial Lens
Comment=Evidence-first, offline-first finance
Exec=FinancialLens
Icon=financial-lens
Categories=Office;Finance;
DESK
  mkdir -p dist
  ARCH=x86_64 appimagetool --appimage-extract-and-run --no-appstream build/AppDir dist/FinancialLens-x86_64.AppImage
'
ls -lh dist/
