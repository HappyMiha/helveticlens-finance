"""Apertus analyst: the model reads the whole document; only what can be checked against it is used."""

import json

from conftest import render_invoice_photo
from financial_lens.ai.providers import Orchestrator, Scripted

RECEIPT = ["Café Frojer", "Feldbergstrasse 40, 4057 Basel", "", "Quittung 17.10.2026",
           "Cappuccino          2x   9.80", "Gipfeli              1x   3.20", "Total CHF            13.00",
           "MWST 2.6% inkl.            0.33", "Bezahlt Karte"]


class Analyst(Scripted):
    def __init__(self, lie=False):
        super().__init__(name="test-analyst", locality="local")
        self.lie, self.calls = lie, 0

    def complete(self, system, user):
        self.calls += 1
        if "Swiss bookkeeper" not in system:
            return "{}"
        return json.dumps({"doc_type": "receipt", "merchant": "Café Frojer", "date": "2026-10-17", "currency": "CHF",
                           "total": "13.00", "vat": "0.33", "payment": "card",
                           "items": [{"name": "Cappuccino", "qty": 2, "amount": "9.80"},
                                     {"name": "Gipfeli", "qty": 1, "amount": "3.20"},
                                     {"name": "Invented cake", "qty": 1, "amount": "77.70" if self.lie else None}],
                           "category": "Food / Restaurants", "summary": "Two cappuccinos and a croissant"})


def _attach(lens, model, monkeypatch):
    monkeypatch.setenv("FL_ANALYST", "1")
    lens.attach_ai(Orchestrator(routes={t: [model] for t in ("understand", "extract", "classify", "parse_question")}))


def test_analyst_reads_items_and_category(lens, monkeypatch):
    model = Analyst()
    _attach(lens, model, monkeypatch)
    res = lens.ingest(render_invoice_photo(RECEIPT, noise=False, tilt=0), "frojer.jpg")
    assert model.calls >= 1 and len(res.operation_ids) == 1
    op = lens.operation_detail(res.operation_ids[0])
    assert op["category_path"] == ["Food", "Restaurants"] and op["amount"] == "13.00"
    assert op["description"] == "Two cappuccinos and a croissant"
    d = lens.upload_detail(res.document_id)
    r = d["reading"]
    assert [i["name"] for i in r["items"]][:2] == ["Cappuccino", "Gipfeli"] and r["items_match"]
    assert r["total_printed"] and "items add up" in r["check"]


def test_analyst_amounts_not_printed_are_dropped(lens, monkeypatch):
    _attach(lens, Analyst(lie=True), monkeypatch)
    res = lens.ingest(render_invoice_photo(RECEIPT, noise=False, tilt=0), "frojer.jpg")
    r = lens.upload_detail(res.document_id)["reading"]
    assert "Invented cake" not in [i["name"] for i in r["items"]] and "dropped" in r["check"]


def test_without_analyst_mode_the_model_is_not_asked_for_a_full_reading(lens, monkeypatch):
    monkeypatch.delenv("FL_ANALYST", raising=False)
    model = Analyst()
    lens.attach_ai(Orchestrator(routes={t: [model] for t in ("understand", "extract", "classify", "parse_question")}))
    res = lens.ingest(render_invoice_photo(RECEIPT, noise=False, tilt=0), "frojer.jpg")
    assert lens.upload_detail(res.document_id)["reading"] is None


def test_model_choice(tmp_path, monkeypatch):
    from financial_lens.ai import local_model

    monkeypatch.setattr(local_model, "folder", lambda: tmp_path)
    assert local_model.selected().key == "apertus-8b"
    local_model.select("apertus-1.5-8b")
    st = local_model.status()
    assert st["key"] == "apertus-1.5-8b" and st["role"] == "analyst" and not st["model_installed"]
    assert {m["key"] for m in st["models"]} == {"apertus-8b", "apertus-1.5-8b"}
