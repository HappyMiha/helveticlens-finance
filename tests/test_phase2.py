"""Phase 2: financial intelligence."""

from datetime import date
from decimal import Decimal

from financial_lens import analytics, assistant

REF = "210000000003139471430009017"


def camt(*entries) -> bytes:
    body = []
    for i, (amount, sign, day, party, extra) in enumerate(entries):
        party_tag = "Cdtr" if sign == "DBIT" else "Dbtr"
        body.append(f'<Ntry><Amt Ccy="{extra.get("ccy", "CHF")}">{amount}</Amt><CdtDbtInd>{sign}</CdtDbtInd>'
                    f'<BookgDt><Dt>{day}</Dt></BookgDt><AcctSvcrRef>{extra.get("id", f"{day}-{i}-{amount}")}</AcctSvcrRef>'
                    f'<NtryDtls><TxDtls><RltdPties><{party_tag}><Nm>{party}</Nm></{party_tag}></RltdPties><RmtInf>'
                    + (f'<Strd><CdtrRefInf><Ref>{extra["ref"]}</Ref></CdtrRefInf></Strd>' if "ref" in extra else "")
                    + f'<Ustrd>{extra.get("text", "")}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>')
    return ('<?xml version="1.0"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt>'
            '<Stmt>' + "".join(body) + '</Stmt></BkToCstmrStmt></Document>').encode()


def invoice(lens, amount, day, party, ref=None, due=None, category=("Housing", "Rent")):
    op = lens.add_manual("invoice", amount, "CHF", day, party, category)
    if ref or due:
        lens.correct(op, {k: v for k, v in (("reference", ref), ("due_date", due)) if v}, "from invoice")
    lens.reconcile()
    return op


def test_split_and_partial_payments_by_reference(lens):
    op = invoice(lens, "1000.00", date(2026, 9, 1), "Wohnbau AG", ref=REF)
    lens.ingest(camt(("400.00", "DBIT", "2026-09-05", "Wohnbau AG", {"ref": REF})), "a.xml")
    st = lens.payment_status(op)
    assert st["state"] == "partially_paid" and st["open"] == "600.00"
    assert "Partially paid" in lens.operation_detail(op)["verification_reason"]
    lens.ingest(camt(("600.00", "DBIT", "2026-09-20", "Wohnbau AG", {"ref": REF})), "b.xml")
    assert lens.payment_status(op)["state"] == "paid"
    detail = lens.operation_detail(op)
    assert detail["verification"] == "confirmed" and len(detail["links"]) == 2
    # counted once: 1000 on the treemap, not 2000
    assert lens.treemap(date(2026, 9, 1), date(2026, 9, 30))["total"] == "1000.00"


def test_overpayment_needs_review_and_surplus_is_visible(lens):
    op = invoice(lens, "100.00", date(2026, 9, 1), "Gemeinde Wasser", ref=REF)
    lens.ingest(camt(("120.00", "DBIT", "2026-09-10", "Gemeinde", {"ref": REF})), "o.xml")
    assert lens.payment_status(op)["state"] == "overpaid"
    assert lens.operation_detail(op)["verification"] == "needs_review"
    # the 20.00 not explained by a document is still counted, honestly
    assert lens.treemap(date(2026, 9, 1), date(2026, 9, 30))["total"] == "120.00"


def test_refund_is_proposed_then_nets_the_category(lens):
    lens.ingest(camt(("250.00", "DBIT", "2026-09-02", "Velo Shop Bern", {}),
                     ("80.00", "CRDT", "2026-09-12", "Velo Shop Bern", {"text": "Gutschrift Retoure"})), "r.xml")
    links = lens.db.execute("SELECT * FROM links WHERE link_type='refund'").fetchall()
    assert len(links) == 1 and links[0]["status"] == "proposed"
    lens.decide_link(str(links[0]["id"]), True)
    tree = lens.treemap(date(2026, 9, 1), date(2026, 9, 30))
    assert tree["total"] == "170.00"
    assert lens.dashboard(date(2026, 9, 1), date(2026, 9, 30))["income"] == "0"


def test_duplicate_document_is_flagged_not_dropped(lens):
    a = lens.add_manual("receipt", "54.20", "CHF", date(2026, 9, 3), "Migros Zürich")
    # same receipt arriving again from another document (e.g. scan and photo)
    lens.db.execute("SELECT 1")
    with lens.db.transaction():
        b = lens._new_operation("receipt", {"amount": Decimal("54.20"), "currency": "CHF", "op_date": date(2026, 9, 3),
                                            "counterparty": "MIGROS ZUERICH", "verification": "unconfirmed",
                                            "method": "ocr", "agent": "test"})
        lens._find_duplicates(b)
    d = lens.operation_detail(b)
    assert d["verification"] == "needs_review" and d["links"][0]["link_type"] == "duplicate"
    assert lens.treemap(date(2026, 9, 1), date(2026, 9, 30))["total"] == "108.40"  # both visible until decided
    lens.decide_link(str(d["links"][0]["id"]), True)
    assert lens.treemap(date(2026, 9, 1), date(2026, 9, 30))["total"] == "54.20"
    assert a != b


def test_multi_currency_uses_recorded_rates_only(lens):
    lens.add_manual("expense", "100.00", "EUR", date(2026, 9, 10), "Hotel Como", ("Leisure", "Travel"))
    tree = lens.treemap(date(2026, 9, 1), date(2026, 9, 30))
    assert tree["total"] == "0" and len(tree["unconverted"]) == 1
    lens.set_fx_rate("EUR", date(2026, 9, 1), "0.9412", "SNB monthly average")
    tree = lens.treemap(date(2026, 9, 1), date(2026, 9, 30))
    assert tree["total"] == "94.12" and not tree["unconverted"]
    op = lens.add_manual("expense", "10.00", "EUR", date(2026, 9, 12), "Bar Como", ("Leisure", "Travel"))
    detail = lens.operation_detail(op)
    assert detail["fx_rate"].startswith("0.9412") and "SNB" in detail["fx_source"]


