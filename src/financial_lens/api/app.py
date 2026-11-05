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
    if lens.privacy_level() == "local_only":  # L2: no outbound connections from this process
        from .. import privacy

        host = lens.db.info.host
        privacy.enforce_local_only([host] if host and not host.startswith("/") else [])
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
    allowed = {"amount", "currency", "op_date", "due_date", "counterparty", "description", "category", "confirm",
               "project_id", "object_id", "member_id", "fund_id", "scope", "expense_class", "reference"}
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


# ---------------------------------------------------------------- Phase 3
from fastapi.responses import FileResponse  # noqa: E402

from .. import orgs as _orgs  # noqa: E402
from .. import reports as _rep  # noqa: E402


@app.get("/organizations")
def organizations(fl: FinancialLens = Depends(lens)) -> list[dict]:
    return fl.organizations()


class Org(BaseModel):
    name: str
    kind: str = "personal"


@app.post("/organizations/open")
def open_org(body: Org, fl: FinancialLens = Depends(lens)) -> dict:
    return {"id": fl.open_organization(body.name, body.kind)}


class Member(BaseModel):
    member_no: str
    name: str
    joined_on: date
    object_id: Optional[str] = None
    share_capital: str = "0"


@app.post("/members")
def add_member(body: Member, fl: FinancialLens = Depends(lens)) -> dict:
    return {"id": _orgs.add_member(fl, body.member_no, body.name, body.joined_on, body.object_id, body.share_capital)}


class Dues(BaseModel):
    period: str
    amount: str
    due_date: date
    purpose: str = "contribution"
    fund_id: Optional[str] = None


@app.post("/members/{member_id}/dues")
def dues(member_id: str, body: Dues, fl: FinancialLens = Depends(lens)) -> dict:
    return {"id": _orgs.set_dues(fl, member_id, body.period, body.amount, body.due_date, body.purpose, body.fund_id)}


@app.get("/members/{member_id}/statement")
def member_statement(member_id: str, fl: FinancialLens = Depends(lens)) -> dict:
    return _orgs.member_statement(fl, member_id)


@app.post("/members/match-contributions")
def match(fl: FinancialLens = Depends(lens)) -> list[dict]:
    return _orgs.match_contributions(fl)


@app.get("/arrears")
def arrears(fl: FinancialLens = Depends(lens)) -> list[dict]:
    return _orgs.arrears(fl)


@app.get("/budgets")
def budgets(fl: FinancialLens = Depends(lens)) -> list[dict]:
    return _orgs.budget_vs_actual(fl)


@app.get("/reports")
def report(start: date, end: date, group_by: str = "category", period: str = "month", mode: str = "expenses",
           format: str = "json", fl: FinancialLens = Depends(lens)) -> Response:
    rows = _rep.report(fl, start, end, group_by, period, mode)
    if format == "csv":
        return Response(_rep.to_csv(rows), media_type="text/csv")
    if format == "xlsx":
        return Response(_rep.to_xlsx(rows), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if format == "pdf":
        return Response(_rep.to_pdf(f"{mode.title()} by {group_by}, {start} – {end}", rows,
                                    ["period", group_by, "total", "count"]), media_type="application/pdf")
    return Response(_rep.to_json(rows), media_type="application/json")


@app.post("/export")
def export(fl: FinancialLens = Depends(lens)) -> FileResponse:
    import tempfile
    from pathlib import Path

    target = Path(tempfile.mkdtemp()) / f"financial-lens-export-{date.today()}.zip"
    _rep.export_archive(fl, target)
    return FileResponse(target, filename=target.name, media_type="application/zip")


@app.get("/security/check")
def security_check(fl: FinancialLens = Depends(lens)) -> dict:
    from .. import security

    return security.self_check(fl)
