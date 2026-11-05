# Financial Lens

Evidence-first, offline-first finance for households, businesses and
cooperatives. Part of [Helvetic Lens](https://helveticlens.ch).

Financial Lens reads receipts, invoices and bank statements, matches invoices
with payments and keeps the original document behind every number. Spending
is shown as a treemap that drills down to the record, its history and the
original file.

**Status:** Phases 1–4 of the specification implemented and tested (39 tests on PostgreSQL); not yet packaged for download. Landing page: <https://finance.helveticlens.ch>.

See [specification](docs/SPECIFICATION.md), [§16 acceptance](docs/PHASE1_ACCEPTANCE.md), [decisions](docs/DECISIONS.md), [security](docs/SECURITY.md), [deployment](docs/DEPLOYMENT.md).

## Principles
- Totals are computed deterministically (`Decimal`), never by a language model.
- Documents, recognised expenses and payments are separate, append-only events.
- Every fact keeps provenance: source document, location, method, agent, confidence.
- Ambiguous matches are proposed, not decided.
- Three privacy levels: local only, Swiss hosting, cloud AI.

## Layout
| Path | Purpose |
| --- | --- |
| `src/financial_lens/domain` | Money, events, provenance, ledger |
| `src/financial_lens/ingest` | camt.053/054, Swiss QR-bill, CSV/XLSX bank exports |
| `src/financial_lens/matching` | Invoice ↔ payment reconciliation |
| `src/financial_lens/views` | Treemap aggregation with drill-down |
| `src/financial_lens/extract` | Local OCR (Tesseract, pdftotext, zbar) and field extraction with provenance |
| `src/financial_lens/classify` | Rules, learned rules, built-in hints |
| `src/financial_lens/ai` | Provider-agnostic model layer with privacy gate and redaction |
| `src/financial_lens/store` | PostgreSQL schema (append-only history), original file store |
| `src/financial_lens/service.py` | Ingest, reconciliation, verification, treemap, dashboard |
| `src/financial_lens/analytics.py`, `assistant.py` | Periods, cash flow, recurring, unpaid; natural-language questions |
| `src/financial_lens/orgs.py`, `reports.py` | Cooperatives, roles, budgets, allocation; reports and full export |
| `src/financial_lens/privacy.py`, `backup.py`, `security.py` | L0/L1/L2 modes, encrypted backups, self-check |
| `src/financial_lens/api` | Local FastAPI service (127.0.0.1) |
| `src/financial_lens/desktop` | PySide6 desktop shell |
| `site/` | Static landing page for finance.helveticlens.ch |
| `deploy/` | Container and tunnel for the landing page |
| `docs/` | Specification summary and plans |

## Development
```bash
docker build -t financial-lens-dev -f docker/dev.Dockerfile .
docker compose -f docker/compose.test.yaml run --rm test      # PostgreSQL 17, Tesseract, Qt offscreen
```
Run it: see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Licence
Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
