import {startServer} from '../workbench-host/scripts/local-http.mjs';
import {DemoBridge} from '../worktree/extensions/ledger-workbench/demo/demo-bridge.mjs';
import {fileURLToPath} from 'node:url';
const bridge=new DemoBridge();
bridge.snapshot.workspaceId='official';
const app=await startServer({
  dataDir:fileURLToPath(new URL('../private/workbench-preview-data/',import.meta.url)),
  port:5184,testMode:true,legacy:null,
  ledgerWorkbench:{enabled:true,bridge,binding:{userId:'demo-owner',tenantId:'demo-tenant',workspaceId:'official',
    projectIds:['demo-sample','demo-release','demo-outside'],
    scopes:['ledger:read','am:prepare','am:approve','review:resolve','reminder:manage']}},
});
console.log(JSON.stringify({origin:app.origin,synthetic:true,production_connected:false}));
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,async()=>{await app.close();process.exit(0);});
