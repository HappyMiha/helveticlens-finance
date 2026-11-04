# Phase 1 — §16 acceptance evidence

Run: `docker compose -f docker/compose.test.yaml run --rm test` (PostgreSQL 17, local Tesseract, no network).

| §16 step | Where it is proven |
| --- | --- |
| 1 Upload a photo of an invoice | `test_full_cycle` renders a tilted, blurred, noisy JPEG and calls `ingest`; desktop: drag & drop or *Import files* (`test_desktop_drilldown`) |
| 2 Recognise the document | `extract.fields.detect_type` → `invoice`; logged in AI Activity |
| 3 Extract financial data | amount 184.50, CHF, document date 12.10.2026, due 30.10.2026, counterparty, IBAN — each with line, quote, confidence |
| 4 Create a record | `operations` + revision 1 (`unconfirmed`, method `ocr`) |
| 5 Assign a category | built-in hint → Housing / Electricity; user rules and learned rules take precedence |
| 6 Store the original | content-addressed, read-only, SHA-256 verified on every read (`store/files.py`) |
| 7 Import a bank statement | camt.053 → payments; duplicates by `AcctSvcrRef` skipped |
| 8 Find the matching operation | `reconcile`: QR reference, or amount + date window + counterparty; ambiguous → proposed only |
| 9 Link invoice and payment | `links` row with rule and reasons; both records get a `confirmed` revision |
| 10 Expense on the treemap | counted once: the linked payment is not counted again |
| 11 Open the category, see its operations | `operations(…, ("Housing",))`; desktop drill-down + table |
| 12 Open every piece of evidence | original bytes, OCR text, per-field provenance, linked payment and its statement, full revision history, audit log |

Totals are computed with `Decimal`/PostgreSQL `numeric`; revisions, extractions, AI activity and the audit log are append-only (database triggers).

Screenshots: [overview](screenshots/desktop-overview.png), [drill-down](screenshots/desktop-drilldown.png).
