# Financial Lens

Evidence-first, offline-first finance for households, businesses and
cooperatives. Part of [Helvetic Lens](https://helveticlens.ch).

Financial Lens reads receipts, invoices and bank statements, matches invoices
with payments and keeps the original document behind every number. Spending
is shown as a treemap that drills down to the record, its history and the
original file.

**Status:** in development (Phase 1 MVP). Landing page: <https://finance.helveticlens.ch>.

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
| `src/financial_lens/ingest` | camt.053/054, Swiss QR-bill, (OCR next) |
| `src/financial_lens/matching` | Invoice ↔ payment reconciliation |
| `src/financial_lens/views` | Treemap aggregation with drill-down |
| `src/financial_lens/api` | Local FastAPI service (127.0.0.1) |
| `src/financial_lens/desktop` | PySide6 desktop shell |
| `site/` | Static landing page for finance.helveticlens.ch |
| `deploy/` | Container and tunnel for the landing page |
| `docs/` | Specification summary and plans |

## Development
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,api]'
pytest
uvicorn financial_lens.api.app:app --host 127.0.0.1
```

## Licence
Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
