from __future__ import annotations
import argparse, csv, gzip, hashlib, io, json, os, ssl, sys
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

URL='https://ws.dgbas.gov.tw/001/Upload/463/relfile/10315/2677/cpispl.xls'
OLDSHA='b162edf6946f1e12d21090d56917f66edd59cb45a4cb197b9b4fe1a7305e511f'
BEGIN='1959-01'; PROTECTED_LAST='2026-07'; MIN_COUNT=811
MAX_BYTES=2_000_000

class DataError(ValueError):pass

def sha(b):return hashlib.sha256(b).hexdigest()

def next_month(s):
    y,m=map(int,s.split('-'))
    return f'{y+(m==12):04d}-{m%12+1:02d}'

# Root, cross-certified root, and intermediate certificates are fetched only from
# TWCA's HTTPS-verified official host and SHA256 pinned. 2026-10-11 GitHub Actions
# verified that ws.dgbas.gov.tw serves an unrelated ePKI chain alongside its
# TWCA-signed leaf. These supplemental CA certificates repair path construction;
# TLS hostname verification, signature checks, expiry checks and system trust stay on.
TWCA_CERT_CHAIN = (
    ('root', 'https://sslserver.twca.com.tw/cacert/global_root_2012.crt',
     '59769007f7685d0fcd50872f9f95d5755a5b2b457d81f3692b610a98672f0e1b'),
    ('cyber_cross', 'https://sslserver.twca.com.tw/cacert/GlobalCrossCyber_2022.crt',
     'c619f4e6f7b1baa7a6c6f244092a3f82e46a6d67bee26337fbaf02546f33133f'),
    ('ssl_intermediate', 'https://sslserver.twca.com.tw/cacert/Cyber_SSL_2023.crt',
     '01af2324d098098f5e0cdf6faabada430b21cce777f47eacb26248b2fda3e531'),
)

def twca_verified_context(opener=urlopen):
    """Build a verified TLS context using independently authenticated TWCA CA files."""
    initial_context = ssl.create_default_context()
    pems = []
    for label, url, expected_digest in TWCA_CERT_CHAIN:
        target = urlsplit(url)
        if target.scheme != 'https' or target.hostname != 'sslserver.twca.com.tw':
            raise DataError('Unapproved official TWCA CA endpoint')
        req = Request(url, headers={'User-Agent':'RetirementCPIResearch/1.0 (verified TLS)'})
        try:
            with opener(req, context=initial_context, timeout=20) as response:
                final = urlsplit(response.geturl())
                if final.scheme != 'https' or final.hostname != 'sslserver.twca.com.tw':
                    raise DataError('Unsafe TWCA CA redirect')
                binary = response.read(20_001)
            if len(binary) > 20_000 or sha(binary) != expected_digest:
                raise DataError('Official TWCA CA file changed; review required: ' + label)
            pems.append(ssl.DER_cert_to_PEM_cert(binary))
        except (OSError, ValueError) as e:
            raise DataError('Cannot securely obtain TWCA CA certificate ' + label + ': ' + str(e)) from e
    context = ssl.create_default_context()
    try:
        context.load_verify_locations(cadata='\n'.join(pems))
    except (ssl.SSLError, ValueError) as e:
        raise DataError('Cannot establish signed TWCA trust path: ' + str(e)) from e
    return context

def strict_https_xls(url=URL, opener=urlopen, context_provider=twca_verified_context):
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname!='ws.dgbas.gov.tw':raise DataError('Unexpected official CPI source URL')
    try:
        trusted = context_provider(opener)
        req=Request(url,headers={'User-Agent':'RetirementCPIResearch/1.0 (verified TLS; Github Actions)'})
        with opener(req,context=trusted,timeout=30) as r:
            final=urlsplit(r.geturl())
            if final.scheme!='https' or final.hostname!='ws.dgbas.gov.tw':raise DataError('Unsafe final CPI redirect')
            size=r.headers.get('Content-Length')
            if size and int(size)>MAX_BYTES:raise DataError('Source larger than maximum')
            b=r.read(MAX_BYTES+1)
    except (OSError,ValueError) as e:
        raise DataError('HTTPS official CPI source verification/download failed: '+str(e)) from e
    if len(b)>MAX_BYTES or len(b)<40000 or not b.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
        raise DataError('Invalid OLE XLS payload or size')
    return b

