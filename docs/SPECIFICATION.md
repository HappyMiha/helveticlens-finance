# Financial Lens — specification v0.1 (working summary)

Source: `FINANCIAL_LENS_specification_uk.md` by Miha (Ukrainian original, 2026-11-04).
This file is condensed into English from Miha's original Ukrainian
specification and is used to track implementation; the original is authoritative.

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


## §6 Financial WinDirStat (central UI)
- **6.1 Treemap:** area ∝ sum (e.g. Housing 1800, Food 950, Transport 350, Insurance 600, Medical 250, Leisure 400 CHF). Colours: income greens, expenses red/orange, own transfers neutral, undetermined grey; unconfirmed/problem records get separate indicators. Toggles: income, expenses, net, per account, per project, per counterparty.
- **6.2 Drill-down:** Housing → Rent/Electricity/Water/Heating/Repairs/Other → individual invoices → original PDF, amount, date, counterparty, linked bank transaction, processing history.
- **6.3 Periods:** day, week, month, quarter, year, custom. Compare month vs previous, year vs previous, any two years, actual vs budget.
- **6.4 Other views:** cash flow, income vs expenses, monthly balance, by counterparty, recurring payments, top expenses, unpaid invoices, savings trend.

## §7 Evidence
Every operation stores ID, operation date, amount, currency, type, category, counterparty, description, linked documents, data source, extraction method, OCR result, AI classification, confidence, verification status, change history.
States: **Confirmed** (enough documentary or bank evidence), **Needs review** (recognised but doubtful or inconsistent), **Unconfirmed** (created by user or AI without enough evidence). No false sense of precision.

## §8 Privacy levels (real operating modes, all full-featured)
- **L0 Minimal:** external AI APIs, cloud OCR, sync, advanced analytics; sending documents out stays transparent and controlled.
- **L1 Moderate:** local DB and originals, Swiss server (Swisscom/Infomaniak), encrypted transport, external models when needed, per-document control of what leaves, backups to a chosen server.
- **L2 Max:** fully local server, LLM, OCR, DB, storage; no external APIs, telemetry or outbound requests; runs fully offline.
Security: disk, backup and DB encryption, access control, audit, document integrity checks, air-gapped operation possible.

## §9 AI orchestration
Provider-agnostic (local LLM, OpenAI, Anthropic, OpenAI-compatible), model per task, fallback, quality scoring, error handling. OCR local; document recognition vision LLM; field extraction LLM; classification LLM + rules; duplicates algorithmic; matching reconciliation engine; analytics SQL + LLM; reports LLM; security independent system mechanisms. **Totals, balances and sums are always deterministic code.**

## §10 Entities
User, Organization, Account, Transaction, Income, Expense, Invoice, Receipt, BankStatement, Counterparty, Category, Subcategory, Project, Member, Budget, Document, Evidence, Tag, RecurringRule, AuditLog. Multi-currency with recorded FX rate and source; multiple accounts, cash, own transfers, partial payments, refunds, recurring items, history-preserving corrections. Leave a path to double-entry bookkeeping.

## §11 Natural-language questions
E.g. food spend this year; housing cost last 12 months; expenses over 500 CHF; payments to Swisscom; unpaid invoices; car repairs; one cooperative member's payments; what grew vs last year; transactions without evidence; documents not linked to a bank transaction. Answers link to operations and original documents.

## §12 Stack
Python + Qt (or another cross-platform desktop framework); FastAPI; PostgreSQL as primary store (SQLite not allowed in production); local file storage with controlled structure; PostgreSQL full-text search (+ local vector index if needed); PaddleOCR or Tesseract + local models; abstract Model Provider Layer; interactive treemap with drill-down; local encryption, access control, audit. Modular; not tied to one model, UI or cloud.

## §13 UX
Understandable without accounting training. Main screen: (1) overall balance, (2) income, (3) expenses, (4) treemap, (5) time analytics, (6) unconfirmed operations, (7) unpaid invoices, (8) recent documents. Other screens: Inbox (processing / needs review), Documents (originals and links), Transactions (full register), AI Activity (what AI recognised, classified, changed or proposed). Modern desktop UI, restrained palette, high density, treemap at the centre.

## §14 Export
PDF, CSV, XLSX, JSON, original documents, full archive. Reports monthly, quarterly, yearly, by category, counterparty, project, account, member. Exports keep the trail back to evidence.

## §15 Phases
- **P1 Functional MVP** (fully working local prototype): upload PDFs and photos, manual transactions, OCR, extraction of amounts, dates and counterparties, AI classification, categories and tags, local storage, PostgreSQL, linking documents to transactions, treemap, month and year filters, drill-down to originals.
- **P2 Financial intelligence:** bank statements, automatic payment matching, duplicates, recurring payments, unpaid invoice tracking, multi-currency, advanced analytics, AI assistant.
- **P3 Multi-profile:** personal, business, cooperatives, multiple organisations, members, permissions, projects and budgets, advanced reports.
- **P4 Security and deployment:** three privacy levels, local models, external providers, Swiss server infrastructure, encrypted backups, security audit, fully offline deployment.

## §16 MVP acceptance
Not an MVP if it only OCRs photos or only shows a pretty treemap. The full cycle must work:
1. User uploads a photo of an invoice.
2. System recognises the document.
3. Extracts the financial data.
4. Creates a record.
5. Assigns a category.
6. Stores the original.
7. User imports a bank statement.
8. System finds the matching operation.
9. Links the invoice to the payment.
10. Shows the expense on the treemap.
11. User opens the category and sees all its operations.
12. User can open every piece of evidence.
All totals mathematically correct; every change traceable.

## §17 Inviolable rules
1. No manual structuring required from the user. 2. Originals never lost or silently altered. 3. AI never invents operations. 4. AI never silently confirms doubtful ones. 5. Every operation has provenance. 6. Every change has history. 7. All categories and tags editable. 8. Local mode is full-featured. 9. No money maths by an LLM. 10. No personal data to external models without permission. 11. Provider-independent. 12. Full data export.

## §18 Vision and architecture notes
Five years of documents; drill Transport → Car → Repairs to every payment and receipt; compare 2026 vs 2025. Motto: *Feed anything. Understand everything. See where every franc goes.*
- A document is not a transaction: invoice, expense recognition and payment are separate events (no double counting).
- AI is not the centre: PostgreSQL, rules and a deterministic engine guarantee correctness.
- Store provenance of every fact, including who confirmed it.
- Future: Financial Flow Map (income source → account → transfer → expense → evidence document).
