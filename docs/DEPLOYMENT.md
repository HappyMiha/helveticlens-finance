# Deployment

## 1. Desktop on one computer (L2, fully offline)
```bash
pip install -e '.[api,db,desktop,security]' pillow pyzbar openpyxl   # plus tesseract-ocr, poppler-utils, libzbar0
createdb financial_lens
export FL_DSN="dbname=financial_lens" FL_DATA=~/FinancialLens
financial-lens init
financial-lens desktop
```
Drop files on the window, or run `financial-lens watch ~/FinancialLens/inbox` for a watched import folder.

## 2. Docker on one machine (L2 by default)
```bash
cd docker
umask 077; mkdir -p secrets
PW=$(head -c 18 /dev/urandom | base64 | tr -d '/+=')
printf '%s' "$PW" > secrets/db_password
printf 'host=db user=fl dbname=fl password=%s' "$PW" > secrets/dsn
docker compose -f compose.yaml up -d --build          # API at http://127.0.0.1:8765/docs
docker compose -f compose.yaml --profile local-ai up -d  # with a local model server
```
The app and database containers are on an `internal` network: verified that the app container cannot reach the internet. Only the `gate` proxy publishes `127.0.0.1:8765`.

## 3. Swiss server (L1)
Run the same stack on a server hosted in Switzerland (e.g. Infomaniak, Swisscom). Put a TLS reverse proxy with authentication in front of `gate` instead of the loopback port, use `sslmode=verify-full` in the DSN if the database is remote, set the privacy level with `financial-lens privacy L1` and declare Swiss model endpoints with `"locality": "swiss"` in `config.json`.

## Model configuration (`~/.config/financial-lens/config.json` or `FL_CONFIG`)
```json
{
  "providers": [
    {"name": "ollama", "type": "openai_compatible", "base_url": "http://ollama:11434/v1", "model": "qwen2.5:7b", "locality": "local"},
    {"name": "infomaniak", "type": "openai_compatible", "base_url": "https://api.infomaniak.com/1/ai/<id>/openai", "model": "mixtral", "locality": "swiss", "api_key": "…"},
    {"name": "claude", "type": "anthropic", "model": "claude-sonnet-5-5", "api_key": "…", "locality": "external"}
  ],
  "routes": {"classify": ["ollama", "infomaniak"], "extract": ["ollama"], "parse_question": ["ollama"]}
}
```
Providers not allowed by the current privacy level are skipped (and logged), never called.
