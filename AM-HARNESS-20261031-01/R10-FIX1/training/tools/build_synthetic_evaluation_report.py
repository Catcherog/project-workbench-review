from pathlib import Path
import json,hashlib,statistics,struct,math
R=Path(__file__).resolve().parents[3];T=Path(__file__).resolve().parents[1];B=R/'AM-HARNESS-20261031-01/R7/private'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
cases=read(T/'private/reserved-evaluation/cases.frozen.json')['cases']
results={arm:read(B/f'r10-synthetic-eval-{arm}-001/evaluation.json') for arm in ('base','sft')}
notes={
 'R10F1-RES-01':['两版都把输入2103.3.18改成2021年3月18日，日期事实错误。'],
 'R10F1-RES-03':['两版均先保留归属待核，未直接归入梧桐；后续建议仍需真实来源核对，文本不代表已执行。'],
 'R10F1-RES-04':['归为项目外事项；两版仍有不必要的补充追问，未作真人风格评分。'],
 'R10F1-RES-05':['两版都在预览中写2010年4月8日，再要求核对原输入2103.4.8；不得先改写给定日期。'],
 'R10F1-RES-06':['“9份图纸，目前尚未批准”可能把预览批准状态归因到图纸本身；输入批准范围也较简略，保留为歧义待核项。'],
 'R10F1-RES-08':['两版都将文档保存超时、无文档ID写成保存失败，并建议直接重试；应保留结果未知并先核对原请求。'],
 'R10F1-RES-11':['新增遗漏：基座保留2103.6.2下一检查点，新SFT输出删除了该检查点。'],
 'R10F1-RES-12':['两版都改坏2103.7.1/2103.7.15日期，并将设备已停机表述为原计划中需停机。'],
 'R10F1-RES-13':['两版都把生成后撤权导致的读取受阻写成文稿生成任务中断，混淆生成与阅读状态。'],
 'R10F1-RES-14':['两版都区分历史阅读与当前依据，但普通依据变化提示及采用前重新校验没有完整说明；需继续核对覆盖性。'],
}
rows=[]
for i,c in enumerate(cases):
 a=results['base']['cases'][i];b=results['sft']['cases'][i]
 assert a['case_id']==b['case_id']==c['case_id'] and a['messages']==b['messages']
 rows.append({'case':c,'base':a,'sft':b,'byte_identical':a['output']==b['output'],'assistant_review_notes':notes.get(c['case_id'],[]),
              'review_origin':'executing_assistant_posthoc','human_authored':False,'business_execution_performed':False})
checks={}
for arm in ('base','sft'):
 run=B/f'r10-synthetic-eval-{arm}-001';plan=read(run.with_name(run.name+'-plan')/'plan.json');req=read(run/'request.json');result=read(run/'result.json')
 assert result['complete'] and result['plan_sha256']==plan['sha256'] and results[arm]['completed']==14
 assert all(sha(run/name)==value for name,value in result['files_sha256'].items())
 sub=read(T/f'private/synthetic-eval-{arm}-submission.json');ident=sub['request']['request_id'];control=T/'private/control-results'/ident
 outcome=read(control/(ident+'.result.json'));exe=read(control/'execution-evidence/execution.json')
 assert outcome['ok'] and outcome['window']['restore_verified'] and exe['independent_worker_groups_gone']
 checks[arm]={'request_id':ident,'completed':14,'adapter_loaded':results[arm]['adapter_loaded'],'request_config_sha256':sha(Path(plan['config']['path'])),
 'result_sha256':sha(run/'result.json'),'workers_stopped':True,'original_q8_restored':True,
 'median_generation_seconds':statistics.median(c['generation_seconds'] for c in results[arm]['cases']),
 'timing_scope':'generation only; model load, queue and Q8 restoration excluded'}
