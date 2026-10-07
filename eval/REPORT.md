# Evaluation Report

*Generated 2026-10-07 by `python evaluate.py --provider gemini` (model `gemini-2.5-flash`) on the 8 documents in `samples/`; saved model outputs re-validated with the current code (`--results`).*

## Headline

| Metric | Result |
|---|---|
| Field-level accuracy | **99%** (103 labelled fields) |
| Documents processed successfully | 8/8 |
| Validation verdict correct (good docs pass, planted error caught) | 8/8 |
| Accuracy when confidence ≥ 0.9 | 100% (n=97) |
| Accuracy when confidence < 0.9 | 0% (n=1) |
| Wrong fields routed to human review | 1/1 |

## Per document

| Document | Input mode | What makes it hard | Field accuracy | Validation | Review? |
|---|---|---|---|---|---|
| `co_047_riverside_sewer_reroute.txt` | text | clean text | 100% | ✓ passed | no |
| `co_0082_hotel_fire_emergency.txt` | text | informal lower-case text; missing fields; permit fee | 100% | ✓ passed | no |
| `co_011_school_footings.txt` | text | nested subtotals; multi-bucket roll-up | 100% | ✓ passed | no |
| `co_007_deduct_value_engineering.txt` | text | deduct / credit (negative amounts); dot leaders; net-credit with an add-back | 100% | ✓ passed | no |
| `co_118_math_error.txt` | text | PLANTED ERROR: line items sum to $11,000, stated total $13,500 | 100% | ✗ Cost math mismatch: line items sum to $11,000.00 but stated total is $13,500.00 (diff -$2,500.00) | yes |
| `co_052_email_thread.eml` | text | email thread; revised price ($14,800 -> $9,050 final); unsigned (no approver) | 92% | ✓ passed | yes |
| `co_215_digital_form.pdf` | pdf_text | digital PDF; table layout | 100% | ✓ passed | no |
| `co_031_scanned.pdf` | pdf_vision | scanned image PDF (no text layer); skew + noise + JPEG artefacts; handwritten note | 100% | ✓ passed | no |

## Per field

| Field | Accuracy |
|---|---|
| `approved_by` | 88% |
| `change_order_number` | 100% |
| `contractor_name` | 100% |
| `contractor_representative` | 100% |
| `cost_breakdown.labor` | 100% |
| `cost_breakdown.materials` | 100% |
| `cost_breakdown.total` | 100% |
| `date_issued` | 100% |
| `new_completion_date` | 100% |
| `owner_name` | 100% |
| `project_name` | 100% |
| `reason_category` | 100% |
| `schedule_impact_days` | 100% |

## Every miss

| Document | Field | Expected | Got | Confidence |
|---|---|---|---|---|
| `co_052_email_thread.eml` | `approved_by` | None | Rachel Kim | 0.6 |
