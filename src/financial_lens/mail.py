"""Import documents from a mailbox (IMAP).

Forward invoices and receipts to a dedicated address; attachments (PDF,
images, XML, CSV/XLSX) and plain-text bodies become documents with the e-mail
as provenance. Each message is imported once (by Message-ID). Nothing is
deleted or marked on the server.

Privacy: in L2 (local only) only a mail server on this machine or the local
network is allowed — e.g. Proton Mail Bridge or Dovecot on 127.0.0.1. In L1/L0
any server you configure, over TLS. Credentials come from the environment
or config, never from the database.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

from .service import FinancialLens

ACCEPTED = {"application/pdf", "image/jpeg", "image/png", "image/heic", "image/heif", "image/tiff", "image/webp",
            "application/xml", "text/xml", "text/csv", "text/plain",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"}
EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp", ".xml", ".csv", ".xlsx", ".txt")
MAX_BYTES = 25 * 1024 * 1024


class MailError(RuntimeError):
    pass


@dataclass
class MailResult:
    messages: int = 0
    skipped: int = 0
    documents: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _host_is_local(host: str) -> bool:
    try:
        addrs = {i[4][0] for i in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    return all(ipaddress.ip_address(a.split("%")[0]).is_private or ipaddress.ip_address(a.split("%")[0]).is_loopback
               for a in addrs)


def fetch(lens: FinancialLens, host: str, user: str, password: str, folder: str = "INBOX", port: int = 993,
          allowed_senders: Optional[list[str]] = None, limit: int = 200,
          connect: Optional[Callable[[str, int], imaplib.IMAP4]] = None) -> MailResult:
    lens.authorize("write")
    level = lens.privacy_level()
    if level == "local_only" and connect is None and not _host_is_local(host):
        raise MailError(f"Local-only mode: {host} is not on this machine or the local network. "
                        "Use a local bridge (e.g. Proton Mail Bridge) or choose privacy level L1.")
    if connect is None:
        from . import privacy

        if privacy.guard_active():
            privacy._allowed_hosts.add(host)  # the user's own local mail server
        imap = imaplib.IMAP4_SSL(host, port) if port == 993 else imaplib.IMAP4(host, port)
        if port != 993:
            imap.starttls()
    else:
        imap = connect(host, port)
    mailbox = f"{user}@{host}/{folder}"
    result = MailResult()
    try:
        imap.login(user, password)
        imap.select(folder, readonly=True)
        typ, data = imap.search(None, "ALL")
        ids = data[0].split()[-limit:]
        for num in ids:
            typ, parts = imap.fetch(num, "(BODY.PEEK[])")
            raw = parts[0][1]
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            mid = (msg.get("Message-ID") or f"<no-id-{num.decode()}>").strip()
            if lens.db.execute("SELECT 1 FROM mail_messages WHERE organization_id=%s AND mailbox=%s AND message_id=%s",
                               (lens.org, mailbox, mid)).fetchone():
                result.skipped += 1
                continue
            sender = str(msg.get("From", ""))
            if allowed_senders and not any(a.casefold() in sender.casefold() for a in allowed_senders):
                result.notes.append(f"Ignored message from {sender}: not an allowed sender")
                _remember(lens, mailbox, mid, msg, 0)
                continue
            docs = _import_message(lens, msg, mailbox, result)
            _remember(lens, mailbox, mid, msg, len(docs))
            result.messages += 1
            result.documents.extend(docs)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    with lens.db.transaction():
        lens._audit("mail_import", "mailbox", mailbox, {"messages": result.messages, "documents": len(result.documents),
                                                        "skipped": result.skipped})
    return result


def _remember(lens, mailbox, mid, msg, n):
    try:
        when = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc) if msg.get("Date") else None
    except (TypeError, ValueError):
        when = None
    lens.db.execute("INSERT INTO mail_messages (organization_id, mailbox, message_id, sender, subject, received_at, documents) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (lens.org, mailbox, mid, str(msg.get("From", ""))[:300], str(msg.get("Subject", ""))[:300], when, n))


def _import_message(lens: FinancialLens, msg, mailbox: str, result: MailResult) -> list[str]:
    docs = []
    subject = str(msg.get("Subject", "")).strip() or "(no subject)"
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        ctype = part.get_content_type()
        if ctype not in ACCEPTED and not name.lower().endswith(EXTENSIONS):
            result.notes.append(f"Skipped {name}: {ctype} is not a supported document type")
            continue
        data = part.get_payload(decode=True) or b""
        if len(data) > MAX_BYTES:
            result.notes.append(f"Skipped {name}: larger than 25 MB")
            continue
        res = lens.ingest(data, name, None if ctype == "application/octet-stream" else ctype)
        docs.append(res.document_id)
        result.notes.extend(f"{name}: {m}" for m in res.messages)
    if not docs:  # an e-invoice or receipt in the body
        body = msg.get_body(preferencelist=("plain",))
        text = body.get_content() if body is not None else ""
        if text.strip():
            res = lens.ingest(f"{subject}\n{text}".encode(), f"{subject[:60]}.txt", "text/plain")
            docs.append(res.document_id)
            result.notes.extend(f"{subject}: {m}" for m in res.messages)
    for d in docs:
        lens.db.execute("UPDATE documents SET received_by=%s WHERE id=%s AND received_by=%s",
                        (f"mail:{mailbox}", d, lens.actor))
    return docs
