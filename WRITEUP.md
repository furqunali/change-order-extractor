# Change-Order Extraction — Approach & Failure Modes

**Author:** Furqan Ali · **Role:** AI Engineer, Sledge · **Repo:** <https://github.com/furqunali/change-order-extractor>

## TL;DR

Messy change orders (digital PDFs, scanned PDFs, plain text, email threads) go in; schema-validated JSON with per-field confidence, deterministic checks and a human-review flag come out. On a hand-labelled set of 8 deliberately difficult documents, the pipeline scored **99% field accuracy (102/103)**. The validator gave the correct verdict on **8/8** documents, including catching a planted arithmetic error. The one wrong field, a hallucinated approver, is now **routed to human review on every run**. On a second run the model repeated that mistake at *high* confidence, so I added an evidence check that doesn't depend on the model (details below). Full results: [`eval/REPORT.md`](eval/REPORT.md).

## Pipeline

```
file ──► ingest ──► LLM extraction ──► schema normalization ──► validation ──► JSON + review flag
```

1. **Ingest** (`co_extractor/ingest.py`). Text, `.eml` and digital PDFs (via `pdfplumber`) become text. If a PDF has under ~40 characters per page, it is treated as scanned, and the raw PDF is sent to the model's native document/vision input. That avoids a local OCR dependency, and the model sees the layout, tables and handwriting directly.
2. **Extract** (`prompt.py`, `providers.py`). A single prompt with explicit rules:
   - use null rather than guess;
   - negative amounts for deduct COs;
   - map line items into fixed cost buckets without double-counting subtotals;
   - take the latest value when a document revises itself;
   - report the stated total even when the document's own math is wrong.

   Providers sit behind a small interface: Claude by default, or Gemini with `--provider gemini`. Switching models is a flag, which makes cost/accuracy comparisons cheap. If the reply is not valid JSON, the model is re-prompted once with the parse error.
3. **Normalize** (`schema.py`, pydantic). The LLM output is never trusted as-is:
   - `"$1,234.50"`, `"(1,545.00)"`, `"Oct 3rd, 2024"` are coerced into floats and ISO dates;
   - confidences are clamped to [0, 1], and missing keys become explicit nulls;
   - anything that cannot be coerced becomes null with confidence 0, so the error surfaces downstream instead of being silently wrong;
   - `overall_confidence` is computed by the code, not taken from the model.
