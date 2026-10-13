"""Read-only, pathwise B+85 monitoring. Frozen engines are never edited.

Annual event order and grouped inner PoS mirror the canonical outer engine.
Saved pending approvals are locked spending envelopes, never approved twice.
Real monetary units here are activation-year TWD millions.
"""
from dataclasses import replace
from math import isfinite, log1p, sqrt
import time
import hashlib
from pathlib import Path
import numpy as np
from expense_contract import bind_current_expense, CONTRACT as EXPENSE_CONTRACT

CONTRACT = 'B85_PATHWISE_ASSET_PROJECTION_V1'
SEED = 20261112


def trace_paths(cfg, *, engine, paths=2048, inner_paths=512, seed=SEED,
                opening=None, locked=None, fraction=1.0, injected_returns=None,
                progress=None, time_limit=120):
    if cfg.use_charity or cfg.external_income_by_age:
        raise ValueError('此研究契約不支援慈善釋放或外部收入')
    age0 = int(opening['age']) if opening else cfg.start_age
    if not cfg.start_age <= age0 <= cfg.end_age or not 0 < fraction <= 1:
        raise ValueError('模擬年齡或期間不合理')
    started = time.perf_counter()
    ages = np.arange(age0, cfg.end_age + 1, dtype=int)
    n, t = int(paths), len(ages)
    rng = engine._pcg(seed)
    rp, rc = engine.generate_market_returns(rng, n, ages, cfg)
    # Independent partial-year stream; annual drift/friction scale with time,
    # volatility with sqrt(time), retaining stock/bond correlation. Full-year
    # mode preserves canonical streams exactly.
    if fraction != 1:
        prng = engine._pcg(seed ^ 0xC0FFEE)
        sm, ss, bm, bs, rho, cr = engine.SCENARIOS[cfg.scenario].params_for_age(age0)
        z1, z2 = prng.standard_normal(n), prng.standard_normal(n)
        rs = np.exp(log1p(sm)*fraction + ss*sqrt(fraction)*z1)*(1-cfg.friction.stock_drag)**fraction-1
        rb = np.exp(log1p(bm)*fraction + bs*sqrt(fraction)*(rho*z1+sqrt(1-rho*rho)*z2))*(1-cfg.friction.bond_drag)**fraction-1
        rp[:, 0] = cfg.stock_weight*rs + (1-cfg.stock_weight)*rb
        rc[:, 0] = (1+cr)**fraction-1
    if injected_returns is not None:
        rp, rc = (np.asarray(x, dtype=float).copy() for x in injected_returns)
        if rp.shape != (n,t) or rc.shape != (n,t) or not np.isfinite(rp).all() or not np.isfinite(rc).all() or np.any(rp < -1) or np.any(rc < -1):
            raise ValueError('注入報酬形狀或數值錯誤')
    if cfg.emergency_once:
        if cfg.forced_emergency_age is None:
            emergency_age = rng.integers(age0, cfg.end_age+1, size=n)
            emergency_amount = rng.uniform(cfg.emergency_min*engine._activation_scale(cfg), cfg.emergency_max*engine._activation_scale(cfg), size=n)
        else:
            emergency_age = np.full(n, cfg.forced_emergency_age)
            amount = cfg.forced_emergency_amount
            if amount is None: amount = (cfg.emergency_min+cfg.emergency_max)/2*engine._activation_scale(cfg)
            emergency_amount = np.full(n, amount)
    else:
        emergency_age, emergency_amount = np.full(n,-1), np.zeros(n)
    invest = np.full(n, opening['investment_m'] if opening else cfg.initial_investment,dtype=float)
    cash = np.full(n, opening['safety_cash_m'] if opening else cfg.initial_safety_cash,dtype=float)
    mult = np.full(n, opening.get('sticky_before',1.) if opening else 1.,dtype=float)
    pending = np.full(n, opening.get('emergency_pending',True) if opening else cfg.emergency_once, dtype=bool)
    prev = np.full(n, opening.get('prior_completed_net_real_return') or 0. if opening else 0.,dtype=float)
    success, floor_failure, mandatory_failure = np.ones(n,bool), np.zeros(n,bool), np.zeros(n,bool)
    ever_cut = np.zeros(n,bool)
    first_floor_age=np.full(n,-1,dtype=int)
    first_mandatory_age=np.full(n,-1,dtype=int)
    first_gap_age=np.full(n,-1,dtype=int)
    first_gap_amount=np.zeros(n)
    first_gap_cash_before=np.zeros(n)
    first_gap_cash_after=np.zeros(n)
    bridge_total, consumption = np.zeros(n), np.zeros(n)
    bridge_years = np.zeros(n,int)
    bridge_min_cash = cash.copy()
    cash_hist, investment_hist = np.empty((n,t)), np.empty((n,t))
    annual = []
    max_error = 0.
    recovery_events = 0
    cache = engine.RequiredAssetCache(cfg, inner_paths, seed, end_age=cfg.end_age)
    for j, age in enumerate(ages):
        if time.perf_counter()-started > time_limit:
            raise ValueError('計算超過時間上限；請改用快速研究模式')
        age = int(age)
        pre = invest + cash
        cash_before=cash.copy()
        car_gap=np.zeros(n);extra_gap=np.zeros(n)
        live_fraction = fraction if j==0 else 1.
        if locked is not None and j==0:
            pos = np.full(n, locked['pos'])
            mult[:] = locked['sticky_after']
            ever_cut |= pos <= cfg.guardrail_low
            living = np.full(n, locked['living_pool_paid_m'])
            bridge = np.full(n, locked['bridge_from_cash_m'])
            car_paid = np.full(n, locked['car_paid_m'])
            extra_paid = np.full(n, locked['extra_mandatory_paid_m'])
            refill = np.full(n, locked['cash_refill_m'])
            invest[:] = locked['investment_before_return_m']
            cash[:] = locked['safety_cash_before_return_m']
            # This approval's transfers already happened. A future emergency
            # is paid once; never rerun its saved refill or ordinary spending.
        else:
            active = success.copy()
            pos = engine._grouped_pos(cache, pre, age, mult, pending, active)
            cut = (pos <= cfg.guardrail_low) & active
            add = (pos >= cfg.guardrail_high) & active
            ever_cut |= cut
            mult[cut] *= 1-cfg.guardrail_step
            mult[add] *= 1+cfg.guardrail_step
            mult = np.minimum(mult,cfg.normal_spend_cap_multiple)
            if age > cfg.start_age:
                trying = active & (pos>cfg.guardrail_low) & (prev>0) & (mult<1)
                if np.any(trying):
                    normal = engine._grouped_pos(cache, pre, age, np.ones(n), pending, trying)
                    restored = trying & (normal>=.85)
                    mult[restored] = 1.
                    recovery_events += int(np.sum(restored))
            living = np.array([engine.living_spend_from_multiplier(age,m,cfg) for m in mult])
            if cfg.use_prosperity:
                rates = np.array([engine.prosperity_rate(age,p) for p in pos])
                eligible = (rates>0)&active&(cash>=cfg.safety_cash_target*cfg.safety_cash_tolerance)
                room = np.maximum(0.,invest*rates-living)
                if cfg.prosperity_spending_mode=='recommended_target':
                    room *= np.array([engine.recommended_spending_utilization(age,p) for p in pos])
                elif cfg.prosperity_spending_mode=='permission_only': room[:] = 0
                elif cfg.prosperity_spending_mode!='full_ceiling': raise ValueError('支出模式錯誤')
                living += np.where(eligible, room, 0.)
            living *= live_fraction
            bridge = np.minimum(np.maximum(0.,cash-engine.cash_bridge_emergency_reserve(cfg)),
                np.where(active&(pos<=cfg.cash_bridge_trigger_pos)&cfg.use_cash_bridge,living*cfg.cash_bridge_fraction,0.))
            cash -= bridge
            bridge_min_cash = np.minimum(bridge_min_cash,cash)
            invest,cash,unpaid = engine._pay(invest,cash,living-bridge,'invest')
            success &= unpaid<=1e-12
            living = living-unpaid
            car = cfg.car_cost*engine._activation_scale(cfg) if age in cfg.car_ages else 0.
            invest,cash,unpaid = engine._pay(invest,cash,car,'invest')
            success &= unpaid<=1e-12
            mandatory_failure |= unpaid>1e-12
            car_gap=unpaid.copy()
            car_paid = car-unpaid
            extra = cfg.extra_mandatory_expense_by_age.get(age,0.)
            invest,cash,unpaid = engine._pay(invest,cash,extra,'invest')
            success &= unpaid<=1e-12
            mandatory_failure |= unpaid>1e-12
            extra_gap=unpaid.copy()
            extra_paid = extra-unpaid
            refill = np.zeros(n)
        # Unlike canonical floor flags (which stop monitoring failed plans),
        # the lifetime actual-payment floor is checked for EVERY path/year.
        floor_failure |= living < cfg.floor_spend*engine._activation_scale(cfg)*live_fraction-1e-10
        em = (emergency_age==age)&pending
        em_due = np.where(em,emergency_amount,0.)
        invest,cash,unpaid = engine._pay(invest,cash,em_due,'cash')
        emergency_paid = em_due-unpaid
        success &= unpaid<=1e-12
        mandatory_failure |= unpaid>1e-12
        mandatory_gap=car_gap+extra_gap+unpaid
        pending[em] = False
        if not (locked is not None and j==0):
            refill_ok = success&(cash<cfg.safety_cash_target*cfg.safety_cash_tolerance)&(pos>cfg.guardrail_low)
            refill = np.where(refill_ok,np.minimum(invest,np.minimum(cfg.annual_cash_refill_cap*engine._activation_scale(cfg),np.maximum(0.,cfg.safety_cash_target-cash))),0.)
            invest -= refill
            cash += refill
        floor_gap=np.maximum(0.,cfg.floor_spend*engine._activation_scale(cfg)*live_fraction-living)
        first_floor_age[(first_floor_age<0)&(floor_gap>1e-10)]=age
        first_mandatory_age[(first_mandatory_age<0)&(mandatory_gap>1e-12)]=age
        newly=(first_gap_age<0)&((floor_gap>1e-10)|(mandatory_gap>1e-12))
        first_gap_age[newly]=age
        first_gap_amount[newly]=(floor_gap+mandatory_gap)[newly]
        first_gap_cash_before[newly]=cash_before[newly]
        first_gap_cash_after[newly]=cash[newly]
        paid = living+car_paid+extra_paid+emergency_paid
        error = pre-paid-invest-cash
        max_error = max(max_error,float(np.max(np.abs(error))))
        if max_error > 1e-8: raise ArithmeticError('模擬年度資金不守恆')
        bridge_total += bridge
        bridge_years += (bridge>1e-12).astype(int)
        consumption += living
        gains = invest*rp[:,j]+cash*rc[:,j]
        invest *= 1+rp[:,j]
        cash *= 1+rc[:,j]
        if np.any(invest < -1e-10) or np.any(cash < -1e-10): raise ArithmeticError('資產為負')
        error_close = pre+gains-paid-invest-cash
        max_error = max(max_error,float(np.max(np.abs(error_close))))
        if max_error > 1e-8: raise ArithmeticError('模擬年末資金不守恆')
        prev = rp[:,j]
        investment_hist[:,j],cash_hist[:,j] = invest,cash
        annual.append({'age':age,'plan_paid_fraction':float(np.mean(success)),
            'floor_and_required_fraction':float(np.mean(~floor_failure&~mandatory_failure)),
            'no_floor_breach_fraction':float(np.mean(~floor_failure)),
            'required_expense_paid_fraction':float(np.mean(~mandatory_failure)),
            'extra_paid_median_m':float(np.median(extra_paid)),
            'car_paid_median_m':float(np.median(car_paid)),
            'living_paid_median_m':float(np.median(living)),
            'emergency_paid_median_m':float(np.median(emergency_paid)),
            'bridge_median_m':float(np.median(bridge)), 'refill_median_m':float(np.median(refill)),
            'depleted_fraction':float(np.mean(invest+cash<=1e-10))})
        if progress: progress(j+1,t)
    terminal = invest+cash
    def conditional(arr,mask,p=.5):return float(np.quantile(arr[mask],p)) if mask.any() else None
    failed=first_gap_age>=0
    return {'investment':investment_hist,'cash':cash_hist,'ages':ages,'annual':annual,
        'path_outcomes':{'plan':success,'floor':~floor_failure,'mandatory':~mandatory_failure},
        'first_shortfall':{'floor_age':first_floor_age,'mandatory_age':first_mandatory_age,'joint_age':first_gap_age,
            'amount_m':first_gap_amount,'cash_before_m':first_gap_cash_before,'cash_after_m':first_gap_cash_after},
        'diagnostics':{'plan_success':float(np.mean(success)),
            'floor_and_required_success':float(np.mean(~floor_failure&~mandatory_failure)),
            'first_gap_rate':float(np.mean(failed)),
            'first_gap_age_p50':conditional(first_gap_age,failed),
            'first_floor_age_p50':conditional(first_floor_age,first_floor_age>=0),
            'first_mandatory_age_p50':conditional(first_mandatory_age,first_mandatory_age>=0),
            'first_gap_amount_median_m':conditional(first_gap_amount,failed),
            'first_gap_amount_p90_m':conditional(first_gap_amount,failed,.9),
            'first_gap_cash_before_median_m':conditional(first_gap_cash_before,failed),
            'first_gap_cash_after_median_m':conditional(first_gap_cash_after,failed),
            'lifetime_floor_success':float(np.mean(~floor_failure)),
            'required_expense_success':float(np.mean(~mandatory_failure)),
            'ever_cut':float(np.mean(ever_cut)), 'recovery_events':recovery_events,
            'terminal_med':float(np.median(terminal)), 'terminal_p10':float(np.quantile(terminal,.1)),
            'terminal_p90':float(np.quantile(terminal,.9)), 'life_med':float(np.median(consumption)),
            'cash_bridge_med':float(np.median(bridge_total)), 'ever_cash_bridge':float(np.mean(bridge_years>0)),
            'cash_bridge_min_cash_p10':float(np.quantile(bridge_min_cash,.1)),
            'max_reconciliation_error_m':max_error},
        'seconds':time.perf_counter()-started,
        'working_array_bytes':int(rp.nbytes+rc.nbytes+investment_hist.nbytes+cash_hist.nbytes+cache.portfolio_returns.nbytes)}


