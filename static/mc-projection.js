/* Read-only research worker; cancellation cannot interrupt the ledger worker. */
(function(){
'use strict';
const $=id=>document.getElementById(id),money=n=>new Intl.NumberFormat('zh-TW',{maximumFractionDigits:0}).format(n);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let result=null,sourceKey=null,runningKey=null,simulationWorker=null,timer=null,generation=0,running=false;
const currentKey=()=>{const y=state?.years?.at(-1);return y?y.approval_id+'|'+(y.closing?.sha256||'pending'):null;};
function status(message,mode){$('mc-status').textContent=message;$('mc-status').dataset.state=mode;}
 function finish(){simulationWorker?.terminate();simulationWorker=null;clearTimeout(timer);timer=null;running=false;runningKey=null;$('mc-run').disabled=false;$('mc-cancel').classList.add('hidden');}
function cancel(message='已取消計算；年度紀錄保持原狀。'){generation++;finish();status(message,'cancelled');}
function nominalScale(row,j){
 const inflation=Number($('mc-inflation').value);
 if(!Number.isFinite(inflation)||inflation < -5||inflation>15)throw Error('通膨情境須為 −5%～15%');
 const duration=j+(result.first_approval_locked?result.first_calendar_fraction:1);
 return Math.pow((1+inflation/100)/(1+result.inflation_pct/100),duration);
}
function selectedRows(){
 const asset=$('mc-asset').value,basis=$('mc-basis').value;
 return result.years.map((r,j)=>({year:r.year,age:r.age,q:r[asset+'_'+basis+'_twd'].map(x=>basis==='nominal'?x*nominalScale(r,j):x),depleted:r.depleted_fraction}));
}
function draw(){
 if(!result)return;
 let rows;try{rows=selectedRows()}catch(e){status(e.message,'error');return;}
 const basis=$('mc-basis').value,asset=$('mc-asset').selectedOptions[0].textContent;
 const label=basis==='nominal'?'名目金額（年通膨情境 '+$('mc-inflation').value+'%）':'2026 年固定購買力';
 const w=640,h=264,l=67,r=15,top=20,b=42,pw=w-l-r,ph=h-top-b;
 const max=Math.max(10000,...rows.flatMap(x=>x.q))*1.06;
 const xx=j=>l+(rows.length===1?.5:j/(rows.length-1))*pw;
 const yy=v=>top+(1-v/max)*ph;
 const path=k=>rows.map((x,j)=>(j?'L':'M')+xx(j).toFixed(2)+' '+yy(x.q[k]).toFixed(2)).join(' ');
 let svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+w+' '+h+'" role="img" aria-label="'+esc(asset+'，'+label+'，年末 P10 P50 P90')+'">';
 for(let i=0;i<=4;i++){const y=top+ph*i/4;svg+='<line x1="'+l+'" x2="'+(w-r)+'" y1="'+y+'" y2="'+y+'" stroke="#e2ecf0"/><text x="'+(l-8)+'" y="'+(y+4)+'" text-anchor="end" fill="#607f8c" font-size="11">'+money(max*(1-i/4)/10000)+'</text>';}
 const band=rows.map((x,j)=>xx(j).toFixed(2)+','+yy(x.q[2]).toFixed(2)).concat([...rows].reverse().map((x,j)=>xx(rows.length-1-j).toFixed(2)+','+yy(x.q[0]).toFixed(2))).join(' ');
 svg+='<polygon points="'+band+'" fill="#bde7dd" opacity="0.45"/>';
 ['#b67937','#118368','#3986b0'].forEach((color,k)=>{
  svg+='<path data-percentile="'+[10,50,90][k]+'" d="'+path(k)+'" stroke="'+color+'" stroke-width="'+(k===1?3:2)+'" fill="none"/>';
  rows.forEach((x,j)=>{svg+='<circle tabindex="0" cx="'+xx(j).toFixed(2)+'" cy="'+yy(x.q[k]).toFixed(2)+'" r="3.5" fill="'+color+'"><title>'+x.year+' 年（'+x.age+' 歲）P'+[10,50,90][k]+'：NT$ '+money(x.q[k])+'；'+esc(label)+'</title></circle>';});
 });
 const ticks=new Set([0,rows.length-1]);for(let j=0;j<rows.length;j+=Math.max(1,Math.ceil(rows.length/5)))ticks.add(j);
 for(const j of ticks)svg+='<text x="'+xx(j)+'" y="'+(h-20)+'" font-size="11" fill="#607f8c" text-anchor="middle">'+rows[j].year+'</text>';
 svg+='<text x="'+(l-6)+'" y="12" font-size="10" text-anchor="end" fill="#607f8c">萬元</text></svg>';
 $('mc-chart').innerHTML='<div class="mc-chart-label">'+esc(asset+'・'+label+'・各年年末')+'</div>'+svg+'<div class="dash-scenario-legend"><span class="dash-scenario-key low">P10</span><span class="dash-scenario-key mid">P50</span><span class="dash-scenario-key high">P90</span></div>';
 const pct=x=>(x*100).toFixed(2)+'%',d=result.diagnostics;
 $('mc-diagnostics').innerHTML='<div class="mc-diagnostics-grid">'+[['完整動態計畫成功率',d.plan_success],['終生最低生活費達成率',d.lifetime_floor_success],['必要大額支出達成率',d.required_expense_success]].map(([s,p])=>'<div><small>'+s+'</small><strong>'+pct(p)+'</strong></div>').join('')+'</div><p class="dash-scenario-disclaimer">以上為此批模型抽樣結果。完整計畫／最低生活費／必要支出的單側 95% 信賴下界分別為 '+pct(d.plan_success_wilson_lower_95)+'／'+pct(d.lifetime_floor_success_wilson_lower_95)+'／'+pct(d.required_expense_success_wilson_lower_95)+'；與年度內層 PoS 不同，不是實際退休保證。</p>';
 $('mc-provenance').textContent='亂數種子 '+result.seed+'；'+result.paths+' 外層／'+result.inner_paths+' 內層；運算 '+result.seconds.toFixed(2)+' 秒。固定市場模型與費用情境 net_central_2026ref；截止 104 歲。'+(result.first_approval_locked?'第一個年度沿用已核准預算，後續年度重新依政策決策。':'從最新已結算年度的結轉資產開始。')+(result.legacy_first_pos_excludes_extra?' 舊年度原 PoS 未包含另列必要支出，本次保留原核准，該費用仍只扣一次。':'');
 $('mc-table').innerHTML='<table><caption>'+esc(asset+'・'+label+'（新台幣元）')+'</caption><thead><tr><th>年度／年齡</th><th>P10</th><th>P50</th><th>P90</th><th>耗盡比例</th></tr></thead><tbody>'+rows.map(x=>'<tr><td>'+x.year+'／'+x.age+'</td>'+x.q.map(v=>'<td>'+money(v)+'</td>').join('')+'<td>'+pct(x.depleted)+'</td></tr>').join('')+'</tbody></table>';
 $('mc-export').classList.remove('hidden');
}
async function run(){
 if(running)return;
 if(!currentKey()){status('請先完成年初試算，再執行模擬。','error');return;}
 const inflation=Number($('mc-inflation').value);if(!Number.isFinite(inflation)||inflation< -5||inflation>15){status('通膨情境須為 −5%～15%。','error');return;}
 const gen=++generation,key=currentKey();runningKey=key;running=true;$('mc-run').disabled=true;$('mc-cancel').classList.remove('hidden');status('正在準備獨立研究計算環境；年度帳本仍可使用。','running');
 const higher=$('mc-precision').value==='higher';
 timer=setTimeout(()=>cancel('計算逾時，已停止研究 Worker；可改用快速模式重試，帳本保持原狀。'),higher?240000:180000);
 try{
  const exported=await request('/api/export');if(gen!==generation)return;
  if(currentKey()!==key){cancel('年度紀錄已改變，請依最新年度重新計算。');return;}
  simulationWorker=new Worker('./pyodide-worker.js',{name:'B85-readonly-projection'});
  simulationWorker.onerror=()=>{if(gen!==generation)return;finish();status('研究計算環境無法載入，請稍後重試。','error');};
  simulationWorker.onmessage=e=>{
   if(gen!==generation)return;const m=e.data;
   if(m.type==='progress'){status(m.message,'running');return;}
   if(m.type==='simulation-progress'){status('正在模擬退休年度：'+m.done+'／'+m.total+'，可隨時取消。','running');return;}
   if(m.type!=='result')return;
   if(!m.ok){finish();status(m.error||'模擬失敗，紀錄保持原狀。','error');return;}
   if(m.id===1){simulationWorker.postMessage({id:2,op:'projection',data:{paths:higher?8192:2048,inner_paths:higher?2048:512,inflation_pct:inflation}});return;}
   finish();if(currentKey()!==key){status('年度紀錄已改變，研究結果未套用；請重新計算。','stale');return;}
   result=m.data;sourceKey=key;draw();status('模擬完成：'+result.paths+' 條隨機路徑，至 104 歲。百分位與成功率分開呈現。','complete');
  };
  simulationWorker.postMessage({id:1,op:'init',data:{saved:JSON.stringify(exported.payload)}});
 }catch(e){if(gen!==generation)return;finish();status(e.message,'error');}
}
for(const id of ['mc-asset','mc-basis','mc-inflation'])$(id).addEventListener('input',draw);
$('mc-run').addEventListener('click',run);$('mc-cancel').addEventListener('click',()=>cancel());
$('mc-export').addEventListener('click',()=>{
 if(!result)return;
 const data={...result,display_selection:{asset:$('mc-asset').value,basis:$('mc-basis').value,inflation_pct:Number($('mc-inflation').value)},display_years:selectedRows()};
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='B85_蒙地卡羅研究_'+result.asof+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
});
const observer=new MutationObserver(()=>{
 if(running&&currentKey()!==runningKey)cancel('年度紀錄已更新，計算已取消，請依最新年度重試。');
 if((running||result)&&currentKey()!==sourceKey&&result){result=null;sourceKey=null;$('mc-chart').textContent='年度紀錄已更新，請重新計算。';$('mc-diagnostics').replaceChildren();$('mc-provenance').replaceChildren();$('mc-table').replaceChildren();$('mc-export').classList.add('hidden');if(running)cancel('紀錄已更新，請重新計算。');else status('年度紀錄已更新，舊模擬結果已清除。','stale');}
});
observer.observe($('history-list'),{childList:true});
window.B85_MC_RESEARCH=Object.freeze({getResult:()=>result,isRunning:()=>running});
})();
