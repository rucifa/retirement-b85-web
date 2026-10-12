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
 const today=taiwan.today(),previousMonth=taiwan.prevMonth(today);
 // Every number below was checked against its official bulletin and attached Table-1 XLSX
 // by GitHub before publishing. The historical XLS may trail the publication.
 const eligible=snapshot.records.filter(r=>r.publication_date<=today&&r.month<=previousMonth);
 const latest=eligible.at(-1);
 const snapshotAge=days(today,snapshot.source_checked_at_utc.slice(0,10));
 const staleSnapshot=snapshotAge>75;
 const rate=latest?(latest.official_yoy_pct>0?'+':'')+latest.official_yoy_pct.toFixed(2)+'%':'尚無官方公告';
 const month=latest?latest.month:'尚無可用月份';
 const released=latest?latest.publication_date:'—';
 const lastMonth=eligible.find(r=>r.month===previousMonth);
 const ageText=latest?.month===previousMonth?
  '上個月的官方 CPI 公告已收錄；歷史資料庫同步進度請見進階資料。':
  '上個月（'+safe(previousMonth)+'）尚未收錄公告，以下顯示 GitHub 已保存的最近一次官方公告。';
 const statusLabel=latest?'已收錄官方公告':'尚未收錄官方公告';
 const ytd=snapshot.latest_official_ytd;
 const ytdValid=!!(latest&&ytd&&ytd.period===latest.month&&ytd.publication_date<=today&&
   knownHost(ytd.source_url)&&Number.isFinite(ytd.average_yoy_pct)&&Math.abs(ytd.average_yoy_pct)<100);
 const ytdText=ytdValid?(ytd.average_yoy_pct>0?'+':'')+Number(ytd.average_yoy_pct).toFixed(2)+'%':'尚無年初至今平均公告';
 const ytdPeriod=ytdValid?'今年 1～'+Number(month.slice(-2))+' 月':'截至最新官方公布月份';
 const details=eligible.map(r=>'<li>'+safe(r.month)+'：'+safe(r.verification)+
  '；公告年增率 '+safe((r.official_yoy_pct>0?'+':'')+r.official_yoy_pct.toFixed(2))+'%'+
  '；公告 CPI 指數 '+safe(r.index.toFixed(2))+
  (r.verification==='HISTORICAL_VINTAGE_DIFFERENCE'?'／歷史主資料 '+safe(r.primary_index.toFixed(2)):'')+
  '；公布 '+safe(r.publication_date)+
  '；<a href="'+safe(r.official_source_url)+'" target="_blank" rel="noopener noreferrer">官方公告</a></li>').join('');
 box.dataset.status=staleSnapshot?'stale':latest?'published':'pending';
 box.innerHTML='<div class="cpi-heading"><strong class="cpi-state-title">主計總處 CPI 公開快照</strong><span class="cpi-status">'+safe(statusLabel)+'</span></div>'+
  '<div class="cpi-public-grid"><div><small>'+safe(ytdPeriod)+' CPI 平均較去年同期</small><strong>'+safe(ytdText)+'</strong><small>官方年初至今累計平均</small></div>'+
  '<div><small>最新月份年增率（'+safe(month)+'）</small><strong>'+safe(rate)+'</strong><small>公布 '+safe(released)+'</small></div></div>'+
  '<p class="cpi-caption">'+ageText+' 網站直接呈現 GitHub 上的官方公告數字；年初至今累計平均並非各月份年增率的簡單平均。如有後續修訂，依下一次資料更新為準。</p>'+
  (staleSnapshot?'<p class="cpi-warning">GitHub 的 CPI 快照超過 75 天未重新核對，請確認自動排程是否正常執行。</p>':'')+
  '<p class="cpi-caption">查詢基準：台灣 '+safe(today)+'，最多顯示到 '+safe(previousMonth)+'。月度「年增率」不等於 2026 全年 CPI 年平均，也不會直接修改已核准的退休計算紀錄。</p>'+
  '<details class="cpi-source-detail"><summary>進階資料：原始 CPI、來源與雙來源核對紀錄</summary>'+
  '<p>此區保留完整查證狀態：BULLETIN_ONLY_PENDING_PRIMARY 代表正式新聞稿及附表已核對、但歷史主表尚未同步；CROSS_VERIFIED 代表兩份來源一致。此狀態不影響主畫面呈現已正式公布的年增率。</p>'+
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
 const published=snapshot.records.filter(r=>
  r.month<=lastMonth&&r.publication_date<=day&&r.publication_date<=now
 ).at(-1);
 if(!published||days(day,published.publication_date)>120||days(day,published.publication_date)<0)return;
 manual.value=published.index.toFixed(2);
 release.value=published.publication_date;
 manual.dataset.officialMonth=published.month;
 const note=manual.closest('label')?.querySelector('small');
 if(note)note.textContent='已帶入 '+published.month+' 的官方新聞稿及附表 CPI（公布 '+published.publication_date+'；來源由 GitHub 核對）。此數值不是 2026 全年 CPI；可改為手動假設。';
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
