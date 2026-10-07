"""
Change-Order Extraction Pipeline
Author: Furqan Ali
Description: Extracts structured fields from messy change-order PDFs/text
             into validated JSON with confidence scores.

Providers:   claude (default, ANTHROPIC_API_KEY) or gemini (GEMINI_API_KEY,
             free tier). Select with --provider or CO_EXTRACTOR_PROVIDER.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

DEFAULT_MODELS = {"claude": "claude-opus-5-5", "gemini": "gemini-2.5-flash"}
PROVIDER = os.environ.get("CO_EXTRACTOR_PROVIDER", "claude").lower()
MODEL = os.environ.get("CO_EXTRACTOR_MODEL") or DEFAULT_MODELS.get(PROVIDER)
MAX_ATTEMPTS = 2  # first try + one corrective re-prompt on invalid JSON

_client = None


def get_client():
    """Create the Anthropic client on first use (reads ANTHROPIC_API_KEY)."""
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def configure(provider: str, model: str = None) -> None:
    """Switch provider/model at runtime (used by the CLI flags)."""
    global PROVIDER, MODEL
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"Unknown provider {provider!r}; use one of {list(DEFAULT_MODELS)}")
    PROVIDER = provider
    MODEL = model or os.environ.get("CO_EXTRACTOR_MODEL") or DEFAULT_MODELS[provider]


# ─────────────────────────────────────────────
# LLM providers — each takes a chat history of {"role", "content"} turns
# ("user"/"assistant") and returns the model's text reply.
# ─────────────────────────────────────────────
def _call_claude(messages: list) -> str:
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=messages,
    )
    return response.content[0].text


def _call_gemini(messages: list) -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set (free key: https://aistudio.google.com/apikey)")
    body = {
        "contents": [
            {"role": "model" if m["role"] == "assistant" else "user",
             "parts": [{"text": m["content"]}]}
            for m in messages
        ],
        # JSON mode; generous token budget because thinking tokens count against it
        "generationConfig": {"responseMimeType": "application/json",
                             "maxOutputTokens": 8192, "temperature": 0},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Gemini API error {e.code}: {detail[:300]}") from None
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


PROVIDERS = {"claude": _call_claude, "gemini": _call_gemini}

# ─────────────────────────────────────────────
# Sample messy change-order texts (realistic)
# ─────────────────────────────────────────────
SAMPLE_CHANGE_ORDERS = [
    """
    CHANGE ORDER #CO-2024-047
    Project: Riverside Commercial Complex – Phase 2
    Date: Oct 3rd, 2024
    Contractor: Meridian Build Group LLC
    Owner: Riverside Dev Partners

    Scope of Change:
    Due to unforeseen underground utility conflicts discovered during excavation
    at grid line E-7, contractor is required to reroute main sewer line approx
    85 linear feet to avoid conflict. This includes additional trenching, pipe,
    backfill and compaction per geotech specs.

    Cost Breakdown:
    Labor:     $12,400.00
    Materials: $8,750.00
    Equipment: $3,200.00
    Markup (10%): $2,435.00
    TOTAL ADD: $26,785.00

    Schedule Impact: 6 calendar days added to substantial completion.
    New Substantial Completion Date: November 14, 2024

    Reason Code: Differing Site Conditions
    Approved by: James Whitfield (Project Manager)
    Contractor Rep: Sara Munoz
    """,

    """
    change order request - emergency
    co number: 0082
    proj - downtown hotel renovation 4th & main
    date 11/22/24
    prime contractor: Summit Construction Inc.

    work description: fire suppression system upgrade required by city inspector
    on nov 20 inspection. existing heads dont meet current code, full floor 3 
    replacement needed. work must start immediately per fire marshal order.

    est cost:
    parts/materials $19,200
    labor 3 crews x 2 days = $14,400
    permit fees $850
    overhead & profit 15% = $5,167.50
    grand total = $39,617.50

    time impact - 4 days
    revised completion: December 6 2024
    reason: code compliance / inspector requirement
    auth: Mike Torres GM
    """,

    """
    CHANGE ORDER FORM
    Project Name: Sunset Ridge Elementary School Expansion
    CO #: 2024-CO-011
    Issued: September 15, 2024
    GC: Pinnacle Builders Corp
    Owner Rep: Dr. Angela Reyes, School Board

    Description of Work Added:
    Structural engineer identified inadequate footing depth at column grid B-3
    through B-9 after reviewing original drawings vs actual soil borings. 
    All 7 column footings must be deepened by 18 inches and reinforced per
    revised structural drawings SD-104 Rev B.

    Cost Summary:
    Direct Costs:
      Excavation & shoring:  $7,800.00
      Concrete (add'l):      $11,300.00
      Rebar & embeds:         $4,600.00
      Labor:                  $9,200.00
    Subtotal:                $32,900.00
    General Conditions (8%): $2,632.00
    Fee (5%):                $1,776.00
    TOTAL THIS CO:           $37,308.00

    Days Added: 9
    New Completion: October 28, 2024
    Category: Design Deficiency
    Signatures: Angela Reyes / Tom Harrington (PM)
    """
]


# ─────────────────────────────────────────────
# Extraction via LLM
# ─────────────────────────────────────────────
def extract_change_order(raw_text: str) -> dict:
    """Send raw change-order text to the configured LLM and get structured JSON back."""

    prompt = f"""You are a construction document parser specializing in change orders.

Extract ALL available fields from the change order text below and return ONLY valid JSON.
For each field, also provide a confidence score (0.0 to 1.0) based on how clearly the value appears in the text.

Required JSON structure:
{{
  "change_order_number": {{"value": "...", "confidence": 0.0}},
  "project_name": {{"value": "...", "confidence": 0.0}},
  "date_issued": {{"value": "YYYY-MM-DD or null", "confidence": 0.0}},
  "contractor_name": {{"value": "...", "confidence": 0.0}},
  "owner_name": {{"value": "...", "confidence": 0.0}},
  "scope_description": {{"value": "...", "confidence": 0.0}},
  "reason_code": {{"value": "...", "confidence": 0.0}},
  "cost_breakdown": {{
    "labor": {{"value": 0.00, "confidence": 0.0}},
    "materials": {{"value": 0.00, "confidence": 0.0}},
    "equipment": {{"value": 0.00, "confidence": 0.0}},
    "overhead_markup": {{"value": 0.00, "confidence": 0.0}},
    "other": {{"value": 0.00, "confidence": 0.0}},
    "total": {{"value": 0.00, "confidence": 0.0}}
  }},
  "schedule_impact_days": {{"value": 0, "confidence": 0.0}},
  "new_completion_date": {{"value": "YYYY-MM-DD or null", "confidence": 0.0}},
  "approved_by": {{"value": "...", "confidence": 0.0}},
  "contractor_representative": {{"value": "...", "confidence": 0.0}},
  "overall_confidence": 0.0
}}

Rules:
- Use null for missing fields, never guess
- overall_confidence = average of all field confidences
- Normalize dates to YYYY-MM-DD format
- Extract numeric values only for cost fields (no $ signs)
- Map each line item to labor / materials / equipment / overhead_markup
  (overhead, profit, fee, general conditions, markup); put anything that
  fits none of these (permits, fees, excavation subs, etc.) in "other" as a sum
- Do not double-count subtotals
- Return ONLY the JSON object, no explanation

CHANGE ORDER TEXT:
{raw_text}
"""

    messages = [{"role": "user", "content": prompt}]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw_json = _strip_fences(PROVIDERS[PROVIDER](messages))
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as e:
            if attempt == MAX_ATTEMPTS:
                raise
            # Fallback re-prompt: show the model its output and the parse error
            messages += [
                {"role": "assistant", "content": raw_json},
                {"role": "user", "content": f"That was not valid JSON ({e}). "
                 "Return ONLY the corrected JSON object, nothing else."},
            ]


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if the model wraps its JSON in them."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text


# ─────────────────────────────────────────────
# Validation layer
# ─────────────────────────────────────────────
def validate_extraction(data: dict) -> dict:
    """Validate extracted data and add validation flags."""
    
    issues = []

    # Check required fields
    required = ["change_order_number", "project_name", "date_issued", "contractor_name"]
    for field in required:
        if field not in data or not isinstance(data[field], dict):
            issues.append(f"Missing required field: {field}")
        else:
            if data[field].get("value") is None:
                issues.append(f"Missing required field: {field}")
            elif (data[field].get("confidence") or 0) < 0.5:
                issues.append(f"Low confidence on: {field} ({data[field]['confidence']})")

    # Validate cost math
    if "cost_breakdown" in data:
        cb = data["cost_breakdown"]
        try:
            calculated = sum([
                cb.get("labor", {}).get("value", 0) or 0,
                cb.get("materials", {}).get("value", 0) or 0,
                cb.get("equipment", {}).get("value", 0) or 0,
                cb.get("overhead_markup", {}).get("value", 0) or 0,
                cb.get("other", {}).get("value", 0) or 0,
            ])
            stated_total = cb.get("total", {}).get("value", 0) or 0
            if stated_total > 0:
                variance = abs(calculated - stated_total) / stated_total
                if variance > 0.05:  # >5% variance
                    issues.append(f"Cost math variance: {variance:.1%} (calculated ${calculated:,.2f} vs stated ${stated_total:,.2f})")
        except (TypeError, ZeroDivisionError):
            issues.append("Could not validate cost arithmetic")

    data["_validation"] = {
        "passed": len(issues) == 0,
        "issues": issues,
        "issue_count": len(issues)
    }

    return data


# ─────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────
def flag_duplicates(results: list) -> None:
    """Flag change orders whose CO number was already seen in this batch."""
    seen = {}
    for r in results:
        if r["status"] != "success":
            continue
        data = r["data"]
        co = (data.get("change_order_number") or {}).get("value")
        if not co:
            continue
        key = re.sub(r"[^a-z0-9]", "", str(co).lower())
        if key in seen:
            v = data["_validation"]
            v["issues"].append(f"Duplicate CO number {co} (same as input {seen[key]})")
            v["issue_count"] = len(v["issues"])
            v["passed"] = False
        else:
            seen[key] = r["input_index"]


def run_pipeline(texts: list) -> list:
    results = []
    for i, text in enumerate(texts, 1):
        print(f"\n{'='*60}")
        print(f"Processing Change Order {i}/{len(texts)}...")
        print('='*60)
        
        try:
            extracted = extract_change_order(text)
            validated = validate_extraction(extracted)
            
            result = {
                "input_index": i,
                "status": "success",
                "data": validated
            }

            # Print summary
            co_num = validated.get("change_order_number", {}).get("value", "N/A")
            project = validated.get("project_name", {}).get("value", "N/A")
            total = validated.get("cost_breakdown", {}).get("total", {}).get("value", 0)
            confidence = validated.get("overall_confidence") or 0
            passed = validated.get("_validation", {}).get("passed", False)

            print(f"  CO Number  : {co_num}")
            print(f"  Project    : {project}")
            print(f"  Total Cost : ${total:,.2f}" if total else f"  Total Cost : N/A")
            print(f"  Confidence : {confidence:.0%}")
            print(f"  Validation : {'✓ PASSED' if passed else '✗ ISSUES FOUND'}")
            
            if not passed:
                for issue in validated["_validation"]["issues"]:
                    print(f"    ⚠ {issue}")

        except json.JSONDecodeError as e:
            result = {"input_index": i, "status": "parse_error", "error": str(e)}
            print(f"  ERROR: Could not parse JSON response — {e}")
        except Exception as e:
            result = {"input_index": i, "status": "error", "error": str(e)}
            print(f"  ERROR: {e}")

        results.append(result)

    flag_duplicates(results)
    return results


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252

    parser = argparse.ArgumentParser(description="Change-order extraction pipeline")
    parser.add_argument("--provider", choices=sorted(DEFAULT_MODELS), default=PROVIDER)
    parser.add_argument("--model", help="override the provider's default model")
    args = parser.parse_args()
    configure(args.provider, args.model)
    print("Change-Order Extraction Pipeline")
    print("Author: Furqan Ali | Sledge AI Engineer Task")
    print(f"Provider: {PROVIDER} | Model: {MODEL}")
    print(f"Processing {len(SAMPLE_CHANGE_ORDERS)} sample change orders...\n")

    results = run_pipeline(SAMPLE_CHANGE_ORDERS)

    # Save full output
    output_file = "change_orders_output.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE")
    print(f"  Total processed : {len(results)}")
    print(f"  Successful      : {sum(1 for r in results if r['status'] == 'success')}")
    print(f"  Errors          : {sum(1 for r in results if r['status'] != 'success')}")
    print(f"  Output saved to : {output_file}")
    print('='*60)
