"""Mobile app API v1 (see docs/MOBILE_ARCHITECTURE.md).

Pairing: a one-time offer (5 minutes) is shown as a QR code; the phone proves
the one-time secret and registers its own P-256 public key. Afterwards every
request carries a signature over method, path, time, nonce and body hash,
made with the device key, which never leaves the phone. The server checks
signature, freshness, nonce reuse, revocation and scopes. Values returned are
computed by the ledger; the phone does no money maths.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from ..service import FinancialLens

SCOPES = {"upload", "read", "review", "read_own"}
MAX_SKEW = timedelta(minutes=5)
OFFER_TTL = timedelta(minutes=5)


# ----------------------------------------------------------------- pairing
def create_offer(lens: FinancialLens, address: str, cert_fingerprint: str,
                 scopes: tuple[str, ...] = ("upload", "read")) -> dict:
    """Called on the desktop. Returns the QR payload; the secret is stored only as a hash."""
    lens.authorize("configure")
    if not set(scopes) <= SCOPES:
        raise ValueError("Unknown scope")
    otp = secrets.token_urlsafe(16)
    oid = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + OFFER_TTL
    with lens.db.transaction():
        lens.db.execute("INSERT INTO pair_offers (id, organization_id, otp_sha256, scopes, created_by, expires_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (oid, lens.org, hashlib.sha256(otp.encode()).hexdigest(), list(scopes), lens.actor, expires))
        lens._audit("pair_offer", "mobile", oid, {"scopes": list(scopes), "expires_at": expires.isoformat()})
    uri = (f"fl://pair?v=1&addr={quote(address)}&fp={cert_fingerprint}&offer={oid}&otp={otp}"
           f"&scopes={','.join(scopes)}")
    return {"uri": uri, "offer_id": oid, "expires_at": expires.isoformat()}


def revoke(lens: FinancialLens, device_id: str) -> None:
    lens.authorize("configure")
    with lens.db.transaction():
        lens.db.execute("UPDATE mobile_devices SET revoked_at=now() WHERE id=%s AND organization_id=%s",
                        (device_id, lens.org))
        lens._audit("revoke_mobile", "mobile", device_id, {})


def devices(lens: FinancialLens) -> list[dict]:
    lens.authorize("read")
    return [lens._json(r) for r in lens.db.execute(
        "SELECT id, name, platform, scopes, paired_at, last_seen_at, revoked_at FROM mobile_devices "
        "WHERE organization_id=%s ORDER BY paired_at", (lens.org,)).fetchall()]


def canonical(method: str, path: str, ts: str, nonce: str, body: bytes) -> bytes:
    return "\n".join([method.upper(), path, ts, nonce, hashlib.sha256(body).hexdigest()]).encode()


def _load_key(b64: str):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    key = load_der_public_key(base64.b64decode(b64))
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise ValueError("Device key must be an ECDSA P-256 public key")
    return key


class PairRequest(BaseModel):
    offer: str
    otp: str
    name: str
    platform: str
    public_key: str  # base64 DER SubjectPublicKeyInfo


class Decision(BaseModel):
    accept: bool


def make_router(get_lens) -> APIRouter:
    router = APIRouter(prefix="/mobile/v1")

    @router.post("/pair")
    def pair(body: PairRequest, fl: FinancialLens = Depends(get_lens)) -> dict:
        try:
            key = _load_key(body.public_key)
        except Exception:
            raise HTTPException(422, "Invalid device key.")
        with fl.db.transaction():
            offer = fl.db.execute("SELECT * FROM pair_offers WHERE id=%s FOR UPDATE", (body.offer,)).fetchone()
            ok = (offer is not None and offer["used_at"] is None and offer["expires_at"] > datetime.now(timezone.utc)
                  and hmac.compare_digest(offer["otp_sha256"], hashlib.sha256(body.otp.encode()).hexdigest()))
            if ok:
                did = str(uuid.uuid4())
                fl.db.execute("UPDATE pair_offers SET used_at=now() WHERE id=%s", (body.offer,))
                fl.db.execute("INSERT INTO mobile_devices (id, organization_id, name, platform, public_key, key_sha256, scopes) "
                              "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                              (did, offer["organization_id"], body.name[:80], body.platform[:20], body.public_key,
                               hashlib.sha256(body.public_key.encode()).hexdigest(), offer["scopes"]))
                fl._audit("pair_device", "mobile", did, {"name": body.name[:80], "platform": body.platform[:20],
                                                         "scopes": offer["scopes"]})
        if not ok:
            with fl.db.transaction():
                fl._audit("pair_rejected", "mobile", body.offer, {"name": body.name[:60]}, actor="mobile:unpaired")
            raise HTTPException(403, "This pairing code is invalid, used or expired. Create a new one on the desktop.")
        del key
        return {"device_id": did, "scopes": offer["scopes"]}

    async def device(request: Request, fl: FinancialLens = Depends(get_lens)) -> dict:
        h = request.headers
        did, ts, nonce, sig = (h.get("x-fl-device"), h.get("x-fl-timestamp"), h.get("x-fl-nonce"), h.get("x-fl-signature"))
        if not all((did, ts, nonce, sig)) or len(nonce) > 64:
            raise HTTPException(401, "Signed request required.")
        try:
            when = datetime.fromisoformat(ts)
        except ValueError:
            raise HTTPException(401, "Bad timestamp.")
        if when.tzinfo is None or abs(datetime.now(timezone.utc) - when) > MAX_SKEW:
            raise HTTPException(401, "Request time is off by more than 5 minutes; check the phone's clock.")
        row = fl.db.execute("SELECT * FROM mobile_devices WHERE id::text=%s", (did,)).fetchone()
        if row is None or row["revoked_at"] is not None:
            raise HTTPException(401, "This phone is not paired, or its access was revoked.")
        body = await request.body()
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec

            _load_key(row["public_key"]).verify(base64.b64decode(sig),
                                                canonical(request.method, request.url.path, ts, nonce, body),
                                                ec.ECDSA(hashes.SHA256()))
        except Exception:
            raise HTTPException(401, "Signature check failed.")
        with fl.db.transaction():
            fl.db.execute("DELETE FROM mobile_nonces WHERE seen_at < now() - interval '15 minutes'")
            fresh = fl.db.execute("INSERT INTO mobile_nonces (device_id, nonce) VALUES (%s,%s) ON CONFLICT DO NOTHING "
                                  "RETURNING 1", (did, nonce)).fetchone()
            if not fresh:
                raise HTTPException(401, "Replayed request.")
            fl.db.execute("UPDATE mobile_devices SET last_seen_at=now() WHERE id=%s", (did,))
        if str(row["organization_id"]) != fl.org:
            fl.open_organization(fl.db.execute("SELECT name FROM organizations WHERE id=%s",
                                               (row["organization_id"],)).fetchone()["name"])
        return row

    def need(row: dict, scope: str) -> None:
        if scope not in row["scopes"]:
            raise HTTPException(403, f"This phone does not have the '{scope}' permission.")

    def _period(start: Optional[date], end: Optional[date]) -> tuple[date, date]:
        today = date.today()
        return start or today.replace(day=1), end or today

    @router.post("/documents")
    async def upload(request: Request, dev: dict = Depends(device), fl: FinancialLens = Depends(get_lens)) -> dict:
        need(dev, "upload")
        form = await request.form()
        out = []
        actor = fl.actor
        fl.actor = f"mobile:{dev['name']}"
        try:
            for f in form.getlist("files"):
                data = await f.read()
                if len(data) > 40 * 1024 * 1024:
                    out.append({"file": f.filename, "error": "larger than 40 MB"})
                    continue
                ctype = f.content_type if f.content_type not in (None, "", "application/octet-stream") else None
                res = fl.ingest(data, f.filename or "scan.jpg", ctype)
                item = {"file": f.filename, "sha256": hashlib.sha256(data).hexdigest(), "document_id": res.document_id,
                        "duplicate": bool(res.duplicate_of), "type": res.doc_type, "records": len(res.operation_ids),
                        "messages": res.messages}
                if res.operation_ids:
                    d = fl.operation_detail(res.operation_ids[0])
                    item.update({"operation_id": d["operation_id"], "amount": d["amount"], "currency": d["currency"],
                                 "counterparty": d["counterparty"], "category": d["category_path"],
                                 "status": d["verification"]})
                out.append(item)
        finally:
            fl.actor = actor
        return {"results": out}

    @router.get("/summary")
    def summary(start: Optional[date] = None, end: Optional[date] = None, dev: dict = Depends(device),
                fl: FinancialLens = Depends(get_lens)) -> dict:
        need(dev, "read")
        s, e = _period(start, end)
        d = fl.dashboard(s, e)
        tree = fl.treemap(s, e)
        return {"start": d["start"], "end": d["end"], "currency": d["currency"], "income": d["income"],
                "expenses": d["expenses"], "balance": d["balance"], "unconfirmed": len(d["unconfirmed"]),
                "unpaid": len(d["unpaid"]),
                "categories": [{"name": c["name"], "total": c["total"], "count": c["count"]} for c in tree["children"]],
                "recent_documents": d["recent_documents"][:5]}

    @router.get("/widget")
    def widget(dev: dict = Depends(device), fl: FinancialLens = Depends(get_lens)) -> dict:
        need(dev, "read")
        today = date.today()
        d = fl.dashboard(today.replace(day=1), today)
        top = fl.treemap(today.replace(day=1), today)["children"][:3]
        return {"month": today.strftime("%Y-%m"), "expenses": d["expenses"], "income": d["income"],
                "unconfirmed": len(d["unconfirmed"]), "top": [{"name": c["name"], "total": c["total"]} for c in top],
                "as_of": datetime.now(timezone.utc).isoformat()}

    @router.get("/treemap")
    def treemap(path: str = "", start: Optional[date] = None, end: Optional[date] = None, dev: dict = Depends(device),
                fl: FinancialLens = Depends(get_lens)) -> dict:
        need(dev, "read")
        node = fl.treemap(*_period(start, end))
        for part in [p for p in path.split("/") if p]:
            node = next((c for c in node["children"] if c["name"] == part), None)
            if node is None:
                raise HTTPException(404, "Category not found in this period.")
        return {"name": node["name"], "total": node["total"], "count": node["count"],
                "children": [{"name": c["name"], "total": c["total"], "count": c["count"]} for c in node["children"]],
                "operations": node["operations"]}

    @router.get("/operations/{op_id}")
    def operation(op_id: str, dev: dict = Depends(device), fl: FinancialLens = Depends(get_lens)) -> dict:
        need(dev, "read")
        try:
            d = fl.operation_detail(op_id)
        except TypeError:
            raise HTTPException(404, "Not found.")
        keep = ("operation_id", "kind", "amount", "currency", "op_date", "due_date", "counterparty", "description",
                "category_path", "verification", "verification_reason", "method", "confidence", "tags")
        out = {k: d.get(k) for k in keep}
        out["documents"] = [{"id": x["id"], "filename": x["filename"], "media_type": x["media_type"], "role": x["role"],
                             "sha256": x["sha256"]} for x in d["documents"]]
        out["links"] = [{"status": l["status"], "rule": l["rule"], "reasons": l["reasons"], "other_kind": l["other_kind"],
                         "other_date": l["other_date"], "other_amount": l["other_amount"],
                         "other_counterparty": l["other_counterparty"]} for l in d["links"]]
        out["provenance"] = {k: {kk: v.get(kk) for kk in ("line", "quote", "confidence", "method")}
                             for k, v in (d.get("provenance") or {}).items() if isinstance(v, dict)}
        out["history"] = [{"revision": h["revision"], "created_at": h["created_at"], "agent": h["agent"],
                           "change_reason": h["change_reason"], "verification": h["verification"]} for h in d["history"]]
        return out

    @router.get("/documents/{doc_id}/original")
    def original(doc_id: str, dev: dict = Depends(device), fl: FinancialLens = Depends(get_lens)) -> Response:
        need(dev, "read")
        try:
            data, media, name = fl.original(doc_id)
        except TypeError:
            raise HTTPException(404, "Not found.")
        return Response(data, media_type=media, headers={"Content-Disposition": f'inline; filename="{name}"',
                                                         "Cache-Control": "no-store"})

    @router.post("/links/{link_id}/decision")
    def decide(link_id: str, body: Decision, dev: dict = Depends(device), fl: FinancialLens = Depends(get_lens)) -> dict:
        need(dev, "review")
        actor = fl.actor
        fl.actor = f"mobile:{dev['name']}"
        try:
            fl.decide_link(link_id, body.accept)
        finally:
            fl.actor = actor
        return {"status": "confirmed" if body.accept else "rejected"}

    return router
