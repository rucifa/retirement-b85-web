"""多筆必要支出適配；不更動凍結政策，所有金額先統一購買力。"""
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import copy, json, math, re, uuid

CONTRACT = 'B85_LARGE_EXPENSE_SCHEDULE_V1'
CATEGORIES = {'car':'購車','housing':'購屋','medical':'醫療','other':'其他'}
BASES = {'real_2026','nominal_year'}

def digest(value):
    def canonical(x):
        if isinstance(x,dict):return {k:canonical(v) for k,v in x.items()}
        if isinstance(x,list):return [canonical(v) for v in x]
        if isinstance(x,float) and math.isfinite(x) and x.is_integer():return int(x)
        return x
    return sha256(json.dumps(canonical(value),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def money(value, positive=False):
    if isinstance(value,bool) or value is None or str(value).strip()=='':raise ValueError('請填支出金額')
    try: n=Decimal(str(value).replace(',',''))
    except InvalidOperation:raise ValueError('支出金額格式不正確')
    if not n.is_finite() or n<0 or n>Decimal('1000000000000') or (positive and n<=0) or n!=n.quantize(Decimal('.01')):
        raise ValueError('金額須為有限非負數，最多兩位小數；新增支出須大於零')
    return float(n)

def year(value):
    if isinstance(value,bool) or not re.fullmatch(r'\d{4}',str(value)) or not 2026<=int(value)<=2200:
        raise ValueError('請填2026至2200之間的完整年度')
    return int(value)

def empty():return {'contract':CONTRACT,'revision':0,'inflation_pct':2.,'entries':[]}

def entry(raw):
    if not isinstance(raw,dict) or set(raw)-{'id','year','category','amount_twd','basis','price_year','title'}:
        raise ValueError('支出項目格式或欄位不正確')
    key=raw.get('id','')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',key):raise ValueError('支出項目識別碼不正確')
    cat=raw.get('category');basis=raw.get('basis')
    if cat not in CATEGORIES or basis not in BASES:raise ValueError('請選擇支出類別與物價基準')
    title=raw.get('title','')
    if not isinstance(title,str) or len(title.strip())>100:raise ValueError('項目說明最多100字')
    due=year(raw.get('year'));price=year(raw.get('price_year')) if basis=='nominal_year' else None
    if basis=='real_2026' and raw.get('price_year') not in (None,''):raise ValueError('2026實質金額不應另填名目基準年')
    return {'id':key,'year':due,'category':cat,'amount_twd':money(raw.get('amount_twd'),True),
            'basis':basis,'price_year':price,'title':title.strip()}

def validate(raw, plan=None):
    if raw is None:return empty()
    if not isinstance(raw,dict) or set(raw)!={'contract','revision','inflation_pct','entries'} or raw['contract']!=CONTRACT:
        raise ValueError('不支援的大額支出排程版本')
    revision=raw['revision'];inflation=raw['inflation_pct']
    if isinstance(revision,bool) or not isinstance(revision,int) or revision<0:raise ValueError('排程版本不正確')
    if isinstance(inflation,bool) or not isinstance(inflation,(int,float)) or not math.isfinite(inflation) or not -5<=inflation<=15:
        raise ValueError('支出換算通膨假設須為−5%至15%')
    if not isinstance(raw['entries'],list) or len(raw['entries'])>100:raise ValueError('排程最多100筆')
    items=sorted([entry(e) for e in raw['entries']],key=lambda e:(e['year'],e['id']))
    ids=set();signatures=set();cars=set()
    for e in items:
        if e['id'] in ids:raise ValueError('支出項目識別碼重複')
        ids.add(e['id']);signature=tuple(e[k] for k in ('year','category','amount_twd','basis','price_year','title'))
        if signature in signatures:raise ValueError('相同支出已存在，請勿重複新增')
        signatures.add(signature)
        if e['category']=='car':
            if e['year'] in cars:raise ValueError('同年度已有手動購車支出，請合併為一筆')
            cars.add(e['year'])
        if plan:
            age=plan['start_age']+e['year']-plan['first_year']
            if not plan['start_age']<=age<=104:raise ValueError('支出年度須在退休開始年至104歲之間')
            if age in (60,70,80,90) and (e['category']=='car' or re.search('購車|換車|買車',e['title'])):
                raise ValueError(f"{e['year']}年已有凍結政策定期換車，不能重複新增；修改原換車排程須另作政策決定")
    return {'contract':CONTRACT,'revision':revision,'inflation_pct':float(inflation),'entries':items}

def mutate(raw, action, data, plan=None, locked_year=None):
    value=validate(raw,plan);new=copy.deepcopy(value)
    if action=='inflation':
        try:new['inflation_pct']=float(data['inflation_pct'])
        except (ValueError,TypeError,KeyError):raise ValueError('請填支出換算通膨假設')
    elif action=='delete':
        found=next((e for e in new['entries'] if e['id']==data.get('id')),None)
        if found is None:raise ValueError('找不到該支出項目')
        if locked_year is not None and found['year']<=locked_year:raise ValueError('已核准年度支出不可刪除，請保留原始紀錄')
        new['entries'].remove(found)
    elif action=='upsert':
        proposed=dict(data);key=proposed.get('id')
        old=next((e for e in new['entries'] if e['id']==key),None)
        if key and old is None:raise ValueError('修改的支出項目不存在')
        if not key:proposed['id']=uuid.uuid4().hex
        e=entry(proposed)
        if locked_year is not None and (e['year']<=locked_year or (old and old['year']<=locked_year)):
            raise ValueError('已核准年度不可新增或修改支出，未來年度可編輯')
        if old:new['entries'].remove(old)
        new['entries'].append(e)
    else:raise ValueError('未知排程操作')
    new['revision']+=1
    return validate(new,plan)

def known_cpi(record, current_year=None, current_cpi=None):
    values={str(r['approval']['opening']['year']):r['cpi_decision'] for r in record.get('years',[])}
    if current_year is not None:values[str(current_year)]=current_cpi
    return values

def resolve(raw,plan,indices,from_year=None):
    schedule=validate(raw,plan);indices={int(k):float(v) for k,v in indices.items()}
    if not indices or any(not math.isfinite(v) or not 10<v<500 for v in indices.values()):raise ValueError('支出換算需要有效CPI參考')
    latest=max(indices);ci=indices[latest];rate=1+schedule['inflation_pct']/100
    resolved=[];by_age={}
    for e in schedule['entries']:
        if from_year is not None and e['year']<from_year:continue
        if e['basis']=='real_2026':
            real=e['amount_twd'];price_ci=plan['cpi_2026'];source='2026_FIXED_PURCHASING_POWER'
        else:
            price_ci=indices.get(e['price_year'])
            source='SAVED_DECISION_CPI' if price_ci is not None else 'EXPLICIT_INFLATION_SCENARIO'
            if price_ci is None:price_ci=ci*rate**(e['price_year']-latest)
            real=e['amount_twd']*plan['cpi_2026']/price_ci
        if not math.isfinite(real) or not 0<real<=1e12:raise ValueError('換算後支出超出研究範圍')
        activation_m=real*plan['activation_cpi']/plan['cpi_2026']/1e6
        age=plan['start_age']+e['year']-plan['first_year']
        by_age[age]=by_age.get(age,0.)+activation_m
        due_ci=indices.get(e['year'],ci*rate**(e['year']-latest))
        resolved.append({**e,'age':age,'real_2026_twd':real,'activation_real_m':activation_m,
                         'nominal_due_twd':real*due_ci/plan['cpi_2026'],'price_cpi_used':price_ci,
                         'conversion_source':source,'due_cpi_is_scenario':e['year'] not in indices})
    return by_age,resolved

def bind(cfg,raw,plan,indices,from_year):
    by_age,items=resolve(raw,plan,indices,from_year)
    if not by_age:return cfg,items
    combined=dict(cfg.extra_mandatory_expense_by_age)
    for age,value in by_age.items():combined[age]=combined.get(age,0.)+value
    return replace(cfg,extra_mandatory_expense_by_age=combined),items

def capture(raw,plan,indices,current_year,ad_hoc_twd):
    schedule=validate(raw,plan);_,items=resolve(schedule,plan,indices,current_year)
    data={'contract':CONTRACT,'schedule':schedule,'known_cpi':indices,'year':current_year,
          'ad_hoc_twd':money(ad_hoc_twd),'resolved':items}
    return {**data,'sha256':digest(data)}

def validate_snapshot(snapshot,plan,row):
    if not isinstance(snapshot,dict):raise ValueError('支出核准快照格式不正確')
    payload={k:v for k,v in snapshot.items() if k!='sha256'}
    if digest(payload)!=snapshot.get('sha256') or snapshot.get('contract')!=CONTRACT:raise ValueError('支出核准快照指紋不一致')
    if snapshot['year']!=row['approval']['opening']['year']:raise ValueError('支出快照年度不一致')
    if abs(float(snapshot['known_cpi'][str(snapshot['year'])])-row['cpi_decision'])>1e-8:raise ValueError('支出快照CPI不一致')
    expected=capture(snapshot['schedule'],plan,snapshot['known_cpi'],snapshot['year'],snapshot['ad_hoc_twd'])
    if digest(expected)!=digest(snapshot):raise ValueError('支出換算快照與原始金額不符')
    scheduled=sum(x['activation_real_m'] for x in expected['resolved'] if x['year']==snapshot['year'])
    extra=snapshot['ad_hoc_twd']/1e6*plan['activation_cpi']/row['cpi_decision']
    if abs(scheduled+extra-row['approval']['opening']['planned_extra_m'])>1e-8:raise ValueError('年度排程與核准必要支出不一致')
