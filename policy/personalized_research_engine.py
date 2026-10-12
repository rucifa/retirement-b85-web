# GENERALIZED_RESEARCH_v1: independently forked v3.4.0 policy engine.
# 
# Origin: policy/retirement_model_v340.py, whose SHA256 must remain frozen.
# Only research configuration normal/core spending parameters differ from the
# canonical source. The original policy is not modified or superseded.
# Not certified as a new formal retirement policy.
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""退休模型 B+85 v3.4.0 Release Policy Engine (offline; not live), adapted from FROZEN v3.3.9 Canonical Reference Engine.

VERSION NOTE: This is an isolated versioned policy candidate (not deployed ACTIVE).
The sole economic change is the B+85 recovery gate after ordinary 75/95
Guardrail, before spending. Original v3.3.9 reference is separately preserved.


Purpose
-------
This file is the portable reference implementation for the v3.3.9 retirement
model. It is NOT claimed to be the lost original historical source code. It is
an independently reconstructed, documented implementation frozen from the
formal v3.3.3 specification and validated against the preserved historical
headline outputs.

Units are TWD millions in retirement-activation-year purchasing power unless stated otherwise.
For the preserved 2026 reference case, activation_cpi_factor_from_2026 = 1.0, so
the purchasing-power unit basis is identical to the 2026-real baseline. Strategy
outputs can differ from earlier versions because v3.3.8 changed the Recommended
Spending Target utilization curve and v3.3.9 fixes the normal/core real spending baselines at 65/60. For a future retirement,
2026-real living/capital-expense baselines are scaled to the retirement activation
year by the activation CPI factor, while the safety-cash anchor is intentionally
reset to TWD 2.40 million nominal at activation.

Core implementation choices retained from v3.3.3 / extended through v3.3.9
---------------------------------------------
1. Stock/bond annual real returns are correlated log returns:
   simple_return = exp(log(1+geometric_median) + sigma*z) - 1.
   Therefore the documented volatility parameter is log-return sigma.
2. The investment sleeve is rebalanced to the target stock/bond allocation
   every simulation year (portfolio return = w*stock + (1-w)*bond).
3. The Probability-of-Success (PoS) inner model holds the CURRENT Sticky
   spending multiplier fixed for the remaining horizon. Future Guardrail,
   Prosperity and Charity decisions are not recursively embedded in the inner
   PoS. This prevents double/adaptive recursion and matches the documented
   "required asset distribution at the current multiplier" concept.
4. Inner PoS uses a deterministic required-asset distribution: current assets
   are compared with Monte-Carlo pathwise present values of future mandatory
   living costs, scheduled cars and one still-pending Emergency.
5. Outer annual event order:
   pre-withdrawal state -> PoS -> Sticky Guardrail -> Prosperity permission ->
   Recommended Spending Target (if enabled) -> regular living spend ->
   scheduled car -> Emergency -> safety-cash refill -> Charity evaluation
   (ages 80,85,90,95,100...) -> market return.
6. Investment-pool dividends/interest are already part of total return and are
   never added as external income in PoS. They may reduce execution-time asset
   sales, but not economic withdrawal burden.
7. Safety cash is separate from the 70/30 investment sleeve. v3.3.6 resets
   the safety-cash target to TWD 2.40 million NOMINAL on the retirement
   activation date. Pre-retirement CPI does not inflate this anchor. In a real
   annual execution, later nominal targets are 2.40 * (CPI_year / CPI_activation).
   Because the simulation is expressed in activation-year purchasing power, the
   post-retirement real target remains 2.40. Refill occurs only when PoS > 75%
   and cash <95% of target; Charity is disabled below the 95% threshold.
8. v3.3.8 retains the non-sticky Recommended Spending Target between the normal
   Guardrail budget and the Prosperity soft ceiling, but updates the utilization
   curve after full challenge testing: 33% of extra room at PoS=98%, 40% at
   PoS=99%, and 60% at PoS=100%, linearly interpolated. For age 70+ Prosperity
   starts at PoS=99%, so utilization starts at 40% and rises linearly to 60% at
   PoS=100%. The target remains advisory in real-life execution; simulation mode
   can assume the retiree follows it for validation.
9. v3.3.7 adds the Bear-Market Cash Bridge. When annual pre-decision
   PoS <=75%, up to 50% of the retirement-pool burden of regular living may be
   paid from safety cash, but only from cash ABOVE the inflation-adjusted
   Emergency Reserve floor. The remaining living burden is paid investment-first
   as before. Emergency has priority over the bridge. When PoS >75%, bridge use
   stops and the existing gradual safety-cash refill rule resumes; no single
   rebound year forces a full refill.


10. v3.3.9 removes the automatic age-based decline in baseline living budgets.
    Normal living baseline is fixed at TWD 0.65m in 2026 real purchasing power
    for all retirement ages; the Core reference layer is fixed at TWD 0.60m.
    Actual spending can still fall through the 75/95 Sticky Guardrail, never
    below the TWD 0.50m hard Floor. This is a policy simplification, not a
    fixed-withdrawal rule.
11. Maintenance r1 standardizes the canonical simulation horizon at age 104.
    Alternate horizons remain explicit scenario inputs, not the default baseline.

The reference engine favors clarity and reproducibility while avoiding redundant
same-age recomputation. Maintenance r1 retains only the current-age required-asset
cache and reuses the same-age discount matrix; policy mathematics are unchanged.
The quick mode is suitable for regression checks; the high mode is intended for
formal reruns.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import argparse
import json
import math
from pathlib import Path
from typing import Dict, Iterable, Literal, Optional, Tuple

