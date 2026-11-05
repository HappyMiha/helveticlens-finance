"""Corporate edition: one Financial Lens server for a whole company.

People sign in from their browsers with their own login (or through the company's single sign-on proxy),
each with a role, on one shared PostgreSQL ledger. Every sign-in, change of role and refused action goes to
the tamper-evident audit log. Passwords are stored as scrypt hashes; browser sessions as SHA-256 of a
random token, so a copy of the database does not let anyone sign in.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .service import PERMISSIONS, AccessDenied, FinancialLens

ROLES = ("owner", "admin", "editor", "viewer", "member")
ROLE_LABELS = {"owner": "Owner", "admin": "Administrator", "editor": "Bookkeeper (can record and decide)",
               "viewer": "Viewer (read and export)", "member": "Member (own statement only)"}
SESSION_IDLE = timedelta(hours=int(os.environ.get("FL_SESSION_IDLE_HOURS", "12")))
SESSION_MAX = timedelta(days=int(os.environ.get("FL_SESSION_MAX_DAYS", "7")))
MIN_PASSWORD = 10
LOGIN_RE = re.compile(r"^[A-Za-z0-9._@+-]{2,64}$")


class LoginError(PermissionError):
    pass


# --------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    n, r, p = 2 ** 15, 8, 1
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${dk.hex()}"


def check_password(password: str, stored: Optional[str]) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, n, r, p, salt, dk = stored.split("$")
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                         maxmem=64 * 1024 * 1024, dklen=len(dk) // 2)
    return hmac.compare_digest(got.hex(), dk)


_DUMMY = None


def _dummy_hash() -> str:  # same work for unknown logins, so timing does not reveal who exists
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password(secrets.token_hex(8))
    return _DUMMY


def _check_new_password(password: str, login: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if password.casefold() == login.casefold():
        raise ValueError("The password must not be the login.")


# --------------------------------------------------------------------------- users
def has_logins(lens: FinancialLens) -> bool:
    return bool(lens.db.execute("SELECT 1 FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.organization_id=%s "
                                "AND u.login IS NOT NULL LIMIT 1", (lens.org,)).fetchone())


def _seat_check(lens: FinancialLens) -> None:
    from . import licensing

    st = licensing.status(lens)
    if st.seats is not None and st.state == "active" and licensing.active_users(lens) >= st.seats:
        raise AccessDenied(f"The licence covers {st.seats} users. Request a key for more users first.")


def create_user(lens: FinancialLens, login: str, name: str, role: str, password: Optional[str] = None,
                email: str = "", bootstrap: bool = False) -> str:
    """Create a person with a login. `bootstrap` is the first administrator (from the console or setup code)."""
    if not bootstrap:
        lens.authorize("admin")
        if role == "owner" and lens.role() != "owner":
            raise AccessDenied("Only an owner can make another owner.")
    login = login.strip()
    if not LOGIN_RE.match(login):
        raise ValueError("A login is 2–64 letters, digits or . _ @ + -")
    if role not in ROLES:
        raise ValueError(f"Role is one of {', '.join(ROLES)}.")
    if lens.db.execute("SELECT 1 FROM users WHERE lower(login)=lower(%s)", (login,)).fetchone():
        raise ValueError("This login is taken.")
    if password is not None:
        _check_new_password(password, login)
    _seat_check(lens)
    uid = str(uuid.uuid4())
    with lens.db.transaction():
        lens.db.execute("INSERT INTO users (id, name, login, email, password_hash) VALUES (%s,%s,%s,%s,%s)",
                        (uid, name.strip() or login, login, email.strip(), hash_password(password) if password else None))
        lens.db.execute("INSERT INTO memberships VALUES (%s,%s,%s)", (lens.org, uid, role))
        lens._audit("grant", "membership", uid, {"login": login, "name": name, "role": role, "bootstrap": bootstrap},
                    actor="setup" if bootstrap else None)
    return uid


def users(lens: FinancialLens) -> list[dict]:
    lens.authorize("admin")
    rows = lens.db.execute(
        "SELECT u.id, u.login, u.name, u.email, m.role, u.created_at, u.last_login_at, u.disabled_at, "
        "(u.password_hash IS NOT NULL) AS has_password FROM users u JOIN memberships m ON m.user_id=u.id "
        "WHERE m.organization_id=%s AND u.login IS NOT NULL ORDER BY u.disabled_at NULLS FIRST, lower(u.name)",
        (lens.org,)).fetchall()
    return [lens._json(r) for r in rows]


def _target(lens: FinancialLens, user_id: str) -> dict:
    row = lens.db.execute("SELECT u.*, m.role FROM users u JOIN memberships m ON m.user_id=u.id "
                          "WHERE u.id=%s AND m.organization_id=%s", (user_id, lens.org)).fetchone()
    if not row:
        raise LookupError("No such user.")
    return row


def _owners_left(lens: FinancialLens, without: str) -> int:
    return lens.db.execute("SELECT count(*) AS n FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.organization_id=%s "
                           "AND m.role IN ('owner','admin') AND u.disabled_at IS NULL AND u.id<>%s",
                           (lens.org, without)).fetchone()["n"]


def update_user(lens: FinancialLens, user_id: str, role: Optional[str] = None, disabled: Optional[bool] = None,
                name: Optional[str] = None, email: Optional[str] = None) -> None:
    lens.authorize("admin")
    t = _target(lens, user_id)
    if t["role"] == "owner" and lens.role() != "owner":
        raise AccessDenied("Only an owner can change an owner.")
    if role is not None and role not in ROLES:
        raise ValueError(f"Role is one of {', '.join(ROLES)}.")
    if role == "owner" and lens.role() != "owner":
        raise AccessDenied("Only an owner can make another owner.")
    demoting = (role is not None and role not in ("owner", "admin")) or disabled
    if demoting and t["role"] in ("owner", "admin") and _owners_left(lens, user_id) == 0:
        raise ValueError("Keep at least one active administrator.")
    if disabled is False and t["disabled_at"] is not None:
        _seat_check(lens)
    changes = {}
    with lens.db.transaction():
        if role is not None and role != t["role"]:
            lens.db.execute("UPDATE memberships SET role=%s WHERE organization_id=%s AND user_id=%s", (role, lens.org, user_id))
            changes["role"] = [t["role"], role]
        if disabled is not None and disabled != (t["disabled_at"] is not None):
            lens.db.execute("UPDATE users SET disabled_at=%s WHERE id=%s", (datetime.now(timezone.utc) if disabled else None, user_id))
            if disabled:
                lens.db.execute("DELETE FROM web_sessions WHERE user_id=%s", (user_id,))
            changes["disabled"] = disabled
        if name is not None and name.strip() and name != t["name"]:
            lens.db.execute("UPDATE users SET name=%s WHERE id=%s", (name.strip(), user_id))
            changes["name"] = [t["name"], name.strip()]
        if email is not None and email != (t["email"] or ""):
            lens.db.execute("UPDATE users SET email=%s WHERE id=%s", (email.strip(), user_id))
            changes["email"] = True
        if changes:
            lens._audit("update_user", "user", user_id, {"login": t["login"], **changes})


def set_password(lens: FinancialLens, user_id: str, password: str, current: Optional[str] = None) -> None:
    """An administrator resets anyone's password; a person changes their own with the current one."""
    t = _target(lens, user_id)
    own = str(lens.user_id) == str(user_id)
    if own:
        if t["password_hash"] and not check_password(current or "", t["password_hash"]):
            raise LoginError("The current password is wrong.")
    else:
        lens.authorize("admin")
        if t["role"] == "owner" and lens.role() != "owner":
            raise AccessDenied("Only an owner can reset an owner's password.")
    _check_new_password(password, t["login"])
    with lens.db.transaction():
        lens.db.execute("UPDATE users SET password_hash=%s WHERE id=%s", (hash_password(password), user_id))
        lens.db.execute("DELETE FROM web_sessions WHERE user_id=%s", (user_id,))
        lens._audit("password_change" if own else "password_reset", "user", user_id, {"login": t["login"]})


