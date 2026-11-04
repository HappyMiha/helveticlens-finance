#!/usr/bin/env bash
# One-time publish of Financial Lens: GitHub repo + finance.helveticlens.ch.
# Creates a NEW tunnel "helveticlens-finance" and ONE new DNS record (finance).
# The production helveticlens.ch tunnel, its config and containers are not touched.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=HappyMiha/helveticlens-finance
CERT=/srv/helvetic-lens/helvetic-lens/.cloudflared/cert.pem
IMG=cloudflare/cloudflared@sha256:51c9cefcb4569df44e1ad403ab1d3d8065aa8e84339bcfc6aee75502e1140339
CF="docker run --rm -v $CERT:/cert.pem:ro -v $PWD/deploy/cloudflared:/out -u $(id -u):$(id -g) $IMG tunnel --origincert /cert.pem"

# 1. GitHub repository
if ! gh repo view "$REPO" >/dev/null 2>&1; then
  gh repo create "$REPO" --public --source . --push \
    --description "Financial Lens — evidence-first, offline-first finance. Part of Helvetic Lens. Apache-2.0." \
    --homepage https://finance.helveticlens.ch
else
  git push -u origin main
fi

# 2. Separate tunnel
mkdir -p deploy/cloudflared
if ! ls deploy/cloudflared/*.json >/dev/null 2>&1; then
  $CF --cred-file /out/tunnel.json create helveticlens-finance
fi
chmod 0644 deploy/cloudflared/tunnel.json  # cloudflared runs as uid 65532 in the container
ID=$(python3 -c 'import json;print(json.load(open("deploy/cloudflared/tunnel.json"))["TunnelID"])')
cat > deploy/cloudflared/config.yml <<CFG
tunnel: $ID
credentials-file: /etc/cloudflared/tunnel.json
ingress:
  - hostname: finance.helveticlens.ch
    service: http://site:8080
  - service: http_status:404
CFG

# 3. One new DNS record: finance.helveticlens.ch -> this tunnel
$CF route dns "$ID" finance.helveticlens.ch

# 4. Start
docker compose -f deploy/compose.yaml up -d --build
echo "Done. https://finance.helveticlens.ch"
