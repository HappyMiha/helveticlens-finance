"""Deterministic field extraction from recognised text.

Every value carries where it was found (line), the exact quote and a
confidence. Missing values stay missing: nothing is invented (§17.3).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..ingest import qrbill
from .ocr import Line, TextResult


@dataclass
class Field:
    value: object
    line: Optional[int]
    quote: str
    confidence: float
    method: str  # regex, keyword, qr-bill, layout

    def to_json(self) -> dict:
        d = asdict(self)
        d["value"] = self.value.isoformat() if isinstance(self.value, date) else str(self.value)
        return d


@dataclass
class Extracted:
    doc_type: Field
    amount: Optional[Field] = None
    currency: Optional[Field] = None
    doc_date: Optional[Field] = None
    due_date: Optional[Field] = None
    counterparty: Optional[Field] = None
    iban: Optional[Field] = None
    reference: Optional[Field] = None
    description: Optional[Field] = None

    def fields(self) -> dict[str, Field]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    def to_json(self) -> dict:
        return {k: v.to_json() for k, v in self.fields().items()}

    @property
    def weakest(self) -> float:
        needed = [self.amount, self.doc_date, self.counterparty]
        return min((f.confidence for f in needed if f), default=0.0) if all(needed) else 0.0


TYPE_WORDS = {
    "invoice": ["rechnung", "invoice", "facture", "fattura", "zahlbar bis", "payable", "zahlteil",
                "empfangsschein", "récépissé", "section paiement", "ricevuta"],
    "receipt": ["quittung", "kassenbon", "beleg", "receipt", "ticket de caisse", "scontrino",
                "bar bezahlt", "kartenzahlung", "mwst", "tva", "iva", "rückgeld", "total chf"],
    "payslip": ["lohnabrechnung", "salaire", "bulletin de salaire", "payslip", "busta paga", "nettolohn"],
    "bank_statement": ["kontoauszug", "relevé de compte", "estratto conto", "account statement"],
}
TOTAL_WORDS = ["zu bezahlen", "total", "summe", "betrag", "gesamt", "montant", "à payer", "a payer",
               "totale", "importo", "endbetrag", "amount due", "rechnungsbetrag"]
DUE_WORDS = ["zahlbar bis", "fällig", "faellig", "due", "échéance", "echeance", "payable jusqu",
             "scadenza", "pagabile entro", "zahlungsfrist"]
DOC_DATE_WORDS = ["rechnungsdatum", "datum", "date", "data", "invoice date", "date de facture"]
LEGAL_FORMS = re.compile(r"\b(AG|GmbH|SA|Sàrl|Sarl|S\.A\.|Genossenschaft|Coop|KLG|LLC|Ltd|Inc|Verein|SRL|Sagl)\b", re.I)

# Not part of a date (03.10.2026) or a longer number.
AMOUNT_RE = re.compile(r"(?<![\d.,'’/])(\d{1,3}(?:['’ ]\d{3})+|\d+)[.,](\d{2})(?![\d]|[./]\d)")
CURRENCY_RE = re.compile(r"\b(CHF|EUR|USD|GBP|SFr\.?|Fr\.)", re.I)
DATE_RES = [
    (re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b"), "dmy2"),
]
IBAN_RE = re.compile(r"\b(CH|LI)\s?(\d{2})(?:\s?([0-9A-Z]{4})){4}\s?([0-9A-Z])\b")
QRREF_RE = re.compile(r"\b(\d{2}(?:\s?\d{5}){5})\b")


def _parse_amount(m: re.Match) -> Optional[Decimal]:
    try:
        return Decimal(re.sub(r"['’ ]", "", m.group(1)) + "." + m.group(2))
    except InvalidOperation:
        return None


def _dates(line: Line):
    for regex, kind in DATE_RES:
        for m in regex.finditer(line.text):
            try:
                if kind == "ymd":
                    yield date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0)
                else:
                    year = int(m.group(3))
                    year = year + 2000 if kind == "dmy2" else year
                    yield date(year, int(m.group(2)), int(m.group(1))), m.group(0)
            except ValueError:
                continue


def _conf(line: Line, base: float) -> float:
    ocr = line.confidence if line.confidence is not None else 1.0
    return round(min(base, base * (0.5 + ocr / 2)), 3)


def detect_type(lines: list[Line]) -> Field:
    text = " ".join(l.text.lower() for l in lines)
    scores = {t: sum(text.count(w) for w in words) for t, words in TYPE_WORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return Field("unknown", None, "", 0.0, "keyword")
    total = sum(scores.values())
    hit = next((l for l in lines if any(w in l.text.lower() for w in TYPE_WORDS[best])), None)
    return Field(best, hit.number if hit else None, hit.text if hit else "",
                 round(min(0.95, 0.5 + 0.45 * scores[best] / total), 3), "keyword")


def from_qr(payload: str, result: TextResult) -> Optional[Extracted]:
    try:
        bill = qrbill.parse(payload)
    except qrbill.QRBillError:
        return None
    quote = payload.split("\n")[0:1] + [bill.iban, bill.creditor]
    q = " · ".join(quote)
    ex = Extracted(doc_type=Field("invoice", None, "Swiss QR-bill", 0.99, "qr-bill"))
    ex.currency = Field(bill.currency, None, q, 1.0, "qr-bill")
    if bill.amount:
        ex.amount = Field(bill.amount.amount, None, q, 1.0, "qr-bill")
    ex.counterparty = Field(bill.creditor, None, q, 1.0, "qr-bill")
    ex.iban = Field(bill.iban, None, q, 1.0, "qr-bill")
    if bill.reference:
        ex.reference = Field(bill.reference, None, q, 1.0, "qr-bill")
    if bill.message:
        ex.description = Field(bill.message, None, q, 1.0, "qr-bill")
    return ex


def extract(result: TextResult) -> Extracted:
    lines = result.lines
    ex = Extracted(doc_type=detect_type(lines))

    # Amount: prefer the last amount on a "total" line; otherwise the largest amount.
    best = None
    for line in lines:
        low = line.text.lower()
        weight = 0.9 if any(w in low for w in TOTAL_WORDS) else 0.0
        if "mwst" in low or "tva" in low or "iva" in low or "rabatt" in low or "netto" in low:
            weight = min(weight, 0.3)
        for m in AMOUNT_RE.finditer(line.text):
            value = _parse_amount(m)
            if value is None or value == 0:
                continue
            key = (weight, value if weight else Decimal(0), line.number)
            if best is None or key > best[0]:
                best = (key, value, line, m.group(0))
    if best is not None:
        (weight, _, _), value, line, quote = best
        if not weight:  # no total keyword: largest amount, lower confidence
            value = max((_parse_amount(m) or Decimal(0)) for l in lines for m in AMOUNT_RE.finditer(l.text))
            line = next(l for l in lines for m in AMOUNT_RE.finditer(l.text) if _parse_amount(m) == value)
        ex.amount = Field(value, line.number, line.text, _conf(line, 0.92 if weight else 0.55), "regex")

    # Currency: on the amount line if present, else most frequent; CHF only if seen.
    cur_line = None
    if ex.amount and ex.amount.line:
        cur_line = next((l for l in lines if l.number == ex.amount.line and CURRENCY_RE.search(l.text)), None)
    found = [(l, CURRENCY_RE.search(l.text)) for l in ([cur_line] if cur_line else lines)]
    found = [(l, m) for l, m in found if m]
    if found:
        line, m = found[0]
        code = m.group(1).upper().rstrip(".")
        code = "CHF" if code in {"SFR", "FR"} else code
        ex.currency = Field(code, line.number, line.text, _conf(line, 0.95), "regex")

    # Dates: due date near due words; document date near date words, else the first date.
    for line in lines:
        low = line.text.lower()
        for value, quote in _dates(line):
            if any(w in low for w in DUE_WORDS):
                if not ex.due_date:
                    ex.due_date = Field(value, line.number, line.text, _conf(line, 0.9), "keyword")
            elif not ex.doc_date or (ex.doc_date.method == "regex" and any(w in low for w in DOC_DATE_WORDS)):
                method = "keyword" if any(w in low for w in DOC_DATE_WORDS) else "regex"
                ex.doc_date = Field(value, line.number, line.text, _conf(line, 0.88 if method == "keyword" else 0.7), method)

    # Counterparty: first line with a legal form in the top part, else the first text line.
    top = lines[: max(8, len(lines) // 3)]
    pick = next((l for l in top if LEGAL_FORMS.search(l.text)), None)
    method, base = "layout", 0.8
    if pick is None:
        pick = next((l for l in top if re.search(r"[A-Za-zÄÖÜäöüéèàç]{3}", l.text)
                     and not AMOUNT_RE.search(l.text) and not any(True for _ in _dates(l))), None)
        base = 0.55
    if pick is not None:
        name = pick.text.strip(" ,:")
        m = LEGAL_FORMS.search(name)
        if m:  # nothing after the legal form belongs to the name (stray marks, page numbers)
            name = name[:m.end()].rstrip(" ,")
        ex.counterparty = Field(name, pick.number, pick.text, _conf(pick, base), method)

    for line in lines:
        m = IBAN_RE.search(line.text.replace("-", " "))
        if m and not ex.iban:
            ex.iban = Field(re.sub(r"\s", "", m.group(0)), line.number, line.text, _conf(line, 0.9), "regex")
        r = QRREF_RE.search(line.text)
        if r and not ex.reference:
            ref = re.sub(r"\s", "", r.group(1))
            if qrbill.qr_reference_valid(ref):
                ex.reference = Field(ref, line.number, line.text, _conf(line, 0.95), "regex")

    # A decoded QR-bill is structured data and overrides OCR guesses.
    for payload in result.qr_payloads:
        qr = from_qr(payload, result)
        if qr:
            for name, value in qr.fields().items():
                if name == "doc_type" and ex.doc_type.value not in ("unknown", "receipt"):
                    continue
                setattr(ex, name, value)
            break
    return ex
