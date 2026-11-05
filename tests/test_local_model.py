"""The local model manager: checksums are enforced, downloads resume, nothing runs unverified."""

import hashlib
import http.server
import threading
from functools import partial

import pytest

from financial_lens.ai import local_model as L


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_download_verified_and_mismatch_deleted(server, tmp_path, monkeypatch):
    root, base = server
    data = b"model-bytes" * 1000
    (root / "m.gguf").write_bytes(data)
    monkeypatch.setenv("FL_DATA", str(tmp_path / "data"))
    good = tmp_path / "data" / "ok.gguf"
    L._fetch(f"{base}/m.gguf", good, len(data), hashlib.sha256(data).hexdigest(), "Model", None, threading.Event())
    assert good.read_bytes() == data
    bad = tmp_path / "data" / "bad.gguf"
    with pytest.raises(L.DownloadError, match="checksum"):
        L._fetch(f"{base}/m.gguf", bad, len(data), "0" * 64, "Model", None, threading.Event())
    assert not bad.exists() and not bad.with_suffix(".gguf.part").exists()


def test_status_requires_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("FL_DATA", str(tmp_path))
    p = L.model_path()
    p.parent.mkdir(parents=True)
    p.write_bytes(b"x")
    assert L.status()["model_installed"] is False  # present but never verified
    with pytest.raises(L.DownloadError):
        L.start()
