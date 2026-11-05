"""Turn a bank statement's booking text into something a person recognises.

A statement line such as

    purchase of goods and services abroad a 0 8 7 Withdrawal location: STARLINK DUBLIN 6 7 6 - 5 4
    Transaction date: / 15:40 Card no.: 4871 52** **** 7

becomes kind "card", merchant "Starlink", place "Dublin". The bank's own boilerplate (booking numbers, card
numbers, times) and OCR debris from neighbouring columns (runs of single letters and digits such as
"2 4 - P - G" or "T M _ T D _ T M") are dropped. Nothing is invented: the merchant is always a piece of the
original text, and the original stays in the record's description.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------------- noise
_SINGLE_RUN = re.compile(r"(?<![\w.])(?:[\w*+\-_/.](?:\s+|\s*[-_]\s*)){2,}[\w*+\-_/.](?![\w.])")
_BOILER = [
    r"\b(?:BKB|bank)?\s*booking\s*no\.?\s*:?\s*\d+",
    r"\bbuchungs?-?nr\.?\s*:?\s*\d+",
    r"\bcard\s*no\.?\s*:?\s*[\d*\s]{4,}",
    r"\bkarten-?nr\.?\s*:?\s*[\d*\s]{4,}",
    r"\btransaction\s*dat\w*\s*:?\s*/?\s*(?:\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)?",
    r"\btransaktionsdatum\s*:?\s*/?\s*(?:\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)?",
    r"\b\d{1,2}:\d{2}(?::\d{2})?\b",
    r"\*{2,}",
]


def _single_char_runs(text: str) -> str:
    """Remove runs of 3+ one-character tokens ("2 4 - P - G", "T M _ T D _ T M", "S _ C C")."""
    out = []
    for tok_run in re.split(r"(\s+)", text):
        out.append(tok_run)
    text = "".join(out)
    tokens = text.split()
    keep, run = [], []

    def flush():
        if len(run) >= 3:
            pass  # debris
        else:
            keep.extend(run)
        run.clear()

    for t in tokens:
        if len(t) == 1 or t in ("_", "-", "/"):
            run.append(t)
        else:
            flush()
            keep.append(t)
    flush()
    return " ".join(keep)


def clean(text: str) -> str:
    t = " ".join(text.split())
    for pat in _BOILER:
        t = re.sub(pat, " ", t, flags=re.I)
    t = _single_char_runs(t)
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    t = re.sub(r"(?:\s*[,/;:]\s*)+$", "", t)
    return " ".join(t.split()).strip(" -_/,;:")


# --------------------------------------------------------------------------- merchants we know
# needle (case-insensitive, on the cleaned text) → display name, category path
KNOWN: list[tuple[str, str, tuple[str, ...]]] = [
    (r"booking\s*\.?\s*com|bkgbookingcom|bkg\*?booking", "Booking.com", ("Leisure", "Travel")),
    (r"airbnb", "Airbnb", ("Leisure", "Travel")),
    (r"easyjet", "easyJet", ("Leisure", "Travel")),
    (r"swiss\s*int|swiss\.com", "SWISS", ("Leisure", "Travel")),
    (r"sbb\s*easyride|easyride", "SBB EasyRide", ("Transport", "Public transport")),
    (r"\bsbb\b|\bcff\b|\bffs\b|sbb\s*mobile", "SBB", ("Transport", "Public transport")),
    (r"\bbvb\b|basler\s*verkehrs", "BVB", ("Transport", "Public transport")),
    (r"\bzvv\b", "ZVV", ("Transport", "Public transport")),
    (r"postauto", "PostAuto", ("Transport", "Public transport")),
    (r"\buber\b", "Uber", ("Transport", "Taxi")),
    (r"starlink", "Starlink", ("Housing", "Telecom")),
    (r"swisscom", "Swisscom", ("Housing", "Telecom")),
    (r"sunrise", "Sunrise", ("Housing", "Telecom")),
    (r"\bsalt\b", "Salt", ("Housing", "Telecom")),
    (r"migros", "Migros", ("Food", "Groceries")),
    (r"\bcoop\b", "Coop", ("Food", "Groceries")),
    (r"denner", "Denner", ("Food", "Groceries")),
    (r"\baldi\b", "Aldi", ("Food", "Groceries")),
    (r"\blidl\b", "Lidl", ("Food", "Groceries")),
    (r"marktkauf", "Marktkauf", ("Food", "Groceries")),
    (r"mini\s*mix", "Mini Mix", ("Food", "Groceries")),
    (r"\bvolg\b", "Volg", ("Food", "Groceries")),
    (r"\bspar\b", "Spar", ("Food", "Groceries")),
    (r"\bedeka\b", "Edeka", ("Food", "Groceries")),
    (r"\brewe\b", "Rewe", ("Food", "Groceries")),
    (r"kaufland", "Kaufland", ("Food", "Groceries")),
    (r"mcdonald", "McDonald's", ("Food", "Restaurants")),
    (r"starbucks", "Starbucks", ("Food", "Restaurants")),
    (r"\bcaf[eé]\b|\bbistro\b|\brestaurant\b|\bpizzeria\b|\bbar\b|\bbeiz\b", None, ("Food", "Restaurants")),
    (r"ricardo", "Ricardo", ("Shopping", "Online")),
    (r"galaxus|digitec", "Digitec Galaxus", ("Shopping", "Online")),
    (r"amazon|amzn", "Amazon", ("Shopping", "Online")),
    (r"zalando", "Zalando", ("Shopping", "Online")),
    (r"\bikea\b", "IKEA", ("Housing", "Furniture")),
    (r"apotheke|pharmacie|farmacia|amavita|sunstore", None, ("Healthcare", "Pharmacy")),
    (r"spotify", "Spotify", ("Subscriptions", "Streaming")),
    (r"netflix", "Netflix", ("Subscriptions", "Streaming")),
    (r"apple\.com|itunes", "Apple", ("Subscriptions", "Apps")),
    (r"google\s*\*|google\s*play", "Google", ("Subscriptions", "Apps")),
    (r"openai|chatgpt", "OpenAI", ("Subscriptions", "Apps")),
    (r"anthropic|claude\.ai", "Anthropic", ("Subscriptions", "Apps")),
    (r"helsana|css\s*kranken|swica|sanitas|visana|concordia|assura", None, ("Insurance", "Health insurance")),
    (r"steuerverwaltung|steueramt", None, ("Taxes", "Cantonal")),
]

OWN_ACCOUNT_BANKS = re.compile(r"\b(?:revolut|transferwise|wise|neon|yuh|zak|n26)\b", re.I)


@dataclass
class Booking:
    kind: str                         # card · cash · transfer_out · transfer_in · p2p_out · p2p_in · bill · collective · other
    merchant: str
    place: str = ""
    category: Optional[tuple[str, ...]] = None
    own_account: Optional[bool] = None  # True: certainly own; None: unknown
    possibly_own: bool = False
    notes: list[str] = field(default_factory=list)


def _title(s: str) -> str:
    """BKB VOGESENPLATZ → BKB Vogesenplatz (keeps short all-caps words such as BKB, SBB, AG)."""
    words = []
    for w in s.split():
        if w.isupper() and len(w) > 3 and not re.search(r"\d", w):
            w = w.capitalize()
        words.append(w)
    return " ".join(words)


def _known(text: str) -> Optional[tuple[Optional[str], tuple[str, ...]]]:
    for pat, name, cat in KNOWN:
        if re.search(pat, text, re.I):
            return name, cat
    return None


def _owner_in(text: str, owners: list[str]) -> bool:
    low = text.casefold()
    for o in owners:
        parts = [p for p in o.casefold().split() if len(p) > 2]
        if len(parts) >= 2 and all(p in low for p in parts):
            return True
    return False


def parse(text: str, owners: Optional[list[str]] = None) -> Booking:
    """`owners`: names of the account holder(s), e.g. from the statement header."""
    owners = owners or []
    raw = " ".join(text.split())
    t = clean(raw)
    low = t.casefold()

    def result(kind: str, merchant: str, place: str = "", category=None, **kw) -> Booking:
        merchant = clean(merchant).strip(" ,;:") or clean(raw)[:60]
        hit = _known(merchant) or _known(t)
        if hit:
            name, cat = hit
            merchant = name or merchant
            category = category or cat
        return Booking(kind, _title(merchant)[:80], _title(place)[:60], category, **kw)

    # cash at an ATM
    if re.search(r"\batm\b|cash\s*withdrawal|bargeldbezug|geldautomat|retrait\s*d'?esp|bancomat", low):
        m = re.search(r"(?:withdrawal\s*location|ort|lieu)\s*:?\s*(.+)", t, re.I)
        place = m.group(1) if m else ""
        return Booking("cash", "Cash withdrawal", _title(clean(place))[:60], ("Cash", "Withdrawals"))

    # card payments (also abroad)
    if re.search(r"purchase\s*of\s*goods|einkauf|achat|acquisto|debit\s*card|maestro|card\s*payment|kartenzahlung", low):
        m = re.search(r"(?:withdrawal\s*location|location|ort|lieu)\s*:?\s*(.+)", t, re.I)
        loc = m.group(1) if m else re.sub(r"^.*?(purchase\s*of\s*goods\s*and\s*services(\s*abroad)?|einkauf|achat)\s*", "", t, flags=re.I)
        loc = clean(loc)
        merchant, place = loc, ""
        pm = re.match(r"(.+?)\s+(ZURICH|ZÜRICH|ZUERICH|BASEL|BERN|GENEVE|GENÈVE|LAUSANNE|LUZERN|DUBLIN|LONDON|AMSTERDAM|"
                      r"BERLIN|PARIS|MILANO|WIEN|MULHOUSE|LÖRRACH|LOERRACH|WEIL\s*AM\s*RHEIN|ST\.?\s*LOUIS)\b.*$", loc, re.I)
        if pm:
            merchant, place = pm.group(1), pm.group(2)
        merchant = re.sub(r"\b(gmbh|ag|sa|sarl|ltd|inc|b\.?v\.?|s\.?a\.?r\.?l\.?|hote?l?)\b\.?$", "", merchant, flags=re.I).strip()
        abroad = "abroad" in low or "ausland" in low
        sumup = re.match(r"\s*(?:sumup|sum\s*up|sq\s*\*|zettle_?\*?)\s*\*?\s*(.+)", merchant, re.I)
        if sumup:
            merchant = sumup.group(1)
        b = result("card", merchant or loc, place)
        if abroad:
            b.notes.append("abroad")
        if sumup and b.category is None:
            b.notes.append("paid by card through SumUp or similar (a small shop, café or market stall)")
        return b

    # mobile phone transfers (TWINT and the like)
    p2p = re.search(r"money\s*transfer\s*(to|from)\s*\S*?\s*(\+?\d[\d\s]{8,})", t, re.I)
    if p2p:
        out = p2p.group(1).lower() == "to"
        phone = re.sub(r"\s", "", p2p.group(2))
        rest = clean(t[p2p.end():])
        who = f"{'To' if out else 'From'} {phone}"
        b = Booking("p2p_out" if out else "p2p_in", who, "", ("Transfers", "To people") if out else ("Other income",))
        if rest:
            b.notes.append(rest[:120])
        return b

    # collective payment orders: several bills paid in one booking
    if re.search(r"collective\s*order|sammelauftrag|ordre\s*group|ordine\s*collettivo", low):
        return Booking("collective", "Collective payment order", "", ("Bills", "Collective payment orders"),
                       notes=["several payments booked as one; the bank's order detail shows who was paid"])

    # bank transfers out/in, with the beneficiary in the text
    to_own = _owner_in(t, owners)
    if OWN_ACCOUNT_BANKS.search(t) or to_own:
        bank = OWN_ACCOUNT_BANKS.search(t)
        name = (bank.group(0).title() if bank else "Account") + (" (your account)" if to_own else "")
        return Booking("transfer_out", name, "", ("Own transfers",) if to_own else None,
                       own_account=True if to_own else None, possibly_own=not to_own)

    m = re.match(r"^(payment|debit|credit|zahlung|gutschrift|lastschrift|e-banking[\w-]*|order|auftrag)\b\s*(?:to|an|from|von)?\s*(.+)$",
                 t, re.I)
    if m:
        body = m.group(2)
        body = re.split(r"\s(?:\+?\d{9,}|CH\d{2}\s?\d{4}|IBAN)\b", body)[0]
        body = re.split(r",\s*", body)[0] if re.search(r",\s*\S", body) and len(body) > 40 else body
        kind = "transfer_in" if m.group(1).lower() in ("credit", "gutschrift") else "bill"
        return result(kind, body)
    return result("other", t)


_NAME_LINE = re.compile(r"^(?:(?:herr|frau|mr\.?|mrs\.?|ms\.?|monsieur|madame|signor[ae]?)\s+)?"
                        r"([A-ZÄÖÜÀ-Ý][\w'’-]+(?:\s+[A-ZÄÖÜÀ-Ý][\w'’-]+){1,3})\s*$")
_NOT_NAME = re.compile(r"\b(bank|kantonalbank|statement|auszug|account|konto|relevé|seite|page|iban|bic|swift|"
                       r"strasse|str\.|platz|weg|gasse|avenue|rue|via|ag|gmbh|sa|basel|zürich|zurich|bern|genève|"
                       r"private|privatkonto|sparkonto|currency|währung|balance|saldo|date|datum)\b", re.I)


def owners_from_header(header: str) -> list[str]:
    """Names of account holders printed above the bookings ("Mykhailo Shavrytskyi", "Herr Max Muster")."""
    out = []
    for line in header.splitlines()[:60]:
        line = " ".join(line.split())
        for part in re.split(r"\s{2,}|\s+[|·]\s+|,\s*(?=[A-ZÄÖÜ])", line) if line else []:
            m = _NAME_LINE.match(part.strip())
            if m and not _NOT_NAME.search(m.group(1)) and m.group(1) not in out:
                out.append(m.group(1))
    return out


def label(b: Booking) -> str:
    """What the ledger shows as the counterparty."""
    if b.kind == "cash":
        return f"Cash withdrawal, {b.place}" if b.place else "Cash withdrawal"
    return f"{b.merchant}, {b.place}" if b.place else b.merchant
