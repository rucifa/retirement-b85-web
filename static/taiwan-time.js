/* Taiwan civil-date utilities. GitHub Pages is static: wall-clock source is the browser,
 * interpreted in Asia/Taipei. Never infer date from browser timezone or UTC ISO day. */
(function(){
'use strict';
function today(){
 const parts=new Intl.DateTimeFormat('en-US',{
  timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',
  calendar:'gregory',numberingSystem:'latn'
 }).formatToParts(new Date());
 const get=k=>parts.find(x=>x.type===k)?.value;
 const y=get('year'),m=get('month'),d=get('day');
 if(!y||!m||!d)throw Error('台灣日期轉換不可用');
 return y+'-'+m+'-'+d;
}
function prevMonth(day){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(day))throw Error('台灣日期不符合 ISO 格式');
 const year=Number(day.slice(0,4)),month=Number(day.slice(5,7));
 return (month===1?year-1:year)+'-'+String(month===1?12:month-1).padStart(2,'0');
}
window.B85_TAIWAN_TIME=Object.freeze({today,prevMonth});
const input=document.getElementById('decision_date');
const firstYear=document.getElementById('first_year');
if(input&&!input.value){
 const d=today();input.value=d;
 if(firstYear)firstYear.value=d.slice(0,4);
}
})();
