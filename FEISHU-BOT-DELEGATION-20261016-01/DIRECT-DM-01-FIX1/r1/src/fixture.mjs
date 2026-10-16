import fs from 'node:fs';import {join,resolve} from 'node:path';import {randomUUID} from 'node:crypto';import {DatabaseSync} from 'node:sqlite';
import {keys,digest} from './codec.mjs';import {defaultPolicy,identity,summaryId,purpose} from './policy.mjs';import {DelegationProbe} from './probe.mjs';
export function createFixture(label='case',{root=resolve('runtime',label+'-'+randomUUID())}={}){
 fs.mkdirSync(join(root,'resources'),{recursive:true,mode:0o700});for(const name of ['summary.txt','raw-log.txt'])fs.copyFileSync(new URL('../fixtures/'+name,import.meta.url),join(root,'resources',name));fs.writeFileSync(join(root,'policy.json'),JSON.stringify(defaultPolicy()));
 const k={bot:keys(),human:keys(),receiver:keys()},clock={now:Date.UTC(2026,9,16,0,0,0)};let probe=new DelegationProbe({root,keys:k,clock:()=>clock.now});
 const context={root,keys:k,clock,get probe(){return probe;},reopen(){probe=new DelegationProbe({root,keys:k,clock:()=>clock.now});return probe;},policy(change){const p=JSON.parse(fs.readFileSync(join(root,'policy.json')));change(p);fs.writeFileSync(join(root,'policy.json'),JSON.stringify(p));},received(){const p=join(root,'receiver.sqlite');if(!fs.existsSync(p))return [];const db=new DatabaseSync(p,{readOnly:true});try{return db.prepare('SELECT id,hash,body,receipt FROM deliveries').all();}finally{db.close();}},async close(){return probe.close();}};
 return context;
}
export const intent=(id='request-'+randomUUID(),extra={})=>({kind:'intent',requestId:id,nonce:randomUUID(),tenant:identity.tenant,app:identity.app,bot:identity.bot,human:identity.human,target:identity.target,targetApp:identity.targetApp,text:'把测试进展给指定合成接收人看一下',hops:0,...extra});
export async function prepare(f,{id,relayed=false,answers={},text}={}){
 const p=intent(id,{...(text?{text}:{})}),wire=await f.probe.bot(p);await f.probe.begin(wire);
 const answer={kind:'answer',synthetic:true,human:identity.human,requestId:p.requestId,intentHash:digest(p),answers:{resourceId:summaryId,resourceVersion:'v1',recipient:identity.recipient,purpose,...answers}};
 const human=await f.probe.human(answer),forward=relayed?await f.probe.bot({kind:'relay-human-answer',inner:human}):human;const result=await f.probe.answer(forward,{relayed});return {intent:p,answer,wire,snapshot:result.snapshot};
}
export async function confirm(f,snapshot,decision='approve'){
 const payload={kind:'confirmation',synthetic:true,human:identity.human,requestId:snapshot.requestId,snapshotHash:digest(snapshot),decision,issuedAt:f.clock.now,expiresAt:snapshot.expiresAt,confirmationRef:snapshot.confirmationRef};const proof=await f.probe.human(payload);f.probe.confirm(proof);return proof;
}
export async function ready(f,options){const r=await prepare(f,options);const approval=await confirm(f,r.snapshot);return {...r,approval,delivery:await f.probe.bot({kind:'deliver',snapshot:r.snapshot,confirmation:approval})};}
