# Security and privacy

## Privacy levels (§8)
| Level | Setting | What may leave the machine |
| --- | --- | --- |
| **L2 maximum** (default) | `local_only` | Nothing. The app process blocks every non-loopback socket and name lookup (`privacy.enforce_local_only`), and in Docker the app container sits on an `internal` network with no route out. OCR (Tesseract), QR decoding, rules, matching, analytics and the assistant all run locally; a local model (Ollama, llama.cpp) can be attached. |
| **L1 moderate** | `swiss_hosted` | Text may go to providers declared `swiss` (e.g. Infomaniak, Swisscom), after identifiers are redacted. External providers only for documents individually marked `cloud_ai`. |
| **L0 minimal** | `cloud_ai` | Any configured provider, still per document and redacted, every call logged in AI Activity with what was sent. |

The stricter of the workspace level and the document's own setting always wins. Before any text leaves the machine, IBANs, QR references, e-mail addresses, phone numbers, AHV numbers and card numbers are replaced by placeholders.

## What models may and may not do
- Suggest a category (only from existing categories; confidence capped at 75 %, so AI alone never confirms).
- Find a missing field — accepted only if the model quotes text that exists verbatim in the document and the value can be read from that quote; the record is then *Needs review*.
- Translate a question into a query. Never compute a total, balance or sum (§9, §17.9).

## Integrity
- Originals: content-addressed by SHA-256, written once, read-only, verified on every read; the storage folder is not readable by other users.
- History: revisions, extractions, AI activity and the audit log are append-only (database triggers).
- Audit log is hash-chained: `verify_audit_chain()` detects edits even by a database superuser who disables the trigger.
- `financial-lens check` (or `GET /security/check`) reports privacy level, network guard, providers, originals integrity and permissions, audit chain, API binding, database transport and disk encryption. Warnings are shown, not hidden.

## Backups
`financial-lens backup DIR` writes the full archive encrypted with AES-256-GCM, key from the passphrase via scrypt (n=2¹⁵). Tampering or a wrong passphrase fails restore. Copy the `.flbk` file anywhere (USB, NAS, a Swiss server); the content stays unreadable without the passphrase. `financial-lens restore FILE` checks every file against the manifest and every original against its checksum.

## Access control
Roles per organisation: owner, admin, editor, viewer, member (own statement only). Denied attempts are audited. The API binds to 127.0.0.1; exposing it to a network requires TLS and authentication in front of it (see DEPLOYMENT.md).

## Recommended host measures
Full-disk encryption (LUKS / FileVault / BitLocker) for the data folder and the database volume, set `FL_DISK_ENCRYPTION=luks` (or similar) once done so the self-check reflects it. For an air-gapped machine use the Docker stack without the `gate` service and the desktop app directly.
