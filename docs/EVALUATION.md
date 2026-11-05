# Document understanding — evaluation (2026-11-05)

How to reproduce: `financial-lens eval [--model URL] [--hard]` (generated documents) and
`python -m financial_lens.eval_real DIR [--model URL]` (real scans, e.g. the public SROIE receipts).
The most important column is **false confirmations**: a document marked as reconciled although a value is
wrong. It must be zero; everything uncertain goes to *Needs review* with the reason.

## Generated documents (payslips, statements, invoices; de/fr/it/en; PDF and photos)
| Set | Rules + arithmetic | + Apertus 1.0 8B | + Apertus 1.5 8B (text) | False confirmations |
|---|---|---|---|---|
| Standard layouts (96) | 100 % | 100 % | 100 % | 0 / 0 / 0 |
| Wording the rules were not written for (16 payslips) | 0 % (all to review) | **94 %** | 88 % | 0 / 0 / 0 |
| Damaged scans: skewed, upside down, perspective, shadow, JPEG noise (90) | 73 % | 73 % | 76 % | 0 / 0 / 0 |

## Real receipt scans (SROIE, 20 per row; share of correct totals, then auto-reconciled)
### Rules only, all damage kinds (before the last safety fix)
| Input | Docs | Type right | Total right | Reconciled (auto) | False confirmations | Time / doc |
|---|---|---|---|---|---|---|
| original | 20 | 95 % | 75 % | 40 % | 0 | 6.6 s |
| upside_down | 20 | 70 % | 55 % | 25 % | 0 | 7.8 s |
| sideways | 20 | 75 % | 55 % | 25 % | 0 | 10.5 s |
| skewed | 20 | 85 % | 60 % | 35 % | 1 | 8.9 s |
| perspective | 20 | 85 % | 65 % | 25 % | 0 | 8.1 s |
| dark_shadow | 20 | 100 % | 75 % | 40 % | 0 | 8.3 s |
| blurry_lowres | 20 | 60 % | 35 % | 20 % | 0 | 9.8 s |
| jpeg_noise | 20 | 80 % | 60 % | 40 % | 0 | 7.3 s |

#### rules only
| Input | Docs | Type right | Total right | Reconciled (auto) | False confirmations | Time / doc |
|---|---|---|---|---|---|---|
| original | 20 | 95 % | 70 % | 25 % | 0 | 6.6 s |
| skewed | 20 | 90 % | 65 % | 15 % | 0 | 7.7 s |
| upside_down | 20 | 70 % | 55 % | 15 % | 0 | 7.6 s |
#### rules + Apertus 1.5
| Input | Docs | Type right | Total right | Reconciled (auto) | False confirmations | Time / doc |
|---|---|---|---|---|---|---|
| original | 20 | 95 % | 70 % | 35 % | 0 | 13.0 s |
| skewed | 20 | 90 % | 65 % | 15 % | 0 | 13.4 s |
| upside_down | 20 | 70 % | 55 % | 25 % | 0 | 15.5 s |

## What made the difference
- **Arithmetic decides, labels help.** Totals are the printed amount that other printed amounts prove
  (subtotal + tax, items, paid − change); payslip roles can be found from gross − deductions = net alone.
- **The model is a switch.** Apertus is asked only when the rules are unsure; its reading is accepted only if the
  arithmetic then reconciles and every amount it names is printed on that line. It mainly helps with unfamiliar
  wording; it cannot fix numbers that OCR misread.
- **Image preparation:** orientation detection (Tesseract OSD), deskew only when it reads better, uneven light
  flattened before OCR.
- **Exactness:** sums must match to the cent; 5-Rappen tolerance only for totals that are themselves rounded;
  an approximate VAT-rate check or "paid exactly the total" never confirms on its own; items that do not add
  up block a confirmation.

## Limits
- Blurry, low-resolution photos remain the weakest input (35 % correct totals): OCR is the bottleneck.
- Apertus 1.5's vision model (reading images directly) cannot run on a GTX 1080; it needs a Turing-or-newer
  GPU with ≥ 16 GB or Swiss hosting.
- Apertus 1.5 was tested as a community text-only GGUF conversion, not an official build.
