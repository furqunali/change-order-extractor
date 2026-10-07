"""
Typed output schema (pydantic v2).

The LLM's raw JSON is never trusted as-is: every field is coerced into a
known type ("$1,234.50" -> 1234.5, "Nov 3 2024" -> "2024-11-03"), confidences
are clamped to [0, 1], and missing keys become explicit nulls. If a value
cannot be coerced it is set to null and its confidence is zeroed, so the
validation layer sees the problem instead of a silently wrong value.
"""

import re
from datetime import date, datetime
from typing import Any, Callable, ClassVar, Optional

from pydantic import BaseModel, Field, model_validator

REASON_CATEGORIES = [
    "Differing Site Conditions",
    "Owner Request",
    "Design Error/Omission",
    "Code/Regulatory",
    "Emergency/Unforeseen",
    "Value Engineering",
    "Other",
]

_DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%B %d, %Y", "%B %d %Y",
    "%b %d, %Y", "%b %d %Y", "%d %B %Y", "%b. %d, %Y",
]


def parse_money(v: Any) -> Optional[float]:
    """'$1,234.50' -> 1234.5, '(500)' / '-$500' -> -500.0, None/'' -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v).strip()
    if not s or s.lower() in {"null", "none", "n/a", "na", "-"}:
        return None
    negative = s.startswith("(") and s.endswith(")") or "-" in s.split("$")[0] or "credit" in s.lower()
    digits = re.sub(r"[^0-9.]", "", s)
    if not digits or digits.count(".") > 1:
        raise ValueError(f"not a money value: {v!r}")
    amount = round(float(digits), 2)
    return -amount if negative else amount


def parse_date(v: Any) -> Optional[str]:
    """Normalize common date spellings to ISO YYYY-MM-DD."""
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", str(v).strip())
    if not s or s.lower() in {"null", "none", "n/a"}:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {v!r}")


class _Field(BaseModel):
    value: Any = None
    confidence: float = 0.0

    coerce: ClassVar[Callable] = staticmethod(lambda v: v)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, raw: Any) -> dict:
        if not isinstance(raw, dict):  # model returned a bare value
            raw = {"value": raw, "confidence": 0.5}
        try:
            conf = float(raw.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        conf = min(max(conf, 0.0), 1.0)
        try:
            value = cls.coerce(raw.get("value"))
        except (TypeError, ValueError):
            value, conf = None, 0.0  # uncoercible -> surfaced as missing
        return {"value": value, "confidence": round(conf, 3)}


class TextField(_Field):
    value: Optional[str] = None
    coerce: ClassVar[Callable] = staticmethod(lambda v: (str(v).strip() or None) if v is not None else None)


class MoneyField(_Field):
    value: Optional[float] = None
    coerce: ClassVar[Callable] = staticmethod(parse_money)


class DateField(_Field):
    value: Optional[str] = None
    coerce: ClassVar[Callable] = staticmethod(parse_date)


class IntField(_Field):
    value: Optional[int] = None
    coerce: ClassVar[Callable] = staticmethod(lambda v: None if v in (None, "") else int(round(float(str(v).replace(",", "")))))


class CategoryField(_Field):
    value: Optional[str] = None

    @staticmethod
    def coerce(v):
        if v is None:
            return None
        for cat in REASON_CATEGORIES:
            if str(v).strip().lower() == cat.lower():
                return cat
        return "Other"


class CostBreakdown(BaseModel):
    labor: MoneyField = Field(default_factory=MoneyField)
    materials: MoneyField = Field(default_factory=MoneyField)
    equipment: MoneyField = Field(default_factory=MoneyField)
    overhead_markup: MoneyField = Field(default_factory=MoneyField)
    other: MoneyField = Field(default_factory=MoneyField)
    total: MoneyField = Field(default_factory=MoneyField)


class ChangeOrder(BaseModel):
    change_order_number: TextField = Field(default_factory=TextField)
    project_name: TextField = Field(default_factory=TextField)
    date_issued: DateField = Field(default_factory=DateField)
    contractor_name: TextField = Field(default_factory=TextField)
    owner_name: TextField = Field(default_factory=TextField)
    scope_description: TextField = Field(default_factory=TextField)
    reason_code: TextField = Field(default_factory=TextField)
    reason_category: CategoryField = Field(default_factory=CategoryField)
    cost_breakdown: CostBreakdown = Field(default_factory=CostBreakdown)
    schedule_impact_days: IntField = Field(default_factory=IntField)
    new_completion_date: DateField = Field(default_factory=DateField)
    approved_by: TextField = Field(default_factory=TextField)
    contractor_representative: TextField = Field(default_factory=TextField)
    overall_confidence: float = 0.0
    field_coverage: float = 0.0

    @model_validator(mode="after")
    def _score(self) -> "ChangeOrder":
        """Compute overall confidence ourselves instead of trusting the model's
        arithmetic: mean confidence over the fields that were actually found
        (null fields and $0 cost buckets excluded)."""
        found = [f for name, f in iter_fields(self) if is_present(name, f.value)]
        total = len(list(iter_fields(self)))
        self.overall_confidence = round(sum(f.confidence for f in found) / len(found), 3) if found else 0.0
        self.field_coverage = round(len(found) / total, 3) if total else 0.0
        return self


def iter_fields(co: ChangeOrder):
    """Yield (dotted_name, field) for every leaf field, cost buckets included."""
    for name in ChangeOrder.model_fields:
        attr = getattr(co, name)
        if isinstance(attr, _Field):
            yield name, attr
        elif isinstance(attr, CostBreakdown):
            for sub in CostBreakdown.model_fields:
                yield f"cost_breakdown.{sub}", getattr(attr, sub)


def is_present(name: str, value) -> bool:
    """A $0 cost bucket means "not on this change order", not an extracted value."""
    return value is not None and not (name.startswith("cost_breakdown.") and value == 0)


def normalize(raw: dict) -> dict:
    """Raw LLM JSON -> schema-validated, type-normalized dict."""
    return ChangeOrder.model_validate(raw or {}).model_dump()
