"""Phase 3: multi-profile, cooperatives, permissions, projects, budgets, reports and export."""

import json
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from financial_lens import orgs, reports
from financial_lens.service import AccessDenied
from test_phase2 import camt


def coop(lens):
    lens.open_organization("Wohnbaugenossenschaft Sonnenhalde", "cooperative")
    a = orgs.add_object(lens, "Haus A")
    b = orgs.add_object(lens, "Haus B")
    m1 = orgs.add_member(lens, "101", "Anna Keller", date(2020, 1, 1), a, "5000")
    m2 = orgs.add_member(lens, "102", "Marco Rossi", date(2021, 6, 1), b, "5000")
    fund = orgs.add_fund(lens, "Erneuerungsfonds", "Renovation reserve")
    for m in (m1, m2):
        orgs.set_dues(lens, m, "2026-09", "150.00", date(2026, 9, 30), fund_id=fund)
        orgs.set_dues(lens, m, "2026-10", "150.00", date(2026, 10, 31), fund_id=fund)
    return a, b, m1, m2, fund


def test_multiple_organisations_are_separate(lens):
    lens.add_manual("expense", "10.00", "CHF", date(2026, 9, 1), "Kiosk", ("Food",))
    personal = lens.org
    coop(lens)
    assert lens.treemap(date(2026, 9, 1), date(2026, 9, 30))["total"] == "0"
    lens.open_organization("Test household")
    assert lens.org == personal and lens.treemap(date(2026, 9, 1), date(2026, 9, 30))["total"] == "10.00"
    assert {o["kind"] for o in lens.organizations()} == {"personal", "cooperative"}


def test_member_contributions_arrears_and_fund(lens):
    a, b, m1, m2, fund = coop(lens)
    lens.ingest(camt(("150.00", "CRDT", "2026-09-28", "Anna Keller", {"text": "Beitrag Nr. 101 September"}),
                     ("150.00", "CRDT", "2026-10-29", "A. Keller", {"text": "Mitglied 101 Oktober"}),
                     ("150.00", "CRDT", "2026-09-29", "Marco Rossi", {"text": "September"})), "coop.xml")
    found = orgs.match_contributions(lens)
    assert len(found) == 3
    s1 = orgs.member_statement(lens, m1, until=date(2026, 11, 15))
    assert s1["paid"] == "300.00" and s1["arrears"] == "0.00"
    s2 = orgs.member_statement(lens, m2, until=date(2026, 11, 15))
    # identified by name only → needs review → not yet counted as paid
    assert s2["paid"] == "0.00" and s2["unconfirmed_payments"] == "150.00" and s2["arrears"] == "300.00"
    pay = s2["payments"][0]["operation_id"]
    lens.correct(pay, {"confirm": True, "fund_id": fund}, "treasurer confirmed")
    assert orgs.member_statement(lens, m2, until=date(2026, 11, 15))["arrears"] == "150.00"
    assert [r["member_no"] for r in orgs.arrears(lens, date(2026, 11, 15))] == ["102"]
    for p in s1["payments"]:
        lens.correct(p["operation_id"], {"fund_id": fund}, "earmarked")
    roof = lens.add_manual("invoice", "120.00", "CHF", date(2026, 10, 5), "Dachdecker Huber", ("Housing", "Repairs"))
    lens.correct(roof, {"fund_id": fund}, "charged to renovation fund")
    assert orgs.fund_balance(lens, fund) == {"inflow": "450.00", "outflow": "120.00", "balance": "330.00"}


def test_cost_allocation_by_area(lens):
    a, b, *_ = coop(lens)
    op = lens.add_manual("invoice", "1000.00", "CHF", date(2026, 10, 1), "Gebäudeversicherung", ("Insurance",))
    parts = orgs.allocate(lens, op, {a: 2, b: 1}, "area m²")
    assert [p["amount"] for p in parts] == ["666.67", "333.33"]
    assert sum(Decimal(p["amount"]) for p in parts) == Decimal("1000.00")
    assert orgs.costs_by_object(lens, date(2026, 10, 1), date(2026, 10, 31)) == [
        {"object": "Haus A", "total": "666.67", "records": 1}, {"object": "Haus B", "total": "333.33", "records": 1}]


