# Builds the Linux AppImage on glibc 2.28 (AlmaLinux 8) so it runs on most current distributions.
FROM almalinux:8.10
RUN dnf install -y epel-release && dnf install -y --setopt=install_weak_deps=False \
      python3.12 python3.12-devel python3.12-pip gcc \
      desktop-file-utils tesseract tesseract-langpack-deu tesseract-langpack-fra tesseract-langpack-ita file \
      mesa-libEGL mesa-libGL libxkbcommon libxkbcommon-x11 fontconfig dbus-libs glib2 \
      xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-cursor \
    && dnf clean all
RUN python3.12 -m pip install --upgrade pip && python3.12 -m pip install --no-cache-dir "pyinstaller>=6.11"
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN python3.12 -m pip install --no-cache-dir ".[api,db,security,ocr,embedded]" "PySide6-Essentials>=6.8" openpyxl
RUN curl -fsSL -o /usr/share/tesseract/tessdata/osd.traineddata https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0/osd.traineddata
RUN curl -fsSL -o /usr/local/bin/appimagetool \
      https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-x86_64.AppImage \
    && chmod +x /usr/local/bin/appimagetool
