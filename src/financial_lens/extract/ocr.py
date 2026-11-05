"""Local text recognition. Nothing here uses the network.

Engines: pdftotext for PDFs with a text layer, Tesseract for images and
scanned PDFs, zbar for QR codes (Swiss QR-bill). Each result keeps line
numbers so every extracted value can point at its location.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Line:
    number: int  # 1-based, per document
    page: int
    text: str
    confidence: float | None = None  # 0..1 for OCR, None for a text layer


@dataclass
class TextResult:
    engine: str
    lines: list[Line] = field(default_factory=list)
    qr_payloads: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_confidence(self) -> float | None:
        values = [line.confidence for line in self.lines if line.confidence is not None]
        return sum(values) / len(values) if values else None


IMAGE_TYPES = {"image/jpeg", "image/png", "image/tiff", "image/webp", "image/heic", "image/heif", "image/bmp"}
LANGS = "deu+fra+ita+eng"


def tesseract_cmd() -> str:
    """Tesseract shipped inside the installer, an explicit FL_TESSERACT, or the system one."""
    import os
    import sys

    if os.environ.get("FL_TESSERACT"):
        return os.environ["FL_TESSERACT"]
    base = Path(getattr(sys, "_MEIPASS", "")) / "tesseract"
    exe = base / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
    if exe.exists():
        os.environ.setdefault("TESSDATA_PREFIX", str(base / "tessdata"))
        return str(exe)
    return "tesseract"


def _tess_env() -> dict:
    """Environment for the bundled Tesseract: its libraries live next to the app's."""
    import os
    import sys

    env = dict(os.environ)
    base = getattr(sys, "_MEIPASS", None)
    if base:
        var = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
        if sys.platform != "win32":
            env[var] = os.pathsep.join(p for p in (base, str(Path(base) / "tesseract"), env.get(var, "")) if p)
    return env


def available() -> dict[str, bool]:
    import importlib.util

    return {"tesseract": shutil.which(tesseract_cmd()) is not None or Path(tesseract_cmd()).exists(),
            "pypdfium2": importlib.util.find_spec("pypdfium2") is not None,
            "zxingcpp": importlib.util.find_spec("zxingcpp") is not None}


def _tesseract_version() -> str:
    try:
        out = subprocess.run([tesseract_cmd(), "--version"], capture_output=True, text=True, timeout=10, env=_tess_env())
        return "tesseract-" + (out.stdout or out.stderr).split()[1]
    except Exception:
        return "tesseract"


def _load_image(data: bytes):
    from PIL import Image, ImageOps

    try:  # HEIC support is optional
        import pillow_heif  # type: ignore

        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)
    return image.convert("RGB")


def decode_qr(image) -> list[str]:
    try:  # zxing-cpp: self-contained wheels on Linux, Windows and macOS
        import zxingcpp

        return [r.text for r in zxingcpp.read_barcodes(image) if r.text]
    except ImportError:
        pass
    try:
        from pyzbar import pyzbar
    except Exception:
        return []
    payloads = []
    for symbol in pyzbar.decode(image):
        try:
            payloads.append(symbol.data.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return payloads


def _ocr_image(image, page: int, start: int) -> list[Line]:
    """Run Tesseract and rebuild lines from its TSV output with confidences."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "page.png"
        # Upscale small photos; Tesseract prefers ~300 dpi text height.
        if image.width < 1500:
            factor = 1500 / image.width
            image = image.resize((int(image.width * factor), int(image.height * factor)))
        image.convert("L").save(src)
        out = subprocess.run(
            [tesseract_cmd(), str(src), "stdout", "-l", LANGS, "--psm", "6", "tsv"],
            capture_output=True, text=True, timeout=180, env=_tess_env(),
        )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "tesseract failed")
    grouped: dict[tuple, list[tuple[str, float]]] = {}
    order: list[tuple] = []
    for row in out.stdout.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5" or not cols[11].strip():
            continue
        key = (int(cols[2]), int(cols[3]), int(cols[4]))  # block, paragraph, line
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append((cols[11], max(float(cols[10]), 0.0) / 100))
    lines = []
    for i, key in enumerate(order):
        words = grouped[key]
        lines.append(Line(start + i, page, " ".join(w for w, _ in words),
                          round(sum(c for _, c in words) / len(words), 3)))
    return lines


def recognise(data: bytes, media_type: str) -> TextResult:
    if media_type == "application/pdf":
        return _pdf(data)
    if media_type in IMAGE_TYPES:
        image = _load_image(data)
        result = TextResult(_tesseract_version())
        result.qr_payloads = decode_qr(image)
        result.lines = _ocr_image(image, 1, 1)
        return result
    if media_type.startswith("text/"):
        text = data.decode("utf-8", errors="replace")
        return TextResult("text", [Line(i + 1, 1, t) for i, t in enumerate(text.splitlines()) if t.strip()])
    raise ValueError(f"No text engine for {media_type}")


def _pdf(data: bytes) -> TextResult:
    """Text layer via pdfium; pages rendered for QR codes and, without a text layer, for OCR."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    lines: list[Line] = []
    n = 1
    for p in range(len(pdf)):
        text = pdf[p].get_textpage().get_text_range()
        for raw in text.replace("\r", "").split("\n"):
            if raw.strip():
                lines.append(Line(n, p + 1, " ".join(raw.split())))
                n += 1
    qr: list[str] = []
    ocr_lines: list[Line] = []
    for p in range(min(len(pdf), 5)):
        image = pdf[p].render(scale=200 / 72).to_pil().convert("RGB")
        qr.extend(decode_qr(image))
        if len(lines) < 3:
            ocr_lines.extend(_ocr_image(image, p + 1, len(ocr_lines) + 1))
    pdf.close()
    if len(lines) < 3 and ocr_lines:
        return TextResult(_tesseract_version() + "+pdfium", ocr_lines, qr)
    return TextResult("pdfium", lines, qr)
