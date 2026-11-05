#!/usr/bin/env bash
# Run Apertus 8B Instruct (Swiss open model, EPFL/ETH Zürich/CSCS, Apache-2.0) locally with llama.cpp.
# OpenAI-compatible API on http://127.0.0.1:18765/v1 — loopback only; no data leaves this machine.
# Usage: packaging/apertus.sh [start|stop]   (GPU: FL_GPU=0 by default; CPU fallback if no GPU runtime)
set -euo pipefail
MODELS="${FL_MODELS:-$HOME/.local/share/FinancialLens/models}"
FILE="Apertus-8B-Instruct-2509-Q4_K_M.gguf"
URL="https://huggingface.co/unsloth/Apertus-8B-Instruct-2509-GGUF/resolve/main/$FILE"
case "${1:-start}" in
  stop) docker rm -f financial-lens-apertus >/dev/null && echo stopped; exit 0 ;;
esac
mkdir -p "$MODELS"
if [ ! -f "$MODELS/$FILE" ]; then
  echo "Downloading $FILE (about 5 GB) from Hugging Face…"
  curl -fL -o "$MODELS/$FILE.part" "$URL" && mv "$MODELS/$FILE.part" "$MODELS/$FILE"
fi
docker rm -f financial-lens-apertus >/dev/null 2>&1 || true
GPU=(--gpus "device=${FL_GPU:-0}")
IMG=ghcr.io/ggml-org/llama.cpp:server-cuda
docker run -d --name financial-lens-apertus --restart unless-stopped "${GPU[@]}" -p 127.0.0.1:18765:8080 \
  -v "$MODELS":/models:ro "$IMG" -m "/models/$FILE" --alias apertus-8b -c 8192 -ngl 99 --host 0.0.0.0 --port 8080 \
  --temp 0 >/dev/null
for i in $(seq 1 90); do curl -sf http://127.0.0.1:18765/health >/dev/null && { echo "Apertus ready on http://127.0.0.1:18765/v1"; exit 0; }; sleep 2; done
echo "Apertus did not start; see: docker logs financial-lens-apertus" >&2; exit 1
