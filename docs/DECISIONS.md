# Decisions

Miha asked for decisions to be made autonomously until the spec is done.
Each entry: date · decision · reason.

- 2026-11-05 · Repository `HappyMiha/helveticlens-finance`, Apache-2.0 like the sibling Helvetic Lens repos.
- 2026-11-05 · Financial Lens is a standalone product; it does not use the helveticlens.ch core API.
- 2026-11-05 · finance.helveticlens.ch serves a static landing page with a sample treemap (nginx container on the host PC) through its **own** Cloudflare tunnel, so the production helveticlens.ch tunnel and containers are never touched.
- 2026-11-05 · Design tokens and brand mark copied from helveticlens-pharma (`design-tokens.css`, `favicon.svg`), as the brand book requires repository tokens.
- 2026-11-05 · Core domain is pure Python stdlib (Decimal, dataclasses) so it is testable without services; FastAPI, PostgreSQL, PySide6 and OCR are optional extras.
- 2026-11-05 · Money is `Decimal` in minor-unit precision; floats are rejected at construction.
