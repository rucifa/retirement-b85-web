'use strict';
let token='', state=null, active='opening', engineReady=false;
const $=id=>document.getElementById(id);
const num=x=>Number(x||0);
const twd=n=>new Intl.NumberFormat('zh-TW',{maximumFractionDigits:0}).format(Math.round(Number(n)||0));
const twMoney=n=>'NT$ '+twd(n);
const pct=x=>num(x).toFixed(1)+'%';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function flash(msg,kind='error'){const a=$('alert');a.textContent=msg;a.className='alert'+(kind==='success'?' success':'');a.hidden=false;window.scrollTo({top:70,behavior:'smooth'});}
function clearFlash(){$('alert').hidden=true;}
const dbName='B85-retirement-local-v1', dbStore='user-records', dbKey='annual';
let database=null, worker=null, seq=0;
const pending=new Map();
function databaseOpen(){return new Promise((resolve,reject)=>{const r=indexedDB.open(dbName,1);r.onupgradeneeded=()=>{if(!r.result.objectStoreNames.contains(dbStore))r.result.createObjectStore(dbStore)};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
function dbRead(){return new Promise((res,rej)=>{const t=database.transaction(dbStore,'readonly');const q=t.objectStore(dbStore).get(dbKey);q.onsuccess=()=>res(q.result||null);q.onerror=()=>rej(q.error);});}
function dbWrite(record){return new Promise((res,rej)=>{const t=database.transaction(dbStore,'readwrite');t.objectStore(dbStore).put(JSON.stringify(record),dbKey);t.oncomplete=()=>res();t.onerror=()=>rej(t.error);t.onabort=()=>rej(t.error||Error('瀏覽器資料儲存被拒絕'));});}
function callWorker(op,data={}){return new Promise((resolve,reject)=>{if(!worker){reject(Error('計算引擎尚未啟動'));return;}const id=++seq;pending.set(id,{resolve,reject});worker.postMessage({id,op,data});});}
function downloadJson(data){const a=document.createElement('a'),u=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));a.href=u;a.download='B85_年度研究備份_'+new Date().toISOString().slice(0,10)+'.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),10000);}
async function request(path,data={}){if(!engineReady)throw Error('瀏覽器計算環境尚未完成載入');const op=({'/api/state':'state','/api/approve':'approve','/api/close':'close','/api/demo-close':'demo-close','/api/export':'export','/api/reset':'reset','/api/import':'import'})[path];if(!op)throw Error('未允許的請求');return await callWorker(op,data);}
function setLoadingStatus(message,error=false){const status=$('runtime-status');status.classList.toggle('ready',engineReady&&!error);status.classList.toggle('failed',error);$('runtime-title').textContent=error?'引擎載入失敗':engineReady?'瀏覽器計算環境已就緒':'正在準備退休年度工具';$('runtime-detail').textContent=message;}
async function load(){try{
  database=await databaseOpen();const saved=await dbRead();
  worker=new Worker('./pyodide-worker.js',{name:'B85-policy-worker'});
  worker.onmessage=async event=>{const m=event.data;if(m.type==='progress'){setLoadingStatus(m.message);return;}if(m.type!=='result')return;const job=pending.get(m.id);if(!job)return;pending.delete(m.id);
   if(!m.ok){job.reject(Error(m.error||'模型計算失敗'));return;}
   try{if(m.record){await dbWrite(m.record)}job.resolve(m.data)}catch(e){job.reject(Error('無法保存年度紀錄：'+e.message+'。本次操作不視為完成，請檢查瀏覽器儲存空間並重新開啟頁面。'));engineReady=false;setLoadingStatus('資料儲存發生錯誤，請重新整理並檢查備份。',true)}
  };
  worker.onerror=e=>{engineReady=false;setLoadingStatus('B＋85 背景運算錯誤；請重新整理並確認網路或瀏覽器設定。',true);flash('模型載入失敗：'+e.message)};
  const result=await callWorker('init', {saved});
  engineReady=true;setLoadingStatus('已就緒。資料保存在此瀏覽器，建議定期匯出 JSON 備份。');state=result;render();
 }catch(e){engineReady=false;setLoadingStatus('載入失敗：'+e.message+'。請確認瀏覽器支援 WebAssembly、IndexedDB，並能連接 Pyodide CDN。',true);flash('退休工具無法啟動：'+e.message)}}
function display(view){
 active=view;for(const id of ['opening','closing','history']){$('panel-'+id).classList.toggle('hidden',id!==view)}
 document.querySelectorAll('[data-go]').forEach(b=>b.classList.toggle('selected',b.dataset.go===view));
 $('breadcrumb-current').textContent=({opening:'年初核准',closing:'年末結算',history:'歷年紀錄'})[view];
 clearFlash();
}
function metric(k,v,feature=false){return `<div class="metric ${feature?'featured':''}"><small>${esc(k)}</small><strong class="money-strong">${esc(v)}</strong></div>`}
function lastYear(){return state?.years?.length?state.years[state.years.length-1]:null}
function budgetHtml(y){
 if(!y)return '';
 const total=twMoney(y.living_authorized_twd),car=twMoney(y.car_authorized_twd),pos=pct(y.pos_pct);
 const part=y.calendar_first_year;
 const cpiBasis=y.decision_cpi_source==='SCENARIO_2026_BASELINE'?'本年 CPI 為演練假設（非當時官方公布）。':'';
 const period=part?`首年 ${y.period_start}～${y.period_end}・含首日 ${y.calendar_days}/${y.calendar_year_days} 天（${(y.calendar_fraction*100).toFixed(2)}%）`:`完整年度・${y.year} 年`;
 const annual=part?`按日換算前全年生活費 ${twMoney(y.full_year_living_reference_twd)}，首年核准 ${total}。車輛及額外必要支出不按天數縮減。`:'';
 return `<div class="result-caption">${y.year} 年・${y.age} 歲・${period}・B＋85 研究演練</div>
 <div class="result-grid">
 ${metric('今年核准生活費',total,true)}
 ${metric('全年模型參考 PoS',pos)}
 ${metric('換車專項預算',car)}
 </div><div class="progress-track"><div class="progress-bar" style="width:${Math.max(0,Math.min(100,y.pos_pct))}%"></div></div>
 <div class="inflation-preview result-inflation">${inflationCards(Number(y.decision_cpi),Number(state?.plan?.cpi_2026),state?.years?.length>1?Number(state.years[state.years.length-2].decision_cpi):null,y.year,Number(state?.plan?.spending_profile?.normal_twd??650000))}</div>
 <div class="status-line">● ${esc(cpiBasis)} ${esc(annual)} ${y.b85_restored?'符合 B＋85 生活預算恢復條件':'按當年 Guardrail 狀態計算'}，年度 Sticky 乘數 ${esc(y.sticky_after)}。</div>
 <p class="details-summary">熊市現金橋接：${twMoney(y.bridge_from_cash_twd)}　／　已核准其他必要支出：${twMoney(y.extra_authorized_twd)}。<br>費用與稅負使用模型既有整體淨報酬情境，年末核對不會重扣。PoS 採完整年度模型作參考，未針對首年短期間重新校準；成功率不是保證。</p>
 ${!y.closing?'<div class="result-buttons"><button class="primary-btn" data-go="closing">下一步：年末結算 →</button></div>':'<div class="result-buttons"><button class="secondary-btn" data-go="history">查看已結算紀錄</button></div>'}`;
}

function inflationChange(current,previous){
 if(!(Number.isFinite(current)&&Number.isFinite(previous)&&current>0&&previous>0))return null;
 return (current/previous-1)*100;
}
function signedPct(value){
 if(value===null)return '尚無同期資料';
 return (value>0?'+':'')+value.toFixed(2)+'%';
}
function inflationCards(current,reference,previous,year,normalBase){
 const cumulative=inflationChange(current,reference);
 if(cumulative===null)return '<div class="inflation-hint">請輸入有效且相同基期的 CPI 資料，才可計算購買力。</div>';
 const annual=inflationChange(current,previous);
 const normal=normalBase*current/reference;
 const priorText=annual===null
 ? '首次使用尚未保存上一年度可比的 CPI；不能把 2026 至退休年的累計通膨當作今年通膨率。'
 : '以本次與上次「年初決策時可用 CPI」比較，屬期間參考變動；若兩次 CPI 非相同月份，不能稱為官方年增率。';
 return '<div class="inflation-head"><strong>'+esc(year||'本年度')+' 年物價與生活費</strong><span>以 2026 年設定的正常生活費 '+esc(twMoney(normalBase))+' 為基準</span></div>'
   +'<div class="inflation-cards">'
   +'<div><small>最近一年物價變動（參考）</small><strong>'+esc(signedPct(annual))+'</strong></div>'
   +'<div><small>自 2026 年累計物價變動</small><strong>'+esc(signedPct(cumulative))+'</strong></div>'
   +'<div class="inflation-normal"><small>通膨換算後正常生活費</small><strong>'+esc(twMoney(normal))+'</strong></div>'
   +'</div><p class="inflation-hint">'+esc(priorText)+' 正常生活費不是 B＋85 最終核准額；仍會依 Guardrail、PoS 和 Prosperity 調整。以上數值取決於手動輸入的 CPI，並非官方即時通膨率。</p>';
}
function renderInflationPreview(){
 const el=$('inflation-preview');if(!el)return;
 const previous=lastYear()?.decision_cpi??null;
 const reference=state?.plan?.cpi_2026??Number($('cpi_2026').value||0);
 const floorInput=Number($('floor_spend_2026_twd')?.value||0);
 const wish=$('normal_spend_2026_twd')?.value;
 const normal=Number(state?.plan?.spending_profile?.normal_twd??(wish||floorInput||650000));
 el.innerHTML=inflationCards(Number($('decision_cpi').value),Number(reference),Number(previous),$('decision_date').value.slice(0,4),normal);
}

function closeHtml(y){if(!y?.closing)return '';
 const c=y.closing;
 return `<div class="result-caption">${y.year} 年已完成年度結算 · 待真正來源驗證</div>
 <div class="result-grid">${metric('實際年度支出',twMoney(c.actual_paid_twd),true)}${metric('年底投資資產',twMoney(c.investment_end_twd))}${metric('年底安全現金',twMoney(c.cash_end_twd))}</div>
 <div class="status-line">● 年初預算與真實支出分開；帳務守恆檢查通過</div>
 <p class="details-summary">未花完預算依模型結轉到現金：${twMoney(c.unused_budget_at_close_twd)}。<br>從兩筆資產餘額推導的實質投資池報酬率：${pct(c.net_real_portfolio_return_pct)}（只用於本機演練，未獨立驗證交易、股息或資金轉帳）。</p>
 <div class="result-buttons"><button class="primary-btn" data-go="opening">開始下一年度 →</button><button class="secondary-btn" data-go="history">檢視年度紀錄</button></div>`;
}
function fillNext(){
 const last=lastYear();
 if(!last){$('first-year-fields').classList.remove('hidden');$('reference_cpi_field').classList.remove('hidden');return;}
 $('first-year-fields').classList.add('hidden');$('reference_cpi_field').classList.add('hidden');
 if(last.closing){$('decision_date').value=(last.year+1)+'-01-15';$('decision_cpi').value=last.closing.cpi;
 $('decision_cpi_release').value=(last.year+1)+'-01-10';$('planned_extra_twd').value=0;}
}
function render(){
 const modelLabel=$('dash-engine-name');
 if(modelLabel)modelLabel.textContent=state?.plan?.spending_profile?
  '個人化生活費研究 v1 · B＋85 衍生版':'B＋85 基準 · v3.4.0';
 const last=lastYear();
 $('opening-result').classList.toggle('hidden',!last);if(last)$('opening-result').innerHTML=budgetHtml(last);
 const baseline=$('dashboard-baseline');if(baseline)baseline.classList.toggle('hidden',!last);
 const sp=state?.plan?.spending_profile;
 const refs=sp||{normal_twd:650000,core_twd:600000,floor_twd:500000};
 for(const [field,key] of [['normal','normal_twd'],['core','core_twd'],['floor','floor_twd']]){
  const target=$('dash-baseline-'+field),sub=$('dash-baseline-'+field+'-month');
  if(target)target.textContent=twMoney(refs[key]);
  if(sub)sub.textContent='2026 年實質・每月約 '+twMoney(refs[key]/12);
 }
 if(baseline)baseline.setAttribute('data-profile-mode',sp?'GENERALIZED_RESEARCH_SPENDING_V1':'FROZEN_BASELINE');
 const pending=!!(last && !last.closing);
 $('opening-form').classList.toggle('hidden',pending||!!(last&&last.age>=104));
 $('opening-tag').textContent=pending?'等待年末結算':last?.closing?'可開始下一年':'準備建立';
 $('closing-tag').textContent=pending?'可進行結算':last?.closing?'已完成結算':'尚未核准';
 $('closing-readiness').classList.toggle('hidden',pending||!!(last?.closing));
 $('closing-form-wrap').classList.toggle('hidden',!pending);
 $('closing-result').classList.toggle('hidden',!last?.closing);
 if(last?.closing)$('closing-result').innerHTML=closeHtml(last);
 if(pending){
 $('closing-budget').innerHTML='<span>本年度核准生活費 <strong>'+twMoney(last.living_authorized_twd)+'</strong></span><span>額外預算 '+twMoney(last.car_authorized_twd+last.extra_authorized_twd)+'</span>';
 const today=last.year;
 if(!$('closing_date').value||Number($('closing_date').value.slice(0,4))!==today)$('closing_date').value=today+'-12-31';
 if(!$('closing_cpi').value)$('closing_cpi').value=last.decision_cpi;
 if(!$('closing_cpi_release').value||Number($('closing_cpi_release').value.slice(0,4))!==today)$('closing_cpi_release').value=today+'-12-20';
 if(!$('living_paid_twd').value)$('living_paid_twd').value=Math.floor(last.living_authorized_twd);
 }
 fillNext();
 renderInflationPreview();
 renderHistory();
}
function renderHistory(){
 const list=$('history-list');if(!state?.years?.length){list.innerHTML='<div class="empty-state"><span class="empty-icon">▤</span><h3>還沒有年度紀錄</h3><p>先從年初核准建立第一個年度。</p></div>';return}
 list.innerHTML=[...state.years].reverse().map(y=>`<div class="history-card"><div><strong>${y.year} 年　${y.age} 歲</strong><p>生活預算 ${twMoney(y.living_authorized_twd)} · ${y.closing?'年末已結算':'等待年末結算'} · PoS ${pct(y.pos_pct)}</p></div><div class="history-side"><strong>${y.closing?twMoney(y.closing.investment_end_twd+y.closing.cash_end_twd):'待結算'}</strong><small>${y.closing?'年度終了合計資產':'已核准金額未視為支出'}</small></div></div>`).join('');
}
async function refresh(){state=await request('/api/state');render();}
function updateDecisionMonthHelp(){
 const first=!(state?.years?.length);
 const hint=$('decision-month-guidance'),button=$('use-january-date');
 if(hint)hint.textContent=first?
   '首次退休可選任何日期。只核准當日至 12 月 31 日（含當日）的生活費；隔年一月重新核准全年。':
   '第二年以後每年一月重新核准完整年度，保留已保存的曆年帳本。';
 if(button)button.hidden=true;
}

const fieldVal=id=>$(id).value;
function initPayload(){return {
 decision_date:fieldVal('decision_date'),planned_extra_twd:fieldVal('planned_extra_twd'),start_age:fieldVal('start_age'),
 investment_twd:fieldVal('investment_twd'),cash_twd:fieldVal('cash_twd'),stock_bond:fieldVal('stock_bond'),
 cpi_2026:fieldVal('cpi_2026'),decision_cpi:fieldVal('decision_cpi'),decision_cpi_release:fieldVal('decision_cpi_release'),
 decision_cpi_source:$('decision_cpi').dataset.autoSource||'MANUAL',
 spending_profile_mode:'GENERALIZED_RESEARCH_SPENDING_V1',
 normal_spend_2026_twd:fieldVal('normal_spend_2026_twd')||fieldVal('floor_spend_2026_twd'),
 core_spend_2026_twd:fieldVal('core_spend_2026_twd'),
 floor_spend_2026_twd:fieldVal('floor_spend_2026_twd')};}
function endPayload(){return {closing_date:fieldVal('closing_date'),closing_cpi:fieldVal('closing_cpi'),
 closing_cpi_release:fieldVal('closing_cpi_release'),living_paid_twd:fieldVal('living_paid_twd'),
 car_paid_twd:fieldVal('car_paid_twd'),extra_paid_twd:fieldVal('extra_paid_twd'),
 investment_end_twd:fieldVal('investment_end_twd'),cash_end_twd:fieldVal('cash_end_twd'),
 emergency_paid_twd:fieldVal('emergency_paid_twd'),external_flow_twd:fieldVal('external_flow_twd')};}
function loading(id,flag){$(id).disabled=flag;$(id).classList.toggle('loading',flag)}
$('opening-form').addEventListener('submit',async e=>{e.preventDefault();renderSpendingProfileInput();
 if(!state?.years?.length&&$('spending-profile-preview').dataset.valid!=='true'){flash($('spending-profile-preview').textContent);return;}
 loading('approve-btn',true);try{await request('/api/approve',initPayload());await refresh();display('opening');flash('本年度預算已核准（研究演練），請核對後進行年末結算。','success')}catch(err){flash(err.message)}finally{loading('approve-btn',false)}});
$('closing-form').addEventListener('submit',async e=>{e.preventDefault();loading('close-btn',true);try{await request('/api/close',endPayload());await refresh();display('closing');flash('年末帳務已對帳並保存；可以開始下一年度。','success')}catch(err){flash(err.message)}finally{loading('close-btn',false)}});
$('demo-close-btn').addEventListener('click',async()=>{try{const x=await request('/api/demo-close',{});
 for(const k of ['closing_date','closing_cpi','closing_cpi_release','investment_end_twd','cash_end_twd','living_paid_twd','car_paid_twd','extra_paid_twd','emergency_paid_twd','external_flow_twd'])$(k).value=x[k];
 flash('已填入模擬年底餘額。'+x.simulation_note,'success')
 }catch(e){flash(e.message)}});
$('export-btn').addEventListener('click',async()=>{try{downloadJson(await request('/api/export',{}));flash('JSON 備份已下載，請保存到你自己的安全資料夾。','success')}catch(e){flash(e.message)}});
$('import-btn').addEventListener('click',()=>{if(!engineReady){flash('計算引擎尚未就緒');return;}$('import-file').click();});
$('import-file').addEventListener('change',async e=>{const file=e.target.files?.[0];if(!file)return;
 try{if(file.size>5_000_000)throw Error('備份檔案過大');const imported=JSON.parse(await file.text());
 if(!confirm('匯入備份將覆蓋此瀏覽器目前的年度紀錄。建議先匯出現有資料。確定匯入？'))return;
 await request('/api/import',imported);await refresh();display('history');flash('備份 SHA256 與年度連續性已驗證，匯入完成。','success');
 }catch(err){flash('匯入失敗：'+err.message)}finally{e.target.value='';}});
$('reset-btn').addEventListener('click',async()=>{
 if(!engineReady){flash('計算引擎尚未就緒，暫時無法清除');return;}
 if(!confirm('確定清除這個瀏覽器的全部退休演練紀錄？\n\n按「確定」後會先下載 JSON 備份，再刪除本機年度資料。\n這項動作無法由網頁復原，需使用備份重新匯入。'))return;
 const btn=$('reset-btn');btn.disabled=true;
 try{
  const backup=await request('/api/export',{});
  downloadJson(backup);
  await request('/api/reset',{confirm:'清除演練'});
  await refresh();display('opening');flash('已先下載 JSON 備份，並清除本瀏覽器的演練紀錄。','success');
 }catch(e){flash('清除未完成：'+e.message+'。請使用先前備份復原。')}
 finally{btn.disabled=false;}
});
document.addEventListener('click',e=>{const b=e.target.closest('[data-go]');if(b&&!b.disabled){display(b.dataset.go);}});
$('decision_date').addEventListener('change',()=>{$('first_year').value=$('decision_date').value.slice(0,4);updateDecisionMonthHelp();});
function renderSpendingProfileInput(){
 const floorEl=$('floor_spend_2026_twd'),wishEl=$('normal_spend_2026_twd'),
       coreEl=$('core_spend_2026_twd'),out=$('spending-profile-preview');
 if(!out)return;
 const f=Number(floorEl.value),n=wishEl.value.trim()?Number(wishEl.value):f;
 if(!floorEl.value.trim()||![f,n].every(x=>Number.isInteger(x)&&x>=12000&&x<=10000000)){
  out.textContent='請先填一年最低省不掉的生活費（12,000～10,000,000 元）。希望的生活費可以不填。';
  out.dataset.valid='false';return;
 }
 if(n<f){
  out.textContent='「希望每年花多少」不能低於最低必要生活費。';
  out.dataset.valid='false';return;
 }
 // The legacy 65/60/50 example places Core 2/3 of the way from Floor
 // toward desired spending. Core is an internal reference, NOT a second expense.
 if(coreEl.dataset.userEdited!=='true'){
  coreEl.value=String(Math.min(n,Math.max(f,Math.round(f+(n-f)*2/3))));
 }
 const c=Number(coreEl.value);
 if(!Number.isInteger(c)||c<f||c>n){
  out.textContent='進階的中間生活費參考值必須介於最低需求與希望的生活費之間。';
  out.dataset.valid='false';return;
 }
 out.dataset.valid='true';
 const selected=wishEl.value.trim()?'以你希望的年度生活費 '+twMoney(n)+' 作為模型預算起點。':
  '未填希望支出：先以最低需求 '+twMoney(f)+' 作為模型預算起點。';
 out.textContent='最低生活費每月約 '+twMoney(f/12)+'。'+selected+
  ' 按「試算」才會依資產、PoS 和 Guardrail 計算今年可安排的生活費；不是最大安全提領額。安全現金政策目標仍為 240 萬。';
}
for(const id of ['normal_spend_2026_twd','floor_spend_2026_twd']){
 $(id).addEventListener('input',()=>{renderSpendingProfileInput();renderInflationPreview();});
}
$('core_spend_2026_twd').addEventListener('input',e=>{
 if(e.isTrusted)e.currentTarget.dataset.userEdited='true';
 renderSpendingProfileInput();renderInflationPreview();
});
renderSpendingProfileInput();
for(const id of ['decision_date','cpi_2026','decision_cpi']){
 $(id).addEventListener('input',renderInflationPreview);
}
renderInflationPreview();
updateDecisionMonthHelp();
load();
