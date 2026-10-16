import {readFileSync,realpathSync} from 'node:fs';
import {join,relative,isAbsolute} from 'node:path';
import {DirectDmAuthority,readPrivateJson,digest,canonical,bindingOf} from './direct-dm-authority.mjs';
import {DirectDmTransport} from './direct-dm-transport.mjs';
import {DirectDmController} from './direct-dm-controller.mjs';
// Local setup file is outside every message/body/HTTP input path. No setup
// writes, real request registration, sender or listener starts on import.
export function verifyBuild(root,manifestFile){
 const base=realpathSync(root),list=JSON.parse(readFileSync(manifestFile,'utf8'));
 if(list.version!==1||!Array.isArray(list.files)||!list.files.length)throw Error('BUILD_MANIFEST_INVALID');
 const seen=new Set();
 for(const row of list.files){
  if(!row.path||isAbsolute(row.path)||row.path.split('/').includes('..')||seen.has(row.path))throw Error('BUILD_PATH_INVALID');
  seen.add(row.path);const file=realpathSync(join(base,row.path));
  if(relative(base,file).startsWith('..')||digest(readFileSync(file,'utf8'))!==row.sha256)throw Error('BUILD_BYTES_CHANGED');
 }
 // Mandatory executable paths cannot be silently omitted from the hash list.
 for(const file of ['direct-dm-authority','direct-dm-transport','direct-dm-controller','direct-dm-runtime','direct-dm-isolation','direct-dm-activation','local-http','local-store','feishu-event-bridge','personal-message-reader','agent-monitor','core-feishu-input'])if(!seen.has('scripts/'+file+'.mjs'))throw Error('BUILD_MANIFEST_INCOMPLETE');
 return digest(list);
}
function assertExecutionBinding(manifest,...bindings){
 const expected=bindingOf(manifest);
 for(const value of [expected,...bindings]){
  // Reject missing, non-string, internally inconsistent or extra binding fields.
  // Comparing only each source to itself would recreate READY1-B01.
  if(!value||Object.values(bindingOf(value)).some(v=>typeof v!=='string'||!v)||value.scope!==value.tenantKey+'/'+value.appId||value.ownerId===value.participantId||value.ownerChatId===value.participantChatId||canonical(value)!==canonical(expected))throw Error('EXECUTION_BINDING_MISMATCH');
 }
}
export function composeDirectDmController({store,configFile,root,runner,clock}={}){
 if(!configFile)return null;const c=readPrivateJson(configFile);
 if(c.enabled!==true)return null;
 if(c.version!==1||!store.directDmIsolation)throw Error('ISOLATION_REQUIRED_FOR_EXECUTION');
 const buildHash=verifyBuild(root,c.buildManifest);
 if(c.buildHash!==buildHash)throw Error('BUILD_SNAPSHOT_MISMATCH');
 const authority=new DirectDmAuthority({approvalFile:c.approvalFile,publicKey:c.publicKey,publicKeyHash:c.publicKeyHash,buildHash,store,clock});
 const transport=new DirectDmTransport({cli:c.cli,cliHash:c.cliHash,binding:c.binding,...(runner?{runner}:{})});
 // Recheck bytes for each action; a startup-only verification is insufficient.
 const verifyLocal=manifest=>{
  if(verifyBuild(root,c.buildManifest)!==buildHash)throw Error('BUILD_SNAPSHOT_MISMATCH');
  if(canonical(JSON.parse(readFileSync(configFile,'utf8')))!==canonical(c))throw Error('EXECUTION_CONFIGURATION_CHANGED');
  // authority.admit/current separately verify that this exact manifest and
  // binding match the signed approval. Both checks precede registration/effects.
  assertExecutionBinding(manifest,c.binding,transport.binding);
 };
 const checked={current:m=>{verifyLocal(m);return authority.current(m);},admit:m=>{verifyLocal(m);return authority.admit(m);}};
 return new DirectDmController({gate:store.directDmIsolation,authority:checked,transport});
}
