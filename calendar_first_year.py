"""Calendar-year initial partial-year adapter (SHADOW RESEARCH ONLY).

Run the ORIGINAL B+85 annual policy first, then prorate only living expenditure
over the inclusive remaining calendar days. Full-year PoS/Sticky remain unchanged
reference signals, not recalibrated short-horizon estimates.
"""
from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
import math

from policy.simple_annual_ledger import YearApproval

MODE = "CALENDAR_FIRST_YEAR_RESEARCH_V1"


def fraction_for(start_iso: str) -> tuple[int, int, float]:
    day = date.fromisoformat(start_iso)
    end_exclusive = date(day.year + 1, 1, 1)
    days = (end_exclusive - day).days
    total = (end_exclusive - date(day.year, 1, 1)).days
    if not 1 <= days <= total:
        raise ValueError("invalid first-year calendar period")
    return days, total, days / total


def prorate_first_year(full: YearApproval) -> tuple[YearApproval, dict]:
    o = full.opening
    days, total, f = fraction_for(o.decision_date)
    if o.age != o.start_age or o.year != int(o.decision_date[:4]) or full.mode != "SYNTHETIC_RESEARCH_ONLY":
        raise ValueError("proration requires first-year synthetic B85 approval")
    p = full.policy_preview
    annual_living = p.living_pool_paid_m
    bridge = p.bridge_from_cash_m
    if bridge < -1e-9 or bridge > annual_living + 1e-9:
        raise ValueError("unsupported annual cash bridge")
    cash_released = bridge * (1 - f)
    invest_released = (annual_living - bridge) * (1 - f)
    changed = replace(
        p,
        living_gross_authorized_m=p.living_gross_authorized_m * f,
        living_pool_required_m=p.living_pool_required_m * f,
        living_pool_paid_m=annual_living * f,
        bridge_from_cash_m=bridge * f,
        investment_before_return_m=p.investment_before_return_m + invest_released,
        safety_cash_before_return_m=p.safety_cash_before_return_m + cash_released,
        investment_next_start_m=p.investment_next_start_m + invest_released,
        safety_cash_next_start_m=p.safety_cash_next_start_m + cash_released,
    )
    reserved = changed.living_pool_paid_m + changed.car_paid_m + changed.extra_mandatory_paid_m
    if not math.isclose(o.investment_m + o.safety_cash_m,
                        reserved + changed.investment_before_return_m + changed.safety_cash_before_return_m,
                        abs_tol=1e-8, rel_tol=0):
        raise ArithmeticError("initial partial-year funding is not conserved")
    token = sha256(json.dumps({
        "annual_id": full.approval_id, "date": o.decision_date,
        "days": days, "total": total, "reserved_m": reserved,
        "invest_left_m": changed.investment_before_return_m,
        "cash_left_m": changed.safety_cash_before_return_m
    }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    result = YearApproval(o, changed, reserved, token, mode=MODE)
    metadata = {
        "contract": MODE, "period_start": o.decision_date,
        "period_end": f"{o.year}-12-31", "calendar_days": days,
        "calendar_year_days": total, "calendar_fraction": f,
        "full_year_living_budget_m": annual_living,
        "pos_full_year_reference_only": True,
        "car_and_mandatory_unprorated": True
    }
    return result, metadata


def validate_metadata(row: dict, first_year: int) -> None:
    a = row["approval"]
    o, p = a["opening"], a["policy_preview"]
    meta = row.get("calendar_first_year")
    days, total, f = fraction_for(o["decision_date"])
    if a.get("mode") != MODE or not isinstance(meta, dict) or meta.get("contract") != MODE:
        raise ValueError("first-year contract missing")
    if o["year"] != first_year or o["year"] != int(o["decision_date"][:4]):
        raise ValueError("first-year calendar mismatch")
    if meta.get("period_start") != o["decision_date"] or meta.get("period_end") != f"{first_year}-12-31":
        raise ValueError("first-year interval mismatch")
    if meta.get("calendar_days") != days or meta.get("calendar_year_days") != total:
        raise ValueError("partial-year day count mismatch")
    if not math.isclose(float(meta.get("calendar_fraction", -1)), f, abs_tol=1e-14):
        raise ValueError("partial-year ratio mismatch")
    yearly = meta.get("full_year_living_budget_m")
    if isinstance(yearly, bool) or not isinstance(yearly, (int, float)) or not math.isfinite(yearly):
        raise ValueError("full-year living reference invalid")
    if not math.isclose(p["living_pool_paid_m"], yearly * f, abs_tol=1e-8):
        raise ValueError("partial-year living budget mismatch")
    reserved = p["living_pool_paid_m"] + p["car_paid_m"] + p["extra_mandatory_paid_m"]
    if not math.isclose(reserved, a["spending_reserved_m"], abs_tol=1e-8):
        raise ValueError("partial-year reserved funds mismatch")
    if not math.isclose(o["investment_m"] + o["safety_cash_m"],
                        reserved + p["investment_before_return_m"] + p["safety_cash_before_return_m"],
                        abs_tol=1e-8):
        raise ValueError("partial-year total assets inconsistent")