report={'schema':'am-synthetic-sft-comparison/1','case_count':14,'outputs':28,'byte_identical_pairs':sum(x['byte_identical'] for x in rows),
 'changed_pairs':sum(not x['byte_identical'] for x in rows),'new_clear_omission_cases':['R10F1-RES-11'],
 'clear_issues_in_both':['R10F1-RES-01','R10F1-RES-05','R10F1-RES-08','R10F1-RES-12','R10F1-RES-13'],
 'fresh_unseen_before_fit':True,'independent_human_holdout':False,'subsequent_use':'seen_regression_after_this_evaluation',
 'task_execution_scope':'model-only text responses; no real tools or business actions','quality_conclusion':'No reliable business-quality improvement established; factual errors remain and one new checkpoint omission',
 'checks':checks,'rows':rows,'independent_human_ratings':0,'production_model_changed':False}
(T/'evidence/synthetic-evaluation-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
parts=['# 新SFT与同MLX基座：14个合成保留任务','本轮首次在训练前冻结，未加入训练。来源为执行助手编写的合成组合任务，非独立真人业务测试；后续再使用属于已见回归资料。',
 f"两版各返回14项。7对逐字相同，7对改变。基座纯生成中位{checks['base']['median_generation_seconds']:.3f}秒，新SFT {checks['sft']['median_generation_seconds']:.3f}秒；均不含加载、资源窗口或手机展示。",
 '开发集loss小幅下降，但不能据此判定业务质量改善。执行助手事后复核发现日期改写、超时结果误判等问题仍在，且新SFT在周报草稿中新增检查点遗漏。没有真人评分，也没有实际执行发送、保存、采用或挂载动作。',
 '训练使用事实JSON输入，本组采用自然语言组合任务；因此除同运行时、同基座的适配器比较外，还包含输入组织形式的迁移。所有日期、项目、人员称谓均为虚构，仍应按给定事实原样保留，不能擅自换成“更像真实”的日期。']
for r in rows:
 c=r['case'];parts += [f"## {c['case_id']} / {c['group_id']}",c['question'],'预期事实：'+'；'.join(c['expected_facts']),'必要边界：'+'；'.join(c['required_boundaries']),
 f"### 基座 · {r['base']['generation_seconds']:.3f}秒",r['base']['output'],f"### 新SFT · {r['sft']['generation_seconds']:.3f}秒",r['sft']['output'],
 '执行助手复核：'+('；'.join(r['assistant_review_notes']) or '本次未列明确错漏；不等于独立验收通过。')]
(T/'04_新SFT与基座完整对照.md').write_text('\n\n'.join(parts)+'\n')
adapter=B/'r10-synthetic-run-001/adapters.safetensors'
with adapter.open('rb') as f:n=struct.unpack('<Q',f.read(8))[0];header=json.loads(f.read(n))
tensors={k:v for k,v in header.items() if k!='__metadata__'};count=sum(math.prod(v['shape']) for v in tensors.values())
assert count==713472
(T/'evidence/adapter-tensor-inventory.json').write_text(json.dumps({'sha256':sha(adapter),'tensors':tensors,'trainable_parameters':count,'dtypes':sorted({v['dtype'] for v in tensors.values()}),'optimizer_state_saved':False},indent=2))
p=T/'03_SFT训练细节与loss.md';s=p.read_text();s += '\n\n## 保留任务与产物范围\n\n14个同题对照中7对逐字相同、7对改变；新SFT新增1处检查点遗漏，原有日期改写和超时结果误判仍存在。不能把0.65%的dev loss下降当作业务质量提升。完整28份输出见[同基座对照]('+str(T/'04_新SFT与基座完整对照.md')+')。\n\n实际adapter共18个F32张量、713,472个参数。产物是LoRA adapter及配置，没有保存AdamW优化器状态；不构成可逐步精确恢复的完整训练检查点。\n';p.write_text(s)
print(json.dumps({k:v for k,v in report.items() if k not in ('rows','checks')},ensure_ascii=False));print('tensor_dtypes',sorted({v['dtype'] for v in tensors.values()}))