def test_roles_and_member_only_access(lens):
    a, b, m1, m2, fund = coop(lens)
    viewer = lens.add_user("Board observer", "viewer")
    anna = lens.add_user("Anna Keller", "member")
    lens.db.execute("UPDATE members SET user_id=%s WHERE id=%s", (anna, m1))
    lens.as_user(viewer)
    assert lens.treemap(date(2026, 1, 1), date(2026, 12, 31))
    with pytest.raises(AccessDenied):
        lens.add_manual("expense", "1.00", "CHF", date(2026, 10, 1), "x")
    lens.as_user(anna)
    assert orgs.member_statement(lens, m1)["member"]["name"] == "Anna Keller"
    with pytest.raises(AccessDenied):
        orgs.member_statement(lens, m2)
    with pytest.raises(AccessDenied):
        lens.treemap(date(2026, 1, 1), date(2026, 12, 31))
    lens.as_user(None)
    denied = lens.db.execute("SELECT count(*) AS n FROM audit_log WHERE action='access_denied'").fetchone()["n"]
    assert denied == 3


def test_business_projects_budgets_and_treemap_toggles(lens):
    lens.open_organization("Keller Design GmbH", "business")
    p = orgs.add_project(lens, "Client Alpha")
    op1 = lens.add_manual("invoice", "800.00", "CHF", date(2026, 10, 2), "Druckerei Zürich", ("Leisure",))
    lens.correct(op1, {"category": ("Business", "Printing"), "project_id": p, "scope": "business",
                       "expense_class": "opex"}, "client job")
    op2 = lens.add_manual("invoice", "2400.00", "CHF", date(2026, 10, 9), "Digitec", ("Business", "Equipment"))
    lens.correct(op2, {"scope": "business", "expense_class": "capex"}, "laptop")
    orgs.set_budget(lens, date(2026, 10, 1), date(2026, 10, 31), "1000.00", ("Business",))
    orgs.set_budget(lens, date(2026, 10, 1), date(2026, 12, 31), "500.00", project_id=p)
    bva = orgs.budget_vs_actual(lens)
    assert bva[0]["actual"] == "3200.00" and bva[0]["over"] is True
    assert bva[1]["actual"] == "800.00" and bva[1]["remaining"] == "-300.00"
    oct_ = (date(2026, 10, 1), date(2026, 10, 31))
    by_project = lens.treemap(*oct_, group="project")
    assert {c["name"]: c["total"] for c in by_project["children"]} == {"Client Alpha": "800.00", "(no project)": "2400.00"}
    by_cp = lens.treemap(*oct_, group="counterparty")
    assert {c["name"] for c in by_cp["children"]} == {"Druckerei Zürich", "Digitec"}
    detail = lens.operation_detail(op2)
    assert detail["expense_class"] == "capex" and detail["scope"] == "business"


def test_reports_and_full_export(lens, tmp_path):
    from test_mvp_cycle import CAMT
    lens.ingest(CAMT, "camt.xml")
    lens.add_manual("receipt", "45.00", "CHF", date(2026, 10, 9), "Café Lang", ("Food", "Restaurants"))
    rows = reports.report(lens, date(2026, 1, 1), date(2026, 12, 31), "category", "month")
    assert {r["category"]: r["total"] for r in rows} == {"Housing / Electricity": "184.50", "Food / Groceries": "67.80",
                                                         "Food / Restaurants": "45.00"}
    q = reports.report(lens, date(2026, 1, 1), date(2026, 12, 31), "counterparty", "quarter")
    assert q[0]["period"] == "2026-Q4"
    assert reports.to_csv(rows).startswith("﻿period,category".encode("utf-8-sig")[:3])
    assert reports.to_xlsx(rows)[:2] == b"PK"
    pdf = reports.to_pdf("Expenses 2026", rows, ["period", "category", "total", "count"])
    assert pdf.startswith(b"%PDF-1.4") and b"Food / Groceries" in pdf
    assert json.loads(reports.to_json(rows))[0]["operations"]
    manifest = reports.export_archive(lens, tmp_path / "export.zip")
    with zipfile.ZipFile(tmp_path / "export.zip") as z:
        names = z.namelist()
        assert "manifest.json" in names and "data/operation_revisions.json" in names
        orig = [n for n in names if n.startswith("originals/")]
        assert orig and z.read(orig[0]) == CAMT
        for name, digest in manifest["files"].items():
            import hashlib
            assert hashlib.sha256(z.read(name)).hexdigest() == digest
