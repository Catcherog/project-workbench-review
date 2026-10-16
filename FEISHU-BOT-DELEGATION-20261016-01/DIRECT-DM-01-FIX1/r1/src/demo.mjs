import fs from 'node:fs';import {join} from 'node:path';import {createFixture,ready} from './fixture.mjs';
const output=[];
for(const relayed of [false,true]){
 const f=createFixture(relayed?'demo-relayed':'demo-direct');let evidence;
 try{const r=await ready(f,{relayed});const outcome=await f.probe.deliver(r.delivery);evidence={synthetic:true,trustedPublicKeys:f.probe.trust,policy:f.probe.policy(),confirmationMode:relayed?'via-engineer-bot':'direct-human-adapter',outcome,counts:f.probe.counts(),receiverRecords:f.received(),transcript:f.probe.transcript,adapterProcesses:f.probe.runtime.records};}
 finally{const stop=await f.close();if(evidence)evidence.stop=stop;}
 fs.writeFileSync(join(f.root,'demo-evidence.json'),JSON.stringify(evidence,null,2));output.push({root:f.root,...evidence});
}
fs.mkdirSync('evidence',{recursive:true});fs.writeFileSync('evidence/demo.json',JSON.stringify(output,null,2));console.log(JSON.stringify(output.map(x=>({confirmationMode:x.confirmationMode,outcome:x.outcome,counts:x.counts,distinctAdapterPids:new Set(x.adapterProcesses.map(r=>r.pid)).size,stopConfirmed:x.stop.confirmed,realModelCalls:0,platformMessages:0})),null,2));
