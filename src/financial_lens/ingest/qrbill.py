"""Swiss QR-bill payload (SPC, version 0200) parsing.

The payload is the decoded text of the QR code. Parsing is deterministic and
validates the QR reference check digit (modulo 10, recursive).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from ..domain.money import Money

_MOD10 = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]


class QRBillError(ValueError):
    pass


def qr_reference_valid(reference: str) -> bool:
    digits = reference.replace(" ", "")
    if len(digits) != 27 or not digits.isdigit():
        return False
    carry = 0
    for ch in digits[:-1]:
        carry = _MOD10[(carry + int(ch)) % 10]
    return (10 - carry) % 10 == int(digits[-1])


@dataclass(frozen=True, slots=True)
class QRBill:
    iban: str
    creditor: str
    amount: Optional[Money]
    currency: str
    reference_type: str  # QRR, SCOR or NON
    reference: Optional[str]
    message: Optional[str]


def parse(payload: str) -> QRBill:
    lines = payload.replace("\r\n", "\n").split("\n")
    if len(lines) < 31 or lines[0] != "SPC" or lines[1] != "0200":
        raise QRBillError("Not a Swiss QR-bill payload (SPC 0200).")
    iban = lines[3].replace(" ", "")
    creditor = lines[5]
    amount_text, currency = lines[18].strip(), lines[19].strip()
    if currency not in {"CHF", "EUR"}:
        raise QRBillError(f"QR-bill currency must be CHF or EUR, got {currency!r}.")
    amount = Money(Decimal(amount_text), currency) if amount_text else None
    ref_type, reference = lines[27].strip(), lines[28].strip() or None
    if ref_type == "QRR" and not (reference and qr_reference_valid(reference)):
        raise QRBillError("QR reference check digit is invalid.")
    message = lines[29].strip() or None
    return QRBill(iban, creditor, amount, currency, ref_type, reference, message)
