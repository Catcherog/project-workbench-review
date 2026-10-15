import fs from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {runCodex} from './codex.mjs';
import './import-budget.mjs';
const jobDir=resolve('runtime/local-'+randomUUID()),marker=randomUUID();await fs.mkdir(jobDir,{recursive:true});
await fs.writeFile(join(jobDir,'synthetic.json'),JSON.stringify({marker,label:'合成测试',samples:[{name:'A',planned:8,done:5},{name:'B',planned:6,done:2}],note:'尚未交付审核'}));
const prompt='这是执行者构造的合成验证。请用本地命令读取 synthetic.json，计算已完成样本/计划样本总数，用中文写一句带合成测试字样的摘要。不要读取其他文件。marker原样返回，missing返回空数组，question返回空字符串。';
try{const r=await runCodex({binary:process.env.PROBE_CODEX_BIN||'codex',jobDir,prompt,marker,model:'gpt-6-astra',effort:'max'});await fs.writeFile('evidence/local-model.json',JSON.stringify(r,null,2));console.log(JSON.stringify({jobDir,result:r.result,usage:r.evidence.events.filter(x=>x.type==='turn.completed')}));}catch(e){console.log(JSON.stringify({jobDir,error:e.message,evidence:e.evidence}));process.exitCode=1;}
