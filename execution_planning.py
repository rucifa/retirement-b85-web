"""核准預算來源與人工ETF出售候選；沒有下單、轉帳或付款狀態。"""
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math,re
from large_expenses import digest,money
from withdrawal_sources import attribution,_take,_nominal

CONTRACT='B85_SELL_PLANNING_V1'

def expense_sources(approval,snapshot,decision_cpi,activation_cpi):
    sources=attribution(approval,decision_cpi,activation_cpi)
    if sources['status']!='RECONCILED':return {'status':sources['status'],'items':[]}
    p=approval.policy_preview;o=approval.opening
    cash=o.safety_cash_m-p.bridge_from_cash_m
    inv,cash,_,_= _take(o.investment_m,cash,p.living_pool_paid_m-p.bridge_from_cash_m,'invest')
    inv,cash,_,_= _take(inv,cash,p.car_paid_m,'invest')
    lines=[]
    if snapshot:
        current=[x for x in snapshot['resolved'] if x['year']==o.year]
        lines=[{'id':x['id'],'label':x['title'] or {'car':'購車','housing':'購屋','medical':'醫療','other':'其他'}[x['category']],
                'category':x['category'],'amount':x['activation_real_m']} for x in current]
        ad_hoc=snapshot['ad_hoc_twd']/1e6*activation_cpi/decision_cpi
    else:ad_hoc=p.extra_mandatory_paid_m
    if ad_hoc:lines.append({'id':'annual-ad-hoc','label':'本年另列必要支出（排程以外）','category':'other','amount':ad_hoc})
    result=[]
    for line in lines:
        inv,cash,split,unpaid=_take(inv,cash,line['amount'],'invest')
        if unpaid>1e-8:return {'status':'UNAVAILABLE_REQUIRES_REVIEW','items':[]}
        result.append({k:v for k,v in line.items() if k!='amount'}|{k+'_twd':_nominal(v,decision_cpi,activation_cpi) for k,v in split.items()})
    if abs(sum(x['total_twd'] for x in result)-sources['extra']['total_twd'])>.02*max(1,len(result)):
        return {'status':'UNAVAILABLE_REQUIRES_REVIEW','items':[]}
    return {'status':'RECONCILED','items':result,'all_are_reserved_only':True,
            'cash_below_emergency_reference':sources['cash_after_approval_twd']+0.01<sources['emergency_reserve_reference_twd'],
            'investment_liquidity_needed_twd':sources['total']['invest_twd']+sources['cash_refill_transfer_twd'],
            'cash_refill_is_transfer_not_expense':True}

def valid_date(value,label):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError(f'請填{label}')
    try:return date.fromisoformat(value)
    except ValueError:raise ValueError(f'{label}不正確')

