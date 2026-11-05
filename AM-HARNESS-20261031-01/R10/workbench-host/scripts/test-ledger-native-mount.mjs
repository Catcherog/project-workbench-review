import assert from 'node:assert/strict';
import {mkdtemp,realpath,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {startServer} from './local-http.mjs';
import {DemoBridge} from '../extensions/ledger-workbench/demo/demo-bridge.mjs';

const directory=await realpath(await mkdtemp(join(tmpdir(),'r10-host-ledger-')));
const bridge=new DemoBridge();bridge.snapshot.workspaceId='official';
let app;
try {
  app=await startServer({dataDir:directory,port:5186,testMode:true,legacy:null,ledgerWorkbench:{enabled:true,bridge,
    binding:{userId:'demo-owner',tenantId:'demo-tenant',workspaceId:'official',projectIds:['demo-sample'],scopes:['ledger:read']}}});
  const status=await fetch(app.origin+'/api/v2/status').then(r=>r.json());
  assert.deepEqual(status.ledgerWorkbench,{enabled:true,workspaceId:'official'});
  assert.equal((await fetch(app.origin+'/api/v2/ledger/bootstrap')).status,403);
  const headers={'X-Workbench-Token':status.csrfToken,'X-Workbench-Client':'ui'};
  let response=await fetch(app.origin+'/api/v2/ledger/bootstrap',{headers});assert.equal(response.status,200);
  const data=await response.json();assert.ok(JSON.stringify(data).includes('demo-sample'));
  assert.equal((await fetch(app.origin+'/api/v2/ledger/bootstrap',{headers:{...headers,Origin:'https://untrusted.example'}})).status,403);
  assert.equal((await fetch(app.origin+'/api/v2/ledger/bootstrap',{headers:{...headers,'X-Workbench-Client':'codex'}})).status,403);
  response=await fetch(app.origin+'/api/v2/ledger/am/approve',{method:'POST',headers:{...headers,'Content-Type':'application/json'},
    body:JSON.stringify({scopes:['am:approve'],userId:'demo-owner',previewId:'forged-preview',requestId:'forged-request'})});
  assert.equal(response.status,403);assert.equal(bridge.calls.filter(c=>c.method==='approve').length,0);
  await app.close();app=null;
  app=await startServer({dataDir:directory,port:5187,testMode:true,legacy:null});
  const disabled=await fetch(app.origin+'/api/v2/status',{headers:{Connection:'close'}}).then(r=>r.json());assert.deepEqual(disabled.ledgerWorkbench,{enabled:false});
  console.log(JSON.stringify({checks:7,passed:7,real_business_writes:0,original_host_authorization_preserved:true}));
} finally {if(app)await app.close();await rm(directory,{recursive:true,force:true});}
