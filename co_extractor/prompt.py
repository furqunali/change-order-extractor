"""Extraction prompt. One prompt for every provider and input mode."""

from .schema import REASON_CATEGORIES

_SCHEMA = """{
  "change_order_number": {"value": "...", "confidence": 0.0},
  "project_name": {"value": "...", "confidence": 0.0},
  "date_issued": {"value": "YYYY-MM-DD or null", "confidence": 0.0},
  "contractor_name": {"value": "...", "confidence": 0.0},
  "owner_name": {"value": "...", "confidence": 0.0},
  "scope_description": {"value": "one or two sentences", "confidence": 0.0},
  "reason_code": {"value": "reason as written in the document", "confidence": 0.0},
  "reason_category": {"value": "one of the categories below", "confidence": 0.0},
  "cost_breakdown": {
    "labor": {"value": 0.00, "confidence": 0.0},
    "materials": {"value": 0.00, "confidence": 0.0},
    "equipment": {"value": 0.00, "confidence": 0.0},
    "overhead_markup": {"value": 0.00, "confidence": 0.0},
    "other": {"value": 0.00, "confidence": 0.0},
    "total": {"value": 0.00, "confidence": 0.0}
  },
  "schedule_impact_days": {"value": 0, "confidence": 0.0},
  "new_completion_date": {"value": "YYYY-MM-DD or null", "confidence": 0.0},
  "approved_by": {"value": "...", "confidence": 0.0},
  "contractor_representative": {"value": "...", "confidence": 0.0}
}"""

_RULES = f"""Rules:
- Use null for any field that is not in the document. Never guess or invent.
- Confidence (0.0-1.0) reflects how clearly the value is stated:
  0.9-1.0 explicitly labelled; 0.7-0.89 present but ambiguous;
  0.5-0.69 inferred from context; below 0.5 weak signal.
- Dates: normalize to YYYY-MM-DD. If the year is missing, infer it from other
  dates in the document and lower the confidence.
- Money: numbers only (no $ or commas). A DEDUCT / CREDIT change order has
  NEGATIVE amounts and a negative total.
- Cost buckets: map every line item to labor, materials, equipment,
  overhead_markup (overhead, profit, fee, general conditions, markup, bond) or
  other (permits, subcontracts, anything else). Sum items that share a bucket.
  Never double-count subtotals. The buckets should add up to the stated total;
  if the document's own math is wrong, still report the total AS STATED.
- If the document revises an amount or date (e.g. "revised", "final", a later
  email in a thread), report the latest agreed value.
- schedule_impact_days: calendar days added (negative if time is reduced,
  0 if the document says no time impact, null if not mentioned).
- approved_by: only a person shown approving, accepting, authorizing or
  signing the change order. Someone who requested, priced, sent or received it
  is NOT the approver; if it is not yet approved, use null.
- reason_category must be one of: {", ".join(REASON_CATEGORIES)}.
- Return ONLY the JSON object, no explanation."""


def build_prompt(text: str = None) -> str:
    header = ("You are a construction document parser specializing in change orders.\n"
              "Extract the fields below and return ONLY valid JSON in this structure:\n")
    body = f"{header}{_SCHEMA}\n\n{_RULES}\n"
    if text is None:
        return body + "\nThe change order is attached."
    return body + f"\nCHANGE ORDER TEXT:\n{text}\n"
