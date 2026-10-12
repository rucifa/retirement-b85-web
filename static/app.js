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
let capacityEstimate=null, capacityApprovalId=null;
function capacityHtml(result){
 if(result==='pending')return '<section class="capacity-research" aria-live="polite"><h3>正在執行進階研究</h3><p>正在計算兩種初始 PoS 研究門檻；不影響已核准的年度生活費。</p></section>';
 if(!result)return '<section class="capacity-research"><p>按此區塊展開後才會啟動 95%／99% 初始 PoS 研究計算；不會更動年度核准結果。</p></section>';
 if(result.error)return '<section class="capacity-research" role="alert"><p>進階研究暫時無法完成：'+esc(result.error)+'</p><button id="capacity-retry-btn" type="button" class="secondary-btn">重新計算研究候選值</button></section>';
 const tile=(r,label)=>{
  const ok=Number.isFinite(r?.normal_2026_real_twd);
  const amount=ok?twMoney(r.normal_2026_real_twd):'最低必要生活費未達該門檻';
  const details=ok?'初始模型 PoS '+pct(100*r.inner_pos)+'；依候選生活費重跑 B＋85 首年，按日參考 '+twMoney(r.first_year_living_nominal_twd):'請檢視資產、退休年齡或降低風險門檻，不會擅自調低最低生活費。';
  const v=r?.validation;
  const risk=v?'<p class="capacity-risk">獨立動態研究抽樣 '+v.paths+' 條：完整計畫成功率 '+pct(100*v.model_full_policy_success)+'，模型未觸發 Floor Breach 比率 '+pct(100*v.model_no_floor_breach_fraction)+'，曾減支 '+pct(100*v.ever_cut_probability)+'。此樣本尚非外部校準。</p>':'';
  return '<article><small>'+label+' 初始必要資產 PoS 門檻</small><strong>'+esc(amount)+'</strong><p>'+esc(details)+'</p>'+risk+'</article>';
 };
 return '<section class="capacity-research" aria-label="退休生活費容量雙門檻研究">'+
  '<div class="capacity-heading"><h3>資產可支持的起始生活費（研究候選）</h3><span>2026 年實質金額 · 非核准提款</span></div>'+
  '<div class="capacity-grid">'+tile(result.results.p95,'95%')+tile(result.results.p99,'99%')+'</div>'+
  '<p>最低必要生活費 '+twMoney(result.floor_2026_real_twd)+' 固定不變。雙金額只是「初始、固定 Sticky 的必要資產 PoS」容量，<strong>不是經完整動態驗證的最高安全提領額</strong>，不能直接領走。實際年度預算請以上方 B＋85 試算結果為準。</p>'+
  '<button id="capacity-audit-btn" class="secondary-btn" type="button">追加獨立動態 MC 研究驗證（初步樣本）</button></section>';
}
function capacityAdvancedHtml(result){
 if(!state?.plan?.spending_profile)return '';
 return '<details id="capacity-research-details" class="advanced capacity-research-details">'+
  '<summary>進階風險研究：95%／99% 初始模型容量（選用）</summary>'+
  '<p class="research-disclaimer">一般退休試算不需要使用此功能。此處是尚未完成終生動態認證的初始 PoS 研究，<strong>不是建議提領額</strong>，也不會降低你設定的最低必要生活費。展開後才會另外計算。</p>'+
  capacityHtml(result)+'</details>';
}
async function showCapacity(withValidation=false){
 const first=state?.years?.[0];
 if(!first||!state?.plan?.spending_profile)return;
 const key=first.approval_id;
 if(!withValidation&&capacityApprovalId===key&&capacityEstimate)return;
 capacityApprovalId=key;capacityEstimate='pending';render();
 try{
  const args=withValidation?{validation_paths:512,validation_inner:256}:{};
  const result=await request('/api/capacity',args);
  if(state?.years?.[0]?.approval_id!==key)return;
  capacityEstimate=result;
 }catch(e){capacityEstimate={error:e.message};
  const panel=$('opening-result');if(panel)panel.dataset.capacityError=e.message;
 }
 render();
}

