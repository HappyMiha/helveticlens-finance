"""Content-addressed storage for original documents.

Originals are written once, named by their SHA-256 and made read-only. They are
never moved or rewritten: the folder a user sees (§5) is a virtual path in the
database, so reorganising never touches the file or breaks a link.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path


class IntegrityError(RuntimeError):
    pass


class OriginalStore:
    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o750)  # originals are not readable by other users of this machine
        except PermissionError:
            pass

    def _path(self, sha256: str) -> Path:
        return self.root / sha256[:2] / sha256[2:4] / sha256

    def put(self, data: bytes) -> tuple[str, str]:
        """Store bytes; returns (sha256, storage_key). Idempotent."""
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        if path.exists():
            self.verify(digest)
            return digest, str(path.relative_to(self.root))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        path.chmod(stat.S_IRUSR | stat.S_IRGRP)
        return digest, str(path.relative_to(self.root))

    def get(self, sha256: str) -> bytes:
        data = self._path(sha256).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise IntegrityError(f"Original {sha256} does not match its checksum.")
        return data

    def verify(self, sha256: str) -> bool:
        self.get(sha256)
        return True

    def verify_all(self) -> list[str]:
        """Return the checksums of originals that fail verification."""
        bad = []
        for path in self.root.glob("*/*/*"):
            if path.suffix == ".part":
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != path.name:
                bad.append(path.name)
        return bad
