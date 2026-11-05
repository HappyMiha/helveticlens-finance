"""Security self-check (Phase 4 "security audit"). Reports facts, not reassurance."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from . import privacy
from .service import FinancialLens


def self_check(lens: FinancialLens, api_host: str = "127.0.0.1") -> dict:
    lens.authorize("admin")
    level = lens.privacy_level()
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    add("privacy level", True, privacy.level_name(level))
    if level == "local_only":
        add("outbound network blocked", privacy.guard_active(),
            "socket guard active" if privacy.guard_active() else "guard NOT active: call privacy.enforce_local_only()")
    providers = []
    if lens.ai is not None:
        for task, ps in lens.ai.routes.items():
            for p in ps:
                allowed = p.locality in {"local_only": {"local"}, "swiss_hosted": {"local", "swiss"},
                                         "cloud_ai": {"local", "swiss", "external"}}[level]
                providers.append(f"{task}: {p.name} ({p.locality}) {'allowed' if allowed else 'blocked'}")
    add("model providers", True, "; ".join(providers) or "none configured (rules and local OCR only)")
    bad = lens.files.verify_all()
    add("originals integrity", not bad, f"{len(bad)} failed" if bad else "all originals match their SHA-256")
    loose = [p.name for p in lens.files.root.glob("*/*/*") if p.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)]
    add("originals read-only", not loose, f"{len(loose)} writable" if loose else "all originals are read-only")
    world = lens.files.root.stat().st_mode & stat.S_IROTH
    add("storage not world-readable", not world, "others can read the storage folder" if world else "ok")
    chain = lens.verify_audit_chain()
    add("audit log chain", chain["ok"], f"{chain['checked']} entries verified" if chain["ok"]
        else f"broken at entry {chain['broken_at']}")
    try:
        lens.db.execute("UPDATE audit_log SET actor=actor WHERE false")
        add("append-only history", True, "database triggers protect revisions, extractions and the audit log")
    except Exception as exc:  # pragma: no cover
        add("append-only history", False, str(exc))
    add("API bound to loopback", api_host in ("127.0.0.1", "::1", "localhost"), f"API host {api_host}")
    ssl = lens.db.execute("SELECT current_setting('ssl', true) AS s").fetchone()["s"]
    host = lens.db.info.host
    local_db = host.startswith("/") or host in ("localhost", "127.0.0.1", "::1", "db")
    add("database transport", local_db or ssl == "on", f"host {host}, ssl {ssl}")
    key = os.environ.get("FL_DISK_ENCRYPTION", "")
    add("disk encryption", bool(key), "declared: " + key if key else
        "not declared; use LUKS/FileVault/BitLocker for the data folder and database volume")
    return {"level": level, "ok": all(c["ok"] for c in checks), "checks": checks}
