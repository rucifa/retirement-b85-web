/* Public B+85 dashboard presentation. Never calculates policy results or stores user data. */
(function(){
'use strict';
const $=id=>document.getElementById(id);
const fmt=n=>new Intl.NumberFormat('zh-TW',{maximumFractionDigits:0}).format(Math.round(n));
const money=n=>'NT$ '+fmt(n);
const fine=n=>Number.isFinite(Number(n))&&Number(n)>=0;
const clamp=(x,min,max)=>Math.max(min,Math.min(max,x));
const safe=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stateRead=()=>{
 try{return typeof state!=='undefined'&&state&&Array.isArray(state.years)?state:null;}
 catch{return null;}
};
const text=(id,value)=>{const el=$(id);if(el)el.textContent=String(value);};
function lastAnnual(){
 const s=stateRead();return s?.years?.length?s.years[s.years.length-1]:null;
}
// Read the model's already CPI-converted nominal annual floor reference.
// Only the FIRST retirement year gets calendar proration; future years remain full-year.
// This is a read-only comparison, never an input to the B+85 annual engine.
function compareAnnualLivingBudget(year){
 const positiveAmount=x=>x!==null&&x!==undefined&&x!==''&&Number.isFinite(Number(x))&&Number(x)>=0;
 if(!year||!positiveAmount(year.floor_reference_twd)||!positiveAmount(year.living_authorized_twd))return null;
 const fullYearFloor=Number(year.floor_reference_twd);
 if(fullYearFloor<=0)return null;
 const fraction=year.calendar_first_year?Number(year.calendar_fraction):1;
 if(!Number.isFinite(fraction)||fraction<=0||fraction>1)return null;
 const minimum=Math.round(fullYearFloor*fraction);
 if(minimum<=0)return null;
 const recommended=Math.round(Number(year.living_authorized_twd));
 const difference=recommended-minimum;
 return {minimum,recommended,difference,pct:Math.round(Math.abs(difference)/minimum*1000)/10,
  fraction,prorated:!!year.calendar_first_year};
}
// Read-only presentation helper for deterministic UI regression tests.
window.B85_BUDGET_COMPARISON=Object.freeze({compare:compareAnnualLivingBudget});
function updateKpis(){
 const s=stateRead(),y=lastAnnual(),years=s?.years||[];
 const comparison=compareAnnualLivingBudget(y);
 text('dash-budget',y&&Number.isFinite(Number(y.living_authorized_twd))?money(Number(y.living_authorized_twd)):'尚未試算');
 text('dash-budget-sub',y?(y.calendar_first_year?
  y.year+' 年首年 '+y.calendar_days+'/'+y.calendar_year_days+' 天・按日計算':
  y.year+' 年全年生活費・依 B＋85 計算')+'（不含換車與額外支出）':
  '依輸入資產與 B＋85 模型試算');
 text('dash-minimum',comparison?money(comparison.minimum):'待試算');
 text('dash-minimum-sub',comparison?
  (comparison.prorated?y.year+' 年首年 '+y.calendar_days+'/'+y.calendar_year_days+' 天':'本年度全年')+'・已換算當年物價':
  '試算後按相同期間與物價換算');
 const differenceCard=$('dash-difference-card');
 let stateLabel='pending',title='與最低需求相比',value='待試算',explanation='完成試算後顯示可增加的預算或缺口';
 if(comparison){
  const delta=comparison.difference;
  if(delta>0){stateLabel='surplus';title='比最低需求多出的生活費';value='＋'+money(delta);
   explanation='同期間多 '+comparison.pct.toFixed(1)+'%・僅今年預算，不代表往後都能增加';}
  else if(delta<0){stateLabel='shortfall';title='距離最低生活需求的缺口';value='−'+money(Math.abs(delta));
   explanation='低於最低需求 '+comparison.pct.toFixed(1)+'%・請重新檢視資產與生活費';}
  else{stateLabel='equal';title='與最低生活需求相當';value='NT$ 0';
   explanation='同期間相等，無額外生活費空間';}
 }
 if(differenceCard)differenceCard.dataset.state=stateLabel;
 text('dash-difference-title',title);
 text('dash-difference',value);
 text('dash-difference-sub',explanation);
 text('dash-pos',y&&Number.isFinite(Number(y.pos_pct))?Number(y.pos_pct).toFixed(1)+'%':'—');
 text('dash-pos-sub',y?'完整年度模型參考值（非首年短期間保證）':'完整年度模型參考值，非保證');
 text('dash-years',years.length+' 年');
 text('dash-years-sub',years.length?'最早 '+years[0].year+' 年 · 最新 '+years[years.length-1].year+' 年':'僅保存在此瀏覽器');
 text('dash-policy-status',y?'已計算 '+y.year+' 年預算；'+(y.b85_restored?'符合 B＋85 恢復條件。':'以當年的 Guardrail／Sticky 結果為準。'):'目前尚無核准年度；請先執行年初試算。');
 const history=$('dash-recent-years');
 if(history){
  history.replaceChildren();
  if(!years.length)history.textContent='尚無已保存年度。年初核准後才會建立本機紀錄。';
  for(const y of [...years].reverse().slice(0,4)){
   const row=document.createElement('div');
   row.className='dash-recent-row';
   const year=document.createElement('strong');
   year.textContent=y.year+' 年・'+y.age+' 歲';
   const meta=document.createElement('span');
   meta.textContent=y.closing?'年末已結算':'待年末結算';
   row.append(year,meta);history.append(row);
  }
 }
 drawHistory(years);
 updateGuardrail(y);
 drawScenario(y);
 updateChartMode(y,years);
}
function drawHistory(years){
 const box=$('dash-asset-chart');if(!box)return;
 const closed=(years||[]).filter(y=>y&&y.closing&&fine(y.closing.investment_end_twd)&&fine(y.closing.cash_end_twd))
   .map(y=>({year:Number(y.year),value:(Number(y.closing.investment_end_twd)+Number(y.closing.cash_end_twd))/10000}));
 if(!closed.length){
  box.textContent='目前尚無已結算年度；完成年末結算後，這裡會顯示實際資產走勢。未來蒙地卡羅情境尚未整合，不顯示虛構預測曲線。';
  box.setAttribute('aria-label','尚無可繪製的已結算年度資產資料');
  return;
 }
 const w=640,h=205,l=62,r=18,t=18,b=39,plotW=w-l-r,plotH=h-t-b;
 const top=Math.max(1,...closed.map(x=>x.value))*1.12;
 const bottom=0;
 const xy=closed.map((d,i)=>({
  x:l+(closed.length===1?plotW/2:i*plotW/(closed.length-1)),
  y:t+plotH-(d.value-bottom)/(top-bottom)*plotH,
  ...d
 }));
 let svg='<svg viewBox="0 0 '+w+' '+h+'" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="歷年已結算投資與現金合計市值趨勢">';
 for(let i=0;i<=4;i++){
  const yy=t+i*plotH/4;
  const amt=(top*(4-i)/4);
  svg+='<line x1="'+l+'" y1="'+yy+'" x2="'+(w-r)+'" y2="'+yy+'" stroke="#dce9ee" stroke-width="1"/>'+
  '<text x="'+(l-9)+'" y="'+(yy+4)+'" font-size="11" fill="#7b94a0" text-anchor="end">'+safe(fmt(amt))+'</text>';
 }
 const path=xy.map((p,i)=>(i?'L':'M')+p.x.toFixed(2)+' '+p.y.toFixed(2)).join(' ');
 if(xy.length>1)svg+='<path d="'+path+'" fill="none" stroke="#129a8c" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>';
 for(const p of xy){
  svg+='<circle cx="'+p.x+'" cy="'+p.y+'" r="4.5" fill="#0b8d84" stroke="#fff" stroke-width="2"><title>'+safe(p.year)+'：'+safe(fmt(p.value))+' 萬元</title></circle>'+
  '<text x="'+p.x+'" y="'+(h-12)+'" text-anchor="middle" font-size="11" fill="#617e90">'+safe(p.year)+'</text>';
 }
 svg+='<text x="'+(l-9)+'" y="12" text-anchor="end" font-size="10" fill="#638596">萬元</text></svg>';
 box.innerHTML=svg;
 box.setAttribute('aria-label','已結算年度資產合計：'+closed.map(x=>x.year+'年 '+fmt(x.value)+' 萬元').join('，'));
}
function trend(records){
 const box=$('dash-cpi-trend');if(!box)return;
 const year=String(records?.at(-1)?.month||'').slice(0,4);
 const rows=(records||[]).filter(r=>String(r.month).startsWith(year)&&/^\d{4}-(0[1-9]|1[0-2])$/.test(String(r.month))&&Number.isFinite(Number(r.official_yoy_pct))).
  slice(0,12).map(r=>({...r,yoy:Number(r.official_yoy_pct)}));
 if(rows.length<2){
  box.textContent='官方快照可比較的月度資料不足，暫不繪製 CPI 年增率曲線。';
  return;
 }
 const vals=rows.map(r=>r.yoy),low=Math.min(...vals)-.6,high=Math.max(...vals)+.6;
 const w=390,h=135,l=34,r=10,t=17,b=24,pw=w-l-r,ph=h-t-b;
 const points=rows.map((v,i)=>({x:l+i*pw/(rows.length-1),y:t+(high-v.yoy)/(high-low)*ph,...v}));
 let html='<p>今年 1 月至最近的 CPI 同月年增率（%）｜來源見資料點說明</p>';
 let svg='<svg viewBox="0 0 '+w+' '+h+'" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="已公布月度 CPI 年增率走勢">';
 for(let i=0;i<3;i++){
   const y=t+i*ph/2,axis=high-(high-low)*i/2;
   svg+='<line x1="'+l+'" x2="'+(w-r)+'" y1="'+y+'" y2="'+y+'" stroke="#e1edf0"/>'+
   '<text x="'+(l-5)+'" y="'+(y+4)+'" text-anchor="end" fill="#7894a1" font-size="10">'+safe(axis.toFixed(1))+'</text>';
 }
 for(let i=1;i<points.length;i++){
  const a=points[i-1],b=points[i];
  svg+='<path d="M'+a.x.toFixed(1)+' '+a.y.toFixed(1)+' L'+b.x.toFixed(1)+' '+b.y.toFixed(1)+'" fill="none" stroke="#168f9d" stroke-width="2.4"/>';
 }
 for(const p of points){
  const cx=p.x.toFixed(1),cy=p.y.toFixed(1);
  const origin=p.origin==='OFFICIAL_HISTORICAL_INDEX_DERIVED'?'歷史指數計算值':'官方公告';
  const rate=(p.yoy>=0?'+':'')+p.yoy.toFixed(2)+'%';
  svg+='<circle cx="'+cx+'" cy="'+cy+'" r="3.1" fill="#0b9a8d" aria-hidden="true"/>'+
   '<circle class="cpi-point-hit" cx="'+cx+'" cy="'+cy+'" r="12" fill="transparent" tabindex="0" role="button" aria-label="'+safe(p.month+' 年增率 '+rate+' '+origin)+'" data-month="'+safe(p.month)+'" data-rate="'+safe(rate)+'" data-origin="'+safe(origin)+'"><title>'+safe(p.month+' 年增率 '+rate+' '+origin)+'</title></circle>';
 }
 svg+='<text x="'+l+'" y="'+(h-6)+'" font-size="10" fill="#678496">'+safe(rows[0].month)+'</text>'+
 '<text x="'+(w-r)+'" y="'+(h-6)+'" font-size="10" text-anchor="end" fill="#678496">'+safe(rows.at(-1).month)+'</text></svg>';
 html+=svg+'<div class="cpi-hover-tooltip" role="status" aria-live="polite" hidden></div>';
 box.innerHTML=html;
}
const cpiTrend=$('dash-cpi-trend');
function cpiPointDetails(point){
 const tip=cpiTrend?.querySelector('.cpi-hover-tooltip');
 if(!tip||!point)return;
 const month=point.dataset.month,rate=point.dataset.rate,origin=point.dataset.origin;
 if(!/^\d{4}-\d{2}$/.test(month)||!/^[+-]?\d+(?:\.\d+)?%$/.test(rate))return;
 tip.textContent=month.replace('-',' 年 ')+' 月　年增率 '+rate+'｜'+origin;
 tip.hidden=false;
 const rect=cpiTrend.getBoundingClientRect(),dot=point.getBoundingClientRect();
 const x=dot.left+dot.width/2-rect.left,y=dot.top-rect.top;
 tip.style.left=Math.max(88,Math.min(Math.max(88,rect.width-88),x))+'px';
 tip.style.top=Math.max(7,y-13)+'px';
}
function hideCpiPointDetails(){
 const tip=cpiTrend?.querySelector('.cpi-hover-tooltip');
 if(tip)tip.hidden=true;
}
if(cpiTrend){
 cpiTrend.addEventListener('pointerover',e=>{
  const point=e.target.closest?.('.cpi-point-hit');if(point)cpiPointDetails(point);
 });
 cpiTrend.addEventListener('pointerout',e=>{
  if(e.target.closest?.('.cpi-point-hit'))hideCpiPointDetails();
 });
 cpiTrend.addEventListener('focusin',e=>{
  const point=e.target.closest?.('.cpi-point-hit');if(point)cpiPointDetails(point);
 });
 cpiTrend.addEventListener('focusout',e=>{
  if(e.target.closest?.('.cpi-point-hit'))hideCpiPointDetails();
 });
}

/* Policy signals come only from the saved B+85 annual result. */
function updateGuardrail(y){
 const ring=$('dash-policy-ring'),num=$('dash-guardrail-pos');
 const status=$('dash-policy-status'),detail=$('dash-guardrail-breakdown');
 const levels=[...document.querySelectorAll('[data-guardrail-zone]')];
 levels.forEach(el=>{el.classList.remove('active');el.removeAttribute('aria-current');});
 if(!ring||!num||!status||!detail)return;
 const valid=!!(y&&fine(y.pos_pct));
 ring.style.setProperty('--dash-pos-stop',valid?clamp(Number(y.pos_pct),0,100)+'%':'0%');
 num.textContent=valid?Number(y.pos_pct).toFixed(1)+'%':'—';
 if(!valid){
  status.textContent='尚未核准年度：依 B＋85 模型 PoS 判定減支／維持／增支。';
  status.dataset.state='pending';
  detail.textContent='核准後將顯示正常生活費、Guardrail 全年額度與首年按日換算結果。';
  return;
 }
 const pos=Number(y.pos_pct);
 const action=y.guardrail_action||(y.b85_restored?'B85_RESTORED':pos<=75?'CUT_10_PERCENT':pos>=95?'RAISE_10_PERCENT':'HOLD');
 const zone=action==='CUT_10_PERCENT'?'cut':action==='RAISE_10_PERCENT'?'raise':'hold';
 const el=levels.find(x=>x.dataset.guardrailZone===zone);
 if(el){el.classList.add('active');el.setAttribute('aria-current','true');}
 status.dataset.state=zone;
 const changes={
  CUT_10_PERCENT:'PoS '+pos.toFixed(1)+'% ≤ 75%，已觸發本年度 Sticky 減支 10%。',
  HOLD:'PoS '+pos.toFixed(1)+'%，位於 75%～95% 之間，維持原 Sticky 生活預算。',
  RAISE_10_PERCENT:'PoS '+pos.toFixed(1)+'% ≥ 95%，已觸發本年度 Sticky 增支 10%（仍有上限）。',
  B85_RESTORED:'符合 B＋85 恢復條件，Sticky 恢復至正常額度。'
 };
 status.textContent=changes[action]||'本年度依 B＋85 政策 Guardrail／Sticky 規則核准。';
 detail.replaceChildren();
 const rows=[];
 if(fine(y.normal_reference_twd))rows.push(['正常生活費參考（全年）',money(Number(y.normal_reference_twd))]);
 const full=fine(y.full_year_living_reference_twd)?Number(y.full_year_living_reference_twd):
  (fine(y.living_authorized_twd)?Number(y.living_authorized_twd):null);
 if(full!==null)rows.push(['Guardrail 後全年額度',money(full)]);
 if(y.calendar_first_year&&fine(y.calendar_fraction))rows.push([
  '首年按日換算（'+y.calendar_days+'/'+y.calendar_year_days+' 天）',
  money(Number(y.living_authorized_twd))
 ]);
 else if(fine(y.living_authorized_twd))rows.push(['本年核准生活費',money(Number(y.living_authorized_twd))]);
 if(!rows.length){detail.textContent='舊年度紀錄缺少核准金額，請重新核對資料來源。';return}
 for(let i=0;i<rows.length;i++){
  const line=document.createElement('div');line.className='dash-step'+(i===rows.length-1?' final':'');
  const label=document.createElement('span');label.textContent=rows[i][0];
  const number=document.createElement('strong');number.textContent=rows[i][1];
  line.append(label,number);detail.append(line);
 }
}
let assetMode='actual',assetModeChanged=false;
function updateChartMode(y,years){
 if(!assetModeChanged)assetMode=(y&&!years.some(x=>!!x.closing))?'scenarios':'actual';
 const scenario=assetMode==='scenarios';
 const history=$('dash-asset-chart'),pane=$('dash-scenario-pane');
 if(!history||!pane)return;
 history.classList.toggle('hidden',scenario);
 pane.classList.toggle('hidden',!scenario);
 for(const [id,chosen] of [['dash-actual-tab',!scenario],['dash-scenario-tab',scenario]]){
  const btn=$(id);if(!btn)continue;
  btn.classList.toggle('selected',chosen);
  btn.setAttribute('aria-pressed',chosen?'true':'false');
 }
}
for(const [id,mode] of [['dash-actual-tab','actual'],['dash-scenario-tab','scenarios']]){
 $(id)?.addEventListener('click',()=>{
  assetModeChanged=true;assetMode=mode;
  updateChartMode(lastAnnual(),stateRead()?.years||[]);
  if(mode==='scenarios')drawScenario(lastAnnual());
 });
}
for(const id of ['dash-return-low','dash-return-mid','dash-return-high']){
 $(id)?.addEventListener('input',()=>drawScenario(lastAnnual()));
}
function forecastScenario(y,annualPct){
 const annual=Number(y.full_year_living_reference_twd??y.living_authorized_twd);
 const first=Number(y.living_authorized_twd);
 const opening=Number(y.investment_open_twd)+Number(y.cash_open_twd);
 const firstShare=y.calendar_first_year?Number(y.calendar_fraction):1;
 if(!Number.isFinite(opening)||opening<=0||!Number.isFinite(annual)||annual<0||
    !Number.isFinite(first)||first<0||!Number.isFinite(firstShare)||firstShare<=0||firstShare>1)
   return [];
 const periods=clamp(104-Number(y.age),1,49);
 const points=[{year:Number(y.year),assets:opening/10000}];
 let total=opening;
 for(let i=0;i<periods;i++){
  const spending=i===0?first:annual;
  const fraction=i===0?firstShare:1;
  // Constant real total-asset return; NOT original B+85 market path, future
  // Guardrail, cash/stock split or dynamically recalculated cash bridge.
  total=Math.max(0,total-spending)*Math.pow(1+annualPct/100,fraction);
  if(!Number.isFinite(total))return [];
  points.push({year:Number(y.year)+i+1,assets:total/10000});
 }
 return points;
}
function drawScenario(y){
 const box=$('dash-scenario-chart');if(!box)return;
 if(!y){box.textContent='先完成年度試算，才能以實際起始資產建立三種假設對照。';return;}
 const names=[['dash-return-low','逆風'],['dash-return-mid','中性'],['dash-return-high','順風']];
 const rates=names.map(([id])=>Number($(id)?.value));
 if(rates.some((rate,i)=>!$(names[i][0])?.value||!Number.isFinite(rate)||rate< -99||rate>30)
      || !(rates[0]<rates[1]&&rates[1]<rates[2])){
  box.textContent='請輸入 −99%～＋30% 的實質年報酬假設，並保持逆風 ＜ 中性 ＜ 順風。';return;
 }
 const lines=rates.map(rate=>forecastScenario(y,rate));
 if(lines.some(line=>line.length<2)||lines[0].length!==lines[1].length){
  box.textContent='目前的年度資料不足以建立可核對的情境對照。';return;
 }
 const width=640,height=244,left=58,right=14,top=15,bottom=36;
 const plotW=width-left-right,plotH=height-top-bottom;
 const count=lines[0].length;
 const maximum=Math.max(100,...lines.flatMap(line=>line.map(p=>p.assets)))*1.06;
 const xx=i=>left+i/(count-1)*plotW;
 const yy=value=>top+(1-value/maximum)*plotH;
 const P=(line)=>line.map((p,i)=>(i?'L':'M')+xx(i).toFixed(2)+' '+yy(p.assets).toFixed(2)).join(' ');
 const lower=lines[0],upper=lines[2],middle=lines[1];
 const band=upper.map((p,i)=>xx(i).toFixed(2)+','+yy(p.assets).toFixed(2)).concat(
    [...lower].reverse().map((p,i)=>xx(count-1-i).toFixed(2)+','+yy(p.assets).toFixed(2))).join(' ');
 let svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+width+' '+height+'" role="img" aria-label="三組不同實質報酬假設的資產餘額，非機率分布或 B＋85 蒙地卡羅預測">';
 for(let i=0;i<=4;i++){
  const v=maximum*(1-i/4),yPx=top+plotH*i/4;
  svg+='<line x1="'+left+'" x2="'+(width-right)+'" y1="'+yPx+'" y2="'+yPx+'" stroke="#e2ecf0"/>'+
   '<text x="'+(left-7)+'" y="'+(yPx+4)+'" text-anchor="end" fill="#7b929c" font-size="11">'+safe(fmt(v))+'</text>';
 }
 svg+='<polygon points="'+band+'" fill="#c3dceb" opacity=".30"/>';
 const colors=['#d38d42','#159268','#4b9fda'];
 for(let k=0;k<3;k++){
  const line=lines[k];
  svg+='<path d="'+P(line)+'" stroke="'+colors[k]+'" fill="none" stroke-width="'+(k===1?3:2)+'" stroke-linejoin="round" '+(k===1?'':'stroke-dasharray="5 4"')+'/>';
  const at=Math.max(1,Math.floor(count/6));
  for(let i=0;i<count;i+=at){
   const p=line[i],v=fmt(p.assets);
   svg+='<circle cx="'+xx(i).toFixed(2)+'" cy="'+yy(p.assets).toFixed(2)+'" r="4" fill="'+colors[k]+'" stroke="#fff" stroke-width="1.5"><title>'+safe(String(p.year))+' 年 '+names[k][1]+'（'+(rates[k]>0?'+':'')+rates[k]+'%） '+safe(v)+' 萬元（固定報酬情境，非預測）</title></circle>';
  }
 }
 for(let i=0;i<count;i+=Math.max(1,Math.ceil((count-1)/5))){
  const yr=lines[0][i].year;
  svg+='<text x="'+xx(i).toFixed(2)+'" y="'+(height-11)+'" font-size="11" text-anchor="middle" fill="#6a8795">'+yr+'</text>';
 }
 svg+='<text x="'+(left-7)+'" y="10" font-size="10" text-anchor="end" fill="#698c99">萬元</text></svg>';
 box.innerHTML=svg;
}

async function loadOfficialSummary(){
 try{
  const progress=window.B85_RUNTIME_PROGRESS;
  if(progress)progress.setStage('cpi','loading',45,'正在驗證 GitHub 已公布的官方 CPI 快照');
  const response=await fetch('./data/cpi_verified.json',{cache:'no-store'});
  if(!response.ok)throw Error('HTTP '+response.status);
  const data=await response.json();
  if(data.schema_version!==1||!Array.isArray(data.records))throw Error('來源格式未通過檢查');
  const taiwan=window.B85_TAIWAN_TIME;
  if(!taiwan)throw Error('台灣時區模組未就緒');
  const today=taiwan.today(),maximumMonth=taiwan.prevMonth(today);
  const eligible=data.records.filter(r=>r.month<=maximumMonth&&r.publication_date<=today);
  const newest=eligible.at(-1);
  if(!newest)throw Error('目前沒有已發布的 CPI 公告');
  text('dash-cpi-month',newest.month.replace('-',' / '));
  text('dash-cpi-sub','最新官方公告年增率 '+(newest.official_yoy_pct>0?'+':'')+Number(newest.official_yoy_pct).toFixed(2)+'%');
  const yearData=Array.isArray(data.current_year_chart)?data.current_year_chart.filter(
    x=>x.month<=maximumMonth&&x.month.slice(0,4)===newest.month.slice(0,4)):[];
  trend(yearData.length?yearData.map(x=>({month:x.month,
    official_yoy_pct:x.yoy_pct,origin:x.origin})):eligible);
  if(progress)progress.setStage('cpi','ready',100,'已核對到 '+newest.month.replace('-',' / ')+' 的官方 CPI 公告資料。');

 }catch(e){
  text('dash-cpi-month','來源暫不可用');
  text('dash-cpi-sub','不會採用未查證的 CPI 數字');
  text('dash-cpi-trend','無法驗證官方 CPI 快照，請查看官方公告或稍後再試。');
  const progress=window.B85_RUNTIME_PROGRESS;
  if(progress)progress.setStage('cpi','failed',0,'官方 CPI 快照暫時無法驗證：'+(e?.message||'請稍後再試'));
 }
}
let queued=false;
function requestRefresh(){
 if(queued)return;
 queued=true;
 requestAnimationFrame(()=>{queued=false;updateKpis()});
}
for(const id of ['history-list','opening-result','closing-result']){
 const node=$(id);
 if(node)new MutationObserver(requestRefresh).observe(node,{childList:true,subtree:false});
}
const cpiNav=$('nav-cpi');
if(cpiNav)cpiNav.addEventListener('click',()=>{
 const btn=document.querySelector('[data-go="opening"]');
 if(btn)btn.click();
 const target=$('dashboard-cpi-card');
 if(target)requestAnimationFrame(()=>target.scrollIntoView({behavior:'smooth',block:'start'}));
});
updateKpis();
loadOfficialSummary();
})();