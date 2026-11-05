"""Phase 3: businesses and cooperatives (§2).

Members and their contributions, arrears, objects (properties, units) and
cost allocation, earmarked funds, projects and budgets (actual vs plan).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from .domain.money import Money
from .service import BASE, FinancialLens, _similar


def _id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- register
def add_object(lens: FinancialLens, name: str, kind: str = "property", parent: Optional[str] = None) -> str:
    lens.authorize("configure")
    oid = _id()
    with lens.db.transaction():
        lens.db.execute("INSERT INTO objects (id, organization_id, name, kind, parent_id) VALUES (%s,%s,%s,%s,%s)",
                        (oid, lens.org, name, kind, parent))
        lens._audit("create", "object", oid, {"name": name, "kind": kind})
    return oid


def add_member(lens: FinancialLens, member_no: str, name: str, joined_on: date, object_id: Optional[str] = None,
               share_capital: str = "0", user_id: Optional[str] = None) -> str:
    lens.authorize("admin")
    mid = _id()
    with lens.db.transaction():
        lens.db.execute("INSERT INTO members (id, organization_id, member_no, name, object_id, share_capital, joined_on, "
                        "user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (mid, lens.org, member_no, name, object_id, Decimal(share_capital), joined_on, user_id))
        lens._audit("create", "member", mid, {"member_no": member_no, "name": name})
    return mid


def add_fund(lens: FinancialLens, name: str, purpose: str = "", earmarked: bool = True) -> str:
    lens.authorize("configure")
    fid = _id()
    with lens.db.transaction():
        lens.db.execute("INSERT INTO funds (id, organization_id, name, purpose, earmarked) VALUES (%s,%s,%s,%s,%s)",
                        (fid, lens.org, name, purpose, earmarked))
        lens._audit("create", "fund", fid, {"name": name})
    return fid


def add_project(lens: FinancialLens, name: str) -> str:
    lens.authorize("configure")
    pid = _id()
    with lens.db.transaction():
        lens.db.execute("INSERT INTO projects (id, organization_id, name) VALUES (%s,%s,%s)", (pid, lens.org, name))
        lens._audit("create", "project", pid, {"name": name})
    return pid


def set_dues(lens: FinancialLens, member_id: str, period: str, amount: str, due_date: date,
             purpose: str = "contribution", fund_id: Optional[str] = None) -> str:
    lens.authorize("configure")
    did = _id()
    with lens.db.transaction():
        lens.db.execute("INSERT INTO member_dues (id, organization_id, member_id, period, amount, due_date, purpose, fund_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (member_id, period, purpose) DO NOTHING",
                        (did, lens.org, member_id, period, Decimal(amount), due_date, purpose, fund_id))
        lens._audit("dues", "member", member_id, {"period": period, "amount": amount, "purpose": purpose})
    return did


# ------------------------------------------------------------ contributions
def match_contributions(lens: FinancialLens) -> list[dict]:
    """Incoming payments from members become contributions linked to the member.
    Identified by member number in the remittance, or by name (proposed only)."""
    lens.authorize("write")
    members = lens.db.execute("SELECT * FROM members WHERE organization_id=%s", (lens.org,)).fetchall()
    incoming = lens.db.execute(
        "SELECT * FROM operations_current c WHERE organization_id=%s AND kind='payment' AND amount > 0 AND member_id IS NULL",
        (lens.org,)).fetchall()
    out = []
    with lens.db.transaction():
        for p in incoming:
            text = f"{p['counterparty']} {p['description']}".casefold()
            by_no = [m for m in members if m["member_no"].casefold() in text.split() or
                     f"nr. {m['member_no']}".casefold() in text or f"#{m['member_no']}".casefold() in text]
            by_name = [m for m in members if _similar(m["name"], p["counterparty"]) >= 0.8]
            m, how = (by_no[0], "member number in the payment text") if len(by_no) == 1 else \
                (by_name[0], "payer name") if len(by_name) == 1 else (None, "")
            if m is None:
                continue
            verified = how.startswith("member number")
            lens._revision(str(p["operation_id"]), {
                "member_id": m["id"], "category_id": lens.category_id(("Member contributions",), "income"),
                "agent": "engine:members", "verification": "confirmed" if verified else "needs_review",
                "verification_reason": f"Contribution from member {m['member_no']} identified by {how}"
                                       + ("" if verified else "; please confirm")}, "identified member contribution")
            out.append({"payment": str(p["operation_id"]), "member": str(m["id"]), "by": how})
    return out


def member_statement(lens: FinancialLens, member_id: str, until: Optional[date] = None) -> dict:
    """Dues, payments and arrears for one member (a member may read only their own)."""
    until = until or date.today()
    m = lens.db.execute("SELECT * FROM members WHERE id=%s AND organization_id=%s", (member_id, lens.org)).fetchone()
    if lens.role() == "member":
        if str(m["user_id"]) != str(lens.user_id):
            lens.authorize("read")  # raises
    else:
        lens.authorize("read")
    dues = lens.db.execute("SELECT * FROM member_dues WHERE member_id=%s ORDER BY due_date", (member_id,)).fetchall()
    paid_rows = lens.db.execute(
        "SELECT operation_id, op_date, amount, currency, description, verification FROM operations_current "
        "WHERE organization_id=%s AND member_id=%s AND kind='payment' AND amount > 0 ORDER BY op_date",
        (lens.org, member_id)).fetchall()
    paid = sum((r["amount"] for r in paid_rows if r["currency"] == BASE and r["verification"] == "confirmed"), Decimal(0))
    pending = sum((r["amount"] for r in paid_rows if r["verification"] != "confirmed"), Decimal(0))
    # Allocate confirmed payments to dues oldest first (deterministic).
    rest, lines = paid, []
    for d in dues:
        covered = min(rest, d["amount"])
        rest -= covered
        lines.append({"period": d["period"], "purpose": d["purpose"], "due_date": d["due_date"].isoformat(),
                      "amount": str(d["amount"].quantize(Decimal("0.01"))), "covered": str(covered.quantize(Decimal("0.01"))),
                      "open": str((d["amount"] - covered).quantize(Decimal("0.01"))),
                      "overdue": d["due_date"] < until and covered < d["amount"]})
    arrears = sum((Decimal(l["open"]) for l in lines if l["overdue"]), Decimal(0))
    return {"member": lens._json(m), "dues": lines, "payments": [lens._json(r) for r in paid_rows],
            "paid": str(paid.quantize(Decimal("0.01"))), "unconfirmed_payments": str(pending.quantize(Decimal("0.01"))),
            "credit": str(rest.quantize(Decimal("0.01"))), "arrears": str(arrears.quantize(Decimal("0.01")))}


def arrears(lens: FinancialLens, until: Optional[date] = None) -> list[dict]:
    lens.authorize("read")
    rows = []
    for m in lens.db.execute("SELECT id, member_no, name FROM members WHERE organization_id=%s ORDER BY member_no",
                             (lens.org,)).fetchall():
        st = member_statement(lens, str(m["id"]), until)
        if Decimal(st["arrears"]) > 0:
            rows.append({"member_id": str(m["id"]), "member_no": m["member_no"], "name": m["name"], "arrears": st["arrears"]})
    return rows


# ------------------------------------------------------------- allocation
def allocate(lens: FinancialLens, op: str, weights: dict[str, int], basis: str) -> list[dict]:
    """Split one expense across objects by integer weights (e.g. m²), without losing a cent."""
    lens.authorize("write")
    row = lens.db.execute("SELECT amount, currency FROM operations_current WHERE operation_id=%s", (op,)).fetchone()
    parts = Money(abs(row["amount"]).quantize(Decimal("0.01")), row["currency"]).allocate(list(weights.values()))
    out = []
    with lens.db.transaction():
        lens.db.execute("DELETE FROM allocations WHERE operation_id=%s", (op,))
        for (object_id, w), part in zip(weights.items(), parts):
            lens.db.execute("INSERT INTO allocations (id, organization_id, operation_id, object_id, amount, basis, created_by) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s)", (_id(), lens.org, op, object_id, part.amount, basis, lens.actor))
            out.append({"object_id": object_id, "weight": w, "amount": str(part.amount)})
        lens._audit("allocate", "operation", op, {"basis": basis, "parts": out})
    return out


def costs_by_object(lens: FinancialLens, start: date, end: date) -> list[dict]:
    lens.authorize("read")
    rows = lens.db.execute(
        "SELECT o.name, sum(a.amount) AS total, count(*) AS n FROM allocations a JOIN objects o ON o.id=a.object_id "
        "JOIN operations_current c ON c.operation_id=a.operation_id WHERE a.organization_id=%s AND c.op_date BETWEEN %s AND %s "
        "GROUP BY o.name ORDER BY o.name", (lens.org, start, end)).fetchall()
    direct = lens.db.execute(
        "SELECT o.name, sum(abs(c.amount)) AS total, count(*) AS n FROM operations_current c JOIN objects o ON o.id=c.object_id "
        "WHERE c.organization_id=%s AND c.op_date BETWEEN %s AND %s AND c.kind IN ('invoice','receipt','expense') "
        "AND NOT EXISTS (SELECT 1 FROM allocations a WHERE a.operation_id=c.operation_id) GROUP BY o.name",
        (lens.org, start, end)).fetchall()
    totals: dict[str, list] = {}
    for r in list(rows) + list(direct):
        t = totals.setdefault(r["name"], [Decimal(0), 0])
        t[0] += r["total"]
        t[1] += r["n"]
    return [{"object": k, "total": str(v[0].quantize(Decimal("0.01"))), "records": v[1]} for k, v in sorted(totals.items())]


# ------------------------------------------------------------------ funds
def fund_balance(lens: FinancialLens, fund_id: str, until: Optional[date] = None) -> dict:
    """Earmarked money in (contributions to the fund) minus spending charged to it."""
    lens.authorize("read")
    until = until or date(2999, 12, 31)
    r = lens.db.execute(
        "SELECT coalesce(sum(amount) FILTER (WHERE amount > 0 AND kind IN ('payment','income','contribution')),0) AS inflow, "
        "coalesce(sum(abs(amount)) FILTER (WHERE kind IN ('invoice','receipt','expense') OR (kind='payment' AND amount<0 "
        "AND NOT EXISTS (SELECT 1 FROM links l WHERE l.to_operation_id=operations_current.operation_id AND l.status<>'rejected'))),0) AS outflow "
        "FROM operations_current WHERE organization_id=%s AND fund_id=%s AND op_date <= %s", (lens.org, fund_id, until)).fetchone()
    q = Decimal("0.01")
    return {"inflow": str(r["inflow"].quantize(q)), "outflow": str(r["outflow"].quantize(q)),
            "balance": str((r["inflow"] - r["outflow"]).quantize(q))}


# ---------------------------------------------------------------- budgets
def set_budget(lens: FinancialLens, start: date, end: date, amount: str, category: Optional[tuple[str, ...]] = None,
               project_id: Optional[str] = None) -> str:
    lens.authorize("configure")
    bid = _id()
    with lens.db.transaction():
        lens.db.execute("INSERT INTO budgets (id, organization_id, category_id, project_id, period_start, period_end, amount, "
                        "created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (bid, lens.org, lens.category_id(category) if category else None, project_id, start, end,
                         Decimal(amount), lens.actor))
        lens._audit("budget", "budget", bid, {"category": list(category or ()), "project": project_id, "amount": amount})
    return bid


def budget_vs_actual(lens: FinancialLens) -> list[dict]:
    lens.authorize("read")
    paths = {c["id"]: c["path"] for c in lens.categories()}
    out = []
    for b in lens.db.execute("SELECT b.*, p.name AS project FROM budgets b LEFT JOIN projects p ON p.id=b.project_id "
                             "WHERE b.organization_id=%s ORDER BY period_start", (lens.org,)).fetchall():
        prefix = paths.get(str(b["category_id"])) if b["category_id"] else None
        actual = Decimal(0)
        for r in lens._spend_rows(b["period_start"], b["period_end"]):
            if prefix and paths.get(str(r["category_id"]), ())[:len(prefix)] != prefix:
                continue
            if b["project_id"] and str(r["project_id"]) != str(b["project_id"]):
                continue
            actual += lens._in_base(r) or Decimal(0)
        plan = b["amount"].quantize(Decimal("0.01"))
        out.append({"category": list(prefix) if prefix else None, "project": b["project"],
                    "start": b["period_start"].isoformat(), "end": b["period_end"].isoformat(),
                    "budget": str(plan), "actual": str(actual), "remaining": str(plan - actual),
                    "used_pct": str((actual / plan * 100).quantize(Decimal("0.1"))) if plan else None,
                    "over": actual > plan})
    return out
