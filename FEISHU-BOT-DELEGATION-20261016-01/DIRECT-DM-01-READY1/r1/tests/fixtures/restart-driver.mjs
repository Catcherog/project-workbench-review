// A new controller process reopening the same synthetic ledgers. No platform/model calls.
import {DelegationProbe} from '../../src/probe.mjs';
let text='';for await(const chunk of process.stdin)text+=chunk;const f=JSON.parse(text);const p=new DelegationProbe({root:f.root,keys:f.keys,clock:()=>f.now});
try{const result=await p.deliver(f.envelope),counts=p.counts(),adapterStarts=p.runtime.records.length,stop=await p.close();console.log(JSON.stringify({driverPid:process.pid,result,counts,adapterStarts,stop}));}finally{await p.close();}
