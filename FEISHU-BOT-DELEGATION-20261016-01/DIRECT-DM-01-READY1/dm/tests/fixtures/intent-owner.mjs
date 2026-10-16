import {DirectDmIsolation} from '../../candidate/scripts/direct-dm-isolation.mjs';
let text='';for await(const chunk of process.stdin)text+=chunk;
const {id,policy,now}=JSON.parse(text),gate=new DirectDmIsolation(process.argv[2],{clock:()=>now});
gate.reserveEffect(id,'preview',policy);
console.log(JSON.stringify({ready:true,pid:process.pid,ownerId:gate.ownerId}));
// The parent kills only this owned fixture to exercise genuine orphan recovery.
setInterval(()=>{},1000);
