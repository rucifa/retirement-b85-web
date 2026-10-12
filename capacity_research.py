"""B+85 dual-target INITIAL PoS capacity, independent full-policy diagnostics.

Research-only read-only adapter. No persistent state, policy edits, or withdrawals.
Annual model = user-defined F (hard floor) and a hypothetical N >= F;
the N result is NOT the actual first-year approved withdrawal amount.

Historical reference: frozen Phase 1.15 spending calibration (32/32 regression).
"""
from __future__ import annotations
from dataclasses import replace
from math import ceil, floor, sqrt, isfinite
from typing import Any
import numpy as np
from policy import personalized_research_engine as model
from policy.personalized_research_annual import AnnualInput, decide_year

CONTRACT = 'B85_INVERSE_95_99_RESEARCH_V1'
TARGETS = (0.95, 0.99)
SEARCH_SEED = 20261011
VALIDATION_SEED = 20261031
CAP_NORMAL_TWD = 10_000_000


def _lower_wilson(succeeded: int, samples: int, z: float = 1.6448536269514722) -> float:
    """One-sided 95% confidence lower bound (distinct from success target)."""
    if not 0 <= succeeded <= samples or samples <= 0:
        raise ValueError('invalid simulation result')
    p = succeeded/samples
    return (p + z*z/(2*samples) - z*sqrt((p*(1-p) + z*z/(4*samples))/samples)) / (1 + z*z/samples)


def _normal_cfg(cfg, floor_2026_m: float, normal_2026_m: float, investments: float, cash: float):
    core = floor_2026_m + (normal_2026_m - floor_2026_m)*2/3
    return replace(cfg, personalized_normal_spend=normal_2026_m,
                   personalized_core_spend=core, initial_investment=investments,
                   initial_safety_cash=cash)


def _capital_capacity(cfg, investments: float, cash: float, *, paths: int, seed: int, planned_extra_m: float = 0.0):
    """Algebraically invert the *unchanged* required-asset distribution at Sticky=1.

    With unchanged normal spending each age, zero external income and Sticky=1,
    required present-value assets = N*sum(discounts) + scheduled extras + emergency.
    The emergency RNG reproduces RequiredAssetCache's keyed substream EXACTLY.
    Compare a returned boundary against a fresh engine-required-distribution.
    """
    if cfg.external_income_by_age:
        raise ValueError('external income calibration is not enabled in this contract')
    age = cfg.start_age
    cache = model.RequiredAssetCache(cfg, paths, seed, end_age=cfg.end_age)
    cache.required_distribution(age, 1.0, True)
    discount = cache._age_discount
    life_coeff = np.sum(discount, axis=1)
    nonliving = cache._age_base_extra.copy()
    if cfg.emergency_once:
        keyed_seed = (0x9E3779B1 ^ (age*1000003) ^ 1_000_000 ^
                      (cfg.end_age*97) ^ cfg.seed) & 0xFFFFFFFFFFFFFFFF
        rng = model._pcg(keyed_seed)
        t = rng.integers(0, discount.shape[1], size=paths)
        emergency = rng.uniform(cfg.emergency_min*model._activation_scale(cfg),
                                cfg.emergency_max*model._activation_scale(cfg), size=paths)
        nonliving += emergency * discount[np.arange(paths), t]
    total = investments + cash
    nonliving += planned_extra_m  # First-year confirmed mandatory extras, not a second life annuity.
    capacity_m_2026 = (total - nonliving) / life_coeff / model._activation_scale(cfg)
    if np.any(~np.isfinite(capacity_m_2026)) or np.any(life_coeff <= 0):
        raise ValueError('invalid capacity distribution')
    return np.sort(capacity_m_2026)


def _candidate(sorted_caps, p: float, hard_floor_twd: int):
    n = len(sorted_caps)
    rank = n - ceil(p*n)
    raw_twd = float(sorted_caps[rank])*1_000_000
    if raw_twd + 1e-7 < hard_floor_twd:
        return None, 'FLOOR_UNATTAINABLE_AT_TARGET'
    if raw_twd >= CAP_NORMAL_TWD:
        return CAP_NORMAL_TWD, 'SEARCH_CAPPED'
    best = floor(raw_twd + 1e-7)
    if best < hard_floor_twd:
        return None, 'FLOOR_UNATTAINABLE_AT_TARGET'
    return best, 'CAPACITY_CANDIDATE_ONLY'


def _annual_preview(config, year: dict, f_m: float, normal_twd: int,
                    *, paths: int, seed: int) -> dict:
    opening = year['approval']['opening']
    inv = float(opening['investment_m']); cash = float(opening['safety_cash_m'])
    cfg = _normal_cfg(config, f_m, normal_twd/1_000_000, inv, cash)
    input_ = AnnualInput(decision_date=opening['decision_date'], age=opening['age'],
        retirement_start_age=opening['start_age'], investment_start_m=inv,
        safety_cash_start_m=cash, sticky_before=1.0, emergency_pending=True,
        external_income_m=0.0, extra_mandatory_m=float(opening['planned_extra_m']),
        mode='SYNTHETIC')
    approval = decide_year(input_, cfg, n_inner=paths, seed=seed)
    # This is the full-year proxy; first-year pro-ration applies only to living.
    from calendar_first_year import fraction_for
    days, year_days, fraction = fraction_for(opening['decision_date'])
    # First-year decision == activation date; model units are activation-year
    # purchasing power, numerically equal to retirement-start nominal TWD.
    nominal = 1.0
    return {
        'initial_decision_pos': round(approval.pos, 6),
        'guardrail_cut_now': bool(approval.pos <= .75),
        'full_year_living_nominal_twd': round(approval.living_pool_paid_m*1_000_000*nominal, 2),
        'first_year_living_nominal_twd': round(approval.living_pool_paid_m*fraction*1_000_000*nominal, 2),
        'other_required_nominal_twd': round((approval.car_paid_m+approval.extra_mandatory_paid_m)*1_000_000*nominal, 2),
        'first_year_days': days, 'first_year_year_days': year_days,
        'plan_paid': bool(approval.plan_paid),
    }


