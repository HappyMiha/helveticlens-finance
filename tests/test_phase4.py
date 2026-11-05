"""Phase 4: privacy levels, model providers, encrypted backups, integrity, security self-check."""

import json
import urllib.request
from datetime import date

import pytest

from financial_lens import backup, privacy, security
from financial_lens.ai.providers import Orchestrator, Scripted
from test_mvp_cycle import CAMT


class Recording(Scripted):
    def __init__(self, name, locality, answers=None):
        super().__init__(name=name, locality=locality, answers=answers or {})
        self.seen = []

    def complete(self, system, user):
        self.seen.append(user)
        return super().complete(system, user)


def test_local_only_blocks_the_network_but_not_the_database(lens):
    with privacy.local_only(extra_local_hosts=["db"]):
        with pytest.raises(OSError):
            urllib.request.urlopen("https://api.anthropic.com/", timeout=3)
        # local PostgreSQL keeps working; the whole cycle runs offline
        res = lens.ingest(CAMT, "offline.xml")
        assert len(res.operation_ids) == 3
        assert privacy.guard_active()
    assert not privacy.guard_active()


def test_privacy_levels_route_and_redact(lens):
    local = Recording("ollama", "local", {"Counterparty": '{"category": "Food / Groceries", "confidence": 0.9, "reason": "shop"}'})
    swiss = Recording("infomaniak", "swiss", {"Counterparty": '{"category": "Food / Groceries", "confidence": 0.9, "reason": "shop"}'})
    cloud = Recording("cloud", "external", {"Counterparty": '{"category": "Food / Groceries", "confidence": 0.9, "reason": "shop"}'})
    orch = Orchestrator(routes={"classify": [cloud, swiss, local]})
    lens.attach_ai(orch)
    cats = [c["path"] for c in lens.categories() if c["kind"] == "expense"]

    lens.set_privacy_level("L2")
    sug = orch.classify("Hofladen Brunner", "IBAN CH44 3199 9123 0008 8901 2", cats)
    assert sug.method == "ai" and sug.confidence <= 0.75  # AI alone never reaches confirmed-level confidence
    assert not cloud.seen and not swiss.seen and "CH44" in local.seen[0]  # local may see raw data

    lens.set_privacy_level("L1")
    orch.stats.clear()
    local.seen.clear()
    orch.routes = {"classify": [cloud, swiss]}
    orch.classify("Hofladen Brunner", "IBAN CH44 3199 9123 0008 8901 2", cats)
    assert not cloud.seen and swiss.seen and "[IBAN]" in swiss.seen[0] and "CH44" not in swiss.seen[0]

    lens.set_privacy_level("L0")
    orch.routes = {"classify": [cloud]}
    orch.classify("Hofladen Brunner", "mail anna@example.ch", cats)
    assert "[EMAIL]" in cloud.seen[-1]
    acts = lens.ai_activity()
    assert any(a["summary"] == "skipped by privacy level" for a in acts)
    assert any(a["details"].get("left_machine") for a in acts)


def test_document_privacy_is_respected_per_document(lens):
    cloud = Recording("cloud", "external", {"": "{}"})
    orch = Orchestrator(routes={"extract": [cloud]})
    lens.attach_ai(orch)
    lens.set_privacy_level("L0")
    res = lens.ingest("Quittung\nDanke für Ihren Einkauf".encode(), "note.txt", "text/plain", privacy="local_only")
    assert not cloud.seen  # this document was marked local-only
    res = lens.ingest("Quittung\nBesten Dank".encode(), "note2.txt", "text/plain", privacy="cloud_ai")
    assert cloud.seen


