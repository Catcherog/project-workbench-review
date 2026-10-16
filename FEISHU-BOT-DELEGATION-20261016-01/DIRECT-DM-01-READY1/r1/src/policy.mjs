import fs from 'node:fs';
export const identity={tenant:'demo-tenant',app:'demo-engineer-app',bot:'demo-engineer-bot',human:'demo-engineer-01',targetApp:'demo-muyi-app',target:'demo-muyi-bot',recipient:'demo-muyi-01'};
export const summaryId='demo-project-x/test-summary';
export const action='deliver-summary',purpose='review-test-summary';
export function readPolicy(file){return JSON.parse(fs.readFileSync(file,'utf8'));}
export function checkIdentity(p,policy){
 if(p.tenant!==identity.tenant||p.app!==identity.app||p.bot!==identity.bot||p.human!==identity.human||p.target!==identity.target||p.targetApp!==identity.targetApp)throw Error('IDENTITY_BINDING_MISMATCH');
 if(!policy.binding.active||policy.binding.bot!==p.bot||policy.binding.human!==p.human)throw Error('BINDING_REVOKED_OR_UNKNOWN');
}
export function authorize(p,policy,now,{versions=true}={}){
 checkIdentity(p,policy);
 if(p.action!==action||p.purpose!==purpose||p.resourceId!==summaryId||p.resourceVersion!==policy.resourceVersion||p.recipient!==identity.recipient||p.hops!==0)throw Error('CAPABILITY_OR_RESOURCE_DENIED');
 if(!policy.read||!policy.disclose)throw Error(policy.read?'DISCLOSURE_DENIED':'READ_DENIED');
 if(policy.revokedRequests.includes(p.requestId))throw Error('DELEGATION_REVOKED');
 if(now>=p.expiresAt||p.expiresAt-p.issuedAt>300000||p.issuedAt>now)throw Error('EXPIRED_OR_INVALID_WINDOW');
 if(versions&&(p.policyVersion!==policy.version||p.bindingVersion!==policy.binding.version))throw Error('RULE_VERSION_CHANGED');
}
export function defaultPolicy(){return {version:1,binding:{version:1,active:true,bot:identity.bot,human:identity.human},read:true,disclose:true,resourceVersion:'v1',revokedRequests:[]};}
