"""Evaluate document understanding with and without a model on the same varied documents.

The corpus is generated (no real data): payslips, statements and invoices in four languages,
with different wording, column orders and layouts, as text PDFs and as photos. Each document
knows its true values, so every reading is scored, and the most important number is reported:
**false confirmations** — documents marked consistent although a value is wrong (must be zero).

Run:  financial-lens eval [--model http://127.0.0.1:18765/v1] [--photos]
"""

from __future__ import annotations

import io
import random
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

from .extract import ocr, understand


def _m(v: Decimal, sep="'") -> str:
    s = f"{abs(v):,.2f}".replace(",", sep)
    return ("-" if v < 0 else "") + s


def _pdf(draw) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    draw(c)
    c.showPage()
    c.save()
    return buf.getvalue()


@dataclass
class Doc:
    name: str
    kind: str
    data: bytes
    truth: dict
    media: str = "application/pdf"


PAYSLIP_WORDS = {
    "de": dict(title=["Lohnabrechnung", "Gehaltsabrechnung", "Lohnabrechnung Monat"], base=["Monatslohn", "Grundlohn", "Gehalt"],
               gross=["Bruttolohn", "Total Brutto", "Bruttogehalt", "Lohn brutto", "Gesamtbrutto"],
               ded=[["AHV/IV/EO", "AHV-Beitrag", "AHV IV EO"], ["ALV", "Arbeitslosenversicherung"], ["NBU", "Nichtberufsunfall"],
                    ["BVG", "Pensionskasse", "BVG Beitrag"], ["Quellensteuer"]],
               total_ded=["Total Abzüge", "Abzüge total", "Sozialabzüge total"], child=["Kinderzulage", "Familienzulage"],
               net=["Nettolohn", "Netto-Lohn", "Nettogehalt"], payout=["Auszahlung", "Auszahlungsbetrag", "Überweisung"],
               paid=["Auszahlungsdatum", "Ausbezahlt am"], month=["Oktober"]),
    "fr": dict(title=["Bulletin de salaire", "Décompte de salaire", "Fiche de paie"], base=["Salaire de base", "Salaire mensuel"],
               gross=["Salaire brut", "Total brut"], ded=[["AVS/AI/APG", "Cotisation AVS"], ["AC", "Assurance chômage"],
                                                         ["AANP"], ["LPP", "Caisse de pension"], ["Impôt à la source"]],
               total_ded=["Total des retenues", "Total déductions"], child=["Allocation familiale", "Allocations enfants"],
               net=["Salaire net"], payout=["Montant versé", "Versement"], paid=["Versé le", "Date de paiement"], month=["octobre"]),
    "it": dict(title=["Conteggio salario", "Busta paga"], base=["Salario base"], gross=["Salario lordo"],
               ded=[["AVS/AI/IPG"], ["AD"], ["AINP"], ["LPP", "Cassa pensione"], ["Imposta alla fonte"]],
               total_ded=["Totale deduzioni"], child=["Assegno familiare"], net=["Salario netto"],
               payout=["Importo versato"], paid=["Data di pagamento", "Pagato il"], month=["ottobre"]),
    "en": dict(title=["Payslip", "Salary slip"], base=["Base salary"], gross=["Gross salary", "Gross pay"],
               ded=[["AHV/IV/EO social security"], ["Unemployment insurance ALV"], ["Accident insurance NBU"],
                    ["Pension fund BVG"], ["Withholding tax"]],
               total_ded=["Total deductions"], child=["Child allowance"], net=["Net salary", "Net pay"],
               payout=["Net payment", "Payout"], paid=["Payment date", "Paid on"], month=["October"]),
}


# Wording that the rules were NOT written for: tests generalisation, not memory.
HARD_PAYSLIP = {
    "de": dict(title=["Monatsabrechnung Personal", "Verdienstnachweis"], base=["Fixum", "Lohn vereinbart"],
               gross=["Lohnsumme vor Abzügen", "Summe Bezüge"],
               ded=[["Sozialversicherung 1. Säule"], ["Erwerbslosenkasse"], ["Freizeitunfall"], ["2. Säule Beitrag AN"],
                    ["Steuerabzug an der Quelle"]],
               total_ded=["Summe Abzüge"], child=["Kinderzulage gemäss FamZG"], net=["Verbleibender Lohn", "Lohn nach Abzügen"],
               payout=["Ausbezahlter Betrag", "Gutschrift auf Konto"], paid=["Valuta"], month=["Oktober"]),
    "en": dict(title=["Earnings statement", "Remuneration statement"], base=["Agreed monthly pay"],
               gross=["Total earnings", "Earnings before deductions"],
               ded=[["First pillar contributions"], ["Jobless insurance"], ["Non-occupational accident cover"],
                    ["Second pillar employee share"], ["Source tax"]],
               total_ded=["Sum of deductions"], child=["Family allowance"], net=["Take-home pay", "Remaining pay"],
               payout=["Transferred to your account"], paid=["Value date"], month=["October"]),
}