import numpy as np

ScenarioName = Literal["base", "stress", "conservative"]


@dataclass(frozen=True)
class MarketScenario:
    name: ScenarioName
    stock_median_base: float
    stock_sigma_base: float
    bond_median_base: float
    bond_sigma_base: float
    corr_base: float
    cash_real_base: float
    stock_median_first10: Optional[float] = None
    stock_sigma_first10: Optional[float] = None
    bond_median_first10: Optional[float] = None
    bond_sigma_first10: Optional[float] = None
    corr_first10: Optional[float] = None
    cash_real_first10: Optional[float] = None

    def params_for_age(self, age: int) -> Tuple[float, float, float, float, float, float]:
        if self.name == "stress" and age <= 63:
            return (
                float(self.stock_median_first10),
                float(self.stock_sigma_first10),
                float(self.bond_median_first10),
                float(self.bond_sigma_first10),
                float(self.corr_first10),
                float(self.cash_real_first10),
            )
        return (
            self.stock_median_base,
            self.stock_sigma_base,
            self.bond_median_base,
            self.bond_sigma_base,
            self.corr_base,
            self.cash_real_base,
        )


SCENARIOS: Dict[ScenarioName, MarketScenario] = {
    "base": MarketScenario("base", 0.045, 0.17, 0.018, 0.07, 0.10, 0.0),
    "stress": MarketScenario(
        "stress", 0.045, 0.17, 0.018, 0.07, 0.10, 0.0,
        stock_median_first10=0.025, stock_sigma_first10=0.18,
        bond_median_first10=0.015, bond_sigma_first10=0.08,
        corr_first10=0.20, cash_real_first10=-0.005,
    ),
    "conservative": MarketScenario("conservative", 0.035, 0.18, 0.012, 0.08, 0.20, -0.002),
}


@dataclass(frozen=True)
class Friction:
    name: str = "baseline"
    stock_drag: float = 0.0
    bond_drag: float = 0.0


FRICTIONS: Dict[str, Friction] = {
    "baseline": Friction("baseline", 0.0, 0.0),
    "fee_only_ucits": Friction("fee_only_ucits", 0.00164, 0.0010),
    "ucits_est": Friction("ucits_est", 0.0038, 0.0012),
    "mixed_us_est": Friction("mixed_us_est", 0.0053, 0.0005),
    # 2026 reference preset for validation only: 70/30 weighted drag ~=0.349%/yr.
    # Annual real-life execution must update friction from actual holdings/tax rules.
    "net_central_2026ref": Friction("net_central_2026ref", 0.0046, 0.0009),
    "conservative": Friction("conservative", 0.0065, 0.0015),
}


@dataclass
class ModelConfig:
    start_age: int = 54
    end_age: int = 104
    stock_weight: float = 0.70
    initial_investment: float = 27.0
    initial_safety_cash: float = 2.40
    safety_cash_target: float = 2.40  # nominal TWD millions, re-anchored at retirement activation
    activation_cpi_factor_from_2026: float = 1.0
    safety_cash_tolerance: float = 0.95
    annual_cash_refill_cap: float = 0.50  # 2026-real policy amount; scaled to activation-year purchasing power
    use_cash_bridge: bool = True
    cash_bridge_fraction: float = 0.50
    cash_bridge_trigger_pos: float = 0.75
    # Cash Bridge may not proactively draw safety cash below this reserve.
    # Default policy uses the CPI-scaled lower bound of the one-time Emergency.
    cash_bridge_emergency_reserve_from_emergency_min: bool = True
    floor_spend: float = 0.50  # customizable 2026-real spending-profile Floor (research only)
    personalized_normal_spend: float = 0.65
    personalized_core_spend: float = 0.60
    guardrail_low: float = 0.75
    guardrail_high: float = 0.95
    guardrail_step: float = 0.10
    normal_spend_cap_multiple: float = 1.10
    car_cost: float = 1.20  # 2026-real baseline
    car_ages: Tuple[int, ...] = (60, 70, 80, 90)
    emergency_min: float = 1.20  # 2026-real baseline
    emergency_max: float = 1.50  # 2026-real baseline
    emergency_once: bool = True
    # Optional deterministic Emergency override for formal stress-test replay.
    # None preserves the normal random one-time Emergency timing/amount.
    forced_emergency_age: Optional[int] = None
    forced_emergency_amount: Optional[float] = None
    seed: int = 20260914
    scenario: ScenarioName = "base"
    friction: Friction = field(default_factory=lambda: FRICTIONS["baseline"])
    # External income is OUTSIDE the retirement investment pool. Investment
    # distributions/dividends must never be placed here.
    external_income_by_age: Dict[int, float] = field(default_factory=dict)
    extra_mandatory_expense_by_age: Dict[int, float] = field(default_factory=dict)
    use_prosperity: bool = False
    # Simulation execution mode for Prosperity. Real-life annual execution uses
    # the computed Recommended Target as guidance and never treats it as a
    # mandatory withdrawal.
    prosperity_spending_mode: Literal["permission_only", "recommended_target", "full_ceiling"] = "permission_only"
    use_charity: bool = False
    charity_protected_pos: float = 0.99
    charity_gate_multiple: float = 1.25
    charity_release_fraction: float = 0.50
    charity_start_age: int = 80
    charity_interval: int = 5
    charity_horizon_age: int = 104


