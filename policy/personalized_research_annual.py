"""GENERALIZED_RESEARCH_v1 annual decision fork.

Original documented policy gates stay intact. Browser-generated synthetic
personalized plans are research only; not DOCUMENTED certification.
"""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B+85 formal candidate annual REVIEW adapter. NO trading or automatic deployment.

Amounts are millions of TWD in retirement-activation-year purchasing power.
Values must be reconcilable against date-stamped account/CPI/FX/return records;
source hashes here prove integrity of supplied bytes, not official provenance.
The frozen A remains the authority until B+85 is separately deployed.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
from typing import Optional
import hashlib, math
from . import personalized_research_engine as engine

POLICY_ID = "v3.4.0_B_SAFE85_RELEASE_PACKAGE_NOT_ROUTED"

@dataclass(frozen=True)
class EvidenceFile:
    path: str
    expected_sha256: str
    observed_at: str
    available_at: str

    def verify(self,decision_date:str):
        if self.observed_at>decision_date or self.available_at>decision_date:
            raise ValueError("future-dated evidence")
        path=Path(self.path)
        if not path.is_file():raise ValueError("source document is not available")
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        if sha!=self.expected_sha256:raise ValueError("source bytes SHA256 mismatch")
        return sha

@dataclass(frozen=True)
class AnnualInput:
    decision_date: str
    age: int
    retirement_start_age: int
    investment_start_m: float
    safety_cash_start_m: float
    sticky_before: float
    emergency_pending: bool
    previous_completed_real_portfolio_return: Optional[float] = None
    external_income_m: float = 0.0
    extra_mandatory_m: float = 0.0
    emergency_event_m: float = 0.0
    realized_year_portfolio_return: float = 0.0
    realized_year_cash_return: float = 0.0
    already_failed_plan: bool = False
    mode: str = "SYNTHETIC" # SYNTHETIC or DOCUMENTED
    source_records: tuple[EvidenceFile,...] = ()

@dataclass(frozen=True)
class AnnualResult:
    policy: str
    decision_date: str
    age: int
    pos: float
    normal_pos: Optional[float]
    sticky_before: float
    sticky_after: float
    b85_restored: bool
    living_gross_authorized_m: float
    living_pool_required_m: float
    living_pool_paid_m: float
    bridge_from_cash_m: float
    car_paid_m: float
    extra_mandatory_paid_m: float
    emergency_paid_m: float
    cash_refill_m: float
    investment_before_return_m: float
    safety_cash_before_return_m: float
    investment_next_start_m: float
    safety_cash_next_start_m: float
    emergency_pending_next: bool
    floor_paid: bool
    plan_paid: bool
    cash_bridge_reserve_m: float
    reconciliation_error_m: float


