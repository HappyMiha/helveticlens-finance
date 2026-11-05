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
from typing import Optional


@dataclass
class Word:
    text: str
    x0: float  # horizontal position as a fraction of the page width (0..1)
    x1: float


@dataclass
class Line:
    number: int  # 1-based, per document
    page: int
    text: str
    confidence: float | None = None  # 0..1 for OCR, None for a text layer
    words: list = field(default_factory=list)  # list[Word], left to right, for column analysis


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
        flatten_light(image.convert("L")).save(src)
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
        grouped[key].append((cols[11], max(float(cols[10]), 0.0) / 100,
                             int(cols[6]) / image.width, (int(cols[6]) + int(cols[8])) / image.width))
    lines = []
    for i, key in enumerate(order):
        words = grouped[key]
        lines.append(Line(start + i, page, " ".join(w[0] for w in words),
                          round(sum(w[1] for w in words) / len(words), 3),
                          [Word(w[0], w[2], w[3]) for w in words]))
    return lines


def recognise(data: bytes, media_type: str) -> TextResult:
    if media_type == "application/pdf":
        return _pdf(data)
    if media_type in IMAGE_TYPES:
        image = _load_image(data)
        result = TextResult(_tesseract_version())
        result.qr_payloads = decode_qr(image)
        image, notes = straighten(image)
        result.lines = _ocr_image(image, 1, 1)
        result.engine += "".join(f"+{n}" for n in notes)
        return result
    if media_type.startswith("text/"):
        text = data.decode("utf-8", errors="replace")
        return TextResult("text", [Line(i + 1, 1, t) for i, t in enumerate(text.splitlines()) if t.strip()])
    raise ValueError(f"No text engine for {media_type}")


