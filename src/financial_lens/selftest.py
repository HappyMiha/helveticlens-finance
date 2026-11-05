"""`FinancialLens --self-test [screenshot.png]`: proves a packaged build works on this machine.

Runs in a temporary data folder: starts the embedded PostgreSQL, OCRs a rendered
invoice with the bundled Tesseract, decodes a QR-bill, reads a PDF, imports a
bank statement, reconciles, and opens the main window offscreen.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from datetime import date

CAMT = b"""<?xml version="1.0"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>
<Ntry><Amt Ccy="CHF">184.50</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-27</Dt></BookgDt><AcctSvcrRef>S1</AcctSvcrRef>
<NtryDtls><TxDtls><RltdPties><Cdtr><Nm>Elektrizitaetswerk Limmattal</Nm></Cdtr></RltdPties></TxDtls></NtryDtls></Ntry>
</Stmt></BkToCstmrStmt></Document>"""


def _invoice() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    from pathlib import Path

    font = ImageFont.truetype(str(Path(__file__).parent / "assets" / "DejaVuSans.ttf"), 30)
    img = Image.new("RGB", (1240, 1100), "white")
    d = ImageDraw.Draw(img)
    for i, t in enumerate(["Elektrizitätswerk Limmattal AG", "Rechnung Nr. 4471", "Rechnungsdatum: 12.10.2026",
                           "Netznutzung CHF 71.30", "Energie CHF 99.40", "MWST 8.1% CHF 13.80",
                           "Total zu bezahlen CHF 184.50", "Zahlbar bis 30.10.2026"]):
        d.text((80, 80 + i * 70), t, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def run(screenshot: str | None = None) -> int:
    report: dict = {"platform": sys.platform}
    # Not mkdtemp: its restrictive Windows ACL stops PostgreSQL's initdb from using the folder.
    import uuid

    tmp = os.path.join(tempfile.gettempdir(), "fl-selftest-" + uuid.uuid4().hex[:8])
    os.makedirs(tmp)
    os.environ["FL_DATA"] = tmp
    os.environ.pop("FL_DSN", None)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from . import local_db
        from .extract import ocr
        from .service import FinancialLens

        report["engines"] = ocr.available()
        lens = FinancialLens(local_db.dsn(), local_db.data_dir())
        lens.migrate()
        lens.open_organization()
        report["database"] = lens.db.execute("SELECT version()").fetchone()["version"].split(",")[0]
        res = lens.ingest(_invoice(), "invoice.png")
        op = lens.operation_detail(res.operation_ids[0]) if res.operation_ids else {}
        ex = lens.db.execute("SELECT engine, left(text, 300) AS text FROM extractions ORDER BY created_at DESC LIMIT 1").fetchone()
        report["ocr"] = {"amount": op.get("amount"), "category": op.get("category_path"), "messages": res.messages,
                         "engine": ex["engine"] if ex else None, "text": ex["text"] if ex else None}
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument.new()
        pdf.new_page(200, 200)
        buf = io.BytesIO()
        pdf.save(buf)
        report["pdf"] = ocr._pdf(buf.getvalue()).engine
        import qrcode

        q = io.BytesIO()
        qrcode.make("SPC\n0200\n1").save(q, "PNG")
        from PIL import Image

        report["qr"] = ocr.decode_qr(Image.open(io.BytesIO(q.getvalue())).convert("RGB"))[:1]
        lens.ingest(CAMT, "camt.xml")
        report["reconciled"] = lens.operation_detail(res.operation_ids[0])["verification"] if res.operation_ids else None
        from PySide6.QtWidgets import QApplication

        from .desktop.main import MainWindow

        app = QApplication.instance() or QApplication([])
        w = MainWindow(lens, today=date(2026, 10, 31))
        w.resize(1280, 800)
        app.processEvents()
        report["window_expenses"] = w.kpi["expenses"].text()
        # The phone pairing path: HTTPS server with the pinned certificate, pairing offer, two-step dialog.
        import socket
        import ssl
        import hashlib
        import time

        from .api import mobile_v1
        from .desktop.main import PairDialog

        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            os.environ["FL_MOBILE_PORT"] = str(sk.getsockname()[1])
        port = w._ensure_lan_server()
        served = None
        for _ in range(100):
            try:
                served = hashlib.sha256(ssl.PEM_cert_to_DER_cert(ssl.get_server_certificate(("127.0.0.1", port)))).hexdigest()
                break
            except OSError:
                app.processEvents()
                time.sleep(0.2)
        offer = mobile_v1.create_offer(lens, f"127.0.0.1:{port}", w._tls_fp, ("upload", "read"))
        PairDialog(w, offer["uri"])
        report["pairing"] = {"https": served is not None, "pinned_matches": served == w._tls_fp}
        w._server.should_exit = True
        if screenshot:
            w.grab().save(screenshot)
        lens.close()
        ok = (report["ocr"]["amount"] == "184.50" and report["reconciled"] == "confirmed"
              and report["qr"] == ["SPC\n0200\n1"] and report["window_expenses"] == "CHF 184.50" and report.get("pairing", {}).get("pinned_matches") is True)
    except Exception as exc:  # report, do not hide
        import traceback

        report["error"] = traceback.format_exc()[-2000:]
        ok = False
    report["ok"] = ok
    text = json.dumps(report, indent=2, default=str)
    if screenshot:  # windowed builds on Windows have no console: always leave a report file
        with open(os.path.splitext(screenshot)[0] + ".json", "w", encoding="utf-8") as fh:
            fh.write(text)
    if sys.stdout is not None:
        print(text)
    return 0 if ok else 1
