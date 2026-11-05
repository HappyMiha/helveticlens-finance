"""Encrypted backups and restore (§8 security, Phase 4).

A backup is the full archive (reports.export_archive) encrypted with
AES-256-GCM under a key derived from a passphrase with scrypt. The file can
be copied to any target (USB disk, NAS, a Swiss server) without exposing
content; tampering is detected on restore.

Format: b"FLBK1" | salt(16) | nonce(12) | ciphertext+tag
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional

from psycopg.types.json import Jsonb

from . import reports
from .service import FinancialLens

MAGIC = b"FLBK1"


class BackupError(RuntimeError):
    pass


def _key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode())


def encrypt(data: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(passphrase) < 12:
        raise BackupError("Use a passphrase of at least 12 characters.")
    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(MAGIC):
        raise BackupError("Not a Financial Lens backup.")
    salt, nonce, body = blob[5:21], blob[21:33], blob[33:]
    try:
        return AESGCM(_key(passphrase, salt)).decrypt(nonce, body, MAGIC)
    except InvalidTag as exc:
        raise BackupError("Wrong passphrase, or the backup was modified.") from exc


def create(lens: FinancialLens, target_dir: Path, passphrase: str) -> Path:
    lens.authorize("export")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "archive.zip"
        reports.export_archive(lens, archive)
        blob = encrypt(archive.read_bytes(), passphrase)
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / f"financial-lens-{date.today().isoformat()}-{lens.org[:8]}.flbk"
    tmp_out = out.with_suffix(".part")
    tmp_out.write_bytes(blob)
    os.replace(tmp_out, out)
    with lens.db.transaction():
        lens._audit("backup", "organization", lens.org, {"file": out.name, "bytes": len(blob)})
    return out


# Insert order respects foreign keys.
RESTORE_ORDER = ["categories", "projects", "accounts", "objects", "funds", "members", "documents", "extractions",
                 "operations", "operation_revisions", "document_operations", "links", "classification_rules",
                 "member_dues", "budgets", "allocations", "ai_activity"]


def restore(lens: FinancialLens, backup_file: Path, passphrase: str, new_name: Optional[str] = None) -> str:
    """Restore a backup into a new organisation in this database. Every file is checked
    against the manifest; originals are re-verified by checksum."""
    data = decrypt(backup_file.read_bytes(), passphrase)
    z = zipfile.ZipFile(io.BytesIO(data))
    manifest = json.loads(z.read("manifest.json"))
    import hashlib

    for name, digest in manifest["files"].items():
        if hashlib.sha256(z.read(name)).hexdigest() != digest:
            raise BackupError(f"{name} does not match the manifest.")
    tables = {n[5:-5]: json.loads(z.read(n)) for n in z.namelist() if n.startswith("data/") and n.endswith(".json")}
    org_rows = lens.db.execute("SELECT * FROM organizations WHERE id=%s", (manifest["organization_id"],)).fetchone()
    if org_rows:
        raise BackupError("This organisation already exists in this database; restore into a fresh database.")
    revisions = tables["operation_revisions"]
    ops = {r["operation_id"]: r for r in tables["operations_current"]}
    tables["operations"] = [{"id": oid, "organization_id": manifest["organization_id"], "kind": r["kind"],
                             "created_at": r["operation_created_at"]} for oid, r in ops.items()]
    with lens.db.transaction():
        org = tables["organizations"][0]
        lens.db.execute("INSERT INTO organizations (id, name, kind, base_currency) VALUES (%s,%s,%s,%s)",
                        (org["id"], new_name or org["name"], org["kind"], org["base_currency"]))
        cols_cache: dict[str, list[str]] = {}
        for table in RESTORE_ORDER:
            rows = revisions if table == "operation_revisions" else tables.get(table, [])
            if not rows:
                continue
            cols = cols_cache.setdefault(table, [r["column_name"] for r in lens.db.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name=%s AND table_schema=current_schema()",
                (table,)).fetchall()])
            if table == "categories":  # parents first
                rows = sorted(rows, key=lambda r: r["parent_id"] is not None)
            for r in rows:
                keys = [k for k in r if k in cols and not (table == "ai_activity" and k == "id")]
                values = [Jsonb(r[k]) if isinstance(r[k], (dict, list)) else r[k] for k in keys]
                lens.db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})", values)
        for d in tables["documents"]:
            name = next(n for n in z.namelist() if n.startswith("originals/") and f"/{d['id'][:8]}-" in n)
            sha, _ = lens.files.put(z.read(name))
            if sha != d["sha256"]:
                raise BackupError(f"Original {d['filename']} failed its checksum.")
        lens.org = manifest["organization_id"]
        lens._audit("restore", "organization", lens.org, {"from": backup_file.name, "files": len(manifest["files"])})
    return lens.org


def copy_to(backup: Path, destination: Path) -> Path:
    """Copy an encrypted backup to a mounted target (USB disk, NAS, SMB/SFTP mount of a Swiss server)."""
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / backup.name
    shutil.copy2(backup, target)
    if target.read_bytes() != backup.read_bytes():
        raise BackupError("Copy verification failed.")
    return target
