"""Document understanding by structure and arithmetic, not by a single keyword.

Every document type has its own analyst. Each analyst
  1. finds candidate values together with their role (gross, deduction, net, balance, …),
  2. checks them against the arithmetic the document must satisfy
     (gross − deductions = net; opening + movements = closing; net + VAT = total),
  3. reports what it is sure of, what it is not, and why.

Nothing is invented: when the numbers do not reconcile, the result says so and the
record goes to review. Speed is secondary to correctness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from .ocr import Line, TextResult

TOL = Decimal("0.05")  # Swiss rounding to 5 Rappen

# ------------------------------------------------------------------ tokens
# 1'234.50  1’234.50  1 234,50  1.234,50  1234.50  -12.30  12.30-  (12.30)  12.–
MONEY_RE = re.compile(
    r"(?<![\w.,'’/])(?P<neg1>[-−–]\s?)?(?P<open>\()?"
    r"(?P<int>\d{1,3}(?:['’  .]\d{3})+|\d+)(?:(?P<sep>[.,])(?P<dec>\d{2}|[-–]{1,2}))"
    r"(?P<close>\))?(?P<neg2>-)?(?![\d%])(?!\s?%)(?![./]\d)")
DATE_RE = re.compile(r"(?<![\d'’])(\d{1,2})[./](\d{1,2})(?:[./]((?:19|20)?\d{2})?)?(?![\d'’]|[.,]\d)")
PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?\s?%")


@dataclass
class Money:
    value: Decimal
    x: Optional[float]  # centre position on the page (0..1), when known
    raw: str
    start: int = 0  # character offset in the line


def money_tokens(line: Line) -> list[Money]:
    """All amounts on a line with their horizontal position, percentages excluded."""
    out: list[Money] = []
    text = line.text
    for m in MONEY_RE.finditer(text):
        intpart = re.sub(r"['’  ]", "", m.group("int"))
        sep, dec = m.group("sep"), m.group("dec")
        if "." in intpart and sep == ",":  # 1.234,50
            intpart = intpart.replace(".", "")
        elif "." in intpart:  # 1.234.50 is not a number
            continue
        dec = "00" if dec and dec[0] in "-–" else dec
        try:
            v = Decimal(f"{intpart}.{dec}")
        except InvalidOperation:
            continue
        if m.group("neg1") or m.group("neg2") or (m.group("open") and m.group("close")):
            v = -v
        out.append(Money(v, _x_of(line, m.start(), m.end()), m.group(0).strip(), m.start()))
    return out


def _x_of(line: Line, start: int, end: int) -> Optional[float]:
    """Map a character span of line.text back to the words' positions."""
    if not line.words:
        return None
    pos, best = 0, None
    for w in line.words:
        i = line.text.find(w.text, pos)
        if i < 0:
            continue
        j = i + len(w.text)
        if i < end and j > start:
            best = (w.x0 + w.x1) / 2 if best is None else (best + (w.x0 + w.x1) / 2) / 2
        pos = j
    return best


def dates_in(text: str, default_year: Optional[int] = None) -> list[date]:
    out = []
    for d, m, y in DATE_RE.findall(text):
        year = int(y) if y else default_year
        if year is None:
            continue
        year = year + 2000 if year < 100 else year
        try:
            out.append(date(year, int(m), int(d)))
        except ValueError:
            continue
    return out


def label_of(line: Line) -> str:
    """The text of a line without its amounts and percentages: what the numbers are about."""
    t = MONEY_RE.sub(" ", line.text)
    t = PERCENT_RE.sub(" ", t)
    return " ".join(t.split()).strip(" :.-").casefold()


def has(text: str, words) -> bool:
    return any(w in text for w in words)


# ------------------------------------------------------------- the report
@dataclass
class Check:
    name: str
    ok: bool
    detail: str

    def to_json(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class Analysis:
    doc_type: str
    type_score: float
    type_evidence: list[str]
    checks: list[Check] = field(default_factory=list)
    facts: dict = field(default_factory=dict)  # role -> value with provenance
    rows: list[dict] = field(default_factory=list)  # statement transactions
    problems: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks) and not self.problems

    def to_json(self) -> dict:
        def j(v):
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, date):
                return v.isoformat()
            if isinstance(v, dict):
                return {k: j(x) for k, x in v.items()}
            if isinstance(v, list):
                return [j(x) for x in v]
            return v
        return {"doc_type": self.doc_type, "type_score": self.type_score, "type_evidence": self.type_evidence,
                "checks": [c.to_json() for c in self.checks], "facts": j(self.facts), "rows": j(self.rows),
                "problems": self.problems}


