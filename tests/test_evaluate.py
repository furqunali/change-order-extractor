"""Scoring logic used by evaluate.py."""
import evaluate


def test_match_rules():
    assert evaluate.match("cost_breakdown.total", 39617.5, 39617.50)
    assert not evaluate.match("cost_breakdown.total", 39617.0, 39617.50)
    assert evaluate.match("change_order_number", "CO #0082", "82")
    assert evaluate.match("contractor_name", "Summit Construction, Inc.", "Summit Construction Inc.")
    assert evaluate.match("approved_by", "James Whitfield (Project Manager)", "James Whitfield")
    assert evaluate.match("owner_name", None, None)
    assert not evaluate.match("approved_by", "Rachel Kim", None)
    assert evaluate.match("reason_category", "Code/Regulatory", ["Code/Regulatory", "Emergency/Unforeseen"])
    assert not evaluate.match("date_issued", "2024-11-21", "2024-11-22")
