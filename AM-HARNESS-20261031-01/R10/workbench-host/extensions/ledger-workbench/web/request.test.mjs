import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const compiled=await build({
  stdin:{contents:"export * from './request.ts'; export * from './request-error.ts'; export * from './host-adapter.ts';",resolveDir:dirname(fileURLToPath(import.meta.url)),loader:'ts'},
  bundle:true,write:false,platform:'node',format:'esm',target:'es2022',
});
const {withLedgerOperations, LedgerOperationError, LedgerRequestError, readLedgerResponse, isLedgerAccessError, createNativeLedgerRequest}=
  await import('data:text/javascript;base64,'+Buffer.from(compiled.outputFiles[0].contents).toString('base64'));

test('a queued mutation is submitted once and only its original operation is polled', async () => {
  const calls = [];
  let polls = 0;
  const request = withLedgerOperations(async (path, body) => {
    calls.push({path, body});
    if (body) return {state:'pending',requestId:'original_1',pollUrl:'/api/v2/ledger/operations/original_1'};
    return ++polls === 1
      ? {state:'pending',requestId:'original_1',pollUrl:'/api/v2/ledger/operations/original_1'}
      : {previewId:'verified_preview',body:'原正文'};
  }, {intervalMs:50});
  assert.deepEqual(await request('/api/v2/ledger/am/prepare',{requestId:'original_1',itemId:'item_1'}),
    {previewId:'verified_preview',body:'原正文'});
  assert.equal(calls.filter(call=>call.body).length,1);
  assert.equal(calls.filter(call=>!call.body).length,2);
  assert.ok(calls.slice(1).every(call=>call.path==='/api/v2/ledger/operations/original_1'));
});

test('retry after a polling disconnect resumes the existing operation without another POST', async () => {
  let posts = 0, polls = 0;
  const request = withLedgerOperations(async (_path, body) => {
    if (body) { posts++; return {state:'pending',requestId:'original_2',pollUrl:'/api/v2/ledger/operations/original_2'}; }
    if (++polls===1) throw new Error('network interrupted');
    return {presentationId:'presented',expiresAtMs:12345};
  }, {intervalMs:50});
  const payload={requestId:'original_2',previewId:'preview_2'};
  await assert.rejects(request('/api/v2/ledger/am/present',payload), LedgerOperationError);
  assert.deepEqual(await request('/api/v2/ledger/am/present',payload), {presentationId:'presented',expiresAtMs:12345});
  assert.equal(posts,1);
});

test('a polling location outside the ledger operation boundary is never requested', async () => {
  let calls=0;
  const request=withLedgerOperations(async()=>{calls++;return {
    state:'pending',requestId:'original_3',pollUrl:'https://outside.invalid/collect'};});
  await assert.rejects(request('/api/v2/ledger/am/prepare',{requestId:'original_3'}),LedgerOperationError);
  assert.equal(calls,1);
});

test('an operation cannot silently change identity while polling', async () => {
  let calls=0;
  const request=withLedgerOperations(async()=>++calls===1
    ? {state:'pending',requestId:'original_4',pollUrl:'/api/v2/ledger/operations/original_4'}
    : {state:'pending',requestId:'different_4',pollUrl:'/api/v2/ledger/operations/different_4'}, {intervalMs:50});
  await assert.rejects(request('/api/v2/ledger/am/prepare',{requestId:'original_4'}),LedgerOperationError);
  assert.equal(calls,2);
});

test('permission loss while polling preserves status and code for clearing inaccessible UI', async () => {
  const denial=new LedgerRequestError('scope changed',{status:403,code:'WEB_SCOPE_DENIED'});
  const request=withLedgerOperations(async(_path,body)=>{
    if(body)return{state:'pending',requestId:'original_5',pollUrl:'/api/v2/ledger/operations/original_5'};
    throw denial;
  },{intervalMs:50});
  await assert.rejects(request('/api/v2/ledger/am/present',{requestId:'original_5'}),error=>error===denial&&isLedgerAccessError(error));
});

test('structured source-access changes and non-JSON 401 responses retain their access classification',async()=>{
  await assert.rejects(readLedgerResponse(new Response(JSON.stringify({error:{code:'WEB_SOURCE_ACCESS_CHANGED',message:'source changed'}}),
    {status:409,headers:{'Content-Type':'application/json'}})),error=>error.status===409&&error.code==='WEB_SOURCE_ACCESS_CHANGED'&&isLedgerAccessError(error));
  await assert.rejects(readLedgerResponse(new Response('Sign in',{status:401})),error=>error.status===401&&isLedgerAccessError(error));
  assert.equal(isLedgerAccessError(new TypeError('network failure')),false);
});

test('native transport reuses the host token and never sends it outside the same-origin ledger scope',async()=>{
  const previousWindow=globalThis.window;
  globalThis.window={location:{origin:'http://127.0.0.1:45678'}};
  const calls=[];
  try{
    const request=createNativeLedgerRequest({readToken:()=> 'synthetic-token',fetcher:async(path,options)=>{
      calls.push({path,options});return new Response(JSON.stringify({ok:true}),{headers:{'Content-Type':'application/json'}});
    }});
    await request('/api/v2/ledger/bootstrap');
    assert.equal(calls[0].options.headers['X-Workbench-Token'],'synthetic-token');
    assert.equal(calls[0].options.headers['X-Workbench-Client'],'ui');
    assert.equal(Object.keys(calls[0].options.headers).some(key=>['origin','userid','tenantid'].includes(key.toLowerCase())),false);
    await assert.rejects(request('https://outside.invalid/api/v2/ledger/bootstrap'),error=>error.status===403);
    await assert.rejects(request('/api/v2/ledger/../status'),error=>error.status===403);
    assert.equal(calls.length,1);
  }finally{if(previousWindow===undefined)delete globalThis.window;else globalThis.window=previousWindow;}
});

