# Decisions

Miha asked for decisions to be made autonomously until the spec is done.
Each entry: date · decision · reason.

- 2026-11-05 · Repository `HappyMiha/helveticlens-finance`, Apache-2.0 like the sibling Helvetic Lens repos.
- 2026-11-05 · Financial Lens is a standalone product; it does not use the helveticlens.ch core API.
- 2026-11-05 · finance.helveticlens.ch serves a static landing page with a sample treemap (nginx container on the host PC) through its **own** Cloudflare tunnel, so the production helveticlens.ch tunnel and containers are never touched.
- 2026-11-05 · Design tokens and brand mark copied from helveticlens-pharma (`design-tokens.css`, `favicon.svg`), as the brand book requires repository tokens.
- 2026-11-05 · Core domain is pure Python stdlib (Decimal, dataclasses) so it is testable without services; FastAPI, PostgreSQL, PySide6 and OCR are optional extras.
- 2026-11-05 · Money is `Decimal` in minor-unit precision; floats are rejected at construction.
- 2026-11-05 · Verification states (§7): **confirmed** = two independent agreeing sources (document + bank), a structured reference match, or a person; **needs review** = recognised but low confidence, conflicting, overpaid or a possible duplicate; **unconfirmed** = a single source (OCR-only, manual entry, bank debit without document).
- 2026-11-05 · Spend is counted once (§18): recognised documents count; a bank debit counts only for the part no document explains; confirmed refunds net the original category; confirmed duplicates are excluded.
- 2026-11-05 · Auto-confirmed links only for a QR/SCOR reference match, or exact amount + date window + clearly best counterparty match; everything else is proposed for a person (§4.5, §17.4).
- 2026-11-05 · OCR engine: Tesseract (deu+fra+ita+eng) via its TSV output for per-line confidence; PaddleOCR can be added behind the same `recognise()` interface. QR-bills decoded with zbar override OCR guesses.
- 2026-11-05 · Exchange rates are recorded with their source; an operation without a rate within 40 days is shown as unconverted, never estimated.
- 2026-11-05 · The assistant (§11) parses questions with deterministic patterns (en/de/fr/uk); an optional model may only translate a question into a query, never produce a number.
- 2026-11-05 · Desktop UI in PySide6 widgets talking to the service in-process; the FastAPI service exposes the same operations for other clients.
- 2026-11-05 · Multi-profile (§2): each organisation (personal, business, cooperative) has its own categories, rules, accounts and ledger; the desktop switches profile from the toolbar.
- 2026-11-05 · Roles: owner/admin (everything), editor (import, correct, decide, export), viewer (read, export), member (own statement only). Denied attempts are written to the audit log. Local single-user mode acts as owner.
- 2026-11-05 · Member contributions: a member number in the payment text confirms the contribution; a matching name alone is only proposed. Confirmed payments are allocated to dues oldest first; arrears = overdue open dues.
- 2026-11-05 · Cost allocation across objects uses integer weights (e.g. m²) and the cent-exact `Money.allocate`.
- 2026-11-05 · PDF reports are produced by a small built-in writer (no external dependency); the full archive is a ZIP with every table as JSON and CSV, all originals in their virtual folders and a SHA-256 manifest.
- 2026-11-05 · L2 is enforced twice: a socket guard inside the app process and an `internal` Docker network; only a small proxy publishes the loopback port. Verified that the app container cannot reach the internet.
- 2026-11-05 · Default privacy level for a new profile is L2 (maximum); moving to L1/L0 is an explicit, audited admin action.
- 2026-11-05 · Audit log rows are hash-chained so tampering is detectable even by a database superuser.
- 2026-11-05 · Backups: AES-256-GCM with scrypt-derived key; restore verifies the manifest and every original before inserting anything.
- 2026-11-05 · Phone uploads via an installable web app (PWA) served by the local API instead of a native mobile app: no app store, works on iOS and Android, data stays on the local network. The LAN gate exposes only `/m` to other devices.
- 2026-11-05 · E-mail import reads IMAP read-only (`BODY.PEEK`), deduplicates by Message-ID, never deletes; credentials only from the environment. In L2 only local or private-network mail servers.
- 2026-11-05 · Manual records start *Unconfirmed*; an attached file is linked as evidence but does not confirm the record on its own.
- 2026-11-05 · Mobile (Miha): Android only for now; local network only; the end-to-end encrypted relay will be a paid service later. iOS code stays in the repository but is not built or published.
- 2026-11-05 · The Android release key lives only on the maintainer's PC (`~/.config/financial-lens/android`), not in GitHub; release APKs are signed there and attached to the GitHub release.
- 2026-11-05 · Android app is native Kotlin + Jetpack Compose (not Flutter): device key generated inside the Android Keystore/StrongBox and never exportable, ML Kit document scanner and code scanner, Glance widget, share target, WorkManager queue; 3 MB APK. The earlier Flutter prototype stays in `mobile/` only as a reference for the protocol and is not published.
- 2026-11-05 · Document understanding is analytical (Miha: correctness over speed, no tuning to specific files). Each document type has an analyst that finds values with their role and checks the arithmetic the document must satisfy: payslip gross − deductions (± items after gross) = net, net + expenses = payout; statement opening + credits − debits = closing and running balance line by line, signs from debit/credit columns (by word position) or from the balance change; invoice/receipt total confirmed by net + VAT, the Swiss VAT rate, or line items (+ VAT). Anything that does not reconcile is imported as *Needs review* with the exact reason; nothing is guessed.
