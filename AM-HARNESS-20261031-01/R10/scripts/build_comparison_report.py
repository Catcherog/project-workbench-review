from pathlib import Path
import json,statistics,hashlib,sys
ROOT=Path(__file__).resolve().parents[3];TASK=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(TASK/'private/python-deps')]
import jsonschema
read=lambda p:json.loads(Path(p).read_text())
lines=lambda p:[json.loads(x) for x in Path(p).read_text().splitlines()]
raw=TASK/'private';manifest=read(raw/'model-comparison.manifest.json');native=lines(raw/'model-comparison-run-001/results.jsonl')
case_by_id={c['case_id']:c for c in manifest['cases']}
sets={name:[r for r in native if r['arm']==name] for name in ('q8','mlx_base','mlx_r8_adapter')}
for name,folder in [('codex_max','task-stack-001'),('codex_low','task-stack-low-001'),('q8_review_replay','task-stack-review-low-001')]:
    sets[name]=lines(raw/'codex'/folder/'results.jsonl')
summaries={};details={}
for name,rows in sets.items():
    timings=[];quality=[];chars=[]
    for row in rows:
        case=case_by_id[row['case_id']];output=json.loads(row['output']);jsonschema.validate(output,case['response_schema'])
        text=output['text'];chars.append(len(text))
        if name in ('q8','mlx_base','mlx_r8_adapter'):
            timing=row['timings_ms']['total_experience'] if name=='q8' else row['timings_ms']['provider']
        else:timing=row['total_cli_ms']
        timings.append(timing/1000)
        # Explicit post-hoc assistant audit, not a blinded human rating or a
        # comprehensive semantic oracle. Original fact_guard is not overwritten.
        notes=[]
        if row['case_id']=='R7-H03' and name=='q8':notes.append('遗漏“节点实际完成时间为空”的显式细节')
        if row['case_id']=='R7-H04' and name in ('mlx_base','mlx_r8_adapter'):notes.append('“引入这组任务后”增加了原事实未要求的先后表达，建议精简')
        quality.append({'case_id':row['case_id'],'schema':'pass','assistant_review_notes':notes,'human_authored':False,
            'original_machine_fact_guard':row.get('quality',{}).get('fact_guard','not_in_original_guard')})
    summaries[name]={'planned':4,'completed':sum(r['status']=='completed' for r in rows),'schema_pass':len(quality),
        'time_seconds':{'median':statistics.median(timings),'min':min(timings),'max':max(timings),'mean':statistics.mean(timings)},
        'timing_boundary':'provider_generation_only; model loading and resource window excluded' if name.startswith('mlx') else 'CLI start through final output' if name.startswith('codex') or name=='q8_review_replay' else 'original probe request through returned candidate',
        'median_output_chars':statistics.median(chars),'assistant_review':quality,'independent_human_ratings':0,
        'full_agent_task_completion_rate':None,'phone_end_to_end_seconds':None}
    if name=='q8_review_replay':
        estimates=[r['summed_time_estimate_ms']/1000 for r in rows]
        summaries[name]['summed_time_estimate_seconds']={'median':statistics.median(estimates),'min':min(estimates),'max':max(estimates)}
        summaries[name]['contiguous_pipeline_measured']=False
    details[name]=rows
report={'schema':'r10-exploratory-comparison/1','data_classification':'authorized_business_derived_historical_regression',
    'cases':4,'comparison_scope':'terminal response tasks with fixed fact units; not complete agent workflows',
    'new_training_executed':False,'selected_adapter':'R8 SFT, sha256 9a8c9e4e25b19ac23f5b40abf3eeb438189d95fdf68d4b05e34872283879767a',
    'arms':summaries,'base_adapter_byte_identical_pairs':sum(a['output']==b['output'] for a,b in zip(sets['mlx_base'],sets['mlx_r8_adapter'])),
    'strict_model_lab_positions':{'planned':24,'completed':12,'blocked':12,'other_statuses':0,'synthetic_classification_invalid':True},
    'standard_cli_positions':{'planned':12,'completed':12,'observed_tool_calls':sum(r['observed_tool_calls'] for k,v in sets.items() if k.startswith('codex') or k=='q8_review_replay' for r in v)},
    'limitations':['4 reused historical tasks, one repetition per configuration; not a new holdout',
        'R10 importer originally misclassified source origin; original records retained and importer now rejects this conversion',
        'Standard CLI retains its harness; zero observed tool calls is not proof of an empty tool surface',
        'CLI low versus max was exploratory; prompt wrapper origin label was corrected between runs',
        'MLX provider time excludes load/unload/recovery; cannot be compared directly to phone or full CLI time',
        'Replay review uses stored Q8 candidate; its summed timing is an estimate, not a contiguous run',
        'Original machine facts remained indeterminate; assistant review is post-hoc and not human acceptance'],
    'production_selection':None,'production_changed':False,'billed_cost':None}