def validate_input(data: AnnualInput, prior: AnnualResult|None=None, tolerance:float=1e-8):
    from datetime import date
    decision_date = date.fromisoformat(data.decision_date)
    if data.age < data.retirement_start_age or data.age>104:
        raise ValueError("pre-retirement or post-canonical horizon")
    for x in (data.investment_start_m,data.safety_cash_start_m,data.external_income_m,
              data.extra_mandatory_m,data.emergency_event_m):
        if not math.isfinite(x) or x<0:raise ValueError("negative or nonfinite balance/income/expense")
    for x in (data.realized_year_portfolio_return,data.realized_year_cash_return):
        if not math.isfinite(x) or x < -1:raise ValueError("invalid realized year return")
    if not math.isfinite(data.sticky_before) or not 0<data.sticky_before<=1.1:
        raise ValueError("invalid Sticky multiplier")
    if data.already_failed_plan:raise ValueError("prior plan failure cannot reset to success")
    if data.emergency_event_m and not data.emergency_pending:
        raise ValueError("emergency already consumed; duplicate event")
    if data.age>data.retirement_start_age and data.previous_completed_real_portfolio_return is None:
        raise ValueError("prior real portfolio return required")
    if data.previous_completed_real_portfolio_return is not None:
        if not math.isfinite(data.previous_completed_real_portfolio_return) or data.previous_completed_real_portfolio_return < -1:
            raise ValueError("invalid prior real portfolio return")
    if data.mode not in ("SYNTHETIC","DOCUMENTED"):
        raise ValueError("bad evidence mode")
    if data.mode=="DOCUMENTED":
        raise ValueError("Real annual ACTIVE execution disabled: require verified two-phase decision/closing ledger, signed provenance and authorized live integration")
        if decision_date > date.today():
            raise ValueError("cannot approve future-dated real-world annual decision")
        if len(data.source_records)<3:
            raise ValueError("documented annual decision requires asset, market and price-index source files")
        paths=[str(Path(s.path).resolve()) for s in data.source_records]
        if len(set(paths))!=len(paths):
            raise ValueError("each documented evidence source must have distinct underlying bytes/file")
        for source in data.source_records: source.verify(data.decision_date)
    if prior is not None:
        if data.age != prior.age+1 or data.decision_date<=prior.decision_date:
            raise ValueError("noncontiguous age/date in annual chain")
        if not prior.plan_paid:raise ValueError("prior failed plan cannot be treated as new success")
        for new,old,key in ((data.investment_start_m,prior.investment_next_start_m,'invest'),
                            (data.safety_cash_start_m,prior.safety_cash_next_start_m,'cash'),
                            (data.sticky_before,prior.sticky_after,'sticky')):
            if abs(new-old)>tolerance:raise ValueError("year-to-year "+key+" discontinuity")
        if data.emergency_pending!=prior.emergency_pending_next:
            raise ValueError("emergency status reset or undocumented transition")
        if abs(data.previous_completed_real_portfolio_return - prior_portfolio_return_from_close(prior))>tolerance:
            raise ValueError("previous year investment return evidence mismatch")


def prior_portfolio_return_from_close(prior:AnnualResult):
    if prior.investment_before_return_m == 0:
        if prior.investment_next_start_m != 0:raise ValueError("portfolio arose from zero base")
        return 0.0
    return prior.investment_next_start_m / prior.investment_before_return_m - 1


def _pay(invest:float,cash:float,cost:float,priority:str):
    if priority not in ('invest','cash'):raise ValueError('bad priority')
    if priority=='invest':
        i=min(invest,cost); invest-=i; c=min(cash,cost-i);cash-=c
    else:
        c=min(cash,cost);cash-=c;i=min(invest,cost-c);invest-=i
    return invest,cash,cost-i-c, cost-(cost-i-c)


