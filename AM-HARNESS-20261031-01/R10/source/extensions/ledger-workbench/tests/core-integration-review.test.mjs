import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {randomUUID} from 'node:crypto';
import {ProjectionCache} from '../server/projection-cache.mjs';
import {createLedgerHandler} from '../server/ledger-handler.mjs';
import {sanitizeEvidence} from '../server/evidence-retention.mjs';
import {DemoBridge} from '../demo/demo-bridge.mjs';
import {LedgerError} from '../server/errors.mjs';

const session=()=>({verified:true,id:'integration-review-session',userId:'demo-owner',tenantId:'demo-tenant',
  workspaceId:'ledger-demo',projectIds:['*'],scopes:['ledger:read','am:prepare'],expiresAtMs:Date.now()+600000});

test('cache fingerprint includes the selected project coverage when overall coverage is unchanged',()=>{
  const bridge=new DemoBridge(),cache=new ProjectionCache(bridge),s=session();
  const raw=structuredClone(bridge.snapshot);
  raw.coverage={status:'stale',checkedAt:raw.generatedAt,reasons:['部分来源读取失败']};
  raw.projectCoverage=Object.fromEntries(raw.projects.map(p=>[p.id,{status:'complete',checkedAt:raw.generatedAt,reasons:[]}]));
  cache.accept(raw,s);
  const changed=structuredClone(raw);
  changed.projectCoverage['demo-sample']={status:'stale',checkedAt:raw.generatedAt,reasons:['该项目来源读取失败']};
  const entry=cache.accept(changed,s);
  assert.equal(entry.summaryCache.get('demo-sample').summary.coverage.status,'stale');
});

test('late snapshot cannot replace a newer accepted business version',async()=>{
  const bridge=new DemoBridge(),cache=new ProjectionCache(bridge),s=session();
  const newer=structuredClone(bridge.snapshot),older=structuredClone(newer);
  newer.capturedAtMs=Date.now();newer.generatedAt=new Date(newer.capturedAtMs).toISOString();newer.items[0].version=8;
  older.capturedAtMs=newer.capturedAtMs-1000;older.generatedAt=new Date(older.capturedAtMs).toISOString();older.items[0].version=7;
  cache.accept(newer,s);
  try{cache.accept(older,s);}catch(error){assert.ok(error instanceof LedgerError);}
  assert.equal((await cache.get(s)).snapshot.items[0].version,8);
});

test('explicit source or session scope denial is not an offline-cache fallback',async()=>{
  for(const [code,status] of [['WEB_SCOPE_DENIED',409],['WEB_SOURCE_ACCESS_CHANGED',409],['scope_required',403]]){
    const bridge=new DemoBridge(),cache=new ProjectionCache(bridge,{ttlMs:0}),s=session();
    cache.accept(bridge.snapshot,s);
    bridge.call=async()=>{throw new LedgerError(code,'当前来源权限已经变化',status);};
    await assert.rejects(cache.get(s,{fresh:true}),error=>error.code===code);
  }
});

test('pending refresh preserves the last readable project for GET but blocks mutation prerequisites',async()=>{
  const bridge=new DemoBridge(),cache=new ProjectionCache(bridge,{ttlMs:0}),s=session();
  cache.accept(bridge.snapshot,s);
  bridge.call=async()=>{throw new LedgerError('rpc_pending','正在读取',202,{requestId:'pending-read-review',pollUrl:'/api/v2/ledger/operations/pending-read-review'});};
  bridge.peek=async()=>({state:'pending',requestId:'pending-read-review',expired:false,context:{route:'project',projectId:'demo-sample'}});
  const first=await cache.get(s,{context:{route:'project',projectId:'demo-sample'}});
  assert.equal(first.snapshot.coverage.status,'stale');
  const second=await cache.get(s,{context:{route:'project',projectId:'demo-release'}});
  assert.equal(second.snapshot.coverage.status,'stale');
  await assert.rejects(cache.get(s,{fresh:true,allowStale:false,context:{route:'internal-read'}}),error=>error.status===409);
});

test('expired review evidence removes its copied raw excerpt even without a top-level expiry',()=>{
  const review={id:'review-expired',status:'pending',excerpt:'原始聊天全文',
    evidence:[{sourceId:'s',objectId:'m',version:'v1',rawAvailable:true,quote:'原始聊天全文',rawExpiresAt:'2020-01-01T00:00:00Z'}],
    choices:[{id:'assign',label:'确认归属'}]};
  const sanitized=sanitizeEvidence(review);
  assert.equal(sanitized.evidence[0].quote,null);assert.doesNotMatch(sanitized.excerpt,/原始聊天全文/);
  assert.deepEqual(sanitized.choices,[]);
});

test('a cancelled native item never reaches the prepare bridge through a direct POST',async t=>{
  const bridge=new DemoBridge(),s=session();
  bridge.snapshot.items.find(i=>i.id==='demo-bench').businessState='cancelled';
  const handler=createLedgerHandler({bridge,getSession:()=>s,authorizeMutation:()=>{}});
  const server=createServer((req,res)=>void handler(req,res));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const response=await fetch('http://127.0.0.1:'+server.address().port+'/api/v2/ledger/am/prepare',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({requestId:randomUUID(),projectId:'demo-sample',itemId:'demo-bench'})});
  assert.ok([200,409].includes(response.status));
  assert.equal(bridge.calls.some(c=>c.method==='prepare'),false);
});