def flatten_light(gray):
    """Even out shadows and dim light: divide the page by its own blurred background, so ink stays dark
    and the paper becomes evenly white. Applied only when the lighting is uneven."""
    from PIL import ImageChops, ImageFilter, ImageOps

    small = gray.resize((max(gray.width // 8, 1), max(gray.height // 8, 1)))
    bg_small = small.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(6))
    lo, hi = bg_small.getextrema()
    if hi - lo < 45 and hi > 170:
        return gray  # evenly lit: leave it alone
    bg = bg_small.resize(gray.size, resample=2)
    ink = ImageChops.subtract(bg, gray)  # how much darker than the paper around it
    return ImageOps.autocontrast(ImageOps.invert(ink), cutoff=1)


def _quality(lines: list[Line]) -> float:
    """How readable an OCR result is: confident, real words count; noise does not."""
    import re

    score = 0.0
    for l in lines:
        for w in (l.words or []):
            t = w.text
            if len(t) >= 3 and re.fullmatch(r"[A-Za-zÄÖÜäöüÉÈÀéèàçß0-9.,'’:/%()-]+", t):
                score += 1
        score += (l.confidence or 0) * 0.5
    return score


def _deskew(image):
    """Small rotations (crooked photos and scans): choose the angle at which text rows are sharpest
    (projection profile), using only Pillow."""
    from PIL import ImageOps

    small = ImageOps.grayscale(image)
    small.thumbnail((900, 900))
    small = ImageOps.autocontrast(small).point(lambda v: 255 if v < 140 else 0)  # ink = white

    def sharpness(angle: float) -> float:
        r = small.rotate(angle, expand=False, fillcolor=0)
        col = r.resize((1, r.height), resample=1)  # 1 = BOX: the mean of every row
        vals = list(col.getdata())
        m = sum(vals) / len(vals)
        return sum((v - m) ** 2 for v in vals)

    best = max((a / 2 for a in range(-24, 25)), key=sharpness)  # -12° … +12° in 0.5° steps
    best = max((best + d / 10 for d in range(-5, 6)), key=sharpness)
    return best


def straighten(image) -> tuple:
    """Upright and level before OCR: try the four orientations when the first reading is poor,
    then correct small skew. Returns the image and notes for provenance."""
    notes = []
    probe = image.copy()
    probe.thumbnail((1400, 1400))
    osd = _osd_rotation(probe)
    if osd:
        image = image.rotate(osd, expand=True)
        probe = _probe(image)
        notes.append(f"rotated{osd}")
    first = _ocr_image(probe, 1, 1)
    q0 = _quality(first)
    words = sum(len(l.words) for l in first)
    if osd is None and (words == 0 or q0 / max(words, 1) < 0.85):
        best_angle, best_q = 0, q0
        for angle in (180, 90, 270):
            q = _quality(_ocr_image(probe.rotate(angle, expand=True), 1, 1))
            if q > best_q * 1.6:
                best_angle, best_q = angle, q
        if best_angle:
            image = image.rotate(best_angle, expand=True)
            notes.append(f"rotated{best_angle}")
    angle = _deskew(image)
    if abs(angle) >= 0.7:
        # keep the correction only if it actually reads better (pictures and QR codes can fool the profile)
        before = q0 if not notes else _quality(_ocr_image(_probe(image), 1, 1))
        turned = image.rotate(angle, expand=True, fillcolor="white", resample=3)
        if _quality(_ocr_image(_probe(turned), 1, 1)) > before * 1.03:
            image = turned
            notes.append(f"deskew{angle:+.1f}")
    return image, notes


def _osd_rotation(image) -> Optional[int]:
    """Tesseract's orientation detection (osd.traineddata). Returns the counter-clockwise rotation to
    apply (0/90/180/270), or None when OSD is unavailable or unsure."""
    import re

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "p.png"
        image.convert("L").save(src)
        try:
            out = subprocess.run([tesseract_cmd(), str(src), "stdout", "--psm", "0"], capture_output=True, text=True,
                                 timeout=60, env=_tess_env())
        except Exception:
            return None
    m = re.search(r"Rotate: (\d+)", out.stdout)
    c = re.search(r"Orientation confidence: ([\d.]+)", out.stdout)
    if not m or not c or float(c.group(1)) < 1.5:
        return None
    rot = int(m.group(1)) % 360
    # Tesseract reports the clockwise rotation needed; PIL rotates counter-clockwise.
    return (360 - rot) % 360 if rot else 0


def _probe(image):
    p = image.copy()
    p.thumbnail((1400, 1400))
    return p


def _pdf_lines(page, page_no: int, start: int) -> list[Line]:
    """Rebuild lines and words from pdfium character boxes, keeping horizontal positions
    so tables (statements, payslips) can be read by column."""
    tp = page.get_textpage()
    width = page.get_width() or 1
    chars = []
    for i in range(tp.count_chars()):
        ch = tp.get_text_range(i, 1)
        if not ch or ch in "\r\n":
            continue
        l, b, r, t = tp.get_charbox(i, loose=True)  # loose: font-height boxes, so a line has one centre
        chars.append((ch, l, r, (b + t) / 2, max(t - b, 1)))
    # group into lines by vertical centre (PDF y grows upwards)
    rows: list[list] = []
    for c in sorted(chars, key=lambda c: (-c[3], c[1])):
        if rows and abs(rows[-1][0][3] - c[3]) <= 0.45 * max(c[4], rows[-1][0][4]):
            rows[-1].append(c)
        else:
            rows.append([c])
    lines = []
    for row in rows:
        row.sort(key=lambda c: c[1])
        words, cur, x0, x1 = [], "", None, None
        avg = sum(c[2] - c[1] for c in row) / len(row) or 1
        for ch, l, r, _, _ in row:
            gap = l - x1 if x1 is not None else 0
            if ch.isspace() or (cur and gap > 0.6 * avg):
                if cur:
                    words.append(Word(cur, x0 / width, x1 / width))
                cur, x0, x1 = ("", None, None) if ch.isspace() else (ch, l, r)
                continue
            if not cur:
                x0 = l
            cur += ch
            x1 = r
        if cur:
            words.append(Word(cur, x0 / width, x1 / width))
        if words:
            # big gaps become two spaces, so column breaks stay visible in the text too
            text = ""
            for k, w in enumerate(words):
                if k:
                    text += "  " if (w.x0 - words[k - 1].x1) > 0.03 else " "
                text += w.text
            lines.append(Line(start + len(lines), page_no, text, None, words))
    return lines


def _pdf(data: bytes) -> TextResult:
    """Text layer via pdfium (with word positions); pages rendered for QR codes and,
    without a text layer, for OCR."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    lines: list[Line] = []
    for p in range(len(pdf)):
        lines.extend(_pdf_lines(pdf[p], p + 1, len(lines) + 1))
    qr: list[str] = []
    ocr_lines: list[Line] = []
    for p in range(min(len(pdf), 8)):
        image = pdf[p].render(scale=200 / 72).to_pil().convert("RGB")
        qr.extend(decode_qr(image))
        if len(lines) < 3:
            ocr_lines.extend(_ocr_image(image, p + 1, len(ocr_lines) + 1))
    pdf.close()
    if len(lines) < 3 and ocr_lines:
        return TextResult(_tesseract_version() + "+pdfium", ocr_lines, qr)
    return TextResult("pdfium", lines, qr)
