import os

import pytest
from fastapi.testclient import TestClient

from test_mvp_cycle import CAMT


def test_api_roundtrip(lens, monkeypatch):
    from financial_lens.api import app as api

    api.app.dependency_overrides[api.lens] = lambda: lens
    c = TestClient(api.app)
    r = c.post("/operations", json={"amount": "184.50", "op_date": "2026-10-12", "counterparty": "Elektrizitaetswerk Limmattal",
                                    "kind": "invoice"})
    op = r.json()["id"]
    up = c.post("/documents", files=[("files", ("camt.xml", CAMT, "application/xml"))]).json()
    assert up[0]["doc_type"] == "bank_statement"
    tm = c.get("/treemap", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert tm["total"] == "252.30"
    detail = c.get(f"/operations/{op}").json()
    assert detail["links"], (detail, lens.db.execute("select * from links").fetchall())
    assert detail["links"][0]["status"] == "confirmed"
    doc = detail["links"][0]["other_doc"]  # the statement behind the linked payment
    assert c.get(f"/documents/{doc}/original").content == CAMT
    r = c.post(f"/operations/{op}/corrections", json={"changes": {"category": ["Housing", "Electricity"]},
                                                     "reason": "categorised"})
    assert r.status_code == 200
    assert c.get(f"/operations/{op}").json()["category_path"] == ["Housing", "Electricity"]
    assert c.get("/ai-activity").json()
