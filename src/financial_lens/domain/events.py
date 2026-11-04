"""Append-only financial facts with provenance.

A received document, a recognised expense and a booked payment are separate
events. None of them overwrites another: corrections are new revisions that
point at what they replace, so the history of every fact stays inspectable.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from .money import Money


class Method(str, Enum):
    MANUAL = "manual"
    OCR = "ocr"
    STRUCTURED_IMPORT = "structured_import"  # CAMT, QR-bill, CSV with a schema
    AI_EXTRACTION = "ai_extraction"
    RULE = "rule"


class PrivacyLevel(str, Enum):
    CLOUD_AI = "cloud_ai"  # an external AI provider may see the document
    SWISS_HOSTED = "swiss_hosted"  # only providers hosted in Switzerland
    LOCAL_ONLY = "local_only"  # local OCR/LLM, no network


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a fact came from and how it was obtained."""

    document_id: Optional[str]
    location: str  # e.g. "page 1, line 14" or "camt.053 Ntry[3]"
    method: Method
    agent: str  # "user:miha", "paddleocr-2.8", "rule:qr-reference"
    confidence: Optional[float] = None  # None for structured or manual input
    quote: Optional[str] = None  # exact text the value was read from
    recorded_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """An original file kept unchanged as evidence."""

    filename: str
    media_type: str
    sha256: str
    privacy: PrivacyLevel
    id: str = field(default_factory=_id)
    received_at: datetime = field(default_factory=_now)

    @classmethod
    def from_bytes(cls, filename: str, media_type: str, data: bytes,
                   privacy: PrivacyLevel = PrivacyLevel.LOCAL_ONLY) -> "SourceDocument":
        return cls(filename, media_type, hashlib.sha256(data).hexdigest(), privacy)


@dataclass(frozen=True, slots=True)
class Expense:
    """A recognised obligation or spend, e.g. from a receipt or invoice."""

    amount: Money
    issued_on: date
    counterparty: str
    category: tuple[str, ...]  # path for the treemap, e.g. ("Home", "Energy")
    provenance: Provenance
    reference: Optional[str] = None  # QR / SCOR reference when present
    due_on: Optional[date] = None
    id: str = field(default_factory=_id)
    revises: Optional[str] = None  # id of the revision this one replaces


@dataclass(frozen=True, slots=True)
class Payment:
    """Money that actually moved, as booked by a bank."""

    amount: Money  # negative = outgoing
    booked_on: date
    counterparty: str
    provenance: Provenance
    reference: Optional[str] = None
    bank_reference: Optional[str] = None
    remittance: Optional[str] = None
    id: str = field(default_factory=_id)
    revises: Optional[str] = None


class Ledger:
    """In-memory append-only store; PostgreSQL implements the same contract."""

    def __init__(self) -> None:
        self._documents: dict[str, SourceDocument] = {}
        self._expenses: list[Expense] = []
        self._payments: list[Payment] = []

    def add_document(self, doc: SourceDocument) -> SourceDocument:
        self._documents.setdefault(doc.id, doc)
        return doc

    def document(self, doc_id: str) -> SourceDocument:
        return self._documents[doc_id]

    def record_expense(self, expense: Expense) -> Expense:
        self._expenses.append(expense)
        return expense

    def record_payment(self, payment: Payment) -> Payment:
        if payment.bank_reference and any(
            p.bank_reference == payment.bank_reference for p in self.current_payments()
        ):
            return next(p for p in self._payments if p.bank_reference == payment.bank_reference)
        self._payments.append(payment)
        return payment

    @staticmethod
    def _current(items):
        replaced = {i.revises for i in items if i.revises}
        return [i for i in items if i.id not in replaced]

    def current_expenses(self) -> list[Expense]:
        return self._current(self._expenses)

    def current_payments(self) -> list[Payment]:
        return self._current(self._payments)

    def history(self, fact_id: str) -> list:
        """All revisions leading to fact_id, oldest first."""
        by_id = {i.id: i for i in [*self._expenses, *self._payments]}
        chain = []
        node = by_id.get(fact_id)
        while node is not None:
            chain.append(node)
            node = by_id.get(node.revises) if node.revises else None
        return list(reversed(chain))
