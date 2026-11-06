"""Uploads: see what came from a file, edit it, delete it, and never count the same thing twice."""

from datetime import date
from decimal import Decimal

from conftest import render_invoice_photo
from docgen import statement_bkb_en, statement_columns

INVOICE = ["Elektrizitätswerk Limmattal AG", "Werkstrasse 12, 8952 Schlieren", "", "Rechnung Nr. 2026-10-4471",
           "Rechnungsdatum: 12.10.2026", "Stromlieferung Oktober 2026", "Netznutzung               CHF   71.30",
           "Energie                   CHF   95.95", "MWST 8.1%                 CHF   17.25",
           "Total zu bezahlen         CHF  184.50", "Zahlbar bis 30.10.2026"]


def _live(lens):
    return lens.db.execute("SELECT count(*) AS n FROM operations_current").fetchone()["n"]


def test_upload_detail_lists_records_and_text(lens):
    res = lens.ingest(statement_bkb_en(), "bkb.pdf")
    d = lens.upload_detail(res.document_id)
    assert d["filename"] == "bkb.pdf" and len(d["records"]) == 6
    assert {"Booking.com", "Migros"} <= {r["counterparty"] for r in d["records"]}
    assert "Withdrawal location" in d["text"] and d["records"][0]["category_path"]
    assert [x["filename"] for x in lens.documents()] == ["bkb.pdf"] and lens.documents()[0]["operations"] == 6


def test_delete_upload_removes_its_records_and_can_be_read_again(lens):
    pdf = statement_bkb_en()
    res = lens.ingest(pdf, "bkb.pdf")
    assert _live(lens) == 6
    out = lens.delete_document(res.document_id)
    assert out["deleted_records"] == 6 and _live(lens) == 0 and lens.documents() == []
    d = lens.dashboard(date(2026, 1, 1), date(2026, 12, 31))
    assert d["expenses"] in ("0", "0.00") and not d["recent_documents"]
    again = lens.ingest(pdf, "bkb.pdf")
    assert again.document_id == res.document_id and len(again.operation_ids) == 6 and _live(lens) == 6
    hist = lens.db.execute("SELECT count(*) AS n FROM operation_revisions WHERE deleted").fetchone()["n"]
    assert hist == 6  # deletions stay in the history


def test_edit_add_and_delete_records_of_an_upload(lens):
    res = lens.ingest(statement_bkb_en(), "bkb.pdf")
    rec = next(r for r in lens.upload_detail(res.document_id)["records"] if r["counterparty"] == "Migros")
    lens.correct(rec["operation_id"], {"description": "weekly shop", "amount": "-40.10"}, "edited")
    lens.tag(rec["operation_id"], "family")
    lens.delete_operation(next(r for r in lens.upload_detail(res.document_id)["records"]
                               if r["counterparty"] == "SBB EasyRide")["operation_id"])
    op = lens.add_to_upload(res.document_id, "expense", "-7.50", "CHF", date(2026, 10, 7), "Kiosk", ("Food", "Groceries"))
    d = lens.upload_detail(res.document_id)
    by = {r["counterparty"]: r for r in d["records"]}
    assert "SBB EasyRide" not in by and by["Kiosk"]["operation_id"] == op
    assert by["Migros"]["description"] == "weekly shop" and by["Migros"]["amount"] == "-40.10"
    assert by["Migros"]["tags"] == ["family"] and len(d["records"]) == 6


def test_same_receipt_twice_is_attached_not_counted_twice(lens):
    first = lens.ingest(render_invoice_photo(INVOICE, noise=False, tilt=0), "strom.jpg")
    assert len(first.operation_ids) == 1
    second = lens.ingest(render_invoice_photo(INVOICE, noise=False, tilt=0.6), "strom-2.jpg")
    assert second.operation_ids == first.operation_ids and "Already recorded" in " ".join(second.messages)
    assert _live(lens) == 1
    roles = {r["role"] for r in lens.upload_detail(second.document_id)["records"]}
    assert roles == {"attachment"}
    # deleting the second file leaves the record; deleting the first removes it
    lens.delete_document(second.document_id)
    assert _live(lens) == 1
    lens.delete_document(first.document_id)
    assert _live(lens) == 0


def test_overlapping_statement_does_not_duplicate(lens):
    pdf, _ = statement_columns()
    lens.ingest(pdf, "oktober.pdf")
    n = _live(lens)
    from docgen import as_photo

    again = lens.ingest(as_photo(pdf), "oktober-foto.jpg")
    assert _live(lens) == n, [lens.operation_detail(o)["counterparty"] for o in again.operation_ids]
    assert "already imported" in " ".join(again.messages)


def test_about_has_version_and_changelog():
    from fastapi.testclient import TestClient

    from financial_lens import __version__
    from financial_lens.api import app as api

    body = TestClient(api.app).get("/health").json()
    assert body["version"] == __version__
    notes = api.ui_about()
    assert notes["version"] == __version__ and f"## {__version__}" in notes["changelog"]
