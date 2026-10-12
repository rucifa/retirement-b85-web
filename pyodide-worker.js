'use strict';
/* Runs unchanged v3.4.0 B+85 policy in a dedicated browser Web Worker via Pyodide.
   All financial inputs remain inside the user's browser. Pinned interpreter URL;
   no arbitrary Python evaluation based on user input. */
const VERSION='0.29.5';
const CDN=`https://cdn.jsdelivr.net/pyodide/v${VERSION}/full/`;
let runtime=null;
let ready=false;
let busy=Promise.resolve();
const sourceFiles=['workflow.py','withdrawal_sources.py','bridge.py','expense_contract.py','ledger_integrity.py','projection_research.py','calendar_first_year.py','spending_profile.py','capacity_research.py','policy/__init__.py','policy/retirement_model_v340.py','policy/annual_execution_v340.py','policy/simple_annual_ledger.py','policy/personalized_research_engine.py','policy/personalized_research_annual.py','policy/personalized_research_ledger.py'];
function progress(message){self.postMessage({type:'progress',message});}
async function getRuntime(){
  if(runtime)return runtime;
  progress('正在載入瀏覽器計算環境（第一次可能需要較長時間）');
  importScripts(CDN+'pyodide.js');
  runtime=await self.loadPyodide({indexURL:CDN});
  progress('正在載入 NumPy 與 B＋85 模型');
  await runtime.loadPackage('numpy');
  runtime.FS.mkdirTree('/home/pyodide/policy');
  for(const name of sourceFiles){
    const target=new URL('./'+name,self.location.href);
    const response=await fetch(target,{cache:'no-cache'});
    if(!response.ok)throw new Error(`模型原始檔讀取失敗：${name}`);
    runtime.FS.writeFile('/home/pyodide/'+name,new Uint8Array(await response.arrayBuffer()));
  }
  runtime.runPython(`import sys\nsys.path.insert(0, '/home/pyodide')\nimport bridge`);
  return runtime;
}
async function handle(req){
  const id=req.id;
  try{
    const py=await getRuntime();
    if(req.op==='init'){
      if(ready)throw new Error('計算引擎已啟動');
      py.globals.set('saved_json', req.data?.saved || null);
      const result=py.runPython('bridge.initialize(saved_json)');
      const data=result.toJs({dict_converter:Object.fromEntries});result.destroy();
      ready=true;self.postMessage({type:'result',id,ok:true,data});
      progress('B＋85 引擎已就緒，年度紀錄僅保存在此瀏覽器');
      return;
    }
    if(!ready)throw new Error('請先載入 B＋85 引擎');
    const input=JSON.stringify({op:req.op,data:req.data||{}});
    if(req.op==='projection'){
      py.globals.set('_projection_progress',(done,total)=>self.postMessage({type:'simulation-progress',done,total}));
      py.runPython('bridge.PROJECTION_PROGRESS = _projection_progress');
    }
    py.globals.set('call_json',input);
    const raw=py.runPython(`import json
try:
    _out=bridge.dispatch(call_json)
except bridge.InputError as err:
    _out=json.dumps({"user_input_error":str(err)},ensure_ascii=False)
_out`);
    const response=JSON.parse(raw);
    if(response.user_input_error){
      self.postMessage({type:'result',id,ok:false,error:response.user_input_error});
      return;
    }
    self.postMessage({type:'result',id,ok:true,...response});
  }catch(error){
    const detail=error?.message||String(error);
    if(req.op==='projection')self.postMessage({type:'result',id,ok:false,error:'蒙地卡羅研究未完成，請稍後重試或改用快速模式。',diagnostic:detail.slice(-1800)});
    else self.postMessage({type:'result',id,ok:false,error:detail.slice(0,700)});
  }
}
self.addEventListener('message',event=>{
  const request=event.data;
  busy=busy.then(()=>handle(request)).catch(error=>{self.postMessage({type:'result',id:request.id,ok:false,error:'背景運算失敗：'+String(error)})});
});