function databaseOpen(){return new Promise((resolve,reject)=>{const r=indexedDB.open(dbName,1);r.onupgradeneeded=()=>{if(!r.result.objectStoreNames.contains(dbStore))r.result.createObjectStore(dbStore)};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
function dbRead(){return new Promise((res,rej)=>{const t=database.transaction(dbStore,'readonly');const q=t.objectStore(dbStore).get(dbKey);q.onsuccess=()=>res(q.result||null);q.onerror=()=>rej(q.error);});}
function dbWrite(record){return new Promise((res,rej)=>{const t=database.transaction(dbStore,'readwrite');t.objectStore(dbStore).put(JSON.stringify(record),dbKey);t.oncomplete=()=>res();t.onerror=()=>rej(t.error);t.onabort=()=>rej(t.error||Error('瀏覽器資料儲存被拒絕'));});}
function callWorker(op,data={}){return new Promise((resolve,reject)=>{if(!worker){reject(Error('計算引擎尚未啟動'));return;}const id=++seq;pending.set(id,{resolve,reject});worker.postMessage({id,op,data});});}
function downloadJson(data){const a=document.createElement('a'),u=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));a.href=u;a.download='B85_年度研究備份_'+new Date().toISOString().slice(0,10)+'.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),10000);}
async function request(path,data={}){if(!engineReady)throw Error('瀏覽器計算環境尚未完成載入');const op=({'/api/state':'state','/api/approve':'approve','/api/close':'close','/api/demo-close':'demo-close','/api/export':'export','/api/reset':'reset','/api/import':'import','/api/capacity':'capacity'})[path];if(!op)throw Error('未允許的請求');return await callWorker(op,data);}
const runtimeStages={engine:{state:'loading',percent:0,text:'等待載入 Python 與政策模型'},storage:{state:'loading',percent:0,text:'等待讀取此瀏覽器內的年度紀錄'},cpi:{state:'loading',percent:0,text:'等待驗證已公布的官方 CPI 資料'}};
function setRuntimeStage(name,stateName,percent,text){
 const stage=runtimeStages[name];if(!stage)return;
 stage.state=stateName;stage.percent=Math.max(0,Math.min(100,Number(percent)||0));
 if(text)stage.text=text;
 const card=$('runtime-stage-'+name),bar=$('runtime-stage-'+name+'-bar'),pct=$('runtime-stage-'+name+'-pct'),msg=$('runtime-stage-'+name+'-text');
 if(card)card.dataset.state=stateName;
 if(bar)bar.style.width=stage.percent+'%';
 if(pct)pct.textContent=Math.round(stage.percent)+'%';
 if(msg)msg.textContent=stage.text;
 const all=Object.values(runtimeStages),total=Math.round(all.reduce((sum,x)=>sum+x.percent,0)/all.length);
 const totalBar=$('runtime-total-bar');if(totalBar)totalBar.style.width=total+'%';
 const status=$('runtime-status');
 const usable=runtimeStages.engine.state==='ready'&&runtimeStages.storage.state==='ready';
 if(status){status.classList.toggle('ready',usable);status.classList.toggle('failed',all.some(x=>x.state==='failed'));}
 const readyCount=all.filter(x=>x.state==='ready').length;
 $('runtime-title').textContent=all.some(x=>x.state==='failed')?'部分資料載入失敗':readyCount===all.length?'瀏覽器計算環境已就緒':usable?'退休計算環境已可使用':'正在準備退休年度工具';
 $('runtime-detail').textContent=all.some(x=>x.state==='failed')?'可先繼續使用核心試算；失敗項目請稍後重試或查看提示。':readyCount===all.length?'三個模組皆已就緒，可開始試算與查看紀錄。':usable?'核心試算與本機紀錄已就緒，CPI 快照仍在讀取中。':'目前已完成 '+readyCount+'/3 個模組，請稍候。';
}
window.B85_RUNTIME_PROGRESS={setStage:setRuntimeStage};
function setLoadingStatus(message,error=false){const stateName=error?'failed':engineReady?'ready':'loading';setRuntimeStage('engine',stateName,engineReady&&!error?100:(error?0:45),message);}
async function load(){try{
  database=await databaseOpen();setRuntimeStage('storage','loading',45,'正在檢查此瀏覽器是否已有保存紀錄');const saved=await dbRead();setRuntimeStage('storage','ready',100,saved&&saved.includes('year')?'已讀取本機年度紀錄，可接續上一年度。':'目前尚無本機年度紀錄，可直接開始第一次試算。');
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
 const period=part?'退休開始年度・依實際日期計算':`完整年度・${y.year} 年`;
 const annual=part?`模型全年生活費參考為 ${twMoney(y.full_year_living_reference_twd)}；本次依起始日至年底按日換算為 ${total}。換車及額外必要支出不按天數縮減。`:'';
 const applicable=part?`適用期間：${String(y.period_start).replaceAll('-','/')}～${String(y.period_end).replaceAll('-','/')}（含起始日，共 ${y.calendar_days} 天）`:`適用期間：${y.year}/01/01～${y.year}/12/31（全年）`;
 const budgetExplanation='這是上述期間可安排的生活費總預算，不代表需要在起始日一次提領整筆，也不包含換車或其他必要支出。';
 const amountOK=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))&&Number(v)>=0;
 const bridgeValid=amountOK(y.bridge_from_cash_twd),refillValid=amountOK(y.cash_refill_twd),cashValid=amountOK(y.cash_open_twd);
 const bridge=bridgeValid?twMoney(y.bridge_from_cash_twd):'資料待確認';
 const refill=refillValid?twMoney(y.cash_refill_twd):'資料待確認';
 const startingCash=cashValid?twMoney(y.cash_open_twd):'資料待確認';
 const posValue=Number(y.pos_pct),hasPos=Number.isFinite(posValue);
 const bridgeNote=!bridgeValid?'舊年度資料缺少安全現金橋接數據，請核對備份。':
  Number(y.bridge_from_cash_twd)>0?`本次以安全現金 ${bridge} 支應部分生活費，已包含在生活費預算內。`:
  hasPos&&posValue>75?`本次 PoS ${pct(posValue)} 高於橋接門檻 75%，因此不啟動；大額支出本身不會觸發熊市橋接。`:
  '本次未動用橋接；即使 PoS 達到門檻，仍須受可用安全現金及緊急預備金限制。';
 const refillNote=!refillValid?'舊年度資料缺少現金補回數據，請核對備份。':
  Number(y.cash_refill_twd)>0?`本次由投資資產移回安全現金 ${refill}；屬資產間移轉，不是新增收入。`:
  '本次未補回。只有 PoS 高於 75%、現金低於政策目標的 95%、必要支出可支付且仍有投資資產時，才會逐步補回；不是每逢多頭就自動補滿。';
 const extraKnown=amountOK(y.extra_authorized_twd)&&Number(y.extra_authorized_twd)>0&&!y.extra_included_in_pos;
 const extraPosWarning=extraKnown?
  `<p class="policy-caveat"><strong>重要：本次新增必要支出 ${esc(twMoney(y.extra_authorized_twd))} 雖已列入年度預算，卻沒有加入本年度原始 PoS 的內層試算。</strong> 上方成功機率不能視為已包含這筆新增支出的完整終生風險評估；請勿因此認定資產已充分支應未來所有費用。</p>`:'';
 const budgetTotal=amountOK(y.total_budget_twd)?twMoney(y.total_budget_twd):'資料待確認';
 return `<div class="result-caption">${y.year} 年・${y.age} 歲・${period}・B＋85 研究演練</div>
 <div class="result-grid result-grid-finance">
 ${metric('本次建議生活費預算',total,true)}
 ${metric('模型成功機率（PoS）',pos)}
 ${metric('本次安全現金橋接',bridge)}
 ${metric('本次安全現金補回',refill)}
 </div>
 <p class="details-summary budget-period-note">${esc(applicable)}。${esc(budgetExplanation)}</p>
 <div class="cash-bridge-explain" role="note">
  <p><strong>本次試算開始時安全現金：${esc(startingCash)}</strong>；本次生活費、換車及其他必要支出的核准總預算：${esc(budgetTotal)}。</p>
  <p><strong>安全現金橋接：</strong>${esc(bridgeNote)}</p>
  <p><strong>安全現金補回：</strong>${esc(refillNote)}</p>
  <p>橋接屬於生活費的資金來源，<strong>不是生活費之外可以再加領的金額</strong>；補回只是由投資資產轉入現金，不是新的投資報酬。安全現金起始額也不是年底預估額。</p>
 </div>${extraPosWarning}
 <div class="progress-track"><div class="progress-bar" style="width:${Math.max(0,Math.min(100,y.pos_pct))}%"></div></div>
 <div class="status-line">● ${esc(cpiBasis)} ${esc(annual)} ${y.b85_restored?'符合 B＋85 生活預算恢復條件':'按當年 Guardrail 狀態計算'}，年度 Sticky 乘數 ${esc(y.sticky_after)}。</div>
 <p class="details-summary">換車專項預算：${car}　／　已核准其他必要支出：${twMoney(y.extra_authorized_twd)}。<br>費用與稅負使用模型既有整體淨報酬情境，年末核對不會重扣。PoS 採完整年度模型作參考，未針對首年短期間重新校準；成功率不是保證。</p>
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
 return '<div class="inflation-head"><strong>'+esc(year||'本年度')+' 年物價與生活費</strong><span>以 2026 年輸入或預設的全年生活費 '+esc(twMoney(normalBase))+' 為基準</span></div>'
   +'<div class="inflation-cards">'
   +'<div><small>最近一年物價變動（參考）</small><strong>'+esc(signedPct(annual))+'</strong></div>'
   +'<div><small>自 2026 年累計物價變動</small><strong>'+esc(signedPct(cumulative))+'</strong></div>'
   +'<div class="inflation-normal"><small>原設定的全年生活費（通膨換算後）</small><strong>'+esc(twMoney(normal))+'</strong></div>'
   +'</div><p class="inflation-hint">'+esc(priorText)+' 這是完整一年的生活費設定參考，不是本次適用期間的建議生活費預算，也不是應立即提領的金額。B＋85 仍會依 Guardrail、PoS 和 Prosperity 調整；以上數值依本次使用的 CPI 計算，不等於即時官方通膨率。</p>';
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
 if(last.closing&&$('decision_date').value.slice(0,4)!==String(last.year+1)){
 $('decision_date').value=(last.year+1)+'-01-15';
 $('decision_cpi').value='';$('decision_cpi_release').value='';
 $('decision_cpi').dataset.autoSource='';
 $('planned_extra_twd').value=0;
 $('decision_date').dispatchEvent(new Event('change',{bubbles:true}));
}
}
function render(){
 const modelLabel=$('dash-engine-name');
 if(modelLabel)modelLabel.textContent=state?.plan?.spending_profile?
  '個人化生活費研究 v1 · B＋85 衍生版':'B＋85 基準 · v3.4.0';
 const last=lastYear();
 const advancedOpen=$('capacity-research-details')?.open===true;
 $('opening-result').classList.toggle('hidden',!last);
 if(last){
  $('opening-result').innerHTML=budgetHtml(last)+capacityAdvancedHtml(capacityEstimate);
  const advanced=$('capacity-research-details');if(advanced&&advancedOpen)advanced.open=true;
 }
 const sp=state?.plan?.spending_profile;
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
 // Do not invent an official CPI release date; user must provide verified provenance.
 if(!$('closing_cpi_release').value||Number($('closing_cpi_release').value.slice(0,4))!==today)$('closing_cpi_release').value='';
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
 await request('/api/import',imported);capacityEstimate=null;capacityApprovalId=null;await refresh();display('history');flash('備份 SHA256 與年度連續性已驗證，匯入完成。','success');
 }catch(err){flash('匯入失敗：'+err.message)}finally{e.target.value='';}});
$('reset-btn').addEventListener('click',async()=>{
 if(!engineReady){flash('計算引擎尚未就緒，暫時無法清除');return;}
 if(!confirm('確定清除這個瀏覽器的全部退休演練紀錄？\n\n按「確定」後會先下載 JSON 備份，再刪除本機年度資料。\n這項動作無法由網頁復原，需使用備份重新匯入。'))return;
 const btn=$('reset-btn');btn.disabled=true;
 try{
  const backup=await request('/api/export',{});
  downloadJson(backup);
  await request('/api/reset',{confirm:'清除演練'});
  capacityEstimate=null;capacityApprovalId=null;await refresh();display('opening');flash('已先下載 JSON 備份，並清除本瀏覽器的演練紀錄。','success');
 }catch(e){flash('清除未完成：'+e.message+'。請使用先前備份復原。')}
 finally{btn.disabled=false;}
});
document.addEventListener('click',e=>{
 if(e.target.closest('#capacity-audit-btn')){void showCapacity(true);return;}
 if(e.target.closest('#capacity-retry-btn')){capacityEstimate=null;void showCapacity();return;}
 const b=e.target.closest('[data-go]');if(b&&!b.disabled){display(b.dataset.go);}
});
document.addEventListener('toggle',e=>{
 if(e.target.id==='capacity-research-details'&&e.target.open&&capacityEstimate===null)void showCapacity();
},true);
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
