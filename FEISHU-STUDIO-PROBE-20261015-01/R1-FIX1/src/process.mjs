import {spawn,spawnSync} from 'node:child_process';

export const cleanEnv=()=>Object.fromEntries(['HOME','USER','LOGNAME','LANG','TMPDIR'].filter(k=>process.env[k]).map(k=>[k,process.env[k]]).concat([['PATH','/usr/bin:/bin:/usr/sbin:/sbin']]));

export function processIdentity(pid){
  if(!Number.isSafeInteger(pid)||pid<=0)return null;
  const r=spawnSync('/bin/ps',['-p',String(pid),'-o','lstart=,comm='],{encoding:'utf8',timeout:1000});
  if(r.status===1&&!r.stdout.trim())return null;
  if(r.status!==0)throw Error('PROCESS_INSPECTION_UNAVAILABLE');
  return r.stdout.trim();
}
export function liveGroupMembers(pgid){
  try{process.kill(-pgid,0);}catch(e){if(e.code==='ESRCH')return [];return null;}
  const r=spawnSync('/bin/ps',['-A','-o','pid=,pgid=,stat='],{encoding:'utf8',timeout:500,maxBuffer:2**20});
  if(r.status!==0)return null;
  return r.stdout.trim().split('\n').map(s=>s.trim().split(/\s+/)).filter(x=>Number(x[1])===pgid&&!x[2]?.startsWith('Z')).map(x=>Number(x[0]));
}

/** Own process group only. Completion waits for exit/cleanup evidence, not just kill(). */
export function processRun(binary,args,{cwd,input='',timeoutMs=180000,maxBytes=5242880,env=cleanEnv(),signal,onRecord,onSpawn,terminateGraceMs=250,terminateBoundMs=1800}={}){
  if(!Number.isFinite(timeoutMs)||timeoutMs<=0||terminateGraceMs<0||terminateBoundMs<terminateGraceMs||terminateBoundMs>4000)throw Error('INVALID_PROCESS_LIMIT');
  const startedAt=new Date().toISOString();
  if(signal?.aborted)return Promise.resolve({pid:null,pgid:null,spawned:false,startedAt,endedAt:startedAt,exit:null,signal:null,stopReason:'cancelled',terminationConfirmed:true,stdout:'',stderr:'',signals:[],residualPids:[]});
  return new Promise(resolve=>{
    let child,stdout='',stderr='',line='',bytes=0,closed=false,exit=null,exitSignal=null,stopReason='',requestedAt=0,done=false,pollTimer,timeoutTimer;
    const signals=[];let forced=false,spawnError=null,identity=null;
    const emitLine=s=>{if(!s.trim())return;let value;try{value=JSON.parse(s);}catch{return;}try{onRecord?.(value);}catch{stop('record_error');}};
    const clear=()=>{clearTimeout(pollTimer);clearTimeout(timeoutTimer);signal?.removeEventListener('abort',abort);};
    const finish=(confirmed,residual=[])=>{
      if(done)return;done=true;clear();
      if(line){emitLine(line);line='';}
      if(!confirmed){child?.unref();child?.stdout?.destroy();child?.stderr?.destroy();}
      resolve({pid:child?.pid??null,pgid:child?.pid??null,identity,spawned:!!child?.pid,startedAt,endedAt:new Date().toISOString(),exit,signal:exitSignal,stopReason,spawnError,terminationConfirmed:confirmed,signals,residualPids:residual,stdout,stderr});
    };
    const send=s=>{if(!child?.pid)return;try{process.kill(-child.pid,s);signals.push({signal:s,at:new Date().toISOString()});}catch(e){if(e.code!=='ESRCH')signals.push({signal:s,error:e.code});}};
    const poll=()=>{
      if(done)return;
      const members=child?.pid?liveGroupMembers(child.pid):[];
      if(closed&&members?.length===0)return finish(true);
      const elapsed=Date.now()-requestedAt;
      if(!forced&&elapsed>=terminateGraceMs){forced=true;send('SIGKILL');}
      if(elapsed>=terminateBoundMs)return finish(false,members);
      pollTimer=setTimeout(poll,25);
    };
    const stop=reason=>{if(done||stopReason)return;stopReason=reason;requestedAt=Date.now();send('SIGTERM');poll();};
    const abort=()=>stop('cancelled');
    try{child=spawn(binary,args,{cwd,env,stdio:['pipe','pipe','pipe'],shell:false,detached:true});}catch(e){spawnError=e.code;stopReason='spawn_error';closed=true;return finish(true);}
    child.once('spawn',()=>{try{identity=processIdentity(child.pid);onSpawn?.({pid:child.pid,pgid:child.pid,identity,startedAt});}catch{stop('spawn_receipt_error');}});
    child.stdout.on('data',b=>{if(done)return;bytes+=b.length;if(bytes>maxBytes){stop('output_limit');return;}stdout+=b;line+=b;let n;while((n=line.indexOf('\n'))>=0){const s=line.slice(0,n);line=line.slice(n+1);emitLine(s);}});
    child.stderr.on('data',b=>{if(done)return;bytes+=b.length;if(bytes>maxBytes){stop('output_limit');return;}stderr+=b;});
    child.once('error',e=>{spawnError=e.code;stopReason='spawn_error';closed=true;finish(true);});
    child.once('close',(code,sig)=>{closed=true;exit=code;exitSignal=sig;if(done)return;if(stopReason){poll();return;}const members=child.pid?liveGroupMembers(child.pid):[];if(members?.length===0)finish(true);else stop('orphaned_children');});
    timeoutTimer=setTimeout(()=>stop('timeout'),timeoutMs);
    signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
    child.stdin.on('error',()=>{});child.stdin.end(input);
  });
}
