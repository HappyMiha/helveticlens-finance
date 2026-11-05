"""Synthetic but realistic Swiss documents in different layouts (no real data).

Each generator varies language, column order and wording so the analysts are tested on
structure and arithmetic, not on one template."""

import io
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def _pdf(draw) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    draw(c)
    c.showPage()
    c.save()
    return buf.getvalue()


def _money(v: Decimal) -> str:
    s = f"{abs(v):,.2f}".replace(",", "'")
    return ("-" if v < 0 else "") + s


def payslip_de(gross="6500.00", child="215.00", expenses="0", wrong_net=False, payout_label="Auszahlung") -> bytes:
    g = Decimal(gross)
    ded = [("AHV/IV/EO", "5.300 %", g * Decimal("0.053")), ("ALV", "1.100 %", g * Decimal("0.011")),
           ("NBU", "1.200 %", g * Decimal("0.012")), ("BVG Pensionskasse", "", Decimal("412.35")),
           ("Quellensteuer", "8.20 %", g * Decimal("0.082"))]
    ded = [(n, r, v.quantize(Decimal("0.05"))) for n, r, v in ded]
    total_ded = sum(v for _, _, v in ded)
    net = g - total_ded + Decimal(child)
    payout = net + Decimal(expenses)
    if wrong_net:
        net += Decimal("100.00")

    def draw(c):
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, 800, "Muster Treuhand AG")
        c.setFont("Helvetica", 10)
        c.drawString(50, 786, "Bahnhofstrasse 1, 8001 Zürich")
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, 750, "Lohnabrechnung Oktober 2026")
        c.setFont("Helvetica", 10)
        c.drawString(50, 734, "Mitarbeiter: Anna Keller · Personal-Nr. 1042")
        y = 700
        for label, rate, basis, amount in [("Monatslohn", "", "", _money(g)), ("Bruttolohn", "", "", _money(g))]:
            c.drawString(50, y, label); c.drawRightString(480, y, amount); y -= 16
        y -= 6
        for n, r, v in ded:
            c.drawString(50, y, n); c.drawString(250, y, r); c.drawRightString(370, y, _money(g)); c.drawRightString(480, y, "-" + _money(v)); y -= 16
        c.drawString(50, y, "Total Abzüge"); c.drawRightString(480, y, "-" + _money(total_ded)); y -= 22
        c.drawString(50, y, "Kinderzulage"); c.drawRightString(480, y, _money(Decimal(child))); y -= 16
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, "Nettolohn"); c.drawRightString(480, y, _money(net)); y -= 16
        c.setFont("Helvetica", 10)
        if Decimal(expenses):
            c.drawString(50, y, "Spesen Pauschal"); c.drawRightString(480, y, _money(Decimal(expenses))); y -= 16
        c.drawString(50, y, payout_label); c.drawRightString(480, y, _money(payout)); y -= 16
        c.drawString(50, y - 10, "Auszahlungsdatum 25.10.2026 · IBAN CH93 0076 2011 6238 5295 7")
    return _pdf(draw), {"net": net, "payout": payout, "gross": g, "deductions": total_ded}


def payslip_fr(gross="7200.00") -> bytes:
    g = Decimal(gross)
    ded = [("AVS/AI/APG", g * Decimal("0.053")), ("AC", g * Decimal("0.011")), ("AANP", g * Decimal("0.0095")),
           ("LPP caisse de pension", Decimal("455.10"))]
    ded = [(n, v.quantize(Decimal("0.05"))) for n, v in ded]
    net = g - sum(v for _, v in ded)

    def draw(c):
        c.setFont("Helvetica-Bold", 12)
        c.drawString(60, 805, "Atelier Romand Sàrl")
        c.setFont("Helvetica", 10)
        c.drawString(60, 770, "Bulletin de salaire — novembre 2026")
        c.drawString(330, 770, "Collaborateur : M. Rossi")
        y = 730
        c.drawString(60, y, "Salaire de base"); c.drawRightString(520, y, _money(g)); y -= 15
        c.drawString(60, y, "Salaire brut"); c.drawRightString(520, y, _money(g)); y -= 20
        for n, v in ded:
            c.drawString(60, y, n); c.drawRightString(520, y, _money(-v)); y -= 15
        c.drawString(60, y - 5, "Salaire net"); c.drawRightString(520, y - 5, _money(net))
        c.drawString(60, y - 30, "Montant versé le 25.11.2026"); c.drawRightString(520, y - 30, _money(net))
    return _pdf(draw), {"net": net}


