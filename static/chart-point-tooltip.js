/* Read-only shared point inspection for the three asset SVG charts.
   Displays existing values only: no worker, storage, ledger or policy access. */
(function(){
'use strict';
const escapeHtml=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=n=>'NT$ '+new Intl.NumberFormat('zh-TW',{maximumFractionDigits:0}).format(Math.round(Number(n)));
const fields=['title','series','value','basis','detail','note'];

function marker({x,y,color,title,series,value,basis,detail='',note=''}) {
 if(![x,y,value].every(v=>Number.isFinite(Number(v))))return '';
 const details={title,series,value:money(value),basis,detail,note};
 const aria=fields.map(k=>details[k]).filter(Boolean).join('，');
 const props=fields.map(k=>' data-'+k+'="'+escapeHtml(details[k])+'"').join('');
 const a=escapeHtml(aria);
 // Put the visible dot and a larger transparent hit target in the same group.
 // The target has a keyboard role and a native SVG title fallback.
 return '<g class="chart-point-marker">'+
  '<circle class="chart-point-core" cx="'+Number(x).toFixed(2)+'" cy="'+Number(y).toFixed(2)+'" r="4.2" fill="'+escapeHtml(color)+'" stroke="#fff" stroke-width="1.5" aria-hidden="true"/>'+
  '<circle class="chart-point-hit" cx="'+Number(x).toFixed(2)+'" cy="'+Number(y).toFixed(2)+'" r="10" fill="transparent" stroke="transparent" tabindex="0" role="button" aria-label="'+a+'"'+props+'><title>'+a+'</title></circle></g>';
}
function bind(container) {
 if(!container||container.dataset.chartPointsBound==='true')return;
 container.dataset.chartPointsBound='true';
 let locked=null,active=null;
 const tooltip=()=>{
  let el=container.querySelector(':scope > .chart-point-tooltip');
  if(!el){
   el=document.createElement('div');
   el.className='chart-point-tooltip';
   el.role='status';
   el.setAttribute('aria-live','polite');
   el.hidden=true;
   container.appendChild(el);
  }
  return el;
 };
 const hide=()=>{
  if(active)active.classList.remove('is-active');
  active=null;
  const tip=container.querySelector(':scope > .chart-point-tooltip');
  if(tip)tip.hidden=true;
 };
 const show=p=>{
  if(!p||!p.isConnected)return;
  if(active&&active!==p)active.classList.remove('is-active');
  active=p;p.classList.add('is-active');
  const tip=tooltip();tip.replaceChildren();
  for(const [index,key] of fields.entries()){
   const val=p.dataset[key];if(!val)continue;
   const el=document.createElement(index===0?'strong':'span');
   el.className='chart-point-'+key;
   el.textContent=val;
   tip.appendChild(el);
  }
  tip.hidden=false;
  const rect=container.getBoundingClientRect(),dot=p.getBoundingClientRect();
  const center=(dot.left+dot.width/2)-rect.left;
  const left=Math.max(8,Math.min(center-tip.offsetWidth/2,Math.max(8,container.clientWidth-tip.offsetWidth-8)));
  let top=dot.top-rect.top-tip.offsetHeight-9;
  if(top<5)top=dot.bottom-rect.top+9;
  tip.style.left=left+'px';tip.style.top=top+'px';
 };
 const hit=e=>e.target?.closest?.('.chart-point-hit');
 container.addEventListener('pointerover',e=>{const p=hit(e);if(p&&!locked)show(p);});
 container.addEventListener('pointerout',e=>{if(hit(e)&&!locked&&container.contains(e.relatedTarget)!==false)hide();});
 container.addEventListener('pointerleave',()=>{if(!locked)hide();});
 container.addEventListener('focusin',e=>{const p=hit(e);if(p){locked=null;show(p);}});
 container.addEventListener('focusout',e=>{if(hit(e)&&!locked)hide();});
 container.addEventListener('click',e=>{
  const p=hit(e);
  if(!p){locked=null;hide();return;}
  if(locked===p){locked=null;hide();return;}
  locked=p;show(p);
 });
 container.addEventListener('keydown',e=>{
  if(e.key==='Escape'){locked=null;hide();return;}
  const p=hit(e);
  if(p&&(e.key==='Enter'||e.key===' ')){e.preventDefault();if(locked===p){locked=null;hide();}else{locked=p;show(p);}}
 });
 // Dismiss a touch/click selection when interacting outside the chart.
 document.addEventListener('pointerdown',e=>{
  if(locked&&!container.contains(e.target)){locked=null;hide();}
 });
}
function clear(container){
 if(!container)return;
 const tip=container.querySelector(':scope > .chart-point-tooltip');
 if(tip)tip.hidden=true;
 container.querySelectorAll('.chart-point-hit.is-active').forEach(p=>p.classList.remove('is-active'));
 // Rerender replaces the selected SVG node; next hover/focus starts fresh.
}
window.B85_CHART_POINTS=Object.freeze({marker,bind,clear,money});
})();
