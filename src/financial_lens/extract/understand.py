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

TOL = Decimal("0.005")  # sums must match to the cent; OCR misreads must not hide behind a tolerance


def near_total(computed: Decimal, total: Decimal) -> bool:
    """A printed total may be rounded to 5 Rappen (Swiss cash rounding) — but only if it is itself a
    multiple of 0.05; otherwise the sum must match exactly."""
    if (total * 100) % 5 == 0:
        return abs(computed - total) <= Decimal("0.025")
    return abs(computed - total) <= TOL

# ------------------------------------------------------------------ tokens
# 1'234.50  1’234.50  1 234,50  1.234,50  1234.50  -12.30  12.30-  (12.30)  12.–
MONEY_RE = re.compile(
    r"(?<![\w.,'’/])(?P<neg1>[-−–]\s?)?(?P<open>\()?"
    r"(?P<int>\d{1,3}(?:['’ \u202f.]\d{3})+|\d{1,3}(?:,\d{3})+(?=\.\d\d)|\d+)(?:(?P<sep>[.,])(?P<dec>\d{2}|[-–]{1,2}))"
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
        if "," in intpart:  # 6,500.00 (English thousands separator)
            intpart = intpart.replace(",", "")
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
                (r"bar\b|karte|card|carte|twint|rückgeld|rendu|resto|change|cash|tender", 2),
                (r"\bqty\b|menge|anzahl|quantité|quantità|subtotal|sub total|zwischentotal", 1),
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
    ("net", r"^(total )?(netto ?(lohn|gehalt)|salaire net|salario netto|net (salary|pay)|netto)\b"),
    ("payout", r"auszahlung|auszahlungsbetrag|zahlbetrag|montant vers[ée]|versement|importo versato|net payment|payout|"
               r"amount paid|überweisung"),
    ("gross", r"brutto ?(lohn|gehalt)|total brutto|gesamtbrutto|lohn brutto|salaire brut|total brut|salario lordo|"
              r"gross (salary|pay)|^brutto\b"),
    ("total_deductions", r"totale? (des )?(abzüge|sozialabzüge|déductions|deduzioni|trattenute|deductions|retenues)|"
                         r"(sozial)?abzüge total"),
    ("deduction", r"versicherung|assurance|assicurazione|insurance|cotisation|beitrag|contributo|contribution|"
                  r"social security|pension fund|unemployment|\bad\b|\bainp\b|\bipg\b|cassa pensione|\bahv\b|\biv\b|\beo\b|\bavs\b|\bai\b|\bapg\b|\balv\b|\bac\b|\bbvg\b|\blpp\b|pensionskasse|caisse de pension|"
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


def analyse_payslip(lines: list[Line], a: Analysis, roles: Optional[dict] = None) -> Analysis:
    """roles: optional {line number: (role, amount)} proposed by a model; the arithmetic below decides."""
    found: dict[str, list[tuple[Decimal, Line]]] = {}
    unlabelled: list[tuple[Decimal, Line]] = []
    for l in lines:
        amounts = money_tokens(l)
        if not amounts:
            continue
        if roles is not None:
            if l.number not in roles:
                continue
            role, value = roles[l.number]
            found.setdefault(role, []).append((value, l))
            continue
        lab = re.sub(r"[-/]", " ", label_of(l))
        if not lab:
            continue
        role = next((r for r, p in PAYSLIP_ROLES if re.search(p, lab)), None)
        value = amounts[-1].value  # the amount column is the rightmost; rates and bases sit to its left
        if role is None:
            unlabelled.append((value, l))
            continue
        found.setdefault(role, []).append((value, l))
    # Structure: an unlabelled negative amount between gross and net is a deduction; an unlabelled
    # positive amount between the deductions and net is something added after deductions.
    if roles is None and unlabelled:
        g_line = (found.get("gross") or [(None, None)])[-1][1]
        n_line = (found.get("net") or found.get("payout") or [(None, None)])[0][1]
        last_ded = max((l.number for _, l in found.get("deduction", []) + found.get("total_deductions", [])), default=None)
        for v, l in unlabelled:
            if g_line and n_line and g_line.number < l.number < n_line.number:
                if v < 0:
                    found.setdefault("deduction", []).append((v, l))
                elif last_ded and l.number > last_ded:
                    found.setdefault("earning", []).append((v, l))

    def one(role):
        items = found.get(role, [])
        return items[-1] if items else None  # totals tend to be printed after their items

    gross, net, payout = one("gross"), one("net"), one("payout")
    # Completeness: an amount after the gross salary that no role explains could change the result.
    used = {l.number for items in found.values() for _, l in items}
    g_no = gross[1].number if gross else 0
    stray = [l for v, l in unlabelled if l.number > g_no and l.number not in used]
    if stray:
        a.problems.append("Amounts that could not be assigned: " + "; ".join(l.text[:50] for l in stray[:4]))
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
    if payout and (net or "net" in a.facts):
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


def solve_payslip(lines: list[Line], a: Analysis) -> Optional[Analysis]:
    """Find the roles from the arithmetic alone, without knowing any label:
    gross, a block of deductions (optionally followed by its total), items added afterwards, the net,
    and items between net and payout. Accepted only if exactly one reading explains every amount
    after the gross salary."""
    seq = [(l, abs(money_tokens(l)[-1].value)) for l in lines if money_tokens(l)]
    n = len(seq)
    sols = []
    for i in range(n):
        g = seq[i][1]
        for k in range(i + 3, n):  # at least two deductions between gross and net
            block = seq[i + 1:k]
            for with_total in (True, False):
                deds, total = (block[:-1], block[-1]) if with_total else (block, None)
                if len(deds) < 2:
                    continue
                dsum = sum((v for _, v in deds), Decimal(0))
                if total is not None and abs(dsum - total[1]) > TOL:
                    continue
                for extra in range(0, 3):  # items added after the deductions, before the net line
                    if k + extra >= n:
                        break
                    adds = seq[k:k + extra]
                    net = seq[k + extra]
                    if abs(g - dsum + sum((v for _, v in adds), Decimal(0)) - net[1]) > TOL:
                        continue
                    rest = seq[k + extra + 1:]
                    payout, mids = None, []
                    for m in range(len(rest) - 1, -1, -1):  # payout = net + items in between
                        between = rest[:m]
                        if abs(net[1] + sum((v for _, v in between), Decimal(0)) - rest[m][1]) <= TOL:
                            payout, mids = rest[m], between
                            break
                    tail = rest[(len(mids) + 1) if payout else 0:]
                    if tail:
                        continue  # some amount after the net would remain unexplained
                    before = seq[:i]
                    sols.append(dict(g=seq[i], deds=deds, total=total, adds=adds, net=net, mids=mids, payout=payout,
                                     before=before))
    if not sols:
        return None
    # identical numeric readings (e.g. base salary = gross) count once
    keys = {(s["g"][0].number, s["net"][0].number, (s["payout"] or (None,))[0] and s["payout"][0].number) for s in sols}
    if len(keys) != 1:
        a.problems.append(f"The arithmetic allows {len(keys)} different readings; please check.")
        return None
    s = sols[-1]
    how = "structure: the arithmetic identifies the role"
    a.facts["gross"] = fact(s["g"][1], s["g"][0], how)
    a.facts["deductions"] = [fact(v, l, how) for l, v in s["deds"]]
    a.facts["earnings"] = [fact(v, l, how) for l, v in s["adds"]]
    a.facts["net"] = fact(s["net"][1], s["net"][0], how)
    a.facts["allowances_after_net"] = [fact(v, l, how) for l, v in s["mids"]]
    if s["payout"]:
        a.facts["payout"] = fact(s["payout"][1], s["payout"][0], how)
    dsum = sum((v for _, v in s["deds"]), Decimal(0))
    a.checks.append(Check("gross − deductions (+ additions) = net", True,
                          f"{s['g'][1]} − {dsum} + {sum((v for _, v in s['adds']), Decimal(0))} = {s['net'][1]}"))
    if s["total"]:
        a.checks.append(Check("deductions add up to their total", True, f"{dsum} = {s['total'][1]}"))
    if s["payout"]:
        a.checks.append(Check("net + items = payout", True, f"{s['net'][1]} → {s['payout'][1]}"))
    a.checks.append(Check("every amount after gross is explained", True, "unique reading"))
    employer = next((l for l in lines[:12] if LEGAL.search(l.text) and not money_tokens(l)), None)
    if employer:
        a.facts["employer"] = fact(employer.text.strip(), employer, "legal form in the header")
    per = _period(lines)
    if per:
        a.facts["period"] = {"value": f"{per[0]}-{per[1]:02d}", "line": None, "quote": "", "how": "month in the header"}
    dated = [(dates_in(l.text), l) for l in lines]
    dated = [(d[0], l) for d, l in dated if d]
    if dated:
        a.facts["date"] = fact(dated[-1][0], dated[-1][1], "last date on the payslip")
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
        if amt is None and bal is not None and prev_balance is not None and len(toks) >= 2:
            # the column of the amount was unclear (skewed scan): the balance change decides
            cand = [t.value for t in toks if t.value != bal]
            delta = bal - prev_balance
            if cand and any(abs(abs(c) - abs(delta)) <= TOL for c in cand):
                amt, how = delta, "sign from the change in balance"
        if amt is not None and bal is not None and prev_balance is not None and how.endswith("column"):
            ok = abs(prev_balance + amt - bal) <= TOL
            if not ok and abs(prev_balance - amt - bal) <= TOL:
                amt, how = -amt, "sign from the change in balance"  # amount sat between two columns
            elif not ok:
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
TOTAL = r"zu bezahlen|total|summe|gesamt|endbetrag|rechnungsbetrag|montant|à payer|a payer|totale|importo|amount due|" \
        r"betrag|payable|amount"
NET = r"netto|zwischentotal|subtotal|sub total|sous-total|sous total|imponibile|total exkl|total hors|excl\.?|excluded|" \
      r"ohne mwst|\bht\b"
VAT = r"mwst|mehrwertsteuer|tva|iva|vat|gst|sst|\btax\b|steuer"
INCLUDED = r"inkl|incl|inclu|inciu|compris|enthalten|included"
PAID = r"\bbar\b|cash|tender|bezahlt|gegeben|erhalten|espèces|contanti|paid|karte|card|twint|visa|mastercard"
CHANGE = r"rückgeld|rueckgeld|change|rendu|resto|monnaie"
NOT_TOTAL = r"rabatt|skonto|remise|sconto|discount|tip|trinkgeld|rounding|rundung|arrondi|qty|menge|anzahl"


def analyse_invoice(lines: list[Line], a: Analysis, roles: Optional[dict] = None) -> Analysis:
    """The total is the printed amount that the other printed amounts prove: subtotal + tax,
    items (+ tax), amount paid − change, or the stated VAT rate. Labels help, arithmetic decides —
    so an OCR-garbled 'TOTAL' still works, and a 'Total incl. VAT 2.20' line is not taken for the total."""
    entries = []  # (value, line, kind) using the rightmost amount of each line
    for l in lines:
        toks = money_tokens(l)
        if not toks:
            continue
        lab = label_of(l)
        v = abs(toks[-1].value)
        if roles is not None:
            kind = roles.get(l.number, (None,))[0]
            if kind:
                entries.append((roles[l.number][1].copy_abs(), l, kind))
            continue
        pct = PERCENT_RE.search(l.text)
        if re.search(VAT, lab) and (re.search(INCLUDED, lab) or pct or not re.search(TOTAL, lab)):
            kind = "vat"
        elif re.search(NET, lab):
            kind = "net"
        elif re.search(CHANGE, lab):
            kind = "change"
        elif re.search(PAID, lab):
            kind = "paid"
        elif re.search(NOT_TOTAL, lab):
            kind = "other"
        elif re.search(TOTAL, lab):
            kind = "total"
        elif lab and not dates_in(l.text, 2000) and len(lab) > 2:
            kind = "item"
        else:
            kind = "other"
        entries.append((v, l, kind))

    def of(kind):
        return [(v, l) for v, l, k in entries if k == kind]

    vats, nets, items, paid, change = of("vat"), of("net"), of("item"), of("paid"), of("change")
    rate_of = {}
    for v, l in vats:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s?%", l.text)
        if m:
            rate_of[l.number] = Decimal(m.group(1).replace(",", ".")) / 100
    candidates = {}
    for v, l, k in entries:
        if k in ("total", "net", "item", "paid") and v > 0:
            candidates.setdefault(v, []).append((l, k))
    results = []
    for T, where in candidates.items():
        reasons = []
        if any(near_total(n + x, T) for n, _ in nets for x, _ in vats if n < T):
            reasons.append("subtotal + tax = total")
        before = [(v, l) for v, l in items if l.number < max(w.number for w, _ in where)]
        s_items = sum((v for v, _ in before), Decimal(0))
        if len(before) >= 2 and near_total(s_items, T):
            reasons.append(f"{len(before)} line items add up")
        elif len(before) >= 2 and any(near_total(s_items + x, T) for x, _ in vats):
            reasons.append(f"{len(before)} line items + tax = total")
        if change and any(abs(p - c - T) <= TOL and c > 0 for p, _ in paid for c, _ in change):
            reasons.append("amount paid − change = total")
        elif change and any(abs(p - T) <= TOL for p, _ in paid):
            reasons.append("(approx.) paid exactly the total, no change")  # same digits twice: not independent
        elif paid and not change and any(abs(p - T) <= TOL for p, _ in paid):
            reasons.append("amount paid equals the total")
        for x, l in vats:
            r = rate_of.get(l.number)
            if r and (abs(x - (T * r / (1 + r))) <= Decimal("0.02") * 2 or any(abs(x - n * r) <= TOL * 2 and abs(n + x - T) <= TOL for n, _ in nets)):
                reasons.append(f"(approx.) tax {x} is {r * 100:.1f} % of the total")
                break
        labelled = any(k == "total" for _, k in where)
        if not reasons and not labelled:
            continue
        strong_n = sum(1 for r in reasons if not r.startswith("(approx.)"))
        results.append((strong_n + 0.25 * (len(reasons) - strong_n) + (0.5 if labelled else 0), T, where, reasons, labelled))
    results.sort(key=lambda r: (-r[0], -r[1]))
    if not results:
        a.problems.append("No total amount found.")
        return a
    best = results[0]
    tied = [r for r in results[1:] if r[0] == best[0] and r[1] != best[1]]
    line = next((l for l, k in best[2] if k == "total"), best[2][0][0])
    a.facts["total"] = fact(best[1], line, "; ".join(best[3]) if best[3] else "total label")
    # A rate check is approximate (rounding), so on its own it never confirms a total.
    strong = [r for r in best[3] if not r.startswith("(approx.)")]
    supported = bool(strong) and (best[4] or len(strong) >= 2)
    # Evidence against: printed line items that add up to neither the total nor total − tax.
    t_line = line.number
    before = [v for v, l in items if l.number < t_line]
    if supported and len(before) >= 2 and not any("line items" in r or "subtotal" in r for r in strong):
        s_items = sum(before, Decimal(0))
        if not (near_total(s_items, best[1]) or any(near_total(s_items + x, best[1]) for x, _ in vats)):
            supported = False
            a.problems.append(f"The line items add up to {s_items}, which does not match the total {best[1]}.")
    a.checks.append(Check("total supported by the other amounts", supported,
                          "; ".join(best[3]) if best[3] else "no other printed amount confirms it"))
    if tied:
        a.problems.append("Another amount fits equally well: " + ", ".join(str(r[1]) for r in tied[:3]))
    if not best[3]:
        a.problems.append("The total could not be confirmed by tax, line items or payment.")
    return a


def analyse_rules(result: TextResult) -> Analysis:
    kind, score, evidence = classify(result.lines)
    a = Analysis(kind, score, evidence)
    if kind == "payslip":
        a = analyse_payslip(result.lines, a)
        if not a.consistent:
            solved = solve_payslip(result.lines, Analysis(kind, score, evidence + ["roles from arithmetic"]))
            if solved is not None and solved.consistent:
                return solved
        return a
    if kind == "bank_statement":
        return analyse_statement(result.lines, a)
    if kind in ("invoice", "receipt"):
        return analyse_invoice(result.lines, a)
    a.problems.append("Document type not recognised.")
    return a


# --------------------------------------------------------- model assistance
ROLE_SETS = {
    "payslip": {"gross", "deduction", "total_deductions", "earning", "allowance_after", "net", "payout"},
    "invoice": {"total", "net", "vat", "item"}, "receipt": {"total", "net", "vat", "item"},
}
MODEL_PROMPT = """You read a Swiss financial document line by line. Return JSON only:
{"doc_type": "payslip" | "bank_statement" | "invoice" | "receipt" | "other",
 "roles": [{"line": <line number>, "role": <role>, "amount": "<amount exactly as printed on that line>"}]}
Roles for a payslip: gross, earning (salary items that make up gross), deduction (AHV/IV/EO, ALV, BVG, NBU,
withholding tax, other deductions), total_deductions, allowance_after (added after deductions, e.g. child
allowance or expenses), net, payout. Roles for an invoice or receipt: item, net (total before VAT), vat, total.
Only list lines that carry one of these amounts. Copy amounts exactly; never compute or invent numbers.
For a bank statement return only the doc_type."""


def _model_roles(model, result: TextResult, document_id) -> tuple[Optional[str], dict, str]:
    import json

    numbered = "\n".join(f"L{l.number}: {l.text}" for l in result.lines[:220])
    answer = model.run("understand", MODEL_PROMPT, numbered, document_id=document_id, validate=lambda x: "{" in x)
    if not answer:
        return None, {}, "the model gave no answer"
    try:
        data = json.loads(answer[answer.find("{"): answer.rfind("}") + 1])
    except ValueError:
        return None, {}, "the model's answer was not valid JSON"
    by_no = {l.number: l for l in result.lines}
    roles, rejected = {}, 0
    for r in data.get("roles") or []:
        try:
            n = int(str(r.get("line", "")).lstrip("Ll"))
            role = str(r.get("role", ""))
            line = by_no[n]
        except (ValueError, KeyError):
            rejected += 1
            continue
        claimed = str(r.get("amount", "")).strip()
        # The amount must literally be one of the amounts printed on that line.
        match = next((t for t in money_tokens(line) if t.raw.lstrip("-") == claimed.lstrip("-")
                      or str(abs(t.value)) == claimed.lstrip("-").replace("'", "").replace("’", "")), None)
        if match is None:
            rejected += 1
            continue
        roles[n] = (role, match.value)
    kind = data.get("doc_type")
    note = f"model proposed {len(roles)} roles" + (f", {rejected} rejected (not printed on the line)" if rejected else "")
    return (kind if kind in ("payslip", "bank_statement", "invoice", "receipt") else None), roles, note


def analyse(result: TextResult, model=None, document_id=None) -> Analysis:
    """Rules and arithmetic first. A model (e.g. local Apertus) is asked only when the rules are not sure;
    its proposal is accepted only if the document's arithmetic then reconciles."""
    base = analyse_rules(result)
    if model is None or base.consistent:
        return base
    kind, roles, note = _model_roles(model, result, document_id)
    kind = kind or base.doc_type
    if kind == "payslip":
        solved = solve_payslip(result.lines, Analysis("payslip", 0.7, [f"document type from the model ({note})",
                                                                      "roles from arithmetic"]))
        if solved is not None and solved.consistent:
            solved.facts["assisted_by_model"] = True
            return solved
    if kind == "bank_statement" and base.doc_type != "bank_statement":
        alt = analyse_statement(result.lines, Analysis(kind, 0.7, ["document type proposed by the model"]))
    elif kind in ROLE_SETS and roles:
        roles = {n: r for n, r in roles.items() if r[0] in ROLE_SETS[kind]}
        alt = Analysis(kind, 0.7, ["roles proposed by the model, arithmetic checked by code"])
        alt = analyse_payslip(result.lines, alt, roles) if kind == "payslip" else analyse_invoice(result.lines, alt, roles)
    else:
        base.problems.append(f"Model consulted: {note}; nothing usable.")
        return base
    if alt.consistent:
        alt.type_evidence.append(note)
        for f in alt.facts.values():
            if isinstance(f, dict) and "how" in f:
                f["how"] = f"{f['how']} (role by model, arithmetic verified)"
        alt.facts["assisted_by_model"] = True
        return alt
    base.problems.append(f"Model consulted ({note}), but its reading does not reconcile either.")
    return base
