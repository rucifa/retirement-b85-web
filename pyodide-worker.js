'use strict';
/* Runs unchanged v3.4.0 B+85 policy in a dedicated browser Web Worker via Pyodide.
   All financial inputs remain inside the user's browser. Pinned interpreter URL;
   no arbitrary Python evaluation based on user input. */
const VERSION='0.29.5';
const CDN=`https://cdn.jsdelivr.net/pyodide/v${VERSION}/full/`;
let runtime=null;
let ready=false;
let busy=Promise.resolve();
const sourceFiles=['workflow.py','bridge.py','policy/__init__.py','policy/retirement_model_v340.py','policy/annual_execution_v340.py','policy/simple_annual_ledger.py'];
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
    py.globals.set('call_json',input);
    const response=JSON.parse(py.runPython('bridge.dispatch(call_json)'));
    self.postMessage({type:'result',id,ok:true,...response});
  }catch(error){
    self.postMessage({type:'result',id,ok:false,error:(error?.message||String(error)).slice(0,700)});
  }
}
self.addEventListener('message',event=>{
  const request=event.data;
  busy=busy.then(()=>handle(request)).catch(error=>{self.postMessage({type:'result',id:request.id,ok:false,error:'背景運算失敗：'+String(error)})});
});