def decide_year(data:AnnualInput, cfg:engine.ModelConfig, *,
                n_inner:int=8192,seed:int=20261011,prior:AnnualResult|None=None) -> AnnualResult:
    validate_input(data,prior)
    if data.retirement_start_age != cfg.start_age:
        raise ValueError("model and annual retirement starting age differ")
    if cfg.use_charity:raise ValueError("Charity excluded from B+85 upgrade scope")
    if data.mode=="DOCUMENTED" and not (
        cfg.guardrail_low == .75 and cfg.guardrail_high == .95 and cfg.guardrail_step == .10
        and cfg.cash_bridge_trigger_pos == .75 and cfg.cash_bridge_fraction == .50
        and cfg.use_cash_bridge and cfg.cash_bridge_emergency_reserve_from_emergency_min
        and cfg.safety_cash_target == 2.40 and cfg.safety_cash_tolerance == .95
        and cfg.annual_cash_refill_cap == .50 and cfg.floor_spend == .50
        and cfg.emergency_min == 1.20 and cfg.emergency_max == 1.50):
        raise ValueError("documented decision must use frozen safety/Guardrail policy parameters")
    if cfg.use_prosperity and cfg.prosperity_spending_mode not in ('permission_only','recommended_target','full_ceiling'):
        raise ValueError('unsupported Prosperity mode')
    cash=data.safety_cash_start_m;invest=data.investment_start_m
    total=invest+cash
    pos=engine.single_state_pos(total,data.age,data.sticky_before,data.emergency_pending,cfg,n_inner=n_inner,seed=seed)
    ordinary=min(cfg.normal_spend_cap_multiple,data.sticky_before * (
        1-cfg.guardrail_step if pos<=cfg.guardrail_low else (1+cfg.guardrail_step if pos>=cfg.guardrail_high else 1)))
    normal_pos=None;restored=False
    if (data.age>data.retirement_start_age and ordinary<1 and pos>cfg.guardrail_low
        and data.previous_completed_real_portfolio_return is not None and data.previous_completed_real_portfolio_return>0):
        normal_pos=engine.single_state_pos(total,data.age,1.0,data.emergency_pending,cfg,n_inner=n_inner,seed=seed)
        restored=engine.b85_restore_eligible(age=data.age,start_age=data.retirement_start_age,
          active=True,pre_decision_pos=pos,post_guardrail_multiplier=ordinary,
          prior_completed_real_portfolio_return=data.previous_completed_real_portfolio_return,
          pos_if_full_normal_budget=normal_pos)
    mult=1.0 if restored else ordinary
    gross=engine.living_spend_from_multiplier(data.age,mult,cfg)
    if cfg.use_prosperity and cash >= cfg.safety_cash_target*cfg.safety_cash_tolerance:
        rate=engine.prosperity_rate(data.age,pos)
        if rate>0:
            maxextra=max(0.0,invest*rate-gross)
            if cfg.prosperity_spending_mode=='full_ceiling':gross+=maxextra
            elif cfg.prosperity_spending_mode=='recommended_target':
                gross+=maxextra*engine.recommended_spending_utilization(data.age,pos)
    burden=max(0.,gross-data.external_income_m)
    floor_needed=max(0.,cfg.floor_spend * engine._activation_scale(cfg)-data.external_income_m)
    floor_can_pay=total>=floor_needed-1e-12
    bridge=engine.cash_bridge_payment(burden,cash,pos,cfg)
    cash-=bridge
    invest,cash,remaining,paid_living_rest = _pay(invest,cash,burden-bridge,'invest')
    paid_living=bridge+paid_living_rest
    paid_plan=remaining<=1e-12
    car_paid=extra_paid=emergency_paid=0.
    if data.age in cfg.car_ages:
        cost=cfg.car_cost * engine._activation_scale(cfg)
        invest,cash,unpaid,car_paid=_pay(invest,cash,cost,'invest');paid_plan &= unpaid<=1e-12
    if data.extra_mandatory_m>0:
        invest,cash,unpaid,extra_paid=_pay(invest,cash,data.extra_mandatory_m,'invest');paid_plan &= unpaid<=1e-12
    pending=data.emergency_pending
    if data.emergency_event_m>0:
        invest,cash,unpaid,emergency_paid=_pay(invest,cash,data.emergency_event_m,'cash');paid_plan &= unpaid<=1e-12
        pending=False
    refill=0.
    if paid_plan and cash<cfg.safety_cash_target*cfg.safety_cash_tolerance and pos>cfg.guardrail_low:
        refill=min(cfg.annual_cash_refill_cap*engine._activation_scale(cfg),
                   max(0.,cfg.safety_cash_target-cash),invest)
        invest-=refill;cash+=refill
    before=total
    after=invest+cash
    outflows=paid_living+car_paid+extra_paid+emergency_paid
    err=before-after-outflows
    if abs(err)>1e-8:raise ArithmeticError("annual assets not conserved before returns")
    invest_close=invest*(1+data.realized_year_portfolio_return)
    cash_close=cash*(1+data.realized_year_cash_return)
    return AnnualResult(POLICY_ID,data.decision_date,data.age,float(pos),normal_pos,
       data.sticky_before,mult,restored,float(gross),float(burden),float(paid_living),float(bridge),
       float(car_paid),float(extra_paid),float(emergency_paid),float(refill),
       float(invest),float(cash),float(invest_close),float(cash_close),pending,
       bool(floor_can_pay and (paid_living+data.external_income_m)>=cfg.floor_spend*engine._activation_scale(cfg)-1e-10),
       bool(paid_plan),engine.cash_bridge_emergency_reserve(cfg),float(err))
