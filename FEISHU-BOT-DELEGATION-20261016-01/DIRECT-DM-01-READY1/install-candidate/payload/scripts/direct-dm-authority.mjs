// No approval writer or private key is shipped. Trust is provisioned only by a
// separately approved installation. Chat messages can never supply this object.
import {createHash,createPublicKey,verify} from 'node:crypto';
import {readFileSync,realpathSync,statSync} from 'node:fs';
import {activationKey,activationFile} from './direct-dm-activation.mjs';

const fail=code=>{throw Object.assign(Error(code),{status:409});};
export const canonical=value=>JSON.stringify(sort(value));
function sort(v){return Array.isArray(v)?v.map(sort):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,sort(v[k])])):v;}
export const digest=value=>createHash('sha256').update(typeof value==='string'?value:canonical(value)).digest('hex');
const fields=['appId','tenantKey','scope','ownerId','participantId','botId','participantChatId','ownerChatId','policyVersion','resourceVersion','purpose','summaryHash','previewHash'];
export function bindingOf(m){return Object.fromEntries(fields.map(k=>[k,m[k]]));}
export function readPrivateJson(file){
 const s=statSync(file);if(!s.isFile()||(s.mode&0o077)!==0||s.uid!==process.getuid())fail('AUTHORITY_FILE_NOT_PRIVATE');
 return JSON.parse(readFileSync(file,'utf8'));
}
export class DirectDmAuthority {
 constructor({approvalFile,publicKey,publicKeyHash,buildHash,store,clock=()=>Date.now()}={}){
  if(!approvalFile||!publicKey||!(/^[a-f0-9]{64}$/).test(publicKeyHash||'')||!(/^[a-f0-9]{64}$/).test(buildHash||''))fail('TRUST_NOT_PROVISIONED');
  this.key=createPublicKey(publicKey);if(this.key.asymmetricKeyType!=='ed25519'||digest(this.key.export({type:'spki',format:'pem'}))!==publicKeyHash)fail('TRUST_KEY_MISMATCH');
  Object.assign(this,{approvalFile,buildHash,store,clock});
 }
 approval(manifest){
  const envelope=readPrivateJson(this.approvalFile),p=envelope.payload;
  if(!p||!verify(null,Buffer.from(canonical(p)),this.key,Buffer.from(envelope.signature||'','base64')))fail('APPROVAL_SIGNATURE_INVALID');
  if(p.version!==1||p.task!=='DIRECT-DM-01-READY1'||p.revoked!==false||p.buildHash!==this.buildHash||p.manifestHash!==digest(manifest)||canonical(p.binding)!==canonical(bindingOf(manifest)))fail('APPROVAL_BINDING_INVALID');
  if(!Number.isSafeInteger(p.notBefore)||!Number.isSafeInteger(p.expiresAt)||this.clock()<p.notBefore||this.clock()>=p.expiresAt)fail('APPROVAL_EXPIRED');
  for(const k of ['review','installation','exactText','isolationPrinciple','memberVisibility','conversationBinding','read','disclose']){
   const a=p.evidence?.[k];if(a?.approved!==true||typeof a.reference!=='string'||!a.reference||!(/^[a-f0-9]{64}$/).test(a.sha256||''))fail('APPROVAL_EVIDENCE_MISSING:'+k);
  }
  if(!this.store.directDmIsolation||p.ledgerId!==this.store.directDmIsolation.ledgerId)fail('INSTALLATION_LEDGER_NOT_VERIFIED');
  return p;
 }
 admit(manifest){
  this.approval(manifest);
  // This local-only operation is separate from installation and sending. The
  // one-request limit cannot be reset by stop/expiry or removing configuration.
  const gate=this.store.directDmIsolation;
  if(gate.db.prepare('SELECT COUNT(*) n FROM requests').get().n!==0)fail('LIVE_ROUND_ALREADY_REGISTERED');
  if(this.clock()<manifest.issuedAt||this.clock()>=manifest.expiresAt)fail('REQUEST_EXPIRED');
  gate.register(manifest);return gate.status(manifest.id);
 }
 current(manifest){
  const p=this.approval(manifest);
  const gate=this.store.directDmIsolation,saved=this.store.getSetting(activationKey);
  if(!gate||p.ledgerId!==gate.ledgerId||saved?.ledgerId!==gate.ledgerId||saved.ledgerPath!==realpathSync(gate.file)||!saved.requestHashes?.includes(digest(manifest.id))||this.store.db.prepare('PRAGMA user_version').get().user_version!==3)fail('INSTALLATION_LATCH_NOT_VERIFIED');
  if(canonical(JSON.parse(readFileSync(activationFile(this.store.dir),'utf8')))!==canonical(saved))fail('INSTALLATION_MARKER_MISMATCH');
  if(canonical(gate.request(manifest.id).manifest)!==canonical(manifest))fail('REGISTERED_MANIFEST_CHANGED');
  return {...bindingOf(manifest),reviewApproved:true,exactTextApproved:true,isolationInstalled:true,memberVisible:true,bindingVerified:true,readAllowed:true,discloseAllowed:true};
 }
}
