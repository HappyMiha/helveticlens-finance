"""Phase 2 analytics (§6.3, §6.4). Every number is computed by code from
current operations; nothing here asks a model for a total."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Optional

from .service import BASE, FinancialLens, _similar


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _month_end(y: int, m: int) -> date:
    return (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)


def by_category(lens: FinancialLens, start: date, end: date, depth: int = 1) -> dict[tuple, Decimal]:
    paths = {c["id"]: c["path"] for c in lens.categories()}
    out: dict[tuple, Decimal] = defaultdict(Decimal)
    for r in lens._spend_rows(start, end):
        value = lens._in_base(r)
        if value is not None:
            out[paths.get(str(r["category_id"]), ("Unclassified",))[:depth]] += value
    return dict(out)


def compare(lens: FinancialLens, a: tuple[date, date], b: tuple[date, date], depth: int = 1) -> list[dict]:
    """Category totals for period a vs period b, largest change first."""
    left, right = by_category(lens, *a, depth), by_category(lens, *b, depth)
    rows = []
    for key in set(left) | set(right):
        x, y = left.get(key, Decimal(0)), right.get(key, Decimal(0))
        rows.append({"category": list(key), "a": str(x), "b": str(y), "change": str(y - x),
                     "change_pct": None if x == 0 else str(((y - x) / x * 100).quantize(Decimal("0.1")))})
    return sorted(rows, key=lambda r: -abs(Decimal(r["change"])))


def previous_period(start: date, end: date) -> tuple[date, date]:
    if start.day == 1 and end == _month_end(end.year, end.month):
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        y, m = start.year, start.month - months
        while m <= 0:
            y, m = y - 1, m + 12
        ps = date(y, m, 1)
        y2, m2 = ps.year, ps.month + months - 1
        while m2 > 12:
            y2, m2 = y2 + 1, m2 - 12
        return ps, _month_end(y2, m2)
    span = end - start
    return start - span - timedelta(days=1), start - timedelta(days=1)


def cash_flow(lens: FinancialLens, start: date, end: date) -> list[dict]:
    """Per month: income, expenses, net and cumulative savings (§6.4)."""
    out, cumulative = [], Decimal(0)
    for y, m in _month_iter(start, end):
        s, e = max(start, date(y, m, 1)), min(end, _month_end(y, m))
        inc = sum((lens._in_base(r) or Decimal(0)) for r in lens._income_rows(s, e))
        exp = sum((lens._in_base(r) or Decimal(0)) for r in lens._spend_rows(s, e))
        cumulative += inc - exp
        out.append({"month": f"{y}-{m:02d}", "income": str(inc), "expenses": str(exp), "net": str(inc - exp),
                    "cumulative": str(cumulative)})
    return out


def by_counterparty(lens: FinancialLens, start: date, end: date, limit: int = 20) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in lens._spend_rows(start, end):
        value = lens._in_base(r)
        if value is None:
            continue
        key = _normalise(r["counterparty"]) or "(unknown)"
        g = groups.setdefault(key, {"counterparty": r["counterparty"] or "(unknown)", "total": Decimal(0),
                                    "count": 0, "operations": []})
        g["total"] += value
        g["count"] += 1
        g["operations"].append(str(r["operation_id"]))
    rows = sorted(groups.values(), key=lambda g: -g["total"])[:limit]
    return [{**g, "total": str(g["total"])} for g in rows]


def top_expenses(lens: FinancialLens, start: date, end: date, limit: int = 10) -> list[dict]:
    rows = [(lens._in_base(r), r) for r in lens._spend_rows(start, end)]
    rows = sorted((t for t in rows if t[0] is not None), key=lambda t: -t[0])[:limit]
    return [{"id": str(r["operation_id"]), "amount": str(v), "date": r["op_date"].isoformat(),
             "counterparty": r["counterparty"], "verification": r["verification"]} for v, r in rows]


def _normalise(name: str) -> str:
    name = name.casefold()
    name = re.sub(r"\b(ag|gmbh|sa|sàrl|sarl|ltd|inc|llc|genossenschaft)\b", "", name)
    name = re.sub(r"[^a-zäöüéèàç0-9 ]", " ", name)
    return " ".join(name.split()[:3])


CADENCES = [("weekly", 7, 2), ("monthly", 30.4, 5), ("quarterly", 91.3, 10), ("yearly", 365.25, 20)]


@dataclass
class Recurring:
    counterparty: str
    cadence: str
    typical_amount: Decimal
    currency: str
    last_date: date
    next_expected: date
    occurrences: int
    category_id: Optional[str]
    operation_ids: list[str]


def detect_recurring(lens: FinancialLens, until: Optional[date] = None) -> list[Recurring]:
    """Counterparties paid at a regular interval with a stable amount (±10 %)."""
    until = until or date.today()
    rows = lens.db.execute(
        "SELECT * FROM operations_current WHERE organization_id=%s AND op_date <= %s AND "
        "(kind IN ('invoice','receipt','expense') OR (kind='payment' AND amount < 0 AND NOT EXISTS ("
        "SELECT 1 FROM links l WHERE l.to_operation_id=operations_current.operation_id AND l.status <> 'rejected')))"
        " ORDER BY op_date", (lens.org, until)).fetchall()
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(_normalise(r["counterparty"]), r["currency"])].append(r)
    found = []
    for (name, cur), items in groups.items():
        if not name or len(items) < 3:
            continue
        gaps = [(b["op_date"] - a["op_date"]).days for a, b in zip(items, items[1:])]
        amounts = [abs(r["amount"]) for r in items]
        mid = Decimal(median(amounts))
        if any(abs(a - mid) > mid * Decimal("0.10") for a in amounts[-3:]):
            continue
        g = median(gaps)
        for cadence, days, tolerance in CADENCES:
            if abs(g - days) <= tolerance and all(abs(x - days) <= tolerance * 2 for x in gaps[-3:]):
                last = items[-1]["op_date"]
                found.append(Recurring(items[-1]["counterparty"], cadence, mid.quantize(Decimal("0.01")), cur, last,
                                       last + timedelta(days=round(days)), len(items),
                                       str(items[-1]["category_id"]) if items[-1]["category_id"] else None,
                                       [str(r["operation_id"]) for r in items]))
                break
    return found


def save_recurring(lens: FinancialLens, until: Optional[date] = None) -> list[dict]:
    out = []
    with lens.db.transaction():
        for r in detect_recurring(lens, until):
            lens.db.execute(
                "INSERT INTO recurring_rules (id, organization_id, counterparty, cadence, typical_amount, currency, "
                "category_id, last_date, next_expected, occurrences, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'proposed') "
                "ON CONFLICT (organization_id, counterparty, cadence) DO UPDATE SET typical_amount=EXCLUDED.typical_amount, "
                "last_date=EXCLUDED.last_date, next_expected=EXCLUDED.next_expected, occurrences=EXCLUDED.occurrences, "
                "updated_at=now()",
                (str(uuid.uuid4()), lens.org, r.counterparty, r.cadence, r.typical_amount, r.currency, r.category_id,
                 r.last_date, r.next_expected, r.occurrences))
            out.append({"counterparty": r.counterparty, "cadence": r.cadence, "amount": str(r.typical_amount),
                        "next_expected": r.next_expected.isoformat(), "occurrences": r.occurrences,
                        "operations": r.operation_ids})
    return out


def missing_recurring(lens: FinancialLens, today: Optional[date] = None, grace_days: int = 7) -> list[dict]:
    """Expected recurring payments that have not appeared (e.g. a rent not yet paid)."""
    today = today or date.today()
    rows = lens.db.execute("SELECT * FROM recurring_rules WHERE organization_id=%s AND status <> 'dismissed' "
                           "AND next_expected + %s < %s", (lens.org, grace_days, today)).fetchall()
    return [lens._json(r) for r in rows]


def unpaid(lens: FinancialLens, today: Optional[date] = None) -> list[dict]:
    today = today or date.today()
    rows = lens.db.execute("SELECT operation_id, counterparty, amount, currency, op_date, due_date FROM operations_current "
                           "WHERE organization_id=%s AND kind='invoice' ORDER BY coalesce(due_date, op_date)",
                           (lens.org,)).fetchall()
    out = []
    for r in rows:
        st = lens.payment_status(str(r["operation_id"]))
        if st["state"] in ("unpaid", "partially_paid"):
            overdue = r["due_date"] is not None and r["due_date"] < today
            out.append({**lens._json(r), **st, "overdue": overdue,
                        "days_overdue": (today - r["due_date"]).days if overdue else 0})
    return out
