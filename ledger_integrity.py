"""Validate economic continuity without recalculating saved policy decisions."""
from dataclasses import asdict
from math import isfinite,isclose
from expense_contract import CONTRACT


def validate_chain(record):
    import workflow
    from policy.simple_annual_ledger import YearEndBalances,close_from_balances
    prior=None
    seen=[]
    for row in record['years']:
        if row.get('large_expense_snapshot') is not None:
            from large_expenses import validate_snapshot,known_cpi,digest
            expected_indices=known_cpi({'years':seen},row['approval']['opening']['year'],row['cpi_decision'])
            if digest(expected_indices)!=digest(row['large_expense_snapshot']['known_cpi']):raise ValueError('支出快照混入非當時帳本的CPI資料')
            validate_snapshot(row['large_expense_snapshot'],record['plan'],row)
        approval=workflow.hydrate_approval(row['approval']);o=approval.opening;p=approval.policy_preview
        if row.get('expense_pos_contract') not in (None,CONTRACT):raise ValueError('未知必要支出契約')
        amounts=[o.investment_m,o.safety_cash_m,o.planned_extra_m,approval.spending_reserved_m,
            p.living_pool_paid_m,p.car_paid_m,p.extra_mandatory_paid_m,
            p.investment_before_return_m,p.safety_cash_before_return_m]
        if any(not isfinite(float(v)) or v<0 for v in amounts):raise ValueError('年度資產或金額不合理')
        if not isclose(o.investment_m+o.safety_cash_m,
            approval.spending_reserved_m+p.investment_before_return_m+p.safety_cash_before_return_m,abs_tol=1e-8,rel_tol=0):
            raise ValueError('年度核准資金不守恆')
        if not isclose(approval.spending_reserved_m,p.living_pool_paid_m+p.car_paid_m+p.extra_mandatory_paid_m,abs_tol=1e-8,rel_tol=0):
            raise ValueError('年度支出預算不一致')
        if prior:
            for a,b in [(o.investment_m,prior.investment_next_m),(o.safety_cash_m,prior.safety_cash_next_m),
                        (o.sticky_before,prior.sticky_next),(o.prior_completed_net_real_return,prior.net_portfolio_real_return)]:
                if a is None or not isclose(a,b,abs_tol=1e-8,rel_tol=0):raise ValueError('跨年資產或政策狀態不連續')
            if o.emergency_pending!=prior.emergency_pending_next:raise ValueError('跨年緊急狀態被重置')
        if row.get('close'):
            c=workflow.hydrate_close(row['close'])
            if c.approval_id!=approval.approval_id or c.year!=o.year or c.age!=o.age:raise ValueError('結算與核准身分不一致')
            s=row['statement'];ac=record['plan']['activation_cpi'];dc=row['cpi_decision'];cc=row['closing_cpi']
            real=lambda amount,cpi:workflow.real_m(amount,cpi,ac)
            statement=YearEndBalances(closing_date=row['closing_date'],investment_end_m=real(s['investment_end_twd'],cc),
                safety_cash_end_m=real(s['cash_end_twd'],cc),living_paid_m=real(s['living_paid_twd'],dc),
                car_paid_m=real(s['car_paid_twd'],dc),extra_paid_m=real(s['extra_paid_twd'],dc),event_id=c.closing_event_id)
            expected=asdict(close_from_balances(approval,statement));actual=asdict(c)
            for key,value in expected.items():
                observed=actual[key]
                if isinstance(value,float):
                    if not isfinite(observed) or not isclose(value,observed,abs_tol=1e-8,rel_tol=0):raise ValueError('結算憑證與金額不一致')
                elif value!=observed:raise ValueError('結算憑證或狀態不一致')
            prior=c
        seen.append(row)
