#!/usr/bin/env python3
"""Public-only official Taiwan CPI collector; no private repo, credential or personal data.

The protected 1959-01..2026-07 DGBAS history is represented by a fixed SHA256
of 811 public month/index pairs, never by copied research snapshots. Dual
sources must agree before newer observations are marked CROSS_VERIFIED.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import ssl
import sys
from urllib.parse import urlsplit

import cpi_sources as s

BASELINE_END = '2026-07'
BASELINE_ROWS = 811
BASELINE_SHA256 = '8192337073718435c5bba7ba124ff69b2fa667d58422222466cebc4b7e7923c3'
SOURCE_LIST = 'https://www.stat.gov.tw/News.aspx?n=2668'
ALLOWED = {'CROSS_VERIFIED','BULLETIN_ONLY_PENDING_PRIMARY','HISTORICAL_VINTAGE_DIFFERENCE'}
OFFICIAL_BASE = '2021=100'


class PublishError(ValueError):
    pass


def need(value, message):
    if not value:
        raise PublishError(message)


def parse_day(value):
    try:
        return date.fromisoformat(value)
    except (ValueError,TypeError) as exc:
        raise PublishError('Invalid official date') from exc


def trusted_bulletin(value):
    if not isinstance(value,str):return False
    q=urlsplit(value)
    return q.scheme=='https' and q.netloc=='www.stat.gov.tw' and q.path=='/News_Content.aspx' and not q.fragment and re.fullmatch(r'n=2668&s=\d{4,9}',q.query) is not None


def protected_hash(rows):
    # Exact normalized public 811-month data, beginning at 1959-01.
    base={k:v for k,v in rows.items() if k<=BASELINE_END}
    need(len(base)==BASELINE_ROWS and min(base)=='1959-01' and max(base)==BASELINE_END,
         'OFFICIAL_HISTORICAL_811_MONTH_BASELINE_INCOMPLETE')
    normalized=''.join(f'{k},{Decimal(str(base[k])):.2f}\n' for k in sorted(base))
    return hashlib.sha256(normalized.encode('ascii')).hexdigest()


def check_primary_history(rows):
    need(protected_hash(rows)==BASELINE_SHA256,
         'PRIMARY_HISTORICAL_REVISION_REQUIRES_REVIEW')
    return rows


def parse_primary_with_stale_support(blob, now):
    try:
        return s.parse_official_xls(blob,as_of=now)
    except s.DataError as exc:
        if 'Official CPI stale' not in str(exc):
            raise
        # This bypasses ONLY a freshness rejection for comparison purposes.
        # Certificate verification, OLE schema and protected history remain strict.
        import xlrd
        sheet=xlrd.open_workbook(file_contents=blob).sheet_by_name('CPI')
        last=None
        for row in range(3,sheet.nrows):
            y=sheet.cell_value(row,0)
            if not isinstance(y,(int,float)):continue
            for m in range(1,13):
                val=sheet.cell_value(row,m)
                if isinstance(val,(int,float)) and not isinstance(val,bool) and val>0:
                    last=f'{int(y)+1911:04}-{m:02}'
        need(last is not None,'OFFICIAL_XLS_NO_MONTH')
        y,m=map(int,last.split('-'))
        reference=date(y+(m==12),m%12+1,1)+timedelta(days=40)
        return s.parse_official_xls(blob,as_of=reference)


def load_official(now):
    try:
        context=s.twca_verified_context()
    except (s.DataError,s.DualSourceError,OSError) as exc:
        raise PublishError('TLS_STAGE_TWCA_CA_CHAIN: '+str(exc)) from exc
    try:
        raw=s.strict_https_xls(context_provider=lambda _opener:context)
    except (s.DataError,s.DualSourceError,OSError) as exc:
        raise PublishError('TLS_STAGE_DGBAS_HISTORICAL_XLS: '+str(exc)) from exc
    primary=check_primary_history(parse_primary_with_stale_support(raw,now))
    try:
        listing=s.https_bytes(SOURCE_LIST,context,'www.stat.gov.tw',s.MAX_HTML)
    except (s.DataError,s.DualSourceError,OSError) as exc:
        raise PublishError('TLS_STAGE_STAT_GOV_BULLETIN_LIST: '+str(exc)) from exc
    discovered=s.bulletin_list(listing,now)
    reports=[]
    for item in discovered:
        try:
            article=s.https_bytes(item['url'],context,'www.stat.gov.tw',s.MAX_HTML)
        except (s.DataError,s.DualSourceError,OSError) as exc:
            raise PublishError('TLS_STAGE_STAT_GOV_ARTICLE_'+item['month']+': '+str(exc)) from exc
        meta=s.bulletin_article(article,item,now)
        try:
            excel=s.https_bytes(meta['table1_url'],context,'ws.dgbas.gov.tw',s.MAX_XLSX)
        except (s.DataError,s.DualSourceError,OSError) as exc:
            raise PublishError('TLS_STAGE_DGBAS_TABLE1_'+item['month']+': '+str(exc)) from exc
        row=s.parse_table1(excel,meta)
        row['xlsx_sha256']=s.digest(excel)
        row['html_sha256']=s.digest(article)
        reports.append(row)
    assessment=s.compare(primary,reports,now,protected_last=BASELINE_END)
    need(not assessment['conflicting_months'],
         'CPI_DUAL_SOURCE_CONFLICT_REQUIRES_MANUAL_REVIEW')
    return primary,assessment,s.digest(raw),s.digest(listing)


def valid_old(history, now):
    need(isinstance(history,dict) and history.get('schema_version')==1
         and history.get('source_authority')=='行政院主計總處（DGBAS）'
         and history.get('index_base')==OFFICIAL_BASE,
         'PUBLIC_PREVIOUS_SNAPSHOT_SCHEMA_INVALID')
    need(history.get('annual_2026_index') is None and history.get('annual_2026_release_date') is None,
         'ANNUAL_2026_BASELINE_CONTRACT_NOT_YET_APPROVED')
    records=history.get('records')
    need(isinstance(records,list) and 0<len(records)<=480,'BAD_PREVIOUS_CPI_HISTORY')
    old={}
    for r in records:
        need(r.get('verification') in ALLOWED and isinstance(r.get('month'),str)
             and re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',r['month'])
             and trusted_bulletin(r.get('official_source_url'))
             and re.fullmatch(r'[a-f0-9]{64}',r.get('bulletin_xlsx_sha256','')),
             'INVALID_PREVIOUS_CPI_RECORD')
        need(parse_day(r['publication_date'])<=now and 10<float(r['index'])<1000
             and abs(float(r['official_yoy_pct']))<100,'BAD_PREVIOUS_CPI_VALUE')
        need(r['month'] not in old,'DUPLICATE_PREVIOUS_CPI_MONTH')
        if r['verification']=='CROSS_VERIFIED':
            need(float(r['index'])==float(r.get('primary_index',-1)),
                 'BAD_OLD_VERIFIED_PRIMARY')
        old[r['month']]=r
    need(list(old)==sorted(old),'UNORDERED_OLD_CPI')
    verified=[r['month'] for r in records if r['verification']=='CROSS_VERIFIED']
    need(bool(verified) and verified[-1]==history.get('latest_cross_verified_month'),
         'INCONSISTENT_OLD_VERIFIED_MONTH')
    return old


def public_record(row,now):
    need(row.get('result') in ALLOWED,'UNSAFE_CPI_VERIFICATION_STATUS')
    need(trusted_bulletin(row.get('url')),'UNTRUSTED_DGBAS_SOURCE_URL')
    need(re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',row['month']),
         'INVALID_CPI_PERIOD')
    day=parse_day(row['release_date'])
    need(date.fromisoformat(row['month']+'-01')<=day<=now,'OFFICIAL_CPI_FUTURE_RELEASE')
    ix=float(Decimal(row['index_2021_100']))
    yoy=float(Decimal(row['bulletin_yoy']))
    need(10<ix<1000 and abs(yoy)<100 and abs(yoy-float(row['table1_yoy']))<=0.005,
         'UNTRUSTED_OFFICIAL_CPI_NUMERIC')
    need(re.fullmatch(r'[a-f0-9]{64}',row['xlsx_sha256']) is not None,
         'CPI_XLSX_SHA256_REQUIRED')
    output={
      'month':row['month'],'index':ix,'official_yoy_pct':yoy,
      'publication_date':day.isoformat(),'verification':row['result'],
      'official_source_url':row['url'],
      'bulletin_xlsx_sha256':row['xlsx_sha256'],
    }
    primary=row.get('primary_index_2021_100')
    if row['result']=='BULLETIN_ONLY_PENDING_PRIMARY':
        need(primary is None,'PENDING_CPI_CANNOT_HAVE_PRIMARY')
    else:
        need(primary is not None,'VERIFIED_CPI_REQUIRES_PRIMARY')
        p=float(Decimal(primary))
        need((p==ix)==(row['result']=='CROSS_VERIFIED'),
             'INVALID_PRIMARY_CROSS_VERIFICATION')
        output['primary_index']=p
    return output


def build_snapshot(primary,assessment,raw_sha,list_sha,previous,now):
    need(assessment.get('status') in
         ('BULLETIN_AHEAD_PENDING_PRIMARY','CROSS_VERIFIED','CROSS_VERIFIED_WITH_VINTAGE_DIFFERENCES'),
         'CPI_RESEARCH_STATUS_NOT_SAFE')
    need(not assessment.get('conflicting_months'),'CPI_SOURCE_CONFLICT')
    history=valid_old(previous,now.date())
    new_records=[public_record(row,now.date()) for row in assessment['records']]
    need(len({r['month'] for r in new_records})==len(new_records),'DUPLICATE_NEW_CPI_MONTH')
    new_verified={r['month'] for r in new_records if r['verification']=='CROSS_VERIFIED'}
    old_verified={k for k,r in history.items() if r['verification']=='CROSS_VERIFIED'}
    unchecked=[k for k in primary if k>BASELINE_END and k not in new_verified and k not in old_verified]
    need(not unchecked,'NEW_PRIMARY_MONTH_UNVERIFIED_REQUIRES_REVIEW: '+','.join(unchecked))
    for row in new_records:
        old=history.get(row['month'])
        if old and old['verification']=='CROSS_VERIFIED':
            need(row['verification']=='CROSS_VERIFIED' and row['index']==old['index'],
                 'HISTORICALLY_VERIFIED_VALUE_CHANGED_REQUIRES_REVIEW')
        history[row['month']]=row
    rows=[history[k] for k in sorted(history)]
    need(len(rows)<=480,'TOO_MANY_CPI_RECORDS_FOR_BROWSER_SCHEMA')
    verified=[r['month'] for r in rows if r['verification']=='CROSS_VERIFIED']
    need(bool(verified),'NO_CROSS_VERIFIED_CPI_AVAILABLE')
    need(re.fullmatch(r'[0-9a-f]{64}',raw_sha) and re.fullmatch(r'[0-9a-f]{64}',list_sha),
         'OFFICIAL_SOURCE_HASH_MISSING')
    return {
      'schema_version':1,
      'source_authority':'行政院主計總處（DGBAS）',
      'index_base':OFFICIAL_BASE,
      'source_status':'RESEARCH_STAGED_NOT_ACTIVE',
      'source_checked_at_utc':now.isoformat(),
      'primary_source_sha256':raw_sha,
      'primary_status':'RESEARCH_STAGED_NOT_ACTIVE',
      'primary_latest_month':max(primary),
      'bulletin_latest_month':assessment['secondary_latest'],
      'latest_cross_verified_month':verified[-1],
      'annual_2026_index':None,
      'annual_2026_release_date':None,
      'source_list_url':SOURCE_LIST,
      'records':rows,
    }


def publish(repo,now=None):
    now=now or datetime.now(timezone.utc)
    need((repo/'data/cpi_verified.json').is_file(),'PUBLIC_CPI_JSON_MISSING')
    history=json.loads((repo/'data/cpi_verified.json').read_text('utf-8'))
    manifest_path=repo/'SOURCE_SHA256.json'
    manifest=json.loads(manifest_path.read_text('utf-8'))
    need(manifest.get('policy/retirement_model_v340.py')==
         '54dd2718a098c7f8182fcc44db980c523c2859fdaa276c50e81e8f8ea8712f10',
         'B85_POLICY_HASH_CHANGED')
    for name,expected in manifest.items():
        need(hashlib.sha256((repo/name).read_bytes()).hexdigest()==expected,
             'PUBLIC_SOURCE_MANIFEST_HASH_MISMATCH: '+name)
    primary,assessment,raw_sha,list_sha=load_official(now.date())
    snapshot=build_snapshot(primary,assessment,raw_sha,list_sha,history,now)
    # Only official allowlisted fields leave this collector. No other file is touched.
    raw=(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    target=repo/'data/cpi_verified.json'
    target.write_bytes(raw)
    manifest['data/cpi_verified.json']=hashlib.sha256(raw).hexdigest()
    manifest_path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('CPI_PUBLIC_DUAL_SOURCE_EXPORT_PASS')
    print('latest_primary:',snapshot['primary_latest_month'])
    print('latest_bulletin:',snapshot['bulletin_latest_month'])
    print('latest_verified:',snapshot['latest_cross_verified_month'])
    print('pending:',','.join(r['month'] for r in snapshot['records'] if r['verification']=='BULLETIN_ONLY_PENDING_PRIMARY'))
    print('source_sha256:',manifest['data/cpi_verified.json'])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,default=Path('.'))
    opts=parser.parse_args()
    try:
        publish(opts.repo)
    except (PublishError,s.DataError,s.DualSourceError,OSError,ValueError,KeyError,
            UnicodeError,ImportError,TypeError) as exc:
        print('CPI_PUBLIC_FAIL_CLOSED:',str(exc),file=sys.stderr)
        sys.exit(2)


if __name__=='__main__':
    main()