def gen_payslip(rng: random.Random, lang: str, hard: bool = False) -> Doc:
    W = (HARD_PAYSLIP if hard else PAYSLIP_WORDS)[lang]
    g = Decimal(rng.randrange(420000, 980000, 5)) / 100
    rates = [Decimal("0.053"), Decimal("0.011"), Decimal(rng.choice(["0.0095", "0.012", "0.014"])), None,
             Decimal(rng.choice(["0", "0.045", "0.082", "0.11"]))]
    deds = []
    for names, r in zip(W["ded"], rates):
        v = (g * r).quantize(Decimal("0.05")) if r is not None else Decimal(rng.randrange(25000, 60000, 5)) / 100
        if v:
            deds.append((rng.choice(names), r, v))
    child = Decimal(rng.choice(["0", "215.00", "430.00"]))
    expenses = Decimal(rng.choice(["0", "0", "150.00"]))
    total_ded = sum(v for _, _, v in deds)
    net = g - total_ded + child
    payout = net + expenses
    neg = rng.random() < 0.5
    show_total = rng.random() < 0.7
    show_basis = rng.random() < 0.6
    sep = rng.choice(["'", "’", " "]) if lang != "en" else ","
    employer = rng.choice(["Muster Treuhand AG", "Atelier Romand Sàrl", "Ticino Servizi SA", "Alpine Tech GmbH"])

    def draw(c):
        c.setFont("Helvetica-Bold", 13); c.drawString(50, 800, employer)
        c.setFont("Helvetica", 10); c.drawString(50, 785, "Musterweg 3, 3000 Bern")
        c.setFont("Helvetica-Bold", 12); c.drawString(50, 755, f"{rng.choice(W['title'])} {W['month'][0]} 2026")
        c.setFont("Helvetica", 10)
        y = 720
        c.drawString(50, y, rng.choice(W["base"])); c.drawRightString(490, y, _m(g, sep)); y -= 16
        c.drawString(50, y, rng.choice(W["gross"])); c.drawRightString(490, y, _m(g, sep)); y -= 22
        for n, r, v in deds:
            c.drawString(50, y, n)
            if show_basis and r:
                c.drawString(250, y, f"{r * 100:.3f} %"); c.drawRightString(380, y, _m(g, sep))
            c.drawRightString(490, y, ("-" if neg else "") + _m(v, sep)); y -= 15
        if show_total:
            c.drawString(50, y, rng.choice(W["total_ded"])); c.drawRightString(490, y, ("-" if neg else "") + _m(total_ded, sep)); y -= 20
        if child:
            c.drawString(50, y, rng.choice(W["child"])); c.drawRightString(490, y, _m(child, sep)); y -= 16
        c.setFont("Helvetica-Bold", 10); c.drawString(50, y, rng.choice(W["net"])); c.drawRightString(490, y, _m(net, sep)); y -= 16
        c.setFont("Helvetica", 10)
        if expenses:
            c.drawString(50, y, {"de": "Spesen", "fr": "Frais", "it": "Spese", "en": "Expenses"}[lang]); c.drawRightString(490, y, _m(expenses, sep)); y -= 16
        c.drawString(50, y, rng.choice(W["payout"])); c.drawRightString(490, y, _m(payout, sep)); y -= 20
        c.drawString(50, y, f"{rng.choice(W['paid'])} 25.10.2026")
    return Doc(f"payslip-{lang}{'-hard' if hard else ''}", "payslip", _pdf(draw), {"amount": payout})


