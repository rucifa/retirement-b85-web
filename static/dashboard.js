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
function updateKpis(){
 const s=stateRead(),y=lastAnnual(),years=s?.years||[];
 if(y&&fine(y.living_authorized_twd)){
  text('dash-budget',money(Number(y.living_authorized_twd)));
  text('dash-budget-sub',y.year+' 年・依 B＋85 計算（研究演練）');
 }else{
  text('dash-budget','尚未試算');
  text('dash-budget-sub','完成年初核准後顯示');
 }
 text('dash-pos',y&&fine(y.pos_pct)?Number(y.pos_pct).toFixed(1)+'%':'—');
 text('dash-pos-sub',y?'計算於 '+y.year+' 年（非保證）':'依 B＋85 政策計算');
 text('dash-years',years.length+' 年');
 text('dash-years-sub',years.length?'最早 '+years[0].year+' 年 · 最新 '+years[years.length-1].year+' 年':'僅保存在此瀏覽器');
 text('dash-policy-status',y?'已計算 '+y.year+' 年預算；'+(y.b85_restored?'符合 B＋85 恢復條件。':'以當年的 Guardrail／Sticky 結果為準。'):'目前尚無核准年度；請先執行年初試算。');
 const result=$('dash-recommend-body');
 if(result){
  result.replaceChildren();
  const heading=document.createElement('strong');
  heading.textContent=y&&fine(y.living_authorized_twd)?money(Number(y.living_authorized_twd)):'尚未產生建議';
  result.append(heading);
  const p=document.createElement('p');
  p.textContent=y?
   y.year+' 年已核准生活費 · '+(y.age||'—')+' 歲（研究演練）；不等於實際已提領金額。':
   '請填妥年度資料並執行年初核准，建議金額將直接採用 B＋85 計算結果。';
  result.append(p);
  if(y&&fine(y.pos_pct)){
   const note=document.createElement('p');
   note.className='dash-recommend-note';
   note.textContent='PoS '+Number(y.pos_pct).toFixed(1)+'% · 換車專項 '+(fine(y.car_authorized_twd)?money(Number(y.car_authorized_twd)):'未建立');
   result.append(note);
  }
 }
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
 const rows=(records||[]).filter(r=>/^\d{4}-(0[1-9]|1[0-2])$/.test(String(r.month))&&Number.isFinite(Number(r.official_yoy_pct))).
  slice(-12).map(r=>({...r,yoy:Number(r.official_yoy_pct)}));
 if(rows.length<2){
  box.textContent='官方快照可比較的月度資料不足，暫不繪製 CPI 年增率曲線。';
  return;
 }
 const vals=rows.map(r=>r.yoy),low=Math.min(...vals)-.6,high=Math.max(...vals)+.6;
 const w=390,h=135,l=34,r=10,t=17,b=24,pw=w-l-r,ph=h-t-b;
 const points=rows.map((v,i)=>({x:l+i*pw/(rows.length-1),y:t+(high-v.yoy)/(high-low)*ph,...v}));
 let html='<p>官方公告 CPI 同月年增率（%）｜虛線代表待核對</p>';
 let svg='<svg viewBox="0 0 '+w+' '+h+'" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="已公布月度 CPI 年增率走勢；部分月份仍待來源核對">';
 for(let i=0;i<3;i++){
   const y=t+i*ph/2,axis=high-(high-low)*i/2;
   svg+='<line x1="'+l+'" x2="'+(w-r)+'" y1="'+y+'" y2="'+y+'" stroke="#e1edf0"/>'+
   '<text x="'+(l-5)+'" y="'+(y+4)+'" text-anchor="end" fill="#7894a1" font-size="10">'+safe(axis.toFixed(1))+'</text>';
 }
 for(let i=1;i<points.length;i++){
  const a=points[i-1],b=points[i],pending=a.verification!=='CROSS_VERIFIED'||b.verification!=='CROSS_VERIFIED';
  svg+='<path d="M'+a.x.toFixed(1)+' '+a.y.toFixed(1)+' L'+b.x.toFixed(1)+' '+b.y.toFixed(1)+'" fill="none" stroke="'+(pending?'#86a9b5':'#168f9d')+'" stroke-width="2.4" '+(pending?'stroke-dasharray="5 4"':'')+'/>';
 }
 for(const p of points){
  svg+='<circle cx="'+p.x.toFixed(1)+'" cy="'+p.y.toFixed(1)+'" r="3.1" fill="'+(p.verification==='CROSS_VERIFIED'?'#0b9a8d':'#9eb0b9')+'"><title>'+safe(p.month)+' '+safe(p.yoy.toFixed(2))+'% '+safe(p.verification)+'</title></circle>';
 }
 svg+='<text x="'+l+'" y="'+(h-6)+'" font-size="10" fill="#678496">'+safe(rows[0].month)+'</text>'+
 '<text x="'+(w-r)+'" y="'+(h-6)+'" font-size="10" text-anchor="end" fill="#678496">'+safe(rows.at(-1).month)+'</text></svg>';
 html+=svg;
 box.innerHTML=html;
}
async function loadOfficialSummary(){
 try{
  const response=await fetch('./data/cpi_verified.json',{cache:'no-store'});
  if(!response.ok)throw Error('HTTP '+response.status);
  const data=await response.json();
  if(data.schema_version!==1||!Array.isArray(data.records))throw Error('來源格式未通過檢查');
  const taiwan=window.B85_TAIWAN_TIME;
  if(!taiwan)throw Error('台灣時區模組未就緒');
  const today=taiwan.today(),maximumMonth=taiwan.prevMonth(today);
  const eligible=data.records.filter(r=>r.month<=maximumMonth&&r.publication_date<=today);
  const checked=eligible.filter(r=>r.verification==='CROSS_VERIFIED');
  if(!checked.length)throw Error('沒有完成雙來源核對的月份');
  const newest=checked.at(-1);
  const monthBefore=eligible.find(r=>r.month===maximumMonth);
  text('dash-cpi-month',newest.month.replace('-',' / '));
  text('dash-cpi-sub','官方年增率 '+(newest.official_yoy_pct>0?'+':'')+Number(newest.official_yoy_pct).toFixed(2)+'%；上月 '+(monthBefore?(monthBefore.verification==='CROSS_VERIFIED'?'已查證':'待核對'):'未見公告'));
  trend(eligible);
 }catch{
  text('dash-cpi-month','來源暫不可用');
  text('dash-cpi-sub','不會採用未查證的 CPI 數字');
  text('dash-cpi-trend','無法驗證官方 CPI 快照，請查看官方公告或稍後再試。');
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