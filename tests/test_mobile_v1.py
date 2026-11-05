"""Mobile API v1: one-time QR pairing, device-key signatures, replay protection, scopes, revocation."""

import base64
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from conftest import render_invoice_photo
from test_mvp_cycle import CAMT, INVOICE


class Phone:
    """What the app does: own P-256 key, signed requests."""

    def __init__(self, client, name="Miha's Pixel"):
        self.c = client
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.name = name
        self.device_id = None

    @property
    def public_key(self) -> str:
        der = self.key.public_key().public_bytes(serialization.Encoding.DER,
                                                 serialization.PublicFormat.SubjectPublicKeyInfo)
        return base64.b64encode(der).decode()

    def pair(self, uri: str):
        q = {k: v[0] for k, v in parse_qs(urlparse(uri).query).items()}
        r = self.c.post("/mobile/v1/pair", json={"offer": q["offer"], "otp": q["otp"], "name": self.name,
                                                 "platform": "android", "public_key": self.public_key})
        if r.status_code == 200:
            self.device_id = r.json()["device_id"]
        return r

    def headers(self, method, path, body=b"", ts=None, nonce=None):
        from financial_lens.api.mobile_v1 import canonical

        ts = ts or datetime.now(timezone.utc).isoformat()
        nonce = nonce or uuid.uuid4().hex
        sig = self.key.sign(canonical(method, path, ts, nonce, body), ec.ECDSA(hashes.SHA256()))
        return {"X-FL-Device": self.device_id, "X-FL-Timestamp": ts, "X-FL-Nonce": nonce,
                "X-FL-Signature": base64.b64encode(sig).decode()}

    def get(self, path, **kw):
        return self.c.get(path, headers=self.headers("GET", path.split("?")[0], **kw))

    def upload(self, files):
        req = self.c.build_request("POST", "/mobile/v1/documents", files=files)
        body = req.read()
        req.headers.update(self.headers("POST", "/mobile/v1/documents", body))
        return self.c.send(req)


@pytest.fixture
def api(lens):
    from financial_lens.api import app as a

    a.app.dependency_overrides[a.lens] = lambda: lens
    yield TestClient(a.app, client=("192.168.1.40", 50123))  # a phone on the Wi-Fi
    a.app.dependency_overrides.clear()


def offer(lens, scopes=("upload", "read")):
    from financial_lens.api import mobile_v1

    return mobile_v1.create_offer(lens, "192.168.1.20:8766", "ab" * 32, scopes)


def test_pairing_is_one_time_and_expires(lens, api):
    o = offer(lens)
    assert o["uri"].startswith("fl://pair?v=1&addr=192.168.1.20%3A8766&fp=")
    stored = lens.db.execute("SELECT otp_sha256 FROM pair_offers").fetchone()["otp_sha256"]
    assert parse_qs(urlparse(o["uri"]).query)["otp"][0] not in stored  # only a hash is kept
    phone = Phone(api)
    assert phone.pair(o["uri"]).status_code == 200
    assert Phone(api, "attacker").pair(o["uri"]).status_code == 403  # the same QR cannot be used twice
    late = offer(lens)
    lens.db.execute("UPDATE pair_offers SET expires_at = now() - interval '1 second' WHERE id=%s", (late["offer_id"],))
    assert Phone(api).pair(late["uri"]).status_code == 403
    wrong = offer(lens)["uri"].replace("otp=", "otp=x")
    assert Phone(api).pair(wrong).status_code == 403
    actions = [r["action"] for r in lens.db.execute("SELECT action FROM audit_log ORDER BY id").fetchall()]
    assert actions.count("pair_device") == 1 and actions.count("pair_rejected") == 3


def test_signed_requests_replay_and_tampering(lens, api):
    phone = Phone(api)
    phone.pair(offer(lens)["uri"])
    assert phone.get("/mobile/v1/summary").status_code == 200
    assert api.get("/mobile/v1/summary").status_code == 401  # unsigned
    h = phone.headers("GET", "/mobile/v1/summary")
    assert api.get("/mobile/v1/summary", headers=h).status_code == 200
    assert api.get("/mobile/v1/summary", headers=h).status_code == 401  # replayed nonce
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    assert phone.get("/mobile/v1/summary", ts=old).status_code == 401  # stale
    h = phone.headers("GET", "/mobile/v1/widget")
    assert api.get("/mobile/v1/summary", headers=h).status_code == 401  # signature for another path
    other = Phone(api)
    other.device_id = phone.device_id  # a different key pretending to be the paired phone
    assert other.get("/mobile/v1/summary").status_code == 401
    # the phone still sees nothing outside /mobile/v1
    assert api.get("/treemap").status_code == 403 and api.get("/documents").status_code == 403


