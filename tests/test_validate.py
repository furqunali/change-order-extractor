"""Deterministic validation rules."""
from co_extractor.schema import normalize
from co_extractor.validate import flag_duplicates, validate_extraction


def f(value, confidence=0.95):
    return {"value": value, "confidence": confidence}


def record(**overrides):
    raw = {
        "change_order_number": f("CO-1"), "project_name": f("Test"),
        "date_issued": f("2024-10-03"), "contractor_name": f("Acme"),
        "new_completion_date": f("2024-11-01"),
        "cost_breakdown": {"labor": f(100), "materials": f(50), "overhead_markup": f(15), "total": f(165)},
    }
    raw.update(overrides)
    return normalize(raw)


def v(data, text=None):
    return validate_extraction(data, source_text=text)["_validation"]


def test_clean_record_passes_without_review():
    r = v(record())
    assert r["passed"] and not r["needs_review"] and r["errors"] == [] and r["warnings"] == []


def test_math_mismatch_is_an_error():
    r = v(record(cost_breakdown={"labor": f(4000), "materials": f(6000), "overhead_markup": f(1000), "total": f(13500)}))
    assert not r["passed"]
    assert "Cost math mismatch" in r["errors"][0] and "-$2,500.00" in r["errors"][0]


def test_rounding_within_tolerance_passes():
    assert v(record(cost_breakdown={"labor": f(100.004), "total": f(100)}))["passed"]


def test_deduct_change_order_passes():
    r = v(record(cost_breakdown={"labor": f(-4450), "materials": f(-9150), "equipment": f(-1850),
                                 "overhead_markup": f(-1545), "total": f(-16995)}))
    assert r["passed"] and r["warnings"] == []


def test_deduct_with_positive_lines_warns():
    r = v(record(cost_breakdown={"labor": f(500), "materials": f(-1500), "total": f(-1000)}))
    assert r["passed"] and any("Deduct" in w for w in r["warnings"])


def test_missing_required_and_missing_total():
    r = v(record(contractor_name=f(None, 0.0), cost_breakdown={}))
    assert "Missing required field: contractor_name" in r["errors"]
    assert "Missing cost total" in r["errors"]


def test_completion_before_issue_is_an_error():
    r = v(record(new_completion_date=f("2024-09-01")))
    assert any("before issue date" in e for e in r["errors"])


def test_excessive_markup_warns():
    r = v(record(cost_breakdown={"labor": f(100), "overhead_markup": f(50), "total": f(150)}))
    assert r["passed"] and any("Overhead/markup" in w for w in r["warnings"])


def test_low_confidence_fields_routed_to_review_but_zero_buckets_ignored():
    data = record(approved_by=f("Rachel Kim", 0.6))
    data["cost_breakdown"]["equipment"] = f(0.0, 0.1)
    r = v(data)
    assert r["passed"] and r["needs_review"]
    assert r["review_fields"] == ["approved_by"]


def test_grounding_detects_values_not_in_source():
    source = "CHANGE ORDER CO-1 ... labor $100.00 materials $50.00 markup 15.00 TOTAL $165.00"
    assert v(record(), source)["grounded"] is True
    r = v(record(change_order_number=f("CO-9")), source)
    assert r["grounded"] is False and any("not found verbatim" in w for w in r["warnings"])


def test_duplicates_flagged_across_formatting():
    a = {"source": "a.txt", "status": "success", "data": validate_extraction(record())}
    b = {"source": "b.pdf", "status": "success", "data": validate_extraction(record(change_order_number=f("co 0001")))}
    flag_duplicates([a, b])
    assert a["data"]["_validation"]["passed"]
    assert not b["data"]["_validation"]["passed"]
    assert "Duplicate CO number" in b["data"]["_validation"]["errors"][0]


def test_approver_without_approval_line_is_flagged():
    unsigned = "CO-1 ... TOTAL $165.00 ... Need signed CO by Monday. - Rachel Kim, Owner's PM"
    r = v(record(approved_by=f("Rachel Kim", 0.8)), unsigned)  # confident, above review threshold
    assert r["needs_review"] and r["grounded"] is False
    assert any("no approval/signature line" in w for w in r["warnings"])
    signed = "CO-1 ... TOTAL $165.00 ... Approved by: Rachel Kim"
    assert v(record(approved_by=f("Rachel Kim", 0.8)), signed)["warnings"] == []
