from pathlib import Path
import json,statistics,hashlib,sys
T=Path(__file__).resolve().parents[1];OLD=T.parent/'R10'
sys.path.insert(0,str(OLD/'private/python-deps'))
import jsonschema
read=lambda p:json.loads(p.read_text())
lines=lambda p:[json.loads(x) for x in p.read_text().splitlines()]
manifest=read(OLD/'private/model-comparison.manifest.json');cases={c['case_id']:c for c in manifest['cases']}
new=[]
for p in sorted((T/'private/codex').glob('*/results.jsonl')):
 for r in lines(p):r['run']=p.parent.name;new.append(r)
assert len(new)==24 and all(r['status']=='completed' for r in new)
for r in new:
 jsonschema.validate(json.loads(r['output']),cases[r['case_id']]['response_schema'])
 r['schema_validation']='pass'
 r['assistant_review_notes']=(['状态限定弱化：输入是“已标记完成”，输出写为“已完成”；需复核这种省略是否可接受。'] if r['case_id']=='R7-H03' and r['run'] in ('terra-high-02','terra-high-03') else [])
 r['review_origin']='executing_assistant_posthoc';r['human_authored']=False
summary={}
for model in ('gpt-6.1-sol','gpt-6.1-terra'):
 rows=[r for r in new if r['model']==model];times=[r['total_cli_ms']/1000 for r in rows]
 summary[model]={'reasoning_effort':'high','planned':12,'completed':len(rows),'schema_pass':len(rows),'observed_tool_calls':sum(r['observed_tool_calls'] for r in rows),
  'seconds':{'median':statistics.median(times),'min':min(times),'max':max(times),'mean':statistics.mean(times)},
  'per_case_median_seconds':{c:statistics.median(r['total_cli_ms']/1000 for r in rows if r['case_id']==c) for c in cases},
  'median_output_chars':statistics.median(len(json.loads(r['output'])['text']) for r in rows),'assistant_flagged_state_qualification':sum(bool(r['assistant_review_notes']) for r in rows)}
for case in cases:
 assert len({r['actual_prompt_sha256'] for r in new if r['case_id']==case})==1
relative=1-summary['gpt-6.1-terra']['seconds']['median']/summary['gpt-6.1-sol']['seconds']['median']
report={'schema':'am-r10-fix1-speed-comparison/1','cases':4,'repeats_per_model':3,'planned':24,'completed':24,'models':summary,
 'terra_vs_sol_median_reduction_percent':relative*100,'latency_boundary':'CLI process launch to complete output; excludes Feishu ingress/egress and phone rendering',
 'same_case_prompts_identical_across_models':True,'tool_surface':'not proven empty; zero observed calls',
 'independent_human_ratings':0,'full_agent_task_completion':None,'phone_total_latency':None,'production_choice':None,
 'limitations':['Four reused historical expression tasks, not new holdout','Same CLI 0.163.0 but model-specific host instructions can differ',
 'Three repeats are exploratory; server load/cache/revision and billed cost are uncontrolled or unavailable',
 'Assistant semantic notes are not independent human acceptance','Historical Q8/MLX/Astra measurements have different boundaries or run times']}
