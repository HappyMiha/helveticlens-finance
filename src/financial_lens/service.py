"""Financial Lens application service.

One place that turns inputs into evidence-backed operations on PostgreSQL.
The API and the desktop app both call this; neither does its own maths.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .classify.rules import DEFAULT_TREE, classify
from .domain.money import MINOR_UNITS
from .extract import fields as fx
from .extract import understand
from .extract import ocr
from .ingest import camt053, tabular
from .store.files import OriginalStore

BASE = "CHF"
SPEND_KINDS = ("invoice", "receipt", "expense")
INCOME_KINDS = ("income", "payslip", "contribution")


# Role → allowed actions (§2 cooperatives: per-role access). "member" sees only its own data.
PERMISSIONS = {
    "owner": {"read", "write", "decide", "configure", "admin", "export"},
    "admin": {"read", "write", "decide", "configure", "admin", "export"},
    "editor": {"read", "write", "decide", "export"},
    "viewer": {"read", "export"},
    "member": {"read_own"},
}


class AccessDenied(PermissionError):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _sniff(data: bytes, filename: str) -> str:
    head = data[:16]
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        return "image/heic"
    if head.lstrip().startswith(b"<?xml") or head.lstrip().startswith(b"<Document"):
        return "application/xml"
    if head.startswith(b"PK"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    guess = mimetypes.guess_type(filename)[0]
    return guess or "application/octet-stream"


def _similar(a: str, b: str) -> float:
    a, b = a.casefold(), b.casefold()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class IngestResult:
    document_id: str
    doc_type: str
    duplicate_of: Optional[str]
    operation_ids: list[str]
    links: list[dict]
    messages: list[str]


class FinancialLens:
    def __init__(self, dsn: str, data_dir: str | Path, actor: str = "user:local", ai=None) -> None:
        self.dsn = dsn
        self.files = OriginalStore(Path(data_dir) / "originals")
        self.actor = actor
        self.ai = ai
        self.db = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
        self.org: Optional[str] = None
        self.user_id: Optional[str] = None  # None = single-user local mode (owner)

    # ---------------------------------------------------------------- access
    def role(self) -> str:
        if self.user_id is None:
            return "owner"
        row = self.db.execute("SELECT role FROM memberships WHERE organization_id=%s AND user_id=%s",
                              (self.org, self.user_id)).fetchone()
        return row["role"] if row else "none"

    def authorize(self, action: str) -> None:
        if action not in PERMISSIONS.get(self.role(), set()):
            with self.db.transaction():
                self._audit("access_denied", "organization", self.org or "", {"action": action, "user": self.user_id})
            raise AccessDenied(f"Your role ({self.role()}) does not allow '{action}' in this organisation.")

    def add_user(self, name: str, role: str) -> str:
        self.authorize("admin")
        uid = _uuid()
        with self.db.transaction():
            self.db.execute("INSERT INTO users (id, name) VALUES (%s,%s)", (uid, name))
            self.db.execute("INSERT INTO memberships VALUES (%s,%s,%s)", (self.org, uid, role))
            self._audit("grant", "membership", uid, {"name": name, "role": role})
        return uid

    def as_user(self, user_id: Optional[str]) -> "FinancialLens":
        self.user_id = user_id
        self.actor = f"user:{user_id}" if user_id else "user:local"
        return self

    def organizations(self) -> list[dict]:
        return [self._json(r) for r in self.db.execute("SELECT * FROM organizations ORDER BY name").fetchall()]

    # ------------------------------------------------------------------ setup
    def migrate(self) -> None:
        sql = resources.files("financial_lens.store").joinpath("schema.sql").read_text()
        with self.db.transaction():
            self.db.execute(sql)

    def open_organization(self, name: str = "Personal", kind: str = "personal") -> str:
        row = self.db.execute("SELECT id FROM organizations WHERE name=%s", (name,)).fetchone()
        if row:
            self.org = str(row["id"])
            return self.org
        with self.db.transaction():
            self.org = _uuid()
            self.db.execute("INSERT INTO organizations (id, name, kind) VALUES (%s,%s,%s)", (self.org, name, kind))
            for top, (cat_kind, subs) in DEFAULT_TREE.items():
                parent = self._insert_category(top, None, cat_kind)
                for sub in subs:
                    self._insert_category(sub, parent, cat_kind)
            self._audit("create", "organization", self.org, {"name": name, "kind": kind})
        return self.org

    def _insert_category(self, name: str, parent: Optional[str], kind: str) -> str:
        cid = _uuid()
        self.db.execute("INSERT INTO categories (id, organization_id, parent_id, name, kind) VALUES (%s,%s,%s,%s,%s)",
                        (cid, self.org, parent, name, kind))
        return cid

    def _audit(self, action: str, entity: str, entity_id: str, details: dict, actor: Optional[str] = None) -> None:
        """Append to the audit log. Each row carries a hash over the previous row's hash
        and its own content, so any later edit or deletion breaks the chain."""
        details = json.loads(json.dumps(details, default=str))
        self.db.execute("SELECT pg_advisory_xact_lock(4242)")
        prev = self.db.execute("SELECT chain FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        body = json.dumps([prev["chain"] if prev else "", str(self.org), actor or self.actor, action, entity,
                           entity_id, details], sort_keys=True, ensure_ascii=False)
        chain = hashlib.sha256(body.encode()).hexdigest()
        self.db.execute("INSERT INTO audit_log (organization_id, actor, action, entity, entity_id, details, chain) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (self.org, actor or self.actor, action, entity, entity_id, Jsonb(details), chain))

    def verify_audit_chain(self) -> dict:
        prev, n = "", 0
        for r in self.db.execute("SELECT * FROM audit_log ORDER BY id").fetchall():
            body = json.dumps([prev, str(r["organization_id"]), r["actor"], r["action"], r["entity"], r["entity_id"],
                               r["details"]], sort_keys=True, ensure_ascii=False)
            if hashlib.sha256(body.encode()).hexdigest() != r["chain"]:
                return {"ok": False, "broken_at": r["id"], "checked": n}
            prev, n = r["chain"], n + 1
        return {"ok": True, "checked": n}

    # ------------------------------------------------------------- privacy
    def privacy_level(self) -> str:
        row = self.db.execute("SELECT value FROM settings WHERE organization_id=%s AND key='privacy_level'",
                              (self.org,)).fetchone()
        return row["value"] if row else "local_only"

    def set_privacy_level(self, level: str) -> None:
        from .privacy import resolve

        self.authorize("admin")
        level = resolve(level)
        with self.db.transaction():
            self.db.execute("INSERT INTO settings VALUES (%s,'privacy_level',%s) ON CONFLICT (organization_id, key) "
                            "DO UPDATE SET value=EXCLUDED.value, updated_at=now()", (self.org, Jsonb(level)))
            self._audit("privacy_level", "organization", self.org, {"level": level})
        if self.ai is not None:
            self.ai.level = level

    def ai_assist(self) -> bool:
        """Model assistance is a switch; off means rules and arithmetic only."""
        if self.ai is None:
            return False
        row = self.db.execute("SELECT value FROM settings WHERE organization_id=%s AND key='ai_assist'", (self.org,)).fetchone()
        return bool(row["value"]) if row else True

    def set_ai_assist(self, on: bool) -> None:
        self.authorize("configure")
        with self.db.transaction():
            self.db.execute("INSERT INTO settings VALUES (%s,'ai_assist',%s) ON CONFLICT (organization_id, key) "
                            "DO UPDATE SET value=EXCLUDED.value, updated_at=now()", (self.org, Jsonb(bool(on))))
            self._audit("ai_assist", "organization", self.org, {"on": bool(on)})

    def use_local_model(self, base_url: str = "http://127.0.0.1:18765/v1", model: str = "apertus-8b",
                        name: str = "Apertus 8B (local)") -> None:
        """Attach a model running on this machine (llama.cpp / Ollama, OpenAI-compatible API)."""
        from .ai.providers import OpenAICompatible, Orchestrator

        p = OpenAICompatible(name, base_url, model, "local", timeout=300)
        self.attach_ai(Orchestrator(routes={t: [p] for t in ("understand", "extract", "classify", "parse_question")}))

    def attach_ai(self, orchestrator) -> None:
        """Connect a model orchestrator: it logs into AI Activity and asks each document's privacy setting."""
        orchestrator.level = self.privacy_level()

        def log(task, provider, locality, summary, details):
            with self.db.transaction():
                self._ai_log(task, provider, locality, summary, details)

        def doc_privacy(document_id):
            row = self.db.execute("SELECT privacy FROM documents WHERE id=%s", (document_id,)).fetchone()
            return row["privacy"] if row else "local_only"

        orchestrator.log = log
        orchestrator.document_privacy = doc_privacy
        self.ai = orchestrator

    def _ai_fill(self, ex, text, doc: str):
        """Ask a model for fields the rules could not find. Accepted only if the model quotes
        text that exists verbatim in the document and the value can be read from that quote."""
        if self.ai is None:
            return ex
        missing = [n for n in ("amount", "doc_date", "counterparty") if getattr(ex, n) is None]
        if not missing:
            return ex
        system = ("Extract fields from a financial document. Reply with JSON {field: {\"value\": str, \"quote\": str}} "
                  "for these fields only: " + ", ".join(missing) + ". The quote must be copied exactly from the text. "
                  "Omit a field you cannot find. Never guess.")
        answer = self.ai.run("extract", system, text.text[:6000], document_id=doc,
                             validate=lambda a: "{" in a)
        if not answer:
            return ex
        try:
            data = json.loads(answer[answer.find("{"): answer.rfind("}") + 1])
        except ValueError:
            return ex
        for name in missing:
            item = data.get(name) if isinstance(data, dict) else None
            if not isinstance(item, dict) or not item.get("quote") or item["quote"] not in text.text:
                continue
            line = next((l for l in text.lines if item["quote"] in l.text), None)
            value = item.get("value")
            if name == "amount":
                # The claimed value must literally be a number in the quoted text.
                try:
                    claimed = Decimal(str(value).replace("'", "").replace("’", "").replace(",", "."))
                except Exception:
                    continue
                numbers = {Decimal(n.replace("'", "").replace("’", "").replace(",", "."))
                           for n in re.findall(r"\d[\d'’]*(?:[.,]\d{1,2})?", item["quote"])}
                if claimed not in numbers or claimed <= 0:
                    continue
                value = claimed.quantize(Decimal("0.01"))
            elif name == "doc_date":
                dates = [d for d, _ in fx._dates(fx.Line(0, 1, item["quote"]))]
                if not dates:
                    continue
                value = dates[0]
            setattr(ex, name, fx.Field(value, line.number if line else None, item["quote"], 0.6, "ai"))
        return ex

    def _ai_log(self, task: str, provider: str, locality: str, summary: str, details: dict,
                document_id: Optional[str] = None, operation_id: Optional[str] = None) -> None:
        self.db.execute("INSERT INTO ai_activity (organization_id, task, provider, locality, document_id, operation_id, "
                        "summary, details) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (self.org, task, provider, locality, document_id, operation_id, summary,
                         Jsonb(json.loads(json.dumps(details, default=str)))))

    # ------------------------------------------------------------- categories
    def categories(self) -> list[dict]:
        rows = self.db.execute("SELECT id, parent_id, name, kind, archived FROM categories WHERE organization_id=%s",
                               (self.org,)).fetchall()
        by_id = {r["id"]: r for r in rows}

        def path(r):
            p = [r["name"]]
            while r["parent_id"]:
                r = by_id[r["parent_id"]]
                p.insert(0, r["name"])
            return tuple(p)

        return sorted(({"id": str(r["id"]), "path": path(r), "kind": r["kind"], "archived": r["archived"]}
                       for r in rows), key=lambda c: c["path"])

    def category_id(self, path: Iterable[str], kind: str = "expense") -> str:
        parent = None
        for name in path:
            row = self.db.execute(
                "SELECT id, kind FROM categories WHERE organization_id=%s AND parent_id IS NOT DISTINCT FROM %s "
                "AND lower(name)=lower(%s)", (self.org, parent, name)).fetchone()
            if row:
                parent, kind = str(row["id"]), row["kind"]
            else:
                parent = self._insert_category(name, parent, kind)
                self._audit("create", "category", parent, {"name": name})
        return parent

    def category_path(self, category_id: Optional[str]) -> tuple[str, ...]:
        if not category_id:
            return ("Unclassified",)
        for c in self.categories():
            if c["id"] == str(category_id):
                return c["path"]
        return ("Unclassified",)

    def rename_category(self, category_id: str, name: str) -> None:
        self.authorize("configure")
        with self.db.transaction():
            old = self.db.execute("SELECT name FROM categories WHERE id=%s", (category_id,)).fetchone()
            self.db.execute("UPDATE categories SET name=%s WHERE id=%s", (name, category_id))
            self._audit("rename", "category", category_id, {"from": old["name"], "to": name})

    def _rules(self) -> list[tuple[str, str, tuple[str, ...], str]]:
        rows = self.db.execute("SELECT field, pattern, category_id, origin FROM classification_rules "
                               "WHERE organization_id=%s AND category_id IS NOT NULL ORDER BY created_at DESC",
                               (self.org,)).fetchall()
        return [(r["field"], r["pattern"], self.category_path(r["category_id"]), r["origin"]) for r in rows]

    def add_rule(self, field: str, pattern: str, path: tuple[str, ...], origin: str = "user") -> None:
        self.authorize("configure")
        cid = self.category_id(path)
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO classification_rules (id, organization_id, field, pattern, category_id, origin) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (organization_id, field, pattern) "
                "DO UPDATE SET category_id=EXCLUDED.category_id, origin=EXCLUDED.origin",
                (_uuid(), self.org, field, pattern.casefold(), cid, origin))
            self._audit("rule", "classification_rule", pattern, {"field": field, "path": list(path), "origin": origin})

    # ------------------------------------------------------------ operations
    def _new_operation(self, kind: str, values: dict, change_reason: str = "created") -> str:
        op = _uuid()
        self.db.execute("INSERT INTO operations (id, organization_id, kind) VALUES (%s,%s,%s)", (op, self.org, kind))
        self._revision(op, values, change_reason, first=True)
        return op

    def _revision(self, op: str, values: dict, change_reason: str, first: bool = False) -> str:
        if first:
            number = 1
            current: dict[str, Any] = {}
        else:
            current = self.db.execute("SELECT * FROM operations_current WHERE id IS NOT NULL AND operation_id=%s",
                                      (op,)).fetchone()
            number = current["revision"] + 1
        merged = {k: current.get(k) for k in (
            "amount", "currency", "fx_rate", "fx_source", "op_date", "due_date", "counterparty", "description",
            "category_id", "project_id", "account_id", "reference", "bank_reference", "period", "verification",
            "verification_reason", "source_document_id", "method", "agent", "confidence", "provenance",
            "object_id", "member_id", "fund_id", "scope", "expense_class")}
        merged.update(values)
        merged.setdefault("agent", self.actor)
        if merged.get("period") is None and merged.get("op_date"):
            merged["period"] = merged["op_date"].strftime("%Y-%m")
        cur = merged["currency"]
        if cur != BASE and merged.get("fx_rate") is None and merged.get("op_date"):
            found = self.fx_rate(cur, merged["op_date"])
            if found:
                merged["fx_rate"], merged["fx_source"] = found
        if cur not in MINOR_UNITS:
            raise ValueError(f"Unsupported currency {cur}")
        amount = Decimal(merged["amount"])
        if amount != amount.quantize(Decimal(1).scaleb(-MINOR_UNITS[cur])):
            raise ValueError("Amount has more precision than the currency allows")
        rid = _uuid()
        self.db.execute(
            "INSERT INTO operation_revisions (id, operation_id, revision, amount, currency, fx_rate, fx_source, op_date, "
            "due_date, counterparty, description, category_id, project_id, account_id, reference, bank_reference, period, "
            "verification, verification_reason, source_document_id, method, agent, confidence, provenance, change_reason, "
            "object_id, member_id, fund_id, scope, expense_class) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (rid, op, number, amount, cur, merged.get("fx_rate"), merged.get("fx_source"), merged["op_date"],
             merged.get("due_date"), merged.get("counterparty") or "", merged.get("description") or "",
             merged.get("category_id"), merged.get("project_id"), merged.get("account_id"), merged.get("reference"),
             merged.get("bank_reference"), merged.get("period"), merged["verification"],
             merged.get("verification_reason") or "", merged.get("source_document_id"), merged["method"],
             merged["agent"], merged.get("confidence"), Jsonb(merged.get("provenance") or {}), change_reason,
             merged.get("object_id"), merged.get("member_id"), merged.get("fund_id"), merged.get("scope"),
             merged.get("expense_class")))
        self._audit("revise" if not first else "create", "operation", op,
                    {"revision": number, "reason": change_reason,
                     "changed": sorted(k for k in values if k != "provenance")}, actor=merged["agent"])
        return rid

    def add_manual(self, kind: str, amount: str, currency: str, op_date: date, counterparty: str,
                   category: Optional[tuple[str, ...]] = None, description: str = "") -> str:
        self.authorize("write")
        with self.db.transaction():
            sug = None
            if category is None:
                sug = classify(counterparty, description, self._rules())
                category = sug.path
            op = self._new_operation(kind, {
                "amount": Decimal(amount), "currency": currency, "op_date": op_date, "counterparty": counterparty,
                "description": description,
                "category_id": self.category_id(category, "income" if kind in INCOME_KINDS else "expense"),
                "verification": "unconfirmed", "verification_reason": "Entered manually without a document",
                "method": "manual", "agent": self.actor,
                "provenance": {"category": {"method": sug.method if sug else "manual",
                                            "reason": sug.reason if sug else "chosen by user"}}})
        self.reconcile()
        return op

    def correct(self, op: str, changes: dict, reason: str, actor: Optional[str] = None) -> str:
        self.authorize("write")
        """A person corrects or confirms a record. Creates a revision; never overwrites."""
        actor = actor or self.actor
        values = dict(changes)
        for k in ("op_date", "due_date"):
            if isinstance(values.get(k), str):
                values[k] = date.fromisoformat(values[k])
        if "amount" in values:
            values["amount"] = Decimal(str(values["amount"]))
        if "category" in values:
            path = tuple(values.pop("category"))
            values["category_id"] = self.category_id(path)
        values.setdefault("verification", "confirmed" if values.pop("confirm", False) else None)
        if values["verification"] is None:
            values.pop("verification")
        values.update({"agent": actor, "method": "manual"})
        current = self.db.execute("SELECT * FROM operations_current WHERE operation_id=%s", (op,)).fetchone()
        prov = dict(current["provenance"] or {})
        for k in changes:
            prov[k] = {"method": "manual", "agent": actor, "reason": reason}
        values["provenance"] = prov
        if values.get("verification") == "confirmed":
            values["verification_reason"] = f"Confirmed by {actor}"
        with self.db.transaction():
            rid = self._revision(op, values, reason)
            if "category_id" in values and current["counterparty"]:
                # Learn: next time this counterparty gets the same category (§4.4).
                self.db.execute(
                    "INSERT INTO classification_rules (id, organization_id, field, pattern, category_id, origin) "
                    "VALUES (%s,%s,'counterparty',%s,%s,'learned') ON CONFLICT (organization_id, field, pattern) "
                    "DO UPDATE SET category_id=EXCLUDED.category_id WHERE classification_rules.origin <> 'user'",
                    (_uuid(), self.org, current["counterparty"].casefold()[:60], values["category_id"]))
        return rid

    # --------------------------------------------------------------- ingest
    def ingest(self, data: bytes, filename: str, media_type: Optional[str] = None,
               privacy: str = "local_only") -> IngestResult:
        self.authorize("write")
        media_type = media_type or _sniff(data, filename)
        sha, key = self.files.put(data)
        existing = self.db.execute("SELECT id, doc_type FROM documents WHERE organization_id=%s AND sha256=%s",
                                   (self.org, sha)).fetchone()
        if existing:
            with self.db.transaction():
                self._audit("duplicate_upload", "document", str(existing["id"]), {"filename": filename})
            return IngestResult(str(existing["id"]), existing["doc_type"], str(existing["id"]), [], [],
                                ["This file was already imported; the existing record was kept."])
        doc = _uuid()
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO documents (id, organization_id, sha256, filename, media_type, size_bytes, storage_key, "
                "privacy, processing_status, received_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'processing',%s)",
                (doc, self.org, sha, filename, media_type, len(data), key, privacy, self.actor))
            self._audit("store_original", "document", doc, {"sha256": sha, "filename": filename, "bytes": len(data)})
        try:
            if media_type in ("application/xml", "text/xml") and b"camt.05" in data[:2000]:
                result = self._import_camt(doc, data)
            elif media_type in ("text/csv", "application/vnd.ms-excel") or filename.lower().endswith(".csv"):
                result = self._import_table(doc, tabular.rows_from_csv(data), "csv")
            elif media_type.endswith("spreadsheetml.sheet") or filename.lower().endswith(".xlsx"):
                result = self._import_table(doc, tabular.rows_from_xlsx(data), "xlsx")
            else:
                result = self._process_document(doc, data, media_type)
        except Exception as exc:
            with self.db.transaction():
                self.db.execute("UPDATE documents SET processing_status='failed' WHERE id=%s", (doc,))
                self._audit("processing_failed", "document", doc, {"error": str(exc)[:500]})
            return IngestResult(doc, "unknown", None, [], [], [f"Could not process the file: {exc}"])
        result.links = self.reconcile()
        return result

    def _folder(self, doc_type: str, op_date: Optional[date], path: tuple[str, ...], unpaid: bool) -> str:
        year = str(op_date.year) if op_date else "UNDATED"
        if doc_type == "bank_statement":
            return f"{year}/BANK_STATEMENTS"
        if path == ("Unclassified",) or doc_type == "unknown":
            return f"{year}/UNCLASSIFIED"
        if unpaid:
            return f"{year}/UNPAID_INVOICES"
        top = "INCOME" if path and path[0] in ("Salary", "Other income", "Refunds") else "EXPENSES"
        return f"{year}/{top}/" + "/".join(p.replace(" ", "_") for p in path)

    def _process_document(self, doc: str, data: bytes, media_type: str) -> IngestResult:
        text = ocr.recognise(data, media_type)
        an = understand.analyse(text, model=self.ai if self.ai_assist() else None, document_id=doc)
        if an.doc_type == "bank_statement" and an.rows:
            return self._import_statement_document(doc, text, an)
        if an.doc_type == "payslip":
            return self._record_payslip(doc, text, an)
        ex = self._ai_fill(fx.extract(text), text, doc)
        if an.doc_type in ("invoice", "receipt"):
            ex.doc_type = fx.Field(an.doc_type, None, "; ".join(an.type_evidence), max(an.type_score, 0.6), "evidence")
            total = an.facts.get("total")
            if total and ex.amount is not None and ex.amount.method == "qr-bill":
                pass  # structured QR data wins; a disagreement is reported below
            elif total and (ex.amount is None or Decimal(str(ex.amount.value)) != total["value"]):
                supported = an.checks and an.checks[0].ok
                ex.amount = fx.Field(total["value"], total["line"], total["quote"], 0.95 if supported else 0.6,
                                     "arithmetic" if supported else "label")
        messages = []
        with self.db.transaction():
            self.db.execute("INSERT INTO extractions (id, document_id, engine, text, fields) VALUES (%s,%s,%s,%s,%s)",
                            (_uuid(), doc, text.engine, text.text, Jsonb({**ex.to_json(), "analysis": an.to_json()})))
            self._ai_log("ocr", text.engine, "local", f"Recognised {len(text.lines)} lines"
                         + (f", mean confidence {text.mean_confidence:.0%}" if text.mean_confidence else ""),
                         {"qr_codes": len(text.qr_payloads)}, document_id=doc)
            self._ai_log("recognise", "rules", "local", f"Document type: {ex.doc_type.value}",
                         {"confidence": ex.doc_type.confidence, "quote": ex.doc_type.quote}, document_id=doc)
            self._ai_log("extract", "rules", "local", "Extracted " + ", ".join(ex.fields()),
                         ex.to_json(), document_id=doc)
            doc_type = str(ex.doc_type.value)
            op_ids: list[str] = []
            missing = [n for n in ("amount", "doc_date") if getattr(ex, n) is None]
            if doc_type in ("invoice", "receipt", "payslip", "unknown") and not missing:
                kind = {"invoice": "invoice", "receipt": "receipt", "payslip": "payslip"}.get(doc_type, "expense")
                cp = str(ex.counterparty.value) if ex.counterparty else ""
                desc = str(ex.description.value) if ex.description else ""
                sug = classify(cp, desc, self._rules(), ai=self.ai,
                               categories=[c["path"] for c in self.categories() if c["kind"] == "expense"])
                if sug.method == "ai":
                    self._ai_log("classify", "model", "local", f"Suggested {' / '.join(sug.path)}",
                                 {"confidence": sug.confidence, "reason": sug.reason}, document_id=doc)
                else:
                    self._ai_log("classify", sug.method, "local", f"Category {' / '.join(sug.path)}",
                                 {"confidence": sug.confidence, "reason": sug.reason}, document_id=doc)
                weakest = ex.weakest
                structured = ex.amount.method == "qr-bill"
                doubts = []
                # Money and date decide whether a record can be trusted; a slightly blurry name does not
                # (it is checked again against the bank payment).
                money_conf = min(f.confidence for f in (ex.amount, ex.doc_date))
                if an.consistent and ex.amount.method in ("arithmetic", "qr-bill"):
                    money_conf = max(money_conf, ex.doc_date.confidence)
                if not structured and money_conf < 0.75:
                    doubts.append(f"amount or date read with low confidence ({money_conf:.0%})")
                if ex.counterparty and ex.counterparty.confidence < 0.55:
                    doubts.append(f"counterparty unclear (“{ex.counterparty.value}”)")
                if ex.currency is None:
                    doubts.append("currency not printed; CHF assumed")
                if sug.path == ("Unclassified",):
                    doubts.append("no category found")
                if doc_type == "unknown":
                    doubts.append("document type not recognised")
                qr_agrees = structured and (an.facts.get("total") is None or
                                            an.facts["total"]["value"] == Decimal(str(ex.amount.value)))
                if structured and not qr_agrees:
                    doubts.append(f"QR-bill amount {ex.amount.value} differs from the printed total {an.facts['total']['value']}")
                if not structured:  # a decoded QR-bill is itself the arithmetic proof of the amount
                    doubts.extend(c.detail for c in an.checks if not c.ok)
                    doubts.extend(an.problems)
                ai_fields = [n for n, f in ex.fields().items() if f.method == "ai"]
                if ai_fields:
                    doubts.append("read by a model: " + ", ".join(ai_fields))
                if doubts:
                    verification, reason = "needs_review", "Recognised, but " + "; ".join(doubts)
                else:
                    verification, reason = "unconfirmed", ("Read from a structured QR-bill; awaiting bank payment"
                                                           if structured else "Read from the document; awaiting bank payment")
                prov = {name: {**f.to_json(), "document_id": doc} for name, f in ex.fields().items()}
                prov["category"] = {"method": sug.method, "reason": sug.reason, "confidence": sug.confidence}
                op_date = ex.doc_date.value
                op = self._new_operation(kind, {
                    "amount": Decimal(str(ex.amount.value)), "currency": str(ex.currency.value) if ex.currency else BASE,
                    "op_date": op_date, "due_date": ex.due_date.value if ex.due_date else None,
                    "counterparty": cp, "description": desc,
                    "category_id": self.category_id(sug.path, "income" if kind == "payslip" else "expense"),
                    "reference": str(ex.reference.value) if ex.reference else None,
                    "verification": verification, "verification_reason": reason, "source_document_id": doc,
                    "method": "structured_import" if structured else ("ai_extraction" if ai_fields else "ocr"),
                    "agent": f"pipeline:{text.engine}",
                    "confidence": Decimal(str(round(weakest if not structured else 1.0, 3))), "provenance": prov,
                }, change_reason="recognised from document")
                self.db.execute("INSERT INTO document_operations VALUES (%s,%s,'source')", (doc, op))
                self._find_duplicates(op)
                op_ids.append(op)
                folder = self._folder(doc_type, op_date, sug.path, unpaid=kind == "invoice")
                status = "needs_review" if verification == "needs_review" else "processed"
            else:
                folder = self._folder(doc_type, ex.doc_date.value if ex.doc_date else None, ("Unclassified",), False)
                status = "needs_review"
                messages.append("Not enough data to create a record: missing " + ", ".join(missing or ["type"])
                                + ". Nothing was guessed; the document waits in the inbox.")
            self.db.execute("UPDATE documents SET doc_type=%s, doc_type_confidence=%s, processing_status=%s, folder=%s "
                            "WHERE id=%s", (doc_type, ex.doc_type.confidence, status, folder, doc))
        return IngestResult(doc, doc_type, None, op_ids, [], messages)

    def _explain(self, an) -> str:
        bad = [c.detail for c in an.checks if not c.ok] + an.problems
        good = [c.name for c in an.checks if c.ok]
        return ("Checked: " + "; ".join(good) + ". " if good else "") + ("Doubts: " + "; ".join(bad) if bad else "")

    def _record_payslip(self, doc: str, text, an) -> IngestResult:
        """A payslip is income: the net (or payout) amount, with gross and every deduction kept as evidence."""
        f = an.facts
        amount = f.get("payout") or f.get("net")
        when = f.get("date")
        messages = []
        with self.db.transaction():
            self.db.execute("INSERT INTO extractions (id, document_id, engine, text, fields) VALUES (%s,%s,%s,%s,%s)",
                            (_uuid(), doc, text.engine, text.text, Jsonb({"analysis": an.to_json()})))
            self._ai_log("recognise", "analyst:payslip", "local", "Document type: payslip",
                         {"score": an.type_score, "evidence": an.type_evidence}, document_id=doc)
            self._ai_log("extract", "analyst:payslip", "local",
                         "Checks: " + ", ".join(f"{c.name} {'✓' if c.ok else '✗'}" for c in an.checks),
                         an.to_json(), document_id=doc)
            op_ids = []
            if amount is None or when is None:
                messages.append("Payslip recognised, but " + ("no net or payout amount" if amount is None else "no date") +
                                " was found. Nothing was guessed; it waits in the inbox. " + self._explain(an))
                status, folder = "needs_review", f"{when['value'].year if when else 'UNDATED'}/INCOME/Salary"
            else:
                ok = an.consistent
                reason = ("Payslip arithmetic checks out; awaiting the bank credit. " if ok else "") + self._explain(an)
                prov = {k: v for k, v in an.to_json()["facts"].items()}
                prov["checks"] = [c.to_json() for c in an.checks]
                op = self._new_operation("payslip", {
                    "amount": amount["value"], "currency": BASE, "op_date": when["value"],
                    "counterparty": (f.get("employer") or {}).get("value", ""),
                    "description": f"Salary {f['period']['value']}" if f.get("period") else "Salary",
                    "category_id": self.category_id(("Salary",), "income"),
                    "period": f["period"]["value"] if f.get("period") else None,
                    "verification": "unconfirmed" if ok else "needs_review", "verification_reason": reason[:900],
                    "source_document_id": doc, "method": "ocr" if "tesseract" in text.engine else "structured_import",
                    "agent": "analyst:payslip", "confidence": Decimal("0.95") if ok else Decimal("0.6"), "provenance": prov,
                }, change_reason="recognised payslip")
                self.db.execute("INSERT INTO document_operations VALUES (%s,%s,'source')", (doc, op))
                op_ids.append(op)
                status = "processed" if ok else "needs_review"
                folder = f"{when['value'].year}/INCOME/Salary"
                if not ok:
                    messages.append("Payslip read, but the numbers do not fully reconcile: " + self._explain(an))
            self.db.execute("UPDATE documents SET doc_type='payslip', doc_type_confidence=%s, processing_status=%s, folder=%s "
                            "WHERE id=%s", (an.type_score, status, folder, doc))
        return IngestResult(doc, "payslip", None, op_ids, [], messages)

    def _import_statement_document(self, doc: str, text, an) -> IngestResult:
        """A statement as PDF or photo: every booking line becomes a payment; the balance arithmetic decides
        whether the import can be trusted."""
        from .domain.events import Method, Payment, Provenance
        from .domain.money import Money

        with self.db.transaction():
            self._ai_log("recognise", "analyst:statement", "local", "Document type: bank statement",
                         {"score": an.type_score, "evidence": an.type_evidence}, document_id=doc)
            self._ai_log("extract", "analyst:statement", "local",
                         f"{len(an.rows)} booking lines; checks: " +
                         ", ".join(f"{c.name} {'✓' if c.ok else '✗'}" for c in an.checks), an.to_json(), document_id=doc)
        payments, skipped_rows = [], []
        seen: dict[str, int] = {}
        for r in an.rows:
            if r["amount"] is None or r["date"] is None:
                skipped_rows.append(r["quote"])
                continue
            words = re.sub(r"^\s*\d{1,2}[./]\d{1,2}[./]?(\d{2,4})?\s*", "", r["text"])
            words = re.sub(r"\b\d{1,2}[./]\d{1,2}[./](\d{2,4})?\b", " ", words)
            party = re.sub(r"^(zahlung an|gutschrift von|gutschrift|lastschrift|e-banking|einkauf|paiement à|"
                           r"versement de|virement de|achat|twint|ordine|pagamento a)\s*", "", " ".join(words.split()), flags=re.I)
            key = f"pdf:{r['date']}:{r['amount']}:{party[:30]}"
            seen[key] = seen.get(key, 0) + 1
            payments.append(Payment(
                amount=Money(r["amount"].quantize(Decimal("0.01")), BASE), booked_on=r["date"],
                counterparty=party[:120], remittance=" ".join(words.split())[:300] or None,
                bank_reference=f"{key}#{seen[key]}",
                provenance=Provenance(doc, f"line {r['line']}", Method.STRUCTURED_IMPORT, "analyst:statement",
                                      quote=r["quote"])))
        iban = (an.facts.get("iban") or {}).get("value")
        result = self._import_payments(doc, payments, iban, f"{text.engine}+statement-analyst")
        if not an.consistent:
            note = "The statement does not fully reconcile — please check. " + self._explain(an)
            with self.db.transaction():
                for op in result.operation_ids:
                    self._revision(op, {"verification": "needs_review", "verification_reason": note[:900],
                                        "agent": "analyst:statement"}, "statement checks failed")
                self.db.execute("UPDATE documents SET processing_status='needs_review' WHERE id=%s", (doc,))
            result.messages.append(note)
        else:
            result.messages.append("Statement reconciles: " + "; ".join(c.name for c in an.checks) + ".")
        if skipped_rows:
            result.messages.append(f"{len(skipped_rows)} lines without date or amount were not imported.")
        with self.db.transaction():
            self.db.execute("INSERT INTO extractions (id, document_id, engine, text, fields) VALUES (%s,%s,%s,%s,%s)",
                            (_uuid(), doc, text.engine, text.text, Jsonb({"analysis": an.to_json()})))
        return result

    def _account(self, iban: Optional[str], currency: str) -> Optional[str]:
        if not iban:
            return None
        row = self.db.execute("SELECT id FROM accounts WHERE organization_id=%s AND iban=%s", (self.org, iban)).fetchone()
        if row:
            return str(row["id"])
        aid = _uuid()
        self.db.execute("INSERT INTO accounts (id, organization_id, name, iban, currency) VALUES (%s,%s,%s,%s,%s)",
                        (aid, self.org, f"Account {iban[-4:]}", iban, currency))
        return aid

    def _import_table(self, doc: str, rows: list, engine: str) -> IngestResult:
        payments, problems = tabular.parse(rows, doc, BASE, engine)
        result = self._import_payments(doc, payments, None, engine)
        result.messages.extend(problems)
        return result

    def _import_camt(self, doc: str, data: bytes) -> IngestResult:
        return self._import_payments(doc, camt053.parse(data, doc), camt053.account_iban(data), "camt-parser")

    def _import_payments(self, doc: str, payments: list, iban: Optional[str], engine: str) -> IngestResult:
        op_ids, skipped = [], 0
        with self.db.transaction():
            account = self._account(iban, payments[0].amount.currency if payments else BASE)
            self.db.execute("INSERT INTO extractions (id, document_id, engine, fields) VALUES (%s,%s,%s,%s)",
                            (_uuid(), doc, engine, Jsonb({"entries": len(payments), "iban": iban})))
            for p in payments:
                if p.bank_reference and self.db.execute(
                        "SELECT 1 FROM operations_current WHERE organization_id=%s AND kind='payment' AND bank_reference=%s",
                        (self.org, p.bank_reference)).fetchone():
                    skipped += 1
                    continue
                own = self._is_own_transfer(p.counterparty, p.remittance or "")
                cat = ("Own transfers",) if own else None
                if cat is None and p.amount.amount < 0:
                    sug = classify(p.counterparty, p.remittance or "", self._rules())
                    cat = sug.path
                elif cat is None:
                    sug = classify(p.counterparty, p.remittance or "", self._rules())
                    cat = sug.path if sug.path[0] in ("Salary", "Other income", "Refunds") else ("Other income",)
                op = self._new_operation("transfer" if own else "payment", {
                    "amount": p.amount.amount, "currency": p.amount.currency, "op_date": p.booked_on,
                    "counterparty": p.counterparty, "description": p.remittance or "",
                    "category_id": self.category_id(cat, "transfer" if own else
                                                    ("expense" if p.amount.amount < 0 else "income")),
                    "account_id": account, "reference": p.reference, "bank_reference": p.bank_reference,
                    "verification": "unconfirmed",
                    "verification_reason": "Booked by the bank; no document linked yet",
                    "source_document_id": doc, "method": "structured_import", "agent": p.provenance.agent,
                    "provenance": {"entry": {"location": p.provenance.location, "document_id": doc}},
                }, change_reason="imported from bank statement")
                self.db.execute("INSERT INTO document_operations VALUES (%s,%s,'statement')", (doc, op))
                op_ids.append(op)
            self.db.execute("UPDATE documents SET doc_type='bank_statement', doc_type_confidence=1, "
                            "processing_status='processed', folder=%s WHERE id=%s",
                            (self._folder("bank_statement", payments[0].booked_on if payments else None, (), False), doc))
        msgs = [f"Imported {len(op_ids)} bank entries."]
        if skipped:
            msgs.append(f"Skipped {skipped} entries already imported from another statement.")
        return IngestResult(doc, "bank_statement", None, op_ids, [], msgs)

    def _is_own_transfer(self, counterparty: str, remittance: str) -> bool:
        text = (counterparty + " " + remittance).casefold()
        if any(w in text for w in ("übertrag", "eigenüberweisung", "virement interne", "own transfer", "giroconto")):
            return True
        own_ibans = {r["iban"] for r in self.db.execute(
            "SELECT iban FROM accounts WHERE organization_id=%s AND iban IS NOT NULL", (self.org,)).fetchall()}
        return any(iban in text.upper().replace(" ", "") for iban in own_ibans)

    # ---------------------------------------------------------- reconcile
    REFUND_WORDS = ("gutschrift", "rückerstattung", "rueckerstattung", "refund", "remboursement", "rimborso",
                    "storno", "retoure", "rückzahlung")

    def _open_items(self) -> tuple[list[dict], list[dict], list[dict]]:
        """Spend records with an open amount, outgoing and incoming payments with an unallocated amount."""
        cur = self.db.execute
        expenses = cur(
            "SELECT c.*, c.amount - coalesce((SELECT sum(l.amount) FROM links l WHERE l.from_operation_id=c.operation_id "
            "AND l.status <> 'rejected' AND l.link_type='payment'), 0) AS open_amount "
            "FROM operations_current c WHERE organization_id=%s AND kind = ANY(%s) AND NOT EXISTS ("
            "SELECT 1 FROM links d WHERE d.from_operation_id=c.operation_id AND d.link_type='duplicate' AND d.status='confirmed')",
            (self.org, list(SPEND_KINDS))).fetchall()
        payments = cur(
            "SELECT c.*, -c.amount - coalesce((SELECT sum(l.amount) FROM links l WHERE l.to_operation_id=c.operation_id "
            "AND l.status <> 'rejected' AND l.link_type='payment'), 0) AS remaining, "
            "(SELECT count(*) FROM links l WHERE l.to_operation_id=c.operation_id AND l.status <> 'rejected') AS n_links "
            "FROM operations_current c WHERE organization_id=%s AND kind='payment' AND amount < 0", (self.org,)).fetchall()
        incoming = cur(
            "SELECT c.* FROM operations_current c WHERE organization_id=%s AND kind='payment' AND amount > 0 "
            "AND NOT EXISTS (SELECT 1 FROM links l WHERE l.to_operation_id=c.operation_id AND l.status <> 'rejected')",
            (self.org,)).fetchall()
        return ([e for e in expenses if e["open_amount"] > 0], [p for p in payments if p["remaining"] > 0], incoming)

    def _link(self, e: dict, p: dict, link_type: str, amount: Decimal, rule: str, reasons: list[str],
              status: str) -> dict:
        lid = _uuid()
        eid, pid = str(e["operation_id"]), str(p["operation_id"])
        self.db.execute(
            "INSERT INTO links (id, organization_id, from_operation_id, to_operation_id, link_type, amount, currency, "
            "rule, reasons, status, created_by, decided_by, decided_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "'engine:reconcile',%s, CASE WHEN %s='confirmed' THEN now() END) "
            "ON CONFLICT (from_operation_id, to_operation_id, link_type) DO NOTHING",
            (lid, self.org, eid, pid, link_type, amount, e["currency"], rule, Jsonb(reasons), status,
             "engine:reconcile" if status == "confirmed" else None, status))
        self._ai_log("match", "engine:reconcile", "local",
                     f"{'Linked' if status == 'confirmed' else 'Proposed'} {link_type} for {e['counterparty'] or eid}",
                     {"rule": rule, "reasons": reasons, "amount": str(amount)}, operation_id=eid)
        self._audit("link_" + status, "link", lid, {"from": eid, "to": pid, "rule": rule, "type": link_type},
                    actor="engine:reconcile")
        return {"id": lid, "from": eid, "to": pid, "type": link_type, "rule": rule, "status": status,
                "amount": str(amount), "reasons": reasons}

    def reconcile(self, window_days: int = 45) -> list[dict]:
        """Link spend records to bank payments (§4.5). Many-to-many: split and partial
        payments, overpayments and refunds. Strong evidence is linked and confirmed
        with its reasons recorded; weaker evidence is only proposed."""
        expenses, payments, incoming = self._open_items()
        rejected = {(str(r["from_operation_id"]), str(r["to_operation_id"])) for r in self.db.execute(
            "SELECT from_operation_id, to_operation_id FROM links WHERE organization_id=%s AND status='rejected'",
            (self.org,)).fetchall()}
        remaining = {str(p["operation_id"]): p["remaining"] for p in payments}
        created: list[dict] = []
        touched: set[str] = set()
        with self.db.transaction():
            # Pass A: structured reference. Allocate payments to the open amount, in date order.
            for e in sorted((e for e in expenses if e["reference"]), key=lambda r: r["op_date"]):
                eid = str(e["operation_id"])
                open_amount = e["open_amount"]
                for p in sorted((p for p in payments if p["reference"] == e["reference"]
                                 and p["currency"] == e["currency"]), key=lambda r: r["op_date"]):
                    pid = str(p["operation_id"])
                    if open_amount <= 0 or remaining[pid] <= 0 or (eid, pid) in rejected:
                        continue
                    part = min(open_amount, remaining[pid])
                    reasons = [f"Reference {e['reference']} is on the document and on the bank payment"]
                    if part < e["open_amount"] or part < remaining[pid]:
                        reasons.append(f"Allocates {e['currency']} {part:.2f} of {e['currency']} {e['amount']:.2f}")
                    if remaining[pid] > open_amount:
                        reasons.append(f"Payment exceeds the open amount by {e['currency']} {remaining[pid] - open_amount:.2f}")
                    created.append(self._link(e, p, "payment", part, "qr_reference", reasons, "confirmed"))
                    open_amount -= part
                    remaining[pid] -= part
                    touched.add(eid)
                e["open_amount"] = open_amount

            # Pass B: exact amount within the date window, counterparty as evidence.
            used = {pid for pid, rest in remaining.items() if rest <= 0}
            for e in sorted((e for e in expenses if e["open_amount"] == e["amount"] and str(e["operation_id"]) not in touched),
                            key=lambda r: r["op_date"]):
                eid = str(e["operation_id"])
                start = e["op_date"] - timedelta(days=3)
                end = (e["due_date"] or e["op_date"]) + timedelta(days=window_days)
                cands = [p for p in payments if str(p["operation_id"]) not in used and p["n_links"] == 0
                         and (eid, str(p["operation_id"])) not in rejected and p["currency"] == e["currency"]
                         and remaining[str(p["operation_id"])] == e["amount"] and start <= p["op_date"] <= end]
                if not cands:
                    continue
                scored = sorted(((_similar(p["counterparty"], e["counterparty"]), p) for p in cands),
                                key=lambda t: (-t[0], abs((t[1]["op_date"] - e["op_date"]).days)))
                best, p = scored[0]
                second = scored[1][0] if len(scored) > 1 else -1
                reasons = [f"Amount {e['currency']} {e['amount']:.2f} matches exactly",
                           f"Booked {p['op_date']:%d.%m.%Y}, within {start:%d.%m.%Y}–{end:%d.%m.%Y}"]
                if best >= 0.6:
                    reasons.append(f"Counterparty “{p['counterparty']}” matches “{e['counterparty']}”")
                if best >= 0.6 and best > second:
                    rule, status = "amount_date_counterparty", "confirmed"
                elif len(cands) == 1:
                    rule, status = "amount_date", "proposed"
                    reasons.append("Counterparty names differ; please confirm")
                else:
                    rule, status = "amount_date_ambiguous", "proposed"
                    reasons.append(f"{len(cands)} payments fit; this is the closest in date")
                pid = str(p["operation_id"])
                used.add(pid)
                remaining[pid] = Decimal(0)
                e["open_amount"] = Decimal(0)
                created.append(self._link(e, p, "payment", e["amount"], rule, reasons, status))
                touched.add(eid)

            # Pass C: refunds — incoming money from a counterparty we paid, marked as a refund.
            spent = [e for e in self.db.execute(
                "SELECT * FROM operations_current WHERE organization_id=%s AND (kind = ANY(%s) OR "
                "(kind='payment' AND amount < 0))", (self.org, list(SPEND_KINDS))).fetchall()]
            for r in incoming:
                text = (r["counterparty"] + " " + r["description"]).casefold()
                if not any(w in text for w in self.REFUND_WORDS):
                    continue
                cands = [e for e in spent if e["currency"] == r["currency"] and abs(e["amount"]) >= r["amount"]
                         and timedelta(0) <= r["op_date"] - e["op_date"] <= timedelta(days=180)
                         and _similar(e["counterparty"], r["counterparty"]) >= 0.6]
                if not cands:
                    continue
                e = sorted(cands, key=lambda c: (abs(c["amount"]) != r["amount"], r["op_date"] - c["op_date"]))[0]
                reasons = [f"Incoming {r['currency']} {r['amount']:.2f} is marked as a refund",
                           f"Counterparty “{r['counterparty']}” matches the original “{e['counterparty']}”"]
                created.append(self._link(e, r, "refund", r["amount"], "refund_counterparty", reasons, "proposed"))

            # Pass D: payslips to incoming salary payments.
            for s in self.db.execute(
                    "SELECT * FROM operations_current c WHERE organization_id=%s AND kind='payslip' AND NOT EXISTS ("
                    "SELECT 1 FROM links l WHERE l.from_operation_id=c.operation_id AND l.status <> 'rejected')",
                    (self.org,)).fetchall():
                cands = [r for r in incoming if r["currency"] == s["currency"] and r["amount"] == s["amount"]
                         and abs((r["op_date"] - s["op_date"]).days) <= 15]
                if len(cands) == 1:
                    r = cands[0]
                    reasons = [f"Net pay {s['currency']} {s['amount']:.2f} equals the incoming payment",
                               f"Booked {r['op_date']:%d.%m.%Y}"]
                    good = _similar(r["counterparty"], s["counterparty"]) >= 0.6
                    if good:
                        reasons.append(f"Employer “{r['counterparty']}” matches")
                    created.append(self._link(s, r, "payment", s["amount"], "payslip_amount_date",
                                              reasons, "confirmed" if good else "proposed"))
                    incoming.remove(r)
                    if good:
                        for op_id in (str(s["operation_id"]), str(r["operation_id"])):
                            self._revision(op_id, {"verification": "confirmed", "agent": "engine:reconcile",
                                                   "verification_reason": "Payslip and bank credit agree"},
                                           "linked payslip and salary")

            for e in expenses:
                if str(e["operation_id"]) in touched:
                    self._settle(str(e["operation_id"]))
        return created

    def payment_status(self, op: str) -> dict:
        row = self.db.execute(
            "SELECT c.amount, c.currency, c.due_date, c.kind, coalesce(sum(l.amount) FILTER (WHERE l.status='confirmed'),0) AS paid, "
            "coalesce(sum(l.amount) FILTER (WHERE l.status='proposed'),0) AS proposed, "
            "coalesce((SELECT sum(-p.amount) FROM operations_current p JOIN links x ON x.to_operation_id=p.operation_id "
            "  WHERE x.from_operation_id=c.operation_id AND x.status='confirmed' AND x.link_type='payment'),0) AS paid_gross "
            "FROM operations_current c LEFT JOIN links l ON l.from_operation_id=c.operation_id AND l.link_type='payment' "
            "WHERE c.operation_id=%s GROUP BY c.amount, c.currency, c.due_date, c.kind, c.operation_id", (op,)).fetchone()
        amount, paid = row["amount"], row["paid"]
        if paid >= amount:
            state = "overpaid" if row["paid_gross"] > amount and self._single_target(op) else "paid"
        elif paid > 0:
            state = "partially_paid"
        else:
            state = "unpaid"
        overdue = state in ("unpaid", "partially_paid") and row["due_date"] is not None and row["due_date"] < date.today()
        q = Decimal("0.01")
        return {"state": state, "paid": str(paid.quantize(q)), "open": str(max(amount - paid, Decimal(0)).quantize(q)),
                "proposed": str(row["proposed"].quantize(q)), "overdue": overdue, "currency": row["currency"]}

    def _single_target(self, op: str) -> bool:
        """True when every payment linked to op pays only op (so any surplus is an overpayment of op)."""
        return self.db.execute(
            "SELECT bool_and(n = 1) AS ok FROM (SELECT count(*) n FROM links WHERE to_operation_id IN ("
            "SELECT to_operation_id FROM links WHERE from_operation_id=%s AND link_type='payment' AND status='confirmed') "
            "AND status <> 'rejected' GROUP BY to_operation_id) t", (op,)).fetchone()["ok"] or False

    def _settle(self, eid: str) -> None:
        """Update verification after links change. Confirmed only when fully covered by confirmed links."""
        e = self.db.execute("SELECT * FROM operations_current WHERE operation_id=%s", (eid,)).fetchone()
        st = self.payment_status(eid)
        links = self.db.execute("SELECT l.*, p.verification AS p_verification FROM links l JOIN operations_current p "
                                "ON p.operation_id=l.to_operation_id WHERE l.from_operation_id=%s AND l.status='confirmed' "
                                "AND l.link_type='payment'", (eid,)).fetchall()
        if st["state"] in ("paid", "overpaid"):
            rules = ", ".join(sorted({l["rule"] for l in links}))
            if e["verification"] == "needs_review":
                pass  # a person must resolve the doubt first (§17.4)
            elif st["state"] == "overpaid":
                self._revision(eid, {"verification": "needs_review", "agent": "engine:reconcile",
                                     "verification_reason": f"Paid more than invoiced ({rules}); check for a refund or credit"},
                               "overpayment detected")
            elif e["verification"] != "confirmed":
                self._revision(eid, {"verification": "confirmed", "agent": "engine:reconcile",
                                     "verification_reason": f"Document and bank payment agree ({rules})"},
                               "linked to bank payment")
            for l in links:
                if l["p_verification"] != "confirmed":
                    self._revision(str(l["to_operation_id"]), {
                        "verification": "confirmed" if e["verification"] != "needs_review" else "needs_review",
                        "category_id": e["category_id"], "agent": "engine:reconcile",
                        "verification_reason": f"Payment matches a recorded document ({l['rule']})"},
                        "linked to document")
                self.db.execute("INSERT INTO document_operations SELECT document_id, %s, 'attachment' FROM "
                                "document_operations WHERE operation_id=%s AND role='source' ON CONFLICT DO NOTHING",
                                (str(l["to_operation_id"]), eid))
        elif st["state"] == "partially_paid" and "Partially paid" not in e["verification_reason"]:
            self._revision(eid, {"agent": "engine:reconcile",
                                 "verification_reason": f"Partially paid: {st['currency']} {st['paid']} of {e['amount']:.2f}"},
                           "partial payment linked")

    def decide_link(self, link_id: str, accept: bool, actor: Optional[str] = None) -> None:
        self.authorize("decide")
        actor = actor or self.actor
        with self.db.transaction():
            link = self.db.execute("SELECT * FROM links WHERE id=%s AND organization_id=%s", (link_id, self.org)).fetchone()
            self.db.execute("UPDATE links SET status=%s, decided_by=%s, decided_at=now() WHERE id=%s",
                            ("confirmed" if accept else "rejected", actor, link_id))
            self._audit("link_confirmed" if accept else "link_rejected", "link", link_id, {}, actor=actor)
            if link["link_type"] == "payment":
                self._settle(str(link["from_operation_id"]))
            elif link["link_type"] == "duplicate" and accept:
                self._revision(str(link["from_operation_id"]), {
                    "agent": actor, "verification": "needs_review",
                    "verification_reason": "Duplicate of another record; excluded from totals"}, "marked as duplicate")
            elif link["link_type"] == "duplicate":
                self._revision(str(link["from_operation_id"]), {
                    "agent": actor, "verification": "unconfirmed",
                    "verification_reason": f"Not a duplicate (decided by {actor})"}, "duplicate rejected")
        if not accept:
            self.reconcile()

    # ------------------------------------------------------------- duplicates
    def _find_duplicates(self, op: str) -> None:
        """Same amount, date and counterparty from a different document: propose, never drop (§3)."""
        e = self.db.execute("SELECT * FROM operations_current WHERE operation_id=%s", (op,)).fetchone()
        others = self.db.execute(
            "SELECT * FROM operations_current WHERE organization_id=%s AND operation_id <> %s AND kind = ANY(%s) "
            "AND amount=%s AND currency=%s AND op_date BETWEEN %s AND %s AND "
            "NOT (source_document_id IS NOT NULL AND source_document_id = %s)",
            (self.org, op, list(SPEND_KINDS), e["amount"], e["currency"], e["op_date"] - timedelta(days=2),
             e["op_date"] + timedelta(days=2), e["source_document_id"])).fetchall()
        for o in others:
            if _similar(o["counterparty"], e["counterparty"]) < 0.75:
                continue
            reasons = [f"Same amount {e['currency']} {e['amount']:.2f}",
                       f"Dates {o['op_date']:%d.%m.%Y} and {e['op_date']:%d.%m.%Y}",
                       f"Counterparty “{o['counterparty']}” ≈ “{e['counterparty']}”"]
            self._link(e, o, "duplicate", e["amount"], "same_amount_date_counterparty", reasons, "proposed")
            self._revision(op, {"verification": "needs_review", "agent": "engine:duplicates",
                                "verification_reason": "Possible duplicate of an earlier record"}, "possible duplicate")
            break

    # --------------------------------------------------------------- FX
    def set_fx_rate(self, currency: str, rate_date: date, rate_to_base: str, source: str) -> None:
        self.authorize("configure")
        with self.db.transaction():
            self.db.execute("INSERT INTO fx_rates (currency, rate_date, rate_to_base, base, source, recorded_by) "
                            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (currency, rate_date, Decimal(rate_to_base), BASE, source, self.actor))
            self._audit("fx_rate", "fx_rate", f"{currency}:{rate_date}", {"rate": rate_to_base, "source": source})

    def fx_rate(self, currency: str, on: date) -> Optional[tuple[Decimal, str]]:
        if currency == BASE:
            return Decimal(1), "base currency"
        row = self.db.execute("SELECT rate_to_base, source, rate_date FROM fx_rates WHERE currency=%s AND base=%s "
                              "AND rate_date <= %s ORDER BY rate_date DESC LIMIT 1", (currency, BASE, on)).fetchone()
        if not row or (on - row["rate_date"]).days > 40:
            return None  # no rate close enough: shown as unconverted, never guessed
        return row["rate_to_base"], f"{row['source']} ({row['rate_date']:%d.%m.%Y})"

    def tag(self, op: str, name: str) -> None:
        self.authorize("write")
        with self.db.transaction():
            row = self.db.execute("INSERT INTO tags (id, organization_id, name) VALUES (%s,%s,%s) "
                                  "ON CONFLICT (organization_id, name) DO UPDATE SET name=EXCLUDED.name RETURNING id",
                                  (_uuid(), self.org, name.strip())).fetchone()
            self.db.execute("INSERT INTO operation_tags VALUES (%s,%s) ON CONFLICT DO NOTHING", (op, row["id"]))
            self._audit("tag", "operation", op, {"tag": name})

    def untag(self, op: str, name: str) -> None:
        self.authorize("write")
        with self.db.transaction():
            self.db.execute("DELETE FROM operation_tags t USING tags g WHERE t.tag_id=g.id AND t.operation_id=%s "
                            "AND g.name=%s", (op, name))
            self._audit("untag", "operation", op, {"tag": name})

    def tags(self, op: str) -> list[str]:
        return [r["name"] for r in self.db.execute(
            "SELECT g.name FROM operation_tags t JOIN tags g ON g.id=t.tag_id WHERE t.operation_id=%s ORDER BY g.name",
            (op,)).fetchall()]

    # ---------------------------------------------------------------- views
    def _spend_rows(self, start: date, end: date) -> list[dict]:
        """Expenses counted once (§18): recognised documents, plus the part of bank
        debits that no document explains, minus confirmed refunds. Confirmed
        duplicates are excluded."""
        rows = self.db.execute(
            "SELECT c.*, (SELECT count(*) FROM links l WHERE l.status='proposed' AND "
            "(l.from_operation_id=c.operation_id OR l.to_operation_id=c.operation_id)) AS proposed_links, "
            "CASE WHEN c.kind='payment' THEN -c.amount - coalesce((SELECT sum(l.amount) FROM links l WHERE "
            "l.to_operation_id=c.operation_id AND l.status <> 'rejected' AND l.link_type='payment'),0) "
            "ELSE c.amount END AS counted "
            "FROM operations_current c WHERE c.organization_id=%s AND c.op_date BETWEEN %s AND %s AND ("
            " (c.kind = ANY(%s) AND NOT EXISTS (SELECT 1 FROM links d WHERE d.from_operation_id=c.operation_id "
            "   AND d.link_type='duplicate' AND d.status='confirmed')) OR (c.kind='payment' AND c.amount < 0))",
            (self.org, start, end, list(SPEND_KINDS))).fetchall()
        refunds = self.db.execute(
            "SELECT r.*, 0 AS proposed_links, -l.amount AS counted, e.category_id AS category_id "
            "FROM links l JOIN operations_current r ON r.operation_id=l.to_operation_id "
            "JOIN operations_current e ON e.operation_id=l.from_operation_id "
            "WHERE l.organization_id=%s AND l.link_type='refund' AND l.status='confirmed' AND r.op_date BETWEEN %s AND %s",
            (self.org, start, end)).fetchall()
        return [r for r in rows if r["counted"] > 0] + list(refunds)

    def _income_rows(self, start: date, end: date) -> list[dict]:
        return self.db.execute(
            "SELECT c.*, 0 AS proposed_links, c.amount AS counted FROM operations_current c WHERE c.organization_id=%s "
            "AND c.op_date BETWEEN %s AND %s AND (c.kind = ANY(%s) OR (c.kind='payment' AND c.amount > 0 "
            "AND NOT EXISTS (SELECT 1 FROM links l WHERE l.to_operation_id=c.operation_id AND l.status='confirmed')))",
            (self.org, start, end, list(INCOME_KINDS))).fetchall()

    def _in_base(self, row: dict) -> Optional[Decimal]:
        """Counted amount in CHF (signed: refunds are negative). Uses the recorded rate,
        or the closest recorded rate; never an invented one."""
        amount = row["counted"] if "counted" in row else abs(row["amount"])
        if row["currency"] == BASE:
            return Decimal(amount).quantize(Decimal("0.01"))
        rate = row["fx_rate"]
        if rate is None:
            found = self.fx_rate(row["currency"], row["op_date"])
            rate = found[0] if found else None
        if rate is None:
            return None
        return (Decimal(amount) * rate).quantize(Decimal("0.01"))

    def treemap(self, start: date, end: date, mode: str = "expenses", group: str = "category") -> dict:
        """Toggles (§6.1): expenses or income; grouped by category, account, project, counterparty or object."""
        self.authorize("read")
        rows = self._spend_rows(start, end) if mode == "expenses" else self._income_rows(start, end)
        paths = {c["id"]: c["path"] for c in self.categories()}
        if group != "category":
            table = {"account": "accounts", "project": "projects", "object": "objects", "member": "members"}.get(group)
            names = {str(r["id"]): r["name"] for r in self.db.execute(
                f"SELECT id, name FROM {table} WHERE organization_id=%s", (self.org,)).fetchall()} if table else {}
            for r in rows:
                label = (r["counterparty"] or "(unknown)") if group == "counterparty" else \
                    names.get(str(r.get(f"{group}_id")), f"(no {group})")
                paths[f"g:{r['operation_id']}"] = (label,)
                r["category_id"] = f"g:{r['operation_id']}"
        root: dict = {"name": "All", "total": Decimal(0), "children": {}, "operations": [], "count": 0}
        unconverted = []
        for r in rows:
            value = self._in_base(r)
            if value is None:
                unconverted.append(str(r["operation_id"]))
                continue
            path = paths.get(str(r["category_id"]), ("Unclassified",))
            if group == "category" and path[0] == "Own transfers":
                continue
            node = root
            node["total"] += value
            node["count"] += 1
            for part in path:
                node = node["children"].setdefault(part, {"name": part, "total": Decimal(0), "children": {},
                                                          "operations": [], "count": 0})
                node["total"] += value
                node["count"] += 1
            node["operations"].append({
                "id": str(r["operation_id"]), "kind": r["kind"], "amount": str(value), "currency": BASE,
                "date": r["op_date"].isoformat(), "counterparty": r["counterparty"], "verification": r["verification"],
                "proposed_links": r["proposed_links"], "has_document": r["source_document_id"] is not None
                and r["kind"] != "payment"})

        def finish(n):
            return {"name": n["name"], "total": str(n["total"]), "count": n["count"],
                    "children": [finish(c) for c in sorted(n["children"].values(), key=lambda c: -c["total"])],
                    "operations": sorted(n["operations"], key=lambda o: -Decimal(o["amount"]))}

        out = finish(root)
        out.update({"currency": BASE, "start": start.isoformat(), "end": end.isoformat(), "mode": mode, "group": group,
                    "unconverted": unconverted})
        return out

    def operations(self, start: date, end: date, category_prefix: tuple[str, ...] = ()) -> list[dict]:
        tree = self.treemap(start, end)
        node = tree
        for part in category_prefix:
            node = next((c for c in node["children"] if c["name"] == part), None)
            if node is None:
                return []
        out = []

        def walk(n):
            out.extend(n["operations"])
            for c in n["children"]:
                walk(c)
        walk(node)
        return out

    def dashboard(self, start: date, end: date) -> dict:
        self.authorize("read")
        spend = sum((self._in_base(r) or Decimal(0)) for r in self._spend_rows(start, end))
        income = sum((self._in_base(r) or Decimal(0)) for r in self._income_rows(start, end))
        unconfirmed = self.db.execute(
            "SELECT operation_id, kind, amount, currency, op_date, counterparty, verification, verification_reason "
            "FROM operations_current WHERE organization_id=%s AND verification <> 'confirmed' "
            "ORDER BY op_date DESC LIMIT 50", (self.org,)).fetchall()
        unpaid = self.db.execute(
            "SELECT operation_id, amount, currency, op_date, due_date, counterparty FROM operations_current c "
            "WHERE organization_id=%s AND kind='invoice' AND NOT EXISTS (SELECT 1 FROM links l WHERE "
            "l.from_operation_id=c.operation_id AND l.status='confirmed' AND l.link_type='payment') "
            "ORDER BY coalesce(due_date, op_date)", (self.org,)).fetchall()
        recent = self.db.execute(
            "SELECT id, filename, doc_type, processing_status, folder, received_at FROM documents "
            "WHERE organization_id=%s ORDER BY received_at DESC LIMIT 10", (self.org,)).fetchall()
        bank = self.db.execute(
            "SELECT coalesce(sum(amount),0) AS s FROM operations_current WHERE organization_id=%s "
            "AND kind IN ('payment','transfer') AND currency=%s AND op_date BETWEEN %s AND %s",
            (self.org, BASE, start, end)).fetchone()["s"]
        return {"start": start.isoformat(), "end": end.isoformat(), "currency": BASE,
                "income": str(income), "expenses": str(spend), "balance": str(income - spend),
                "bank_net": str(Decimal(bank).quantize(Decimal("0.01"))),
                "unconfirmed": [self._json(r) for r in unconfirmed], "unpaid": [self._json(r) for r in unpaid],
                "recent_documents": [self._json(r) for r in recent]}

    @staticmethod
    def _json(row: dict) -> dict:
        out = {}
        for k, v in row.items():
            if isinstance(v, Decimal):
                if k in ("amount", "other_amount"):
                    places = MINOR_UNITS.get(row.get("currency") or row.get("other_currency") or BASE, 2)
                    v = v.quantize(Decimal(1).scaleb(-places))
                v = str(v)
            elif isinstance(v, (date,)):
                v = v.isoformat()
            elif isinstance(v, uuid.UUID):
                v = str(v)
            out[k] = v
        return out

    def operation_detail(self, op: str) -> dict:
        self.authorize("read")
        cur = self.db.execute
        current = cur("SELECT * FROM operations_current WHERE operation_id=%s", (op,)).fetchone()
        history = cur("SELECT * FROM operation_revisions WHERE operation_id=%s ORDER BY revision", (op,)).fetchall()
        docs = cur("SELECT d.*, o.role FROM document_operations o JOIN documents d ON d.id=o.document_id "
                   "WHERE o.operation_id=%s ORDER BY o.role DESC", (op,)).fetchall()
        extractions = cur("SELECT e.document_id, e.engine, e.text, e.fields FROM extractions e "
                          "WHERE e.document_id = ANY(%s)", ([d["id"] for d in docs],)).fetchall()
        links = cur("SELECT l.*, c.kind AS other_kind, c.amount AS other_amount, c.currency AS other_currency, "
                    "c.op_date AS other_date, c.counterparty AS other_counterparty, c.source_document_id AS other_doc "
                    "FROM links l JOIN operations_current c ON c.operation_id = CASE WHEN l.from_operation_id=%s "
                    "THEN l.to_operation_id ELSE l.from_operation_id END "
                    "WHERE l.from_operation_id=%s OR l.to_operation_id=%s", (op, op, op)).fetchall()
        audit = cur("SELECT at, actor, action, details FROM audit_log WHERE entity_id=%s OR entity_id = ANY(%s) "
                    "ORDER BY at, id", (op, [str(l["id"]) for l in links])).fetchall()
        result = self._json(current)
        result["category_path"] = list(self.category_path(current["category_id"]))
        result["history"] = [self._json(h) | {"category_path": list(self.category_path(h["category_id"]))}
                             for h in history]
        result["documents"] = [self._json(d) for d in docs]
        result["extractions"] = [self._json(e) for e in extractions]
        result["links"] = [self._json(l) for l in links]
        result["audit"] = [self._json(a) for a in audit]
        result["tags"] = self.tags(op)
        return result

    def original(self, document_id: str) -> tuple[bytes, str, str]:
        self.authorize("read")
        row = self.db.execute("SELECT sha256, media_type, filename FROM documents WHERE id=%s AND organization_id=%s",
                              (document_id, self.org)).fetchone()
        return self.files.get(row["sha256"]), row["media_type"], row["filename"]

    def documents(self) -> list[dict]:
        self.authorize("read")
        rows = self.db.execute(
            "SELECT d.*, (SELECT count(*) FROM document_operations o WHERE o.document_id=d.id) AS operations "
            "FROM documents d WHERE organization_id=%s ORDER BY received_at DESC", (self.org,)).fetchall()
        return [self._json(r) for r in rows]

    def ai_activity(self, limit: int = 200) -> list[dict]:
        return [self._json(r) for r in self.db.execute(
            "SELECT * FROM ai_activity WHERE organization_id=%s ORDER BY id DESC LIMIT %s", (self.org, limit)).fetchall()]

    def close(self) -> None:
        self.db.close()
