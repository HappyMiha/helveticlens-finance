FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-ita poppler-utils libzbar0 \
    && rm -rf /var/lib/apt/lists/* && useradd -u 10001 -m fl && mkdir -p /data && chown fl /data
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[api,db,security]" pillow pillow-heif pypdfium2 zxing-cpp openpyxl "qrcode>=7.4"
USER fl
ENV FL_DATA=/data
CMD ["sh", "-c", "export FL_DSN=\"$(cat ${FL_DSN_FILE:-/dev/null} 2>/dev/null || echo $FL_DSN)\"; exec financial-lens serve --host 0.0.0.0 --port 8765"]
