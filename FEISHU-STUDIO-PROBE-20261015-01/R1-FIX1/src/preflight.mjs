// Read-only by default: no model, Feishu API, event bus, login or install action.
import fs from 'node:fs/promises';import {resolve,join} from 'node:path';import {spawnSync} from 'node:child_process';import {fileURLToPath} from 'node:url';import {DatabaseSync} from 'node:sqlite';
import {buildLaunch,hash} from './launch.mjs';
const root=resolve(fileURLToPath(new URL('..',import.meta.url))),job=join(root,'runtime','preflight-synthetic');
const run=(cmd,args)=>{const r=spawnSync(cmd,args,{encoding:'utf8',timeout:5000,maxBuffer:2**20});return {exit:r.status,text:(r.stdout||'')+(r.stderr||'')};};
const hardware=process.platform==='darwin'?run('/usr/sbin/system_profiler',['SPHardwareDataType']).text.match(/Model Name:\s*(.*)/)?.[1]:'non-macOS';
const binary=process.env.PROBE_CODEX_BIN||run('/usr/bin/which',['codex']).text.trim();
let sqlite=false;try{const d=new DatabaseSync(':memory:');sqlite=d.prepare('SELECT 1 AS ok').get().ok===1;d.close();}catch{}
let version={exit:null,text:''},help={exit:null,text:''},auth={exit:null,text:''},debugHelp={exit:null,text:''};
if(binary.startsWith('/')){version=run(binary,['--version']);help=run(binary,['exec','--help']);auth=run(binary,['login','status']);debugHelp=run(binary,['debug','prompt-input','--help']);}
const launch=buildLaunch({binary,jobDir:job,outputFile:join(root,'runtime','preflight-receipts','final.json'),schemaFile:join(root,'runtime','preflight-receipts','schema.json')});
const supported=['--ignore-user-config','--ignore-rules','--output-schema','--ephemeral','--json'].every(x=>help.text.includes(x));
const rows=run('/bin/ps',['-axo','pid=,comm=']).text.split('\n').map(s=>s.trim().match(/^(\d+)\s+(.+)$/)).filter(Boolean);
const candidates=rows.filter(m=>m[2].endsWith('/lark-cli')||m[2]==='lark-cli');
const receiverCount=candidates.filter(m=>/\sevent\s+(consume|_bus)(\s|$)/.test(run('/bin/ps',['-p',m[1],'-o','args=']).text)).length;
const result={at:new Date().toISOString(),machine:hardware||'unknown',platform:process.platform,arch:process.arch,node:process.version,nodeSqliteWorks:sqlite,studioTested:false,codexVersion:version.exit===0?version.text.trim():'unavailable',requiredExecFlagsPresent:supported,existingReceiverProcessCount:receiverCount,receiverDiscovery:'local process metadata only; no bus connection; absence does not prove no other host/cloud consumer',authStatus:auth.exit===0&&/logged in/i.test(auth.text)?'existing_login_reported':auth.exit===0?'status_returned':'unavailable_or_logged_out',launch:launch.descriptor,launchFingerprint:launch.fingerprint,diagnostic:{entry:'debug prompt-input',supportsIgnoreUserConfig:debugHelp.text.includes('--ignore-user-config'),equivalentExecContextProven:false,reason:'help/flag inspection cannot prove actual bootstrap context; no non-equivalent prompt dump presented as proof'},bootstrapBoundary:{parentProcess:'operator account and inherited HOME; not a separate execution identity',commandProcess:'named restricted profile, separately tested',externalTools:'flags disable tools; effective absence not proven by this preflight'},liveReady:false,realModelCalls:0,feishuApiCalls:0,eventBusConnections:0,installedSoftware:0};
if(process.argv.includes('--write')){await fs.mkdir(join(root,'evidence','fix1'),{recursive:true});await fs.writeFile(join(root,'evidence','fix1','preflight.json'),JSON.stringify(result,null,2));}
console.log(JSON.stringify(result,null,2));