4. **Validate** (`validate.py`). These rules run deterministically:

   | Check | Severity |
   |---|---|
   | Required fields present (CO #, project, date, contractor, total) | error |
   | Cost buckets sum to the stated total (±max($1, 0.5%)) | error |
   | New completion date not before issue date | error |
   | Duplicate CO number within a batch (format-insensitive: `CO-0082` = `82`) | error |
   | Markup > 25% of direct cost; deduct CO with positive lines; implausible schedule days; future date | warning |
   | **Grounding**: for text inputs, the CO number and total must literally appear in the source, and a named approver requires an approval/signature line | warning |

   A record goes to **human review** if it has any error or warning, or any extracted field under 0.7 confidence. The output lists exactly which fields to check, so a reviewer looks at 2 fields, not 20.

## Evaluation

`python evaluate.py` runs all 8 documents in `samples/` and scores them against `samples/ground_truth.json`.

The test set covers:
- clean and informal text;
- a nested-subtotal roll-up;
- a **deduct CO** with negative amounts and an add-back;
- a **planted math error**;
- an **email thread** whose price was revised from $14,800 to $9,050 and which was never signed;
- a **digital PDF** with a table layout;
- a **scanned image-only PDF** with skew, speckle noise, JPEG artefacts and a handwritten note.

Results with `gemini-2.5-flash` (free tier). The default Claude path uses the same code; I could not benchmark it without API credit:

| Metric | Result |
|---|---|
| Field accuracy | 99% (102/103) |
| Validation verdict correct | 8/8 |
| Scanned PDF (vision path) | 100% of fields |
| Wrong fields routed to review | 1/1 |

**The one miss is the most instructive result.** The email-thread CO is unsigned, but the model returned the owner's PM ("Rachel Kim") as `approved_by`:

- **Run 1:** confidence 0.6, below the 0.7 threshold, so it was routed to review. The layered design worked.
- **Run 2:** the same wrong answer at confidence **0.8**, which would have passed the threshold. **Self-reported confidence did not catch a confidently wrong model.**

**Fix:** I added two layers.
- A deterministic evidence check: a named approver requires an approval/signature line ("Approved", "Accepted", "Auth", "Signatures") in the source. It needs no model judgement, and it now flags both runs. It fires on none of the other 7 documents.
- A prompt rule that people who requested, priced or received a CO are not its approver. It was added *after* seeing this failure, so it is not reflected in the scored run. I'll re-run once the free-tier daily quota resets.

Accuracy figures above come from run 1, re-validated with the final code (`python evaluate.py --results eval/results.json`).

## Failure modes & mitigations

| Failure mode | What goes wrong | Mitigation here | Residual risk |
|---|---|---|---|
| **Hallucinated or "helpful" values** | The model fills a field that isn't there (the unsigned approver above, once at 0.8 confidence) | Null-not-guess rule; review below 0.7 confidence; evidence checks for CO #, total and approver | Evidence checks cover text inputs and three fields; scanned docs rely on confidence |
| **Self-reported confidence is uncalibrated** | The model says 0.8 and is wrong (observed, run 2) | Deterministic checks (math, dates, evidence) give signals independent of the model; overall score computed in code | 97/97 fields at ≥0.9 confidence were right in run 1, but n is small. Needs a larger labelled set to calibrate thresholds per field |
| **Cost bucket ambiguity** | "Excavation & shoring": labor, equipment or other? | Fixed buckets plus an `other` bucket; the validator checks the *sum*, so a mis-bucketed line can't hide a wrong total | Per-bucket values can be debatable; the ground truth doesn't score genuinely ambiguous buckets |
| **Document's own math is wrong** | Stated total ≠ line items | Model told to report the total *as stated*; validator flags the mismatch as an error | — |
| **Deduct / credit COs** | Sign errors: credits read as adds | Prompt rule plus a sign-consistency warning | Mixed add/deduct COs need line-level output (future) |
| **Revisions and email threads** | Picks the first estimate instead of the final one | "Latest agreed value" rule; tested on a $14,800 → $9,050 thread | Long threads with out-of-order quoting |
| **Scanned / low-quality input** | OCR noise, skew, handwriting | Native vision input instead of an OCR pipeline; tested on a degraded scan | Very poor scans: confidence drops and the record goes to review, but no image pre-processing yet |
| **Invalid JSON** | Prose or code fences instead of JSON | Fence stripping, JSON mode (Gemini), one corrective re-prompt; a bad document never stops the batch | — |
| **Ambiguous dates** | "11/12/24" (US vs. EU); missing year | ISO normalization; year inferred from other dates with lower confidence | US date order is assumed |
| **Duplicates** | The same CO submitted twice in different formats | Normalized CO-number dedup | Only within a batch; production needs a DB uniqueness check |
| **Rate limits / outages** | 429/5xx from the API | Exponential backoff honouring the server's `retryDelay`; per-document error isolation | — |
| **Non-determinism** | Two runs differ (same wrong approver at 0.6 vs. 0.8 confidence; overall confidence varied) | Temperature 0; deterministic checks don't vary between runs | One scored run is not a guarantee; production evaluation should average several runs |

## What I'd do next with real Sledge data

1. **Bigger labelled set** from real customer COs, then tune the review threshold per field to hit a target precision.
2. **Line-item output**: return every line, not just bucket sums, so the reviewer UI can highlight the source line for each number.
3. **Grounding with evidence spans**: ask the model to cite the source snippet for each field and verify it, which extends grounding to every field and to scanned docs.
4. **Model routing**: a cheap model first, escalating to a stronger model only for low-confidence or failed-validation documents.
5. **Review loop**: human corrections flow back as labelled data for evaluation and few-shot examples.

## Stack

Python 3.10+ · Anthropic Claude (`claude-opus-5-5` default) / Google Gemini (`gemini-2.5-flash`) · pydantic v2 · pdfplumber · pytest (42 offline tests, CI on 3.10–3.12)