# --------------------------------------------------------------------------- sign-in
class _Throttle:
    """At most 5 failed sign-ins per login and per address in 10 minutes."""

    def __init__(self, limit: int = 5, window: float = 600) -> None:
        self.limit, self.window, self.fails, self.lock = limit, window, {}, threading.Lock()

    def blocked(self, *keys: str) -> bool:
        now = time.monotonic()
        with self.lock:
            return any(len([t for t in self.fails.get(k, []) if now - t < self.window]) >= self.limit for k in keys)

    def fail(self, *keys: str) -> None:
        now = time.monotonic()
        with self.lock:
            for k in keys:
                self.fails[k] = [t for t in self.fails.get(k, []) if now - t < self.window] + [now]

    def clear(self, *keys: str) -> None:
        with self.lock:
            for k in keys:
                self.fails.pop(k, None)


throttle = _Throttle()


def _new_session(lens: FinancialLens, user_id: str, via: str, ip: str, agent: str) -> tuple[str, str]:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    with lens.db.transaction():
        lens.db.execute("DELETE FROM web_sessions WHERE expires_at < now() OR last_seen_at < %s", (now - SESSION_IDLE,))
        lens.db.execute("INSERT INTO web_sessions (token_sha256, user_id, organization_id, csrf, via, ip, user_agent, expires_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (hashlib.sha256(token.encode()).hexdigest(), user_id, lens.org,
                                                             csrf, via, ip[:64], agent[:200], now + SESSION_MAX))
        lens.db.execute("UPDATE users SET last_login_at=now() WHERE id=%s", (user_id,))
    return token, csrf


