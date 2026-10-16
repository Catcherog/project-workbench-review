// Offline fixture only. These emitted events are simulated, never real model evidence.
import fs from 'node:fs/promises';
const args=process.argv.slice(2),arg=k=>args[args.indexOf(k)+1];let prompt='';for await(const chunk of process.stdin)prompt+=chunk;
const source=JSON.parse(await fs.readFile(arg('-C')+'/synthetic.json','utf8'));
const marker=prompt.split('控制器会话 marker：').at(-1).trim();
const value=source.tests?{source_marker:source.source_marker,source:'synthetic.json:tests',total:source.tests.length,passed:source.tests.filter(x=>x.status==='passed').length,failed:source.tests.filter(x=>x.status==='failed').length,blocked:source.tests.filter(x=>x.status==='blocked').length,pass_rate_percent:70}:{source_marker:source.source_marker,source:'synthetic.json:minutes',tasks:[{task:'补充接口说明',owner:'合成成员甲',deadline:null},{task:'复核测试结果',owner:'合成成员乙',deadline:'2026-10-19'}]};
const result={marker,summary:JSON.stringify(value),missing:[],question:''};await fs.writeFile(arg('--output-last-message'),JSON.stringify(result));
for(const e of [{type:'thread.started',thread_id:'offline-'+source.source_marker},{type:'turn.started'},{type:'item.completed',item:{id:'read',type:'command_execution',command:'cat synthetic.json',status:'completed',exit_code:0,aggregated_output:JSON.stringify(source)}},{type:'item.completed',item:{id:'final',type:'agent_message',text:JSON.stringify(result)}},{type:'turn.completed',usage:{input_tokens:0,output_tokens:0}}])console.log(JSON.stringify(e));