def _activation_scale(cfg: ModelConfig) -> float:
    """CPI factor from 2026 to retirement activation for 2026-real baselines."""
    f = float(cfg.activation_cpi_factor_from_2026)
    if not math.isfinite(f) or f <= 0:
        raise ValueError("activation_cpi_factor_from_2026 must be > 0")
    return f


def safety_cash_nominal_target_after_activation(
    cpi_current: float, cpi_activation: float, anchor_nominal_millions: float = 2.40
) -> float:
    """Nominal safety-cash target after retirement activation.

    Retirement activation itself is re-anchored to 2.40 million nominal. Later
    nominal targets preserve that activation-date purchasing power using the
    cumulative post-retirement CPI ratio only.
    """
    if cpi_activation <= 0 or cpi_current <= 0:
        raise ValueError("CPI values must be > 0")
    return float(anchor_nominal_millions) * float(cpi_current) / float(cpi_activation)


def normal_living_spend(age: int, cfg: Optional[ModelConfig] = None) -> float:
    """Formal v3.3.9 normal living baseline: 2026-real TWD 0.65m at every age."""
    base = cfg.personalized_normal_spend if cfg is not None else 0.65
    return base * (_activation_scale(cfg) if cfg is not None else 1.0)


def core_living_spend(age: int, cfg: Optional[ModelConfig] = None) -> float:
    """Core lifestyle reference layer: 2026-real TWD 0.60m at every age.

    This is a planning/reference layer, not an independent mechanical withdrawal state.
    The mechanical lower bound remains the TWD 0.50m Floor.
    """
    base = cfg.personalized_core_spend if cfg is not None else 0.60
    return base * (_activation_scale(cfg) if cfg is not None else 1.0)


def living_spend_from_multiplier(age: int, multiplier: float, cfg: ModelConfig) -> float:
    base = normal_living_spend(age, cfg)
    floor = cfg.floor_spend * _activation_scale(cfg)
    return max(floor, min(cfg.normal_spend_cap_multiple * base, multiplier * base))


def cash_bridge_emergency_reserve(cfg: ModelConfig) -> float:
    """Real reserve floor protected from proactive Cash Bridge use.

    The formal v3.3.8 rule retains the v3.3.7 lower bound of the one-time Emergency
    allowance (2026-real TWD 1.20m), scaled into retirement-activation-year
    purchasing power. This reserve can still be used by an actual Emergency or
    as a last-resort source when investment assets cannot fund necessary living;
    it is simply not proactively consumed by the bridge.
    """
    if cfg.cash_bridge_emergency_reserve_from_emergency_min:
        return float(cfg.emergency_min) * _activation_scale(cfg)
    return 0.0


def cash_bridge_payment(living_burden: float, safety_cash: float, pos: float, cfg: ModelConfig) -> float:
    """Maximum proactive Cash Bridge payment for one annual decision state."""
    if not cfg.use_cash_bridge or pos > cfg.cash_bridge_trigger_pos:
        return 0.0
    capacity = max(0.0, float(safety_cash) - cash_bridge_emergency_reserve(cfg))
    target = max(0.0, float(living_burden)) * float(cfg.cash_bridge_fraction)
    return min(target, capacity)


def prosperity_rate(age: int, pos: float) -> float:
    if age <= 69:
        if pos >= 0.99:
            return 0.045
        if pos >= 0.98:
            return 0.040
        return 0.0
    if age <= 79:
        return 0.035 if pos >= 0.99 else 0.0
    if age <= 89:
        return 0.0275 if pos >= 0.99 else 0.0
    return 0.0225 if pos >= 0.99 else 0.0


def recommended_spending_utilization(age: int, pos: float) -> float:
    """Fraction of Prosperity extra room used by the v3.3.8 recommendation.

    The fraction applies only to the gap between the normal Sticky-Guardrail
    budget and the Prosperity soft ceiling. It is non-sticky and is recomputed
    every year.
    """
    p = min(max(float(pos), 0.0), 1.0)
    if age <= 69:
        if p < 0.98:
            return 0.0
        if p < 0.99:
            return 0.33 + (0.40 - 0.33) * ((p - 0.98) / 0.01)
        return 0.40 + (0.60 - 0.40) * ((p - 0.99) / 0.01)
    # At age 70+ the formal Prosperity permission begins only at PoS >=99%.
    if p < 0.99:
        return 0.0
    return 0.40 + (0.60 - 0.40) * ((p - 0.99) / 0.01)


def recommended_spending_target(
    age: int, pos: float, normal_budget: float, eligible_investment_assets: float
) -> tuple[float, float, float]:
    """Return (target, soft_ceiling, utilization) in real TWD millions.

    If Prosperity permission is unavailable, target equals normal_budget.
    """
    rate = prosperity_rate(age, pos)
    if rate <= 0.0:
        return float(normal_budget), float(normal_budget), 0.0
    soft = max(float(normal_budget), float(eligible_investment_assets) * rate)
    u = recommended_spending_utilization(age, pos)
    target = float(normal_budget) + u * (soft - float(normal_budget))
    return float(target), float(soft), float(u)


def _pcg(seed: int) -> np.random.Generator:
    # Explicit generator family for portability across runs.
    return np.random.Generator(np.random.PCG64(seed))


