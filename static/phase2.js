/* 必要支出編輯與人工出售候選；模型運算仍由唯讀研究Worker執行。 */
(function(){
'use strict';
const $=id=>document.getElementById(id),esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>x===null||x===undefined?'尚無缺口':twMoney(x),pct=x=>(Number(x)*100).toFixed(2)+'%';
const categories={car:'購車',housing:'購屋',medical:'醫療',other:'其他'};
let editId=null,hydrated=null,planning=null,comparison=null,comparisonKey=null,runKey=null,worker=null,timer=null,sequence=0,running=false,lastKey=null;
const key=()=>{const y=state?.years?.at(-1);return (y?.approval_id||'none')+'|'+(y?.closing?.sha256||'pending')+'|'+(state?.expense_schedule?.sha256||'');};
function clearEditor(){$('expense-schedule-form').reset();editId=null;$('expense-save').textContent='新增排程';$('expense-cancel-edit').classList.add('hidden');basis();}
function basis(){const nominal=$('expense-basis').value==='nominal_year';$('expense-price-year-field').classList.toggle('hidden',!nominal);$('expense-price-year').required=nominal;if(!nominal)$('expense-price-year').value='';}
async function mutation(action,entry){await request('/api/expense-schedule',{action,entry});await refresh();}
function scheduleRender(){
 const s=state?.expense_schedule;if(!s)return;
 $('expense-inflation-saved').textContent='目前支出換算情境：年通膨 '+s.inflation_pct+'%。未來名目金額依最新已存CPI參考延伸；結算後採年末CPI作下一年價格錨點，不是官方未來預測。';
 $('expense-default-cars').textContent=s.default_car_years.length?'凍結定期換車年度：'+s.default_car_years.join('、')+'（不可重複新增同年度購車）。':'退休起點尚未確定：定期換車重複檢查會在年度核准前完成。';
 const resolved=new Map(s.resolved.map(x=>[x.id,x]));
 if(!s.entries.length){$('expense-schedule-list').textContent='尚無手動排程；原政策定期換車仍保留。';return;}
 $('expense-schedule-list').innerHTML='<table><caption>手動必要支出（不是實際付款）</caption><thead><tr><th>年度／類別</th><th>輸入金額與基準</th><th>換算參考</th><th>操作</th></tr></thead><tbody>'+s.entries.map(e=>{
  const r=resolved.get(e.id),locked=s.locked_through_year!==null&&e.year<=s.locked_through_year;
  return '<tr data-expense-id="'+esc(e.id)+'"><td>'+e.year+'／'+categories[e.category]+'<small>'+esc(e.title||'未另填說明')+'</small></td><td>'+money(e.amount_twd)+'<small>'+(e.basis==='real_2026'?'2026年固定購買力':e.price_year+'年名目金額')+'</small></td><td>'+(r?money(r.real_2026_twd)+'<small>2026購買力；'+(r.conversion_source==='EXPLICIT_INFLATION_SCENARIO'?'使用通膨情境':'使用已存基準')+'</small>':'退休起點確定後換算')+'</td><td>'+(locked?'已核准年度・唯讀':'<button type="button" class="dash-text-link" data-expense-edit="'+esc(e.id)+'">修改</button> <button type="button" class="danger-link" data-expense-delete="'+esc(e.id)+'">刪除</button>')+'</td></tr>';
 }).join('')+'</tbody></table>';
}
// One read-only annual display, never a second editable expense source.
// Before any plan exists, CPI inputs are needed for an exact current-year
// nominal preview; otherwise show "pending", not a fictitious TWD total.
function updateYearSummary(){
 const out=$('expense-year-summary'),note=$('expense-year-summary-note');
 if(!out||!note)return;
 const last=state?.years?.at(-1);
 const year=Number($('decision_date')?.value?.slice(0,4));
 const schedule=state?.expense_schedule;
 if(!Number.isInteger(year)||year<2026||!schedule){
  out.textContent='請先確認決策年度';note.textContent='尚未有可彙總的排程資料。';return;
 }
 const entries=schedule.entries.filter(e=>e.year===year);
 const approved=state?.years?.find(y=>y.year===year);
 // Old snapshots may contain a historical "ad_hoc_twd". Never silently
 // migrate, delete, rewrite or add that amount a second time.
 if(approved){
  const details=approved.large_expense_sources;
  const legacy=details?.items?.filter(x=>x.id==='annual-ad-hoc')||[];
  const scheduled=details?.items?.filter(x=>x.id!=='annual-ad-hoc')||[];
  if(details?.status==='RECONCILED'){
   out.textContent=twMoney(scheduled.reduce((v,x)=>v+x.total_twd,0));
   note.textContent='已核准 '+year+' 年排程 '+scheduled.length+' 筆（使用核准時快照，唯讀）。'+
    (legacy.length?'另有舊版年度臨時費用 '+twMoney(legacy.reduce((v,x)=>v+x.total_twd,0))+'，僅保留原核准紀錄，不再提供新增入口。':'政策定期換車及一般生活費另計。');
  }else{
   out.textContent='核准明細待核對';
   note.textContent='既有核准結果保持不變；不能由現在的排程猜測當年的資金來源。';
  }
  return;
 }
 if(!entries.length){
  out.textContent=twMoney(0);
  note.textContent=year+' 年尚無手動大額支出排程；政策定期換車另計。新增請使用下方唯一入口。';return;
 }
 const resolved=new Map((schedule.resolved||[]).map(x=>[x.id,x]));
 const base=Number(state?.plan?.cpi_2026??$('cpi_2026').value);
 const decision=Number($('decision_cpi').value);
 const hasCpi=Number.isFinite(base)&&base>0&&
              Number.isFinite(decision)&&decision>0&&
              $('cpi_2026').value!==''&&$('decision_cpi').value!=='';
 const rate=1+Number(schedule.inflation_pct)/100;
 const amounts=entries.map(e=>{
  const r=resolved.get(e.id);
  if(r&&Number.isFinite(Number(r.nominal_due_twd)))return Number(r.nominal_due_twd);
  if(e.basis==='nominal_year'&&e.price_year===year)return Number(e.amount_twd);
  if(!hasCpi||!Number.isFinite(rate)||rate<=0)return null;
  if(e.basis==='real_2026'||e.price_year===2026)return Number(e.amount_twd)*decision/base;
  return Number(e.amount_twd)/Math.pow(rate,e.price_year-year);
 });
 if(amounts.some(x=>x===null||!Number.isFinite(x)||x<0)){
  out.textContent=entries.length+' 筆，金額待換算';
  note.textContent='需先有一致的2026 CPI基準及本年決策 CPI，才能換算不同物價基準的合計。排程已保存，不會遺失。';return;
 }
 const total=amounts.reduce((a,b)=>a+b,0);
 out.textContent=twMoney(total);
 note.textContent='共 '+entries.length+' 筆，'+year+' 年名目金額'+
   (state?.plan?'（依已保存CPI及通膨情境推估，須以核准時計算為準）':'（依目前輸入的CPI／通膨情境預覽，尚未核准）')+
   '；政策定期換車及生活費另計。不需在上方再次輸入。';
}
function holdingRow(value={}){
 const el=document.createElement('fieldset');el.className='execution-holding';
 const field=(label,k,type,placeholder,extra='')=>'<label class="field"><span>'+label+'</span><input data-holding="'+k+'" type="'+type+'" '+extra+' placeholder="'+placeholder+'" required/></label>';
 el.innerHTML='<legend>人工持倉與報價</legend><div class="grid-form">'+field('證券／ETF代號','ticker','text','例如：VWRA','maxlength="32"')+field('券商／帳戶識別','broker','text','例如：券商A','maxlength="60"')+
 '<label class="field"><span>資產分類</span><select data-holding="sleeve"><option value="stock">股票</option><option value="bond">債券</option></select></label><label class="field"><span>報價幣別</span><select data-holding="currency"><option value="USD">USD</option><option value="TWD">TWD</option></select></label>'+
 field('持有股數','units','number','例如：100.25','min="0" step="any"')+field('每股報價','price','number','例如：192.90','min="0.000001" step="any"')+field('最小交易單位','lot_step','number','例如：1或0.001','min="0.000001" step="any"')+field('報價日期','quote_date','date','請填報價日期')+'</div><button type="button" class="danger-link" data-remove-holding>移除此筆持倉</button>';
 for(const input of el.querySelectorAll('[data-holding]'))if(value[input.dataset.holding]!==undefined)input.value=value[input.dataset.holding];
 $('execution-holdings').appendChild(el);return el;
}
function planningRender(){
 const y=state?.years?.at(-1),pending=y&&!y.closing;
 $('execution-planning-form').classList.toggle('hidden',!pending);
 if(!pending){$('execution-funding-summary').textContent=y?'該年度已結算；下一年度核准後再規劃出售。':'請先核准年度預算，再提供人工持倉及報價。';$('expense-current-sources').replaceChildren();$('execution-planning-result').replaceChildren();hydrated=null;planning=null;return;}
 const src=y.withdrawal_sources,details=y.large_expense_sources;
 if(src.status!=='RECONCILED'){$('execution-funding-summary').textContent=src.warning;$('execution-planning-form').classList.add('hidden');return;}
 $('execution-funding-summary').innerHTML='<p><strong>投資池所需流動資金：</strong>'+money(src.total.invest_twd+src.cash_refill_transfer_twd)+'（支出 '+money(src.total.invest_twd)+'＋現金補回轉帳 '+money(src.cash_refill_transfer_twd)+'）。<strong>安全現金預留支出：</strong>'+money(src.total.cash_twd)+'。</p><p>生活費橋接 '+money(src.bridge_twd)+' 已包含在來源合計；核准預留後安全現金 '+money(src.cash_after_approval_twd)+'，Emergency保護額參考 '+money(src.emergency_reserve_reference_twd)+'。'+(details?.cash_below_emergency_reference?'必要支付後現金低於Emergency參考額，請核對後續安排。':'')+'</p>';
 const split=x=>'<tr><td>'+esc(x.label)+'</td><td>'+money(x.invest_twd)+'</td><td>'+money(x.cash_twd)+'</td><td>'+money(x.total_twd)+'</td></tr>';
 $('expense-current-sources').innerHTML=details?.items.length?'<table><caption>本年度排程與另列支出的預留來源</caption><thead><tr><th>項目</th><th>投資池</th><th>安全現金</th><th>合計</th></tr></thead><tbody>'+details.items.map(split).join('')+'</tbody></table>':'本年度沒有手動排程或另列支出；生活費及政策換車請查看上方資金來源表。';
 if(hydrated!==y.approval_id){
  hydrated=y.approval_id;planning=null;$('execution-holdings').replaceChildren();
  for(const id of ['execution-asof','execution-fx','execution-broker-cash','execution-fee'])$(id).value='';
  const saved=state.execution_plans?.[y.approval_id]?.input;
  if(saved){for(const [id,k] of [['execution-asof','asof_date'],['execution-fx','fx_twd_per_usd'],['execution-broker-cash','broker_cash_twd'],['execution-fee','fee_estimate_twd']])$(id).value=saved[k]??'';saved.holdings.forEach(holdingRow);}
  else holdingRow();
 }
 drawPlanning();
}
function drawPlanning(){
 if(!planning){$('execution-planning-result').textContent='尚未計算出售候選。儲存的人工規劃可隨JSON備份還原，年度預算與資產餘額不會因此改變。';return;}
 const p=planning;
 $('execution-planning-result').innerHTML='<p class="phase2-warning">'+esc(p.warning)+'</p><p><strong>'+(p.status==='INSUFFICIENT_QUOTED_HOLDINGS'?'可出售持倉不足，仍有缺口':'人工出售候選已計算，仍待券商核對')+'</strong>；估計出售總額 '+money(p.estimated_gross_sell_twd)+'、費用 '+money(p.estimated_fees_twd)+'、淨額 '+money(p.estimated_net_sell_twd)+'、流動資金缺口 '+money(p.liquidity_shortfall_twd)+'。</p><p>人工持倉＋券商現金與年度起始投資額差額：'+money(p.difference_from_opening_investment_twd)+'；請核對時點與完整持倉。'+(!p.fee_estimate_provided?'費稅尚未填寫，不能當成零費用交易。':'')+'</p><table><caption>出售候選（不是已下單交易）</caption><thead><tr><th>ETF／帳戶</th><th>持有股數</th><th>候選出售股數</th><th>估計新台幣金額</th></tr></thead><tbody>'+p.orders.map(h=>'<tr><td>'+esc(h.ticker)+'<small>'+esc(h.broker)+'／'+h.currency+'／'+(h.sleeve==='stock'?'股票':'債券')+'</small></td><td>'+h.units+'</td><td>'+h.sell_units+'</td><td>'+money(h.sell_units*h.price_twd)+'</td></tr>').join('')+'</tbody></table><p>整股／零股取整後餘裕 '+money(p.rounding_excess_twd)+'；證券出售後股票占比估計 '+(p.estimated_after_stock_weight===null?'未提供持倉或無剩餘證券':pct(p.estimated_after_stock_weight))+'，目標 '+pct(p.target_stock_weight)+'。</p><p><strong>仍待核對：</strong>'+p.pending_checks.map(esc).join('；')+'。</p>';
}
function finish(){worker?.terminate();worker=null;clearTimeout(timer);timer=null;running=false;runKey=null;$('expense-compare-run').disabled=false;$('expense-compare-cancel').classList.add('hidden');}
function compareStatus(message,mode){$('expense-compare-status').textContent=message;$('expense-compare-status').dataset.state=mode;}
function cancel(message='研究已取消，年度核准與結算均未改變。'){sequence++;finish();compareStatus(message,'cancelled');}
function drawComparison(){
 if(!comparison)return;
 const rows=comparison.rows,age=x=>x===null?'尚無缺口':Number(x).toFixed(1)+'歲';
 $('expense-comparison-result').innerHTML='<p class="phase2-warning">'+esc(comparison.note)+'</p><table><caption>同起點、同路徑研究比較（至104歲；不是全球市場認證）</caption><thead><tr><th>配置／手動排程</th><th>完整計畫</th><th>終生Floor＋必要支出</th><th>首次Floor／必要缺口年齡P50</th><th>首個缺口金額P50／P90</th><th>首缺口年度付款前／後安全現金P50</th></tr></thead><tbody>'+rows.map(r=>{const d=r.diagnostics;return '<tr><td>'+r.stock_bond+'<small>'+(r.scheduled_expenses_included?'含手動排程':'不含手動排程')+'</small></td><td>'+pct(d.plan_success)+'</td><td>'+pct(d.floor_and_required_success)+'<small>單側95%下界 '+pct(d.floor_and_required_success_wilson_lower_95)+'</small></td><td>'+age(d.first_floor_age_p50)+'／'+age(d.first_mandatory_age_p50)+'</td><td>'+money(d.first_gap_amount_median_real2026_twd)+'／'+money(d.first_gap_amount_p90_real2026_twd)+'</td><td>'+money(d.first_gap_cash_before_median_real2026_twd)+'／'+money(d.first_gap_cash_after_median_real2026_twd)+'</td></tr>';}).join('')+'</tbody></table><p>年齡、缺口金額與缺口時現金的百分位數只以發生對應缺口的路徑為分母，金額是第一個缺口當年的不足，不是終生累計；全部為2026購買力。原政策定期換車、本年排程以外支出、Emergency、橋接與補回均保留。</p>';
 $('expense-compare-export').classList.remove('hidden');
}
async function compare(){
 if(running)return;if(!state?.years?.length){compareStatus('請先核准年度預算。','error');return;}
 const current=key(),generation=++sequence;runKey=current;running=true;$('expense-compare-run').disabled=true;$('expense-compare-cancel').classList.remove('hidden');compareStatus('正在準備成對研究，年度帳本可繼續使用。','running');
 const higher=$('mc-precision').value==='higher';timer=setTimeout(()=>cancel('計算逾時，已停止唯讀研究；請改用快速模式。'),higher?300000:240000);
 try{
  const exported=await request('/api/export');if(generation!==sequence)return;if(key()!==current){cancel('排程或年度已變更，請重新研究。');return;}
  worker=new Worker('./pyodide-worker.js',{name:'B85-readonly-expense-comparison'});
  worker.onerror=()=>{if(generation===sequence){finish();compareStatus('研究環境載入失敗，請稍後重試。','error');}};
  worker.onmessage=e=>{
   if(generation!==sequence)return;const m=e.data;
   if(m.type==='progress'){compareStatus(m.message,'running');return;}
   if(m.type==='simulation-progress'){compareStatus('正在比較四組路徑：'+m.done+'／'+m.total+'年度，可取消。','running');return;}
   if(m.type!=='result')return;
   if(!m.ok){finish();compareStatus(m.error,'error');return;}
   if(m.id===1){worker.postMessage({id:2,op:'expense-comparison',data:{paths:higher?8192:2048,inner_paths:higher?2048:512}});return;}
   finish();if(key()!==current){compareStatus('資料已變更，結果未套用。','stale');return;}
   comparison=m.data;comparisonKey=current;drawComparison();compareStatus('成對研究完成：'+comparison.paths+'條同市場／Emergency路徑，各比較兩種配置；不改已核准年度。','complete');
  };
  worker.postMessage({id:1,op:'init',data:{saved:JSON.stringify(exported.payload)}});
 }catch(e){if(generation===sequence){finish();compareStatus(e.message,'error');}}
}
function render(){
 const current=key();if(lastKey&&lastKey!==current){
  if(!state?.plan&&state?.expense_schedule?.revision===0&&!state.expense_schedule.entries.length){
   clearEditor();hydrated=null;planning=null;$('execution-holdings').replaceChildren();
   for(const id of ['execution-asof','execution-fx','execution-broker-cash','execution-fee','expense-inflation'])$(id).value='';
  }
  if(running)cancel('排程或年度已更新，研究已取消。');
  if(comparison&&comparisonKey!==current){comparison=null;$('expense-comparison-result').replaceChildren();$('expense-compare-export').classList.add('hidden');compareStatus('排程或年度已更新，請重新研究。','stale');}
 }
 lastKey=current;scheduleRender();planningRender();updateYearSummary();
}
$('expense-basis').addEventListener('change',basis);$('expense-cancel-edit').addEventListener('click',clearEditor);
$('expense-schedule-form').addEventListener('submit',async e=>{e.preventDefault();const button=$('expense-save');button.disabled=true;
 try{await mutation('upsert',{id:editId,year:$('expense-year').value,category:$('expense-category').value,amount_twd:$('expense-amount').value,basis:$('expense-basis').value,price_year:$('expense-basis').value==='nominal_year'?$('expense-price-year').value:null,title:$('expense-title-input').value});clearEditor();flash('排程已保存。新年度PoS與未來模擬會納入；既有核准不回溯改算。','success');}
 catch(err){flash(err.message);}finally{button.disabled=false;}});
$('expense-schedule-list').addEventListener('click',async e=>{const edit=e.target.closest('[data-expense-edit]'),remove=e.target.closest('[data-expense-delete]');
 if(edit){const v=state.expense_schedule.entries.find(x=>x.id===edit.dataset.expenseEdit);if(!v)return;editId=v.id;for(const [id,k] of [['expense-year','year'],['expense-category','category'],['expense-amount','amount_twd'],['expense-basis','basis'],['expense-price-year','price_year'],['expense-title-input','title']])$(id).value=v[k]??'';basis();$('expense-save').textContent='保存修改';$('expense-cancel-edit').classList.remove('hidden');$('expense-year').focus();}
 if(remove){try{await mutation('delete',{id:remove.dataset.expenseDelete});if(editId===remove.dataset.expenseDelete)clearEditor();flash('未來支出已刪除，既有核准快照保留。','success');}catch(err){flash(err.message);}}
});
$('expense-inflation-save').addEventListener('click',async()=>{if($('expense-inflation').value===''){flash('請填換算通膨情境。');return;}try{await mutation('inflation',{inflation_pct:$('expense-inflation').value});flash('支出換算情境已保存，不回溯修改已核准預算。','success');}catch(e){flash(e.message);}});
$('execution-add-holding').addEventListener('click',()=>{if($('execution-holdings').children.length>=40){flash('最多40筆持倉。');return;}holdingRow();planning=null;drawPlanning();});
$('execution-holdings').addEventListener('click',e=>{if(e.target.closest('[data-remove-holding]')){e.target.closest('.execution-holding').remove();planning=null;drawPlanning();}});
$('execution-planning-form').addEventListener('input',()=>{planning=null;drawPlanning();});
$('execution-planning-form').addEventListener('submit',async e=>{e.preventDefault();const button=$('execution-calculate');button.disabled=true;
 try{const data={approval_id:state.years.at(-1).approval_id,asof_date:$('execution-asof').value,fx_twd_per_usd:$('execution-fx').value,broker_cash_twd:$('execution-broker-cash').value,fee_estimate_twd:$('execution-fee').value,holdings:[...$('execution-holdings').children].map(el=>Object.fromEntries([...el.querySelectorAll('[data-holding]')].map(input=>[input.dataset.holding,input.value])))};
  const r=await request('/api/execution-plan',data);planning=r.planning;await refresh();flash('人工出售候選已保存；沒有下單、轉帳或付款，年度資產未變動。','success');
 }catch(err){flash(err.message);}finally{button.disabled=false;}});
$('expense-compare-run').addEventListener('click',compare);$('expense-compare-cancel').addEventListener('click',()=>cancel());
$('expense-compare-export').addEventListener('click',()=>{if(!comparison)return;const url=URL.createObjectURL(new Blob([JSON.stringify(comparison,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='B85_大額支出成對研究_'+comparison.start_year+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);});
$('expense-jump-to-schedule').addEventListener('click',()=>$('phase2-schedule-panel').scrollIntoView({behavior:'smooth',block:'start'}));
window.B85_PHASE2=Object.freeze({render,updateYearSummary,getComparison:()=>comparison,getPlanning:()=>planning,isComparing:()=>running});basis();
})();
