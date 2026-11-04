"""Treemap aggregation with drill-down to evidence.

Each node carries its deterministic total and the ids of the facts inside it,
so every rectangle on screen can be opened down to the original document.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from ..domain.events import Expense
from ..domain.money import Money, MoneyError


@dataclass
class Node:
    name: str
    total: Money
    children: dict[str, "Node"] = field(default_factory=dict)
    expense_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total": str(self.total.amount),
            "currency": self.total.currency,
            "expense_ids": self.expense_ids,
            "children": [c.to_dict() for c in sorted(
                self.children.values(), key=lambda n: n.total.amount, reverse=True)],
        }


def build(expenses: Iterable[Expense], currency: str = "CHF") -> Node:
    root = Node("All", Money(Decimal(0), currency))
    for expense in expenses:
        if expense.amount.currency != currency:
            raise MoneyError(
                f"Expense {expense.id} is in {expense.amount.currency}; convert with a "
                f"recorded rate before aggregating in {currency}."
            )
        node = root
        node.total = node.total + expense.amount
        for part in expense.category or ("Uncategorised",):
            node = node.children.setdefault(part, Node(part, Money(Decimal(0), currency)))
            node.total = node.total + expense.amount
        node.expense_ids.append(expense.id)
    return root
