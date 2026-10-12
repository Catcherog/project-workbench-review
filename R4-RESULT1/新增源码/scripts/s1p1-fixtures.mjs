import {mkdirSync,mkdtempSync,writeFileSync,chmodSync} from 'node:fs';
import path from 'node:path';
import {createServer} from 'node:net';
import * as d from '../dist-local/domain.mjs';
import {startServer} from './local-http.mjs';
import {emptyEntry} from './work-item-entry.mjs';
export const output=path.resolve('output/s1p1-r4-20261012');mkdirSync(output,{recursive:true});
export const anchor='2026-10-12T02:00:00.000Z';
export const row=(id,extra={})=>({id,title:id,projectIds:[],sourceIds:[],objectIds:[],version:1,createdAt:anchor,updatedAt:anchor,...extra});
export function fixtureState(id='s1p1'){
 const s=d.emptyState(id,'S1/P1 · 虚构隔离验证','demo');s.projects=[row('p',{title:'模拟验证项目',projectLevel:'L2'})];
 const ids={};for(const [name,nature,title] of [['risk','risk','模拟认证风险'],['action','action','模拟培训材料'],['reference','reference','模拟未读资料']]){
  const text=name==='reference'?'https://example.test/spec':'模拟责任人需要补充测试报告，尚未收到结果，继续核对和跟进。';
  s.sources.push(row('src-'+name,{title:'虚构原文 '+name,excerpt:text,author:'模拟工程师',projectIds:['p'],occurredAt:anchor,collectedAt:anchor}));
  [ids[name]]=d.applyWorkItemFindings(s,[{id:'p1-'+name,title,nature,summary:text,impact:nature==='risk'?'可能影响模拟节点':'',nextStep:nature==='reference'?'先读清资料，暂不转为待办':'核对模拟测试报告',urgency:nature==='risk'?'urgent':'normal',sourceIds:['src-'+name],association:{kind:'project',id:'p',confirmed:true,reason:'虚构关联'},triage:{necessary:nature!=='reference',ready:true,reason:'虚构已明确工作',gaps:[]}}],anchor);
 }
 return {s,ids};
}
export function planFor(text,occurredAt=anchor){
 const p=emptyEntry();
 if(!text)return p;
 if(/资料中|引用|他说/.test(text)){p.intent='discuss';return p;}
 const question=/[?？]|怎么办|你觉得|建议|分析一下/.test(text),facts=/已联系|已经联系|已收到|补充进展|风险.*解除|检查完成|停止跟进/.test(text),time=/检查|完成.*待定|要求.*完成|待定/.test(text);
 p.intent=question?(facts||time?'mixed':'discuss'):'record';
 if(facts){p.progress=text.split(/[，；。]/).filter(x=>/已联系|已经联系|已收到|补充进展/.test(x)).join('；');p.progressQuote=p.progress?text.split(/[，；。]/).find(x=>/已联系|已经联系|已收到|补充进展/.test(x)):'';}
 if(/风险.*解除/.test(text)){p.riskDecision='resolved';p.riskQuote=text;p.followup=/无需|不需要|无后续|不再/.test(text)?'end':'continue';p.followupQuote=text;}
 if(/停止跟进/.test(text)){p.followup='cancel';p.followupQuote=text;}
 if(/检查完成/.test(text)){p.checkCompleted=true;p.checkQuote='检查完成';}
 for(const key of ['check','completion']){
  const match=key==='check'?/周[三四].*检查|检查.*周[三四]|今天检查|明天下午四点检查/.exec(text):/完成时间待定|完成待定|要求\d{4}-\d{2}-\d{2}完成/.exec(text);
  if(match){const q=match[0];p[key]={state:q.includes('待定')?'pending':'scheduled',date:q.includes('周四')?'2026-10-15':q.includes('周三')?'2026-10-14':q.includes('明天')?new Date(Date.parse(occurredAt)+86400000).toISOString().slice(0,10):q.includes('今天')?occurredAt.slice(0,10):/\d{4}-\d{2}-\d{2}/.exec(q)?.[0]||'',time:q.includes('下午四点')?'16:00':'',zone:'Asia/Shanghai',quote:q};}
 }
 if(/目前都待定/.test(text))for(const k of ['check','completion'])p[k]={state:'pending',date:'',time:'',zone:'',quote:'目前都待定'};
 return p;
}
export function operation(s,id,text,manual={},extra={}){const source=s.sources.find(x=>x.id===id),c=d.workItemState(s,source);return {workspaceId:s.workspaceId,sourceId:id,requestId:crypto.randomUUID(),action:'p1-submit',expectedVersion:source.version,expectedBasis:c.basis,expectedEvidenceBasis:c.liveEvidenceBasis,entry:planFor(text),input:{text,occurredAt:anchor,manual},...extra};}
export function fakeCodex(folder){
 const file=path.join(folder,'fake-codex.mjs');const fixture=import.meta.url;
 writeFileSync(file,`#!${process.execPath}\nimport {writeFileSync} from 'node:fs';\nimport {planFor} from ${JSON.stringify(fixture)};\nif(process.argv.includes('--version')){console.log('codex simulated');process.exit(0)}\nlet input='';for await(const x of process.stdin)input+=x;\nconst text=JSON.parse(input.match(/<user_request_json>\\n([\\s\\S]*?)\\n<\\/user_request_json>/)[1]),context=JSON.parse(input.match(/<context_json>\\n([\\s\\S]*?)\\n<\\/context_json>/)[1]);\nif(text.includes('延迟'))await new Promise(r=>setTimeout(r,text.includes('延迟长')?3500:1200));\nconst result={answer:'建议：继续依据实际反馈判断，不把建议写成安排。',operations:[],actionRequests:[],workItemRequests:[],citations:[],gaps:['模拟模型只依据当前输入；未核实外部实际交付'],nextSteps:[],conflicts:[],workItemEntry:planFor(text,context.p1Context?.occurredAt)};\nwriteFileSync(process.argv[process.argv.indexOf('--output-last-message')+1],JSON.stringify(result));console.log(JSON.stringify({type:'turn.completed',usage:{input_tokens:10,output_tokens:10,cached_input_tokens:0}}));\n`);chmodSync(file,0o700);return file;
}
export async function startFixture({real=false}={}){
 const dataDir=mkdtempSync(path.join(output,real?'real-':'isolated-'));
 const port=await new Promise(resolve=>{const server=createServer();server.listen(0,'127.0.0.1',()=>{const port=server.address().port;server.close(()=>resolve(port));});});
 const app=await startServer({dataDir,port,testMode:true,legacy:null,assistantOptions:{...(real?{}:{codexBin:fakeCodex(dataDir)}),timeoutMs:real?600000:10000}});
 const {s,ids}=fixtureState();app.store.insert(s);await new Promise(r=>setTimeout(r,30));
 async function api(endpoint,body){const response=await fetch(app.origin+endpoint,{method:body===undefined?'GET':'POST',headers:{'X-Workbench-Token':app.token,'X-Workbench-Client':'ui',...(body!==undefined?{'content-type':'application/json'}:{})},body:body===undefined?undefined:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Object.assign(Error(result.error),{status:response.status,result});return result;}
 return {...app,api,ids,dataDir,workspaceId:s.workspaceId,state:()=>app.store.load(s.workspaceId)};
}
