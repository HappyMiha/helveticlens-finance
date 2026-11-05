"""Document understanding: structure and arithmetic across layouts, languages, PDF and photo."""

from datetime import date
from decimal import Decimal

import pytest

from docgen import as_photo, invoice_with_decoys, payslip_de, payslip_fr, statement_columns, statement_signed_fr
from financial_lens.extract import ocr, understand


def analyse(data, media="application/pdf"):
    return understand.analyse(ocr.recognise(data, media))


@pytest.mark.parametrize("photo", [False, True])
def test_payslip_de_net_is_income_with_all_deductions(lens, photo):
    pdf, truth = payslip_de()
    data = as_photo(pdf) if photo else pdf
    an = analyse(data, "image/jpeg" if photo else "application/pdf")
    assert an.doc_type == "payslip"
    assert an.facts["gross"]["value"] == truth["gross"]
    assert an.facts["net"]["value"] == truth["net"]
    assert sum(d["value"] for d in an.facts["deductions"]) == truth["deductions"]
    assert an.consistent, an.to_json()["checks"]
    res = lens.ingest(data, "lohn.jpg" if photo else "lohn.pdf")
    op = lens.operation_detail(res.operation_ids[0])
    assert op["kind"] == "payslip" and Decimal(op["amount"]) == truth["payout"]
    assert op["category_path"] == ["Salary"] and op["op_date"] == "2026-10-25"
    assert "Muster Treuhand" in op["counterparty"] and op["verification"] == "unconfirmed"
    assert lens.dashboard(date(2026, 10, 1), date(2026, 10, 31))["income"] == str(truth["payout"])


def test_payslip_with_expenses_and_french_layout():
    pdf, truth = payslip_de(expenses="120.00")
    an = analyse(pdf)
    assert an.facts["payout"]["value"] == truth["payout"] and an.consistent
    pdf, truth = payslip_fr()
    an = analyse(pdf)
    assert an.doc_type == "payslip" and an.facts["net"]["value"] == truth["net"] and an.consistent
    assert an.facts["date"]["value"] == date(2026, 11, 25)


def test_payslip_that_does_not_add_up_goes_to_review(lens):
    pdf, _ = payslip_de(wrong_net=True)
    an = analyse(pdf)
    assert not an.consistent and any("printed net" in c.detail for c in an.checks if not c.ok)
    res = lens.ingest(pdf, "lohn-falsch.pdf")
    op = lens.operation_detail(res.operation_ids[0])
    assert op["verification"] == "needs_review" and "difference" in op["verification_reason"]


@pytest.mark.parametrize("photo", [False, True])
def test_statement_with_debit_credit_columns(lens, photo):
    pdf, truth = statement_columns()
    data = as_photo(pdf) if photo else pdf
    an = analyse(data, "image/jpeg" if photo else "application/pdf")
    assert an.doc_type == "bank_statement"
    assert [r["amount"] for r in an.rows] == [a for _, _, a in truth["rows"]], an.to_json()["rows"]
    assert an.consistent, an.to_json()["checks"]
    assert "Rechnung 2026-10-4471" in an.rows[0]["text"]  # second text line belongs to the booking
    res = lens.ingest(data, "kontoauszug.jpg" if photo else "kontoauszug.pdf")
    assert len(res.operation_ids) == 5 and "reconciles" in " ".join(res.messages)
    salary = [lens.operation_detail(o) for o in res.operation_ids if Decimal(lens.operation_detail(o)["amount"]) > 0][0]
    assert salary["category_path"] == ["Salary"]


def test_statement_signed_amount_and_year_from_period():
    pdf, truth = statement_signed_fr()
    an = analyse(pdf)
    assert [r["amount"] for r in an.rows] == [a for _, _, a in truth["rows"]]
    assert an.rows[0]["date"] == date(2026, 11, 3) and an.consistent


def test_statement_that_does_not_reconcile_is_imported_for_review(lens):
    pdf, _ = statement_columns(break_balance=True)
    an = analyse(pdf)
    assert not an.consistent
    res = lens.ingest(pdf, "auszug-defekt.pdf")
    assert res.operation_ids and all(lens.operation_detail(o)["verification"] == "needs_review" for o in res.operation_ids)


def test_invoice_total_is_the_one_the_arithmetic_supports(lens):
    pdf, truth = invoice_with_decoys()
    an = analyse(pdf)
    assert an.doc_type == "invoice" and an.facts["total"]["value"] == truth["total"]
    assert "net + VAT = total" in an.facts["total"]["how"]
    res = lens.ingest(pdf, "velo.pdf")
    assert lens.operation_detail(res.operation_ids[0])["amount"] == "201.40"


def test_statement_without_header_takes_sign_from_balance():
    from docgen import statement_no_header

    pdf, truth = statement_no_header()
    an = analyse(pdf)
    assert an.doc_type == "bank_statement"
    assert [r["amount"] for r in an.rows] == [a for _, _, a in truth["rows"]]
    assert all(r["how"] == "sign from the change in balance" for r in an.rows) and an.consistent


def test_receipt_ignores_cash_and_change():
    from docgen import receipt_with_change

    pdf, truth = receipt_with_change()
    an = analyse(pdf)
    assert an.doc_type == "receipt" and an.facts["total"]["value"] == truth["total"]
    assert "line items add up" in an.facts["total"]["how"]
