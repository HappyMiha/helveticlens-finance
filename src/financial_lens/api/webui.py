"""The local web interface: served by the Financial Lens service on 127.0.0.1 only.

Security for a service on localhost:
  * Host header must be this machine (127.0.0.1 / localhost) — blocks DNS rebinding.
  * Every request needs the session cookie (or the bearer key for scripts). The key is random, kept in
    the user's own profile, and handed to the browser once through the launch URL fragment.
  * Changes need a matching CSRF header, so no other web page can submit forms to the service.
  * Phones never use this; they reach only /mobile/v1 with their signed requests.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
from importlib import resources
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from ..service import FinancialLens

COOKIE = "fl_session"
OPEN_PATHS = ("/ui/session", "/health", "/ui/edition")
STATIC = Path(str(resources.files("financial_lens") / "webui"))


class Settings:
    edition = "personal"  # "corporate": many people sign in on one office server (api/corporate.py)
    require_auth = False  # switched on by the service launcher
    key: Optional[str] = None
    allowed_hosts: set[str] = {"127.0.0.1", "localhost", "[::1]"}


def load_key(data_dir: Path) -> str:
    p = data_dir / "ui-key"
    if p.exists():
        return p.read_text().strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(32)
    p.write_text(key)
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return key


def csrf_for(key: str) -> str:
    return hmac.new(key.encode(), b"csrf", "sha256").hexdigest()[:32]


async def guard(request: Request, call_next):
    if not Settings.require_auth:
        return await call_next(request)
    path = request.url.path
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if path == "/m" or path.startswith(("/m/", "/mobile/v1/")):
        return await call_next(request)  # phone endpoints have their own protection
    if host not in Settings.allowed_hosts:
        return JSONResponse({"detail": "This service answers only on this computer."}, status_code=403)
    if path.startswith(OPEN_PATHS) or path in ("/", "/ui", "/ui/") or path.startswith("/ui/static/"):
        return await call_next(request)
    key = Settings.key or ""
    token = request.cookies.get(COOKIE) or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token, key):
        return JSONResponse({"detail": "Open Financial Lens from its own window or tray icon."}, status_code=401)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.cookies.get(COOKIE):
        if not hmac.compare_digest(request.headers.get("x-fl-csrf", ""), csrf_for(key)):
            return JSONResponse({"detail": "Request blocked (CSRF)."}, status_code=403)
    return await call_next(request)


def _fingerprint(name: str) -> str:
    import hashlib

    return hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:10]


class SessionIn(BaseModel):
    key: str


def make_router(get_lens) -> APIRouter:
    r = APIRouter()

    @r.get("/", include_in_schema=False)
    @r.get("/ui", include_in_schema=False)
    @r.get("/ui/", include_in_schema=False)
    def index() -> HTMLResponse:
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for name in ("app.js", "app.css", "tokens.css"):  # a new version is never hidden by the browser cache
            html = html.replace(f"/ui/static/{name}", f"/ui/static/{name}?v={_fingerprint(name)}")
        return HTMLResponse(html,
                            headers={"Cache-Control": "no-store",
                                     "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; "
                                     "style-src 'self'; script-src 'self'; frame-ancestors 'none'; form-action 'none'"})

    @r.get("/ui/static/{name}", include_in_schema=False)
    def static(name: str) -> Response:
        p = (STATIC / name).resolve()
        if p.parent != STATIC.resolve() or not p.exists():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "no-cache"})

    @r.post("/ui/session")
    def session(body: SessionIn) -> Response:
        if not Settings.key or not hmac.compare_digest(body.key, Settings.key):
            raise HTTPException(401, "Wrong key.")
        resp = JSONResponse({"csrf": csrf_for(Settings.key)})
        resp.set_cookie(COOKIE, Settings.key, httponly=True, samesite="strict", secure=False, path="/")
        return resp

    @r.get("/ui/me")
    def me(request: Request, fl: FinancialLens = Depends(get_lens)) -> dict:
        from .. import privacy

        out = {"csrf": csrf_for(Settings.key) if Settings.key else "", "org": fl.org,
               "organizations": fl.organizations(), "privacy": fl.privacy_level(),
               "network_guard": privacy.guard_active(), "ai_assist": fl.ai_assist(), "edition": Settings.edition}
        if Settings.edition == "corporate":
            from .. import licensing

            user = getattr(request.state, "fl_user", None) or {}
            lic = licensing.status(fl)
            out.update(csrf=user.get("csrf", ""), user={k: user.get(k) for k in ("id", "login", "name", "role", "via")},
                       organizations=[o for o in out["organizations"] if o["id"] == fl.org],
                       license={"state": lic.state, "writable": lic.writable, "days_left": lic.days_left,
                                "message": lic.message, "trial_ends": lic.trial_ends, "expires": lic.expires})
        return out

    # ----------------------------------------------------------- phone pairing
    @r.post("/ui/pair-phone")
    def pair_phone(fl: FinancialLens = Depends(get_lens)) -> dict:
        import io

        fl.authorize("configure")
        import qrcode
        import qrcode.image.svg

        from . import mobile_v1
        from .mobile import lan_address

        port, fp = start_phone_server(fl)
        offer = mobile_v1.create_offer(fl, f"{lan_address()}:{port}", fp, ("upload", "read", "review"))
        buf = io.BytesIO()
        qrcode.make(offer["uri"], image_factory=qrcode.image.svg.SvgPathImage, box_size=8).save(buf)
        app_buf = io.BytesIO()
        qrcode.make("https://github.com/HappyMiha/helveticlens-finance/releases/latest/download/FinancialLens-Android.apk",
                    image_factory=qrcode.image.svg.SvgPathImage, box_size=8).save(app_buf)
        return {"pair_svg": buf.getvalue().decode(), "app_svg": app_buf.getvalue().decode(),
                "expires_at": offer["expires_at"]}

    @r.get("/ui/phones")
    def phones(fl: FinancialLens = Depends(get_lens)) -> list[dict]:
        from . import mobile_v1

        return mobile_v1.devices(fl)

    @r.delete("/ui/phones/{device_id}")
    def revoke_phone(device_id: str, fl: FinancialLens = Depends(get_lens)) -> dict:
        from . import mobile_v1

        mobile_v1.revoke(fl, device_id)
        return {"status": "revoked"}

    # ---------------------------------------------------------------- local AI
    @r.get("/ui/ai")
    def ai_status(fl: FinancialLens = Depends(get_lens)) -> dict:
        from ..ai import local_model

        return {**local_model.status(), "enabled": fl.ai_assist(), "progress": _ai_job}

    @r.post("/ui/ai/install")
    def ai_install() -> dict:
        from ..ai import local_model

        if _ai_job.get("running"):
            return _ai_job

        def work():
            _ai_job.update(running=True, error=None, label="Starting", frac=0.0)
            try:
                local_model.install(lambda l, f: _ai_job.update(label=l, frac=round(f, 4)), _ai_cancel)
                _ai_job.update(done=True)
            except Exception as exc:
                _ai_job.update(error=str(exc))
            finally:
                _ai_job.update(running=False)

        _ai_cancel.clear()
        threading.Thread(target=work, daemon=True).start()
        return {"running": True}

    @r.post("/ui/ai/cancel")
    def ai_cancel() -> dict:
        _ai_cancel.set()
        return {"status": "cancelling"}

    class Toggle(BaseModel):
        on: bool

    @r.post("/ui/ai/toggle")
    def ai_toggle(body: Toggle, fl: FinancialLens = Depends(get_lens)) -> dict:
        from ..ai import local_model

        fl.authorize("configure")
        if body.on:
            url = os.environ.get("FL_MODEL_URL") or local_model.start()
            if Settings.edition == "corporate":
                from . import app as api

                api.pool.each(lambda other: other.use_local_model(url, "apertus-8b"))
            fl.use_local_model(url, "apertus-8b")
        else:
            local_model.stop()
        if fl.ai is not None:
            fl.set_ai_assist(body.on)
        return {"enabled": fl.ai_assist()}

    return r


_ai_job: dict = {}
_ai_cancel = threading.Event()
_phone_server: dict = {}


def start_phone_server(fl: FinancialLens) -> tuple[int, str]:
    """HTTPS on the local network for paired phones (pinned certificate). Started on first use."""
    if _phone_server.get("port"):
        return _phone_server["port"], _phone_server["fp"]
    import sys

    import uvicorn

    from ..tls import ensure_certificate

    cert, key, fp = ensure_certificate(fl.files.root.parent / "tls")
    port = int(os.environ.get("FL_MOBILE_PORT", "8766"))
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stdout or open(os.devnull, "w")
        sys.stderr = sys.stderr or open(os.devnull, "w")
    config = uvicorn.Config("financial_lens.api.app:app", host="0.0.0.0", port=port, log_level="warning",
                            ssl_certfile=str(cert), ssl_keyfile=str(key), log_config=None)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    _phone_server.update(port=port, fp=fp, server=server)
    return port, fp