def _validation(cfg, normal_twd: int, floor_m: float, inv: float, cash: float,
                *, paths: int, inner: int, seed: int) -> dict:
    candidate = _normal_cfg(cfg, floor_m, normal_twd/1_000_000, inv, cash)
    result = model.simulate_outer(candidate, n_outer=paths, n_inner=inner, seed=seed)
    floor_success = 1 - result['floor']
    whole_success = result['success']
    return {'model_full_policy_success': round(whole_success, 6),
            'model_no_floor_breach_fraction': round(floor_success, 6),
            'ever_cut_probability': round(result['ever_cut'], 6),
            'model_success_wilson_lower_95': round(_lower_wilson(round(whole_success*paths),paths), 6),
            'floor_wilson_lower_95': round(_lower_wilson(round(floor_success*paths), paths),6),
            'paths': paths, 'inner_per_annual_decision': inner, 'seed': seed,
            'status':'PRELIMINARY_INDEPENDENT_MC_NOT_EXTERNALLY_CALIBRATED'}


def evaluate_saved_first_year(state: dict, *, paths: int = 4096,
                              validation_paths: int = 0, validation_inner: int = 256) -> dict:
    """Read-only, never modifies state. Recalculates candidate N for a saved first-year plan.

    validation_paths=0 (default) means display only inner PoS candidates.
    Nonzero outer validation produces preliminary diagnostics, NOT certification.
    """
    import workflow
    if not isinstance(state, dict) or not state.get('years') or not state.get('plan'):
        raise ValueError('請先建立第一年退休研究紀錄')
    if paths < 256 or paths > 16384:
        raise ValueError('unsupported inner draw count')
    plan = state['plan']; p = plan.get('spending_profile')
    if not p:
        raise ValueError('此功能只支援個人化生活費研究紀錄；既有凍結基準維持原狀')
    first = state['years'][0]
    initial = first['approval']['opening']
    if initial['age'] != initial['start_age']:
        raise ValueError('invalid first-year age')
    f_twd = int(p['floor_twd']); f_m = f_twd/1_000_000
    cfg = workflow.policy_config(plan)
    invest = float(initial['investment_m']); cash = float(initial['safety_cash_m'])
    sorted_caps = _capital_capacity(cfg, invest, cash, paths=paths, seed=SEARCH_SEED,
                                    planned_extra_m=float(initial.get('planned_extra_m',0.)))
    results = {}
    for probability in TARGETS:
        raw, status = _candidate(sorted_caps, probability, f_twd)
        row: dict[str,Any] = {'target_probability':probability,'normal_2026_real_twd':raw,
                             'status':status, 'inner_pos':None,
                             'full_year_living_nominal_twd':None,
                             'first_year_living_nominal_twd':None, 'validation':None}
        if raw is not None:
            row['inner_pos'] = float(np.count_nonzero(sorted_caps >= raw/1_000_000)/len(sorted_caps))
            row.update(_annual_preview(cfg, first, f_m, raw, paths=paths, seed=SEARCH_SEED))
            if not row['plan_paid']:
                row['status']='UNFUNDED_ANNUAL_PREVIEW'
            if validation_paths:
                if validation_paths < 128 or validation_paths > 30000:
                    raise ValueError('unsupported outer draw count')
                row['validation'] = _validation(cfg,raw,f_m,invest,cash,
                    paths=validation_paths, inner=validation_inner,
                    seed=VALIDATION_SEED)
                v = row['validation']
                row['meets_lifetime_success_gate'] = bool(v['model_success_wilson_lower_95'] >= probability)
                row['meets_lifetime_floor_gate'] = bool(v['floor_wilson_lower_95'] >= probability)
                # Even with statistical gate pass, this preliminary MC is not
                # external validation; never call it a certified maximum.
        results['p'+str(round(probability*100))] = row
    a,b=results['p95']['normal_2026_real_twd'], results['p99']['normal_2026_real_twd']
    if a is not None and b is not None and b>a:
        raise AssertionError('99% capacity cannot exceed 95% capacity')
    return {'contract':CONTRACT,'status':'RESEARCH_CANDIDATE_NOT_A_SAFE_WITHDRAWAL',
            'p95_p99_are_initial_inner_pos_only':True,
            'floor_2026_real_twd':f_twd,'first_year':first['approval']['opening']['year'],
            'model_end_age':104,'inner_paths':paths,'search_seed':SEARCH_SEED,
            'target_lifetime_mc_certified':False,'results':results,
            'note':'雙門檻為固定 Sticky 的必要資產初始 PoS；與完整動態退休 Floor 成功率不同。僅研究候選，不代表最高安全提款或保證。'}
