"""Embedded PostgreSQL for the desktop installers.

The packaged app starts its own private PostgreSQL in the user's data folder
(binaries come with the `pgserver` wheel), so nothing has to be installed and
no port is opened: on Linux and macOS it listens on a Unix socket only, on
Windows on 127.0.0.1. SQLite is not used (§12).
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

_server = None


def data_dir() -> Path:
    if os.environ.get("FL_DATA"):
        return Path(os.environ["FL_DATA"]).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FinancialLens"
    if os.uname().sysname == "Darwin":
        return Path.home() / "Library" / "Application Support" / "FinancialLens"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "FinancialLens"


def _uri_to_dsn(uri: str) -> str:
    u = urlparse(uri)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    parts = {"dbname": (u.path or "/postgres").lstrip("/") or "postgres", "user": unquote(u.username or "postgres")}
    if u.password:
        parts["password"] = unquote(u.password)
    host = q.get("host") or u.hostname
    if host:
        parts["host"] = host
    if u.port:
        parts["port"] = str(u.port)
    return " ".join(f"{k}={v}" for k, v in parts.items())


def dsn() -> str:
    """FL_DSN if set (own PostgreSQL), otherwise the embedded server."""
    if os.environ.get("FL_DSN"):
        return os.environ["FL_DSN"]
    global _server
    if _server is None:
        import pgserver

        root = data_dir() / "postgres"
        root.parent.mkdir(parents=True, exist_ok=True)  # initdb creates the cluster directory itself
        try:
            _server = pgserver.get_server(str(root), cleanup_mode="stop")
        except Exception as exc:  # make the database's own message visible
            import subprocess

            detail = ""
            for attr in ("stderr", "stdout", "output"):
                if getattr(exc, attr, None):
                    detail += str(getattr(exc, attr))[-1500:]
            log = root / "log" if (root / "log").exists() else None
            if log:
                detail += "".join(p.read_text(errors="replace")[-800:] for p in log.glob("*"))
            raise RuntimeError(f"Embedded PostgreSQL could not start: {exc}\n{detail}") from exc
        # Create the database with psycopg, not pgserver's psql helper: that one runs through a shell
        # and breaks on paths with spaces (e.g. "Financial Lens.app").
        import psycopg

        with psycopg.connect(_uri_to_dsn(_server.get_uri("postgres")), autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname='financial_lens'").fetchone():
                conn.execute("CREATE DATABASE financial_lens")
    return _uri_to_dsn(_server.get_uri("financial_lens"))
