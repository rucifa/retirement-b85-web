/* Official public CPI viewer. Read-only: never changes B+85 policy inputs or IndexedDB. */
(function(){
'use strict';
const box=document.getElementById('official-cpi-panel');
const decision=document.getElementById('decision_date');
if(!box||!decision)return;
let snapshot=null,loadError='';
const safe=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const validDate=s=>typeof s==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(s)&&!Number.isNaN(Date.parse(s+'T00:00:00Z'))&&new Date(s+'T00:00:00Z').toISOString().slice(0,10)===s;
const days=(later,earlier)=>Math.floor((Date.parse(later+'T00:00:00Z')-Date.parse(earlier+'T00:00:00Z'))/86400000);
const sha=s=>typeof s==='string'&&/^[0-9a-f]{64}$/.test(s);
const statusSet=new Set(['CROSS_VERIFIED','BULLETIN_ONLY_PENDING_PRIMARY','HISTORICAL_VINTAGE_DIFFERENCE']);
const knownHost=u=>{try{const x=new URL(u);return x.protocol==='https:'&&(x.hostname==='www.stat.gov.tw'||x.hostname==='ws.dgbas.gov.tw')}catch{return false}};
function validate(d){
 if(!d||d.schema_version!==1||d.index_base!=='2021=100'||d.source_authority!=='行政院主計總處（DGBAS）'||d.source_status!=='RESEARCH_STAGED_NOT_ACTIVE')throw Error('CPI 快照版本或基期不符合');
 if(!validDate(d.source_checked_at_utc?.slice(0,10))||!sha(d.primary_source_sha256)||!knownHost(d.source_list_url))throw Error('快照來源、時間或雜湊無效');
 if(!Array.isArray(d.records)||d.records.length===0||d.records.length>500)throw Error('CPI 月度紀錄不完整');
 let previous='';
 for(const r of d.records){
  if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(r.month)||r.month<=previous)throw Error('CPI 月份沒有依序排列或重複');previous=r.month;
  if(!Number.isFinite(r.index)||r.index<=10||r.index>=1000||!Number.isFinite(r.official_yoy_pct)||Math.abs(r.official_yoy_pct)>=100)throw Error('CPI 指數或公告年增率有誤');
  if(!validDate(r.publication_date)||r.publication_date<r.month+'-01'||r.publication_date>d.source_checked_at_utc.slice(0,10))throw Error('官方公布日期不合理');
  if(!statusSet.has(r.verification)||!knownHost(r.official_source_url)||!sha(r.bulletin_xlsx_sha256))throw Error('CPI 查證狀態或來源不可信');
  if(r.verification==='CROSS_VERIFIED'&&(!Number.isFinite(r.primary_index)||Math.abs(r.primary_index-r.index)>0.00001))throw Error('雙來源值不一致卻標為已查證');
  if(r.verification==='HISTORICAL_VINTAGE_DIFFERENCE'&&(!Number.isFinite(r.primary_index)||Math.abs(r.primary_index-r.index)<0.00001))throw Error('不同版本的 CPI 資料未分辨');
 }
 const cross=d.records.filter(x=>x.verification==='CROSS_VERIFIED');
 if(cross.at(-1)?.month!==d.latest_cross_verified_month)throw Error('最近已查證月份與資料不符');
 if(d.annual_2026_index!==null||d.annual_2026_release_date!==null)throw Error('本版快照沒有 2026 全年基準的核對資料');
 return d;
}
function paint(){
 if(loadError){box.innerHTML='<strong class="cpi-state-title">官方 CPI 暫時無法讀取</strong><p> '+safe(loadError)+'。保留原手動輸入，所有示範數字均非官方自動查證。</p>';box.dataset.status='error';return}
 if(!snapshot){box.innerHTML='<strong class="cpi-state-title">正在讀取官方 CPI 快照…</strong>';box.dataset.status='loading';return}
 const d=decision.value;
 if(!validDate(d)){box.textContent='請先選擇有效的年初決策日期';box.dataset.status='invalid-date';return}
 const sameYearRecords=snapshot.records.filter(r=>r.month.slice(0,4)===d.slice(0,4));
 const releaseEligible=snapshot.records.filter(r=>r.publication_date<=d&&r.month<=d.slice(0,7));
 const cross=releaseEligible.filter(r=>r.verification==='CROSS_VERIFIED').at(-1);
 const pending=releaseEligible.filter(r=>r.verification==='BULLETIN_ONLY_PENDING_PRIMARY').at(-1);
 const reportYear=Number(snapshot.records.at(-1).month.slice(0,4)),year=Number(d.slice(0,4));
 const unavailable=year>reportYear||(!sameYearRecords.length&&year!==reportYear);
 const lastReleaseAge=cross?days(d,cross.publication_date):Infinity;
 const fresh=!!cross&&lastReleaseAge<=120&&lastReleaseAge>=0;
 const now=new Date().toISOString().slice(0,10);
 const snapshotAge=days(now,snapshot.source_checked_at_utc.slice(0,10));
 const staleSnapshot=snapshotAge>75;
 let yoy='尚無當年官方資料',heading='尚無當年官方資料',extra='';
 if(unavailable){
  extra=safe(year)+' 年尚未有可供該年度使用的已查證 CPI；網站不會把 '+safe(reportYear)+' 年的數字當成 '+safe(year)+' 年官方通膨。';
 }else if(fresh){
  yoy=(cross.official_yoy_pct>0?'+':'')+cross.official_yoy_pct.toFixed(2)+'%';
  heading='已查證月度 CPI（非全年指數）';
  extra='統計 '+safe(cross.month)+'，公布 '+safe(cross.publication_date)+'；官方公告同月年增率，該月指數經雙來源核對。';
 }else if(cross){
  heading='已查證歷史月度資料／目前過期';
  extra='最新合格的舊月份為 '+safe(cross.month)+'，但對本決策日已超過 120 天；不能視為最新決策依據。';
 }else{
  extra='在 '+safe(d)+' 年初決策日期以前，沒有已雙來源核對且完成公布的可用月份。';
 }
 const pendingHtml=!unavailable&&pending?
  '<p class="cpi-pending">待雙來源確認：'+safe(pending.month)+' 官方新聞稿公布年增率 '+safe(pending.official_yoy_pct.toFixed(2))+
  '%（'+safe(pending.publication_date)+' 公布）。主 Excel 尚未核對，不納入「已查證」數值。 <a href="'+safe(pending.official_source_url)+'" target="_blank" rel="noopener noreferrer">查看公告</a></p>':'';
 const details=snapshot.records.map(r=>'<li>'+safe(r.month)+'：'+safe(r.verification)+
  '；CPI '+safe(r.index.toFixed(2))+(r.verification==='HISTORICAL_VINTAGE_DIFFERENCE'?'／主資料修訂值 '+safe(r.primary_index.toFixed(2)):'')+
  '；發布 '+safe(r.publication_date)+'</li>').join('');
 box.dataset.status=fresh&&!staleSnapshot?'verified':(unavailable?'no-year-data':staleSnapshot?'stale':'pending');
 box.innerHTML='<div class="cpi-heading"><strong class="cpi-state-title">主計總處 CPI 公開快照</strong><span class="cpi-status">'+safe(heading)+'</span></div>'+
  '<div class="cpi-public-grid"><div><small>最近官方可用通膨率（該月份年增率）</small><strong>'+safe(yoy)+'</strong></div>'+
  '<div><small>相對 2026 年全年購買力基準累積物價變化</small><strong>尚無全年官方基準</strong></div>'+
  '<div><small>當年通膨調整後正常生活費</small><strong>尚無當年官方資料</strong></div></div>'+
  '<p class="cpi-caption">'+extra+'</p>'+pendingHtml+
  (staleSnapshot?'<p class="cpi-warning">此公開快照已逾 75 天未同步；可能不是最新公布資料，請查原始官方公告。</p>':'')+
  '<p class="cpi-caption">2026 年全年 CPI 年平均尚未正式完成公布，不能以 7 月指數或演練預設值取代；正常生活費 2026 實質基準為 NT$650,000，與 B＋85 實際核准額不同。本區僅讀取官方來源快照，不自動修改手動欄位或既有年度紀錄。</p>'+
  '<details class="cpi-source-detail"><summary>進階資料：原始 CPI、來源與核對紀錄</summary>'+
  '<p>統一基期：'+safe(snapshot.index_base)+'。來源最後核對 '+safe(snapshot.source_checked_at_utc.slice(0,10))+
  '（UTC）。來源狀態：'+safe(snapshot.source_status)+'。<a href="'+safe(snapshot.source_list_url)+'" target="_blank" rel="noopener noreferrer">主計總處物價新聞稿</a></p>'+
  '<ul>'+details+'</ul><p>來源原始檔 SHA256：<code>'+safe(snapshot.primary_source_sha256)+'</code></p></details>';
}
async function load(){
 try{
  const r=await fetch('./data/cpi_verified.json',{cache:'no-store'});
  if(!r.ok)throw Error('HTTP '+r.status);
  snapshot=validate(await r.json());loadError='';
 }catch(e){snapshot=null;loadError=e.message||'無法驗證快照'}
 paint();
}
decision.addEventListener('input',paint);
decision.addEventListener('change',paint);
load();
})();