def normalize_input(data,approval_id):
    if not isinstance(data,dict) or set(data)-{'approval_id','asof_date','fx_twd_per_usd','broker_cash_twd','fee_estimate_twd','holdings'}:
        raise ValueError('出售規劃輸入格式不正確')
    if data.get('approval_id',approval_id)!=approval_id:raise ValueError('核准版本已變更，請重新規劃')
    asof=valid_date(data.get('asof_date'),'規劃日期')
    if not isinstance(data.get('holdings'),list) or not 1<=len(data['holdings'])<=40:raise ValueError('請填1至40筆持倉')
    holdings=[];keys=set()
    for raw in data['holdings']:
        if not isinstance(raw,dict) or set(raw)-{'ticker','broker','sleeve','currency','units','price','lot_step','quote_date'}:raise ValueError('持倉欄位格式不正確')
        ticker=raw.get('ticker','');broker=raw.get('broker','')
        if not isinstance(ticker,str) or not re.fullmatch(r'[A-Za-z0-9.^_-]{1,32}',ticker):raise ValueError('請填正確的ETF或證券代號')
        if not isinstance(broker,str) or not broker.strip() or len(broker)>60:raise ValueError('請填券商／帳戶識別（最多60字）')
        if raw.get('sleeve') not in ('stock','bond') or raw.get('currency') not in ('TWD','USD'):raise ValueError('初版只支援股票／債券及TWD／USD報價')
        try:price=float(raw['price'])
        except (ValueError,TypeError,KeyError):raise ValueError('請填有效報價')
        if isinstance(raw['price'],bool) or not math.isfinite(price) or not 0<price<=1e9:raise ValueError('報價須為有限正數')
        # 股數與交易單位可含零股精度，與金額的小數規則分開。
        try:units=float(raw['units']);step=float(raw['lot_step'])
        except (ValueError,TypeError,KeyError):raise ValueError('請填持有股數及最小交易單位')
        if isinstance(raw['units'],bool) or isinstance(raw['lot_step'],bool) or not math.isfinite(units) or not 0<=units<=1e9 or not math.isfinite(step) or not .000001<=step<=1e6:raise ValueError('股數或最小交易單位超出範圍')
        quote=valid_date(raw.get('quote_date'),'報價日期')
        if quote>asof:raise ValueError('報價日期不得晚於規劃日期')
        key=(ticker.upper(),broker.strip(),raw['currency'])
        if key in keys:raise ValueError('同券商同幣別持倉重複，請先合併股數')
        keys.add(key)
        holdings.append({'ticker':ticker.upper(),'broker':broker.strip(),'sleeve':raw['sleeve'],'currency':raw['currency'],
                         'units':units,'price':price,'lot_step':step,'quote_date':quote.isoformat()})
    usd=any(x['currency']=='USD' for x in holdings)
    fx=data.get('fx_twd_per_usd')
    if usd:
        if isinstance(fx,bool):raise ValueError('換匯估算不可為布林值')
        try:fx=float(fx)
        except (ValueError,TypeError):raise ValueError('請填美元換匯估算')
        if not math.isfinite(fx):raise ValueError('換匯估算須為有限數字')
        if not 1<=fx<=200:raise ValueError('請填有效美元換匯估算，不會自動採模型匯率30')
    elif fx in (None,''):fx=None
    else:
        try:fx=float(fx)
        except (ValueError,TypeError):raise ValueError('請填有效換匯估算')
        if not math.isfinite(fx) or not 1<=fx<=200:raise ValueError('換匯估算超出範圍')
    def optional(key):return money(data[key]) if data.get(key) not in (None,'') else 0.
    return {'approval_id':approval_id,'asof_date':asof.isoformat(),'fx_twd_per_usd':fx,
            'broker_cash_twd':optional('broker_cash_twd'),'fee_estimate_twd':optional('fee_estimate_twd'),
            'fee_estimate_provided':data.get('fee_estimate_twd') not in (None,''),'holdings':holdings}

