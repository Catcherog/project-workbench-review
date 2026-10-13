import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';
import {readFileSync,writeFileSync,readdirSync,statSync} from 'node:fs';
import {setTimeout as delay} from 'node:timers/promises';
import path from 'node:path';
import * as d from '../dist-local/domain.mjs';
import {startCoreFixture,output} from './core-fixtures.mjs';
if(process.env.PM_RUN_CORE_REAL!=='1')throw Error('Explicit real-model opt-in required');
const db=new DatabaseSync('/REVIEW_MAIN/.local-workbench/workbench.sqlite',{readOnly:true}),runtime=JSON.parse(db.prepare('select payload from settings where key=?').get('aiRuntime').payload);db.close();
const files=[];for(const dir of ['app','lib','scripts']){const walk=p=>{for(const n of readdirSync(p)){const f=path.join(p,n);if(statSync(f).isDirectory())walk(f);else if(/\.(ts|tsx|mjs|py|css)$/.test(f))files.push(f);}};walk(dir);}const fingerprint=createHash('sha256');for(const f of files.sort())fingerprint.update(f).update(readFileSync(f));
const record={case:'final-image-and-time',scope:'real model, synthetic image and local item, no live business writes',sourceTreeSha256:fingerprint.digest('hex'),runtime:runtime.chat,startedAt:new Date().toISOString()};
const app=await startCoreFixture({real:true});app.runtimeSettings.update({revision:0,chat:runtime.chat,background:runtime.background});
try{
 const s=app.state(),row=s.sources.find(r=>r.id===app.ids.action);row.title='合成样件验证';row.workItem.summary='等待样件到库后核对验证结果';row.workItem.p1={completion:{state:'scheduled',date:'2026-10-20',precision:'date',origin:'manual'}};s.revision++;app.store.save(s,s.revision-1);
 const file=await app.api('/api/v2/attachments',{workspaceId:app.workspaceId,name:'synthetic-progress.png',mime:'image/png',base64:readFileSync(output+'/synthetic-progress.png').toString('base64')});
 const current=app.state(),item=current.sources.find(r=>r.id===app.ids.action),c=d.workItemState(current,item);
 const input={workspaceId:app.workspaceId,requestId:crypto.randomUUID(),sessionId:crypto.randomUUID(),parentJobId:'',mode:'answer',contextRef:{kind:'sources',id:item.id},sourceIds:[],attachmentIds:[file.attachment.id],text:'这张合成截图属于当前样件验证事项，请记录其中已经发生的进展，把检查安排在2026-10-14。完成要求保持原样，不发送消息。',p1Input:{occurredAt:new Date().toISOString(),expectedVersion:item.version,expectedBasis:c.basis,expectedEvidenceBasis:c.liveEvidenceBasis,manual:{}}};
 record.input=input.text;let job=(await app.api('/api/v2/codex/jobs',input)).job;record.jobId=job.id;console.log('START',record.case,job.id);
 while(job.status==='running'){await delay(1000);job=(await app.api('/api/v2/codex/jobs/'+job.id+'?workspaceId='+app.workspaceId)).job;}
 record.job=job;assert.equal(job.status,'completed',job.error);assert.equal(job.p1Outcome.status,'saved');const result=app.state().sources.find(r=>r.id===item.id);assert.equal(result.workItem.p1.check.date,'2026-10-14');assert.equal(result.workItem.p1.check.defaultTime,'10:00');assert.equal(result.workItem.p1.completion.date,'2026-10-20');assert.ok(result.workItem.p1.progress.some(p=>p.proof?.some(e=>e.kind==='image')));assert.equal(d.workItemState(app.state(),result).closed,false);assert.equal(app.state().sources.filter(r=>r.reminderRun||r.followupNotification).length,0);record.passed=true;console.log('PASS',record.case);
}catch(error){record.passed=false;record.error=error.message;process.exitCode=1;console.log('FAIL',record.case,error.message);}finally{record.finishedAt=new Date().toISOString();record.usage=app.assistant.aiUsage.status();writeFileSync(output+'/real-model-final.json',JSON.stringify(record,null,2));await app.close();}
