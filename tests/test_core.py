from datetime import date
from decimal import Decimal

import pytest

from financial_lens.domain.events import Expense, Ledger, Method, Payment, Provenance
from financial_lens.domain.money import Money, MoneyError, total
from financial_lens.ingest import camt053, qrbill
from financial_lens.matching.reconcile import reconcile
from financial_lens.views import treemap

QRR = "210000000003139471430009017"

CAMT = f"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>
<Ntry><Amt Ccy="CHF">129.40</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-12</Dt></BookgDt>
<AcctSvcrRef>B1</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Nm>EWZ Zürich</Nm></Cdtr></RltdPties>
<RmtInf><Strd><CdtrRefInf><Ref>{QRR}</Ref></CdtrRefInf></Strd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="CHF">54.20</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-14</Dt></BookgDt>
<AcctSvcrRef>B2</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Nm>Migros</Nm></Cdtr></RltdPties>
<RmtInf><Ustrd>Card payment</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="CHF">5200.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-10-25</Dt></BookgDt>
<AcctSvcrRef>B3</AcctSvcrRef></Ntry>
</Stmt></BkToCstmrStmt></Document>""".encode()


def prov(doc="d1"):
    return Provenance(doc, "page 1", Method.OCR, "test", 0.9)


def chf(v):
    return Money(Decimal(v), "CHF")


def test_money_rejects_floats_and_excess_precision():
    with pytest.raises(MoneyError):
        Money(0.1, "CHF")
    with pytest.raises(MoneyError):
        Money(Decimal("1.005"), "CHF")
    assert Money.parse("1'234.50", "CHF") == chf("1234.50")
    assert Money.parse("1 234,50", "EUR") == Money(Decimal("1234.50"), "EUR")


def test_total_and_allocation_never_lose_a_cent():
    assert total([chf("0.10")] * 3, "CHF") == chf("0.30")
    parts = chf("100.00").allocate([1, 1, 1])
    assert [p.amount for p in parts] == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    with pytest.raises(MoneyError):
        chf("1") + Money(Decimal("1"), "EUR")


def test_qr_reference_and_payload():
    assert qrbill.qr_reference_valid(QRR)
    assert not qrbill.qr_reference_valid(QRR[:-1] + "0")
    lines = ["SPC", "0200", "1", "CH4431999123000889012", "S", "EWZ Zürich", "Tramstrasse",
             "35", "8050", "Zürich", "CH"] + [""] * 7 + ["129.40", "CHF"] + [""] * 7 + \
            ["QRR", QRR, "Strom Q3", "EPD", ""]
    bill = qrbill.parse("\n".join(lines))
    assert bill.amount == chf("129.40") and bill.reference == QRR


def test_camt_import_and_reconciliation():
    payments = camt053.parse(CAMT, "stmt")
    assert [p.amount for p in payments] == [chf("-129.40"), chf("-54.20"), chf("5200.00")]
    assert payments[0].reference == QRR and payments[0].provenance.location == "camt.053 Ntry[0]"
    energy = Expense(chf("129.40"), date(2026, 9, 30), "EWZ", ("Home", "Energy"), prov(),
                     reference=QRR, due_on=date(2026, 10, 30))
    food = Expense(chf("54.20"), date(2026, 10, 14), "MIGROS", ("Household", "Groceries"), prov())
    matches, ambiguous = reconcile([energy, food], payments)
    assert {(m.expense_id, m.rule) for m in matches} == {(energy.id, "reference"), (food.id, "amount_date")}
    assert not ambiguous


def test_ambiguous_payments_are_not_guessed():
    e = Expense(chf("20.00"), date(2026, 10, 1), "Kiosk", ("Misc",), prov())
    p = [Payment(chf("-20.00"), date(2026, 10, 2), "A", prov()),
         Payment(chf("-20.00"), date(2026, 10, 3), "B", prov())]
    matches, ambiguous = reconcile([e], p)
    assert not matches and len(ambiguous[0].candidate_payment_ids) == 2


def test_revisions_keep_history_and_treemap_drills_down():
    ledger = Ledger()
    first = ledger.record_expense(Expense(chf("10.00"), date(2026, 10, 1), "Café", ("Food",), prov()))
    fixed = ledger.record_expense(Expense(chf("12.00"), date(2026, 10, 1), "Café", ("Food", "Out"),
                                          Provenance("d1", "page 1", Method.MANUAL, "user"),
                                          revises=first.id))
    ledger.record_expense(Expense(chf("30.00"), date(2026, 10, 2), "SBB", ("Transport",), prov()))
    assert [e.id for e in ledger.history(fixed.id)] == [first.id, fixed.id]
    tree = treemap.build(ledger.current_expenses()).to_dict()
    assert tree["total"] == "42.00"
    assert tree["children"][0]["name"] == "Transport"
    assert tree["children"][1]["children"][0]["expense_ids"] == [fixed.id]


def test_duplicate_bank_entries_are_imported_once():
    ledger = Ledger()
    for p in camt053.parse(CAMT, "s1") + camt053.parse(CAMT, "s2"):
        ledger.record_payment(p)
    assert len(ledger.current_payments()) == 3