def parse_official_xls(raw, as_of=None):
    as_of=as_of or datetime.now(timezone.utc).date()
    if not raw.startswith(bytes.fromhex('d0cf11e0a1b11ae1')) or not 40000<len(raw)<MAX_BYTES:
        raise DataError('Invalid XLS signature or length')
    try:
        import xlrd
        sh=xlrd.open_workbook(file_contents=raw).sheet_by_name('CPI')
    except Exception as e:raise DataError('Cannot read official CPI sheet: '+str(e)) from e
    if sh.cell_value(2,0)!='民國年' or any(not str(sh.cell_value(2,m)).startswith(f'{m}月') for m in range(1,13)):
        raise DataError('CPI sheet schema changed')
    results={}
    for row in range(3,sh.nrows):
        roc=sh.cell_value(row,0)
        if not isinstance(roc,(int,float)):continue
        year=int(roc)+1911
        if not 1959<=year<=as_of.year:raise DataError('Unexpected calendar year')
        for mo in range(1,13):
            rawval=sh.cell_value(row,mo)
            if rawval in ('',None):continue
            if isinstance(rawval,bool):raise DataError('Invalid CPI value')
            try:v=Decimal(str(rawval))
            except (InvalidOperation,ValueError):raise DataError('Non-numeric CPI value')
            if not v.is_finite() or not Decimal('1')<v<Decimal('300'):raise DataError('CPI value outside valid range')
            key=f'{year:04d}-{mo:02d}'
            if key>as_of.strftime('%Y-%m'):raise DataError('Future CPI observation')
            if key in results:raise DataError('Duplicate CPI month')
            results[key]=format(v,'.2f')
    if not results or min(results)!=BEGIN or len(results)<MIN_COUNT or max(results)<PROTECTED_LAST:
        raise DataError('Official CPI history incomplete / unexpectedly truncated')
    ey,em=map(int,max(results).split('-'))
    month_end=date(ey+(em==12),em%12+1,1)-timedelta(days=1)
    if (as_of-month_end).days>75:raise DataError(f'Official CPI stale: last observation {max(results)}')
    expect=BEGIN
    for key in sorted(results):
        if key!=expect:raise DataError(f'Missing CPI month: {expect}')
        expect=next_month(expect)
    return results


# Read-only bulletin validation routines, copied from independently verified public-source parser.
from html.parser import HTMLParser
from urllib.parse import urljoin, parse_qs
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile
import re
LIST_URL='https://www.stat.gov.tw/News.aspx?n=2668'
MAX_HTML=2_000_000
MAX_XLSX=1_000_000
MAX_BULLETINS=4
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
class DualSourceError(ValueError): pass

def digest(b): return hashlib.sha256(b).hexdigest()

def period(roc:int,month:int)->str:
    y=int(roc)+1911;m=int(month)
    if not 1959<=y<=2100 or not 1<=m<=12:raise DualSourceError('Invalid ROC period')
    return f'{y:04}-{m:02}'

