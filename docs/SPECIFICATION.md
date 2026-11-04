# Financial Lens — specification v0.1 (working summary)

Source: `FINANCIAL_LENS_specification_uk.md` by Miha (Ukrainian original, 2026-11-04).
This file is an English working summary used to track implementation; the
original document is authoritative.

## Product
Offline-first, AI-assisted desktop application, "WinDirStat for finances".
Scenarios: personal/family; sole trader/SME (personal vs business, opex vs
capex, by client/project, paid/unpaid, refunds, several activities per user);
cooperatives (member register, contribution history, arrears, cost allocation
per property, earmarked funds, project budgets, member reports, per-role access).

## §3 Data first
Inputs in any order: photos, scans, PDF, e-invoices, bank statements and
exports, manual entries, notes. The system determines the document type, OCRs
it, extracts amount, currency, document and operation dates, payer/payee and
purpose, categorises, finds links, detects duplicates and proposes storage.
The user can correct anything. AI must not invent missing data or turn
guesses into facts.

## §4.1 Ingestion
JPG/PNG/HEIC/PDF/TXT/CSV/XLSX/XML, bank exports, manual text; drag and drop,
watched import folder, bulk upload, API; works offline.

## §4.2 Recognition
OCR plus document intelligence (structure, tables, fields, QR-bill, document
type). Swiss: QR-bill, QR-IBAN/IBAN, CHF and other currencies, CAMT.053/054,
ISO 20022, future eBill.

## §4.3 Example record
Type invoice · payee electricity supplier · 184.50 CHF · document date
12.10.2026 · due 30.10.2026 · category utilities/electricity · status awaiting
payment · period Oct 2026 · source PDF · evidence: original file.

## §4.4 Classification
Category, subcategory, counterparty, project, object, period, operation type,
linked documents. Categories are user-editable; AI adapts and learns rules
("this shop means project X").

## §4.5 Reconciliation (key)
Invoices↔payments, receipts↔transactions, payslips↔income, member
contributions, refunds↔original expense, advances↔final settlement. Links are
many-to-many; partial payments, several payments per invoice, overpayments and
refunds. Non-obvious links are proposed, never auto-confirmed without enough
evidence.

## §5 Storage
Dynamic, example-only tree, e.g.
`FINANCIAL_DATA/2026/{INCOME/{Salary,Other_Income,Refunds},EXPENSES/{Housing,Food,Transport,Insurance,Healthcare,Utilities},TAXES,BANK_STATEMENTS,UNPAID_INVOICES,PROJECTS,UNCLASSIFIED}`, plus `2025/` and `ARCHIVE/`.
Five things kept separate: originals, processed data, transactions, links,
metadata with history. Moving a document never alters the original or breaks links.

## Further sections
Pending: remaining sections (privacy levels, treemap UI, architecture, phases,
§16 acceptance cycle) are being transcribed.
