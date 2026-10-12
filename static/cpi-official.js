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
 if(loadError){box.innerHTML='<strong class="cpi-state-title">官方 CPI 暫時無法讀取</strong><p>'+safe(loadError)+'。資料無法驗證，保留原手動輸入與演練欄位，不會提供虛構官方數字。</p>';box.dataset.status='error';return}
 if(!snapshot){box.innerHTML='<strong class="cpi-state-title">正在讀取官方 CPI 快照…</strong>';box.dataset.status='loading';return}
 const taiwan=window.B85_TAIWAN_TIME;
 if(!taiwan){box.textContent='台灣時間模組尚未載入；暫停官方資料時點判定。';box.dataset.status='error';return}
 const today=taiwan.today();
 const previousMonth=taiwan.prevMonth(today);
 const releaseEligible=snapshot.records.filter(r=>r.publication_date<=today&&r.month<=previousMonth);
 const cross=releaseEligible.filter(r=>r.verification==='CROSS_VERIFIED').at(-1);
 const pending=releaseEligible.filter(r=>r.verification==='BULLETIN_ONLY_PENDING_PRIMARY').at(-1);
 const lastMonth=releaseEligible.find(r=>r.month===previousMonth);
 const lastReleaseAge=cross?days(today,cross.publication_date):Infinity;
 const fresh=!!cross&&lastReleaseAge<=120&&lastReleaseAge>=0;
 const snapshotAge=days(today,snapshot.source_checked_at_utc.slice(0,10));
 const staleSnapshot=snapshotAge>75;
 const yoy=fresh?(cross.official_yoy_pct>0?'+':'')+cross.official_yoy_pct.toFixed(2)+'%':'尚無近期已查證資料';
 const heading=fresh?'已查證月度資料（非全年 CPI）':cross?'最近已查證月份已過期':'尚無雙來源已查證月份';
 const lastMonthText=lastMonth?
  (lastMonth.verification==='CROSS_VERIFIED'?'上個月（'+previousMonth+'）已完成雙來源核對。':
   lastMonth.verification==='BULLETIN_ONLY_PENDING_PRIMARY'?'上個月（'+previousMonth+'）已公布，但尚待主資料核對。':
   '上個月（'+previousMonth+'）出現不同資料版本，須進一步確認。'):
  '上個月（'+previousMonth+'）目前沒有可供使用的官方公告紀錄；不以其他月份冒充上個月。';
 const extra=cross?
  '最近可用的已查證月份：'+safe(cross.month)+'（公布 '+safe(cross.publication_date)+'）。'+safe(lastMonthText):
  '截至台灣 '+safe(today)+'，'+safe(lastMonthText)+'目前沒有可用的雙來源已查證月度資料。';
 const pendingHtml=pending?
  '<p class="cpi-pending">最新待核對月份：'+safe(pending.month)+'；公告年增率 '+safe(pending.official_yoy_pct.toFixed(2))+
  '%（'+safe(pending.publication_date)+' 公布）。此數字不能視為已完成雙來源查證。 <a href="'+safe(pending.official_source_url)+'" target="_blank" rel="noopener noreferrer">查看官方公告</a></p>':'';
 const details=releaseEligible.map(r=>'<li>'+safe(r.month)+'：'+safe(r.verification)+
  '；CPI '+safe(r.index.toFixed(2))+(r.verification==='HISTORICAL_VINTAGE_DIFFERENCE'?'／主資料修訂值 '+safe(r.primary_index.toFixed(2)):'')+
  '；發布 '+safe(r.publication_date)+'</li>').join('');
 box.dataset.status=staleSnapshot?'stale':fresh?'verified':'pending';
 box.innerHTML='<div class="cpi-heading"><strong class="cpi-state-title">主計總處 CPI 公開快照</strong><span class="cpi-status">'+safe(heading)+'</span></div>'+
  '<div class="cpi-public-grid"><div><small>最近已查證月份年增率</small><strong>'+safe(yoy)+'</strong></div>'+
  '<div><small>上個月官方資料狀態</small><strong>'+safe(lastMonth?lastMonth.verification==='CROSS_VERIFIED'?'已查證':lastMonth.verification==='BULLETIN_ONLY_PENDING_PRIMARY'?'待雙來源核對':'資料版本差異':'尚未取得公告')+'</strong></div></div>'+
  '<p class="cpi-caption">'+extra+'</p>'+pendingHtml+
  (staleSnapshot?'<p class="cpi-warning">此公開快照已逾 75 天未重新核對，請查主計總處最新公告。</p>':'')+
  '<p class="cpi-caption">查詢基準：台灣 '+safe(today)+'，統計月份最多截至 '+safe(previousMonth)+'。2026 全年 CPI 年平均尚無已確認基準，因此不提供官方累積物價變化或官方換算生活費。模擬年度的 CPI 輸入不會因本卡自動改寫。</p>'+
  '<details class="cpi-source-detail"><summary>進階資料：原始 CPI、來源與核對紀錄</summary>'+
  '<p>統一基期：'+safe(snapshot.index_base)+'。來源最後核對 '+safe(snapshot.source_checked_at_utc.slice(0,10))+
  '（UTC）。來源狀態：'+safe(snapshot.source_status)+'。<a href="'+safe(snapshot.source_list_url)+'" target="_blank" rel="noopener noreferrer">主計總處物價新聞稿</a></p>'+
  '<ul>'+details+'</ul><p>來源原始檔 SHA256：<code>'+safe(snapshot.primary_source_sha256)+'</code></p></details>';
}
function prefillInitialMonthlyCpi(){
 // Never overwrite submitted history or a user-adjusted CPI assumption.
 const manual=document.getElementById('decision_cpi');
 const release=document.getElementById('decision_cpi_release');
 const ref=document.getElementById('reference_cpi_field');
 if(!manual||!release||!decision||!snapshot||!window.B85_TAIWAN_TIME)return;
 if(manual.value||release.value||manual.dataset.userEdited==='true'||release.dataset.userEdited==='true')return;
 try{
  if(typeof state!=='undefined'&&state&&Array.isArray(state.years)&&state.years.length)return;
 }catch{return}
 const day=decision.value;
 if(!validDate(day))return;
 const now=window.B85_TAIWAN_TIME.today(),lastMonth=window.B85_TAIWAN_TIME.prevMonth(day);
 const checked=snapshot.records.filter(r=>
  r.verification==='CROSS_VERIFIED'&&r.month<=lastMonth&&r.publication_date<=day&&r.publication_date<=now
 ).at(-1);
 if(!checked||days(day,checked.publication_date)>120||days(day,checked.publication_date)<0)return;
 manual.value=checked.index.toFixed(2);
 release.value=checked.publication_date;
 manual.dataset.officialMonth=checked.month;
 const note=manual.closest('label')?.querySelector('small');
 if(note)note.textContent='已帶入 '+checked.month+' 的雙來源已查證月度 CPI（公布 '+checked.publication_date+'）。此數值不是 2026 全年 CPI；可改為手動假設。';
 manual.dispatchEvent(new Event('input',{bubbles:true}));
}
const manualCpi=document.getElementById('decision_cpi'),manualRelease=document.getElementById('decision_cpi_release');
if(manualCpi)manualCpi.addEventListener('input',e=>{if(e.isTrusted)manualCpi.dataset.userEdited='true';});
if(manualRelease)manualRelease.addEventListener('input',e=>{if(e.isTrusted)manualRelease.dataset.userEdited='true';});
async function load(){
 try{
  const r=await fetch('./data/cpi_verified.json',{cache:'no-store'});
  if(!r.ok)throw Error('HTTP '+r.status);
  snapshot=validate(await r.json());loadError='';prefillInitialMonthlyCpi();
 }catch(e){snapshot=null;loadError=e.message||'無法驗證快照'}
 paint();
}
load();
})();
