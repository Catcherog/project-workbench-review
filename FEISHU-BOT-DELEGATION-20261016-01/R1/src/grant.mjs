import {authenticated,exact,digest} from './codec.mjs';import {identity,authorize} from './policy.mjs';
export const snapshotFields=['protocol','requestId','tenant','app','bot','human','target','targetApp','recipient','action','purpose','resourceId','resourceVersion','body','contentSha256','policyVersion','bindingVersion','issuedAt','expiresAt','nonce','confirmationRef','hops'];
export function validateSnapshot(snapshot){exact(snapshot,snapshotFields);if(snapshot.protocol!=='demo-delegation/v1'||typeof snapshot.body!=='string'||digest(snapshot.body)!==snapshot.contentSha256)throw Error('SNAPSHOT_INTEGRITY');}
export function humanProof(envelope,trust){return authenticated(envelope,'human',identity.human,trust.human);}
export function validateConfirmation(envelope,snapshot,trust,now){const p=humanProof(envelope,trust);exact(p,['kind','synthetic','human','requestId','snapshotHash','decision','issuedAt','expiresAt','confirmationRef']);if(p.kind!=='confirmation'||p.synthetic!==true||p.human!==snapshot.human||p.requestId!==snapshot.requestId||p.snapshotHash!==digest(snapshot)||p.expiresAt!==snapshot.expiresAt||p.confirmationRef!==snapshot.confirmationRef||p.issuedAt<snapshot.issuedAt||p.issuedAt>now||now>=p.expiresAt||!['approve','reject'].includes(p.decision))throw Error('CONFIRMATION_BINDING');return p;}
export function validateDelivery(envelope,row,trust,policy,now){
 const p=authenticated(envelope,'bot',identity.bot,trust.bot);exact(p,['kind','snapshot','confirmation']);if(p.kind!=='deliver')throw Error('UNSUPPORTED_MESSAGE_TYPE');validateSnapshot(p.snapshot);
 if(!row?.data.snapshot||digest(p.snapshot)!==digest(row.data.snapshot))throw Error('CONFIRMED_SNAPSHOT_CHANGED');
 authorize(p.snapshot,policy,now);
 if(!row.data.confirmation||digest(p.confirmation)!==digest(row.data.confirmation))throw Error('NO_INDEPENDENT_CONFIRMATION');
 const c=validateConfirmation(p.confirmation,p.snapshot,trust,now);if(c.decision!=='approve')throw Error('HUMAN_REJECTED');return p.snapshot;
}