def test_payslip_matches_salary(lens):
    with lens.db.transaction():
        s = lens._new_operation("payslip", {"amount": Decimal("6200.00"), "currency": "CHF", "op_date": date(2026, 9, 25),
                                            "counterparty": "Muster AG", "category_id": lens.category_id(("Salary",), "income"),
                                            "verification": "unconfirmed", "method": "ocr", "agent": "test"})
    lens.ingest(camt(("6200.00", "CRDT", "2026-09-25", "MUSTER AG", {"text": "Lohn September"})), "s.xml")
    assert lens.operation_detail(s)["verification"] == "confirmed"
    assert lens.dashboard(date(2026, 9, 1), date(2026, 9, 30))["income"] == "6200.00"  # once, not twice


def test_csv_and_xlsx_bank_exports(lens):
    csv = ("Buchungsdatum;Buchungstext;Belastung;Gutschrift;Saldo\n"
           "03.09.2026;Coop Pronto Bern;12.50;;1000.00\n"
           "03.09.2026;Coop Pronto Bern;12.50;;987.50\n"
           "05.09.2026;Rückerstattung Krankenkasse;;45.00;1032.50\n"
           "kaputt;;;;\n").encode()
    res = lens.ingest(csv, "konto.csv")
    assert len(res.operation_ids) == 3 and any("skipped" in m for m in res.messages)
    again = lens.ingest(csv.replace(b"kaputt", b"broken"), "konto2.csv")
    assert again.operation_ids == []
    from openpyxl import Workbook
    import io
    wb = Workbook()
    ws = wb.active
    ws.append(["Date", "Description", "Amount", "Currency"])
    ws.append([date(2026, 9, 7), "SBB CFF FFS", -55.0, "CHF"])
    buf = io.BytesIO()
    wb.save(buf)
    res = lens.ingest(buf.getvalue(), "export.xlsx")
    op = lens.operation_detail(res.operation_ids[0])
    assert op["amount"] == "-55.00" and op["category_path"] == ["Transport", "Public transport"]


def test_recurring_unpaid_and_analytics(lens):
    for m in range(3, 10):
        lens.ingest(camt((f"{1850 + (m % 2) * 5}.00", "DBIT", f"2026-{m:02d}-01", "Wohnbau Genossenschaft",
                          {"text": "Miete"})), f"m{m}.xml")
    rec = analytics.save_recurring(lens, until=date(2026, 9, 30))
    assert rec and rec[0]["cadence"] == "monthly" and rec[0]["next_expected"] == "2026-10-01"
    assert analytics.missing_recurring(lens, today=date(2026, 10, 15))
    op = invoice(lens, "300.00", date(2026, 9, 1), "Zahnarzt Dr. Weber", due=date(2026, 9, 30),
                 category=("Healthcare", "Dentist"))
    late = analytics.unpaid(lens, today=date(2026, 10, 10))
    assert late[0]["operation_id"] == op and late[0]["overdue"] and late[0]["days_overdue"] == 10
    flow = analytics.cash_flow(lens, date(2026, 8, 1), date(2026, 9, 30))
    assert flow[0]["expenses"] == "1850.00" and Decimal(flow[1]["cumulative"]) == -(Decimal("1850") + Decimal("1855") + Decimal("300"))
    cmp = analytics.compare(lens, (date(2026, 8, 1), date(2026, 8, 31)), (date(2026, 9, 1), date(2026, 9, 30)))
    assert {tuple(r["category"]) for r in cmp} >= {("Housing",), ("Healthcare",)}
    assert analytics.previous_period(date(2026, 9, 1), date(2026, 9, 30)) == (date(2026, 8, 1), date(2026, 8, 31))
    top = analytics.top_expenses(lens, date(2026, 1, 1), date(2026, 12, 31), 1)
    assert top[0]["amount"] == "1855.00"
    assert analytics.by_counterparty(lens, date(2026, 1, 1), date(2026, 12, 31))[0]["count"] == 7


def test_assistant_questions(lens):
    lens.ingest(camt(("54.20", "DBIT", "2026-09-03", "Migros", {}), ("612.00", "DBIT", "2026-09-04", "Swisscom", {}),
                     ("39.90", "DBIT", "2026-08-04", "Swisscom", {})), "q.xml")
    invoice(lens, "300.00", date(2026, 9, 1), "Zahnarzt Dr. Weber", due=date(2026, 9, 30), category=("Healthcare", "Dentist"))
    today = date(2026, 10, 5)
    a = assistant.ask(lens, "Скільки я витратив на їжу цього року?", today)
    assert a["total"] == "54.20" and a["query"]["category"] == ["Food"]
    a = assistant.ask(lens, "Show all expenses over 500 CHF", today)
    assert [i["label"].split(" · ")[1] for i in a["items"]] == ["Swisscom"]
    a = assistant.ask(lens, "Alle Zahlungen an Swisscom", today)
    assert a["total"] == "651.90" and len(a["items"]) == 2
    a = assistant.ask(lens, "unpaid invoices", today)
    assert len(a["items"]) == 1 and "overdue" in a["items"][0]["label"]
    a = assistant.ask(lens, "transactions without evidence", today)
    assert len(a["items"]) == 4
    a = assistant.ask(lens, "documents not linked to a bank transaction", today)
    assert a["computed_by"] == "deterministic ledger query"
