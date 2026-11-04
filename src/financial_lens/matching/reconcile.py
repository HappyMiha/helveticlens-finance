"""Match recognised expenses to booked payments.

Rules are deterministic and every match states why it was made. A match is a
proposal with evidence; ambiguous cases are left for the person to decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Iterable

from ..domain.events import Expense, Payment


@dataclass(frozen=True, slots=True)
class Match:
    expense_id: str
    payment_id: str
    rule: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Ambiguity:
    expense_id: str
    candidate_payment_ids: tuple[str, ...]
    reason: str


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def reconcile(expenses: Iterable[Expense], payments: Iterable[Payment],
              window_days: int = 45) -> tuple[list[Match], list[Ambiguity]]:
    open_payments = [p for p in payments if p.amount.amount < 0]
    used: set[str] = set()
    matches: list[Match] = []
    ambiguous: list[Ambiguity] = []

    expenses = list(expenses)
    # Pass 1: structured references (QR / SCOR) are exact evidence.
    for expense in expenses:
        if not expense.reference:
            continue
        for payment in open_payments:
            if payment.id in used or payment.reference != expense.reference:
                continue
            if payment.amount.abs() != expense.amount:
                continue
            used.add(payment.id)
            matches.append(Match(expense.id, payment.id, "reference", (
                f"Reference {expense.reference} appears on both records",
                f"Amount {expense.amount} matches",
            )))
            break

    matched = {m.expense_id for m in matches}
    # Pass 2: amount, currency and date window, with counterparty as a tie-break.
    for expense in expenses:
        if expense.id in matched:
            continue
        start = expense.issued_on
        end = (expense.due_on or expense.issued_on) + timedelta(days=window_days)
        candidates = [
            p for p in open_payments
            if p.id not in used and p.amount.abs() == expense.amount
            and start <= p.booked_on <= end
        ]
        if len(candidates) > 1:
            named = [p for p in candidates if _similar(p.counterparty, expense.counterparty) >= 0.6]
            candidates = named if len(named) == 1 else candidates
        if len(candidates) == 1:
            payment = candidates[0]
            used.add(payment.id)
            reasons = [
                f"Amount {expense.amount} matches",
                f"Booked {payment.booked_on.isoformat()} within {start.isoformat()}–{end.isoformat()}",
            ]
            if _similar(payment.counterparty, expense.counterparty) >= 0.6:
                reasons.append(f"Counterparty “{payment.counterparty}” resembles “{expense.counterparty}”")
            matches.append(Match(expense.id, payment.id, "amount_date", tuple(reasons)))
        elif len(candidates) > 1:
            ambiguous.append(Ambiguity(expense.id, tuple(p.id for p in candidates),
                                       "Several payments have the same amount in the date window"))
    return matches, ambiguous
