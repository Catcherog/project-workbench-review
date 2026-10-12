import assert from 'node:assert/strict';import {writeFileSync,readFileSync,existsSync} from 'node:fs';import {setTimeout as delay} from 'node:timers/promises';import * as d from '../dist-local/domain.mjs';import {startFixture,fixtureState,anchor,output} from './s1p1-fixtures.mjs';
if(process.env.PM_RUN_S1P1_REAL!=='1')throw Error('Explicit synthetic real-model test opt-in is required');
let current,runtimeEvidence;
try{
 const status=await(await fetch('http://127.0.0.1:5173/api/v2/status')).json();
 current=await(await fetch('http://127.0.0.1:5173/api/v2/ai-settings',{headers:{'X-Workbench-Token':status.csrfToken,'X-Workbench-Client':'ui'}})).json();runtimeEvidence='formal readback at test start';
}catch(error){
 if(!existsSync(output+'/real-results.json'))throw error;
 const prior=JSON.parse(readFileSync(output+'/real-results.json'));
 current={chat:prior.runtime,background:prior.runtime};runtimeEvidence='same-session earlier verified chat configuration; formal service not listening; no restart';
}
assert.equal(current.chat.model,'gpt-6-astra');assert.equal(current.chat.effort,'max');
const selected=process.env.PM_S1P1_CASES?.split(',');const previous=selected&&existsSync(output+'/real-results.json')?JSON.parse(readFileSync(output+'/real-results.json')).results:[];
const app=await startFixture({real:true});app.runtimeSettings.update({revision:0,chat:current.chat,background:current.background});const results=[];
const cases=[
 ['A03/B13','完成时间待定，周三先检查。','action',{},j=>{assert.equal(j.p1Outcome.status,'saved');assert.equal(j.p1Outcome.receipt.timing.check.date,'2026-10-14');assert.equal(j.p1Outcome.receipt.timing.completion.state,'pending');}],
 ['B16','我已经联系负责人了，接下来怎么办？','action',{},j=>{assert.equal(j.p1Outcome.status,'saved');assert.equal(j.p1Outcome.stay,true);assert.match(j.p1Outcome.receipt.progress,/联系/);}],
 ['B18/B21','我已收到报告，风险已经解除，不需要再跟进。','risk',{},j=>{assert.equal(j.p1Outcome.status,'saved');assert.equal(j.p1Outcome.receipt.closed,true);}],
 ['B27','你觉得现在应该催吗？','action',{},j=>assert.equal(j.p1Outcome.status,'discuss')],
 ['B11','明天下午四点检查。','action',{},j=>{assert.equal(j.p1Outcome.status,'saved');assert.equal(j.p1Outcome.receipt.timing.check.date,'2026-10-02');assert.equal(j.p1Outcome.receipt.timing.check.time,'16:00');}],
 ['B26','周三检查。','action',{check:{state:'scheduled',date:'2026-10-15'}},j=>{assert.equal(j.p1Outcome.status,'clarify');assert.equal(j.p1Outcome.conflicts[0].field,'check');}],
 ['evidence-boundary','这段资料写着：“风险已经解除，不需要再跟进”。请分析这句话是否有充分依据，不要改变事项。','risk',{},j=>assert.equal(j.p1Outcome.status,'discuss')],
 ['B27-manual','你觉得现在应该催吗？','action',{completion:{state:'scheduled',date:'2026-10-20'}},j=>{assert.equal(j.p1Outcome.status,'saved');assert.equal(j.p1Outcome.stay,true);assert.equal(j.p1Outcome.receipt.timing.completion.date,'2026-10-20');}]
];
async function runCase(test,index){const [id,text,kind,manual,verify]=test,{s,ids}=fixtureState('p1-real-'+index);app.store.insert(s);await delay(50);const live=app.store.load(s.workspaceId),row=live.sources.find(x=>x.id===ids[kind]),c=d.workItemState(live,row);
 const body={workspaceId:s.workspaceId,requestId:crypto.randomUUID(),sessionId:crypto.randomUUID(),parentJobId:'',mode:'answer',sourceIds:[],contextRef:{kind:'sources',id:row.id},text,p1Input:{occurredAt:id==='B11'?'2026-10-01T02:00:00.000Z':anchor,manual,expectedVersion:row.version,expectedBasis:c.basis,expectedEvidenceBasis:c.liveEvidenceBasis}};
 let job=(await app.api('/api/v2/codex/jobs',body)).job;console.log('START',id,job.id);while(job.status==='running'){await delay(800);job=(await app.api('/api/v2/codex/jobs/'+job.id+'?workspaceId='+s.workspaceId)).job;}
 try{assert.equal(job.status,'completed',job.error);verify(job);results.push({id,input:text,manual,passed:true,job});console.log('PASS',id);}catch(e){results.push({id,input:text,manual,passed:false,error:e.message,job});console.log('FAIL',id,e.message);}writeFileSync(output+'/real-results.json',JSON.stringify({syntheticData:true,realModel:true,runtimeEvidence,runtime:current.chat,externalBusinessWrites:0,results:[...previous.filter(x=>!results.some(r=>r.id===x.id)),...results]},null,2));
}
try{const tests=selected?cases.filter(x=>selected.includes(x[0])):cases;for(let i=0;i<tests.length;i+=2)await Promise.all(tests.slice(i,i+2).map((x,j)=>runCase(x,i+j)));const failed=results.filter(r=>!r.passed);assert.equal(failed.length,0,failed.map(x=>x.id+':'+x.error).join('\n'));}finally{await app.close();}
