# Change-Order Extraction Pipeline — Approach & Writeup

**Author:** Furqan Ali  
**Role Applied:** AI Engineer — Sledge  
**GitHub:** github.com/furqunali

---

## Overview

This pipeline extracts structured fields from unstructured or semi-structured change-order documents (PDFs, scanned text, or raw strings) and outputs validated JSON with per-field confidence scores.

---

## Approach

### 1. Ingestion
Raw change-order text is fed into the pipeline — this can come from:
- Direct PDF text extraction (via `pdfplumber` or `pymupdf`)
- OCR output from scanned documents
- Pasted plain text

### 2. LLM-Powered Extraction (Claude API)
Instead of brittle regex rules, the pipeline uses **Claude (Opus 5.5 by default, configurable via `CO_EXTRACTOR_MODEL`)** as the extraction engine. A structured prompt instructs the model to:
- Identify all key fields (CO number, project, contractor, costs, dates, etc.)
- Return **only valid JSON** — no prose
- Assign a **confidence score (0.0–1.0)** per field based on textual clarity
- Use `null` for missing fields rather than guessing

This approach handles messy formatting, inconsistent field names, abbreviations, and OCR noise far better than regex.

### 3. Validation Layer
After extraction, a Python validator checks:
- **Required fields** are present and non-null
- **Low-confidence flags** on fields below 0.5
- **Cost arithmetic** — recalculates labor + materials + equipment + markup + other and compares against the stated total (flags >5% variance). Line items that fit no named bucket (permit fees, excavation subs, etc.) go to `other`, so they don't trigger false variance flags
- **Duplicate CO numbers** — after a batch, CO numbers are normalized (case/punctuation-insensitive) and repeats are flagged

### 4. Output
A JSON array with one object per change order, each containing:
- Extracted fields with values + confidence scores
- `overall_confidence` (average across all fields)
- `_validation` block with pass/fail and issue list

---

## Confidence Score Logic

| Score | Meaning |
|-------|---------|
| 0.9–1.0 | Field explicitly labeled and clearly stated |
| 0.7–0.89 | Field present but with minor ambiguity |
| 0.5–0.69 | Inferred from context |
| < 0.5 | Weak signal — flagged for human review |

---

## Failure Modes & Mitigations

| Failure Mode | Description | Mitigation |
|---|---|---|
| **OCR noise** | Scanned docs with garbled text | Model reports lower confidence; <0.5 on required fields is flagged |
| **Missing fields** | CO has no contractor name or date | Returns `null` + low confidence; flagged in validation |
| **Non-standard formats** | "Grand Total" vs "Total This CO" | LLM handles synonyms naturally |
| **Cost math errors** | Stated total doesn't match line items | Arithmetic check flags >5% variance |
| **Multi-page COs** | Cost split across pages | Concatenate page text before extraction (planned: chunk + merge for very long docs) |
| **JSON parse failure** | Model returns prose instead of JSON | Strip code fences; on parse failure, one corrective re-prompt with the error message |
| **Ambiguous dates** | "Nov 22" with no year | Defaults to current year; flagged low confidence |
| **Duplicate CO numbers** | Same CO submitted twice | Normalized CO-number dedup check flags repeats in the batch |

---

## Stack

- **Language:** Python 3.11+
- **LLM:** Anthropic Claude — `claude-opus-5-5` by default (via `anthropic` SDK)
- **PDF parsing:** `pdfplumber` (recommended addition)
- **Validation:** Pure Python

---

## How to Run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here   # Windows: setx ANTHROPIC_API_KEY your_key_here
python extractor.py
python -m pytest -q tests                # offline validation tests, no key needed
```

Output is saved to `change_orders_output.json`.

---

## Future Improvements

1. **PDF ingestion** — add `pdfplumber` layer for direct PDF support
2. **Batch processing** — folder watch + async extraction
3. **Human review queue** — auto-route low-confidence extractions to reviewers
4. **Fine-tuned model** — train on labeled CO dataset for higher accuracy
5. **Database integration** — write validated records to PostgreSQL or MongoDB
