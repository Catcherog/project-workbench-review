// Deterministic local executable. No API/model/network access.
import fs from 'node:fs/promises';
import {spawn} from 'node:child_process';
const args=process.argv.slice(2),mode=args.find(x=>x.startsWith('--fixture='))?.split('=')[1]||'ok';
const value=flag=>args[args.indexOf(flag)+1];
if(mode==='stubborn'){
 process.on('SIGTERM',()=>{});
 if(args.includes('--descendant'))spawn(process.execPath,[new URL(import.meta.url).pathname,'--fixture=stubborn'],{stdio:'ignore'});
 console.log(JSON.stringify({ready:true,pid:process.pid}));setInterval(()=>{},1000);
}else{
 const source=JSON.parse(await fs.readFile(value('-C')+'/synthetic.json','utf8'));
 const emit=x=>console.log(JSON.stringify(x));emit({type:'thread.started',thread_id:'offline-thread'});emit({type:'turn.started'});
 if(mode==='failed'){emit({type:'turn.failed',error:{message:'synthetic_failure'}});process.exit(1);}
 if(mode==='late')await new Promise(r=>setTimeout(r,250));
 const result={marker:source.marker,summary:'合成测试 7/14，50%。',missing:[],question:''};
 if(mode==='extra')result.chatId='forged-target';if(mode==='clarify')result.question='未授权的额外问题';if(mode==='wrong-marker')result.marker='other-session';
 await fs.writeFile(value('--output-last-message'),JSON.stringify(result));
 emit({type:'item.completed',item:{id:'final',type:'agent_message',text:JSON.stringify(result)}});
 if(mode!=='no-complete')emit({type:'turn.completed',usage:{input_tokens:0,output_tokens:0}});
}
