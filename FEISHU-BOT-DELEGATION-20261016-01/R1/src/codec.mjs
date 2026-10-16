import {createHash,sign,verify,generateKeyPairSync} from 'node:crypto';
export const canonical=value=>JSON.stringify(sort(value));
function sort(v){if(Array.isArray(v))return v.map(sort);if(v&&typeof v==='object')return Object.fromEntries(Object.keys(v).sort().map(k=>[k,sort(v[k])]));return v;}
export const digest=v=>createHash('sha256').update(typeof v==='string'?v:canonical(v)).digest('hex');
export const keys=()=>{const k=generateKeyPairSync('ed25519');return {privateKey:k.privateKey.export({format:'pem',type:'pkcs8'}),publicKey:k.publicKey.export({format:'pem',type:'spki'})};};
export function signed(channel,principal,payload,privateKey){const content={protocol:'demo-delegation/v1',channel,principal,payload};return {...content,signature:sign(null,Buffer.from(canonical(content)),privateKey).toString('base64')};}
export function exact(o,names){if(!o||typeof o!=='object'||Array.isArray(o)||Object.keys(o).sort().join('|')!==names.slice().sort().join('|'))throw Error('INVALID_FIELDS');}
export function authenticated(envelope,channel,principal,publicKey){
 exact(envelope,['protocol','channel','principal','payload','signature']);
 if(envelope.protocol!=='demo-delegation/v1'||envelope.channel!==channel||envelope.principal!==principal)throw Error('UNTRUSTED_PRINCIPAL');
 const {signature,...content}=envelope;if(typeof signature!=='string'||!verify(null,Buffer.from(canonical(content)),publicKey,Buffer.from(signature,'base64')))throw Error('INVALID_SIGNATURE');return envelope.payload;
}
