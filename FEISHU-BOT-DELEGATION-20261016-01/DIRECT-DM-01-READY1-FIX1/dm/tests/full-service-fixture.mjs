import {mkdtempSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import net from 'node:net';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {startServer} from '../candidate/scripts/local-http.mjs';
import {PersonalMessageReader} from '../candidate/scripts/personal-message-reader.mjs';
import {createIsolationLedger} from '../candidate/scripts/direct-dm-isolation.mjs';
import * as domain from '../candidate/dist-local/domain.mjs';
import {fixture} from './fixture.mjs';

export const blockedExternal=[];
const spawn=childProcess.spawn,spawnSync=childProcess.spawnSync,execFile=childProcess.execFile,execSync=childProcess.execSync;
childProcess.spawn=childProcess.spawnSync=childProcess.execFile=childProcess.execSync=(...args)=>{blockedExternal.push(String(args[0]));throw Error('FULL_SERVICE_TEST_FORBIDS_EXTERNAL_EXECUTION');};
syncBuiltinESMExports();
export function restoreExecutionGuard(){Object.assign(childProcess,{spawn,spawnSync,execFile,execSync});syncBuiltinESMExports();}
export async function freePort(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const port=s.address().port;await new Promise(r=>s.close(r));return port;}
export async function fullFixture(){
 const f=fixture(),dir=mkdtempSync(join(tmpdir(),'fix1-full-service-')),dataDir=join(dir,'store'),ledger=join(dir,'isolation.sqlite'),scopeFile=join(dir,'synthetic-scope.json');
 createIsolationLedger(ledger);writeFileSync(scopeFile,JSON.stringify({scopeStatus:'confirmed_by_user',historyBackfill:false,collectFrom:domain.feedbackCollectFrom,syntheticFixtureOnly:true}));
 const state={now:f.manifest.issuedAt-1000,messages:[],groups:[],reads:[],externalModels:0};
 const asRaw=m=>({...m,create_time:String(m.create_time),sender:{id:m.sender_id,sender_type:m.sender_type||'user',name:'Synthetic person'},msg_type:'text',body:{content:JSON.stringify({text:m.content})}});
 const client={simulation:true,identity:async()=>f.identity,run:async args=>{
  state.reads.push(args.slice(0,2));
  if(args[0]==='api'&&args[1]==='GET')return {items:state.messages.map(asRaw)};
  if(args[1]==='+messages-search')return {messages:state.messages.map(asRaw),has_more:false};
  if(args[1]==='+chat-list')return {chats:state.groups,has_more:false};
  if(args[1]==='+chat-messages-list')return {messages:state.messages.filter(m=>m.chat_id===args[args.indexOf('--chat-id')+1]).map(asRaw),has_more:false};
  throw Error('UNEXPECTED_MOCK_PLATFORM_CALL');
 }};
 const blockedModel=async()=>{state.externalModels++;throw Error('REAL_MODEL_FORBIDDEN');};
 const base={dataDir,testMode:true,legacy:null,feedbackOptions:{scopeFile,taskClient:client,analyse:blockedModel},agentMonitorOptions:{reader:new PersonalMessageReader({client}),clock:()=>new Date(state.now).toISOString()},eventBridgeOptions:{client},riskAgentOptions:{analyse:blockedModel},intakeOptions:{autoCollect:false,analyse:blockedModel},meetingOptions:{analyse:blockedModel},taskContextOptions:{analyse:blockedModel},caseChatOptions:{analyse:blockedModel},assistantOptions:{codexBin:'/synthetic/disabled-codex'}};
 let app;
 async function start({configured=true,configuredFile=ledger,...extra}={}){
  app=await startServer({...base,port:await freePort(),...(configured?{directDmLedger:configuredFile}:{}),directDmIsolationOptions:{clock:()=>state.now},...extra});return app;
 }
 async function close(){if(app){await app.close();app=null;}}
 function arm(){app.store.directDmIsolation.register(f.manifest);}
 return {f,dir,dataDir,ledger,state,client,base,start,close,arm,get app(){return app;},dispose:async()=>{await close();f.close();}};
}
