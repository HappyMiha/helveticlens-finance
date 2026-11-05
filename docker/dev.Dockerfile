# Development and test image: local OCR, PostgreSQL client, Qt offscreen.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-ita \
      poppler-utils libzbar0 fonts-dejavu-core \
      libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
      "fastapi>=0.115" "uvicorn>=0.32" "python-multipart>=0.0.12" httpx \
      "psycopg[binary]>=3.2" pillow pyzbar "qrcode>=7.4" pytest openpyxl \
      "PySide6-Essentials>=6.8" "cryptography>=43" "pillow-heif>=0.18" pypdfium2 zxing-cpp pgserver
ENV PYTHONPATH=/app/src QT_QPA_PLATFORM=offscreen
