# Change-Order Extraction Pipeline

**Author:** Furqan Ali  
**Task:** Sledge AI Engineer Application

A pipeline that extracts structured fields from messy construction change-order documents into validated JSON with confidence scores — powered by Claude AI, with Google Gemini (free tier) as a drop-in alternative provider.

---

## Features

- Extracts 14 fields (plus a 6-line cost breakdown) from unstructured change-order text
- Per-field confidence scores (0.0 – 1.0), low-confidence fields flagged for review
- Validation: required fields, cost arithmetic (>5% variance flagged), duplicate CO numbers
- Self-correcting: one re-prompt with the parse error if the model returns invalid JSON
- Handles inconsistent formatting, abbreviations and lower-case "emergency" style notes
- Pluggable LLM provider: Claude (default) or Gemini via `--provider gemini`
- Offline unit tests for the validation layer (`pytest`, no API key needed)

## Quick Start

```bash
git clone https://github.com/furqunali/change-order-extractor
cd change-order-extractor
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
python extractor.py              # model: claude-opus-5-5 (override with --model)
python -m pytest -q tests        # offline tests
```

### Free alternative: Gemini

No Anthropic credit? Get a free key at <https://aistudio.google.com/apikey> and run:

```bash
export GEMINI_API_KEY=your_key_here
python extractor.py --provider gemini          # default model: gemini-2.5-flash
```

The prompt, validation, re-prompt fallback and output format are identical across providers.

## Sample Run (real output)

Run on 7 Oct 2026 with `python extractor.py --provider gemini` (`gemini-2.5-flash`, free tier).
Full JSON: [`examples/sample_output_gemini.json`](examples/sample_output_gemini.json)

| CO | Project | Total | Confidence | Validation | Notes |
|---|---|---|---|---|---|
| CO-2024-047 | Riverside Commercial Complex – Phase 2 | $26,785.00 | 100% | ✓ passed | Clean, fully labelled form |
| 0082 | downtown hotel renovation 4th & main | $39,617.50 | 82% | ✓ passed | Lower-case "emergency" note; $850 permit fee → `other`; owner & contractor rep absent → `null` + low confidence (not guessed) |
| 2024-CO-011 | Sunset Ridge Elementary School Expansion | $37,308.00 | 94% | ✓ passed | Sub-items rolled up (concrete + rebar → materials, GC 8% + fee 5% → overhead); buckets sum exactly to total |

Excerpt (CO-2024-047):

```json
{
  "change_order_number": {
    "value": "CO-2024-047",
    "confidence": 1.0
  },
  "date_issued": {
    "value": "2024-10-03",
    "confidence": 1.0
  },
  "cost_breakdown": {
    "labor": {
      "value": 12400.0,
      "confidence": 1.0
    },
    "materials": {
      "value": 8750.0,
      "confidence": 1.0
    },
    "equipment": {
      "value": 3200.0,
      "confidence": 1.0
    },
    "overhead_markup": {
      "value": 2435.0,
      "confidence": 1.0
    },
    "other": {
      "value": 0.0,
      "confidence": 1.0
    },
    "total": {
      "value": 26785.0,
      "confidence": 1.0
    }
  },
  "schedule_impact_days": {
    "value": 6,
    "confidence": 1.0
  },
  "overall_confidence": 1.0,
  "_validation": {
    "passed": true,
    "issues": [],
    "issue_count": 0
  }
}
```

## See Also

- [WRITEUP.md](WRITEUP.md) — Full approach, failure modes & design decisions