def test_model_extraction_must_quote_the_document(lens):
    text = "Bäckerei Frey\nBrot und Gipfeli\nzu zahlen CHF 12\nam 03.10.2026"  # no decimals: rules find no amount
    honest = Recording("local-llm", "local", {"Brot": json.dumps({
        "amount": {"value": "12", "quote": "zu zahlen CHF 12"},
        "doc_date": {"value": "2026-10-03", "quote": "am 03.10.2026"}})})
    lens.attach_ai(Orchestrator(routes={"extract": [honest]}))
    res = lens.ingest(text.encode(), "receipt.txt", "text/plain")
    op = lens.operation_detail(res.operation_ids[0])
    assert op["amount"] == "12.00" and op["verification"] == "needs_review" and op["method"] == "ai_extraction"
    assert op["provenance"]["amount"]["method"] == "ai" and op["provenance"]["amount"]["quote"] == "zu zahlen CHF 12"
    liar = Recording("bad-llm", "local", {"Milch": json.dumps({
        "amount": {"value": "99.00", "quote": "total 99.00"}, "doc_date": {"value": "2026-10-04", "quote": "04.10.2026"}})})
    lens.attach_ai(Orchestrator(routes={"extract": [liar]}))
    res = lens.ingest("Laden\nMilch\nam 04.10.2026".encode(), "r2.txt", "text/plain")
    assert res.operation_ids == []  # an invented amount is rejected; nothing is created


def test_fallback_and_quality_scoring(lens):
    class Broken(Scripted):
        def complete(self, system, user):
            raise TimeoutError("model server down")

    broken = Broken(name="broken", locality="local")
    ok = Scripted(name="ok", locality="local", answers={"Counterparty": '{"category": "Food", "confidence": 0.7, "reason": "x"}'})
    orch = Orchestrator(routes={"classify": [broken, ok]})
    lens.attach_ai(orch)
    for _ in range(3):
        assert orch.classify("A", "", [("Food",)]).path == ("Food",)
    assert orch.score(ok) > orch.score(broken)
    assert orch._ordered("classify")[0].name == "ok"


def test_encrypted_backup_and_restore(lens, tmp_path):
    lens.ingest(CAMT, "camt.xml")
    lens.add_manual("receipt", "45.00", "CHF", date(2026, 10, 9), "Café Lang", ("Food", "Restaurants"))
    before = lens.treemap(date(2026, 10, 1), date(2026, 10, 31))
    file = backup.create(lens, tmp_path / "backups", "correct horse battery staple")
    blob = file.read_bytes()
    assert b"Migros" not in blob and blob.startswith(b"FLBK1")
    with pytest.raises(backup.BackupError):
        backup.decrypt(blob, "wrong passphrase!!")
    tampered = tmp_path / "t.flbk"
    tampered.write_bytes(blob[:-1] + bytes([blob[-1] ^ 1]))
    with pytest.raises(backup.BackupError):
        backup.restore(lens, tampered, "correct horse battery staple")
    copy = backup.copy_to(file, tmp_path / "nas")
    # restore into a fresh database schema
    import psycopg, uuid
    from financial_lens.service import FinancialLens
    from conftest import PG
    schema = "r_" + uuid.uuid4().hex[:8]
    admin = psycopg.connect(PG, autocommit=True)
    admin.execute(f"CREATE SCHEMA {schema}")
    fresh = FinancialLens(f"{PG} options=-csearch_path={schema}", tmp_path / "restored")
    fresh.migrate()
    fresh.restore = backup.restore(fresh, copy, "correct horse battery staple")
    after = fresh.treemap(date(2026, 10, 1), date(2026, 10, 31))
    assert after["total"] == before["total"] and after["children"] == before["children"]
    doc = fresh.documents()[0]
    assert fresh.original(doc["id"])[0]
    fresh.close()
    admin.execute(f"DROP SCHEMA {schema} CASCADE")


def test_audit_chain_detects_tampering_and_self_check(lens):
    lens.ingest(CAMT, "camt.xml")
    assert lens.verify_audit_chain()["ok"]
    report = security.self_check(lens)
    names = {c["check"]: c["ok"] for c in report["checks"]}
    assert names["originals integrity"] and names["audit log chain"] and names["append-only history"]
    assert names["originals read-only"] and names["API bound to loopback"]
    # an attacker with database superuser rights disables the trigger and edits history
    lens.db.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only")
    lens.db.execute("UPDATE audit_log SET actor='someone-else' WHERE id = (SELECT min(id) FROM audit_log)")
    lens.db.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only")
    assert not lens.verify_audit_chain()["ok"]
