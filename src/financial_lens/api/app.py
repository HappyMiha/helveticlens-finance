"""Local HTTP API over the Financial Lens service.

Run: FL_DSN="host=localhost dbname=fl user=fl" FL_DATA=~/FinancialLens \
     uvicorn financial_lens.api.app:app --host 127.0.0.1
It binds to loopback by default and makes no outbound requests in local-only mode.
"""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..service import FinancialLens

app = FastAPI(title="Financial Lens", version="0.2.0")


@lru_cache(maxsize=1)
def _lens() -> FinancialLens:
    lens = FinancialLens(os.environ.get("FL_DSN", "dbname=financial_lens"),
                         os.path.expanduser(os.environ.get("FL_DATA", "~/FinancialLens")),
                         actor=os.environ.get("FL_ACTOR", "user:local"))
    lens.migrate()
    lens.open_organization(os.environ.get("FL_ORG", "Personal"), os.environ.get("FL_ORG_KIND", "personal"))
    return lens


def lens() -> FinancialLens:
    return _lens()


def _period(start: Optional[date], end: Optional[date]) -> tuple[date, date]:
    today = date.today()
    start = start or today.replace(day=1)
    end = end or today
    if end < start:
        raise HTTPException(422, "The end date is before the start date.")
    return start, end


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/documents")
async def upload(files: list[UploadFile], privacy: str = "local_only", fl: FinancialLens = Depends(lens)) -> list[dict]:
    if privacy not in ("local_only", "swiss_hosted", "cloud_ai"):
        raise HTTPException(422, "Unknown privacy level.")
    out = []
    for f in files:
        res = fl.ingest(await f.read(), f.filename or "upload", f.content_type
                        if f.content_type not in (None, "application/octet-stream") else None, privacy)
        out.append(res.__dict__)
    return out


@app.get("/documents")
def documents(fl: FinancialLens = Depends(lens)) -> list[dict]:
    return fl.documents()


@app.get("/documents/{document_id}/original")
def original(document_id: str, fl: FinancialLens = Depends(lens)) -> Response:
    try:
        data, media, name = fl.original(document_id)
    except TypeError:
        raise HTTPException(404, "Document not found.")
    return Response(data, media_type=media, headers={"Content-Disposition": f'inline; filename="{name}"'})


@app.get("/dashboard")
def dashboard(start: Optional[date] = None, end: Optional[date] = None, fl: FinancialLens = Depends(lens)) -> dict:
    return fl.dashboard(*_period(start, end))


@app.get("/treemap")
def treemap(start: Optional[date] = None, end: Optional[date] = None, mode: str = "expenses",
            fl: FinancialLens = Depends(lens)) -> dict:
    if mode not in ("expenses", "income"):
        raise HTTPException(422, "mode is expenses or income")
    return fl.treemap(*_period(start, end), mode)


@app.get("/operations")
def operations(start: Optional[date] = None, end: Optional[date] = None, category: str = "",
               fl: FinancialLens = Depends(lens)) -> list[dict]:
    path = tuple(p for p in category.split("/") if p)
    return fl.operations(*_period(start, end), path)


@app.get("/operations/{op_id}")
def operation(op_id: str, fl: FinancialLens = Depends(lens)) -> dict:
    try:
        return fl.operation_detail(op_id)
    except TypeError:
        raise HTTPException(404, "Operation not found.")


class Manual(BaseModel):
    kind: str = "expense"
    amount: str
    currency: str = "CHF"
    op_date: date
    counterparty: str
    category: Optional[list[str]] = None
    description: str = ""


@app.post("/operations")
def add_operation(body: Manual, fl: FinancialLens = Depends(lens)) -> dict:
    op = fl.add_manual(body.kind, body.amount, body.currency, body.op_date, body.counterparty,
                       tuple(body.category) if body.category else None, body.description)
    return {"id": op}


class Correction(BaseModel):
    changes: dict
    reason: str


@app.post("/operations/{op_id}/corrections")
def correct(op_id: str, body: Correction, fl: FinancialLens = Depends(lens)) -> dict:
    allowed = {"amount", "currency", "op_date", "due_date", "counterparty", "description", "category", "confirm"}
    if set(body.changes) - allowed:
        raise HTTPException(422, f"Only {sorted(allowed)} can be corrected.")
    return {"revision_id": fl.correct(op_id, body.changes, body.reason)}


class Decision(BaseModel):
    accept: bool


@app.post("/links/{link_id}/decision")
def decide(link_id: str, body: Decision, fl: FinancialLens = Depends(lens)) -> dict:
    fl.decide_link(link_id, body.accept)
    return {"status": "confirmed" if body.accept else "rejected"}


@app.get("/categories")
def categories(fl: FinancialLens = Depends(lens)) -> list[dict]:
    return fl.categories()


class Rule(BaseModel):
    field: str = "counterparty"
    pattern: str
    category: list[str]


@app.post("/rules")
def add_rule(body: Rule, fl: FinancialLens = Depends(lens)) -> dict:
    fl.add_rule(body.field, body.pattern, tuple(body.category))
    return {"status": "ok"}


@app.get("/ai-activity")
def ai_activity(fl: FinancialLens = Depends(lens)) -> list[dict]:
    return fl.ai_activity()


# ---------------------------------------------------------------- Phase 2
from .. import analytics as _an  # noqa: E402
from .. import assistant as _as  # noqa: E402


@app.get("/analytics/cash-flow")
def cash_flow(start: Optional[date] = None, end: Optional[date] = None, fl: FinancialLens = Depends(lens)) -> list[dict]:
    return _an.cash_flow(fl, *_period(start, end))


@app.get("/analytics/compare")
def compare(a_start: date, a_end: date, b_start: date, b_end: date, depth: int = 1,
            fl: FinancialLens = Depends(lens)) -> list[dict]:
    return _an.compare(fl, (a_start, a_end), (b_start, b_end), depth)


@app.get("/analytics/counterparties")
def counterparties(start: Optional[date] = None, end: Optional[date] = None, fl: FinancialLens = Depends(lens)) -> list[dict]:
    return _an.by_counterparty(fl, *_period(start, end))


@app.get("/analytics/top")
def top(start: Optional[date] = None, end: Optional[date] = None, fl: FinancialLens = Depends(lens)) -> list[dict]:
    return _an.top_expenses(fl, *_period(start, end))


@app.get("/recurring")
def recurring(fl: FinancialLens = Depends(lens)) -> dict:
    return {"detected": _an.save_recurring(fl), "missing": _an.missing_recurring(fl)}


@app.get("/unpaid")
def unpaid_invoices(fl: FinancialLens = Depends(lens)) -> list[dict]:
    return _an.unpaid(fl)


class Question(BaseModel):
    question: str


@app.post("/ask")
def ask(body: Question, fl: FinancialLens = Depends(lens)) -> dict:
    return _as.ask(fl, body.question)


class Rate(BaseModel):
    currency: str
    rate_date: date
    rate_to_chf: str
    source: str


@app.post("/fx-rates")
def fx_rate(body: Rate, fl: FinancialLens = Depends(lens)) -> dict:
    fl.set_fx_rate(body.currency.upper(), body.rate_date, body.rate_to_chf, body.source)
    return {"status": "ok"}
