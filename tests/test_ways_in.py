"""More ways to bring documents in: HEIC photos, manual entry, e-mail, paired phones."""

import io
from datetime import date
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

from conftest import render_invoice_photo
from test_mvp_cycle import CAMT, INVOICE


def heic(jpg: bytes) -> bytes:
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.open(io.BytesIO(jpg)).save(buf, format="HEIF", quality=90)
    return buf.getvalue()


def test_iphone_heic_photo(lens):
    data = heic(render_invoice_photo(INVOICE, noise=False, tilt=0.5))
    res = lens.ingest(data, "IMG_0042.HEIC")
    assert lens.documents()[0]["media_type"] == "image/heic"
    op = lens.operation_detail(res.operation_ids[0])
    assert op["amount"] == "184.50" and op["category_path"] == ["Housing", "Electricity"]


class FakeIMAP:
    def __init__(self, messages):
        self.messages = messages
        self.readonly = None

    def login(self, user, password):
        assert password == "secret"

    def select(self, folder, readonly=False):
        self.readonly = readonly
        return "OK", [b"1"]

    def search(self, charset, criterion):
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.messages)))]

    def fetch(self, num, what):
        assert "PEEK" in what  # never marks messages as read
        return "OK", [(b"", self.messages[int(num) - 1].as_bytes())]

    def logout(self):
        pass


def mail(mid, subject, sender="rechnungen@ewz.ch", attach=None, body="", ctype="application/pdf"):
    m = EmailMessage()
    m["Message-ID"], m["Subject"], m["From"], m["Date"] = mid, subject, sender, "Thu, 05 Nov 2026 06:30:00 +0100"
    m.set_content(body or "See attachment.")
    if attach:
        maintype, subtype = ctype.split("/")
        m.add_attachment(attach[1], maintype=maintype, subtype=subtype, filename=attach[0])
    return m


def test_mail_import_once_with_provenance(lens):
    from financial_lens import mail as ml

    photo = render_invoice_photo(INVOICE, noise=False, tilt=0)
    box = FakeIMAP([mail("<a@x>", "Ihre Rechnung", attach=("rechnung.jpg", photo), ctype="image/jpeg"),
                    mail("<b@x>", "Kontoauszug", attach=("camt.xml", CAMT), ctype="application/xml"),
                    mail("<c@x>", "Quittung Bäckerei", body="Bäckerei Frey\nzu bezahlen CHF 12.80\nDatum 03.10.2026"),
                    mail("<d@x>", "Newsletter", sender="spam@ads.example", body="Buy now")])
    res = ml.fetch(lens, "mail.example.ch", "me", "secret", connect=lambda h, p: box,
                   allowed_senders=["ewz.ch", "bank", "baeckerei", "rechnungen"])
    assert box.readonly is True
    assert res.messages == 3 and any("not an allowed sender" in n for n in res.notes)
    res2 = ml.fetch(lens, "mail.example.ch", "me", "secret", connect=lambda h, p: box)
    assert res2.messages == 0 and res2.skipped == 4  # every message is read once, including the ignored one
    docs = {d["filename"]: d for d in lens.documents()}
    assert docs["rechnung.jpg"]["received_by"].startswith("mail:me@mail.example.ch")
    inv = [o for o in lens.db.execute("SELECT * FROM operations_current WHERE kind='invoice'").fetchall()]
    assert len(inv) == 1 and inv[0]["verification"] == "confirmed"  # invoice from mail matched the statement from mail
    assert any(d.endswith(".txt") for d in docs)  # receipt in a mail body became a document


def test_mail_respects_local_only(lens):
    from financial_lens import mail as ml

    with pytest.raises(ml.MailError):
        ml.fetch(lens, "imap.gmail.com", "me", "secret")


def test_phone_pairing_upload_and_lan_gate(lens):
    from financial_lens.api import app as api
    from financial_lens.api import mobile

    api.app.dependency_overrides[api.lens] = lambda: lens
    info = mobile.pair_device(lens, "Miha's phone", base_url="http://192.168.1.20:8765")
    assert info["url"].startswith("http://192.168.1.20:8765/m#t=")
    stored = lens.db.execute("SELECT token_sha256 FROM device_tokens").fetchone()["token_sha256"]
    assert info["token"] not in stored  # only a hash is kept

    phone = TestClient(api.app, client=("192.168.1.33", 50000))
    page = phone.get("/m")
    assert page.status_code == 200 and 'capture="environment"' in page.text
    assert phone.get("/m/manifest.webmanifest").json()["display"] == "standalone"
    assert phone.get("/treemap").status_code == 403  # the phone sees only the upload page
    assert phone.get("/documents").status_code == 403

    photo = render_invoice_photo(INVOICE, noise=False, tilt=0)
    bad = phone.post("/m/upload", files=[("files", ("x.jpg", photo, "image/jpeg"))], headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    ok = phone.post("/m/upload", files=[("files", ("IMG_1.jpg", photo, "image/jpeg"))],
                    headers={"Authorization": f"Bearer {info['token']}"}).json()
    r = ok["results"][0]
    assert r["amount"] == "184.50" and r["category"] == "Housing / Electricity"
    assert lens.documents()[0]["received_by"] == "device:Miha's phone"
    mobile.revoke_device(lens, info["id"])
    again = phone.post("/m/upload", files=[("files", ("IMG_2.jpg", b"x", "image/jpeg"))],
                       headers={"Authorization": f"Bearer {info['token']}"})
    assert again.status_code == 401
    api.app.dependency_overrides.clear()


def test_desktop_manual_entry_with_attachment(lens, tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from financial_lens.desktop.main import MainWindow, ManualDialog

    app = QApplication.instance() or QApplication([])
    w = MainWindow(lens, today=date(2026, 10, 31))
    dlg = ManualDialog(w, [c["path"] for c in lens.categories()], date(2026, 10, 31))
    dlg.amount.setText("12,5x")
    dlg._accept()
    assert "positive amount" in dlg.error.text()
    dlg.amount.setText("38.50")
    dlg.counterparty.setText("Wochenmarkt Bern")
    dlg.category.setCurrentIndex(dlg.category.findText("Food / Groceries"))
    v = dlg.values()
    assert v["amount"] == "38.50" and v["category"] == ("Food", "Groceries")
    receipt = tmp_path / "markt.jpg"
    receipt.write_bytes(render_invoice_photo(["Wochenmarkt", "Gemüse 38.50"], noise=False, tilt=0))
    v["attachment"] = str(receipt)
    op = w.add_record(**v)
    d = lens.operation_detail(op)
    assert d["verification"] == "unconfirmed" and d["category_path"] == ["Food", "Groceries"]
    assert any(doc["filename"] == "markt.jpg" and doc["role"] == "attachment" for doc in d["documents"])
    assert w.kpi["expenses"].text() == "CHF 38.50"
    app.processEvents()
