"""Offline tests for the validation layer (no API key needed)."""
from extractor import validate_extraction, flag_duplicates, _strip_fences


def field(value, confidence=0.95):
    return {"value": value, "confidence": confidence}


def base_record(**cost):
    costs = {k: field(v) for k, v in cost.items()}
    return {
        "change_order_number": field("CO-1"),
        "project_name": field("Test Project"),
        "date_issued": field("2024-10-03"),
        "contractor_name": field("Acme"),
        "cost_breakdown": costs,
    }


def test_clean_record_passes():
    d = validate_extraction(base_record(labor=100, materials=50, total=150))
    assert d["_validation"]["passed"]


def test_other_bucket_counts_toward_total():
    # Permit fee lives in "other" — must not trigger a false variance flag
    d = validate_extraction(base_record(labor=14400, materials=19200,
                                        overhead_markup=5167.5, other=850,
                                        total=39617.5))
    assert d["_validation"]["passed"]


def test_cost_variance_flagged():
    d = validate_extraction(base_record(labor=100, total=200))
    assert not d["_validation"]["passed"]
    assert "Cost math variance" in d["_validation"]["issues"][0]


def test_missing_and_low_confidence_flagged():
    rec = base_record(total=0)
    rec["date_issued"] = field(None, 0.0)
    rec["contractor_name"] = field("Acme?", 0.3)
    del rec["project_name"]
    issues = validate_extraction(rec)["_validation"]["issues"]
    assert any("project_name" in i for i in issues)
    assert any("date_issued" in i for i in issues)
    assert any("Low confidence on: contractor_name" in i for i in issues)


def test_duplicate_co_numbers_flagged():
    a = validate_extraction(base_record(total=0))
    b = validate_extraction(base_record(total=0))
    b["change_order_number"] = field("co 1")  # same CO, different formatting
    results = [{"input_index": 1, "status": "success", "data": a},
               {"input_index": 2, "status": "success", "data": b}]
    flag_duplicates(results)
    assert a["_validation"]["passed"]
    assert not b["_validation"]["passed"]
    assert "Duplicate CO number" in b["_validation"]["issues"][0]


def test_strip_fences():
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_fences('{"a": 1}') == '{"a": 1}'
