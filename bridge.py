"""Whitelisted browser bridge around unchanged B+85 annual policy and local workflow.

Only called from Pyodide Web Worker; it has no network/API or brokerage access.
No eval, no dynamic code injection, no automatic official CPI claims.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from datetime import date
from workflow import AnnualWorkflow, InputError, digest, hydrate_approval, hydrate_close

STATE_PATH=Path('/home/pyodide/private/annual_records.json')
ENGINE: AnnualWorkflow | None = None


def _validate_import(export: dict):
    if not isinstance(export, dict) or export.get('file_kind') != 'local_yearly_research_export':
        raise InputError('只接受本工具產生的年度研究 JSON 備份')
    record=export.get('payload')
    if not isinstance(record, dict) or digest(record)!=export.get('sha256'):
        raise InputError('匯入檔案的 SHA256 不一致，已拒絕還原')
    if record.get('schema')!=1 or not isinstance(record.get('years'),list):
        raise InputError('備份版本或年度結構不相容')
    years=record['years']
    if len(years)>51:raise InputError('年度數量超出 104 歲模型範圍')
    if bool(years)!=bool(record.get('plan')):
        raise InputError('退休計畫與年度紀錄不一致')
    if years:
        plan=record['plan']
        if not isinstance(plan,dict) or plan.get('mode')!='SIMULATION_SHADOW_ONLY' or plan.get('fx_assumption')!=30 or plan.get('model_version')!='v3.4.0_B85':
            raise InputError('不接受不同政策或不同匯率的年度備份')
        if plan.get('stock_bond') not in ('70/30','65/35'):
            raise InputError('備份股債配置異常')
        for key in ('cpi_2026','activation_cpi'):
            if not isinstance(plan.get(key),(int,float)) or not 10 < plan[key] < 500:
                raise InputError('備份 CPI 值異常')
        first_year=plan.get('first_year');start_age=plan.get('start_age')
        if not isinstance(first_year,int) or not isinstance(start_age,int):raise InputError('備份起始資訊錯誤')
        for i,row in enumerate(years):
            if not isinstance(row,dict) or not isinstance(row.get('approval'),dict):raise InputError('備份年度格式不正確')
            appr=hydrate_approval(row['approval']);opening=appr.opening
            if opening.year!=first_year+i or opening.age!=start_age+i:
                raise InputError('年度或年齡有跳號，已拒絕還原')
            if opening.decision_date[:4]!=str(opening.year):raise InputError('決策年分異常')
            if date.fromisoformat(row['cpi_decision_release'])>date.fromisoformat(opening.decision_date):
                raise InputError('備份包含決策日尚未公布的 CPI')
            if row.get('close') is None:
                if i!=len(years)-1:raise InputError('不可還原跳過年度結算的備份')
            else:
                close=hydrate_close(row['close']);
                if not close.closing_event_sha256 or not row.get('statement'):
                    raise InputError('年度結算缺少必要憑證')
                if date.fromisoformat(row['closing_cpi_release'])>date.fromisoformat(row['closing_date']):
                    raise InputError('年度結算 CPI 來源日期異常')
    return copy.deepcopy(record)


def initialize(raw: str | None):
    global ENGINE
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    if raw:
        if len(raw)>5_000_000:raise InputError('既有本機帳務資料異常過大')
        try:
            saved=json.loads(raw)
            if not isinstance(saved,dict):raise ValueError('bad record')
        except ValueError as e:raise InputError('瀏覽器已儲存的年度資料無法解析；請匯入先前 JSON 備份') from e
        STATE_PATH.write_text(json.dumps(saved,ensure_ascii=False),encoding='utf-8')
    elif STATE_PATH.exists():STATE_PATH.unlink()
    ENGINE=AnnualWorkflow(STATE_PATH)
    return ENGINE.overview()


def dispatch(source: str):
    global ENGINE
    if ENGINE is None:raise InputError('B＋85 計算引擎尚未載入')
    p=json.loads(source)
    if not isinstance(p,dict):raise InputError('請求格式不正確')
    op=p.get('op');data=p.get('data',{})
    if not isinstance(data,dict):raise InputError('請求資料必須是物件')
    if op=='state':result=ENGINE.overview()
    elif op=='approve':result=ENGINE.approve(data)
    elif op=='close':result=ENGINE.close(data)
    elif op=='demo-close':result=ENGINE.demo_closing_balances()
    elif op=='export':result=ENGINE.export_data()
    elif op=='reset':result=ENGINE.reset(data.get('confirm',''))
    elif op=='import':
        record=_validate_import(data)
        backup=STATE_PATH.read_bytes() if STATE_PATH.exists() else None
        try:
            STATE_PATH.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
            new=AnnualWorkflow(STATE_PATH)
            result=new.overview()
            ENGINE=new
        except Exception:
            if backup is not None:STATE_PATH.write_bytes(backup)
            else:STATE_PATH.unlink(missing_ok=True)
            raise
    else:raise InputError('未允許的操作')
    changed=op in ('approve','close','reset','import')
    return json.dumps({'data':result, 'record':copy.deepcopy(ENGINE._state) if changed else None},ensure_ascii=False,allow_nan=False)
