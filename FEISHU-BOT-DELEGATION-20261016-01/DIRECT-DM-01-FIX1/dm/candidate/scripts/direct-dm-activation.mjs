// Persistent startup binding. This module is loaded only by the candidate host.
import {existsSync,readFileSync,realpathSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {DirectDmIsolation} from './direct-dm-isolation.mjs';
import {durableWrite} from './local-store.mjs';

export const activationKey='directDmIsolationRequired';
export const activationFile=dir=>join(dir,'direct-dm-isolation-required.json');
const hash=s=>createHash('sha256').update(s).digest('hex');
const fail=message=>Object.assign(Error(message),{status:409});
function readMarker(file){
 try{return JSON.parse(readFileSync(file,'utf8'));}catch{throw fail('ISOLATION_PERSISTENT_MARKER_INVALID');}
}
function validateRegistration(value){
 if(value?.version!==1||typeof value.ledgerPath!=='string'||!value.ledgerPath||typeof value.ledgerId!=='string'||!Array.isArray(value.requestHashes)||value.requestHashes.some(x=>!(/^[a-f0-9]{64}$/).test(x)))throw fail('ISOLATION_PERSISTENT_REGISTRATION_INVALID');
}
export function attachDirectDmIsolation({store,configuredFile,clock,inspectPid}={}){
 const markerFile=activationFile(store.dir),marker=existsSync(markerFile)?readMarker(markerFile):null;
 const saved=store.getSetting(activationKey),version=store.db.prepare('PRAGMA user_version').get().user_version;
 const required=!!saved||!!marker||version===3;
 if(required){
  if(!saved||!marker||version!==3)throw fail('ISOLATION_PERSISTENT_REGISTRATION_MISSING');
  validateRegistration(saved);validateRegistration(marker);
  if(JSON.stringify(saved)!==JSON.stringify(marker))throw fail('ISOLATION_PERSISTENT_REGISTRATION_MISMATCH');
 }
 if(!required&&!configuredFile)return null; // A never-enabled installation is unchanged.
 const requested=configuredFile?resolve(configuredFile):saved.ledgerPath;
 if(!existsSync(requested))throw fail('ISOLATION_LEDGER_MISSING');
 const canonical=realpathSync(requested);
 if(required&&canonical!==saved.ledgerPath)throw fail('ISOLATION_LEDGER_REDIRECT_DENIED');
 let gate;
 const persist=(instance,requestId)=>{
  const prior=store.getSetting(activationKey);
  if(prior){
   validateRegistration(prior);
   if(prior.ledgerId!==instance.ledgerId||prior.ledgerPath!==instance.file)throw fail('ISOLATION_LEDGER_ID_CHANGED');
   if(!existsSync(markerFile)||JSON.stringify(readMarker(markerFile))!==JSON.stringify(prior))throw fail('ISOLATION_PERSISTENT_REGISTRATION_MISMATCH');
  }
  const present=instance.db.prepare('SELECT id FROM requests').all().map(x=>hash(x.id));
  const hashes=[...new Set([...(prior?.requestHashes||[]),...present,...(requestId?[hash(requestId)]:[])])].sort();
  const record={version:1,ledgerPath:instance.file,ledgerId:instance.ledgerId,requestHashes:hashes};
  // Commit the latch before requests/effects. A torn activation fails closed.
  // Version 3 intentionally prevents the previous host (max version 2) from booting.
  store.transaction(()=>{store.setSetting(activationKey,record);store.db.exec('PRAGMA user_version=3');});
  durableWrite(markerFile,JSON.stringify(record));
 };
 try{
  gate=new DirectDmIsolation(canonical,{clock,inspectPid,activate:persist});
  if(required){
   if(gate.ledgerId!==saved.ledgerId)throw fail('ISOLATION_LEDGER_ID_CHANGED');
   const hashes=new Set(gate.db.prepare('SELECT id FROM requests').all().map(x=>hash(x.id)));
   if(saved.requestHashes.some(x=>!hashes.has(x)))throw fail('ISOLATION_REGISTERED_REQUEST_MISSING');
  }else if(gate.db.prepare('SELECT COUNT(*) n FROM requests').get().n)persist(gate);
  Object.defineProperty(store,'directDmIsolation',{value:gate,writable:false,configurable:false});
  return gate;
 }catch(e){gate?.close();throw e;}
}
