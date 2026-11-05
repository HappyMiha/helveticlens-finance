"""Privacy levels as real operating modes (§8) and the outbound network guard.

  L0 minimal   (cloud_ai)      external AI and cloud services allowed, transparent and per document.
  L1 moderate  (swiss_hosted)  local data; Swiss-hosted providers; external only with per-document consent.
  L2 maximum   (local_only)    no outbound connections at all; local OCR, models, database and storage.

In L2 the guard is enforced at the socket level for this process, so a bug
or a misconfigured provider cannot leak data: only loopback and Unix
sockets (local PostgreSQL, a local model server) are reachable.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from contextlib import contextmanager
from typing import Iterable, Optional

LEVELS = {"L0": "cloud_ai", "L1": "swiss_hosted", "L2": "local_only"}
_original_connect = socket.socket.connect
_original_create = socket.create_connection
_original_getaddrinfo = socket.getaddrinfo
_allowed_hosts: set[str] = set()
_active = False


class NetworkBlocked(ConnectionRefusedError):
    pass


def _is_local(host) -> bool:
    if isinstance(host, (bytes, bytearray)):
        host = host.decode()
    host = str(host)
    if host in _allowed_hosts or host in ("localhost", "") or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _guarded_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
        raise NetworkBlocked(f"Local-only mode: outbound connection to {address[0]} blocked")
    return _original_connect(self, address)


def _guarded_create(address, *args, **kwargs):
    if not _is_local(address[0]):
        raise NetworkBlocked(f"Local-only mode: outbound connection to {address[0]} blocked")
    return _original_create(address, *args, **kwargs)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host is not None and not _is_local(host):
        raise NetworkBlocked(f"Local-only mode: name lookup for {host} blocked")
    return _original_getaddrinfo(host, *args, **kwargs)


def enforce_local_only(extra_local_hosts: Iterable[str] = ()) -> None:
    """Block every non-loopback connection from this process (L2).

    extra_local_hosts: names that resolve to this machine or an isolated local
    network, e.g. the PostgreSQL container name "db" in an internal Docker network.
    """
    global _active
    _allowed_hosts.update(extra_local_hosts)
    socket.socket.connect = _guarded_connect
    socket.create_connection = _guarded_create
    socket.getaddrinfo = _guarded_getaddrinfo
    _active = True


def release() -> None:
    global _active
    socket.socket.connect = _original_connect
    socket.create_connection = _original_create
    socket.getaddrinfo = _original_getaddrinfo
    _allowed_hosts.clear()
    _active = False


def guard_active() -> bool:
    return _active


@contextmanager
def local_only(extra_local_hosts: Iterable[str] = ()):
    enforce_local_only(extra_local_hosts)
    try:
        yield
    finally:
        release()


# ------------------------------------------------------------- redaction
_PATTERNS = [
    (re.compile(r"\b(?:CH|LI)\d{2}(?:\s?[0-9A-Z]{4}){4}\s?[0-9A-Z]\b"), "[IBAN]"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){3,7}(?:\s?[0-9A-Z]{1,4})?\b"), "[IBAN]"),
    (re.compile(r"\b\d{2}(?:\s?\d{5}){5}\b"), "[QR-REFERENCE]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?:\+41|0041|\b0)\s?(?:\d{2})\s?\d{3}\s?\d{2}\s?\d{2}\b"), "[PHONE]"),
    (re.compile(r"\b756\.\d{4}\.\d{4}\.\d{2}\b"), "[AHV]"),
    (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[CARD]"),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Remove identifiers before text may leave the machine (§17.10)."""
    found = []
    for pattern, label in _PATTERNS:
        if pattern.search(text):
            found.append(label)
            text = pattern.sub(label, text)
    return text, found


def level_name(level: str) -> str:
    return {"cloud_ai": "L0 minimal", "swiss_hosted": "L1 moderate", "local_only": "L2 maximum"}[level]


def resolve(level: str) -> str:
    level = LEVELS.get(level, level)
    if level not in ("cloud_ai", "swiss_hosted", "local_only"):
        raise ValueError(f"Unknown privacy level {level!r}")
    return level


def document_may_leave(org_level: str, document_privacy: Optional[str], provider_locality: str) -> bool:
    """Per-document control (§8 L1): the stricter of the workspace level and the document's own setting wins."""
    order = {"local_only": 0, "swiss_hosted": 1, "cloud_ai": 2}
    effective = min(order[org_level], order.get(document_privacy or "local_only", 0))
    allowed = {0: {"local"}, 1: {"local", "swiss"}, 2: {"local", "swiss", "external"}}[effective]
    return provider_locality in allowed


@contextmanager
def download_window():
    """Temporarily allow outbound connections for a download the person started (model or runtime).
    In local-only mode the guard is restored immediately afterwards; documents are never sent."""
    was_active = _active
    keep = set(_allowed_hosts)
    if was_active:
        release()
    try:
        yield
    finally:
        if was_active:
            enforce_local_only(keep)