def login(lens: FinancialLens, login_name: str, password: str, ip: str = "", agent: str = "") -> tuple[str, str, dict]:
    keys = ("login:" + login_name.casefold(), "ip:" + ip)
    if throttle.blocked(*keys):
        raise LoginError("Too many failed attempts. Wait 10 minutes and try again.")
    row = lens.db.execute("SELECT u.*, m.role FROM users u JOIN memberships m ON m.user_id=u.id "
                          "WHERE lower(u.login)=lower(%s) AND m.organization_id=%s", (login_name.strip(), lens.org)).fetchone()
    ok = check_password(password, row["password_hash"] if row else _dummy_hash()) and row is not None
    if not ok or row["disabled_at"] is not None:
        throttle.fail(*keys)
        with lens.db.transaction():
            lens._audit("login_failed", "user", str(row["id"]) if row else "", {"login": login_name[:64], "ip": ip,
                        "reason": "disabled" if ok else "wrong login or password"}, actor="anonymous")
        raise LoginError("Wrong login or password." if not ok else "This account is disabled.")
    throttle.clear(*keys)
    token, csrf = _new_session(lens, str(row["id"]), "password", ip, agent)
    with lens.db.transaction():
        lens._audit("login", "user", str(row["id"]), {"login": row["login"], "ip": ip}, actor=f"user:{row['id']}")
    return token, csrf, {"id": str(row["id"]), "login": row["login"], "name": row["name"], "role": row["role"]}


def sso_session(lens: FinancialLens, identity: str, ip: str = "", agent: str = "") -> Optional[tuple[str, str, dict]]:
    """A person the company's sign-on proxy vouched for (by login or e-mail). Only known, active users."""
    row = lens.db.execute("SELECT u.*, m.role FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.organization_id=%s "
                          "AND u.disabled_at IS NULL AND (lower(u.login)=lower(%s) OR lower(u.email)=lower(%s))",
                          (lens.org, identity, identity)).fetchone()
    if not row:
        with lens.db.transaction():
            lens._audit("login_failed", "user", "", {"login": identity[:64], "ip": ip, "reason": "unknown SSO user"},
                        actor="sso")
        return None
    token, csrf = _new_session(lens, str(row["id"]), "sso", ip, agent)
    with lens.db.transaction():
        lens._audit("login", "user", str(row["id"]), {"login": row["login"], "ip": ip, "via": "sso"}, actor=f"user:{row['id']}")
    return token, csrf, {"id": str(row["id"]), "login": row["login"], "name": row["name"], "role": row["role"]}