def project_saved(state, *, paths=2048, inner_paths=512, seed=SEED, inflation_pct=2., progress=None):
    import workflow
    from policy import retirement_model_v340 as frozen, personalized_research_engine as research
    from capacity_research import _lower_wilson
    if not state.get('plan') or not state.get('years'):
        raise ValueError('請先完成一次年度試算')
    if not isinstance(paths,int) or isinstance(paths,bool) or not 256<=paths<=8192:
        raise ValueError('外層路徑數須為 256～8192')
    if not isinstance(inner_paths,int) or isinstance(inner_paths,bool) or not 128<=inner_paths<=4096:
        raise ValueError('內層路徑數須為 128～4096')
    if not isinstance(seed,int) or not 0<=seed<=2**32-1:
        raise ValueError('亂數種子不合理')
    inflation_pct = float(inflation_pct)
    if not isfinite(inflation_pct) or not -5<=inflation_pct<=15:
        raise ValueError('通膨情境須為 −5%～15%')
    plan = state['plan']; row = state['years'][-1]
    cfg = workflow.policy_config(plan)
    from large_expenses import bind,known_cpi,digest as schedule_digest,validate as schedule_validate
    engine = research if plan.get('spending_profile') else frozen
    stored_open = row['approval']['opening']
    cfg,resolved_schedule=bind(cfg,state.get('expense_schedule'),plan,known_cpi(state),stored_open['year']+(1 if row.get('close') else 0))
    locked = None; fraction=1.
    if row.get('close'):
        c = row['close']; age0=stored_open['age']+1; year0=stored_open['year']+1
        if age0>104: raise ValueError('已結算 104 歲，沒有剩餘退休年度可模擬')
        opening={'age':age0,'investment_m':c['investment_next_m'],'safety_cash_m':c['safety_cash_next_m'],
                 'sticky_before':c['sticky_next'],'emergency_pending':c['emergency_pending_next'],
                 'prior_completed_net_real_return':c['net_portfolio_real_return']}
        nominal_anchor = row['closing_cpi']/plan['activation_cpi']
        asof = row['closing_date']
    else:
        opening=dict(stored_open); age0=opening['age']; year0=opening['year']
        locked=dict(row['approval']['policy_preview'])
        fraction=float(row.get('calendar_first_year',{}).get('calendar_fraction',1.))
        schedule=dict(cfg.extra_mandatory_expense_by_age);schedule.pop(age0,None)
        cfg=bind_current_expense(replace(cfg,extra_mandatory_expense_by_age=schedule),age0,opening['planned_extra_m'])
        nominal_anchor=row['cpi_decision']/plan['activation_cpi']
        asof=opening['decision_date']
    # The last completed year's required outflow has already left its pools.
    # A pending year's approval is a locked first envelope, not a second draw.
    trace=trace_paths(cfg,engine=engine,paths=paths,inner_paths=inner_paths,seed=seed,
                      opening=opening,locked=locked,fraction=fraction,progress=progress)
    real_scale=plan['activation_cpi']/plan['cpi_2026']
    rows=[]
    for j,age in enumerate(trace['ages']):
        a=trace['investment'][:,j];b=trace['cash'][:,j]
        nominal_factor=nominal_anchor*(1+inflation_pct/100)**(j+(fraction if locked else 1.))
        entry=dict(trace['annual'][j],year=year0+j,
            nominal_factor_from_activation_real=nominal_factor,
            inflation_scenario_pct=inflation_pct)
        for name,arr in [('total',a+b),('investment',a),('cash',b)]:
            q=np.quantile(arr,[.1,.5,.9])
            entry[name+'_real_2026_twd']=(q/real_scale*1_000_000).tolist()
            entry[name+'_nominal_twd']=(q*nominal_factor*1_000_000).tolist()
        rows.append(entry)
    d=trace['diagnostics']
    for key in ('plan_success','lifetime_floor_success','required_expense_success','floor_and_required_success'):
        d[key+'_wilson_lower_95']=_lower_wilson(round(d[key]*paths),paths)
    for key in ('first_gap_amount_median_m','first_gap_amount_p90_m','first_gap_cash_before_median_m','first_gap_cash_after_median_m'):
        d[key[:-2]+'_real2026_twd']=None if d[key] is None else d[key]/real_scale*1e6
    return {'contract':CONTRACT,'status':'VALIDATED_CODE_RESEARCH_NOT_EXTERNALLY_CALIBRATED',
        'large_expense_schedule_sha256':schedule_digest(schedule_validate(state.get('expense_schedule'),plan)),
        'large_expense_schedule_resolved':resolved_schedule,
        'policy_sha256':'54dd2718a098c7f8182fcc44db980c523c2859fdaa276c50e81e8f8ea8712f10',
        'research_engine_sha256':hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        'projection_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'profile_sha256':plan.get('spending_profile_sha256'),
        'source_approval_id':row['approval']['approval_id'],'source_state_sha256':workflow.digest(state),
        'asof':asof,'start_age':age0,'end_age':104,'paths':paths,'inner_paths':inner_paths,'seed':seed,
        'percentiles':[10,50,90],'percentiles_are_not_pos':True,
        'all_paths_included':True,'first_approval_locked':locked is not None,
        'first_calendar_fraction':fraction,'first_pos_is_full_year_reference':True,
        'known_expense_contract':EXPENSE_CONTRACT,
        'legacy_first_pos_excludes_extra':bool(locked and opening.get('planned_extra_m') and row.get('expense_pos_contract')!=EXPENSE_CONTRACT),
        'nominal_is_inflation_scenario':True,'inflation_pct':inflation_pct,
        'seconds':trace['seconds'],'working_array_bytes':trace['working_array_bytes'],
        'diagnostics':d,'years':rows}