def prepare(data,annual,plan):
    sources=annual['withdrawal_sources']
    if sources['status']!='RECONCILED':raise ValueError('核准來源尚未對帳，不能猜測出售資金')
    inputs=normalize_input(data,annual['approval_id'])
    asof=valid_date(inputs['asof_date'],'規劃日期')
    if asof.year!=annual['year'] or asof<valid_date(annual['decision_date'],'核准日期'):
        raise ValueError('規劃日期須在核准後且同一年度')
    needed=sources['total']['invest_twd']+sources['cash_refill_transfer_twd']
    liquid=max(0.,needed-inputs['broker_cash_twd']);fee=inputs['fee_estimate_twd'] if liquid else 0.
    gross=liquid+fee
    items=[]
    for h in inputs['holdings']:
        price=h['price']*(inputs['fx_twd_per_usd'] if h['currency']=='USD' else 1.)
        items.append({**h,'price_twd':price,'value_twd':h['units']*price,'sell_units':0.})
    total=sum(h['value_twd'] for h in items);stocks=sum(h['value_twd'] for h in items if h['sleeve']=='stock')
    stock_sell=min(gross,max(0.,stocks-plan['stock_weight']*max(0.,total-gross)))
    quotas={'stock':stock_sell,'bond':gross-stock_sell}
    def ceiling_units(amount,h):
        n=(Decimal(str(max(0.,amount)))/Decimal(str(h['price_twd']))/Decimal(str(h['lot_step']))).to_integral_value(rounding=ROUND_CEILING)
        cap=(Decimal(str(h['units']))/Decimal(str(h['lot_step']))).to_integral_value(rounding=ROUND_FLOOR)
        return float(min(n,cap)*Decimal(str(h['lot_step'])))
    for sleeve,quota in quotas.items():
        sleeve_total=sum(h['value_twd'] for h in items if h['sleeve']==sleeve)
        for h in items:
            if h['sleeve']==sleeve and sleeve_total:h['sell_units']=ceiling_units(quota*h['value_twd']/sleeve_total,h)
    sold=sum(h['sell_units']*h['price_twd'] for h in items)
    if sold+1e-6<gross:
        for h in items:
            remaining=gross-sold
            if remaining<=1e-6:break
            cap=ceiling_units(h['value_twd'],h)
            added=min(cap-h['sell_units'],ceiling_units(remaining,h))
            if added>0:h['sell_units']+=added;sold+=added*h['price_twd']
    if sold==0:fee=0.
    if fee>sold:raise ValueError('費稅估計高於可出售金額，請先核對報價與費用')
    net=sold-fee;covered=inputs['broker_cash_twd']+net+0.01>=needed
    after=max(0.,total-sold);stock_after=max(0.,stocks-sum(h['sell_units']*h['price_twd'] for h in items if h['sleeve']=='stock'))
    result={'contract':CONTRACT,'mode':'PLANNING_ONLY_NO_TRANSACTIONS','status':'CANDIDATE_REQUIRES_BROKER_REVIEW' if covered else 'INSUFFICIENT_QUOTED_HOLDINGS',
            'approval_id':annual['approval_id'],'invest_for_spending_twd':sources['total']['invest_twd'],
            'invest_for_cash_refill_twd':sources['cash_refill_transfer_twd'],'total_invest_liquidity_needed_twd':needed,
            'safety_cash_for_spending_twd':sources['total']['cash_twd'],'available_broker_cash_twd':inputs['broker_cash_twd'],
            'estimated_gross_sell_twd':sold,'estimated_fees_twd':fee,'estimated_net_sell_twd':net,
            'liquidity_shortfall_twd':max(0.,needed-inputs['broker_cash_twd']-net),'rounding_excess_twd':max(0.,inputs['broker_cash_twd']+net-needed),
            'quoted_portfolio_twd':total+inputs['broker_cash_twd'],'difference_from_opening_investment_twd':total+inputs['broker_cash_twd']-annual['investment_open_twd'],
            'estimated_after_stock_weight':stock_after/after if after else None,'target_stock_weight':plan['stock_weight'],'orders':items,
            'pending_checks':['報價及股票／債券分類','券商可賣股數、零股與最小交易單位','交易費、稅費及實際換匯','交割與可提款日、銀行轉帳時程','持倉與年度資產對帳，安全現金用途確認'],
            'fee_estimate_provided':inputs['fee_estimate_provided'],
            'warning':'僅為人工輸入資料的出售候選，沒有下單、換匯、轉帳或付款。費用只用於出售淨額估算，不再扣退休模型摩擦。'}
    saved={'contract':CONTRACT,'mode':'PLANNING_ONLY_NO_TRANSACTIONS','input':inputs}
    saved['sha256']=digest(saved)
    return result,saved

def validate_saved_plans(record):
    saved=record.get('execution_plans',{})
    if not isinstance(saved,dict) or len(saved)>60:raise ValueError('出售規劃備份格式不正確')
    ids={r['approval']['approval_id'] for r in record['years']}
    for key,value in saved.items():
        if key not in ids or not isinstance(value,dict) or set(value)!={'contract','mode','input','sha256'}:raise ValueError('出售規劃缺少相符年度')
        if value['contract']!=CONTRACT or value['mode']!='PLANNING_ONLY_NO_TRANSACTIONS':raise ValueError('備份不得冒充已執行交易')
        if digest({k:v for k,v in value.items() if k!='sha256'})!=value['sha256']:raise ValueError('出售規劃指紋不一致')
        raw={k:v for k,v in value['input'].items() if k!='fee_estimate_provided'}
        normalized=normalize_input(raw,key)
        # 未填費用與填零的標記不同；金額與其餘欄位必須一致。
        normalized['fee_estimate_provided']=value['input'].get('fee_estimate_provided')
        if not isinstance(normalized['fee_estimate_provided'],bool) or digest(normalized)!=digest(value['input']):raise ValueError('出售規劃輸入資料不一致')