def session_user(lens: FinancialLens, token: str) -> Optional[dict]:
    if not token:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = lens.db.execute(
        "SELECT s.csrf, s.last_seen_at, s.via, u.id, u.login, u.name, m.role FROM web_sessions s JOIN users u ON u.id=s.user_id "
        "JOIN memberships m ON m.user_id=u.id AND m.organization_id=s.organization_id WHERE s.token_sha256=%s "
        "AND s.organization_id=%s AND s.expires_at > now() AND s.last_seen_at > now() - %s AND u.disabled_at IS NULL",
        (digest, lens.org, SESSION_IDLE)).fetchone()
    if not row:
        return None
    if datetime.now(timezone.utc) - row["last_seen_at"] > timedelta(minutes=1):
        lens.db.execute("UPDATE web_sessions SET last_seen_at=now() WHERE token_sha256=%s", (digest,))
    return {"id": str(row["id"]), "login": row["login"], "name": row["name"], "role": row["role"], "csrf": row["csrf"],
            "via": row["via"]}


def logout(lens: FinancialLens, token: str) -> None:
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = lens.db.execute("DELETE FROM web_sessions WHERE token_sha256=%s RETURNING user_id", (digest,)).fetchone()
    if row:
        with lens.db.transaction():
            lens._audit("logout", "user", str(row["user_id"]), {}, actor=f"user:{row['user_id']}")


# --------------------------------------------------------------------------- first administrator
def setup_code(data_dir) -> Optional[str]:
    """A one-time code that lets the first administrator be created in the browser. Printed to the console."""
    from pathlib import Path

    p = Path(data_dir) / "setup-code"
    if p.exists():
        return p.read_text().strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    code = "-".join(secrets.token_hex(2).upper() for _ in range(4))
    p.write_text(code)
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return code


def bootstrap_admin(lens: FinancialLens, data_dir, code: str, login: str, name: str, password: str) -> str:
    from pathlib import Path

    p = Path(data_dir) / "setup-code"
    if has_logins(lens):
        raise AccessDenied("The first administrator already exists; ask them for an account.")
    if not p.exists() or not hmac.compare_digest(code.strip().upper(), p.read_text().strip()):
        raise LoginError("Wrong setup code. It is printed in the server's console and log at start.")
    uid = create_user(lens, login, name, "owner", password, bootstrap=True)
    p.unlink(missing_ok=True)
    return uid


# --------------------------------------------------------------------------- audit log
def audit(lens: FinancialLens, limit: int = 300, before: Optional[int] = None, actor: str = "", action: str = "") -> dict:
    lens.authorize("admin")
    q = ["a.organization_id=%s"]
    args: list = [lens.org]
    if before:
        q.append("a.id < %s")
        args.append(before)
    if actor:
        q.append("(a.actor=%s OR u.login ILIKE %s OR u.name ILIKE %s)")
        args += [actor, f"%{actor}%", f"%{actor}%"]
    if action:
        q.append("a.action=%s")
        args.append(action)
    rows = lens.db.execute(
        "SELECT a.id, a.at, a.actor, a.action, a.entity, a.entity_id, a.details, u.name AS actor_name, u.login AS actor_login "
        "FROM audit_log a LEFT JOIN users u ON a.actor = 'user:' || u.id::text WHERE " + " AND ".join(q) +
        " ORDER BY a.id DESC LIMIT %s", (*args, min(limit, 1000))).fetchall()
    actions = [r["action"] for r in lens.db.execute(
        "SELECT DISTINCT action FROM audit_log WHERE organization_id=%s ORDER BY action", (lens.org,)).fetchall()]
    return {"entries": [lens._json(r) for r in rows], "actions": actions, "chain": lens.verify_audit_chain()}


def can(role: str, action: str) -> bool:
    return action in PERMISSIONS.get(role, set())
