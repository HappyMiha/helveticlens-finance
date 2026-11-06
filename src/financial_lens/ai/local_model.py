"""Local AI on any computer: download once, verify, run on this machine only.

What is downloaded (only when the person asks for it):
  * the model — Apertus 8B Instruct (Swiss AI, Apache-2.0), 4-bit GGUF, about 5.1 GB, from Hugging Face,
    pinned to one repository commit and one SHA-256;
  * the runtime — llama.cpp's `llama-server` for this platform (Vulkan on Windows/Linux: NVIDIA, AMD and
    Intel graphics; Metal on Apple silicon; CPU otherwise), about 15–40 MB, from llama.cpp's GitHub
    release, pinned by SHA-256.
A file whose checksum does not match is deleted and never started. The server listens on 127.0.0.1 only
and stops with the app. Documents never leave the computer.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .. import local_db

LLAMA_TAG = "b12128"
RUNTIMES = {
    ("Windows", "AMD64"): ("llama-b12128-bin-win-vulkan-x64.zip", 37684327,
                           "9cc33cbbb4c124a5694d6eec0bd0ecb69db291085ebe0a535a573484be2845ba"),
    ("Linux", "x86_64"): ("llama-b12128-bin-ubuntu-vulkan-x64.tar.gz", 35884041,
                          "630d8e57080290005ec8df8126d324c7167ea4a4a8691919262a9ae7d0c5b210"),
    ("Darwin", "arm64"): ("llama-b12128-bin-macos-arm64.tar.gz", 16672024,
                          "b77c6b4c4a0217153a14cfc062b341622a07ec5726c8d302386d75749780be25"),
    ("Darwin", "x86_64"): ("llama-b12128-bin-macos-x64.tar.gz", 12411588,
                           "ae08827a63a9c20e1f99e9b39732d5791e710be6dd9deb12b2df76c71ee5855b"),
}


@dataclass(frozen=True)
class ModelSpec:
    key: str
    name: str
    file: str
    url: str
    size: int
    sha256: str
    licence: str
    ctx: int = 8192
    role: str = "helper"          # helper: asked when the rules are unsure · analyst: reads every document
    needs: str = "any computer (8 GB RAM); faster with a graphics card"


APERTUS_8B = ModelSpec(
    "apertus-8b", "Apertus 8B Instruct (Swiss AI)", "Apertus-8B-Instruct-2509-Q4_K_M.gguf",
    "https://huggingface.co/unsloth/Apertus-8B-Instruct-2509-GGUF/resolve/"
    "61c32783830424ac7a6d0fd80d4166e29dbaee06/Apertus-8B-Instruct-2509-Q4_K_M.gguf",
    5057885440, "87e7f0eb5a1d33e1a8ea4e7fdd2363764e0465061dd92962e0073aec31a7944d", "Apache-2.0")

# Apertus 1.5 (Swiss AI, 2026), text part, 8-bit: reads whole documents for the analyst mode. Checked with
# llama.cpp b12128 (model-check workflow). Its image input is not supported by llama.cpp yet.
APERTUS_15 = ModelSpec(
    "apertus-1.5-8b", "Apertus 1.5 8B (Swiss AI) · analyst", "apertus-v1.5-8b-text-q8_0.gguf",
    "https://huggingface.co/andreasmartin/apertus-v1.5-8b-text-Q8_0-GGUF/resolve/"
    "a39f7e04b541673750afecba224d3a3cf1f20862/apertus-v1.5-8b-text-q8_0.gguf",
    8567121856, "dea904ad80cd725ec89962abae464477f5d8114d1f4377514f381f7dc2ed202d", "Apache-2.0",
    ctx=16384, role="analyst", needs="a graphics card with 12 GB or more of video memory (16 GB recommended)")

MODELS = {m.key: m for m in (APERTUS_8B, APERTUS_15)}


class DownloadError(RuntimeError):
    pass


def folder() -> Path:
    return local_db.data_dir() / "ai"


def runtime_spec():
    key = (platform.system(), platform.machine().replace("aarch64", "arm64"))
    if key not in RUNTIMES:
        raise DownloadError(f"No local AI runtime for {key[0]} {key[1]} yet.")
    return RUNTIMES[key]


def server_binary() -> Optional[Path]:
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    hits = list((folder() / "runtime").rglob(exe))
    return hits[0] if hits else None


def selected() -> ModelSpec:
    """The model the person chose (Settings → Local AI); the smaller one unless they picked the analyst."""
    try:
        return MODELS.get((folder() / "model.txt").read_text().strip(), APERTUS_8B)
    except OSError:
        return APERTUS_8B


def select(key: str) -> ModelSpec:
    if key not in MODELS:
        raise DownloadError(f"Unknown model {key}.")
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / "model.txt").write_text(key)
    return MODELS[key]


def model_path(spec: Optional[ModelSpec] = None) -> Path:
    return folder() / "models" / (spec or selected()).file


def installed(spec: ModelSpec) -> bool:
    m = model_path(spec)
    return m.exists() and m.with_suffix(".verified").exists()


_gpu_cache: dict = {}


def gpu_info() -> Optional[dict]:
    """Best effort: the graphics card and its memory (NVIDIA through nvidia-smi). None if unknown."""
    if "v" in _gpu_cache:
        return _gpu_cache["v"]
    info = None
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10, creationflags=flags).stdout.strip()
            if out:
                name, mem = [x.strip() for x in out.splitlines()[0].split(",")[:2]]
                info = {"name": name, "vram_gb": round(int(mem) / 1024, 1)}
        except Exception:
            info = None
    _gpu_cache["v"] = info
    return info


def status(spec: Optional[ModelSpec] = None) -> dict:
    spec = spec or selected()
    gpu = gpu_info()
    return {"key": spec.key, "model": spec.name, "role": spec.role, "licence": spec.licence, "size_bytes": spec.size,
            "model_installed": installed(spec), "runtime_installed": server_binary() is not None,
            "folder": str(folder()), "gpu": gpu,
            "models": [{"key": m.key, "name": m.name, "role": m.role, "size_bytes": m.size, "needs": m.needs,
                        "installed": installed(m), "selected": m.key == spec.key,
                        "fits": None if gpu is None else (m.role != "analyst" or gpu["vram_gb"] >= 11.5)}
                       for m in MODELS.values()]}


def _sha256(path: Path, progress: Optional[Callable[[str, float], None]] = None) -> str:
    h = hashlib.sha256()
    total = path.stat().st_size or 1
    done = 0
    with open(path, "rb") as fh:
        while chunk := fh.read(8 * 1024 * 1024):
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress("Checking", done / total)
    return h.hexdigest()


def _fetch(url: str, target: Path, size: int, sha: str, label: str,
           progress: Optional[Callable[[str, float], None]], cancel: threading.Event) -> None:
    from .. import privacy

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "FinancialLens", **({"Range": f"bytes={have}-"} if have else {})})
    with privacy.download_window():  # the only outbound connection the app makes, and only on request
        with urllib.request.urlopen(req, timeout=60) as resp, open(part, "ab" if have else "wb") as out:
            if have and resp.status != 206:  # server ignored the resume request
                out.truncate(0)
                have = 0
            done = have
            while chunk := resp.read(1024 * 1024):
                if cancel.is_set():
                    raise DownloadError("Download cancelled; it will resume where it stopped.")
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(label, done / size)
    if part.stat().st_size != size:
        raise DownloadError(f"{label}: expected {size} bytes, got {part.stat().st_size}.")
    if _sha256(part, progress) != sha:
        part.unlink()
        raise DownloadError(f"{label}: checksum mismatch — the file was deleted and will not be used.")
    os.replace(part, target)


def install(progress: Optional[Callable[[str, float], None]] = None, cancel: Optional[threading.Event] = None,
            spec: Optional[ModelSpec] = None) -> None:
    spec = spec or selected()
    cancel = cancel or threading.Event()
    free = shutil.disk_usage(folder().parent if folder().parent.exists() else Path.home()).free
    if not model_path(spec).exists() and free < spec.size * 1.1:
        raise DownloadError(f"Not enough free disk space: {spec.size / 1e9:.1f} GB needed.")
    if server_binary() is None:
        name, size, sha = runtime_spec()
        archive = folder() / "downloads" / name
        _fetch(f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/{name}", archive, size, sha,
               "Runtime", progress, cancel)
        dest = folder() / "runtime"
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(dest)
        else:
            with tarfile.open(archive) as t:
                t.extractall(dest, filter="data")
        for p in dest.rglob("llama-server*"):
            p.chmod(0o755)
        archive.unlink()
    m = model_path(spec)
    marker = m.with_suffix(".verified")
    if m.exists() and not marker.exists():  # a file placed here by hand is checked before first use
        if m.stat().st_size != spec.size or _sha256(m, progress) != spec.sha256:
            m.unlink()
        else:
            marker.write_text(spec.sha256)
    if not m.exists():
        _fetch(spec.url, m, spec.size, spec.sha256, "Model", progress, cancel)
        marker.write_text(spec.sha256)


def remove() -> None:
    stop()
    shutil.rmtree(folder(), ignore_errors=True)


_proc: Optional[subprocess.Popen] = None
_url: Optional[str] = None
_running_key: str = ""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(spec: Optional[ModelSpec] = None, timeout: float = 240) -> str:
    """Start llama-server on loopback; graphics card first, CPU if the GPU path fails. Returns the API URL."""
    global _proc, _url, _running_key
    spec = spec or selected()
    if _proc is not None and _proc.poll() is None and _url and _running_key == spec.key:
        return _url
    if _proc is not None:
        stop()
    exe = server_binary()
    if exe is None or not model_path(spec).exists():
        raise DownloadError("The local model is not installed yet.")
    log = folder() / "server.log"
    for gpu_layers in ("99", "0"):
        port = _free_port()
        args = [str(exe), "-m", str(model_path(spec)), "--alias", spec.key, "-c", str(spec.ctx if gpu_layers != "0" else 8192),
                "-ngl", gpu_layers, "-np", "1",
                "--host", "127.0.0.1", "--port", str(port), "--temp", "0"]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with open(log, "a") as fh:
            _proc = subprocess.Popen(args, stdout=fh, stderr=subprocess.STDOUT, cwd=exe.parent, creationflags=flags)
        url = f"http://127.0.0.1:{port}"
        t0 = time.time()
        while time.time() - t0 < timeout and _proc.poll() is None:
            try:
                urllib.request.urlopen(url + "/health", timeout=2).read()
                _url, _running_key = url + "/v1", spec.key
                return _url
            except Exception:
                time.sleep(1)
        stop()
    raise DownloadError(f"The local model did not start; see {log}.")


def running() -> bool:
    return (_proc is not None and _proc.poll() is None and bool(_url)) or bool(os.environ.get("FL_MODEL_URL"))


def stop() -> None:
    global _proc, _url
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(10)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc, _url = None, None


import atexit  # noqa: E402

atexit.register(stop)
