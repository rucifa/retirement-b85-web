"""Read-only, fail-closed B85 annual APPROVAL source attribution.

This reconstructs the existing, already-approved payment event order. It NEVER
changes policy, annual ledger, transfers, or saved backup schema. In particular
an approved spending envelope is NOT a trade, withdrawal, or payment receipt.
Amounts are retirement-activation-year real TWD millions until conversion.
"""
from __future__ import annotations

from math import isfinite

CONTRACT = "B85_APPROVAL_SOURCE_ATTRIBUTION_V1"
EPS = 1e-8


def _take(invest: float, cash: float, amount: float, first: str):
    if amount < -EPS or not isfinite(amount):
        raise ValueError("invalid approved amount")
    amt = max(0., amount)
    if first == "invest":
        i = min(invest, amt)
        c = min(cash, amt-i)
    elif first == "cash":
        c = min(cash, amt)
        i = min(invest, amt-c)
    else:
        raise ValueError("invalid attribution source priority")
    return invest-i, cash-c, {"invest":i, "cash":c, "total":i+c}, amt-i-c


def _nominal(value: float, cpi: float, activation: float) -> float:
    return round(float(value)*1000000*float(cpi)/float(activation),2)


def attribution(approval, decision_cpi: float, activation_cpi: float) -> dict:
    """Use a stored YearApproval, never recompute PoS or edit its result."""
    p, o = approval.policy_preview, approval.opening
    base = {"contract":CONTRACT, "mode":"APPROVAL_ONLY_NOT_REAL_TRANSACTIONS"}
    if not all(isfinite(v) for v in (o.investment_m,o.safety_cash_m,
                                     decision_cpi,activation_cpi)):
        raise ValueError("invalid source amounts/CPI")
    if decision_cpi<=0 or activation_cpi<=0:
        raise ValueError("invalid CPI")
    inv, cash = float(o.investment_m), float(o.safety_cash_m)
    if min(inv,cash) < -EPS:
        raise ValueError("negative opening assets")
    try:
        bridge=float(p.bridge_from_cash_m)
        living=float(p.living_pool_paid_m)
        if bridge < -EPS or bridge > living+EPS or bridge > cash+EPS:
            raise ValueError("unmatched bridge")
        cash -= max(0.,bridge)
        inv,cash,rest,unpaid = _take(inv,cash, living-bridge,"invest")
        if unpaid>EPS: raise ValueError("living envelope not funded")
        living_sources={"invest":rest["invest"],"cash":rest["cash"]+bridge,
                        "total":living}
        inv,cash,car,unpaid = _take(inv,cash,float(p.car_paid_m),"invest")
        if unpaid>EPS: raise ValueError("car envelope not funded")
        inv,cash,extra,unpaid = _take(inv,cash,float(p.extra_mandatory_paid_m),"invest")
        if unpaid>EPS: raise ValueError("extra envelope not funded")
        refill=float(p.cash_refill_m)
        if refill < -EPS or refill > inv+EPS: raise ValueError("unmatched refill")
        inv-=max(0.,refill)
        cash+=max(0.,refill)
        if (abs(inv-p.investment_before_return_m)>EPS or
            abs(cash-p.safety_cash_before_return_m)>EPS):
            # Example: legacy partial-year prorator refunded investment
            # mechanically although investment had not funded the full
            # original living amount. Never invent a false precise source.
            raise ValueError("approved pool cannot be sourced event-by-event")
        total_invest = living_sources["invest"]+car["invest"]+extra["invest"]
        total_cash = living_sources["cash"]+car["cash"]+extra["cash"]
        if (abs((total_invest+total_cash)-(living+p.car_paid_m+p.extra_mandatory_paid_m))>EPS or
            abs(o.investment_m+o.safety_cash_m-(inv+cash+total_invest+total_cash))>EPS):
            raise ValueError("funding does not reconcile")
        def money(row):
            return {name+"_twd":_nominal(row[name],decision_cpi,activation_cpi)
                    for name in ("invest","cash","total")}
        return {**base,"status":"RECONCILED",
                "living":money(living_sources),"car":money(car),"extra":money(extra),
                "total":money({"invest":total_invest,"cash":total_cash,
                               "total":total_invest+total_cash}),
                "bridge_twd":_nominal(bridge,decision_cpi,activation_cpi),
                "cash_refill_transfer_twd":_nominal(refill,decision_cpi,activation_cpi),
                "emergency_reserve_reference_twd":_nominal(
                    p.cash_bridge_reserve_m,decision_cpi,activation_cpi),
                "investment_after_approval_twd":_nominal(inv,decision_cpi,activation_cpi),
                "cash_after_approval_twd":_nominal(cash,decision_cpi,activation_cpi),
                "warning":"核准預留資金，不是已交易、已提款或實際付款。安全現金保護額僅限制主動橋接，並非任何情況都不可動用。"}
    except ValueError:
        return {**base,"status":"UNAVAILABLE_REQUIRES_REVIEW",
                "warning":"該年度核准紀錄無法安全拆分逐項來源；僅使用原核准總額，不顯示猜測金流。"}