def gen_statement(rng: random.Random, lang: str) -> Doc:
    H = {"de": ("Datum", "Text", "Belastung", "Gutschrift", "Saldo", "Kontoauszug", "Saldo alt", "Schlusssaldo"),
         "fr": ("Date", "Libellé", "Débit", "Crédit", "Solde", "Relevé de compte", "Solde initial", "Solde final"),
         "it": ("Data", "Descrizione", "Addebito", "Accredito", "Saldo", "Estratto conto", "Saldo iniziale", "Saldo finale"),
         "en": ("Date", "Description", "Debit", "Credit", "Balance", "Account statement", "Opening balance", "Closing balance")}[lang]
    opening = Decimal(rng.randrange(10000, 900000)) / 100
    texts = ["Coop", "Migros", "SBB", "Swisscom", "Wohnbau AG", "Kiosk", "Salt", "Apotheke", "Steueramt", "Muster AG Lohn"]
    rows = []
    for d in sorted(rng.sample(range(1, 29), rng.randint(4, 9))):
        a = Decimal(rng.randrange(500, 250000)) / 100
        rows.append((f"{d:02d}.10.2026", rng.choice(texts), a if rng.random() < 0.2 else -a))
    layout = rng.choice(["columns", "signed", "columns_balance_first"])
    sep = "'" if lang != "en" else ","

    def draw(c):
        c.setFont("Helvetica", 10)
        c.drawString(50, 800, f"Testbank AG · {H[5]} 01.10.2026 – 31.10.2026 · CH93 0076 2011 6238 5295 7")
        y = 760
        heads = [(50, H[0]), (120, H[1]), (360, H[2]), (430, H[3]), (500, H[4])] if layout == "columns" else \
                [(50, H[0]), (120, H[1]), (360, H[4]), (470, {"de": "Betrag", "fr": "Montant", "it": "Importo", "en": "Amount"}[lang])] \
                if layout == "signed" else [(50, H[0]), (120, H[1]), (330, H[4]), (420, H[2]), (500, H[3])]
        for x, h in heads:
            c.drawString(x, y, h)
        y -= 16
        bal_x = {"columns": 545, "signed": 410, "columns_balance_first": 380}[layout]
        c.drawString(120, y, H[6]); c.drawRightString(bal_x, y, _m(opening, sep)); y -= 15
        bal = opening
        for d, t, a in rows:
            bal += a
            c.drawString(50, y, d); c.drawString(120, y, t)
            if layout == "columns":
                c.drawRightString(410 if a < 0 else 480, y, _m(abs(a), sep)); c.drawRightString(545, y, _m(bal, sep))
            elif layout == "signed":
                c.drawRightString(410, y, _m(bal, sep)); c.drawRightString(530, y, _m(a, sep))
            else:
                c.drawRightString(380, y, _m(bal, sep)); c.drawRightString(470 if a < 0 else 545, y, _m(abs(a), sep))
            y -= 15
        c.drawString(120, y, H[7]); c.drawRightString(bal_x, y, _m(bal, sep))
    return Doc(f"statement-{lang}-{layout}", "bank_statement", _pdf(draw), {"rows": [a for _, _, a in rows]})


def gen_invoice(rng: random.Random, lang: str) -> Doc:
    W = {"de": ("Rechnung", "Total exkl. MWST", "MWST", "Total CHF", "Zahlbar bis", "Rabatt"),
         "fr": ("Facture", "Total hors TVA", "TVA", "Total CHF", "Payable jusqu'au", "Remise"),
         "it": ("Fattura", "Totale imponibile", "IVA", "Totale CHF", "Pagabile entro", "Sconto"),
         "en": ("Invoice", "Subtotal excl. VAT", "VAT", "Total CHF", "Payable by", "Discount")}[lang]
    items = [Decimal(rng.randrange(1000, 90000)) / 100 for _ in range(rng.randint(2, 5))]
    disc = Decimal(rng.choice(["0", "0", "15.00"]))
    net = sum(items) - disc
    vat = (net * Decimal("0.081")).quantize(Decimal("0.05"))
    total = net + vat

    def draw(c):
        c.setFont("Helvetica-Bold", 12); c.drawString(50, 800, rng.choice(["Velo Huber GmbH", "Garage Meier AG", "Imprimerie Léman SA"]))
        c.setFont("Helvetica", 10); c.drawString(50, 770, f"{W[0]} 5512 · 14.10.2026")
        y = 730
        for i, a in enumerate(items):
            c.drawString(50, y, f"Position {i + 1}"); c.drawRightString(500, y, _m(a)); y -= 15
        if disc:
            c.drawString(50, y, W[5]); c.drawRightString(500, y, "-" + _m(disc)); y -= 15
        c.drawString(50, y, W[1]); c.drawRightString(500, y, _m(net)); y -= 15
        c.drawString(50, y, f"{W[2]} 8.1 %"); c.drawRightString(500, y, _m(vat)); y -= 15
        c.drawString(50, y, W[3]); c.drawRightString(500, y, _m(total)); y -= 15
        c.drawString(50, y, f"{W[4]} 13.11.2026 · Tel. 044 123 45 67")
    return Doc(f"invoice-{lang}", "invoice", _pdf(draw), {"amount": total})