class Anchors(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.links=[];self.active=None;self.text=[]
    def handle_starttag(self,t,attrs):
        if t=='a':self.active={'attrs':dict(attrs),'text':''}
    def handle_endtag(self,t):
        if t=='a' and self.active is not None:self.links.append(self.active);self.active=None
    def handle_data(self,txt):
        self.text.append(txt)
        if self.active is not None:self.active['text']+=txt

def decode_html(b):
    if len(b)>MAX_HTML or not b:raise DualSourceError('HTML source too large or empty')
    try:return b.decode('utf-8-sig')
    except UnicodeDecodeError as e:raise DualSourceError('HTML encoding unsupported') from e

def bulletin_list(blob:bytes,now:date)->list[dict]:
    h=Anchors();h.feed(decode_html(blob));seen={}
    for a in h.links:
        title=re.search(r'(\d{3})年\s*(\d{1,2})月消費者物價指數\s*\(CPI\)',a['text'])
        if not title:continue
        month=period(int(title[1]),int(title[2]))
        if month>now.strftime('%Y-%m'):continue
        raw=urljoin(LIST_URL,a['attrs'].get('href',''))
        u=urlsplit(raw);params=parse_qs(u.query)
        if u.scheme!='https' or u.hostname!='www.stat.gov.tw' or u.path!='/News_Content.aspx' or params.get('n')!=['2668'] or not re.fullmatch(r'\d{4,8}',params.get('s',[''])[0]):continue
        if month in seen and seen[month]['url']!=raw:raise DualSourceError('Duplicate official bulletin for '+month)
        seen[month]={'month':month,'url':raw,'release_id':params['s'][0]}
    if not seen:raise DualSourceError('No official CPI bulletin on list page')
    return [seen[k] for k in sorted(seen,reverse=True)[:MAX_BULLETINS]]

def bulletin_article(blob:bytes,source:dict,now:date)->dict:
    h=Anchors();h.feed(decode_html(blob));words=''.join(h.text)
    match=re.search(r'張貼日期[:：]\s*(\d{3})-(\d{2})-(\d{2})',words)
    if not match:raise DualSourceError('Missing bulletin posting date')
    published=date(int(match[1])+1911,int(match[2]),int(match[3]))
    if published>now:raise DualSourceError('Bulletin has future publication date')
    roc,mm=map(int,[int(source['month'][:4])-1911,source['month'][5:]])
    phrase=f'{mm}月消費者物價總指數(CPI)'
    if phrase not in words:raise DualSourceError('Bulletin body refers to unexpected index')
    segment=words[words.index(phrase):words.index(phrase)+300]
    mom=re.search(r'較上(?:[（(]\d+[)）])?月\s*([漲跌])\s*(\d+(?:\.\d+)?)\s*[％%]',segment)
    yoy=re.search(r'較上(?:[（(]\d+[)）])?年同月\s*([漲跌])\s*(\d+(?:\.\d+)?)\s*[％%]',segment)
    if not mom or not yoy:raise DualSourceError('Cannot identify unadjusted CPI MoM/YoY in bulletin')
    paths=[]
    expected=f't{roc:03}{mm:02}_1.xlsx'
    for a in h.links:
        u=urlsplit(urljoin(source['url'],a['attrs'].get('href','')))
        if u.scheme!='https' or u.hostname!='ws.dgbas.gov.tw':continue
        if re.fullmatch(r'/001/Upload/463/relfile/10980/\d{4,9}/'+expected,u.path,re.I):paths.append(u.geturl())
    if len(set(paths))!=1:raise DualSourceError('Expected unique official Table-1 XLSX link')
    result=dict(source,release_date=published.isoformat(),table1_url=paths[0],
                bulletin_mom=str(Decimal(mom[2])*(-1 if mom[1]=='跌' else 1)),
                bulletin_yoy=str(Decimal(yoy[2])*(-1 if yoy[1]=='跌' else 1)))
    return result

def xlsx_values(data:bytes)->dict:
    if not 2000<len(data)<MAX_XLSX or not data.startswith(b'PK'):
        raise DualSourceError('Not expected Table 1 XLSX file')
    try:
        with ZipFile(BytesIO(data)) as z:
            files=z.namelist()
            if len(files)>120 or sum(z.getinfo(n).file_size for n in files)>4_000_000:raise DualSourceError('Suspicious XLSX ZIP expansion')
            if any(n.startswith('/') or '..' in n.split('/') for n in files):raise DualSourceError('Unsafe XLSX archive paths')
            if 'xl/worksheets/sheet1.xml' not in files:raise DualSourceError('Missing worksheet')
            strings=[]
            if 'xl/sharedStrings.xml' in files:
                root=ET.fromstring(z.read('xl/sharedStrings.xml'))
                for item in root.findall(NS+'si'):
                    strings.append(''.join((t.text or '') for t in item.iter(NS+'t')))
            ws=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            wanted={'A1','A2','C2','B6','C6','D6','E6','G6'}
            values={}
            for c in ws.iter(NS+'c'):
                addr=c.attrib.get('r')
                if addr not in wanted:continue
                v=c.find(NS+'v')
                inline=c.find(NS+'is')
                if c.attrib.get('t')=='s' and v is not None:
                    item=strings[int(v.text)]
                elif c.attrib.get('t')=='inlineStr' and inline is not None:
                    item=''.join((q.text or '') for q in inline.iter(NS+'t'))
                else:item=v.text if v is not None else None
                values[addr]=item
            return values
    except (BadZipFile, ET.ParseError, IndexError,KeyError,ValueError) as e:raise DualSourceError('Malformed Excel Table 1: '+str(e)) from e

def parse_table1(blob:bytes,meta:dict)->dict:
    v=xlsx_values(blob)
    if '消費者物價指數變動分析表' not in (v.get('A1') or ''):
        raise DualSourceError('Unexpected CPI Table-1 title')
    if not re.search(r'民國110年\s*=\s*100',v.get('A2') or ''):
        raise DualSourceError('Unexpected Table-1 CPI index base')
    p=re.search(r'民國(\d{3})年\s*(\d{1,2})月',v.get('C2') or '')
    if not p or period(int(p[1]),int(p[2]))!=meta['month']:
        raise DualSourceError('Table-1 period does not match published bulletin')
    if (v.get('B6') or '').strip()!='總指數':raise DualSourceError('Table-1 CPI total-index row missing')
    if Decimal(str(v.get('C6','0')))!=1000:raise DualSourceError('Table-1 CPI weight not total')
    idx=Decimal(str(v['D6']));mom=Decimal(str(v['E6']));yoy=Decimal(str(v['G6']))
    if not Decimal('10')<idx<Decimal('300'):raise DualSourceError('Table-1 CPI index out of expected range')
    if abs(mom-Decimal(meta['bulletin_mom']))>Decimal('0.005') or abs(yoy-Decimal(meta['bulletin_yoy']))>Decimal('0.005'):
        raise DualSourceError('Published bulletin rates differ from official Table 1')
    return {**meta,'index_2021_100':str(idx),'table1_mom':str(mom),'table1_yoy':str(yoy)}

def https_bytes(url:str,context,allowed_host:str,max_size:int):
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname!=allowed_host:raise DualSourceError('Unapproved official source URL')
    req=Request(url,headers={'User-Agent':'RetirementCPIResearch/1.0 (official cross-check)'})
    try:
        with urlopen(req,context=context,timeout=24) as r:
            final=urlsplit(r.geturl())
            if final.scheme!='https' or final.hostname!=allowed_host:raise DualSourceError('Unapproved official redirect')
            if int(r.headers.get('Content-Length') or '0')>max_size:raise DualSourceError('Official source exceeds byte limit')
            blob=r.read(max_size+1)
    except (OSError,ValueError) as e:raise DualSourceError('Official data HTTPS failed: '+str(e)) from e
    if not blob or len(blob)>max_size:raise DualSourceError('Official data empty or exceeds max size')
    return blob

def compare(primary_rows:dict, bulletins:list[dict],today:date, protected_last:str="2026-07")->dict:
    verified=[]; pending=[]; discrepant=[]; vintages=[]; checked=[]
    for rec in bulletins:
        month=rec['month'];ix=Decimal(rec['index_2021_100'])
        if month in primary_rows:
            main=Decimal(str(primary_rows[month]));rec['primary_index_2021_100']=str(main)
            if main==ix:
                rec['result']='CROSS_VERIFIED';verified.append(month)
            elif month<=protected_last:
                rec['result']='HISTORICAL_VINTAGE_DIFFERENCE';vintages.append(month)
            else:
                rec['result']='CONFLICT_REQUIRES_REVIEW';discrepant.append(month)
        else:
            rec['result']='BULLETIN_ONLY_PENDING_PRIMARY';pending.append(month)
        checked.append(rec)
    # Verify bulletin-only month-to-month arithmetic, allowing 2 decimal point index rounding.
    items={r['month']:r for r in checked}
    for key,r in items.items():
        year,mo=map(int,key.split('-'))
        prior=f'{year-(mo==1):04}-{(mo+10)%12+1:02}'
        if prior in items:
            a=Decimal(items[prior]['index_2021_100']);b=Decimal(r['index_2021_100'])
            expected=(b/a-1)*100
            if abs(expected-Decimal(r['table1_mom']))>Decimal('0.035'):
                r['result']='CONFLICT_REQUIRES_REVIEW'
                if key not in discrepant:discrepant.append(key)
                if key in pending:pending.remove(key)
                if key in verified:verified.remove(key)
    primary_latest=max(primary_rows)
    last_year,last_mo=map(int,primary_latest.split('-'))
    last_end=date(last_year+(last_mo==12),last_mo%12+1,1)-timedelta(days=1)
    stale_days=(today-last_end).days
    return {'status':'CONFLICT_REQUIRES_REVIEW' if discrepant else 'BULLETIN_AHEAD_PENDING_PRIMARY' if pending else 'CROSS_VERIFIED_WITH_VINTAGE_DIFFERENCES' if vintages else 'CROSS_VERIFIED',
            'primary_latest':primary_latest,'primary_stale_days':stale_days,
            'primary_stale_warning':stale_days>75,'secondary_latest':max(items),
            'verified_months':sorted(verified),'pending_months':sorted(pending),
            'conflicting_months':sorted(discrepant),'historical_vintage_differences':sorted(vintages),'records':checked}

def fresh_primary_months_not_cross_verified(protected:dict, primary_rows:dict, assessment:dict)->list[str]:
    return sorted((set(primary_rows)-set(protected))-set(assessment['verified_months']))