def test_upload_scan_and_read_back(lens, api):
    phone = Phone(api)
    phone.pair(offer(lens)["uri"])
    photo = render_invoice_photo(INVOICE, noise=False, tilt=0)
    r = phone.upload([("files", ("scan.jpg", photo, "image/jpeg"))]).json()["results"][0]
    assert r["amount"] == "184.50" and r["category"] == ["Housing", "Electricity"] and not r["duplicate"]
    again = phone.upload([("files", ("scan-retry.jpg", photo, "image/jpeg"))]).json()["results"][0]
    assert again["duplicate"] and again["document_id"] == r["document_id"]  # offline-queue retries are harmless
    phone.upload([("files", ("camt.xml", CAMT, "application/xml"))])
    s = phone.get("/mobile/v1/summary?start=2026-10-01&end=2026-10-31").json()
    assert s["expenses"] == "252.30" and s["categories"][0]["name"] == "Housing"
    t = phone.get("/mobile/v1/treemap?path=Housing/Electricity&start=2026-10-01&end=2026-10-31").json()
    op = t["operations"][0]
    d = phone.get(f"/mobile/v1/operations/{op['id']}").json()
    assert d["verification"] == "confirmed" and d["links"][0]["other_kind"] == "payment"
    assert d["provenance"]["amount"]["quote"].lower().startswith("total")
    orig = phone.get(f"/mobile/v1/documents/{d['documents'][0]['id']}/original")
    assert orig.content == photo and orig.headers["cache-control"] == "no-store"
    assert lens.documents()[-1]["received_by"].startswith("mobile:")
    w = phone.get("/mobile/v1/widget").json()
    assert set(w) >= {"month", "expenses", "unconfirmed", "top", "as_of"}


def test_scopes_and_revocation(lens, api):
    from financial_lens.api import mobile_v1

    upload_only = Phone(api, "Scanner")
    upload_only.pair(offer(lens, ("upload",))["uri"])
    assert upload_only.get("/mobile/v1/summary").status_code == 403
    photo = render_invoice_photo(INVOICE, noise=False, tilt=0)
    assert upload_only.upload([("files", ("a.jpg", photo, "image/jpeg"))]).status_code == 200
    reader = Phone(api)
    reader.pair(offer(lens)["uri"])
    mobile_v1.revoke(lens, reader.device_id)
    assert reader.get("/mobile/v1/summary").status_code == 401
    assert [d["name"] for d in mobile_v1.devices(lens) if d["revoked_at"] is None] == ["Scanner"]


def test_tls_certificate_is_stable_and_pinnable(tmp_path):
    from financial_lens.tls import ensure_certificate, fingerprint

    cert, key, fp = ensure_certificate(tmp_path)
    assert len(fp) == 64 and oct(key.stat().st_mode)[-3:] == "600"
    assert ensure_certificate(tmp_path)[2] == fp == fingerprint(cert)  # same certificate on every start


def test_desktop_serves_pinned_https_for_phones(lens, monkeypatch, tmp_path):
    """The desktop 'Pair phone' path: HTTPS with its own certificate; the fingerprint in the QR matches it."""
    pytest.importorskip("PySide6")
    import socket
    import ssl
    import time
    import hashlib

    from PySide6.QtWidgets import QApplication
    from financial_lens.desktop.main import MainWindow
    from financial_lens.api import mobile_v1

    app = QApplication.instance() or QApplication([])
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("FL_MOBILE_PORT", str(port))
    monkeypatch.setenv("FL_DSN", lens.dsn)
    w = MainWindow(lens)
    assert w._ensure_lan_server() == port
    for _ in range(50):
        try:
            der = ssl.get_server_certificate(("127.0.0.1", port))
            break
        except OSError:
            time.sleep(0.2)
    served = hashlib.sha256(ssl.PEM_cert_to_DER_cert(der)).hexdigest()
    offer = mobile_v1.create_offer(lens, f"127.0.0.1:{port}", w._tls_fp)
    assert f"fp={served}" in offer["uri"]
    w._server.should_exit = True
    app.processEvents()


def test_pair_dialog_shows_install_and_connect_steps(lens, tmp_path):
    pytest.importorskip("PySide6")
    import os
    from pathlib import Path
    from PySide6.QtWidgets import QApplication, QLabel
    from financial_lens.desktop.main import APP_DOWNLOAD_URL, MainWindow, PairDialog

    app = QApplication.instance() or QApplication([])
    w = MainWindow(lens)
    d = PairDialog(w, "fl://pair?v=1&addr=192.168.1.20%3A8766&fp=" + "ab" * 32 + "&offer=o&otp=s")
    texts = " ".join(l.text() for l in d.findChildren(QLabel))
    assert "1 · Install the app" in texts and "2 · Connect this phone" in texts
    assert APP_DOWNLOAD_URL.endswith("FinancialLens-Android.apk")
    d.resize(760, 560)
    d.show()
    app.processEvents()
    out = Path(os.environ.get("FL_SCREENSHOTS", tmp_path))
    out.mkdir(parents=True, exist_ok=True)
    d.grab().save(str(out / "desktop-pair-phone.png"))
