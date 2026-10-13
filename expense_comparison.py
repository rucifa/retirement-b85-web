"""最新起點的成對必要支出研究；不替換已核准年度或執行提款。"""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from math import isfinite
from large_expenses import bind,known_cpi,validate,digest
from expense_contract import bind_current_expense
from projection_research import trace_paths
from capacity_research import _lower_wilson

CONTRACT='B85_PAIRED_LARGE_EXPENSE_RESEARCH_V1'

def compare_saved(state,paths=2048,inner_paths=512,seed=20261112,progress=None):
    import workflow
    from policy import retirement_model_v340 as frozen,personalized_research_engine as personal
    if not state.get('years') or not state.get('plan'):raise ValueError('請先建立年度核准，再比較未來支出')
    for value,low,high,label in ((paths,256,8192,'外層'),(inner_paths,128,4096,'內層')):
        if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:raise ValueError(f'{label}路徑數超出研究範圍')
    if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<=2**32-1:raise ValueError('亂數種子不合理')
    plan=state['plan'];row=state['years'][-1];o=row['approval']['opening'];cfg=workflow.policy_config(plan)
    engine=personal if plan.get('spending_profile') else frozen
    if row.get('close'):
        c=row['close'];year=o['year']+1;age=o['age']+1
        opening={'age':age,'investment_m':c['investment_next_m'],'safety_cash_m':c['safety_cash_next_m'],
            'sticky_before':c['sticky_next'],'emergency_pending':c['emergency_pending_next'],
            'prior_completed_net_real_return':c['net_portfolio_real_return']}
        ad_hoc=0.;origin='NEXT_YEAR_AFTER_CLOSE'
    else:
        year=o['year'];age=o['age'];opening=dict(o);origin='FULL_YEAR_COUNTERFACTUAL_PRE_APPROVAL'
        # 比較採完整年度的原政策；已核准的部分年度帳本仍完全保留。
        ad_hoc=(row['large_expense_snapshot']['ad_hoc_twd']/1e6*plan['activation_cpi']/row['cpi_decision']
                if row.get('large_expense_snapshot') else o['planned_extra_m'])
    if age>104:raise ValueError('已到104歲，沒有剩餘年度可比較')
    schedule=validate(state.get('expense_schedule'),plan);indices=known_cpi(state)
    scale=plan['activation_cpi']/plan['cpi_2026'];rows=[]
    for weight in (.70,.65):
        base=replace(cfg,stock_weight=weight)
        scheduled,resolved=bind(base,schedule,plan,indices,year)
        base=bind_current_expense(base,age,ad_hoc)
        extras=dict(scheduled.extra_mandatory_expense_by_age)
        if ad_hoc:extras[age]=extras.get(age,0.)+ad_hoc
        scheduled=replace(scheduled,extra_mandatory_expense_by_age=extras)
        for added,active in ((False,base),(True,scheduled)):
            number=len(rows)
            callback=(lambda done,total,num=number:progress(num*len(range(age,105))+done,4*len(range(age,105)))) if progress else None
            trace=trace_paths(active,engine=engine,paths=paths,inner_paths=inner_paths,seed=seed,opening=opening,progress=callback)
            d=dict(trace['diagnostics'])
            for key in ('plan_success','lifetime_floor_success','required_expense_success','floor_and_required_success'):
                d[key+'_wilson_lower_95']=_lower_wilson(round(d[key]*paths),paths)
            for key in ('first_gap_amount_median_m','first_gap_amount_p90_m','first_gap_cash_before_median_m','first_gap_cash_after_median_m'):
                d[key[:-2]+'_real2026_twd']=None if d[key] is None else d[key]/scale*1e6
            rows.append({'stock_bond':'70/30' if weight==.70 else '65/35','scheduled_expenses_included':added,
                         'diagnostics':d,'annual':[dict(r,year=year+j) for j,r in enumerate(trace['annual'])],
                         'seconds':trace['seconds']})
    return {'contract':CONTRACT,'status':'PAIRED_MODEL_RESEARCH_NOT_GLOBAL_CERTIFICATION','origin':origin,
            'source_state_sha256':workflow.digest(state),'source_approval_id':row['approval']['approval_id'],
            'schedule_sha256':digest(schedule),'schedule_revision':schedule['revision'],'start_year':year,'start_age':age,'end_age':104,
            'paths':paths,'inner_paths':inner_paths,'seed':seed,'same_market_and_emergency_streams':True,'full_year_reference':True,
            'first_gap_percentiles_conditioned_on_failed_paths':True,'years_without_gap_return_null':True,
            'scheduled_items':resolved,'rows':rows,'frozen_policy_sha256':sha256(Path(frozen.__file__).read_bytes()).hexdigest(),
            'note':'每種配置以相同市場及Emergency路徑比較；原換車及本年排程以外支出仍包含。待結算年度採付款前資產的完整年度反事實，不重寫原核准按日預算。購屋僅流出，房貸、租金、稅費、不動產價值未建模。'}
