"""Corporate edition licences: a 3-month trial, then a signed key from Helvetic Lens.

Everything is checked offline. A key is an Ed25519 signature by the Helvetic Lens issuer over a small
JSON payload, bound to one installation:

    FLK1.<base64url payload>.<base64url signature>
    payload = {"v": 1, "install": "<uuid>", "customer": "Muster AG", "seats": 25,
               "plan": "monthly" | "2y", "issued": "2026-11-05", "expires": "2027-11-05"}

Prices (CHF, per user): 1 per month, or 10 for two years. The trial starts with the first start of the
corporate server; its date is written to the append-only audit log, so it cannot be reset by editing
settings. Without a valid licence after the trial the data stays readable and exportable, but nothing
new can be recorded (read-only), so a company never loses access to its own books.

Issuing (Helvetic Lens only, needs the private key that never leaves the issuer's computer):
    financial-lens license keygen                 # once; prints the public key for ISSUER_PUBLIC_KEYS
    financial-lens license issue REQUEST --plan monthly --seats 25 --months 12
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

TRIAL_DAYS = 90
PRICE_PER_USER_MONTH = Decimal("1")
PRICE_PER_USER_2Y = Decimal("10")
PLANS = ("monthly", "2y")
PREFIX = "FLK1"
REQUEST_PREFIX = "FLR1"
LICENSE_CONTACT = os.environ.get("FL_LICENSE_CONTACT", "info@helveticlens.ch")

# Public keys of the Helvetic Lens licence issuer (raw Ed25519, base64). Several may be listed while a key
# is rotated. FL_LICENSE_PUBKEY adds one (used by tests and private builds).
ISSUER_PUBLIC_KEYS: list[str] = []


class LicenseError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_keys() -> list[str]:
    keys = list(ISSUER_PUBLIC_KEYS)
    if os.environ.get("FL_LICENSE_PUBKEY"):
        keys.append(os.environ["FL_LICENSE_PUBKEY"].strip())
    return keys


# --------------------------------------------------------------------------- prices
def price(plan: str, seats: int, months: int = 1) -> Decimal:
    if plan == "monthly":
        return PRICE_PER_USER_MONTH * seats * months
    if plan == "2y":
        return PRICE_PER_USER_2Y * seats
    raise LicenseError(f"Unknown plan {plan!r}; use monthly or 2y.")


# --------------------------------------------------------------------------- keys
def verify(key: str, install_id: str) -> dict:
    """Return the payload of a valid key for this installation, or raise LicenseError."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    parts = key.strip().split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenseError("This is not a Financial Lens licence key.")
    try:
        body, sig = _unb64(parts[1]), _unb64(parts[2])
    except Exception:
        raise LicenseError("The licence key is damaged (copy it again, completely).")
    pubs = _public_keys()
    if not pubs:
        raise LicenseError("This build has no licence issuer key configured.")
    for pub in pubs:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(sig, body)
            break
        except (InvalidSignature, ValueError):
            continue
    else:
        raise LicenseError("The licence key's signature is not valid.")
    payload = json.loads(body)
    if payload.get("v") != 1 or payload.get("plan") not in PLANS or int(payload.get("seats", 0)) < 1:
        raise LicenseError("The licence key has an unknown format.")
    if payload.get("install") != install_id:
        raise LicenseError("This key was issued for another installation.")
    return payload