def to_photo(doc: Doc, rng: random.Random) -> Doc:
    import pypdfium2 as pdfium
    from PIL import ImageFilter

    img = pdfium.PdfDocument(doc.data)[0].render(scale=2.2).to_pil().convert("RGB")
    img = img.rotate(rng.uniform(-1.2, 1.2), fillcolor="white").filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.9)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=rng.randint(70, 90))
    return Doc(doc.name + "-photo", doc.kind, buf.getvalue(), doc.truth, "image/jpeg")


def corpus(n_each: int = 6, photos: bool = False, seed: int = 7, hard: bool = False) -> list[Doc]:
    rng = random.Random(seed)
    docs = []
    if hard:
        for lang in ("de", "en"):
            docs += [gen_payslip(rng, lang, hard=True) for _ in range(n_each)]
        return docs
    for lang in ("de", "fr", "it", "en"):
        for _ in range(n_each):
            docs += [gen_payslip(rng, lang), gen_statement(rng, lang), gen_invoice(rng, lang)]
    if photos:
        docs += [to_photo(d, rng) for d in docs[::3]]
    return docs


@dataclass
class Score:
    docs: int = 0
    type_ok: int = 0
    value_ok: int = 0
    consistent: int = 0
    false_confirmations: int = 0
    seconds: float = 0.0
    failures: list = field(default_factory=list)


def _value_ok(doc: Doc, an) -> bool:
    if doc.kind == "bank_statement":
        return [r["amount"] for r in an.rows] == doc.truth["rows"]
    if doc.kind == "payslip":
        v = (an.facts.get("payout") or an.facts.get("net") or {}).get("value")
        return v == doc.truth["amount"]
    return (an.facts.get("total") or {}).get("value") == doc.truth["amount"]


def run(docs: list[Doc], model=None, progress: Optional[Callable[[str], None]] = None) -> Score:
    s = Score()
    for d in docs:
        t0 = time.time()
        text = ocr.recognise(d.data, d.media)
        an = understand.analyse(text, model=model)
        s.seconds += time.time() - t0
        s.docs += 1
        t_ok = an.doc_type == d.kind
        v_ok = t_ok and _value_ok(d, an)
        s.type_ok += t_ok
        s.value_ok += v_ok
        s.consistent += an.consistent
        if an.consistent and not v_ok:
            s.false_confirmations += 1
        if not (v_ok and an.consistent):
            s.failures.append((d.name, an.doc_type, [c.detail for c in an.checks if not c.ok] + an.problems))
        if progress:
            progress(f"{d.name}: type {'✓' if t_ok else '✗'} value {'✓' if v_ok else '✗'} consistent {'✓' if an.consistent else '✗'}")
    return s


def report(name: str, s: Score) -> str:
    pct = lambda n: f"{100 * n / s.docs:.0f} %" if s.docs else "—"  # noqa: E731
    return (f"| {name} | {s.docs} | {pct(s.type_ok)} | {pct(s.value_ok)} | {pct(s.consistent)} | "
            f"{s.false_confirmations} | {s.seconds / max(s.docs, 1):.1f} s |")


HEADER = ("| Mode | Documents | Type right | Values right | Reconciled (auto) | False confirmations | Time / doc |\n"
          "|---|---|---|---|---|---|---|")


def damaged_corpus(kinds=("skewed", "upside_down", "perspective", "dark_shadow", "jpeg_noise"), n_each: int = 2,
                   seed: int = 9) -> list[Doc]:
    """Scans and phone photos gone wrong: the same documents, rendered and damaged like real captures."""
    import pypdfium2 as pdfium

    from .eval_real import damage

    rng = random.Random(seed)
    base = []
    for lang in ("de", "fr", "en"):
        for _ in range(n_each):
            base += [gen_payslip(rng, lang), gen_statement(rng, lang), gen_invoice(rng, lang)]
    out = []
    for d in base:
        page = pdfium.PdfDocument(d.data)[0].render(scale=2.0).to_pil().convert("RGB")
        for k in kinds:
            img = damage(page, k, rng)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85)
            out.append(Doc(f"{d.name}-{k}", d.kind, buf.getvalue(), d.truth, "image/jpeg"))
    return out