def generate_market_returns(
    rng: np.random.Generator,
    n_paths: int,
    ages: np.ndarray,
    cfg: ModelConfig,
) -> Tuple[np.ndarray, np.ndarray]:
    """Generate annual rebalanced investment-sleeve and safety-cash returns."""
    scen = SCENARIOS[cfg.scenario]
    out = np.empty((n_paths, len(ages)), dtype=np.float64)
    cash = np.empty_like(out)
    w = cfg.stock_weight
    for j, age in enumerate(ages):
        sm, ss, bm, bs, rho, cash_r = scen.params_for_age(int(age))
        z1 = rng.standard_normal(n_paths)
        z2 = rng.standard_normal(n_paths)
        zs = z1
        zb = rho * z1 + math.sqrt(1.0 - rho * rho) * z2
        rs = np.exp(math.log1p(sm) + ss * zs) - 1.0
        rb = np.exp(math.log1p(bm) + bs * zb) - 1.0
        # Friction is applied as a multiplicative annual drag on each sleeve.
        rs = (1.0 + rs) * (1.0 - cfg.friction.stock_drag) - 1.0
        rb = (1.0 + rb) * (1.0 - cfg.friction.bond_drag) - 1.0
        out[:, j] = w * rs + (1.0 - w) * rb
        cash[:, j] = cash_r
    return out, cash


class RequiredAssetCache:
    """Inner Monte Carlo required-asset distributions.

    For a given age, current Sticky multiplier and Emergency state, this cache
    calculates pathwise present value of future mandatory real spending. The
    current multiplier is held fixed throughout the remaining inner horizon.

    This is a deliberate canonical approximation of the documented historical
    inner PoS concept. It is not claimed to reproduce the lost original source
    line-by-line; regression bands are used to verify economic equivalence.
    """

    def __init__(self, cfg: ModelConfig, n_inner: int, seed: int, end_age: Optional[int] = None):
        self.cfg = cfg
        self.n_inner = int(n_inner)
        self.start_age = cfg.start_age
        self.end_age = int(end_age if end_age is not None else cfg.end_age)
        self.ages = np.arange(self.start_age, self.end_age + 1, dtype=int)
        # A distinct stream avoids call-order dependence between outer and inner
        # simulations while retaining deterministic reproduction.
        self.rng = _pcg(seed ^ 0x5A17C3D1)
        self.portfolio_returns, _ = generate_market_returns(self.rng, self.n_inner, self.ages, cfg)
        self._cache: Dict[Tuple[int, float, bool], np.ndarray] = {}
        self._cache_age: Optional[int] = None
        self._age_discount: Optional[np.ndarray] = None
        self._age_ages: Optional[np.ndarray] = None
        self._age_base_extra: Optional[np.ndarray] = None

    def required_distribution(self, age: int, multiplier: float, emergency_pending: bool) -> np.ndarray:
        if age < self.start_age or age > self.end_age:
            raise ValueError(f"age {age} outside cache horizon {self.start_age}-{self.end_age}")

        # The outer loop is chronological. No state from a prior age is ever reused,
        # so retain only same-age distributions. Also compute the expensive discount
        # matrix and deterministic mandatory extras once per age, not once per multiplier.
        if self._cache_age != int(age):
            self._cache.clear()
            self._cache_age = int(age)
            idx = age - self.start_age
            ages = self.ages[idx:]
            r = self.portfolio_returns[:, idx:]
            gross = 1.0 + r
            cumulative = np.cumprod(gross, axis=1)
            discount = np.ones_like(r)
            if r.shape[1] > 1:
                discount[:, 1:] = 1.0 / cumulative[:, :-1]
            base_extra = np.zeros(self.n_inner, dtype=np.float64)
            scale = _activation_scale(self.cfg)
            for car_age in self.cfg.car_ages:
                if age <= car_age <= self.end_age:
                    base_extra += (self.cfg.car_cost * scale) * discount[:, car_age - age]
            for exp_age, amount in self.cfg.extra_mandatory_expense_by_age.items():
                if age <= exp_age <= self.end_age:
                    base_extra += float(amount) * discount[:, exp_age - age]
            self._age_ages = ages
            self._age_discount = discount
            self._age_base_extra = base_extra

        mkey = round(float(multiplier), 3)
        key = (int(age), mkey, bool(emergency_pending))
        if key in self._cache:
            return self._cache[key]

        ages = self._age_ages
        discount = self._age_discount
        living = np.array(
            [living_spend_from_multiplier(int(a), mkey, self.cfg) for a in ages],
            dtype=np.float64,
        )
        outside_income = np.array(
            [self.cfg.external_income_by_age.get(int(a), 0.0) for a in ages],
            dtype=np.float64,
        )
        living_net = np.maximum(0.0, living - outside_income)
        req = np.sum(discount * living_net[None, :], axis=1)
        req += self._age_base_extra

        if emergency_pending and self.cfg.emergency_once:
            # Keyed substream: result is independent of cache call order.
            keyed_seed = (
                0x9E3779B1
                ^ (age * 1000003)
                ^ int(round(mkey * 1_000_000))
                ^ (self.end_age * 97)
                ^ self.cfg.seed
            ) & 0xFFFFFFFFFFFFFFFF
            erng = _pcg(keyed_seed)
            t = erng.integers(0, len(ages), size=self.n_inner)
            amt = erng.uniform(self.cfg.emergency_min * _activation_scale(self.cfg), self.cfg.emergency_max * _activation_scale(self.cfg), size=self.n_inner)
            req += amt * discount[np.arange(self.n_inner), t]

        req.sort()
        self._cache[key] = req
        return req

    def probability_of_success(
        self, assets: np.ndarray | float, age: int, multiplier: float, emergency_pending: bool
    ) -> np.ndarray | float:
        req = self.required_distribution(age, multiplier, emergency_pending)
        arr = np.asarray(assets, dtype=np.float64)
        out = np.searchsorted(req, arr, side="right") / float(self.n_inner)
        return float(out) if arr.ndim == 0 else out

    def protected_reserve(
        self, age: int, multiplier: float, emergency_pending: bool, target_pos: float = 0.99
    ) -> float:
        req = self.required_distribution(age, multiplier, emergency_pending)
        # Smallest reserve that meets target empirical success fraction.
        q = min(max(float(target_pos), 0.0), 1.0)
        return float(np.quantile(req, q, method="higher"))


