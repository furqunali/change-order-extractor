# Change-Order Extraction Pipeline

[![tests](https://github.com/furqunali/change-order-extractor/actions/workflows/tests.yml/badge.svg)](https://github.com/furqunali/change-order-extractor/actions/workflows/tests.yml)

**Author:** Furqan Ali · **Task:** Sledge — AI Engineer

Extracts structured fields from **messy construction change orders** (digital PDFs, **scanned PDFs**, plain text, email threads) into **schema-validated JSON with per-field confidence scores**. Deterministic checks and a human-review flag tell you exactly which fields to double-check.

📄 **Approach & failure modes:** [WRITEUP.md](WRITEUP.md) · 📊 **Evaluation:** [eval/REPORT.md](eval/REPORT.md)

## Results (8 hand-labelled hard documents)

| Metric | Result |
|---|---|
| Field-level accuracy | **99%** (102/103 labelled fields) |
| Validation verdict correct (good docs pass, planted math error caught) | **8/8** |
| Scanned image-only PDF (skew, noise, handwriting) | 100% of fields |
| Wrong fields routed to human review | 1/1 |

*Scored with `gemini-2.5-flash` (free tier); Claude is the default provider and uses the same code.*
*The one miss, and how a second run exposed a confidently wrong answer, is discussed in the writeup.*

## How it works

```
file ─► ingest ─────────► LLM extraction ─► schema normalization ─► validation ─► JSON + review flag
        txt/eml/pdf text   Claude | Gemini    pydantic: types,       math, dates,
        scanned → vision   JSON re-prompt     dates, $, nulls        evidence, dups
```

- **Any input:** text and digital PDFs are read as text; scanned or image-only PDFs and photos go to the model's native vision input, with no OCR install.
- **Per-field confidence**, an `overall_confidence` computed in code (not by the model), and `field_coverage`.
- **Validated JSON** (pydantic): `"$1,234.50"` → `1234.5`, `"(1,545.00)"` → `-1545.0`, `"Oct 3rd, 2024"` → `2024-10-03`; values that can't be read become `null` with confidence 0.
- **Deterministic checks:**
  - errors: cost buckets ≠ total, completion before issue date, missing required fields, duplicate CO numbers;
  - warnings: markup > 25%, deduct sign errors;
  - evidence: the CO #, total and approver must be traceable to the source.
- **Human-review routing:** `needs_review` plus the exact `review_fields` to check.
- **Production habits:** a bad document never stops the batch, retries honour the API's rate-limit hints, 42 offline tests run in CI, and providers are pluggable.

## Quick start

```bash
git clone https://github.com/furqunali/change-order-extractor
cd change-order-extractor
pip install -r requirements.txt

export ANTHROPIC_API_KEY=...            # default provider: Claude (claude-opus-5-5)
python extractor.py                     # runs every document in samples/
python extractor.py my_co.pdf inbox/    # your own files or folders

export GEMINI_API_KEY=...               # free alternative: https://aistudio.google.com/apikey
python extractor.py --provider gemini

python evaluate.py --provider gemini    # score against samples/ground_truth.json
python -m pytest -q tests               # 42 offline tests, no API key needed
```

## Example output

Console summary for three of the sample documents (`extractor.print_result` over the saved run in `eval/results.json`):

```text
[1/3] co_031_scanned.pdf  (pdf_vision)
  CO Number  : 031
  Project    : Lakeside Apartments - Bldg C
  Total Cost : $11,800.00
  Confidence : 93%  (fields found: 72%)
  Validation : ✓ PASSED

[2/3] co_118_math_error.txt  (text)
  CO Number  : 118
  Project    : Oak Hollow Retail Center
  Total Cost : $13,500.00
  Confidence : 100%  (fields found: 89%)
  Validation : ✗ FAILED  → needs human review
    ✗ Cost math mismatch: line items sum to $11,000.00 but stated total is $13,500.00 (diff -$2,500.00)

[3/3] co_052_email_thread.eml  (text)
  CO Number  : 52
  Project    : Northpoint Office Park
  Total Cost : $9,050.00
  Confidence : 95%  (fields found: 83%)
  Validation : ✓ PASSED  → needs human review
    ⚠ approved_by 'Rachel Kim' but the source has no approval/signature line
    review: approved_by
```

Each record in the JSON looks like this (abridged from [`eval/results.json`](eval/results.json)):

```json
{
  "source": "co_007_deduct_value_engineering.txt",
  "input_mode": "text",
  "status": "success",
  "data": {
    "change_order_number": {"value": "DCO-007", "confidence": 1.0},
    "date_issued": {"value": "2025-02-14", "confidence": 1.0},
    "reason_category": {"value": "Value Engineering", "confidence": 1.0},
    "cost_breakdown": {
      "labor": {"value": -4450.0, "confidence": 1.0},
      "materials": {"value": -9150.0, "confidence": 1.0},
      "total": {"value": -16995.0, "confidence": 1.0}
    },
    "schedule_impact_days": {"value": -2, "confidence": 1.0},
    "overall_confidence": 0.994,
    "_validation": {"passed": true, "errors": [], "warnings": [], "grounded": true,
                    "needs_review": false, "review_fields": []}
  }
}
```

## Project layout

```
co_extractor/   ingest.py · prompt.py · providers.py · schema.py · validate.py · pipeline.py
extractor.py    CLI
evaluate.py     scoring vs. ground truth → eval/REPORT.md
samples/        8 test documents (txt, eml, digital PDF, scanned PDF) + ground_truth.json + make_samples.py
tests/          42 offline tests (LLM and HTTP mocked)
```