def statement_columns(break_balance=False) -> bytes:
    """German, separate debit/credit columns, running balance, multi-line texts."""
    opening = Decimal("4210.35")
    rows = [("02.10.2026", ["Zahlung an Elektrizitätswerk", "Rechnung 2026-10-4471"], Decimal("-184.50")),
            ("05.10.2026", ["Einkauf Migros Zürich", "Karte ****1234"], Decimal("-67.80")),
            ("25.10.2026", ["Gutschrift Muster Treuhand AG", "Lohn Oktober 2026"], Decimal("6198.95")),
            ("28.10.2026", ["Dauerauftrag Wohnbau Genossenschaft"], Decimal("-1850.00")),
            ("30.10.2026", ["TWINT Kiosk am Bahnhof"], Decimal("-12.40"))]

    def draw(c):
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, 800, "Zürcher Testbank AG")
        c.setFont("Helvetica", 10)
        c.drawString(50, 780, "Kontoauszug 01.10.2026 – 31.10.2026")
        c.drawString(50, 766, "Privatkonto CH93 0076 2011 6238 5295 7 · CHF")
        y = 730
        c.setFont("Helvetica-Bold", 9)
        for x, h in [(50, "Datum"), (115, "Text"), (360, "Belastung"), (430, "Gutschrift"), (500, "Saldo")]:
            c.drawString(x, y, h)
        c.setFont("Helvetica", 9)
        y -= 16
        c.drawString(115, y, "Saldo alt"); c.drawRightString(545, y, _money(opening)); y -= 16
        bal = opening
        for d, text, amt in rows:
            bal += amt
            shown = bal + (Decimal("10.00") if break_balance and d.startswith("28") else 0)
            c.drawString(50, y, d); c.drawString(115, y, text[0])
            if amt < 0:
                c.drawRightString(410, y, _money(-amt))
            else:
                c.drawRightString(480, y, _money(amt))
            c.drawRightString(545, y, _money(shown)); y -= 13
            for extra in text[1:]:
                c.drawString(115, y, extra); y -= 13
            y -= 3
        c.setFont("Helvetica-Bold", 9)
        c.drawString(115, y, "Schlusssaldo"); c.drawRightString(545, y, _money(bal))
    return _pdf(draw), {"opening": opening, "rows": rows}


def statement_signed_fr() -> bytes:
    """French, one signed amount column, balance first, date without year."""
    opening = Decimal("1200.00")
    rows = [("03.11", "Achat Coop Lausanne", Decimal("-45.20")), ("10.11", "Virement de Atelier Romand Sàrl", Decimal("6107.10")),
            ("15.11", "Paiement à Swisscom", Decimal("-79.00"))]

    def draw(c):
        c.setFont("Helvetica", 10)
        c.drawString(60, 800, "Banque Exemple SA — Relevé de compte novembre 2026")
        c.drawString(60, 786, "Période 01.11.2026 - 30.11.2026 · IBAN CH56 0483 5012 3456 7800 9")
        y = 750
        for x, h in [(60, "Date"), (120, "Libellé"), (380, "Solde"), (470, "Montant")]:
            c.drawString(x, y, h)
        y -= 16
        c.drawString(120, y, "Solde initial"); c.drawRightString(430, y, _money(opening)); y -= 15
        bal = opening
        for d, t, a in rows:
            bal += a
            c.drawString(60, y, d); c.drawString(120, y, t); c.drawRightString(430, y, _money(bal)); c.drawRightString(530, y, _money(a)); y -= 15
        c.drawString(120, y, "Solde final"); c.drawRightString(430, y, _money(bal))
    return _pdf(draw), {"rows": rows}


def invoice_with_decoys() -> bytes:
    def draw(c):
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, 800, "Velo Huber GmbH")
        c.setFont("Helvetica", 10)
        c.drawString(50, 770, "Rechnung Nr. 5512 · Rechnungsdatum 14.10.2026")
        y = 730
        for t, a in [("Service Velo", "120.00"), ("Bremsbeläge 2 Stk.", "48.00"), ("Kette", "39.00")]:
            c.drawString(50, y, t); c.drawRightString(500, y, a); y -= 15
        c.drawString(50, y, "Rabatt Stammkunde"); c.drawRightString(500, y, "-20.70"); y -= 15
        c.drawString(50, y, "Total exkl. MWST"); c.drawRightString(500, y, "186.30"); y -= 15
        c.drawString(50, y, "MWST 8.1 %"); c.drawRightString(500, y, "15.10"); y -= 15
        c.drawString(50, y, "Total CHF"); c.drawRightString(500, y, "201.40"); y -= 15
        c.drawString(50, y, "Zahlbar bis 13.11.2026 · Kundennummer 778.120 · Tel. 044 123 45 67")
    return _pdf(draw), {"total": Decimal("201.40")}