def issue(private_key_b64: str, request: str, plan: str, seats: int, months: int = 12,
          customer: Optional[str] = None, start: Optional[date] = None) -> str:
    """Sign a key for the installation named in a request code (issuer side)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    req = read_request(request)
    if plan not in PLANS:
        raise LicenseError("plan is monthly or 2y")
    if seats < 1:
        raise LicenseError("seats must be at least 1")
    start = start or date.today()
    expires = _add_months(start, 24 if plan == "2y" else months)
    payload = {"v": 1, "install": req["install"], "customer": customer or req.get("org", ""), "seats": int(seats),
               "plan": plan, "issued": start.isoformat(), "expires": expires.isoformat()}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    sig = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64)).sign(body)
    return f"{PREFIX}.{_b64(body)}.{_b64(sig)}"


def keygen() -> tuple[str, str]:
    """A new issuer key pair (private, public), both raw Ed25519 in base64."""
    from cryptography.hazmat.primitives import serialization as s
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(s.Encoding.Raw, s.PrivateFormat.Raw, s.NoEncryption())
    pub = k.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)
    return base64.b64encode(priv).decode(), base64.b64encode(pub).decode()


def public_of(private_key_b64: str) -> str:
    from cryptography.hazmat.primitives import serialization as s
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    k = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    return base64.b64encode(k.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)).decode()


def issuer_key_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return Path(os.environ.get("FL_ISSUER_KEY", base / "financial-lens-issuer" / "issuer.key"))


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise AssertionError


# --------------------------------------------------------------------------- requests
def make_request(install_id: str, org: str, users: int) -> str:
    body = json.dumps({"v": 1, "install": install_id, "org": org, "users": users}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode()
    return f"{REQUEST_PREFIX}.{_b64(body)}"


def read_request(code: str) -> dict:
    code = "".join(code.split())
    if not code.startswith(REQUEST_PREFIX + "."):
        raise LicenseError("This is not a Financial Lens licence request.")
    try:
        req = json.loads(_unb64(code.split(".", 1)[1]))
        uuid.UUID(req["install"])
    except Exception:
        raise LicenseError("The licence request is damaged (copy it again, completely).")
    return req


# --------------------------------------------------------------------------- state of one installation
@dataclass
class Status:
    state: str                  # trial · active · trial_ended · expired · over_seats · invalid
    writable: bool
    install_id: str
    trial_started: str
    trial_ends: str
    days_left: int
    users: int
    seats: Optional[int] = None
    plan: Optional[str] = None
    customer: Optional[str] = None
    expires: Optional[str] = None
    message: str = ""
    prices: dict = field(default_factory=dict)
    contact: str = LICENSE_CONTACT


def _setting(lens, key: str):
    row = lens.db.execute("SELECT value FROM settings WHERE organization_id=%s AND key=%s", (lens.org, key)).fetchone()
    return row["value"] if row else None


def install_id(lens) -> str:
    """The installation's identity, fixed at the first corporate start (kept in the audit log)."""
    row = lens.db.execute("SELECT entity_id, at FROM audit_log WHERE action='trial_start' AND organization_id=%s "
                          "ORDER BY id LIMIT 1", (lens.org,)).fetchone()
    if row:
        return row["entity_id"]
    iid = str(uuid.uuid4())
    with lens.db.transaction():
        lens._audit("trial_start", "installation", iid, {"trial_days": TRIAL_DAYS}, actor="system")
    return iid


def trial_started(lens) -> date:
    install_id(lens)
    row = lens.db.execute("SELECT at FROM audit_log WHERE action='trial_start' AND organization_id=%s ORDER BY id LIMIT 1",
                          (lens.org,)).fetchone()
    return row["at"].date()


def active_users(lens) -> int:
    return lens.db.execute(
        "SELECT count(*) AS n FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.organization_id=%s "
        "AND u.login IS NOT NULL AND u.disabled_at IS NULL", (lens.org,)).fetchone()["n"]


def status(lens, today: Optional[date] = None) -> Status:
    today = today or date.today()
    iid = install_id(lens)
    started = trial_started(lens)
    ends = started + timedelta(days=TRIAL_DAYS)
    users = active_users(lens)
    prices = {"monthly": str(price("monthly", max(users, 1))), "2y": str(price("2y", max(users, 1)))}
    base = dict(install_id=iid, trial_started=started.isoformat(), trial_ends=ends.isoformat(), users=users, prices=prices)
    key = _setting(lens, "license_key")
    if key:
        try:
            p = verify(key, iid)
        except LicenseError as exc:
            return Status("invalid", False, days_left=0, message=str(exc), **base)
        exp = date.fromisoformat(p["expires"])
        lic = dict(seats=p["seats"], plan=p["plan"], customer=p.get("customer"), expires=p["expires"])
        if exp < today:
            return Status("expired", False, days_left=0, message=f"The licence ended on {exp:%d.%m.%Y}. "
                          "Data stays readable and exportable; request a new key to keep recording.", **lic, **base)
        if users > p["seats"]:
            return Status("over_seats", False, days_left=(exp - today).days, message=(
                f"{users} active users, the licence covers {p['seats']}. Disable users or request a key for more."),
                **lic, **base)
        return Status("active", True, days_left=(exp - today).days, **lic, **base)
    if today <= ends:
        return Status("trial", True, days_left=(ends - today).days, message=f"Trial until {ends:%d.%m.%Y}.", **base)
    return Status("trial_ended", False, days_left=0, message=(
        f"The 3-month trial ended on {ends:%d.%m.%Y}. Data stays readable and exportable; "
        "request a licence key to keep recording."), **base)


def install_key(lens, key: str) -> dict:
    lens.authorize("admin")
    p = verify(key, install_id(lens))
    from psycopg.types.json import Jsonb

    with lens.db.transaction():
        lens.db.execute("INSERT INTO settings VALUES (%s,'license_key',%s) ON CONFLICT (organization_id, key) "
                        "DO UPDATE SET value=EXCLUDED.value, updated_at=now()", (lens.org, Jsonb(key.strip())))
        lens._audit("license_install", "installation", p["install"],
                    {k: p[k] for k in ("customer", "seats", "plan", "issued", "expires")})
    return p


def request_code(lens) -> str:
    org = lens.db.execute("SELECT name FROM organizations WHERE id=%s", (lens.org,)).fetchone()["name"]
    return make_request(install_id(lens), org, active_users(lens))
