"""CSV and XLSX bank exports. Columns are recognised by their headers in
German, French, Italian and English; rows that cannot be read are reported,
not guessed."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..domain.events import Method, Payment, Provenance
from ..domain.money import Money

HEADERS = {
    "date": ["buchungsdatum", "datum", "date", "booking date", "data", "date comptable", "valuta", "valutadatum", "value date"],
    "amount": ["betrag", "amount", "montant", "importo", "betrag chf"],
    "debit": ["belastung", "soll", "debit", "débit", "addebito", "lastschrift"],
    "credit": ["gutschrift", "haben", "credit", "crédit", "accredito"],
    "text": ["buchungstext", "text", "beschreibung", "description", "libellé", "descrizione", "details", "mitteilung", "verwendungszweck"],
    "counterparty": ["empfänger", "auftraggeber", "name", "counterparty", "bénéficiaire", "beneficiario", "payee", "zahlungsempfänger"],
    "currency": ["währung", "currency", "devise", "valuta iso", "ccy"],
    "reference": ["referenz", "reference", "référence", "riferimento", "qr-referenz"],
}


class TabularError(ValueError):
    pass


def _match(header: str) -> Optional[str]:
    h = header.strip().casefold()
    for key, words in HEADERS.items():
        if h in words:
            return key
    for key, words in HEADERS.items():
        if any(w in h for w in words):
            return key
    return None


def _amount(text) -> Optional[Decimal]:
    if text is None or text == "":
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return Decimal(str(text)).quantize(Decimal("0.01"))
    t = str(text).strip().replace("'", "").replace("’", "").replace(" ", "").replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+,\d{2}", t) or re.fullmatch(r"-?\d+,\d{2}", t):
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    t = str(value or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def rows_from_csv(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    return [r for r in csv.reader(io.StringIO(text), dialect)]


def rows_from_xlsx(data: bytes) -> list[list]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]


def parse(rows: list[list], document_id: str, currency: str = "CHF", engine: str = "csv") -> tuple[list[Payment], list[str]]:
    header_at, columns = None, {}
    for i, row in enumerate(rows[:20]):
        found = {}
        for j, cell in enumerate(row):
            key = _match(str(cell or ""))
            if key and key not in found:
                found[key] = j
        if "date" in found and ("amount" in found or "debit" in found or "credit" in found):
            header_at, columns = i, found
            break
    if header_at is None:
        raise TabularError("No date and amount columns found; this does not look like a bank export.")
    payments, problems, seen = [], [], {}
    for i, row in enumerate(rows[header_at + 1:], start=header_at + 2):
        cell = lambda k: row[columns[k]] if k in columns and columns[k] < len(row) else None  # noqa: E731
        if not any(c not in (None, "") for c in row):
            continue
        booked = _date(cell("date"))
        if "amount" in columns:
            amount = _amount(cell("amount"))
        else:
            debit, credit = _amount(cell("debit")), _amount(cell("credit"))
            amount = (credit or Decimal(0)) - (abs(debit) if debit else Decimal(0)) if (debit or credit) else None
        if booked is None or amount is None:
            problems.append(f"Row {i}: could not read date or amount; skipped")
            continue
        cur = str(cell("currency") or currency).strip().upper() or currency
        text = str(cell("text") or "").strip()
        party = str(cell("counterparty") or "").strip() or text[:60]
        payments.append(Payment(
            amount=Money(amount.quantize(Decimal("0.01")), cur), booked_on=booked, counterparty=party,
            reference=(str(cell("reference")).replace(" ", "") if cell("reference") else None),
            bank_reference=_key(seen, f"{engine}:{booked.isoformat()}:{amount}:{party[:30]}:{text[:30]}"),
            remittance=text or None,
            provenance=Provenance(document_id, f"{engine} row {i}", Method.STRUCTURED_IMPORT, f"parser:{engine}")))
    return payments, problems


def _key(seen: dict, base: str) -> str:
    """Stable per-file key: identical rows on the same day stay distinct, re-imports match."""
    seen[base] = seen.get(base, 0) + 1
    return f"{base}#{seen[base]}"
