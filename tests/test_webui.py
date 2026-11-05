"""The local web interface: page served, and the service refuses anything that is not this user's browser."""

from fastapi.testclient import TestClient


def _client(lens, monkeypatch, auth=True):
    from financial_lens.api import app as api
    from financial_lens.api import webui

    api.app.dependency_overrides[api.lens] = lambda: lens
    monkeypatch.setattr(webui.Settings, "require_auth", auth)
    monkeypatch.setattr(webui.Settings, "key", "k" * 43)
    return TestClient(api.app, base_url="http://127.0.0.1:8765"), webui


def test_page_and_assets_are_served(lens, monkeypatch):
    c, _ = _client(lens, monkeypatch)
    r = c.get("/ui")
    assert r.status_code == 200 and "Financial Lens" in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"]
    for name in ("app.js", "app.css", "tokens.css", "favicon.svg"):
        assert c.get(f"/ui/static/{name}").status_code == 200
    assert c.get("/ui/static/..%2F..%2Fservice.py").status_code == 404


def test_requires_key_then_cookie_and_csrf(lens, monkeypatch):
    c, webui = _client(lens, monkeypatch)
    assert c.get("/dashboard").status_code == 401
    assert c.post("/ui/session", json={"key": "wrong"}).status_code == 401
    r = c.post("/ui/session", json={"key": "k" * 43})
    assert r.status_code == 200
    csrf = r.json()["csrf"]
    assert c.get("/dashboard").status_code == 200  # cookie now set
    me = c.get("/ui/me").json()
    assert me["csrf"] == csrf and me["privacy"] == "local_only"
    body = {"amount": "12.40", "op_date": "2026-10-12", "counterparty": "Migros", "kind": "expense"}
    assert c.post("/operations", json=body).status_code == 403  # no CSRF header: blocked
    assert c.post("/operations", json=body, headers={"X-FL-CSRF": "x" * 32}).status_code == 403
    assert c.post("/operations", json=body, headers={"X-FL-CSRF": csrf}).status_code == 200
    rows = c.get("/ui/transactions", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert rows[0]["counterparty"] == "Migros"
    tm = c.get("/treemap", params={"start": "2026-10-01", "end": "2026-10-31", "group": "counterparty"}).json()
    assert tm["children"][0]["name"] == "Migros"
    assert set(c.get("/ui/inbox").json()) == {"links", "review", "documents"}


def test_bearer_key_for_scripts(lens, monkeypatch):
    c, _ = _client(lens, monkeypatch)
    assert c.get("/dashboard", headers={"Authorization": "Bearer " + "k" * 43}).status_code == 200


def test_foreign_host_is_refused(lens, monkeypatch):
    """DNS rebinding: a web page that points its own name at 127.0.0.1 is refused."""
    c, _ = _client(lens, monkeypatch)
    c.post("/ui/session", json={"key": "k" * 43})
    assert c.get("/dashboard", headers={"Host": "evil.example:8765"}).status_code == 403
    assert c.get("/ui", headers={"Host": "evil.example"}).status_code == 403


def test_key_file_is_private(tmp_path):
    import os
    import stat

    from financial_lens.api.webui import load_key

    k = load_key(tmp_path)
    assert len(k) >= 40 and load_key(tmp_path) == k
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "ui-key").stat().st_mode) == 0o600


def test_lan_sees_only_phone_paths(lens, monkeypatch):
    """A phone on the Wi-Fi may reach /m and /mobile/v1 only — not /members, which merely starts with /m."""
    from financial_lens.api import app as api
    from financial_lens.api import mobile

    api.app.dependency_overrides[api.lens] = lambda: lens
    monkeypatch.setattr(mobile, "is_local_client", lambda request: False)
    c = TestClient(api.app, base_url="https://192.168.1.20:8766")
    assert c.get("/members").status_code == 403
    assert c.get("/dashboard").status_code == 403
    assert c.get("/m").status_code == 200
    assert c.get("/health").headers["x-financial-lens"] == "1"


def test_autostart_files(tmp_path, monkeypatch):
    import sys

    from financial_lens import launcher

    if sys.platform == "win32":
        return
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(launcher.Path, "home", lambda: tmp_path)
    assert not launcher.autostart_enabled()
    launcher.set_autostart(True)
    assert launcher.autostart_enabled() and "--service" in launcher._autostart_path().read_text()
    launcher.set_autostart(False)
    assert not launcher.autostart_enabled()


def test_ai_status_says_plainly_what_is_going_on(lens, monkeypatch):
    c, _ = _client(lens, monkeypatch)
    c.post("/ui/session", json={"key": "k" * 43})
    s = c.get("/ui/ai").json()
    assert s["state"] in ("not_installed", "off", "starting", "on", "error")
