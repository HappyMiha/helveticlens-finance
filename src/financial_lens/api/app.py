"""Local FastAPI service used by the desktop app.

Binds to 127.0.0.1 by default. In local-only privacy mode nothing here makes
an outbound request.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, UploadFile

from ..domain.events import Ledger, SourceDocument
from ..ingest import camt053
from ..matching.reconcile import reconcile
from ..views import treemap

app = FastAPI(title="Financial Lens", version="0.1.0")
ledger = Ledger()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/imports/bank-statement")
async def import_statement(file: UploadFile) -> dict:
    data = await file.read()
    doc = ledger.add_document(SourceDocument.from_bytes(
        file.filename or "statement.xml", file.content_type or "application/xml", data))
    try:
        payments = camt053.parse(data, doc.id)
    except Exception as exc:  # malformed XML is a user-facing error, not a crash
        raise HTTPException(422, f"Could not read the statement: {exc}") from exc
    for payment in payments:
        ledger.record_payment(payment)
    return {"document_id": doc.id, "sha256": doc.sha256, "payments": len(payments)}


@app.get("/reconciliation")
def reconciliation() -> dict:
    matches, ambiguous = reconcile(ledger.current_expenses(), ledger.current_payments())
    return {
        "matches": [{"expense_id": m.expense_id, "payment_id": m.payment_id,
                     "rule": m.rule, "reasons": list(m.reasons)} for m in matches],
        "ambiguous": [{"expense_id": a.expense_id,
                       "candidates": list(a.candidate_payment_ids),
                       "reason": a.reason} for a in ambiguous],
    }


@app.get("/treemap")
def treemap_view(currency: str = "CHF") -> dict:
    return treemap.build(ledger.current_expenses(), currency).to_dict()