def _pay(
    invest: np.ndarray,
    cash: np.ndarray,
    amount: np.ndarray | float,
    first: Literal["invest", "cash"],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    amount_arr = np.broadcast_to(np.asarray(amount, dtype=np.float64), invest.shape).copy()
    if first == "invest":
        used = np.minimum(invest, amount_arr)
        invest = invest - used
        rem = amount_arr - used
        used2 = np.minimum(cash, rem)
        cash = cash - used2
        rem = rem - used2
    else:
        used = np.minimum(cash, amount_arr)
        cash = cash - used
        rem = amount_arr - used
        used2 = np.minimum(invest, rem)
        invest = invest - used2
        rem = rem - used2
    return invest, cash, rem


def _grouped_pos(
    cache: RequiredAssetCache,
    total_assets: np.ndarray,
    age: int,
    multipliers: np.ndarray,
    emergency_pending: np.ndarray,
    active: np.ndarray,
) -> np.ndarray:
    pos = np.zeros_like(total_assets, dtype=np.float64)
    rounded = np.round(multipliers, 3)
    for pending in (False, True):
        p_mask = (emergency_pending == pending) & active
        if not np.any(p_mask):
            continue
        for m in np.unique(rounded[p_mask]):
            mask = p_mask & (rounded == m)
            pos[mask] = cache.probability_of_success(total_assets[mask], age, float(m), pending)
    return pos


def b85_restore_eligible(*, age: int, start_age: int, active: bool,
                         pre_decision_pos: float, post_guardrail_multiplier: float,
                         prior_completed_real_portfolio_return: Optional[float],
                         pos_if_full_normal_budget: Optional[float]) -> bool:
    """B+85 recovery gate. Fail-closed for missing, nonfinite or future inputs.

    pos_if_full_normal_budget MUST be computed for the same start-of-year assets,
    age, known pending Emergency and INNER distribution at sticky multiplier=1.
    This predicate never uses the current year's future realized market return.
    """
    if not active or age <= start_age or post_guardrail_multiplier >= 1.0:
        return False
    if not (math.isfinite(pre_decision_pos) and 0.0 <= pre_decision_pos <= 1.0):
        raise ValueError("invalid pre-decision PoS")
    if pre_decision_pos <= 0.75:
        return False
    if prior_completed_real_portfolio_return is None:
        raise ValueError("prior completed portfolio return missing")
    if not math.isfinite(float(prior_completed_real_portfolio_return)):
        raise ValueError("invalid prior completed portfolio return")
    if prior_completed_real_portfolio_return <= 0.0:
        return False
    if pos_if_full_normal_budget is None or not math.isfinite(float(pos_if_full_normal_budget)) or not 0 <= pos_if_full_normal_budget <= 1:
        raise ValueError("recovery requires valid independently recomputed full-budget PoS")
    return pos_if_full_normal_budget >= 0.85


def simulate_outer(
    cfg: ModelConfig,
    n_outer: int = 12000,
    n_inner: int = 3500,
    seed: Optional[int] = None,
    injected_outer_returns=None,
) -> Dict[str, float]:
    """Run the portable outer retirement simulation.

    This function is the canonical *reference* implementation for v3.3.9.
    Historical source-code identity is not asserted; preserved headline outputs
    are checked through regression bands in regression_test_v1.py.
    """
    if cfg.use_charity:
        raise ValueError("Charity is excluded from approved B+85 upgrade scope")
    seed = cfg.seed if seed is None else int(seed)
    ages = np.arange(cfg.start_age, cfg.end_age + 1, dtype=int)
    rng = _pcg(seed)
    portfolio_returns, cash_returns = generate_market_returns(rng, n_outer, ages, cfg)
    # Optional reproducible EXOGENOUS market trajectories for A/B stress replay.
    # Preserve emergency RNG order and compute the decision in year j only from
    # last completed year (j-1); NEVER from current-year injected return.
    if injected_outer_returns is not None:
        rp, rc = injected_outer_returns
        if rp.shape != portfolio_returns.shape or rc.shape != cash_returns.shape:
            raise ValueError("injected path shape mismatch")
        if not np.isfinite(rp).all() or not np.isfinite(rc).all() or np.any(rp < -1) or np.any(rc < -1):
            raise ValueError("invalid injected market returns")
        portfolio_returns, cash_returns = rp.copy(), rc.copy()

    if cfg.emergency_once:
        if cfg.forced_emergency_age is not None:
            emergency_age = np.full(n_outer, int(cfg.forced_emergency_age), dtype=int)
            amt = (
                float(cfg.forced_emergency_amount)
                if cfg.forced_emergency_amount is not None
                else 0.5 * (cfg.emergency_min + cfg.emergency_max) * _activation_scale(cfg)
            )
            emergency_amt = np.full(n_outer, amt, dtype=np.float64)
        else:
            emergency_age = rng.integers(cfg.start_age, cfg.end_age + 1, size=n_outer)
            emergency_amt = rng.uniform(cfg.emergency_min * _activation_scale(cfg), cfg.emergency_max * _activation_scale(cfg), size=n_outer)
    else:
        emergency_age = np.full(n_outer, -1, dtype=int)
        emergency_amt = np.zeros(n_outer)

    invest = np.full(n_outer, cfg.initial_investment, dtype=np.float64)
    cash = np.full(n_outer, cfg.initial_safety_cash, dtype=np.float64)
    multiplier = np.ones(n_outer, dtype=np.float64)
    emergency_pending = np.full(n_outer, cfg.emergency_once, dtype=bool)

    success = np.ones(n_outer, dtype=bool)
    floor_breach = np.zeros(n_outer, dtype=bool)
    ever_cut = np.zeros(n_outer, dtype=bool)
    b85_recovery_count = np.zeros(n_outer, dtype=np.int32)
    life_total = np.zeros(n_outer, dtype=np.float64)
    prosperity_total = np.zeros(n_outer, dtype=np.float64)
    recommended_extra_total = np.zeros(n_outer, dtype=np.float64)
    cash_bridge_total = np.zeros(n_outer, dtype=np.float64)
    cash_bridge_years = np.zeros(n_outer, dtype=int)
    cash_bridge_min_cash = cash.copy()
    charity_total = np.zeros(n_outer, dtype=np.float64)
    charity_count = np.zeros(n_outer, dtype=int)
    first_charity_age = np.full(n_outer, -1, dtype=int)
    charity_post_release_min_pos = 1.0
    charity_post_release_violations = 0
    charity_release_events = 0

    inner = RequiredAssetCache(cfg, n_inner, seed, end_age=cfg.end_age)
    charity_cache = None
    if cfg.use_charity:
        charity_cfg = ModelConfig(**{**asdict(cfg), "end_age": cfg.charity_horizon_age})
        # asdict turns Friction into a dict; restore object.
        charity_cfg.friction = cfg.friction
        charity_cache = RequiredAssetCache(charity_cfg, n_inner, seed ^ 0xABCDEF, end_age=cfg.charity_horizon_age)

    for j, age in enumerate(ages):
        active = success.copy()
        total_pre = invest + cash
        pos = _grouped_pos(inner, total_pre, int(age), multiplier, emergency_pending, active)

        # 75/95 Sticky Guardrail. Equality follows formal text: <=75 cut, >=95 add.
        cut = (pos <= cfg.guardrail_low) & active
        add = (pos >= cfg.guardrail_high) & active
        ever_cut |= cut
        multiplier[cut] *= (1.0 - cfg.guardrail_step)
        multiplier[add] *= (1.0 + cfg.guardrail_step)
        # Economic normal-spending ceiling is 110% of the age baseline.
        multiplier = np.minimum(multiplier, cfg.normal_spend_cap_multiple)

        # v3.4.0 B+85 ONLY: full normal lifestyle can resume after an
        # ordinary Sticky cut when last COMPLETED market-year portfolio return
        # was positive, CURRENT pre-decision PoS >75%, and current-year
        # PoS recomputed at normal baseline (multiplier 1) is >=85%.
        # No change to PoS for core Sticky, cash bridge, Emergency or Prosperity.
        if j > 0:
            try_recovery = (active & (pos > cfg.guardrail_low)
                            & (portfolio_returns[:, j - 1] > 0.0)
                            & (multiplier < 1.0))
            if np.any(try_recovery):
                restored_pos = _grouped_pos(
                    inner, total_pre, int(age), np.ones(n_outer, dtype=np.float64),
                    emergency_pending, try_recovery
                )
                restore = try_recovery & (restored_pos >= 0.85)
                multiplier[restore] = 1.0
                b85_recovery_count += restore.astype(np.int32)

        base_spend = np.array(
            [living_spend_from_multiplier(int(age), m, cfg) for m in multiplier], dtype=np.float64
        )
        outside_income = float(cfg.external_income_by_age.get(int(age), 0.0))

        # Prosperity and Recommended Target are defined on GROSS lifestyle
        # spending. Only after the spending decision is made do true outside
        # incomes reduce the economic burden on the retirement pool.
        gross_living = base_spend.copy()
        prosperity_extra_gross = np.zeros(n_outer, dtype=np.float64)
        recommended_extra_gross = np.zeros(n_outer, dtype=np.float64)
        if cfg.use_prosperity:
            rates = np.array([prosperity_rate(int(age), float(p)) for p in pos])
            eligible = (
                (rates > 0.0)
                & active
                & (cash >= cfg.safety_cash_target * cfg.safety_cash_tolerance)
            )
            soft_ceiling = np.maximum(base_spend, invest * rates)
            extra_room = np.maximum(0.0, soft_ceiling - base_spend)
            if cfg.prosperity_spending_mode == "full_ceiling":
                prosperity_extra_gross = np.where(eligible, extra_room, 0.0)
            elif cfg.prosperity_spending_mode == "recommended_target":
                util = np.array([recommended_spending_utilization(int(age), float(p)) for p in pos])
                recommended_extra_gross = np.where(eligible, util * extra_room, 0.0)
                prosperity_extra_gross = recommended_extra_gross.copy()
            elif cfg.prosperity_spending_mode != "permission_only":
                raise ValueError(f"unknown prosperity_spending_mode: {cfg.prosperity_spending_mode}")
            gross_living += prosperity_extra_gross
            prosperity_total += prosperity_extra_gross
            recommended_extra_total += recommended_extra_gross

        final_living = np.maximum(0.0, gross_living - outside_income)

        # Floor Breach is narrower than Plan Failure: it means available
        # retirement resources cannot fund the hard 0.50 real living floor.
        # A path can fail to fund its higher Guardrail/Prosperity budget without
        # necessarily breaching the hard floor.
        floor_needed_from_pool = max(0.0, cfg.floor_spend * _activation_scale(cfg) - outside_income)
        floor_breach |= (invest + cash < floor_needed_from_pool - 1e-12) & success

        # Regular living with v3.3.7 Bear-Market Cash Bridge (retained in v3.3.8).
        # The bridge is keyed to the same pre-decision PoS used by the 75/95
        # Guardrail. It may use at most 50% of the pool-funded living burden and
        # only cash ABOVE the protected Emergency Reserve. This does not prevent
        # the protected reserve from serving as a last resort if investments are
        # later insufficient; it only prevents proactive bridge depletion.
        bridge_paid = np.zeros(n_outer, dtype=np.float64)
        if cfg.use_cash_bridge:
            reserve = cash_bridge_emergency_reserve(cfg)
            bridge_eligible = active & (pos <= cfg.cash_bridge_trigger_pos)
            bridge_target = np.where(bridge_eligible, final_living * cfg.cash_bridge_fraction, 0.0)
            bridge_capacity = np.maximum(0.0, cash - reserve)
            bridge_paid = np.minimum(bridge_target, bridge_capacity)
            cash -= bridge_paid
            cash_bridge_total += bridge_paid
            cash_bridge_years += (bridge_paid > 1e-12).astype(int)
            cash_bridge_min_cash = np.minimum(cash_bridge_min_cash, cash)

        remaining_living = np.maximum(0.0, final_living - bridge_paid)
        invest, cash, rem = _pay(invest, cash, remaining_living, "invest")
        living_failed = rem > 1e-12
        success &= ~living_failed
        life_total += (final_living - rem)

        # Scheduled cars: investment first, then cash.
        if int(age) in cfg.car_ages:
            invest, cash, rem = _pay(invest, cash, cfg.car_cost * _activation_scale(cfg), "invest")
            success &= (rem <= 1e-12)

        # Known additional mandatory expense.
        extra = float(cfg.extra_mandatory_expense_by_age.get(int(age), 0.0))
        if extra > 0:
            invest, cash, rem = _pay(invest, cash, extra, "invest")
            success &= (rem <= 1e-12)

        # Emergency: safety cash first, then investment.
        em = (emergency_age == age) & emergency_pending
        if np.any(em):
            amounts = np.where(em, emergency_amt, 0.0)
            invest, cash, rem = _pay(invest, cash, amounts, "cash")
            success &= (rem <= 1e-12)
            emergency_pending[em] = False

        # Safety cash refill after mandatory spending; do not force small gaps.
        refill_ok = (
            success
            & (cash < cfg.safety_cash_target * cfg.safety_cash_tolerance)
            & (pos > cfg.guardrail_low)
        )
        refill_cap = cfg.annual_cash_refill_cap * _activation_scale(cfg)
        refill = np.minimum(refill_cap, np.maximum(0.0, cfg.safety_cash_target - cash))
        refill = np.where(refill_ok, np.minimum(refill, invest), 0.0)
        invest -= refill
        cash += refill

        # Charitable late-life surplus capital release.
        if (
            cfg.use_charity
            and charity_cache is not None
            and age >= cfg.charity_start_age
            and (age - cfg.charity_start_age) % cfg.charity_interval == 0
        ):
            total_available = invest + cash
            rounded = np.round(multiplier, 3)
            proposed = np.zeros(n_outer, dtype=np.float64)
            for pending in (False, True):
                p_mask = (
                    (emergency_pending == pending)
                    & success
                    & (cash >= cfg.safety_cash_target * cfg.safety_cash_tolerance)
                )
                if not np.any(p_mask):
                    continue
                for m in np.unique(rounded[p_mask]):
                    mask = p_mask & (rounded == m)
                    reserve = charity_cache.protected_reserve(
                        int(age), float(m), pending, cfg.charity_protected_pos
                    )
                    gate = reserve * cfg.charity_gate_multiple
                    surplus = np.maximum(0.0, total_available[mask] - reserve)
                    p = np.where(
                        total_available[mask] >= gate,
                        surplus * cfg.charity_release_fraction,
                        0.0,
                    )
                    # Safety cash is never donated; release cannot exceed investment.
                    p = np.minimum(p, invest[mask])
                    # Post-release PoS must still be >= target. If proposed release
                    # fails, formal conservative action is no release this cycle.
                    post_assets = total_available[mask] - p
                    post_pos = charity_cache.probability_of_success(
                        post_assets, int(age), float(m), pending
                    )
                    valid_release = p > 0.0
                    if np.any(valid_release):
                        observed = post_pos[valid_release]
                        charity_post_release_min_pos = min(
                            charity_post_release_min_pos, float(np.min(observed))
                        )
                        charity_post_release_violations += int(
                            np.sum(observed < cfg.charity_protected_pos)
                        )
                        charity_release_events += int(np.sum(valid_release))
                    p = np.where(post_pos >= cfg.charity_protected_pos, p, 0.0)
                    proposed[mask] = p
            released = proposed > 0
            invest -= proposed
            charity_total += proposed
            charity_count += released.astype(int)
            first_charity_age[(released) & (first_charity_age < 0)] = int(age)

        # End-of-year market return. Investment sleeve is annual-rebalanced by
        # construction of portfolio_returns; safety cash earns scenario cash return.
        invest *= (1.0 + portfolio_returns[:, j])
        cash *= (1.0 + cash_returns[:, j])
        invest = np.maximum(invest, 0.0)
        cash = np.maximum(cash, 0.0)

    terminal = invest + cash
    first_age_valid = first_charity_age[first_charity_age >= 0]
    result = {
        "scenario": cfg.scenario,
        "friction": cfg.friction.name,
        "prosperity_spending_mode": cfg.prosperity_spending_mode,
        "seed": seed,
        "n_outer": int(n_outer),
        "n_inner": int(n_inner),
        "policy_name": "B_SAFE85_v3.4.0",
        "b85_recovery_events": int(np.sum(b85_recovery_count)),
        "b85_share_ever_recovery": float(np.mean(b85_recovery_count > 0)),
        "start_age": cfg.start_age,
        "end_age": cfg.end_age,
        "activation_cpi_factor_from_2026": float(cfg.activation_cpi_factor_from_2026),
        "safety_cash_target_at_activation": float(cfg.safety_cash_target),
        "success": float(np.mean(success)),
        "floor": float(np.mean(floor_breach)),
        "ever_cut": float(np.mean(ever_cut)),
        "life_med": float(np.median(life_total)),
        "life_p10": float(np.quantile(life_total, 0.10)),
        "life_p90": float(np.quantile(life_total, 0.90)),
        "prosperity_med": float(np.median(prosperity_total)),
        "recommended_extra_med": float(np.median(recommended_extra_total)),
        "cash_bridge_enabled": bool(cfg.use_cash_bridge),
        "cash_bridge_fraction": float(cfg.cash_bridge_fraction),
        "cash_bridge_trigger_pos": float(cfg.cash_bridge_trigger_pos),
        "cash_bridge_emergency_reserve": float(cash_bridge_emergency_reserve(cfg)),
        "cash_bridge_med": float(np.median(cash_bridge_total)),
        "cash_bridge_p90": float(np.quantile(cash_bridge_total, 0.90)),
        "ever_cash_bridge": float(np.mean(cash_bridge_years > 0)),
        "cash_bridge_years_med_among_users": (
            float(np.median(cash_bridge_years[cash_bridge_years > 0])) if np.any(cash_bridge_years > 0) else 0.0
        ),
        "cash_bridge_min_cash_p10": float(np.quantile(cash_bridge_min_cash, 0.10)),
        "charity_med": float(np.median(charity_total)),
        "ever_release": float(np.mean(charity_count > 0)),
        "first_release_age_med": float(np.median(first_age_valid)) if len(first_age_valid) else None,
        "release_count_med": float(np.median(charity_count)),
        "charity_post_release_min_pos": (
            float(charity_post_release_min_pos) if charity_release_events > 0 else None
        ),
        "charity_post_release_violations": int(charity_post_release_violations),
        "charity_release_events": int(charity_release_events),
        "terminal_med": float(np.median(terminal)),
        "terminal_p10": float(np.quantile(terminal, 0.10)),
        "terminal_p90": float(np.quantile(terminal, 0.90)),
    }
    return result


def single_state_pos(
    total_assets: float,
    age: int,
    sticky_multiplier: float,
    emergency_pending: bool,
    cfg: ModelConfig,
    n_inner: int = 10000,
    seed: Optional[int] = None,
) -> float:
    """Exact single-state annual PoS estimate for real-life annual execution."""
    seed = cfg.seed if seed is None else int(seed)
    cache = RequiredAssetCache(cfg, n_inner, seed, end_age=cfg.end_age)
    return float(cache.probability_of_success(total_assets, age, sticky_multiplier, emergency_pending))


def _cli() -> None:
    p = argparse.ArgumentParser(description="Retirement model v3.3.9 canonical reference engine (Maintenance r1)")
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="base")
    p.add_argument("--friction", choices=sorted(FRICTIONS), default="baseline")
    p.add_argument("--mode", choices=["smoke", "quick", "high"], default="quick")
    p.add_argument("--end-age", type=int, default=104)
    p.add_argument("--initial-investment", type=float, default=27.0, help="Investment assets in retirement-activation-year TWD millions")
    p.add_argument("--initial-safety-cash", type=float, default=2.40, help="Actual safety cash at retirement activation in TWD millions")
    p.add_argument("--seed", type=int, default=20260914)
    p.add_argument("--activation-cpi-factor", type=float, default=1.0, help="CPI factor from 2026 to retirement activation; safety-cash anchor remains 2.40 nominal")
    p.add_argument("--prosperity", action="store_true")
    p.add_argument("--charity", action="store_true")
    p.add_argument("--no-cash-bridge", action="store_true", help="Disable retained v3.3.7 Bear-Market Cash Bridge for paired regression/comparison")
    p.add_argument(
        "--prosperity-spending-mode",
        choices=["permission_only", "recommended_target", "full_ceiling"],
        default="permission_only",
    )
    p.add_argument("--output", type=Path)
    args = p.parse_args()

    counts = {
        "smoke": (3000, 1200),
        "quick": (12000, 3500),
        "high": (50000, 10000),
    }
    n_outer, n_inner = counts[args.mode]
    cfg = ModelConfig(
        end_age=args.end_age,
        initial_investment=args.initial_investment,
        initial_safety_cash=args.initial_safety_cash,
        seed=args.seed,
        scenario=args.scenario,
        friction=FRICTIONS[args.friction],
        activation_cpi_factor_from_2026=args.activation_cpi_factor,
        use_prosperity=args.prosperity,
        prosperity_spending_mode=args.prosperity_spending_mode,
        use_charity=args.charity,
        use_cash_bridge=not args.no_cash_bridge,
    )
    result = simulate_outer(cfg, n_outer=n_outer, n_inner=n_inner, seed=args.seed)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    _cli()
