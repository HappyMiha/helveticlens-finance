"""Corporate edition HTTP layer: sign-in, sessions, team, audit log and licence.

Turned on by `financial-lens server` (webui.Settings.edition = "corporate"). Then:
  * the service listens on the office network and every browser signs in with its own login;
  * each request runs as that person, with their role, on its own database connection;
  * a baseline rule per request (read for GET, write for changes, admin for the team, audit log and licence)
    sits in front of the checks the ledger itself makes;
  * after the trial, or when the licence ended, the ledger is read-only until a key is installed.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import re
from contextvars import ContextVar
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .. import corporate as C
from .. import licensing as L
from ..service import AccessDenied, FinancialLens

COOKIE = "fl_corp"
current_user: ContextVar[Optional[str]] = ContextVar("fl_current_user", default=None)


class Config:
    sso_header = os.environ.get("FL_SSO_HEADER", "")             # e.g. X-Forwarded-User (set by the sign-on proxy)
    sso_proxies = [p.strip() for p in os.environ.get("FL_SSO_TRUSTED_PROXIES", "127.0.0.1,::1").split(",") if p.strip()]
    allowed_hosts = {h.strip().lower() for h in os.environ.get("FL_ALLOWED_HOSTS", "").split(",") if h.strip()}
    secure_cookie = os.environ.get("FL_COOKIE_SECURE", "") == "1"
    data_dir = ""


# Paths anyone may open without signing in.
OPEN = ("/health", "/ui/static/", "/ui/login", "/ui/setup", "/ui/edition")
PAGES = ("/", "/ui", "/ui/")
# Changes still possible when the ledger is read-only (licence missing): signing in and out, passwords,
# the team (to get under the seat count) and the licence itself.
ALWAYS_WRITABLE = ("/ui/login", "/ui/logout", "/ui/setup", "/ui/password", "/ui/users", "/ui/license", "/export", "/ask")
ADMIN = ("/ui/users", "/ui/audit", "/ui/license", "/security/check", "/devices", "/mail/", "/ui/pair-phone", "/ui/phones",
         "/ui/ai/install", "/ui/ai/cancel", "/ui/ai/toggle")
READ_POSTS = ("/ask", "/ui/logout", "/ui/password")
MEMBER_OK = re.compile(r"^/(ui/me|ui/logout|ui/password|members/[0-9a-f-]+/statement)$")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _trusted_proxy(ip: str) -> bool:
    for p in Config.sso_proxies:
        try:
            if ipaddress.ip_address(ip) in ipaddress.ip_network(p, strict=False):
                return True
        except ValueError:
            continue
    return ip == "testclient" and "testclient" in Config.sso_proxies


def make_guard(pool):
    """The middleware: who is this, may they do this, is the ledger writable."""

    async def guard(request: Request, call_next):
        path, method = request.url.path, request.method
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
        if Config.allowed_hosts and host not in Config.allowed_hosts:
            return JSONResponse({"detail": "Unknown server name."}, status_code=403)
        if path in PAGES or path.startswith(OPEN):
            return await call_next(request)
        if path == "/m" or path.startswith(("/m/", "/mobile/v1/")):
            return await call_next(request)  # paired phones: signed requests, their own checks

        def identify():
            with pool.borrow(None) as fl:
                token = request.cookies.get(COOKIE) or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
                user = C.session_user(fl, token) if token else None
                new = None
                if user is None and Config.sso_header and _trusted_proxy(_client_ip(request)):
                    ident = request.headers.get(Config.sso_header, "").strip()
                    if ident:
                        made = C.sso_session(fl, ident, _client_ip(request), request.headers.get("user-agent", ""))
                        if made:
                            new = made[0]
                            user = C.session_user(fl, made[0])
                lic = L.status(fl)
                return user, new, lic

        user, new_token, lic = await run_in_threadpool(identify)
        if user is None:
            return JSONResponse({"detail": "Please sign in.", "login": True}, status_code=401)
        if method not in ("GET", "HEAD", "OPTIONS") and request.cookies.get(COOKIE) and not new_token:
            if not hmac.compare_digest(request.headers.get("x-fl-csrf", ""), user["csrf"]):
                return JSONResponse({"detail": "Request blocked (CSRF)."}, status_code=403)
        role = user["role"]
        if role == "member" and not MEMBER_OK.match(path):
            return JSONResponse({"detail": "Your role shows only your own statement."}, status_code=403)
        if path.startswith("/organizations/open"):
            return JSONResponse({"detail": "The corporate server keeps one organisation."}, status_code=403)
        if path.startswith(ADMIN) and not (path == "/ui/license" and method == "GET") and not C.can(role, "admin") \
                and not (path.startswith("/ui/ai") and C.can(role, "configure")):
            return JSONResponse({"detail": "Only administrators can do this."}, status_code=403)
        if method in ("GET", "HEAD") and role != "member" and not C.can(role, "read"):
            return JSONResponse({"detail": "Your role cannot read this ledger."}, status_code=403)
        if method not in ("GET", "HEAD", "OPTIONS"):
            if path == "/export" and not C.can(role, "export"):
                return JSONResponse({"detail": "Your role cannot export."}, status_code=403)
            if not path.startswith(READ_POSTS + ("/export", "/ui/users", "/ui/license")) and not C.can(role, "write"):
                return JSONResponse({"detail": "Your role can read but not change the ledger."}, status_code=403)
            if not lic.writable and not path.startswith(ALWAYS_WRITABLE):
                return JSONResponse({"detail": lic.message or "A licence key is needed.", "license": lic.state},
                                    status_code=402)
        request.state.fl_user = user
        tok = current_user.set(user["id"])
        try:
            response = await call_next(request)
        finally:
            current_user.reset(tok)
        if new_token:
            _set_cookie(response, new_token)
        return response

    return guard


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=Config.secure_cookie, path="/",
                    max_age=int(C.SESSION_MAX.total_seconds()))


class LoginIn(BaseModel):
    login: str
    password: str


class SetupIn(BaseModel):
    code: str
    login: str
    name: str
    password: str


class UserIn(BaseModel):
    login: str
    name: str
    role: str = "viewer"
    email: str = ""
    password: str


class UserPatch(BaseModel):
    role: Optional[str] = None
    disabled: Optional[bool] = None
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None


class PasswordIn(BaseModel):
    current: str = ""
    password: str


class KeyIn(BaseModel):
    key: str


def _fail(exc: Exception):
    if isinstance(exc, (AccessDenied,)):
        raise HTTPException(403, str(exc))
    if isinstance(exc, C.LoginError):
        raise HTTPException(401, str(exc))
    if isinstance(exc, LookupError):
        raise HTTPException(404, str(exc))
    if isinstance(exc, (ValueError, L.LicenseError)):
        raise HTTPException(422, str(exc))
    raise exc


def _corporate_only() -> None:
    from . import webui

    if webui.Settings.edition != "corporate":
        raise HTTPException(404)


def make_router(get_lens, pool) -> APIRouter:
    from . import webui

    r = APIRouter(dependencies=[Depends(_corporate_only)])
    open_r = APIRouter()

    @open_r.get("/ui/edition")
    def edition() -> dict:
        if webui.Settings.edition != "corporate":
            return {"edition": webui.Settings.edition}
        with pool.borrow(None) as fl:
            return {"edition": "corporate", "needs_setup": not C.has_logins(fl), "sso": bool(Config.sso_header)}

    @r.post("/ui/login")
    def do_login(body: LoginIn, request: Request) -> Response:
        with pool.borrow(None) as fl:
            try:
                token, csrf, user = C.login(fl, body.login, body.password, _client_ip(request),
                                            request.headers.get("user-agent", ""))
            except C.LoginError as exc:
                raise HTTPException(401, str(exc))
        resp = JSONResponse({"csrf": csrf, "user": user})
        _set_cookie(resp, token)
        return resp

    @r.post("/ui/setup")
    def setup(body: SetupIn, request: Request) -> Response:
        with pool.borrow(None) as fl:
            try:
                C.bootstrap_admin(fl, Config.data_dir, body.code, body.login, body.name, body.password)
                token, csrf, user = C.login(fl, body.login, body.password, _client_ip(request),
                                            request.headers.get("user-agent", ""))
            except Exception as exc:
                _fail(exc)
        resp = JSONResponse({"csrf": csrf, "user": user})
        _set_cookie(resp, token)
        return resp

    @r.post("/ui/logout")
    def do_logout(request: Request) -> Response:
        with pool.borrow(None) as fl:
            C.logout(fl, request.cookies.get(COOKIE, ""))
        resp = JSONResponse({"status": "signed out"})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @r.post("/ui/password")
    def password(body: PasswordIn, fl: FinancialLens = Depends(get_lens)) -> dict:
        try:
            C.set_password(fl, str(fl.user_id), body.password, body.current)
        except Exception as exc:
            _fail(exc)
        return {"status": "changed; sign in again"}

    # ------------------------------------------------------------------ team
    @r.get("/ui/users")
    def list_users(fl: FinancialLens = Depends(get_lens)) -> dict:
        lic = L.status(fl)
        return {"users": C.users(fl), "roles": [{"id": k, "label": v} for k, v in C.ROLE_LABELS.items()],
                "seats": lic.seats, "active": lic.users, "me": str(fl.user_id)}

    @r.post("/ui/users")
    def add_user(body: UserIn, fl: FinancialLens = Depends(get_lens)) -> dict:
        try:
            return {"id": C.create_user(fl, body.login, body.name, body.role, body.password, body.email)}
        except Exception as exc:
            _fail(exc)

    @r.patch("/ui/users/{user_id}")
    def patch_user(user_id: str, body: UserPatch, fl: FinancialLens = Depends(get_lens)) -> dict:
        try:
            C.update_user(fl, user_id, body.role, body.disabled, body.name, body.email)
            if body.password:
                C.set_password(fl, user_id, body.password)
        except Exception as exc:
            _fail(exc)
        return {"status": "ok"}

    # ------------------------------------------------------------- audit log
    @r.get("/ui/audit")
    def audit(limit: int = 300, before: Optional[int] = None, actor: str = "", action: str = "",
              fl: FinancialLens = Depends(get_lens)) -> dict:
        return C.audit(fl, limit, before, actor, action)

    @r.get("/ui/audit.csv")
    def audit_csv(fl: FinancialLens = Depends(get_lens)) -> Response:
        import csv
        import io
        import json

        fl.authorize("admin")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "at", "actor", "login", "action", "entity", "entity_id", "details"])
        before = None
        while True:
            page = C.audit(fl, 1000, before)["entries"]
            for e in page:
                w.writerow([e["id"], e["at"], e["actor_name"] or e["actor"], e["actor_login"] or "", e["action"],
                            e["entity"], e["entity_id"], json.dumps(e["details"], ensure_ascii=False)])
            if len(page) < 1000:
                break
            before = page[-1]["id"]
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="financial-lens-audit.csv"'})

    # ---------------------------------------------------------------- licence
    @r.get("/ui/license")
    def license_status(fl: FinancialLens = Depends(get_lens)) -> dict:
        st = L.status(fl).__dict__
        if C.can(fl.role(), "admin"):
            st["request"] = L.request_code(fl)
        return st

    @r.post("/ui/license")
    def license_install(body: KeyIn, fl: FinancialLens = Depends(get_lens)) -> dict:
        try:
            L.install_key(fl, body.key)
        except Exception as exc:
            _fail(exc)
        return L.status(fl).__dict__

    open_r.include_router(r)
    return open_r
