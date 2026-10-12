# GENERALIZED_RESEARCH_v1 annual ledger fork, not formal policy.
# 
# The finance mechanics follow unchanged simple_annual_ledger.py, but compute
# new approvals from personalized_research_annual/research_engine instead.
# Existing closed yearly records keep the original ledger path.
"""Research-only, minimal, two-phase yearly accounting for B+85.

Money is in *retirement-activation-year* real TWD millions (not nominal
TWD); use CPI-as-of normalization upstream. An approved envelope is not
an expense. Tax-inclusive returns are applied exactly once at year end.

This module preserves the B+85 decision engine and does not expose LIVE
or DOCUMENTED execution. Approval and close events are immutable pure data.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256
import json
import math
from typing import Optional

from policy.personalized_research_annual import AnnualInput, AnnualResult, decide_year
from policy import personalized_research_engine as policy

USD_TWD_ASSUMED = 30.0
EPS = 1e-8


def _amount(name: str, value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or v < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return v


def _return(name: str, value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or v < -1:
        raise ValueError(f"{name} must be finite and >= -1")
    return v


@dataclass(frozen=True)
class AnnualOpening:
    year: int
    decision_date: str
    age: int
    start_age: int
    investment_m: float
    safety_cash_m: float
    sticky_before: float = 1.0
    emergency_pending: bool = True
    prior_completed_net_real_return: Optional[float] = None
    planned_extra_m: float = 0.0
    # External income is intentionally excluded from this lightweight prototype.
    # Pension and other receipts require an explicit separate income source later.


@dataclass(frozen=True)
class YearApproval:
    opening: AnnualOpening
    policy_preview: AnnualResult
    spending_reserved_m: float
    approval_id: str
    mode: str = "SYNTHETIC_RESEARCH_ONLY"

    @property
    def living_budget_m(self) -> float:
        return self.policy_preview.living_pool_paid_m

    @property
    def car_budget_m(self) -> float:
        return self.policy_preview.car_paid_m

    @property
    def extra_budget_m(self) -> float:
        return self.policy_preview.extra_mandatory_paid_m


@dataclass(frozen=True)
class YearActual:
    living_paid_m: float
    car_paid_m: float = 0.0
    extra_paid_m: float = 0.0
    one_time_emergency_paid_m: float = 0.0
    # "net" means already after relevant tax, fund cost and fees;
    # "gross_scenario" means a simplified drag will be applied only once.
    portfolio_real_return: float = 0.0
    cash_real_return: float = 0.0
    return_basis: str = "net"
    modeled_annual_drag: float = 0.0
    closing_date: str = ""
    event_id: str = ""


@dataclass(frozen=True)
class YearClose:
    year: int
    age: int
    approval_id: str
    closing_event_id: str
    closing_event_sha256: str
    net_portfolio_real_return: float
    investment_next_m: float
    safety_cash_next_m: float
    sticky_next: float
    emergency_pending_next: bool
    actual_paid_total_m: float
    unused_budget_returned_to_cash_m: float
    investment_gain_m: float
    safety_cash_gain_m: float
    reconciliation_error_m: float
    mode: str = "SYNTHETIC_RESEARCH_ONLY"


def _stable_sha(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def approve_year(opening: AnnualOpening, cfg: policy.ModelConfig,
                 *, n_inner: int = 256, seed: int = 20261011,
                 prior_close: Optional[YearClose] = None) -> YearApproval:
    d = date.fromisoformat(opening.decision_date)
    if d.year != opening.year or d.year < 2026:
        raise ValueError("decision date does not match planning year")
    inv = _amount("investment", opening.investment_m)
    cash = _amount("safety cash", opening.safety_cash_m)
    _amount("planned extra", opening.planned_extra_m)
    if opening.start_age != cfg.start_age or cfg.use_charity:
        raise ValueError("B+85 candidate policy configuration mismatch")
    if prior_close is not None:
        if opening.year != prior_close.year + 1 or opening.age != prior_close.age + 1:
            raise ValueError("year and age must advance exactly once")
        if abs(inv - prior_close.investment_next_m) > EPS or abs(cash - prior_close.safety_cash_next_m) > EPS:
            raise ValueError("unexplained opening asset discontinuity")
        if abs(opening.sticky_before - prior_close.sticky_next) > EPS:
            raise ValueError("Sticky state did not roll forward")
        if opening.emergency_pending != prior_close.emergency_pending_next:
            raise ValueError("Emergency state did not roll forward")
        if opening.prior_completed_net_real_return is None or abs(opening.prior_completed_net_real_return-prior_close.net_portfolio_real_return)>EPS:
            raise ValueError("last year's return must match finalized prior year")
    elif opening.age != opening.start_age:
        raise ValueError("historical year close required before later-year approval")
    # Future portfolio/cash returns, and unforeseen emergency, are intentionally
    # NOT an input to the policy approval. This calls the unchanged B+85 policy.
    input_ = AnnualInput(
        decision_date=opening.decision_date, age=opening.age,
        retirement_start_age=opening.start_age,
        investment_start_m=inv, safety_cash_start_m=cash,
        sticky_before=opening.sticky_before,
        emergency_pending=opening.emergency_pending,
        previous_completed_real_portfolio_return=opening.prior_completed_net_real_return,
        external_income_m=0.0,
        extra_mandatory_m=opening.planned_extra_m,
        emergency_event_m=0.0,
        realized_year_portfolio_return=0.0,
        realized_year_cash_return=0.0,
        mode="SYNTHETIC",
    )
    preview = decide_year(input_, cfg, n_inner=n_inner, seed=seed)
    if not preview.plan_paid:
        raise ValueError("cannot authorize an unfunded spending plan")
    reserved = preview.living_pool_paid_m + preview.car_paid_m + preview.extra_mandatory_paid_m
    if abs(inv+cash-preview.investment_before_return_m-preview.safety_cash_before_return_m-reserved) > EPS:
        raise ArithmeticError("year-start budget funding is not conserved")
    approval_id=_stable_sha({"opening": opening.__dict__, "policy":preview.policy, "pos":preview.pos,
                             "living":preview.living_pool_paid_m,"car":preview.car_paid_m,"extra":preview.extra_mandatory_paid_m,
                             "invest_after":preview.investment_before_return_m,"cash_after":preview.safety_cash_before_return_m})
    return YearApproval(opening,preview,reserved,approval_id)


def close_year(approval:YearApproval, actual:YearActual) -> YearClose:
    d=date.fromisoformat(actual.closing_date)
    if d.year != approval.opening.year or d<date.fromisoformat(approval.opening.decision_date) or (d==date.fromisoformat(approval.opening.decision_date) and approval.mode!="CALENDAR_FIRST_YEAR_RESEARCH_V1"):
        raise ValueError("close must be after approval within same year")
    if not actual.event_id or len(actual.event_id)>128:
        raise ValueError("unique year-end closing event ID required")
    if actual.return_basis not in ("net", "gross_scenario"):
        raise ValueError("invalid return basis")
    paid_living=_amount("living paid",actual.living_paid_m)
    paid_car=_amount("car paid",actual.car_paid_m)
    paid_extra=_amount("mandatory extras paid",actual.extra_paid_m)
    emergency=_amount("emergency paid",actual.one_time_emergency_paid_m)
    if paid_living > approval.living_budget_m + EPS or paid_car>approval.car_budget_m + EPS or paid_extra>approval.extra_budget_m + EPS:
        raise ValueError("actual spending exceeded approved budget; require new approval")
    if emergency > 0 and not approval.opening.emergency_pending:
        raise ValueError("one-time emergency already consumed")
    if emergency > 0 and (emergency < 1.2-EPS or emergency>1.5+EPS):
        raise ValueError("one-time emergency outside configured 1.2–1.5m policy range")
    portfolio=_return("portfolio real return",actual.portfolio_real_return)
    cash_return=_return("cash real return",actual.cash_real_return)
    drag=_amount("modeled annual tax-cost drag",actual.modeled_annual_drag)
    if drag>=1:raise ValueError("annual drag must be below 100%")
    if actual.return_basis=="net" and drag!=0:
        raise ValueError("already-net return may not have a second tax/cost deduction")
    net_r=portfolio-drag if actual.return_basis=="gross_scenario" else portfolio
    if net_r < -1:raise ValueError("net return cannot be less than -100%")
    plan=approval.policy_preview
    before_i=plan.investment_before_return_m
    before_c=plan.safety_cash_before_return_m
    investment_gain=before_i*net_r
    cash_gain=before_c*cash_return
    invest=before_i+investment_gain
    cash=before_c+cash_gain
    actual_regular=paid_living+paid_car+paid_extra
    refund=approval.spending_reserved_m-actual_regular
    if refund<-EPS:raise ValueError("negative unspent envelope")
    # Unspent approved funds are held as a non-invested spending envelope all
    # year, returned to safety cash only on closing. No phantom return accrues.
    cash+=max(refund,0)
    cash_used=min(cash,emergency);cash-=cash_used
    remaining=emergency-cash_used
    invest_used=min(invest,remaining);invest-=invest_used
    if remaining-invest_used>EPS:
        raise ValueError("realized funds insufficient for emergency")
    paid=actual_regular+emergency
    err=(approval.opening.investment_m+approval.opening.safety_cash_m+investment_gain+cash_gain
         -paid-invest-cash)
    if abs(err)>EPS:raise ArithmeticError("year-end asset conservation failed")
    event_sha=_stable_sha({"approval_id":approval.approval_id,"actual":actual.__dict__,
                           "net_return":net_r,"usd_twd":USD_TWD_ASSUMED})
    return YearClose(approval.opening.year,approval.opening.age,
                     approval.approval_id,actual.event_id,event_sha,
                     net_r,invest,cash,plan.sticky_after,
                     approval.opening.emergency_pending and emergency<=0,
                     paid,max(refund,0),investment_gain,cash_gain,err)

@dataclass(frozen=True)
class YearEndBalances:
    """Ordinary year-end UX: just balances and expenses; no return input."""
    closing_date: str
    investment_end_m: float
    safety_cash_end_m: float
    living_paid_m: float
    car_paid_m: float = 0.0
    extra_paid_m: float = 0.0
    emergency_paid_m: float = 0.0
    event_id: str = ""  # system generates deterministic ID when blank


def nominal_to_activation_real(nominal_m: float,
                               current_cpi: float,
                               activation_cpi: float) -> float:
    """Convert actual nominal TWD to B85's retirement-start purchasing power."""
    for name, value in (("current CPI", current_cpi), ("activation CPI", activation_cpi)):
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError(name + " must be finite and positive")
    return _amount("nominal TWD million", nominal_m) * float(activation_cpi) / float(current_cpi)