(T/'evidence/speed-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
# Business identity and year transformation is explicit; original outputs remain private.
replacements={'Digital Twin':'项目乙','VTS':'项目丙','德昌电机':'项目丁','工具包':'项目甲','2026':'2096','2027':'2097'}
def redact(s):
 for a,b in replacements.items():s=s.replace(a,b)
 return s
(T/'private/redaction-map.json').write_text(json.dumps(replacements,ensure_ascii=False,indent=2))
oldrows=[]
for r in lines(OLD/'private/model-comparison-run-001/results.jsonl'):
 if r['arm'] in ('q8','mlx_base','mlx_r8_adapter'):
  r['run']='R10-'+r['arm'];oldrows.append(r)
for folder in ('task-stack-001','task-stack-low-001','task-stack-review-low-001'):
 for r in lines(OLD/'private/codex'/folder/'results.jsonl'):r['run']='R10-'+folder;oldrows.append(r)
public=[]
for r in oldrows+new:
 c=cases[r['case_id']];out=json.loads(r['output']);jsonschema.validate(out,c['response_schema'])
 public.append({'case_id':r['case_id'],'run':r['run'],'model':r.get('model',r.get('arm')),'effort':r.get('effort'),
  'question_redacted':redact(c['facts']['frame']['question']),
  'expected_fact_units_redacted':[redact(x) for x in c['facts']['review_context']['fixed_facts']],
  'full_output_redacted':redact(out['text']),'original_output_sha256':hashlib.sha256(r['output'].encode()).hexdigest(),
  'prompt_sha256':r.get('actual_prompt_sha256',c['messages_sha256']),
  'total_cli_ms':r.get('total_cli_ms'),'native_timings_ms':r.get('timings_ms'),
  'summed_time_estimate_ms':r.get('summed_time_estimate_ms'),'status':r['status'],
  'assistant_review_notes':r.get('assistant_review_notes',[]),'human_authored':False,'schema_validation':'pass'})
assert len(public)==48
(T/'evidence/redacted-comparison.json').write_text(json.dumps({'redaction':'Project names replaced consistently; years shifted +70; amounts and intra-year intervals retained for semantic audit. This is a derived audit copy, not the exact inference input.',
 'cases':4,'outputs':48,'original_raw_snapshots_exported':False,'rows':public},ensure_ascii=False,indent=2))
parts=['# Sol / Terra high 速度与逐题对照','2026.11.5，Asia/Shanghai。','同一4道历史表达题，每模型3轮；交替运行顺序为 Sol、Terra、Terra、Sol、Sol、Terra。24次全部返回，JSON结构检查通过，未观察到工具调用。',
 '| 模型 | 完成 | 中位耗时 | 最短—最长 |','|---|---:|---:|---:|']
for model,s in summary.items():
 v=s['seconds'];parts.append(f"| {model} / high | 12/12 | {v['median']:.2f}秒 | {v['min']:.2f}—{v['max']:.2f}秒 |")
parts += [f"这批题中 Terra 的中位耗时比 Sol 低约{relative*100:.1f}%。样本仅4题，不能推断所有任务、复杂文稿或手机总体验也有同等提升。",
 '计时从 CLI 启动到完整结果，不含飞书入站、出站和手机展示。两模型使用同一用户题目，均设 high；标准CLI自带宿主指令，未证明工具表为空。服务端版本、缓存和实际费用未知。',
 '执行助手语义复核发现：Terra在节点状态题的第1、2轮将“已标记完成”简写成“已完成”，状态限定有所弱化，保留为待复核项。其余输出在本次阅读中保留主要事实，不能据此记作独立业务验收通过。',
 '历史Astra low中位13.10秒、max29.58秒可供参考，但运行批次不同。历史Q8 9.84秒是请求到候选返回，MLX/R8约7.5秒仅计推理，均不能直接作为本轮完整CLI耗时的等价基线。',
 '官方模型及CLI参数依据：[OpenAI Docs](https://learn.chatgpt.com/docs/models?surface=cli)。本机实际命令和事件留在私有目录；本报告数字来自实际运行。',
 '以下包括上轮24份和本轮24份完整输出。项目名已统一替换，年份平移70年；数值及年内日期关系保留。此为脱敏派生副本，原始输入、输出和哈希仍留本机。']
for case in cases:
 records=[r for r in public if r['case_id']==case]
 parts += [f'## {case}',records[0]['question_redacted'],'\n'.join('- '+x for x in records[0]['expected_fact_units_redacted'])]
 for r in records:
  timing=(f"CLI {r['total_cli_ms']/1000:.2f}秒" if r['total_cli_ms'] else '原生分段计时见JSON原记录')
  parts += [f"### {r['run']} · {timing}",r['full_output_redacted']]
  if r['assistant_review_notes']:parts += ['复核备注：'+'；'.join(r['assistant_review_notes'])]
(T/'02_模型速度与完整脱敏对照.md').write_text('\n\n'.join(parts)+'\n')
print(json.dumps({'models':summary,'outputs':len(public)},ensure_ascii=False))
