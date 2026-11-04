"""Deterministic money arithmetic.

Totals in Financial Lens are always computed here, never by a language model.
Amounts are Decimal values in minor-unit precision; floats are rejected so a
rounding error can never enter a ledger silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Iterable

# ISO 4217 minor units for the currencies the MVP handles.
MINOR_UNITS = {"CHF": 2, "EUR": 2, "USD": 2, "GBP": 2, "JPY": 0}


class MoneyError(ValueError):
    """Raised for invalid amounts or mixed-currency arithmetic."""


def _quantum(currency: str) -> Decimal:
    try:
        places = MINOR_UNITS[currency]
    except KeyError as exc:
        raise MoneyError(f"Unsupported currency: {currency}") from exc
    return Decimal(1).scaleb(-places)


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.amount, float):
            raise MoneyError("Floats are not accepted for money; pass str or Decimal.")
        try:
            value = Decimal(self.amount)
        except (InvalidOperation, TypeError) as exc:
            raise MoneyError(f"Invalid amount: {self.amount!r}") from exc
        if not value.is_finite():
            raise MoneyError("Amount must be finite.")
        quantum = _quantum(self.currency)
        if value != value.quantize(quantum):
            raise MoneyError(
                f"{self.amount} has more precision than {self.currency} allows."
            )
        object.__setattr__(self, "amount", value.quantize(quantum))

    @classmethod
    def parse(cls, text: str, currency: str) -> "Money":
        """Parse an extracted amount such as "1'234.50" or "1 234,50"."""
        cleaned = text.strip().replace("'", "").replace("’", "").replace(" ", "")
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", "")
        return cls(Decimal(cleaned), currency)

    def _same(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise MoneyError(f"Cannot combine {self.currency} and {other.currency}.")

    def __add__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def abs(self) -> "Money":
        return Money(abs(self.amount), self.currency)

    def allocate(self, weights: Iterable[int]) -> list["Money"]:
        """Split without losing a cent; remainders go to the first parts."""
        weights = list(weights)
        if not weights or any(w < 0 for w in weights) or sum(weights) == 0:
            raise MoneyError("Weights must be non-negative with a positive sum.")
        quantum = _quantum(self.currency)
        units = int(self.amount / quantum)
        total = sum(weights)
        shares = [units * w // total for w in weights]
        for i in range(units - sum(shares)):
            shares[i % len(shares)] += 1
        return [Money(Decimal(s) * quantum, self.currency) for s in shares]

    def __str__(self) -> str:
        return f"{self.currency} {self.amount:,.{MINOR_UNITS[self.currency]}f}".replace(",", "’")


def total(items: Iterable[Money], currency: str) -> Money:
    result = Money(Decimal(0), currency)
    for item in items:
        result = result + item
    return result


def round_amount(value: Decimal, currency: str) -> Decimal:
    return value.quantize(_quantum(currency), rounding=ROUND_HALF_EVEN)
