"""Local-first B+85 research-only end-to-end annual UI workflow.

Preserves the approved B+85 policy module, the simple two-stage accounting
module and their fail-closed LIVE gate. No web access, brokerage, GitHub writes,
or automated trades. State persists as local JSON through atomic replacement.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any
import copy
import json
import math
import os
import tempfile

from policy.retirement_model_v340 import ModelConfig, FRICTIONS, normal_living_spend
from policy.simple_annual_ledger import (
    AnnualOpening, YearApproval, YearClose, YearEndBalances, approve_year,
    close_from_balances, nominal_to_activation_real, USD_TWD_ASSUMED,
)
from policy.annual_execution_v340 import AnnualResult
from calendar_first_year import MODE as CALENDAR_MODE, prorate_first_year

MILLION = 1_000_000
STATE_VERSION = 1
SEED = 20261011
# This is intentionally smaller than a production decision-quality PoS run.
INNER_DRAWS = 4096

class InputError(ValueError):
    """Prevent misuse, invalid data or ambiguity in a research-only workflow."""


def amt(obj: dict, key: str, *, positive: bool = False) -> float:
    if key not in obj or obj[key] is None or str(obj[key]).strip() == '':
        raise InputError(f'缺少欄位：{key}')
    try:
        raw = Decimal(str(obj[key]).replace(',', ''))
    except (InvalidOperation, ValueError, TypeError):
        raise InputError(f'欄位 {key} 不是有效數字')
    if not raw.is_finite():
        raise InputError(f'欄位 {key} 不能是無限大或 NaN')
    v=float(raw)
    if v<0 or (positive and v<=0) or not math.isfinite(v) or v>1_000_000_000_000:
        raise InputError(f'欄位 {key} 必須為有限、非負且合理的數值')
    return v


def integral(obj:dict,key:str,low:int,high:int)->int:
    if key not in obj or isinstance(obj[key],bool): raise InputError(f'請填正確的 {key}')
    try: v=int(str(obj[key]))
    except (ValueError,TypeError):raise InputError(f'請填正確的 {key}')
    if str(v)!=str(obj[key]) or not low<=v<=high:raise InputError(f'{key} 不在允許範圍')
    return v


def valid_date(s: str, field: str) -> date:
    try:
        if not isinstance(s,str) or len(s)!=10:raise ValueError()
        return date.fromisoformat(s)
    except ValueError: raise InputError(f'{field} 日期不正確')


def source_date(effective_date:str,publication_date:str, label:str)->None:
    a=valid_date(effective_date,'決策／結算')
    b=valid_date(publication_date, label+'發布')
    if b>a: raise InputError(f'{label} 的公布日期晚於使用日期，不可偷看未來數據')


def real_m(nominal: float, current_cpi: float, activation_cpi: float) -> float:
    return nominal_to_activation_real(nominal/MILLION,current_cpi,activation_cpi)


def nominal_twd(real_million: float,current_cpi:float,activation_cpi:float)->float:
    return round(real_million * MILLION * current_cpi / activation_cpi,2)


def copy_json(d:dict)->dict:
    return json.loads(json.dumps(d,ensure_ascii=False,allow_nan=False))


def digest(obj)->str:
    return sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def policy_config(base:dict)->ModelConfig:
    return ModelConfig(
        start_age=base['start_age'],end_age=104,
        stock_weight=base['stock_weight'],
        activation_cpi_factor_from_2026=base['activation_cpi']/base['cpi_2026'],
        use_prosperity=True,prosperity_spending_mode='recommended_target',
        use_charity=False,
        friction=FRICTIONS['net_central_2026ref'],
    )


def hydrate_approval(stored:dict)->YearApproval:
    return YearApproval(
        opening=AnnualOpening(**stored['opening']),
        policy_preview=AnnualResult(**stored['policy_preview']),
        spending_reserved_m=stored['spending_reserved_m'],
        approval_id=stored['approval_id'],
        mode=stored['mode'],
    )


def hydrate_close(stored:dict)->YearClose:
    return YearClose(**stored)


class AnnualWorkflow:
    """One-person, offline, demo/shadow-mode yearly flow. Never a LIVE router."""
    def __init__(self,path: Path):
        self.path=Path(path)
        self.lock=RLock()
        self._state=self._read()

    def _read(self)->dict:
        if not self.path.exists():return {'schema':STATE_VERSION,'plan':None,'years':[]}
        b=self.path.read_bytes()
        try:d=json.loads(b)
        except (ValueError,UnicodeError):raise InputError('本機紀錄檔無法解析，已停止使用以避免覆寫')
        if d.get('schema')!=STATE_VERSION or not isinstance(d.get('years'),list):
            raise InputError('紀錄檔版本不相容，請先備份，不要覆寫')
        return d

    def _commit(self,new:dict):
        # Atomic replacement; durable store stays private on the local machine.
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.ledger-',suffix='.tmp')
        try:
            if os.name!='nt':os.fchmod(fd,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump(new,f,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)
                f.write('\n');f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        self._state=new

    def overview(self)->dict:
        with self.lock:
            return copy_json({
                'mode':'SIMULATION_SHADOW_ONLY',
                'model':'v3.4.0 B+85',
                'money':'TWD_nominal_in_UI; retirement_activation_year_real_in_model',
                'usd_twd':USD_TWD_ASSUMED,
                'poS_method':'Inner Monte Carlo, fixed seed and %d paths (research, not guarantee)'%INNER_DRAWS,
                'plan':self._state['plan'],
                'years': [self._public_year(x) for x in self._state['years']],
                'has_data':bool(self._state['years']),
                'has_pending_close':bool(self._state['years'] and self._state['years'][-1]['close'] is None),
                'policy_active':False,
            })

    def _public_year(self,y:dict)->dict:
        approval=hydrate_approval(y['approval'])
        opening=approval.opening
        closing =y['close']
        decision_cpi=y['cpi_decision']
        activation_cpi=self._state['plan']['activation_cpi']
        pv=approval.policy_preview
        cfg=policy_config(self._state['plan'])
        action=('B85_RESTORED' if pv.b85_restored
                else 'CUT_10_PERCENT' if pv.pos<=cfg.guardrail_low
                else 'RAISE_10_PERCENT' if pv.pos>=cfg.guardrail_high else 'HOLD')
        result={
            'year':opening.year,'age':opening.age,'decision_date':opening.decision_date,
            'status':'CLOSED' if closing else 'APPROVED_RESEARCH',
            'decision_cpi':decision_cpi,'decision_cpi_release':y['cpi_decision_release'],
            'decision_cpi_source':y.get('cpi_decision_source','LEGACY_UNTAGGED'),
            'approval_id':approval.approval_id,
            'pos_pct':round(pv.pos*100,2),
            'normal_pos_pct':round(pv.normal_pos*100,2) if pv.normal_pos is not None else None,
            'b85_restored':pv.b85_restored,
            'sticky_before':round(opening.sticky_before,5),
            'sticky_after':round(pv.sticky_after,5),
            'guardrail_action':action,
            'guardrail_low_pct':cfg.guardrail_low*100,
            'guardrail_high_pct':cfg.guardrail_high*100,
            'normal_reference_twd':nominal_twd(normal_living_spend(opening.age,cfg),decision_cpi,activation_cpi),
            'floor_reference_twd':nominal_twd(cfg.floor_spend*cfg.activation_cpi_factor_from_2026,decision_cpi,activation_cpi),
            'living_authorized_twd':nominal_twd(approval.living_budget_m,decision_cpi,activation_cpi),
            'car_authorized_twd':nominal_twd(approval.car_budget_m,decision_cpi,activation_cpi),
            'extra_authorized_twd':nominal_twd(approval.extra_budget_m,decision_cpi,activation_cpi),
            'bridge_from_cash_twd':nominal_twd(pv.bridge_from_cash_m,decision_cpi,activation_cpi),
            'cash_refill_twd':nominal_twd(pv.cash_refill_m,decision_cpi,activation_cpi),
            'total_budget_twd':nominal_twd(approval.spending_reserved_m,decision_cpi,activation_cpi),
            'investment_open_twd':nominal_twd(opening.investment_m,decision_cpi,activation_cpi),
            'cash_open_twd':nominal_twd(opening.safety_cash_m,decision_cpi,activation_cpi),
            'emergency_pending':opening.emergency_pending,
            'assumed_drag_description':'已在 B+85 市場模型的 net_central_2026ref 情境中計入一次，年末不重扣。',
        }
        meta=y.get('calendar_first_year')
        if meta:
            result.update({
                'calendar_first_year':True,
                'period_start':meta['period_start'],'period_end':meta['period_end'],
                'calendar_days':meta['calendar_days'],'calendar_year_days':meta['calendar_year_days'],
                'calendar_fraction':meta['calendar_fraction'],
                'full_year_living_reference_twd':nominal_twd(meta['full_year_living_budget_m'],decision_cpi,activation_cpi),
                'pos_period_label':'全年政策 PoS 參考，尚非部分年度精算'
            })
        else:
            result.update({'calendar_first_year':False,'period_start':opening.decision_date,
                           'period_end':f'{opening.year}-12-31','calendar_fraction':1,
                           'pos_period_label':'全年政策 PoS 參考'})
        if closing:
            c=hydrate_close(closing)
            close_cpi=y['closing_cpi']
            result['closing']={
                'date':y['closing_date'],
                'cpi':close_cpi,
                'cpi_release':y['closing_cpi_release'],
                'investment_end_twd':nominal_twd(c.investment_next_m,close_cpi,activation_cpi),
                'cash_end_twd':nominal_twd(c.safety_cash_next_m,close_cpi,activation_cpi),
                'actual_paid_twd':y['statement']['living_paid_twd']+y['statement']['car_paid_twd']+y['statement']['extra_paid_twd'],
                'unused_budget_real_twd':round(c.unused_budget_returned_to_cash_m*MILLION,2),
                'unused_budget_at_close_twd':nominal_twd(c.unused_budget_returned_to_cash_m,close_cpi,activation_cpi),
                'net_real_portfolio_return_pct':round(c.net_portfolio_real_return*100,4),
                'balance_reconciliation_error_twd':round(c.reconciliation_error_m*MILLION,6),
                'sha256':c.closing_event_sha256,
            }
        return result

    def _validate_asof(self,data:dict,period_date:str, prefix:str)->tuple[float,str]:
        ci=amt(data,prefix+'_cpi',positive=True)
        pub=data.get(prefix+'_cpi_release','')
        source_date(period_date,pub,prefix.upper()+' CPI')
        # Official base currently published as 2021=100; the model uses ratios.
        if ci < 10 or ci > 500:raise InputError('CPI 指數格式不合理，請確認輸入的是指數值而非年增率')
        return ci,pub

    def approve(self,data:dict)->dict:
        with self.lock:
            prior=self._state['years'][-1] if self._state['years'] else None
            if prior and not prior['close']:
                raise InputError('上一年度尚未結算；不可直接開始下一年度')
            if prior and self._state['years'][-1]['approval']['opening']['age']>=104:
                raise InputError('已到達 104 歲模型終點')
            dt=data.get('decision_date','')
            decision=valid_date(dt,'年初決策')
            if prior is not None and decision.month!=1:
                raise InputError('曆年制在第一年後必須於每年一月核准完整年度')
            origin=data.get('decision_cpi_source','MANUAL')
            if origin=='SCENARIO_2026_BASELINE':
                if prior is not None or decision.year!=2026:
                    raise InputError('2026 基準假設只適用於 2026 年首次退休的演練')
                current_cpi=amt(data,'decision_cpi',positive=True)
                base_assumed=amt(data,'cpi_2026',positive=True)
                if not math.isclose(current_cpi,base_assumed,rel_tol=0,abs_tol=0.001):
                    raise InputError('決策 CPI 須與設定的 2026 基準假設一致')
                if data.get('decision_cpi_release')!=dt:
                    raise InputError('假設生效日應等於決策日，不能視為官方 CPI 公布日')
                if not 10<current_cpi<500:raise InputError('CPI 假設指數不合理')
                release=dt  # Effective as-of for a scenario, not official CPI.
            else:
                if origin not in ('MANUAL','OFFICIAL_BULLETIN','MISSING_HISTORICAL_CPI'):
                    raise InputError('不支援的 CPI 資料來源標籤')
                current_cpi,release=self._validate_asof(data,dt,'decision')
            if prior is None:
                start_age=integral(data,'start_age',45,90)
                y=decision.year
                if y<2026:raise InputError('起始年度不得早於 2026')
                strategy=data.get('stock_bond')
                if strategy not in ('70/30','65/35'):
                    raise InputError('股債配置只能選擇 70/30 或 65/35')
                stock_weight=.70 if strategy=='70/30' else .65
                cpi_2026=amt(data,'cpi_2026',positive=True)
                if not 10<cpi_2026<500:raise InputError('2026 CPI 基準值不合理')
                inv=amt(data,'investment_twd')
                cash=amt(data,'cash_twd')
                if inv+cash<=0:raise InputError('初始資產不可為零')
                # Retirement activation year is the purchasing-power base.
                opening=AnnualOpening(year=y,decision_date=dt,age=start_age,start_age=start_age,
                                      investment_m=inv/MILLION,safety_cash_m=cash/MILLION,
                                      planned_extra_m=amt(data,'planned_extra_twd')/MILLION)
                plan={'first_year':y,'start_age':start_age,'stock_bond':strategy,
                      'stock_weight':stock_weight,'cpi_2026':cpi_2026,
                      'activation_cpi':current_cpi,'fx_assumption':30,
                      'mode':'SIMULATION_SHADOW_ONLY',
                      'cost_assumption':'net_central_2026ref',
                      'model_version':'v3.4.0_B85',
                      'seed':SEED,'inner_paths':INNER_DRAWS,
                      'calendar_first_year_contract':CALENDAR_MODE}
                prior_close=None
            else:
                plan=self._state['plan']
                prev_open=prior['approval']['opening']
                if decision.year!=prev_open['year']+1:raise InputError('必須逐年遞增，不可跳年')
                c=hydrate_close(prior['close'])
                opening=AnnualOpening(
                    year=decision.year,decision_date=dt,
                    age=prev_open['age']+1,start_age=plan['start_age'],
                    investment_m=c.investment_next_m,safety_cash_m=c.safety_cash_next_m,
                    sticky_before=c.sticky_next,
                    emergency_pending=c.emergency_pending_next,
                    prior_completed_net_real_return=c.net_portfolio_real_return,
                    planned_extra_m=real_m(amt(data,'planned_extra_twd'),current_cpi,plan['activation_cpi']))
                prior_close=c
                # Beginning-of-year nominal values are reference previews only;
                # no unverified external contributions/transfers are inferred.
            cfg=policy_config(plan)
            try:
                approval=approve_year(opening,cfg,n_inner=INNER_DRAWS,seed=SEED,prior_close=prior_close)
                first_calendar=None
                if prior is None:
                    approval,first_calendar=prorate_first_year(approval)
            except (ValueError,ArithmeticError,OverflowError) as e:raise InputError('B＋85 年度核准遭拒：'+str(e)) from e
            row={
                'approval':asdict(approval),
                'cpi_decision':current_cpi,'cpi_decision_release':release,'cpi_decision_source':origin,
                'closing_cpi':None,'closing_cpi_release':None,
                'closing_date':None,'close':None,'statement':None,
            }
            if first_calendar is not None:
                row['calendar_first_year']=first_calendar

            new=copy.deepcopy(self._state)
            new['plan']=plan;new['years'].append(row)
            self._commit(new)
            return {'approval':self._public_year(row),'overview':self.overview()}

    def close(self,data:dict)->dict:
        with self.lock:
            if not self._state['years']:raise InputError('尚無年初核准紀錄')
            row=self._state['years'][-1]
            if row['close'] is not None:raise InputError('該年度已結算；禁止重複結算或覆寫')
            approval=hydrate_approval(row['approval'])
            closing_date=data.get('closing_date','')
            closing=valid_date(closing_date,'年末結算')
            if closing.year!=approval.opening.year or closing<date.fromisoformat(approval.opening.decision_date) or (closing==date.fromisoformat(approval.opening.decision_date) and approval.mode!=CALENDAR_MODE):
                raise InputError('結算日期必須在核准後且同一年度')
            close_cpi,pub=self._validate_asof(data,closing_date,'closing')
            if close_cpi + 1e-8 < row['cpi_decision']*.5 or close_cpi>row['cpi_decision']*2:
                raise InputError('年內 CPI 變動異常，請檢查指數欄位')
            plan=self._state['plan']
            living=amt(data,'living_paid_twd');car=amt(data,'car_paid_twd');extras=amt(data,'extra_paid_twd')
            invested=amt(data,'investment_end_twd');cash=amt(data,'cash_end_twd')
            if amt(data,'emergency_paid_twd')>0:
                raise InputError('緊急支出必須另外驗證資金來源，簡化流程暫不直接結算')
            if amt(data,'external_flow_twd')>0:
                raise InputError('有額外入金／轉帳時，需要交易核對，不能把它當成市場報酬')
            # Converting actual expenses at decision CPI is a declared annual
            # approximation; each year-end balance uses closing CPI exactly.
            real_exp=lambda amount:real_m(amount,row['cpi_decision'],plan['activation_cpi'])
            st=YearEndBalances(closing_date=closing_date,
                investment_end_m=real_m(invested,close_cpi,plan['activation_cpi']),
                safety_cash_end_m=real_m(cash,close_cpi,plan['activation_cpi']),
                living_paid_m=real_exp(living),car_paid_m=real_exp(car),
                extra_paid_m=real_exp(extras),event_id=f'{approval.opening.year}-annual-close')
            try:result=close_from_balances(approval,st)
            except (ValueError,ArithmeticError) as e:raise InputError('年度資產未通過對帳：'+str(e)) from e
            new=copy.deepcopy(self._state)
            row=new['years'][-1]
            row.update({'closing_cpi':close_cpi,'closing_cpi_release':pub,'closing_date':closing_date,
                        'close':asdict(result),
                        'statement':{'living_paid_twd':living,'car_paid_twd':car,
                          'extra_paid_twd':extras,'investment_end_twd':invested,
                          'cash_end_twd':cash,'decision_cpi':row['cpi_decision'],
                          'closing_cpi':close_cpi,'closing_date':closing_date}})
            self._commit(new)
            return {'year_close':self._public_year(row),'overview':self.overview()}

    def demo_closing_balances(self)->dict:
        with self.lock:
            if not self._state['years'] or self._state['years'][-1]['close'] is not None:
                raise InputError('目前沒有等待結算的年初核准')
            row=self._state['years'][-1]
            p=hydrate_approval(row['approval'])
            ci=row['cpi_decision'];ac=self._state['plan']['activation_cpi']
            living=nominal_twd(max(0,p.living_budget_m-.08),ci,ac)
            car=nominal_twd(p.car_budget_m,ci,ac)
            extra=nominal_twd(p.extra_budget_m,ci,ac)
            unused=p.spending_reserved_m-(max(0,p.living_budget_m-.08)+p.car_budget_m+p.extra_budget_m)
            # Same CPI => deterministic demo values; user can edit.
            inv=nominal_twd(p.policy_preview.investment_before_return_m*1.05,ci,ac)
            cash=nominal_twd(p.policy_preview.safety_cash_before_return_m*0.99+unused,ci,ac)
            return {'closing_date':f'{p.opening.year}-12-31','closing_cpi':ci,
                    'closing_cpi_release':f'{p.opening.year}-12-20',
                    'investment_end_twd':inv,'cash_end_twd':cash,
                    'living_paid_twd':living,'car_paid_twd':car,'extra_paid_twd':extra,
                    'emergency_paid_twd':0,'external_flow_twd':0,
                    'simulation_note':'假設投資池實質 +5%、現金實質 −1%、生活費少花約 8 萬元（實質購買力）'}

    def export_data(self)->dict:
        with self.lock:
            payload=copy_json(self._state)
            return {'mode':'SIMULATION_SHADOW_ONLY','file_kind':'local_yearly_research_export',
                    'payload':payload,'sha256':digest(payload)}

    def reset(self,word: str):
        if word!='清除演練':raise InputError('請輸入指定的重設確認文字')
        with self.lock:
            if self.path.exists():
                backup=self.path.with_name('retirement-backup-'+date.today().isoformat()+'.json')
                if backup.exists():
                    backup=self.path.with_name('retirement-backup-'+date.today().isoformat()+'-'+sha256(self.path.read_bytes()).hexdigest()[:12]+'.json')
                backup.write_bytes(self.path.read_bytes())
            self._commit({'schema':STATE_VERSION,'plan':None,'years':[]})
            return self.overview()
