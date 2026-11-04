"""Natural-language questions (§11).

The question is turned into a structured query; the answer (totals, lists)
is computed by code from the ledger and always links to the operations and
original documents. A model may help *parse* a question it is given, never
compute the answer. Understands English, German, French and Ukrainian.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from . import analytics
from .service import FinancialLens

CATEGORY_WORDS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("car repair", "ремонт авто", "ремонт машин", "autoreparatur", "réparation", "werkstatt"), ("Transport", "Car repairs")),
    (("food", "їж", "продукт", "харч", "essen", "lebensmittel", "nourriture", "alimentation"), ("Food",)),
    (("groceries", "супермаркет", "einkauf"), ("Food", "Groceries")),
    (("restaurant", "ресторан", "кафе"), ("Food", "Restaurants")),
    (("housing", "житл", "оренд", "wohnen", "logement", "miete", "rent"), ("Housing",)),
    (("electricity", "електр", "strom"), ("Housing", "Electricity")),
    (("transport", "транспорт", "verkehr", "mobilit"), ("Transport",)),
    (("insurance", "страхув", "versicherung", "assurance"), ("Insurance",)),
    (("health", "медиц", "здоров", "gesundheit", "santé", "healthcare"), ("Healthcare",)),
    (("tax", "подат", "steuer", "impôt"), ("Taxes",)),
    (("leisure", "дозвіл", "freizeit", "loisir"), ("Leisure",)),
]


@dataclass
class Query:
    intent: str = "list"  # list, total, unpaid, no_evidence, unlinked_documents, growth
    category: Optional[list[str]] = None
    counterparty: Optional[str] = None
    min_amount: Optional[str] = None
    start: Optional[date] = None
    end: Optional[date] = None
    period_label: str = "all time"
    notes: list[str] = field(default_factory=list)


def _period(q: str, today: date) -> tuple[Optional[date], Optional[date], str]:
    if re.search(r"last 12 months|past 12 months|останні 12 місяц|за 12 місяц|letzten 12 monat|12 derniers mois", q):
        return today - timedelta(days=365), today, "last 12 months"
    if re.search(r"last year|минулого року|минулий рік|letztes jahr|vorjahr|l'année dernière", q) and \
            not re.search(r"(than|ніж|als|vs|порівняно|compared)", q):
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), str(today.year - 1)
    if re.search(r"this month|цього місяця|цей місяць|diesen monat|ce mois", q):
        return today.replace(day=1), today, "this month"
    if re.search(r"this year|цього року|цей рік|за рік|dieses jahr|cette année|in \d{4}|за \d{4}|у \d{4}|\b20\d\d\b", q):
        m = re.search(r"\b(20\d\d)\b", q)
        year = int(m.group(1)) if m else today.year
        return date(year, 1, 1), min(today, date(year, 12, 31)) if year == today.year else date(year, 12, 31), str(year)
    return None, None, "all time"


def parse(question: str, today: Optional[date] = None) -> Query:
    today = today or date.today()
    q = question.casefold()
    query = Query()
    query.start, query.end, query.period_label = _period(q, today)
    if re.search(r"unpaid|неоплачен|не оплачен|unbezahlt|offene rechnung|impayé", q):
        query.intent = "unpaid"
    elif re.search(r"without (evidence|document)|no (evidence|document)|без доказ|без документ|ohne beleg|sans justificatif", q):
        query.intent = "no_evidence"
    elif re.search(r"not linked|не прив.язан|не пов.язан|nicht verknüpft|non lié", q):
        query.intent = "unlinked_documents"
    elif re.search(r"grew|increase|зросл|збільшил|gestiegen|zugenommen|augmenté", q):
        query.intent = "growth"
    elif re.search(r"how much|скільки|wie viel|combien|total|сума|витрат", q):
        query.intent = "total"
    for words, path in CATEGORY_WORDS:
        if any(w in q for w in words):
            query.category = list(path)
            break
    m = re.search(r"(?:over|above|more than|більше|понад|вище|über|mehr als|plus de)\s*(?:chf\s*)?(\d[\d'’ ]*(?:[.,]\d{1,2})?)", q)
    if m:
        query.min_amount = re.sub(r"['’ ]", "", m.group(1)).replace(",", ".")
    m = re.search(r"(?:payments? to|paid to|платежі на|платежі для|оплати на|zahlungen an|an|paiements à)\s+([A-ZÄÖÜ][\w&.\-]+(?:\s[A-ZÄÖÜ][\w&.\-]+)?)",
                  question)
    if m:
        query.counterparty = m.group(1)
    m = re.search(r"(?:member|член[а-я]*|mitglied[a-z]*|membre)\s+([A-ZА-ЯІЇЄÄÖÜ][\w\-]+(?:\s[A-ZА-ЯІЇЄÄÖÜ][\w\-]+)?)", question)
    if m:
        query.counterparty = m.group(1)
        query.notes.append("member contributions")
    return query


def _parse_with_model(lens: FinancialLens, question: str) -> Optional[Query]:
    if lens.ai is None:
        return None
    system = ("Convert a question about personal finances into JSON with keys intent (list|total|unpaid|no_evidence|"
              "unlinked_documents|growth), category (list of names or null), counterparty, min_amount, start, end "
              "(ISO dates or null). Do not answer the question and do not compute any number.")
    answer = lens.ai.run("parse_question", system, question)
    if not answer:
        return None
    try:
        data = json.loads(answer[answer.find("{"): answer.rfind("}") + 1])
        return Query(intent=data.get("intent", "list"), category=data.get("category"),
                     counterparty=data.get("counterparty"), min_amount=data.get("min_amount"),
                     start=date.fromisoformat(data["start"]) if data.get("start") else None,
                     end=date.fromisoformat(data["end"]) if data.get("end") else None, period_label="as parsed",
                     notes=["question parsed by model"])
    except (ValueError, TypeError):
        return None


def ask(lens: FinancialLens, question: str, today: Optional[date] = None) -> dict:
    today = today or date.today()
    query = parse(question, today)
    if query.intent == "list" and not (query.category or query.counterparty or query.min_amount):
        query = _parse_with_model(lens, question) or query
    start = query.start or date(1970, 1, 1)
    end = query.end or date(2999, 12, 31)

    if query.intent == "unpaid":
        items = analytics.unpaid(lens, today)
        total = sum((Decimal(i["open"]) for i in items if i["currency"] == "CHF"), Decimal(0))
        return _answer(query, f"{len(items)} unpaid invoices, CHF {total:.2f} open.", total,
                       [{"id": i["operation_id"], "label": f"{i['counterparty']} · {i['currency']} {i['open']}"
                         + (" · overdue" if i["overdue"] else "")} for i in items])
    if query.intent == "no_evidence":
        rows = lens.db.execute(
            "SELECT c.* FROM operations_current c WHERE organization_id=%s AND op_date BETWEEN %s AND %s AND kind <> 'transfer' "
            "AND NOT EXISTS (SELECT 1 FROM document_operations d JOIN documents x ON x.id=d.document_id WHERE "
            "d.operation_id=c.operation_id AND x.doc_type <> 'bank_statement') ORDER BY op_date DESC",
            (lens.org, start, end)).fetchall()
        return _answer(query, f"{len(rows)} operations have no supporting document (receipt or invoice).", None,
                       [_item(lens, r) for r in rows])
    if query.intent == "unlinked_documents":
        rows = lens.db.execute(
            "SELECT c.* FROM operations_current c WHERE organization_id=%s AND kind IN ('invoice','receipt','expense') "
            "AND source_document_id IS NOT NULL AND op_date BETWEEN %s AND %s AND NOT EXISTS (SELECT 1 FROM links l "
            "WHERE l.from_operation_id=c.operation_id AND l.link_type='payment' AND l.status='confirmed') ORDER BY op_date DESC",
            (lens.org, start, end)).fetchall()
        return _answer(query, f"{len(rows)} documents are not linked to a bank transaction.", None,
                       [_item(lens, r) for r in rows])
    if query.intent == "growth":
        this = (date(today.year, 1, 1), today)
        last = (date(today.year - 1, 1, 1), today.replace(year=today.year - 1))
        rows = [r for r in analytics.compare(lens, last, this) if Decimal(r["change"]) > 0]
        text = "; ".join(f"{' / '.join(r['category'])} +CHF {Decimal(r['change']):.2f}" for r in rows[:5]) or "Nothing grew."
        return _answer(query, f"Compared with the same period last year: {text}", None,
                       [{"category": r["category"], "label": f"{r['a']} → {r['b']}"} for r in rows])

    # list / total with filters
    ops = lens.operations(start, end, tuple(query.category or ()))
    if query.counterparty:
        needle = query.counterparty.casefold()
        ops = [o for o in ops if needle in (o["counterparty"] or "").casefold()]
    if query.min_amount:
        ops = [o for o in ops if Decimal(o["amount"]) > Decimal(query.min_amount)]
    total = sum((Decimal(o["amount"]) for o in ops), Decimal(0))
    what = " / ".join(query.category) if query.category else "spending"
    text = f"{what} ({query.period_label}): CHF {total:.2f} in {len(ops)} operations."
    return _answer(query, text, total, [{"id": o["id"], "label": f"{o['date']} · {o['counterparty']} · CHF {o['amount']}",
                                         "verification": o["verification"]} for o in ops])


def _item(lens: FinancialLens, r: dict) -> dict:
    return {"id": str(r["operation_id"]), "label": f"{r['op_date']} · {r['counterparty']} · {r['currency']} {abs(r['amount']):.2f}",
            "verification": r["verification"]}


def _answer(query: Query, text: str, total: Optional[Decimal], items: list[dict]) -> dict:
    q = asdict(query)
    q["start"] = query.start.isoformat() if query.start else None
    q["end"] = query.end.isoformat() if query.end else None
    return {"answer": text, "total": None if total is None else str(total), "items": items, "query": q,
            "computed_by": "deterministic ledger query"}
