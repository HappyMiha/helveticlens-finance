"""Reports and export (§14). Every exported row keeps its trail back to the
evidence: operation id, document ids and SHA-256 of the originals."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .service import FinancialLens

GROUPS = ("category", "counterparty", "project", "account", "member", "object")
PERIODS = ("month", "quarter", "year", "all")


def _period_key(d: date, period: str) -> str:
    if period == "month":
        return f"{d.year}-{d.month:02d}"
    if period == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if period == "year":
        return str(d.year)
    return "all"


def report(lens: FinancialLens, start: date, end: date, group_by: str = "category", period: str = "month",
           mode: str = "expenses") -> list[dict]:
    lens.authorize("read")
    if group_by not in GROUPS or period not in PERIODS:
        raise ValueError("Unknown grouping or period")
    paths = {c["id"]: " / ".join(c["path"]) for c in lens.categories()}
    names = {}
    for table, col in (("projects", "name"), ("accounts", "name"), ("members", "name"), ("objects", "name")):
        for r in lens.db.execute(f"SELECT id, {col} FROM {table} WHERE organization_id=%s", (lens.org,)).fetchall():
            names[str(r["id"])] = r[col]
    rows = lens._spend_rows(start, end) if mode == "expenses" else lens._income_rows(start, end)
    agg: dict[tuple, dict] = defaultdict(lambda: {"total": Decimal(0), "count": 0, "operations": [], "documents": set()})
    for r in rows:
        v = lens._in_base(r)
        if v is None:
            continue
        key_value = {
            "category": paths.get(str(r["category_id"]), "Unclassified"),
            "counterparty": r["counterparty"] or "(unknown)",
            "project": names.get(str(r["project_id"]), "(no project)"),
            "account": names.get(str(r["account_id"]), "(no account)"),
            "member": names.get(str(r["member_id"]), "(no member)"),
            "object": names.get(str(r["object_id"]), "(no object)"),
        }[group_by]
        a = agg[(_period_key(r["op_date"], period), key_value)]
        a["total"] += v
        a["count"] += 1
        a["operations"].append(str(r["operation_id"]))
        if r["source_document_id"]:
            a["documents"].add(str(r["source_document_id"]))
    return [{"period": p, group_by: g, "total": str(a["total"]), "count": a["count"],
             "operations": a["operations"], "documents": sorted(a["documents"])}
            for (p, g), a in sorted(agg.items(), key=lambda kv: (kv[0][0], -kv[1]["total"]))]


# ----------------------------------------------------------------- formats
def to_csv(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]), extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ";".join(v) if isinstance(v, (list, tuple)) else v for k, v in r.items()})
    return buf.getvalue().encode("utf-8-sig")


def to_xlsx(rows: list[dict], title: str = "Report") -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    if rows:
        ws.append(list(rows[0]))
        for r in rows:
            ws.append([";".join(v) if isinstance(v, (list, tuple)) else
                       (float(v) if k == "total" else v) for k, v in r.items()])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_json(rows: list[dict]) -> bytes:
    return json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode()


def to_pdf(title: str, rows: list[dict], columns: Iterable[str]) -> bytes:
    """A plain, dependency-free PDF table (Helvetica, A4)."""
    columns = list(columns)
    lines = [title, f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by Financial Lens", ""]
    widths = [max(len(c), *(len(str(r.get(c, ""))) for r in rows)) if rows else len(c) for c in columns]
    widths = [min(w, 40) for w in widths]
    lines.append("  ".join(c.upper().ljust(w) for c, w in zip(columns, widths)))
    for r in rows:
        lines.append("  ".join(str(r.get(c, ""))[:w].ljust(w) for c, w in zip(columns, widths)))
    pages = [lines[i:i + 60] for i in range(0, len(lines), 60)] or [[]]

    def esc(t: str) -> str:
        t = t.encode("latin-1", "replace").decode("latin-1")
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"]
    kids = []
    for page in pages:
        stream = "BT /F1 8 Tf 36 806 Td 11 TL " + " ".join(f"({esc(l)}) '" for l in page) + " ET"
        objs.append(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


# ----------------------------------------------------------------- archive
def _rows(lens: FinancialLens, sql: str) -> list[dict]:
    return [lens._json(r) for r in lens.db.execute(sql, (lens.org,)).fetchall()]


def export_archive(lens: FinancialLens, target: Path) -> dict:
    """Full export (§17.12): originals, processed data, operations with every revision,
    links, metadata and history, with a SHA-256 manifest."""
    lens.authorize("export")
    tables = {
        "operations_current": "SELECT * FROM operations_current WHERE organization_id=%s ORDER BY op_date",
        "operation_revisions": "SELECT r.* FROM operation_revisions r JOIN operations o ON o.id=r.operation_id "
                               "WHERE o.organization_id=%s ORDER BY r.operation_id, r.revision",
        "documents": "SELECT * FROM documents WHERE organization_id=%s ORDER BY received_at",
        "extractions": "SELECT e.* FROM extractions e JOIN documents d ON d.id=e.document_id WHERE d.organization_id=%s",
        "document_operations": "SELECT x.* FROM document_operations x JOIN documents d ON d.id=x.document_id WHERE d.organization_id=%s",
        "links": "SELECT * FROM links WHERE organization_id=%s",
        "categories": "SELECT * FROM categories WHERE organization_id=%s",
        "classification_rules": "SELECT * FROM classification_rules WHERE organization_id=%s",
        "tags": "SELECT t.name, ot.operation_id FROM operation_tags ot JOIN tags t ON t.id=ot.tag_id WHERE t.organization_id=%s",
        "members": "SELECT * FROM members WHERE organization_id=%s",
        "member_dues": "SELECT * FROM member_dues WHERE organization_id=%s",
        "funds": "SELECT * FROM funds WHERE organization_id=%s",
        "projects": "SELECT * FROM projects WHERE organization_id=%s",
        "budgets": "SELECT * FROM budgets WHERE organization_id=%s",
        "objects": "SELECT * FROM objects WHERE organization_id=%s",
        "allocations": "SELECT * FROM allocations WHERE organization_id=%s",
        "accounts": "SELECT * FROM accounts WHERE organization_id=%s",
        "audit_log": "SELECT * FROM audit_log WHERE organization_id=%s ORDER BY id",
        "ai_activity": "SELECT * FROM ai_activity WHERE organization_id=%s ORDER BY id",
    }
    manifest = {"format": "financial-lens-archive/1", "created_at": datetime.now(timezone.utc).isoformat(),
                "organization_id": lens.org, "files": {}}
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name: str, data: bytes) -> None:
            z.writestr(name, data)
            manifest["files"][name] = hashlib.sha256(data).hexdigest()

        for name, sql in tables.items():
            rows = _rows(lens, sql)
            put(f"data/{name}.json", to_json(rows))
            put(f"data/{name}.csv", to_csv(rows))
        for d in _rows(lens, "SELECT id, sha256, filename, folder FROM documents WHERE organization_id=%s"):
            data = lens.files.get(d["sha256"])  # verifies integrity
            put(f"originals/{d['folder'] or 'UNFILED'}/{d['id'][:8]}-{Path(d['filename']).name}", data)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    with lens.db.transaction():
        lens._audit("export_archive", "organization", lens.org, {"files": len(manifest["files"]), "path": str(target)})
    return manifest