def as_photo(pdf: bytes) -> bytes:
    """Render the first page like a phone photo (OCR path, word boxes from Tesseract)."""
    import pypdfium2 as pdfium
    from PIL import ImageFilter

    page = pdfium.PdfDocument(pdf)[0]
    img = page.render(scale=2.2).to_pil().convert("RGB").rotate(0.6, expand=False, fillcolor="white").filter(ImageFilter.GaussianBlur(0.6))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def statement_no_header() -> bytes:
    """No column header at all: the sign can only come from the running balance."""
    rows = [("01.12.2026", "Gutschrift Kundenzahlung", Decimal("950.00")), ("03.12.2026", "Coop Pronto", Decimal("-23.70")),
            ("07.12.2026", "SBB Mobile", Decimal("-8.80"))]

    def draw(c):
        c.setFont("Helvetica", 10)
        c.drawString(50, 800, "Kontoauszug Dezember 2026 · CH93 0076 2011 6238 5295 7")
        y = 770
        c.drawString(50, y, "Saldovortrag"); c.drawRightString(530, y, "300.00"); y -= 15
        bal = Decimal("300.00")
        for d, t, a in rows:
            bal += a
            c.drawString(50, y, d); c.drawString(130, y, t); c.drawRightString(430, y, _money(abs(a))); c.drawRightString(530, y, _money(bal)); y -= 15
        c.drawString(50, y, "Neuer Saldo"); c.drawRightString(530, y, _money(bal))
    return _pdf(draw), {"rows": rows}


def receipt_with_change() -> bytes:
    def draw(c):
        c.setFont("Courier", 10)
        y = 800
        for t, a in [("Bäckerei Frey AG", ""), ("Quittung 12.12.2026 07:41", ""), ("Gipfeli 3x", "4.80"), ("Ruchbrot", "5.20"),
                     ("Kaffee", "4.50"), ("TOTAL CHF", "14.50"), ("Bar", "20.00"), ("Rückgeld", "5.50"), ("inkl. MWST 2.6%", "0.37")]:
            c.drawString(50, y, t)
            if a:
                c.drawRightString(260, y, a)
            y -= 13
    return _pdf(draw), {"total": Decimal("14.50")}


def statement_bkb_en() -> bytes:
    """English statement with BKB-style booking texts, card and booking numbers and OCR-like debris."""
    opening = Decimal("9000.00")
    rows = [
        ("01.10.2026", ["purchase of goods and services abroad", "Withdrawal location: BKGBOOKINGCOM HOTE",
                        "Transaction date: / 11:36:30 Card no.: 4871 52** **** 7"], Decimal("-312.40")),
        ("02.10.2026", ["atm Cash withdrawal ATM", "Withdrawal location: BKB VOGESENPLATZ 63",
                        "Transaction date: / 20:31:21 Card no.: 4871 52** **** 7"], Decimal("-200.00")),
        ("03.10.2026", ["debit collective order of 2 4 4 0 1", "BKB Booking No. 1236984944"], Decimal("-4591.15")),
        ("04.10.2026", ["Revolut Bank UAB Konstitucijos ave. 21B", "LT-Vilnius Lithuania Mykhailo Shavrytskyi, CH",
                        "BKB Booking No. 1229000001"], Decimal("-1000.00")),
        ("05.10.2026", ["purchase of goods and services", "Withdrawal location: Migros M Mulhauserst",
                        "Transaction date: / 16:27:06 Card no.: 4871 52** **** 7"], Decimal("-45.10")),
        ("06.10.2026", ["payment SBB EASYRIDE, BERN", "T M _ T D _ T M BKB Booking No. 1237488234"], Decimal("-18.60")),
    ]

    def draw(c):
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, 800, "Basler Kantonalbank")
        c.setFont("Helvetica", 10)
        c.drawString(50, 784, "Mykhailo Shavrytskyi")
        c.drawString(50, 770, "Statement of account 01.10.2026 - 31.10.2026")
        c.drawString(50, 756, "Private account CH93 0076 2011 6238 5295 7 CHF")
        y = 720
        c.setFont("Helvetica-Bold", 9)
        for x, h in [(50, "Date"), (115, "Text"), (360, "Debit"), (430, "Credit"), (500, "Balance")]:
            c.drawString(x, y, h)
        c.setFont("Helvetica", 9)
        y -= 16
        c.drawString(115, y, "Opening balance"); c.drawRightString(545, y, _money(opening)); y -= 16
        bal = opening
        for d, text, amt in rows:
            bal += amt
            c.drawString(50, y, d); c.drawString(115, y, text[0])
            c.drawRightString(410, y, _money(-amt))
            c.drawRightString(545, y, _money(bal)); y -= 13
            for extra in text[1:]:
                c.drawString(115, y, extra); y -= 13
            y -= 3
        c.setFont("Helvetica-Bold", 9)
        c.drawString(115, y, "Closing balance"); c.drawRightString(545, y, _money(bal))
    return _pdf(draw)