def close_from_balances(approval: YearApproval, statement: YearEndBalances) -> YearClose:
    """Simple default close from asset statements; derive return internally.

    Requires all balances to have been CPI-normalized to retirement-activation
    purchasing power. Nonroutine flows/one-time Emergency get explicit review;
    otherwise a cash transfer can masquerade as a market return.
    """
    if statement.emergency_paid_m:
        raise ValueError("Emergency requires a reviewed cash/investment funding event")
    actual_living = _amount("living paid", statement.living_paid_m)
    actual_car = _amount("car paid", statement.car_paid_m)
    actual_extra = _amount("extra paid", statement.extra_paid_m)
    obs_i = _amount("observed investment balance", statement.investment_end_m)
    obs_c = _amount("observed cash balance", statement.safety_cash_end_m)
    if actual_living > approval.living_budget_m + EPS or actual_car > approval.car_budget_m + EPS or actual_extra > approval.extra_budget_m + EPS:
        raise ValueError("actual spending exceeded approval; manual review required")
    prev = approval.policy_preview
    refund = approval.spending_reserved_m - (actual_living + actual_car + actual_extra)
    invested = prev.investment_before_return_m
    cash_base = prev.safety_cash_before_return_m
    if invested <= EPS:
        if obs_i > EPS:raise ValueError("new investment asset appeared without a source")
        inferred_portfolio_return=0.0
    else:
        inferred_portfolio_return = obs_i/invested-1
    observed_cash_before_refund=obs_c-refund
    if cash_base <= EPS:
        if abs(observed_cash_before_refund)>EPS:
            raise ValueError("cash movement cannot be explained without a cash base")
        inferred_cash_return=0.0
    else:
        inferred_cash_return=observed_cash_before_refund/cash_base-1
    # Stable economic receipts irrespective of floating-point rounding in the broker balance.
    inferred_portfolio_return=round(inferred_portfolio_return,12)
    inferred_cash_return=round(inferred_cash_return,12)
    if not -1-EPS <= inferred_portfolio_return or not -1-EPS <= inferred_cash_return:
        raise ValueError("unexplained asset loss / return below -100%")
    # Large cash-account change usually indicates a missing transfer or income,
    # not ordinary interest. Do not silently label it a cash investment return.
    if abs(inferred_cash_return) > .20:
        raise ValueError("large unexplained cash change; review omitted flows")
    id_ = statement.event_id or f"{approval.opening.year}-annual-close"
    actual=YearActual(living_paid_m=actual_living,car_paid_m=actual_car,
                      extra_paid_m=actual_extra,
                      portfolio_real_return=inferred_portfolio_return,
                      cash_real_return=inferred_cash_return,
                      closing_date=statement.closing_date,event_id=id_)
    close=close_year(approval,actual)
    if abs(close.investment_next_m - obs_i)>EPS or abs(close.safety_cash_next_m - obs_c)>EPS:
        raise ArithmeticError("year-end actual balances did not reconcile")
    return close
