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
 const live=document.getElementById('latest-cpi-index'),meta=document.getElementById('latest-cpi-meta');
 // Every number below was checked against its official bulletin and attached Table-1 XLSX
 // by GitHub before publishing. The historical XLS may trail the publication.
 const eligible=snapshot.records.filter(r=>r.publication_date<=today&&r.month<=previousMonth);
 const latest=eligible.at(-1);
 const snapshotAge=days(today,snapshot.source_checked_at_utc.slice(0,10));
 const staleSnapshot=snapshotAge>75;
 const rate=latest?(latest.official_yoy_pct>0?'+':'')+latest.official_yoy_pct.toFixed(2)+'%':'尚無官方公告';
 const month=latest?latest.month:'尚無可用月份';
 const released=latest?latest.publication_date:'—';
 if(live)live.textContent=latest?Number(latest.index).toFixed(2):'尚無公告';
 if(meta)meta.textContent=latest?latest.month+' 官方指數・公布 '+latest.publication_date+'；若模擬歷史日期，試算仍以當時已公布數值為準。':'尚未取得最新公布指數，請稍後重試。';
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
function prefillReferenceFromPublishedMonths(){
 const base=document.getElementById('cpi_2026'),
       help=document.getElementById('cpi-reference-explanation');
 if(!base||!snapshot||!window.B85_TAIWAN_TIME)return;
 try{if(typeof state!=='undefined'&&state?.years?.length)return;}catch{return;}
 if(base.dataset.userEdited==='true')return;
 const today=window.B85_TAIWAN_TIME.today();
 const previous=window.B85_TAIWAN_TIME.prevMonth(today);
 const published=snapshot.records.filter(r=>r.month.startsWith('2026-')&&r.month<=previous&&r.publication_date<=today);
 const newest=published.at(-1);
 const chart=snapshot.current_year_chart;
 if(!newest||!Array.isArray(chart)||chart.length===0){
  if(help)help.textContent='目前尚無可驗證的 2026 年 CPI 月度資料，請自行輸入基準指數並核對資料；系統不會預填虛構數字。';
  return;
 }
 const monthly=chart.filter(r=>r.month?.startsWith('2026-')&&r.month<=newest.month&&Number.isFinite(r.index));
 if(!monthly.length||monthly[0].month!=='2026-01'||monthly.at(-1).month!==newest.month){
  if(help)help.textContent='目前無法確認年初至今每個月的 CPI，請先核對來源再自行輸入年度基準。';
  return;
 }
 // Monthly index levels in a consistent 2021=100 base, NOT the mean of YoY %.
 const provisional=monthly.reduce((sum,r)=>sum+r.index,0)/monthly.length;
 base.value=provisional.toFixed(2);
 base.dataset.autoSource='OFFICIAL_YTD_INDEX_AVG_PROVISIONAL';
 base.dataset.latestMonth=newest.month;
 if(help)help.textContent='已自動取用 GitHub 官方月指數：2026 年 1～'+
   Number(newest.month.slice(-2))+' 月平均 '+base.value+
   '（2021＝100）。隨新月份公告更新；不是 2026 全年官方平均，也不是月年增率。已建立的年度不會改寫。';
 base.dispatchEvent(new Event('input',{bubbles:true}));
}
function prefillInitialMonthlyCpi(){
 const input=document.getElementById('decision_cpi'),release=document.getElementById('decision_cpi_release');
 const base=document.getElementById('cpi_2026'),notice=document.getElementById('cpi-decision-asof-note');
 const caption=document.getElementById('decision-cpi-date-caption');
 if(!input||!release||!base||!decision||!window.B85_TAIWAN_TIME)return;
 try{if(typeof state!=='undefined'&&state?.years?.length&&!state.years.at(-1)?.closing)return}catch{return}
 const day=decision.value;if(!validDate(day))return;
 if(input.dataset.userEdited==='true'||release.dataset.userEdited==='true'){
  input.dataset.autoSource='MANUAL';
  if(notice)notice.textContent='目前為自行輸入的 CPI；請確認公布日期不晚於決策日。';
  if(caption)caption.textContent='CPI 官方公布日期（自行核對）';
  return;
 }
 if(input.value&&release.value&&!input.dataset.autoSource){
  if(notice)notice.textContent='已有自行設定的 CPI，請核對是否適用於 '+day+'。';
  return;
 }
 const today=window.B85_TAIWAN_TIME.today(),lastMonth=window.B85_TAIWAN_TIME.prevMonth(day);
 const eligible=snapshot?.records?.filter(r=>r.month<=lastMonth&&r.publication_date<=day&&r.publication_date<=today).at(-1);
 // A stale 3+ month index is not automatically the right next-year index.
 const recent=eligible&&days(day,eligible.publication_date)>=0&&days(day,eligible.publication_date)<=65;
 const help=input.closest('label')?.querySelector('small');
 if(recent){
  input.value=Number(eligible.index).toFixed(2);release.value=eligible.publication_date;
  input.dataset.autoSource='OFFICIAL_BULLETIN';
  if(notice)notice.textContent='已採用 '+day+' 當時可用的 '+eligible.month+' 官方 CPI 指數；旁邊的快照仍顯示今日最新資料。';
  if(caption)caption.textContent='CPI 官方公布日期';
  if(help)help.textContent='來自官方新聞稿及附表，公布 '+eligible.publication_date+'。';
 }else if(day.startsWith('2026-')){
  const assumed=base.value.trim();
  if(!assumed){
   input.value='';release.value='';
   input.dataset.autoSource='MISSING_HISTORICAL_CPI';
   if(notice)notice.textContent='缺少 2026 CPI 基準，無法建立日期 '+day+' 的演練假設；請確認自動資料或自行填入指數。';
   return;
  }
  input.value=assumed;release.value=day;
  input.dataset.autoSource='SCENARIO_2026_BASELINE';
  if(notice)notice.textContent='此日期缺少可核對的當時 CPI：使用 2026 年暫定基準 '+assumed+
     ' 作演練假設（非當天公布的官方指數）。歷史日期不會倒填後來才公布的月 CPI。';
  if(caption)caption.textContent='演練假設生效日（非官方公布日）';
  if(help)help.textContent='使用自行設定的 2026 CPI 基準；非官方 CPI 資料。';
 }else{
  input.value='';release.value='';input.dataset.autoSource='MISSING_HISTORICAL_CPI';
  if(notice)notice.textContent='無法在 GitHub 快照找到 '+day+' 當日近期已公布 CPI。請從官方來源確認月份、指數與真正公布日期後手動輸入；不得沿用上一年結算的 CPI 並製造公布日期。';
  if(caption)caption.textContent='CPI 官方公布日期';
  if(help)help.textContent='目前缺少當日可用的 CPI，請手動補充。';
 }
 input.dispatchEvent(new Event('input',{bubbles:true}));
}
const manualCpi=document.getElementById('decision_cpi'),manualRelease=document.getElementById('decision_cpi_release');
if(manualCpi)manualCpi.addEventListener('input',e=>{if(e.isTrusted){manualCpi.dataset.userEdited='true';manualCpi.dataset.autoSource='MANUAL';}});
if(manualRelease)manualRelease.addEventListener('input',e=>{if(e.isTrusted){manualRelease.dataset.userEdited='true';if(manualCpi)manualCpi.dataset.autoSource='MANUAL';}});
decision.addEventListener('input',prefillInitialMonthlyCpi);
decision.addEventListener('change',prefillInitialMonthlyCpi);
document.getElementById('cpi_2026')?.addEventListener('input',e=>{
 if(e.isTrusted)e.currentTarget.dataset.userEdited='true';
 if(['SCENARIO_2026_BASELINE','MISSING_HISTORICAL_CPI'].includes(manualCpi?.dataset.autoSource))prefillInitialMonthlyCpi();
});
async function load(){
 try{
  const r=await fetch('./data/cpi_verified.json',{cache:'no-store'});
  if(!r.ok)throw Error('HTTP '+r.status);
  snapshot=validate(await r.json());loadError='';prefillReferenceFromPublishedMonths();prefillInitialMonthlyCpi();
 }catch(e){snapshot=null;loadError=e.message||'無法驗證快照'}
 paint();
}
load();
})();