def fact(value, line: Optional[Line], how: str) -> dict:
    return {"value": value, "line": line.number if line else None, "quote": line.text if line else "", "how": how}


# ---------------------------------------------------------- document type
SIGNALS = {
    "payslip": [(r"lohnabrechnung|lohnausweis\b|salary slip|payslip|pay slip|décompte de salaire|bulletin de (salaire|paie)|"
                 r"fiche de (salaire|paie)|conteggio (del )?salario|busta paga|cedolino", 4),
                (r"bruttolohn|salaire brut|salario lordo|gross (salary|pay)", 3),
                (r"nettolohn|salaire net|salario netto|net (salary|pay)", 3),
                (r"\bahv\b|\bavs\b|\biv\b|\beo\b|\bapg\b|\balv\b|\bac\b|\bbvg\b|\blpp\b|\bnbu\b|\baanp\b|pensionskasse|caisse de pension", 2),
                (r"quellensteuer|impôt à la source|imposta alla fonte", 2),
                (r"auszahlung|montant vers[ée]|versamento|net payment", 1)],
    "bank_statement": [(r"kontoauszug|kontoblatt|relevé de compte|extrait de compte|estratto conto|account statement|bank statement", 4),
                       (r"saldo|solde|balance", 2),
                       (r"belastung|gutschrift|débit|crédit|addebito|accredito|lastschrift|debit|credit", 2),
                       (r"buchung|valuta|date valeur|data valuta|value date|booking", 1),
                       (r"\biban\b", 1)],
    "invoice": [(r"\brechnung\b|rechnungsnummer|rechnungsdatum|facture|fattura|invoice", 4),
                (r"zahlbar bis|payable (jusqu|by)|pagabile entro|zahlungsfrist|due date|échéance|scadenza", 3),
                (r"zahlteil|empfangsschein|section paiement|récépissé|ricevuta|qr-?rechnung", 2),
                (r"\biban\b|referenz|référence|riferimento", 1)],
    "receipt": [(r"quittung|kassenbon|kassenzettel|reçu|ticket de caisse|scontrino|receipt", 4),
                (r"bar\b|karte|card|carte|twint|rückgeld|rendu|resto|change", 2),
                (r"mwst|tva|iva|vat", 1),
                (r"vielen dank|merci|grazie|thank you", 1)],
}


def classify(lines: list[Line]) -> tuple[str, float, list[str]]:
    text = "\n".join(l.text.casefold() for l in lines)
    scores, evidence = {}, {}
    for kind, rules in SIGNALS.items():
        s, ev = 0, []
        for pattern, weight in rules:
            m = re.search(pattern, text)
            if m:
                s += weight
                ev.append(m.group(0))
        scores[kind], evidence[kind] = s, ev
    # structure: many dated rows with amounts is a strong sign of a statement
    dated_rows = sum(1 for l in lines if DATE_RE.match(l.text.strip()) and money_tokens(l))
    if dated_rows >= 3:
        scores["bank_statement"] += min(dated_rows, 8)
        evidence["bank_statement"].append(f"{dated_rows} dated rows with amounts")
    best = max(scores, key=scores.get)
    total = sum(scores.values()) or 1
    if scores[best] < 3:
        return "unknown", 0.0, []
    return best, round(scores[best] / total, 2), evidence[best]


