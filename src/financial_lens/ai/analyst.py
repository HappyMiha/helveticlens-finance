"""Apertus analyst: the local model reads a whole document, the program checks what it says.

Used with Apertus 1.5 on computers with a strong graphics card. The model returns the merchant, date, total,
VAT, every line item, a category and a one-line summary. Nothing it says is taken on trust: a name counts only
if it is printed in the document, an amount only if that amount is printed, and the items are added up and
compared with the total. The result is kept with the upload so a person can see what was read.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..extract.understand import money_tokens

PROMPT = """You are a careful Swiss bookkeeper. You get the text of one document, line by line (from a scan or a PDF),
and a list of categories. Return JSON only, no other text:
{"doc_type": "receipt" | "invoice" | "payslip" | "bank_statement" | "other",
 "merchant": "<shop or company that issued the document, exactly as printed>",
 "date": "<YYYY-MM-DD, the purchase or invoice date>",
 "currency": "<CHF, EUR, ...>",
 "total": "<amount to pay, exactly as printed>",
 "vat": "<VAT amount exactly as printed, or null>",
 "payment": "card" | "cash" | "twint" | "invoice" | "other" | null,
 "items": [{"name": "<item as printed>", "qty": <number or null>, "amount": "<line amount exactly as printed>"}],
 "category": "<one category from the list>",
 "summary": "<one short sentence: what was bought or billed>"}
Copy names and amounts exactly as they are printed. Never compute, round or invent numbers. Use null when
something is not in the document. Choose the category only from the list."""


def _dec(s) -> Optional[Decimal]:
    if s is None:
        return None
    t = re.sub(r"[^\d.,\-]", "", str(s)).replace("'", "")
    if t.count(",") == 1 and t.count(".") == 0:
        t = t.replace(",", ".")
    t = t.replace(",", "")
    try:
        return Decimal(t).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().casefold()


def read(model, text, categories: list[str], document_id: Optional[str] = None,
         model_name: str = "Apertus 1.5") -> Optional[dict]:
    lines = text.lines[:400]
    numbered = "\n".join(f"L{l.number}: {l.text}" for l in lines)
    user = numbered + "\n\nCategories:\n" + "\n".join(categories)
    answer = model.run("understand", PROMPT, user, document_id=document_id, validate=lambda x: "{" in x)
    if not answer:
        return None
    try:
        data = json.loads(answer[answer.find("{"): answer.rfind("}") + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    printed = {abs(t.value).quantize(Decimal("0.01")) for l in lines for t in money_tokens(l)}
    whole = _norm(text.text)

    merchant = str(data.get("merchant") or "").strip()
    merchant_printed = bool(merchant) and _norm(merchant) in whole
    total = _dec(data.get("total"))
    total_printed = total is not None and abs(total) in printed
    vat = _dec(data.get("vat"))
    items, dropped = [], 0
    for it in data.get("items") or []:
        if not isinstance(it, dict) or not str(it.get("name") or "").strip():
            continue
        amt = _dec(it.get("amount"))
        if amt is not None and abs(amt) not in printed:
            dropped += 1
            continue
        qty = it.get("qty")
        items.append({"name": str(it["name"]).strip()[:120], "qty": qty if isinstance(qty, (int, float)) else None,
                      "amount": str(amt) if amt is not None else None})
    when = None
    try:
        when = date.fromisoformat(str(data.get("date") or "")[:10])
    except ValueError:
        pass
    category = str(data.get("category") or "").strip()
    if category not in categories:
        category = ""

    checks = []
    if total is not None:
        checks.append("total is printed" if total_printed else "total is NOT printed in the document")
    summed = sum((Decimal(i["amount"]) for i in items if i["amount"]), Decimal(0))
    items_match = bool(items) and total is not None and abs(summed - abs(total)) <= Decimal("0.05")
    if items and total is not None:
        checks.append(f"items add up to the total ({summed})" if items_match
                      else f"items add up to {summed}, total {abs(total)}")
    if dropped:
        checks.append(f"{dropped} item(s) dropped: amount not printed")
    if merchant:
        checks.append("merchant is printed" if merchant_printed else "merchant name not found in the text")

    return {"model": model_name, "doc_type": data.get("doc_type"), "merchant": merchant or None,
            "merchant_printed": merchant_printed, "date": when.isoformat() if when else None,
            "currency": str(data.get("currency") or "").upper()[:3] or None,
            "total": str(total) if total is not None else None, "total_printed": total_printed,
            "vat": str(vat) if vat is not None else None, "payment": data.get("payment"),
            "items": items, "items_match": items_match, "category": category or None,
            "summary": str(data.get("summary") or "").strip()[:240] or None, "check": "; ".join(checks)}
