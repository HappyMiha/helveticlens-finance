"""Categorisation: user rules first, then learned rules, then built-in hints,
then (optionally) an AI suggestion restricted to existing categories.

The default tree follows §5 of the specification and is fully editable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DEFAULT_TREE: dict[str, tuple[str, list[str]]] = {
    "Housing": ("expense", ["Rent", "Electricity", "Water", "Heating", "Repairs", "Telecom", "Furniture", "Other"]),
    "Food": ("expense", ["Groceries", "Restaurants"]),
    "Transport": ("expense", ["Public transport", "Car", "Fuel", "Car repairs", "Parking"]),
    "Insurance": ("expense", ["Health insurance", "Household insurance", "Car insurance"]),
    "Healthcare": ("expense", ["Doctor", "Pharmacy", "Dentist"]),
    "Utilities": ("expense", ["Electricity", "Water", "Waste"]),
    "Leisure": ("expense", ["Sport", "Culture", "Travel"]),
    "Taxes": ("expense", ["Federal", "Cantonal", "Municipal"]),
    "Shopping": ("expense", ["Online", "Clothes", "Electronics", "Other"]),
    "Subscriptions": ("expense", ["Streaming", "Apps"]),
    "Cash": ("expense", ["Withdrawals"]),
    "Bills": ("expense", ["Collective payment orders"]),
    "Transfers": ("expense", ["To people"]),
    "Salary": ("income", []),
    "Other income": ("income", []),
    "Refunds": ("income", []),
    "Own transfers": ("transfer", []),
    "Unclassified": ("unclassified", []),
}

# Built-in hints: substring (case-insensitive) → category path.
HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("elektrizit", ("Housing", "Electricity")), ("ewz", ("Housing", "Electricity")),
    ("strom", ("Housing", "Electricity")), ("électricité", ("Housing", "Electricity")),
    ("romande energie", ("Housing", "Electricity")), ("bkw", ("Housing", "Electricity")),
    ("wasser", ("Housing", "Water")), ("miete", ("Housing", "Rent")), ("loyer", ("Housing", "Rent")),
    ("affitto", ("Housing", "Rent")), ("verwaltung", ("Housing", "Rent")), ("immobilien", ("Housing", "Rent")),
    ("swisscom", ("Housing", "Telecom")), ("sunrise", ("Housing", "Telecom")), ("salt mobile", ("Housing", "Telecom")),
    ("migros", ("Food", "Groceries")), ("coop", ("Food", "Groceries")), ("denner", ("Food", "Groceries")),
    ("aldi", ("Food", "Groceries")), ("lidl", ("Food", "Groceries")), ("volg", ("Food", "Groceries")),
    ("restaurant", ("Food", "Restaurants")), ("café", ("Food", "Restaurants")), ("cafe", ("Food", "Restaurants")),
    ("pizzeria", ("Food", "Restaurants")),
    ("sbb", ("Transport", "Public transport")), ("cff", ("Transport", "Public transport")),
    ("zvv", ("Transport", "Public transport")), ("postauto", ("Transport", "Public transport")),
    ("garage", ("Transport", "Car repairs")), ("autowerkstatt", ("Transport", "Car repairs")),
    ("tankstelle", ("Transport", "Fuel")), ("avia", ("Transport", "Fuel")), ("shell", ("Transport", "Fuel")),
    ("parking", ("Transport", "Parking")),
    ("krankenkasse", ("Insurance", "Health insurance")), ("css", ("Insurance", "Health insurance")),
    ("helsana", ("Insurance", "Health insurance")), ("swica", ("Insurance", "Health insurance")),
    ("sanitas", ("Insurance", "Health insurance")), ("visana", ("Insurance", "Health insurance")),
    ("concordia", ("Insurance", "Health insurance")), ("assura", ("Insurance", "Health insurance")),
    ("mobiliar", ("Insurance", "Household insurance")), ("axa", ("Insurance", "Household insurance")),
    ("apotheke", ("Healthcare", "Pharmacy")), ("pharmacie", ("Healthcare", "Pharmacy")),
    ("farmacia", ("Healthcare", "Pharmacy")), ("amavita", ("Healthcare", "Pharmacy")),
    ("zahnarzt", ("Healthcare", "Dentist")), ("arztpraxis", ("Healthcare", "Doctor")),
    ("steueramt", ("Taxes", "Cantonal")), ("steuerverwaltung", ("Taxes", "Cantonal")),
    ("lohn", ("Salary",)), ("salaire", ("Salary",)),
]


@dataclass(frozen=True)
class Suggestion:
    path: tuple[str, ...]
    confidence: float
    method: str  # user-rule, learned-rule, builtin-hint, ai, none
    reason: str


def classify(counterparty: str, description: str, user_rules: list[tuple[str, str, tuple[str, ...], str]],
             ai=None, categories: Optional[list[tuple[str, ...]]] = None) -> Suggestion:
    """user_rules: (field, pattern, path, origin) with origin 'user' or 'learned'."""
    text = {"counterparty": counterparty.casefold(), "description": description.casefold()}
    for origin in ("user", "learned"):
        for field, pattern, path, rule_origin in user_rules:
            if rule_origin == origin and pattern.casefold() in text.get(field, ""):
                conf = 0.97 if origin == "user" else 0.9
                return Suggestion(path, conf, f"{origin}-rule",
                                  f"{field} contains “{pattern}” ({'your rule' if origin == 'user' else 'learned from your correction'})")
    combined = text["counterparty"] + " " + text["description"]
    for needle, path in HINTS:
        if needle in combined:
            return Suggestion(path, 0.8, "builtin-hint", f"“{needle}” appears in the counterparty or description")
    if ai is not None and categories:
        suggestion = ai.classify(counterparty, description, categories)
        if suggestion is not None:
            return suggestion
    return Suggestion(("Unclassified",), 0.0, "none", "No rule or hint matched")
