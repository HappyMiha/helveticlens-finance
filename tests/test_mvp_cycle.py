"""§16 acceptance: the full twelve-step cycle, on a photo, against PostgreSQL."""

from datetime import date
from decimal import Decimal

import psycopg
import pytest

from conftest import render_invoice_photo

INVOICE = [
    "Elektrizitätswerk Limmattal AG",
    "Werkstrasse 12, 8952 Schlieren",
    "",
    "Rechnung Nr. 2026-10-4471",
    "Rechnungsdatum: 12.10.2026",
    "Kundennummer 778 120",
    "Stromlieferung Oktober 2026",
    "Netznutzung               CHF   71.30",
    "Energie                   CHF   95.95",
    "MWST 8.1%                 CHF   17.25",
    "Total zu bezahlen         CHF  184.50",
    "Zahlbar bis 30.10.2026",
    "IBAN CH44 3199 9123 0008 8901 2",
]

CAMT = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>
<Id>STMT-2026-10</Id><Acct><Id><IBAN>CH9300762011623852957</IBAN></Id></Acct>
<Ntry><Amt Ccy="CHF">184.50</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-27</Dt></BookgDt>
<AcctSvcrRef>ZKB-20261027-001</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Nm>Elektrizitaetswerk Limmattal</Nm></Cdtr></RltdPties>
<RmtInf><Ustrd>Rechnung 2026-10-4471</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="CHF">67.80</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-15</Dt></BookgDt>
<AcctSvcrRef>ZKB-20261015-004</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Nm>Migros Zuerich</Nm></Cdtr></RltdPties>
</TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="CHF">6200.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-10-25</Dt></BookgDt>
<AcctSvcrRef>ZKB-20261025-002</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Dbtr><Nm>Muster AG</Nm></Dbtr></RltdPties>
<RmtInf><Ustrd>Lohn Oktober</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
</Stmt></BkToCstmrStmt></Document>"""

OCT = (date(2026, 10, 1), date(2026, 10, 31))


def test_full_cycle(lens):
    photo = render_invoice_photo(INVOICE)

    # 1–6: upload a photo; recognise, extract, create a record, categorise, store the original.
    res = lens.ingest(photo, "IMG_4471.jpg")
    assert res.doc_type == "invoice", res
    assert len(res.operation_ids) == 1, res.messages
    invoice_id = res.operation_ids[0]
    inv = lens.operation_detail(invoice_id)
    assert Decimal(inv["amount"]) == Decimal("184.50")
    assert inv["currency"] == "CHF"
    assert inv["op_date"] == "2026-10-12" and inv["due_date"] == "2026-10-30"
    assert "Elektrizit" in inv["counterparty"]
    assert inv["category_path"] == ["Housing", "Electricity"]
    assert inv["provenance"]["amount"]["quote"].lower().startswith("total")
    original, media, _ = lens.original(res.document_id)
    assert original == photo and media == "image/jpeg"

    # 7–9: import a bank statement; find the operation; link invoice and payment.
    stmt = lens.ingest(CAMT, "camt053_2026-10.xml")
    assert stmt.doc_type == "bank_statement" and len(stmt.operation_ids) == 3
    links = [l for l in lens.operation_detail(invoice_id)["links"] if l["status"] == "confirmed"]
    assert len(links) == 1 and links[0]["rule"] == "amount_date_counterparty"
    inv = lens.operation_detail(invoice_id)
    assert inv["verification"] == "confirmed"

    # 10: the expense is on the treemap, counted once (not again as a payment).
    tree = lens.treemap(*OCT)
    housing = next(c for c in tree["children"] if c["name"] == "Housing")
    assert housing["total"] == "184.50"
    groceries = next(c for c in tree["children"] if c["name"] == "Food")
    assert groceries["total"] == "67.80"
    assert tree["total"] == "252.30"  # 184.50 + 67.80, salary is income, not spend

    # 11: open the category and see all its operations.
    ops = lens.operations(*OCT, ("Housing",))
    assert [o["id"] for o in ops] == [invoice_id]

    # 12: every piece of evidence opens: original, extraction, linked payment, history.
    detail = lens.operation_detail(invoice_id)
    assert detail["documents"][0]["sha256"] and lens.files.verify(detail["documents"][0]["sha256"])
    assert "184.50" in detail["extractions"][0]["text"]
    assert detail["links"][0]["other_kind"] == "payment"
    assert [h["revision"] for h in detail["history"]] == [1, 2]
    assert detail["history"][0]["verification"] == "unconfirmed"

    # Totals: dashboard figures are exact and consistent with the treemap.
    dash = lens.dashboard(*OCT)
    assert dash["expenses"] == "252.30" and dash["income"] == "6200.00" and dash["balance"] == "5947.70"
    assert dash["bank_net"] == str(Decimal("6200.00") - Decimal("184.50") - Decimal("67.80"))
    assert not dash["unpaid"]


def test_history_is_append_only_and_corrections_teach(lens):
    op = lens.add_manual("expense", "42.00", "CHF", date(2026, 10, 3), "Velo Huber GmbH")
    assert lens.operation_detail(op)["verification"] == "unconfirmed"
    lens.correct(op, {"category": ("Transport", "Bike")}, "Bike service")
    detail = lens.operation_detail(op)
    assert detail["category_path"] == ["Transport", "Bike"] and len(detail["history"]) == 2
    with pytest.raises(psycopg.errors.RaiseException):
        lens.db.execute("UPDATE operation_revisions SET amount = 1")
    # The correction became a learned rule for the next record from the same counterparty.
    op2 = lens.add_manual("expense", "19.00", "CHF", date(2026, 10, 20), "Velo Huber GmbH")
    assert lens.operation_detail(op2)["category_path"] == ["Transport", "Bike"]


def test_same_file_twice_and_same_statement_twice(lens):
    lens.ingest(CAMT, "a.xml")
    again = lens.ingest(CAMT, "a-copy.xml")
    assert again.duplicate_of
    other = CAMT.replace(b"STMT-2026-10", b"STMT-2026-10-B")
    res = lens.ingest(other, "b.xml")
    assert res.operation_ids == [] and "already imported" in " ".join(res.messages)


def test_doubtful_documents_are_not_guessed(lens):
    res = lens.ingest("Notiz: Velo bringen\nMorgen anrufen".encode(), "note.txt", "text/plain")
    assert res.operation_ids == [] and "Nothing was guessed" in res.messages[0]


def test_qr_bill_photo_and_reference_match(lens):
    ref = "210000000003139471430009017"
    payload = "\n".join(["SPC", "0200", "1", "CH4431999123000889012", "S", "Wohnbau Genossenschaft Sihlfeld",
                         "Sihlfeldstrasse", "10", "8003", "Zürich", "CH"] + [""] * 7 +
                        ["1850.00", "CHF"] + [""] * 7 + ["QRR", ref, "Miete November", "EPD", ""])
    photo = render_invoice_photo(["Wohnbau Genossenschaft Sihlfeld", "Mietzins November 2026",
                                  "Datum 25.10.2026", "Betrag CHF 1'850.00"], qr_payload=payload, tilt=0.4, noise=False)
    res = lens.ingest(photo, "miete.jpg")
    op = lens.operation_detail(res.operation_ids[0])
    assert op["reference"] == ref and op["amount"] == "1850.00" and op["method"] == "structured_import"
    assert op["category_path"] == ["Housing", "Rent"]
    camt = (b'<?xml version="1.0"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt>'
            b'<Stmt><Ntry><Amt Ccy="CHF">1850.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-31</Dt></BookgDt>'
            b'<AcctSvcrRef>R1</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Nm>WBG</Nm></Cdtr></RltdPties>'
            b'<RmtInf><Strd><CdtrRefInf><Ref>' + ref.encode() + b'</Ref></CdtrRefInf></Strd></RmtInf>'
            b'</TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>')
    lens.ingest(camt, "nov.xml")
    detail = lens.operation_detail(res.operation_ids[0])
    assert detail["links"][0]["rule"] == "qr_reference" and detail["verification"] == "confirmed"


def test_weak_match_is_only_proposed(lens):
    op = lens.add_manual("expense", "20.00", "CHF", date(2026, 10, 1), "Kiosk am Bahnhof")
    camt = (b'<?xml version="1.0"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt>'
            b'<Stmt><Ntry><Amt Ccy="CHF">20.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-02</Dt></BookgDt>'
            b'<AcctSvcrRef>K1</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Nm>TWINT *P2P</Nm></Cdtr></RltdPties>'
            b'</TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>')
    lens.ingest(camt, "k.xml")
    link = lens.operation_detail(op)["links"][0]
    assert link["status"] == "proposed"
    assert lens.operation_detail(op)["verification"] == "unconfirmed"
    # Counted once on the treemap even while only proposed.
    assert lens.treemap(*OCT)["total"] == "20.00"
    lens.decide_link(str(link["id"]), accept=True)
    assert lens.operation_detail(op)["verification"] == "confirmed"


def test_scanned_pdf_and_tags(lens):
    import io

    from PIL import Image

    jpg = render_invoice_photo(["Garage Meier GmbH", "Rechnung 881", "Datum: 04.10.2026",
                                "Service Velo und Bremsen", "Total CHF 312.40"], noise=False, tilt=0)
    buf = io.BytesIO()
    Image.open(io.BytesIO(jpg)).save(buf, "PDF", resolution=150)
    res = lens.ingest(buf.getvalue(), "scan.pdf")
    op = lens.operation_detail(res.operation_ids[0])
    assert op["amount"] == "312.40" and op["category_path"] == ["Transport", "Car repairs"]
    lens.tag(res.operation_ids[0], "car")
    assert lens.operation_detail(res.operation_ids[0])["tags"] == ["car"]
    folder = lens.documents()[0]["folder"]
    assert folder == "2026/UNPAID_INVOICES"