out=TASK/'evidence/model-comparison-summary.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
names={'q8':'当前 Q8','mlx_base':'MLX 基座','mlx_r8_adapter':'MLX + R8 SFT','codex_max':'Codex CLI / gpt-6-astra / max','codex_low':'Codex CLI / gpt-6-astra / low','q8_review_replay':'Q8 候选 → Codex low 复核（回放）'}
parts=['# R10 模型比较：完整原文与计时','2026.11.5，Asia/Shanghai。生产模型与开关未变。',
    '本轮仅比较 4 个既有历史业务派生材料上的末端表达任务。使用的是已经完成的 R8 SFT adapter；本轮新 SFT/DPO 训练为 0。不能将本表称为完整 Agent 任务完成率、独立业务验收或手机总响应时延。',
    '| 方案 | 返回 / 计划 | 中位耗时 | 范围 | 计时边界 |','|---|---:|---:|---:|---|']
for name,item in summaries.items():
    t=item['time_seconds'];boundary='推理阶段，不含加载和恢复' if name.startswith('mlx') else '复核阶段 CLI 全过程' if name=='q8_review_replay' else '请求至候选返回' if name=='q8' else 'CLI 启动至完整结果'
    parts.append(f"| {names[name]} | {item['completed']} / 4 | {t['median']:.2f}s | {t['min']:.2f}–{t['max']:.2f}s | {boundary} |")
estimate=summaries['q8_review_replay']['summed_time_estimate_seconds']
parts += ['',f"回放组合的分段相加估算中位数为 {estimate['median']:.2f}s，范围 {estimate['min']:.2f}–{estimate['max']:.2f}s；不是连续实跑的端到端测量。",'',
    '同一 MLX 运行时下，基座与 R8 SFT 四对输出逐字相同；未观察到后训练文本增益。Codex low 比本机默认 max 更快，但这是少量历史任务的探索结果，不能归因为纯推理强度的普遍因果效果。',
    '执行端逐条复核发现：Q8 在节点状态题遗漏“实际完成时间为空”的显式细节；MLX 在待恢复题多加了不必要的先后措辞。Codex 两个配置及复核候选保留了这些题目的主要事实与状态限制。该判断为 Codex 助手事后审阅，非真人盲评。所有 24 份供本报告展示的输出重新用 jsonschema 4.26.0 检查通过；原运行缺依赖造成的 schema 检查结果保留，未覆盖。',
    '严格无工具比较器中，Codex 与两个组合各 4 个位置仍 blocked。标准 CLI 整体方案另行执行 12 个位置并全部返回，未观察到工具调用；不能把它冒充严格无工具入口通过。CLI 请求模型固定为 gpt-6-astra，版本 0.163.0；实际服务端权重 revision 未暴露。',
    'CLI 的实际输入约 1.22 万 token，包含其自身宿主指令；不是与 Qwen 完全相同的总上下文。比较的是部署方案。费用缺少实际账单，保持未知。',
    '建议下一步按任务类别扩大同场比较：普通进度问答、冲突归属、长文档、跨天跟进及异常恢复分别统计完整完成率与总时延。先验证较快的单模型路径，只有实测证明复核能减少有意义的错误时再采用组合；当前不切换生产路由。']
for case in manifest['cases']:
    parts+=['',f"## {case['case_id']}：{case['facts']['frame']['question']}",'固定事实：']
    parts += ['- '+x for x in case['facts']['review_context']['fixed_facts']]
    for name,rows in details.items():
        row=next(r for r in rows if r['case_id']==case['case_id'])
        parts+=['',f'### {names[name]}',json.loads(row['output'])['text']]
p=TASK/'private/模型对比_完整原文与计时.md';p.write_text('\n\n'.join(parts)+'\n');p.chmod(0o600)
print(json.dumps({name:item['time_seconds'] for name,item in summaries.items()},ensure_ascii=False))