# ------------------------------------------------------------------ payslip
PAYSLIP_ROLES = [  # order matters: the first matching role wins
    ("net", r"^(total )?(netto ?lohn|salaire net|salario netto|net (salary|pay)|nettolohn|netto)\b"),
    ("payout", r"auszahlung|auszahlungsbetrag|zahlbetrag|montant vers[ée]|versement|importo versato|net payment|überweisung"),
    ("gross", r"brutto ?lohn|total brutto|bruttolohn|salaire brut|total brut|salario lordo|gross (salary|pay)|^brutto\b"),
    ("total_deductions", r"total (abzüge|sozialabzüge|déductions|deduzioni|deductions)|abzüge total|total des retenues"),
    ("deduction", r"\bahv\b|\biv\b|\beo\b|\bavs\b|\bai\b|\bapg\b|\balv\b|\bac\b|\bbvg\b|\blpp\b|pensionskasse|caisse de pension|"
                  r"\bnbu\b|\baanp\b|\bktg\b|\bijm\b|krankentaggeld|unfall|accident|quellensteuer|impôt à la source|"
                  r"imposta alla fonte|withholding tax|\bfak\b|parkplatz|abzug|retenue|deduzione"),
    ("allowance_after", r"spesen|frais|spese|expenses|pauschalspesen"),
    ("earning", r"monatslohn|grundlohn|stundenlohn|salaire de base|salaire mensuel|salario base|base salary|"
                r"13\. ?monatslohn|13e salaire|tredicesima|überstunden|heures supplémentaires|zulage|allocation|"
                r"assegno|bonus|gratifikation|provision|commission|ferienentschädigung|feiertag"),
]
MONTHS = {**{m: i + 1 for i, m in enumerate(["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
                                             "september", "oktober", "november", "dezember"])},
          **{m: i + 1 for i, m in enumerate(["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                                             "septembre", "octobre", "novembre", "décembre"])},
          **{m: i + 1 for i, m in enumerate(["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
                                             "agosto", "settembre", "ottobre", "novembre", "dicembre"])},
          **{m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                             "september", "october", "november", "december"])}}
LEGAL = re.compile(r"\b(AG|GmbH|SA|Sàrl|Sarl|S\.A\.|Genossenschaft|Coop|KLG|Ltd|Inc|SRL|Sagl|Verein|Stiftung)\b", re.I)


def _period(lines: list[Line]) -> Optional[tuple[int, int]]:
    for l in lines[:25]:
        t = l.text.casefold()
        for name, num in MONTHS.items():
            m = re.search(rf"\b{name}\b\s*(20\d\d)", t)
            if m:
                return int(m.group(1)), num
        m = re.search(r"\b(0?[1-9]|1[0-2])[./](20\d\d)\b", t)
        if m and not DATE_RE.search(t.replace(m.group(0), "")):
            return int(m.group(2)), int(m.group(1))
    for l in lines[:25]:
        ds = dates_in(l.text)
        if ds:
            return ds[0].year, ds[0].month
    return None


def analyse_payslip(lines: list[Line], a: Analysis) -> Analysis:
    found: dict[str, list[tuple[Decimal, Line]]] = {}
    for l in lines:
        amounts = money_tokens(l)
        if not amounts:
            continue
        lab = label_of(l)
        if not lab:
            continue
        role = next((r for r, p in PAYSLIP_ROLES if re.search(p, lab)), None)
        if role is None:
            continue
        value = amounts[-1].value  # the amount column is the rightmost; rates and bases sit to its left
        found.setdefault(role, []).append((value, l))

    def one(role):
        items = found.get(role, [])
        return items[-1] if items else None  # totals tend to be printed after their items

    gross, net, payout = one("gross"), one("net"), one("payout")
    deductions = found.get("deduction", [])
    earnings = found.get("earning", [])
    after = found.get("allowance_after", [])
    total_ded = one("total_deductions")
    ded_sum = sum((abs(v) for v, _ in deductions), Decimal(0))
    if gross:
        a.facts["gross"] = fact(abs(gross[0]), gross[1], "label")
    if net:
        a.facts["net"] = fact(abs(net[0]), net[1], "label")
    if payout:
        a.facts["payout"] = fact(abs(payout[0]), payout[1], "label")
    a.facts["deductions"] = [fact(abs(v), l, label_of(l)) for v, l in deductions]
    a.facts["earnings"] = [fact(abs(v), l, label_of(l)) for v, l in earnings]
    a.facts["allowances_after_net"] = [fact(abs(v), l, label_of(l)) for v, l in after]

    before = [(v, l) for v, l in earnings if gross and l.number < gross[1].number]
    if before and gross:
        s = sum((abs(v) for v, _ in before), Decimal(0))
        a.checks.append(Check("earnings add up to gross", abs(s - abs(gross[0])) <= TOL,
                              f"sum of {len(before)} earning lines {s} vs gross {abs(gross[0])}"))
    if total_ded and deductions:
        a.checks.append(Check("deductions add up to their total", abs(ded_sum - abs(total_ded[0])) <= TOL,
                              f"sum of {len(deductions)} deduction lines {ded_sum} vs total {abs(total_ded[0])}"))
    if total_ded:
        ded_sum = abs(total_ded[0])
    if gross and net:
        g, n = abs(gross[0]), abs(net[0])
        # Some items (child allowances, expenses) are added after the deductions; try the layouts that exist.
        later = [abs(v) for v, l in earnings if l.number > gross[1].number]
        options = [("gross − deductions = net", g - ded_sum),
                   ("gross − deductions + items after gross = net", g - ded_sum + sum(later, Decimal(0))),
                   ("gross − deductions + expenses = net", g - ded_sum + sum((abs(v) for v, _ in after), Decimal(0)))]
        hit = next(((name, v) for name, v in options if abs(v - n) <= TOL), None)
        if hit:
            a.checks.append(Check(hit[0], True, f"{g} − {ded_sum} … = {hit[1]}, printed net {n}"))
        else:
            a.checks.append(Check("gross − deductions = net", False,
                                  f"{g} − {ded_sum} = {g - ded_sum}, but the printed net is {n} "
                                  f"(difference {n - (g - ded_sum)})"))
    elif gross and deductions and not net:
        computed = abs(gross[0]) - ded_sum
        a.facts["net"] = {"value": computed, "line": None, "quote": "", "how": "computed: gross − deductions"}
        a.problems.append("No net salary printed; it was computed from gross and deductions — please check.")
    if payout and (net or gross):
        base = abs(net[0]) if net else a.facts["net"]["value"]
        extra = sum((abs(v) for v, _ in after), Decimal(0))
        a.checks.append(Check("net + expenses = payout", abs(base + extra - abs(payout[0])) <= TOL,
                              f"{base} + {extra} vs payout {abs(payout[0])}"))
    if not (net or payout or gross):
        a.problems.append("No gross, net or payout amount could be identified.")

    employer = next((l for l in lines[:12] if LEGAL.search(l.text) and not money_tokens(l)), None)
    if employer:
        a.facts["employer"] = fact(employer.text.strip(), employer, "legal form in the header")
    per = _period(lines)
    if per:
        a.facts["period"] = {"value": f"{per[0]}-{per[1]:02d}", "line": None, "quote": "", "how": "month in the header"}
    pay_date = None
    for l in lines:
        if re.search(r"auszahlungsdatum|ausbezahlt am|zahltag|date de paiement|vers[ée] le|data di pagamento|pagato il|payment date|paid on|valuta", l.text.casefold()):
            ds = dates_in(l.text)
            if ds:
                pay_date = (ds[0], l)
                break
    if pay_date:
        a.facts["date"] = fact(pay_date[0], pay_date[1], "payment date label")
    elif per:
        y, m = per
        last = (date(y + (m == 12), m % 12 + 1, 1) - date.resolution)
        a.facts["date"] = {"value": last, "line": None, "quote": "", "how": "last day of the pay period"}
    return a


# ------------------------------------------------------------ bank statement
HEAD = {
    "date": r"^(buchungs)?datum$|^date$|^data$|^buchung$|^booking$",
    "value": r"^valuta$|^value$|^date valeur$|^valeur$",
    "text": r"text|beschreibung|libellé|descrizione|details|description|mitteilung|verwendungszweck|avis",
    "debit": r"belastung|lastschrift|^soll$|débit|debit|addebito|ausgang|withdrawal",
    "credit": r"gutschrift|^haben$|crédit|credit|accredito|eingang|deposit",
    "amount": r"^betrag$|^montant$|^importo$|^amount$",
    "balance": r"saldo|solde|balance",
}
OPENING = r"saldo alt|anfangssaldo|alter saldo|saldovortrag|vortrag|solde (initial|précédent|reporté|à nouveau)|" \
          r"saldo (iniziale|precedente|riportato)|opening balance|previous balance|balance brought forward"
CLOSING = r"schlusssaldo|neuer saldo|saldo neu|endsaldo|solde (final|nouveau|au )|saldo (finale|nuovo)|closing balance|new balance"


def _columns(lines: list[Line]) -> tuple[Optional[int], dict[str, float]]:
    for l in lines[:60]:
        if len(l.words) < 3:
            continue
        cols = {}
        for w in l.words:
            t = w.text.casefold().strip(":")
            for role, p in HEAD.items():
                if role not in cols and re.search(p, t):
                    cols[role] = (w.x0 + w.x1) / 2
        if "date" in cols and ({"debit", "credit"} & set(cols) or "amount" in cols or "balance" in cols) and len(cols) >= 3:
            return l.number, cols
    return None, {}


def _statement_year(lines: list[Line]) -> Optional[int]:
    for l in lines[:30]:
        ds = dates_in(l.text)
        if ds:
            return ds[-1].year
    return None


def analyse_statement(lines: list[Line], a: Analysis) -> Analysis:
    header_line, cols = _columns(lines)
    year = _statement_year(lines)
    iban = None
    for l in lines[:40]:
        m = re.search(r"\b(CH|LI)\d{2}(?:\s?[0-9A-Z]{4}){4}\s?[0-9A-Z]\b", l.text)
        if m:
            iban = re.sub(r"\s", "", m.group(0))
            break
    if iban:
        a.facts["iban"] = {"value": iban, "line": None, "quote": "", "how": "IBAN in the header"}
    opening = closing = None
    rows: list[dict] = []
    for l in lines:
        if header_line and l.number <= header_line:
            continue
        low = l.text.casefold()
        amounts = money_tokens(l)
        if re.search(OPENING, low) and amounts:
            opening = (amounts[-1].value, l)
            continue
        if re.search(CLOSING, low) and amounts:
            closing = (amounts[-1].value, l)
            continue
        start = DATE_RE.match(l.text.strip())
        if start:
            lead = len(l.text) - len(l.text.lstrip()) + start.end()
            amounts = [t for t in amounts if t.start >= lead]
            # a second date (value date) right after the booking date is not an amount either
            second = DATE_RE.match(l.text[lead:].lstrip())
            if second:
                lead2 = lead + (len(l.text[lead:]) - len(l.text[lead:].lstrip())) + second.end()
                amounts = [t for t in amounts if t.start >= lead2]
        if start and amounts:
            d = dates_in(start.group(0), year)
            rows.append({"date": d[0] if d else None, "line": l, "amounts": amounts, "text": [label_of(l)]})
        elif rows and not amounts and not start and l.text.strip() and len(l.text) < 120:
            rows[-1]["text"].append(l.text.strip())  # multi-line booking text
        elif rows and start is None and amounts and re.search(r"total|summe|umsatz|totaux|totale", low):
            continue  # column totals are not transactions

    # Assign each amount to a column: by header position when known, by balance arithmetic otherwise.
    prev_balance = opening[0] if opening else None
    out = []
    for r in rows:
        amt, bal, how = None, None, ""
        toks = r["amounts"]
        if cols and all(t.x is not None for t in toks):
            def nearest(t):
                return min((k for k in cols if k in ("debit", "credit", "amount", "balance")),
                           key=lambda k: abs(cols[k] - t.x))
            for t in toks:
                k = nearest(t)
                if k == "balance":
                    bal = t.value
                elif k == "debit":
                    amt, how = -abs(t.value), "debit column"
                elif k == "credit":
                    amt, how = abs(t.value), "credit column"
                elif k == "amount":
                    amt, how = t.value, "signed amount column"
        else:
            if len(toks) >= 2:
                amt_tok, bal = toks[-2].value, toks[-1].value
                if prev_balance is not None:
                    delta = bal - prev_balance
                    if abs(abs(delta) - abs(amt_tok)) <= TOL:
                        amt, how = delta, "sign from the change in balance"
                    else:
                        amt, how = amt_tok, "amount and balance do not agree"
                else:
                    amt, how = amt_tok, "no opening balance to determine the sign"
            else:
                amt, how = toks[-1].value, "single amount without column or balance"
        if amt is not None and bal is not None and prev_balance is not None and how.endswith("column"):
            ok = abs(prev_balance + amt - bal) <= TOL
            if not ok:
                how += "; balance does not follow"
        if bal is not None:
            prev_balance = bal
        text = " ".join(t for t in r["text"] if t).strip()
        out.append({"date": r["date"], "amount": amt, "balance": bal, "text": text, "line": r["line"].number,
                    "quote": r["line"].text, "how": how})
    a.rows = out
    credits = sum((x["amount"] for x in out if x["amount"] and x["amount"] > 0), Decimal(0))
    debits = sum((-x["amount"] for x in out if x["amount"] and x["amount"] < 0), Decimal(0))
    a.facts.update({"rows": len(out), "credits": credits, "debits": debits})
    if opening:
        a.facts["opening"] = fact(opening[0], opening[1], "opening balance label")
    if closing:
        a.facts["closing"] = fact(closing[0], closing[1], "closing balance label")
    if not out:
        a.problems.append("No booking lines with a date and an amount were found.")
        return a
    if opening and closing:
        diff = opening[0] + credits - debits - closing[0]
        a.checks.append(Check("opening + credits − debits = closing", abs(diff) <= TOL,
                              f"{opening[0]} + {credits} − {debits} = {opening[0] + credits - debits}, printed closing {closing[0]}"))
    else:
        a.problems.append("Opening or closing balance not found; totals cannot be verified.")
    unsure = [x for x in out if not x["how"].endswith("column") and x["how"] != "sign from the change in balance"]
    broken = [x for x in out if "does not follow" in x["how"] or "do not agree" in x["how"]]
    a.checks.append(Check("every line has a reliable sign", not unsure,
                          "all signs from columns or balance changes" if not unsure else
                          f"{len(unsure)} lines without a reliable sign: " + "; ".join(x["quote"][:40] for x in unsure[:3])))
    if any(x["balance"] is not None for x in out):
        a.checks.append(Check("running balance continues line by line", not broken,
                              "each balance follows from the previous one" if not broken else
                              f"{len(broken)} lines break the running balance"))
    if any(x["date"] is None for x in out):
        a.problems.append("Some booking lines have no year; the statement period was not found.")
    return a


# ---------------------------------------------------------- invoice / receipt
TOTAL = r"zu bezahlen|total|summe|gesamt|endbetrag|rechnungsbetrag|montant|à payer|a payer|totale|importo|amount due|betrag"
NET = r"netto|zwischentotal|subtotal|sous-total|sous total|imponibile|total exkl|total hors|excl\.?|ohne mwst|ht\b"
VAT = r"mwst|mehrwertsteuer|tva|iva|vat"
NOT_TOTAL = r"rabatt|skonto|remise|sconto|discount|rückgeld|rendu|resto|change|gegeben|bar\b|erhalten|tip|trinkgeld"


def analyse_invoice(lines: list[Line], a: Analysis) -> Analysis:
    totals, nets, vats, items = [], [], [], []
    for l in lines:
        toks = money_tokens(l)
        if not toks:
            continue
        lab = label_of(l)
        v = toks[-1].value
        if re.search(NET, lab):
            nets.append((v, l))
        elif re.search(VAT, lab) and not re.search(r"inkl|incl|compris|inclus", lab):
            vats.append((v, l))
        elif re.search(TOTAL, lab) and not re.search(NOT_TOTAL, lab):
            totals.append((v, l))
        elif re.search(VAT, lab):  # "inkl. MWST 8.1% 13.80" states VAT inside the total
            vats.append((v, l))
        elif lab and not re.search(NOT_TOTAL, lab) and not dates_in(l.text, 2000) and len(lab) > 2:
            items.append((v, l))
    # Choose the total that the other numbers support.
    best, why = None, ""
    for v, l in sorted(totals, key=lambda t: -abs(t[0])):
        reasons = []
        if any(abs(n + x - v) <= TOL for n, _ in nets for x, _ in vats):
            reasons.append("net + VAT = total")
        if any(abs(x - v * r / (1 + r)) <= TOL for x, _ in vats for r in (Decimal("0.081"), Decimal("0.026"), Decimal("0.038"))):
            reasons.append("VAT is the Swiss rate of the total")
        s = sum((i for i, _ in items), Decimal(0))
        if items and abs(s - v) <= TOL:
            reasons.append(f"{len(items)} line items add up")
        elif items and any(abs(s + x - v) <= TOL for x, _ in vats):
            reasons.append(f"{len(items)} line items + VAT = total")
        if reasons and (best is None or len(reasons) > len(why)):
            best, why = (v, l), reasons
    if best is None and totals:
        # no arithmetic support: prefer the last explicit total line, but say so
        best, why = totals[-1], []
        a.problems.append("The total could not be confirmed by VAT or line items.")
    if best:
        a.facts["total"] = fact(abs(best[0]), best[1], "; ".join(why) if why else "total label")
        a.checks.append(Check("total supported by the other amounts", bool(why), "; ".join(why) or "no supporting amounts"))
    else:
        a.problems.append("No total amount found.")
    if len({abs(v) for v, _ in totals}) > 1 and not why:
        a.problems.append("Several different totals are printed: " + ", ".join(str(abs(v)) for v, _ in totals[:4]))
    return a


def analyse(result: TextResult) -> Analysis:
    kind, score, evidence = classify(result.lines)
    a = Analysis(kind, score, evidence)
    if kind == "payslip":
        return analyse_payslip(result.lines, a)
    if kind == "bank_statement":
        return analyse_statement(result.lines, a)
    if kind in ("invoice", "receipt"):
        return analyse_invoice(result.lines, a)
    a.problems.append("Document type not recognised.")
    return a
