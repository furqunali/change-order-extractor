"""
Deterministic validation on top of the (schema-normalized) LLM output.

Errors   -> the record is wrong or unusable as-is   (passed = False)
Warnings -> the record is plausible but suspicious  (passed stays True)
Either one, or any extracted field under REVIEW_THRESHOLD confidence, routes
the record to human review with the exact fields to look at.

LLM confidence is self-reported, so the grounding check below adds an
independent signal: for text inputs, key values must literally appear in the
source document.
"""

import re
from datetime import date

REQUIRED = ["change_order_number", "project_name", "date_issued", "contractor_name"]
COST_PARTS = ["labor", "materials", "equipment", "overhead_markup", "other"]
REVIEW_THRESHOLD = 0.7
MAX_MARKUP_RATIO = 0.25   # overhead + profit above 25% of direct cost is unusual
MAX_SCHEDULE_DAYS = 365

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_APPROVAL = re.compile(r"\b(approv\w*|accept\w*|authori[sz]\w*|auth|signatures?|signed by)\b", re.I)


def _val(data, path):
    node = data
    for key in path.split("."):
        node = (node or {}).get(key)
    return (node or {}).get("value")


def _conf(data, path):
    node = data
    for key in path.split("."):
        node = (node or {}).get(key)
    return (node or {}).get("confidence") or 0.0


def validate_extraction(data: dict, source_text: str = None) -> dict:
    errors, warnings = [], []

    # 1. Required fields
    for field in REQUIRED:
        if _val(data, field) is None:
            errors.append(f"Missing required field: {field}")
        elif _conf(data, field) < 0.5:
            warnings.append(f"Low confidence on: {field} ({_conf(data, field)})")

    # 2. Cost arithmetic: buckets must add up to the stated total
    total = _val(data, "cost_breakdown.total")
    parts = [_val(data, f"cost_breakdown.{p}") or 0 for p in COST_PARTS]
    if total is None:
        errors.append("Missing cost total")
    else:
        calculated = round(sum(parts), 2)
        tolerance = max(1.0, abs(total) * 0.005)
        if abs(calculated - total) > tolerance:
            errors.append(f"Cost math mismatch: line items sum to {_usd(calculated)} "
                          f"but stated total is {_usd(total)} (diff {_usd(calculated - total)})")
        # Deduct CO: everything should share the total's sign
        if total < 0 and any(p > 0 for p in parts):
            warnings.append("Deduct change order contains positive line items")

        # 3. Markup sanity
        direct = sum(_val(data, f"cost_breakdown.{p}") or 0 for p in ["labor", "materials", "equipment", "other"])
        markup = _val(data, "cost_breakdown.overhead_markup") or 0
        if direct and markup and markup / direct > MAX_MARKUP_RATIO:
            warnings.append(f"Overhead/markup is {markup / direct:.0%} of direct cost (>{MAX_MARKUP_RATIO:.0%})")

    # 4. Dates and schedule
    issued, completion = _val(data, "date_issued"), _val(data, "new_completion_date")
    if issued and completion and completion < issued:  # ISO strings compare correctly
        errors.append(f"New completion date {completion} is before issue date {issued}")
    if issued and issued > date.today().isoformat():
        warnings.append(f"Issue date {issued} is in the future")
    days = _val(data, "schedule_impact_days")
    if days is not None and abs(days) > MAX_SCHEDULE_DAYS:
        warnings.append(f"Schedule impact of {days} days looks implausible")

    # 5. Grounding: key values must be traceable to the source text
    grounded = None
    if source_text:
        grounded = True
        co = _val(data, "change_order_number")
        if co and _alnum(co) not in _alnum(source_text):
            warnings.append(f"CO number {co!r} not found verbatim in source")
            grounded = False
        if total is not None:
            amounts = {round(float(n.replace(",", "")), 2) for n in _NUMBER.findall(source_text)
                       if n.replace(",", "").replace(".", "", 1).isdigit()}
            if round(abs(total), 2) not in amounts:
                warnings.append(f"Total {_usd(total)} not found verbatim in source")
                grounded = False
        # An approver needs an approval/signature line, not just a name in the doc
        approver = _val(data, "approved_by")
        if approver and not _APPROVAL.search(source_text):
            warnings.append(f"approved_by {approver!r} but the source has no approval/signature line")
            grounded = False

    # 6. Human-review routing (a $0 cost bucket just means "not on this CO")
    review_fields = sorted(
        name for name, conf, value in _leaf_fields(data)
        if value is not None and conf < REVIEW_THRESHOLD
        and not (name.startswith("cost_breakdown.") and value == 0)
    )
    data["_validation"] = {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "grounded": grounded,
        "needs_review": bool(errors or warnings or review_fields),
        "review_fields": review_fields,
    }
    return data


def flag_duplicates(results: list) -> None:
    """Flag change orders whose CO number already appeared in this batch."""
    seen = {}
    for r in results:
        if r["status"] != "success":
            continue
        data = r["data"]
        co = _val(data, "change_order_number")
        if not co:
            continue
        key = _alnum(co).lstrip("co").lstrip("0") or _alnum(co)
        if key in seen:
            v = data["_validation"]
            v["errors"].append(f"Duplicate CO number {co} (same as {seen[key]})")
            v["passed"], v["needs_review"] = False, True
        else:
            seen[key] = r["source"]


def _usd(x: float) -> str:
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def _alnum(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _leaf_fields(data):
    for name, node in data.items():
        if name.startswith("_") or not isinstance(node, dict):
            continue
        if "confidence" in node:
            yield name, node.get("confidence") or 0.0, node.get("value")
        else:
            for sub, leaf in node.items():
                if isinstance(leaf, dict) and "confidence" in leaf:
                    yield f"{name}.{sub}", leaf.get("confidence") or 0.0, leaf.get("value")
