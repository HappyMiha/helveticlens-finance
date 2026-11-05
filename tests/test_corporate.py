"""Corporate edition: people sign in on one server, roles hold, every step is audited, the licence decides
whether the ledger can still be changed."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from financial_lens import corporate as C
from financial_lens import licensing as L

PW = "correct horse 42"


@pytest.fixture
def issuer(monkeypatch):
    priv, pub = L.keygen()
    monkeypatch.setenv("FL_LICENSE_PUBKEY", pub)
    return priv


@pytest.fixture
def server(lens, monkeypatch, tmp_path, issuer):
    from financial_lens.api import app as api
    from financial_lens.api import corporate as web_corp
    from financial_lens.api import webui
    from financial_lens.service import FinancialLens

    def clone():
        fl = FinancialLens(lens.dsn, tmp_path, actor="user:test")
        fl.org = lens.org
        return fl

    monkeypatch.setattr(api.app, "dependency_overrides", {})  # other tests pin a single-user ledger
    fresh = api.LensPool(size=4)
    monkeypatch.setattr(api.pool, "__dict__", {**fresh.__dict__})
    monkeypatch.setattr(api.pool, "_make", clone)
    monkeypatch.setattr(webui.Settings, "edition", "corporate")
    monkeypatch.setattr(web_corp.Config, "data_dir", str(tmp_path))
    monkeypatch.setattr(web_corp.Config, "allowed_hosts", set())
    monkeypatch.setattr(web_corp.Config, "sso_header", "")
    C.throttle.fails.clear()
    yield lens
    for fl in api.pool.all:
        fl.close()


def client():
    from financial_lens.api import app as api

    return TestClient(api.app, base_url="http://finance.office.local:8765")


def sign_in(c, login, password=PW):
    r = c.post("/ui/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"X-FL-CSRF": r.json()["csrf"]}


def owner(c, server, tmp_path):
    code = C.setup_code(tmp_path)
    r = c.post("/ui/setup", json={"code": code, "login": "anna", "name": "Anna Muster", "password": PW})
    assert r.status_code == 200, r.text
    return {"X-FL-CSRF": r.json()["csrf"]}


def test_first_administrator_needs_the_setup_code(server, tmp_path):
    c = client()
    assert c.get("/ui/edition").json() == {"edition": "corporate", "needs_setup": True, "sso": False}
    assert c.get("/dashboard").status_code == 401
    C.setup_code(tmp_path)
    bad = c.post("/ui/setup", json={"code": "0000-0000-0000-0000", "login": "eve", "name": "Eve", "password": PW})
    assert bad.status_code == 401
    h = owner(c, server, tmp_path)
    assert c.get("/ui/edition").json()["needs_setup"] is False
    me = c.get("/ui/me").json()
    assert me["edition"] == "corporate" and me["user"]["login"] == "anna" and me["user"]["role"] == "owner"
    assert me["license"]["state"] == "trial" and me["license"]["writable"] is True
    assert me["csrf"] == h["X-FL-CSRF"]
    # the setup code works once only
    again = c.post("/ui/setup", json={"code": "x", "login": "eve", "name": "Eve", "password": PW})
    assert again.status_code == 403


def test_roles_sessions_and_audit(server, tmp_path):
    c = client()
    h = owner(c, server, tmp_path)
    assert c.post("/ui/users", json={"login": "bob", "name": "Bob", "role": "editor", "password": PW}, headers=h).status_code == 200
    assert c.post("/ui/users", json={"login": "vera", "name": "Vera", "role": "viewer", "password": PW}, headers=h).status_code == 200
    assert c.post("/ui/users", json={"login": "x", "name": "Short", "role": "viewer", "password": "short"},
                  headers=h).status_code == 422
    body = {"amount": "120.00", "op_date": "2026-10-12", "counterparty": "Swisscom", "kind": "expense"}
    assert c.post("/operations", json=body).status_code == 403  # no CSRF
    assert c.post("/operations", json=body, headers=h).status_code == 200

    bob, vera = client(), client()
    hb, hv = sign_in(bob, "bob"), sign_in(vera, "vera")
    assert bob.post("/operations", json={**body, "counterparty": "Migros"}, headers=hb).status_code == 200
    assert bob.get("/ui/users").status_code == 403  # bookkeepers do not manage the team
    assert bob.get("/ui/audit").status_code == 403
    rows = vera.get("/ui/transactions", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert {r["counterparty"] for r in rows} == {"Swisscom", "Migros"}
    assert vera.post("/operations", json=body, headers=hv).status_code == 403  # viewers only read
    assert vera.post("/ask", json={"question": "unpaid invoices"}, headers=hv).status_code == 200

    # each change carries the person who made it
    log = c.get("/ui/audit").json()
    assert log["chain"]["ok"]
    actions = [(e["action"], e["actor_login"]) for e in log["entries"]]
    assert ("login", "bob") in actions and ("login", "vera") in actions and ("grant", "anna") in actions
    revs = server.db.execute("SELECT DISTINCT r.agent FROM operation_revisions r").fetchall()
    assert len({r["agent"] for r in revs}) == 2  # Anna's and Bob's records, not one shared "local" user
    assert "login" in c.get("/ui/audit.csv").text

    # disabling ends the person's sessions at once
    vid = next(u["id"] for u in c.get("/ui/users").json()["users"] if u["login"] == "vera")
    assert c.patch(f"/ui/users/{vid}", json={"disabled": True}, headers=h).status_code == 200
    assert vera.get("/dashboard").status_code == 401
    assert client().post("/ui/login", json={"login": "vera", "password": PW}).status_code == 401
    # the last administrator cannot lock everyone out
    me = c.get("/ui/me").json()["user"]["id"]
    assert c.patch(f"/ui/users/{me}", json={"role": "viewer"}, headers=h).status_code == 422
    assert c.post("/ui/logout", headers=h).status_code == 200
    assert c.get("/dashboard").status_code == 401


def test_wrong_passwords_are_throttled(server, tmp_path):
    c = client()
    owner(c, server, tmp_path)
    other = client()
    for _ in range(5):
        assert other.post("/ui/login", json={"login": "anna", "password": "wrong password!"}).status_code == 401
    r = other.post("/ui/login", json={"login": "anna", "password": PW})
    assert r.status_code == 401 and "Too many" in r.json()["detail"]
    fails = server.db.execute("SELECT count(*) AS n FROM audit_log WHERE action='login_failed'").fetchone()["n"]
    assert fails == 5


def test_member_sees_only_own_statement(server, tmp_path):
    c = client()
    h = owner(c, server, tmp_path)
    assert c.post("/ui/users", json={"login": "max", "name": "Max", "role": "member", "password": PW}, headers=h).status_code == 200
    m = client()
    sign_in(m, "max")
    assert m.get("/ui/me").status_code == 200
    assert m.get("/dashboard").status_code == 403
    assert m.get("/ui/transactions").status_code == 403


def test_after_trial_a_reminder_but_work_goes_on(server, tmp_path, monkeypatch):
    c = client()
    h = owner(c, server, tmp_path)
    assert c.get("/ui/me").json()["license"]["nag"] is False
    later = date.today() + timedelta(days=L.TRIAL_DAYS + 1)
    real_status = L.status
    monkeypatch.setattr(L, "status", lambda lens, today=None: real_status(lens, today or later))
    lic = c.get("/ui/me").json()["license"]
    assert lic["state"] == "trial_ended" and lic["nag"] is True and lic["writable"] is True
    assert "buy a subscription" in lic["message"] and lic["contact"] == "info@helveticlens.ch"
    body = {"amount": "9.90", "op_date": "2026-10-12", "counterparty": "Coop", "kind": "expense"}
    assert c.post("/operations", json=body, headers=h).status_code == 200


def test_trial_then_signed_key(server, tmp_path, issuer, monkeypatch):
    monkeypatch.setattr(L, "ENFORCE", True)  # strict mode: read-only without a licence
    c = client()
    h = owner(c, server, tmp_path)
    st = L.status(server)
    assert st.state == "trial" and st.days_left == L.TRIAL_DAYS and st.prices == {"monthly": "1", "2y": "10"}
    body = {"amount": "9.90", "op_date": "2026-10-12", "counterparty": "Coop", "kind": "expense"}

    # 3 months later: still readable, no longer writable
    later = date.today() + timedelta(days=L.TRIAL_DAYS + 1)
    real_status = L.status
    monkeypatch.setattr(L, "status", lambda lens, today=None: real_status(lens, today or later))
    assert L.status(server).state == "trial_ended"
    r = c.post("/operations", json=body, headers=h)
    assert r.status_code == 402 and "trial ended" in r.json()["detail"] and "readable" in r.json()["detail"]
    assert c.get("/dashboard").status_code == 200
    lic = c.get("/ui/license").json()
    assert lic["request"].startswith("FLR1.")

    # a key for another installation, or a forged one, is refused
    other = L.make_request("00000000-0000-4000-8000-000000000000", "Other AG", 3)
    assert c.post("/ui/license", json={"key": L.issue(issuer, other, "monthly", 5)}, headers=h).status_code == 422
    fake_priv, _ = L.keygen()
    assert c.post("/ui/license", json={"key": L.issue(fake_priv, lic["request"], "monthly", 5)}, headers=h).status_code == 422

    key = L.issue(issuer, lic["request"], "2y", 2, customer="Muster AG", start=later)
    r = c.post("/ui/license", json={"key": key}, headers=h)
    assert r.status_code == 200 and r.json()["state"] == "active" and r.json()["seats"] == 2
    assert c.post("/operations", json=body, headers=h).status_code == 200

    # seats: the owner plus one more; a third person needs a bigger licence
    assert c.post("/ui/users", json={"login": "bob", "name": "Bob", "role": "editor", "password": PW}, headers=h).status_code == 200
    r = c.post("/ui/users", json={"login": "carl", "name": "Carl", "role": "viewer", "password": PW}, headers=h)
    assert r.status_code == 403 and "2 users" in r.json()["detail"]

    # two years on the key expires and the ledger is read-only again
    monkeypatch.setattr(L, "status", lambda lens, today=None: real_status(lens, today or later + timedelta(days=800)))
    assert c.post("/operations", json=body, headers=h).status_code == 402
    assert any(e["action"] == "license_install" for e in c.get("/ui/audit").json()["entries"])


def test_trial_cannot_be_reset_by_editing_settings(server, tmp_path):
    first = L.install_id(server)
    server.db.execute("DELETE FROM settings")
    assert L.install_id(server) == first  # kept in the append-only audit log


def test_key_format_and_prices(issuer):
    req = L.make_request("6f1c1f5e-1111-4a4a-9b9b-222233334444", "Muster AG", 12)
    assert L.read_request(req)["users"] == 12
    key = L.issue(issuer, req, "monthly", 12, months=12, start=date(2026, 11, 5))
    p = L.verify(key, "6f1c1f5e-1111-4a4a-9b9b-222233334444")
    assert p["expires"] == "2027-11-05" and p["seats"] == 12 and p["customer"] == "Muster AG"
    tampered = key.split(".")
    tampered[1] = tampered[1][:-2] + ("A" if tampered[1][-2] != "A" else "B") + tampered[1][-1]
    with pytest.raises(L.LicenseError):
        L.verify(".".join(tampered), "6f1c1f5e-1111-4a4a-9b9b-222233334444")
    assert str(L.price("monthly", 12, 12)) == "144" and str(L.price("2y", 12)) == "120"
    assert L.issue(issuer, req, "2y", 1, start=date(2026, 2, 28)).count(".") == 2


def test_sso_header_from_trusted_proxy_only(server, tmp_path, monkeypatch):
    from financial_lens.api import corporate as web_corp

    c = client()
    owner(c, server, tmp_path)
    monkeypatch.setattr(web_corp.Config, "sso_header", "X-Forwarded-User")
    monkeypatch.setattr(web_corp.Config, "sso_proxies", ["testclient"])
    s = client()
    assert s.get("/ui/me", headers={"X-Forwarded-User": "nobody"}).status_code == 401
    r = s.get("/ui/me", headers={"X-Forwarded-User": "anna"})
    assert r.status_code == 200 and r.json()["user"]["login"] == "anna"
    assert "fl_corp" in s.cookies
    assert s.get("/dashboard").status_code == 200  # the session cookie now carries on
    monkeypatch.setattr(web_corp.Config, "sso_proxies", ["10.9.9.9"])
    assert client().get("/ui/me", headers={"X-Forwarded-User": "anna"}).status_code == 401


def test_personal_edition_is_unchanged(lens, monkeypatch):
    from financial_lens.api import app as api
    from financial_lens.api import webui

    api.app.dependency_overrides[api.lens] = lambda: lens
    try:
        c = TestClient(api.app, base_url="http://127.0.0.1:8765")
        assert c.get("/ui/edition").json() == {"edition": "personal"}
        assert c.post("/ui/login", json={"login": "a", "password": "b"}).status_code == 404
    finally:
        api.app.dependency_overrides.clear()
