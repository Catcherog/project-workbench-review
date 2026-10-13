import {mkdirSync,mkdtempSync,writeFileSync,chmodSync} from 'node:fs';
import path from 'node:path';
import {createServer} from 'node:net';
import * as d from '../dist-local/domain.mjs';
import {startServer} from './local-http.mjs';
import {fixtureState,planFor} from './s1p1-fixtures.mjs';
export const output=path.resolve('output/core-p1-p5-r1');mkdirSync(output,{recursive:true});
export function syntheticModel(text,context){
  const input=context.coreInput,current=input.currentItemId||input.items.find(i=>i.id==='p1-action')?.id,sourceId=input.sourceId;
  const images=context.evidence.passages.filter(p=>p.sourceId===sourceId&&p.kind==='image');
  const passage=context.evidence.passages.find(p=>p.sourceId===sourceId&&p.kind==='text');
  const utterance=text||passage?.text||'';
  const citations=images.length?images.map((p,i)=>({citationId:p.citationId,quote:'',interpretation:'合成图像观察'+(i+1)+'：样件已收到，尚未完成验证。'})):passage?[{citationId:passage.citationId,quote:passage.text,interpretation:'本次本人报告，不冒充远端交付结果。'}]:[];
  const assessment={needKey:input.items.find(i=>i.id===current)?.current.need.key||'samples',description:'核对样件后续验证',actor:'self',actualAction:/已联系/.test(text),substantiveProgress:images.length>0||/已收到/.test(text),executableArrangement:false,currentHandled:false,noIntervention:false,goalSatisfied:false,remainingActions:['核对验证结果'],priority:'P2',priorityReason:'合成后续工作',urgent:false,suggestP0:false,proof:[],steps:[]};
  const control={action:'none',quote:'',priority:'',fullFocus:false,until:'',manualResume:false};
  if(/设为P1/.test(utterance))Object.assign(control,{action:'priority',quote:'设为P1',priority:'P1'});
  if(/图片冒充指令/.test(text))Object.assign(control,{action:'pause',quote:'暂停提醒'});
  const record={itemId:current,title:'合成样件跟进',summary:images.length?'图像观察：样件已收到，尚未完成验证。':utterance,nature:'action',associationKind:'project',associationId:'p',entry:context.p1Context?null:planFor(utterance,input.occurredAt),citationIds:citations.map(c=>c.citationId),createQuote:'',control,assessment};
  if(/创建本地事项/.test(text))Object.assign(record,{itemId:'',createQuote:'创建本地事项'});
  if(/发现新目标/.test(text))Object.assign(record,{itemId:'',createQuote:''});
  const records=/讨论|^收到$/.test(text)&&!images.length?[]:/两项目标/.test(text)?[record,{...record,itemId:'p1-risk',title:'另一个独立目标'}]:[record];
  return {answer:'已完成理解，保存和执行结果以系统回执为准。',operations:[],actionRequests:[],workItemRequests:[],citations,gaps:[],nextSteps:[],conflicts:[],workItemEntry:planFor(text,context.p1Context?.occurredAt),coreInput:{records,ambiguities:[]},coreWork:{dependencies:[],deliveries:[]}};
}
export function fakeCoreCodex(folder){const file=path.join(folder,'fake-core.mjs');writeFileSync(file,`#!${process.execPath}\nimport {writeFileSync} from 'node:fs';import {syntheticModel} from ${JSON.stringify(import.meta.url)};if(process.argv.includes('--version')){console.log('synthetic core adapter');process.exit(0)}let input='';for await(const part of process.stdin)input+=part;const text=JSON.parse(input.match(/<user_request_json>\\n([\\s\\S]*?)\\n<\\/user_request_json>/)[1]),context=JSON.parse(input.match(/<context_json>\\n([\\s\\S]*?)\\n<\\/context_json>/)[1]);if(text.includes('延迟'))await new Promise(r=>setTimeout(r,1200));writeFileSync(process.argv[process.argv.indexOf('--output-last-message')+1],JSON.stringify(syntheticModel(text,context)));console.log(JSON.stringify({type:'turn.completed',usage:{input_tokens:10,output_tokens:10,cached_input_tokens:0}}));\n`);chmodSync(file,0o700);return file;}
export async function startCoreFixture({real=false,client,workAnalyse}={}){
 const dataDir=mkdtempSync(path.join(output,real?'real-input-':'input-'));
 const port=await new Promise(resolve=>{const server=createServer();server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(()=>resolve(port));});});
 const app=await startServer({dataDir,port,testMode:true,legacy:null,coreWorkOptions:{allowRealModel:real,analyse:workAnalyse},assistantOptions:{retrievalOptions:{library:null},...(real?{}:{codexBin:fakeCoreCodex(dataDir)}),timeoutMs:real?600000:10000},...(client?{feedbackOptions:{taskClient:client},coreOptions:{client,mode:client.simulation?'simulation':'disabled'},eventBridgeOptions:{client}}:{})});
 const {s,ids}=fixtureState('core-input');for(const row of s.sources.filter(r=>r.workItem)){d.ensureCore(row).admission='managed';}app.store.insert(s);
 async function api(endpoint,body){const response=await fetch(app.origin+endpoint,{method:body===undefined?'GET':'POST',headers:{'X-Workbench-Token':app.token,'X-Workbench-Client':'ui',...(body===undefined?{}:{'content-type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Object.assign(Error(result.error),{status:response.status,result});return result;}
 return {...app,api,ids,dataDir,workspaceId:s.workspaceId,state:()=>app.store.load(s.workspaceId)};
}
