"""Schema normalization: the LLM's raw JSON is coerced into known types."""
import pytest

from co_extractor.schema import normalize, parse_date, parse_money


@pytest.mark.parametrize("raw,expected", [
    ("$12,400.00", 12400.0), ("(1,545.00)", -1545.0), ("-$500", -500.0),
    (26785, 26785.0), ("", None), (None, None), ("n/a", None),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Oct 3rd, 2024", "2024-10-03"), ("11/22/24", "2024-11-22"),
    ("December 6 2024", "2024-12-06"), ("2025-01-21", "2025-01-21"), (None, None),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_normalize_fills_missing_fields_and_clamps_confidence():
    d = normalize({"change_order_number": {"value": "CO-1", "confidence": 1.7}})
    assert d["change_order_number"] == {"value": "CO-1", "confidence": 1.0}
    assert d["owner_name"] == {"value": None, "confidence": 0.0}
    assert d["cost_breakdown"]["total"] == {"value": None, "confidence": 0.0}


def test_uncoercible_value_becomes_null_with_zero_confidence():
    d = normalize({"date_issued": {"value": "sometime soon", "confidence": 0.9},
                   "cost_breakdown": {"total": {"value": "about ten grand", "confidence": 0.9}}})
    assert d["date_issued"] == {"value": None, "confidence": 0.0}
    assert d["cost_breakdown"]["total"] == {"value": None, "confidence": 0.0}


def test_bare_values_and_category_mapping():
    d = normalize({"schedule_impact_days": "6", "reason_category": {"value": "owner request", "confidence": 0.9}})
    assert d["schedule_impact_days"]["value"] == 6
    assert d["reason_category"]["value"] == "Owner Request"
    assert normalize({"reason_category": {"value": "weather", "confidence": 0.8}})["reason_category"]["value"] == "Other"


def test_overall_confidence_is_computed_not_trusted():
    d = normalize({"change_order_number": {"value": "1", "confidence": 1.0},
                   "project_name": {"value": "P", "confidence": 0.5},
                   "overall_confidence": 0.99})
    assert d["overall_confidence"] == 0.75
    assert 0 < d["field_coverage"] < 1


def test_zero_cost_buckets_do_not_drag_overall_confidence():
    d = normalize({"change_order_number": {"value": "1", "confidence": 1.0},
                   "cost_breakdown": {"equipment": {"value": 0, "confidence": 0.1},
                                      "total": {"value": 100, "confidence": 1.0}}})
    assert d["overall_confidence"] == 1.0
