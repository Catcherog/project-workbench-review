from pathlib import Path
import json,subprocess,statistics,collections
TASK=Path(__file__).resolve().parents[1];OUT=TASK/'evidence';sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TASK/'worktree',text=True).strip()
suites=json.loads((OUT/'final-source/summary.json').read_text());audit=json.loads((OUT/'six-fixes-tests.json').read_text());comp=json.loads((OUT/'regression-comparison.json').read_text())
models=json.loads((OUT/'model-summary.json').read_text()) if (OUT/'model-summary.json').exists() else {'recorded_observations':0,'families':{},'missing':[None]*288}
pairs=[json.loads(p.read_text()) for p in (OUT/'model-pairs').glob('*.json')];blind=json.loads((TASK/'blind-public/pair-index.json').read_text()) if (TASK/'blind-public/pair-index.json').exists() else None
phase='已实施待审计；整体启用与业务验收尚未通过。' if models['recorded_observations']==288 else '代码已实施；固定模型评估仍在进行，尚未完成回传。'
original=suites['original'];same=comp.get('same_states_types_messages_and_assertion_locations',False)
text=f'''# AM-HARNESS-20261031-01 / R2-FIX1 当前交接

要求：v2.0-design.1，加本次独立复审补充。任务日期：2026.10.31（Asia/Shanghai）。

**{phase}** 新表达保持关闭，不能把保护块、原文投影或回退计为自由表达成功。

## 基线与版本

| 项目 | 值 |
| --- | --- |
| 源码基线 | `60f60f564080b75206cd80b35597c1d086925354` |
| 审核基线 | `ae460a197f3c5b85174c5cd5bb44002a08210328` |
| 本轮最终源码 SHA | `{sha}` |
| 本轮模型测量 SHA | `{models.get('model_measurement_source',sha)}` |
| 本轮审核 SHA | 本文件所在远端固定提交；由最终审核链接与独立读回记录标识，不能用源码 SHA 代替 |

从真实工作树增量实施，保留 R1-FIX2、R2 及原有有效工作。原配置字节保持，未用审核副本覆盖配置、数据库或后续源码。指令与采用范围见 [本轮指令](input/01_本轮指令与采用范围.md)。

## 已实施与当前边界

正式模型测量固定在 e86a4433；测量期间发现批准后续接读取了不含回执的元信息接口，随后在隔离分支补修。最终源码与模型测量 SHA 分列，11 项增量反例和补充主循环测量另列，不改写旧提案或把旧实测标成最终源码运行。

六项发现已有代码补修和对应反例检查：逐事项目标与真实回执匹配、文档采用与只读发送对账契约、身份续验与内容期限分离、shadow 离线观察、关模式后清理、投递终态同步。另接入持久目标、受限语义校验和追问、查询/文档共享 EvidenceBundle、当前依赖影子比较，以及请求冻结快照内的短引用协议。

通用自然语言目标、完整专业异步流程、自由语义覆盖与精确来源完整性仍有边界，见 [未完成项](03_未完成与验收边界.md)。本轮自测不等于独立复审批准。

## 验证结果

- 新增审计反例及边界检查 **{audit['new_audit_cases']} 项**通过，包含在完整工程中。
- 完整原工程 **{original['passed']} 通过、{len(original['failures'])} 项既有失败**，真实退出码 **{suites['returncodes']['original']}**。既有失败名称、状态、错误类型/信息及断言位置逐项一致：**{'是' if same else '需查看差异'}**。
- Harness **{suites['harness']['passed']}**、会话 **{suites['r2']['passed']}** 通过。会话 verify 和 pytest 为同组，脱敏重建为复跑，均不重复累计。
- 修正后的表达预检已记录 **{len(pairs)}/12 对**。主循环按 **48 场景 × 3 次 × 2 模式**固定评估，已记录 **{models['recorded_observations']}/288 条观察**；实际数字、分母和各阶段判定见 [验证与模型评估](02_验证与模型评估.md)。试验观察完成不等于任务办成。
- 正式主循环中新协议候选（schema及原冻结快照绑定）75/123，自由采用0/123；任务p95原版46.63秒、新模式64.97秒，未满足启用门槛。
- 最终源码另有3个场景的双模式补充实测，共6条；限定的项目、事项、次数、回读及持久目标状态核对通过，不加入主分母。
- 盲评材料：{'已准备48项，其中'+str(blind['available_pairs'])+'项有可呈现配对；其余缺失照实保留' if blind else '待固定首轮全部记录完成后生成'}。未进行人工评分、手机、独立人员或正式业务验收。

## 运行与本轮事件

原 Qwen `qwen3.8:27b-bartowski-q8_0`、原协调器、唯一消费者、600 秒身份和 `ledger_write=false` 保持。生产 response 为 `legacy`，旧重写 `off`，目标执行新开关未开启。运行加载指纹与实际源码分列核对。

评估曾触发原模型通道 `stop_unknown`。已保留故障样本，停止继续入队；等待模型自然卸载并核对推理进程结束后，通过原恢复入口恢复通道。原未知输出仍为未知，未重放，未重启或替换 Qwen/Ollama。此后增加下一次模型调用的剩余时间预检，原单轮 120 秒上限保持。详见 [修复与接线](01_修复与接线.md)及 [恢复证据](evidence/model-stop-reconciliation.json)。

最终源码的本人原通道只读查询已独立回读：1条回复、0次持久模型任务，单次服务记录4.8082秒，属于 Codex 代操作的旧模式回归；不计新表达、人评或手机验收。真实正文和消息标识留在私有验证目录，公开材料仅含必要摘要与指纹。

## 审核入口

1. [修复与接线](01_修复与接线.md)、[本轮差异](FINAL.diff)。
2. [验证与模型评估](02_验证与模型评估.md)、[旧失败逐项比较](evidence/regression-comparison.json)。
3. [未完成与验收边界](03_未完成与验收边界.md)、[复现与运行](04_复现与运行.md)。
4. [验收状态](05_验收状态.md)、[运行源码映射](evidence/runtime-loaded-map.json)、[源码指纹](SOURCE_SHA256.json)、[交付清单](MANIFEST.json)。

只发布本轮 R2-FIX1 目录；远端固定提交逐文件读回后再给出最终审核链接。其他轮次保持。
'''
(TASK/'00_当前交接.md').write_text(text)
lines=['# 验证与模型评估','', '原始设计种子、资格规则和执行输入已冻结。保留 48 个场景和三次配对，不靠删除失败或更换首轮答案取得通过。','',
'## 回归与计数','',f"完整原工程 {original['tests']} 项：{original['passed']} 通过、{len(original['failures'])} 既有失败，退出码 1。新增 {audit['new_audit_cases']} 项已包含在该集合。Harness 与会话套件另列；重复运行及脱敏重建不相加。",'',
'## 12 对表达预检','']
for r in sorted(pairs,key=lambda x:x['family']):
 a=r['variants']['legacy'];b=r['variants']['response'];lines.append(f"- {r['family']}：原版 {a.get('seconds',0):.2f}s，新协议 {b.get('seconds',0):.2f}s；{b.get('validation_reason') or b.get('error')}。")
lines += ['', '这组只测已取得生产 adapter 结果后的表达阶段；不代表整任务时延、真实业务完成或自然度。','', '## 主循环逐任务族','',
'下表中的原版是同一补修源码的 legacy 表达路径，二者采用相同的目标跟踪设置。不是把源码基线60f与当前完整系统混作一组前后性能比较。', '',
'| 任务族 / 模式 | 观察 / 计划 | 固定资格分母 | 产生候选请求 | 自由采用 | 原生硬检查通过/失败/未评 | 总耗时 p50 / p95 |','| --- | ---: | ---: | ---: | ---: | --- | --- |']
for k,v in sorted(models['families'].items()):
 l=v.get('task_latency',v['all_observation_latency']);n=v['independent_native_checks'];fmt=lambda x:'—' if x is None else f'{x:.2f}s'
 lines.append(f"| {k} | {v['observed']}/{v['planned_observations']} | {v['frozen_eligible_denominator']} | {v['generated_candidate_requests']} | {v['free_adopted']} | {n.get('pass',0)}/{n.get('fail',0)}/{n.get('not_assessed',0)} | {fmt(l['p50_seconds'])} / {fmt(l['p95_seconds'])} |")
lines += ['', '## 协议、语义与调用分项', '', '| 任务族 / 新模式 | 最终 schema/绑定合格候选率 | schema 判定 | 覆盖判定 | 语义判定 | 实际主/纠正请求 | 预算停止 |', '| --- | ---: | --- | --- | --- | --- | ---: |']
for key,value in sorted(models['families'].items()):
 if not key.endswith(' / enforce'):continue
 rate=value.get('valid_final_candidate_rate');rate='—' if rate is None else f'{rate:.1%}'
 fmt_counts=lambda field:' / '.join(f'{k}:{v}' for k,v in sorted(value.get(field,{}).items())) or '无提案'
 roles=value.get('actual_prompt_call_roles',{})
 lines.append(f"| {key} | {rate} | {fmt_counts('schema_stages')} | {fmt_counts('coverage_stages')} | {fmt_counts('semantic_stages')} | {roles.get('main',0)} / {roles.get('task_correction',0)} | {value.get('budget_exhausted',0)} |")
lines += ['', '表中 schema/覆盖/语义为实际提案阶段计数；无提案仍留在固定资格分母。主/纠正请求根据实际输入中的宿主纠正指令分类，发起前被预算挡住的尝试另列。普通主循环额外表达调用为零，离线 shadow 的额外观察调用单列。候选绑定按其原冻结快照核对；后续结果变化仍由实际选择层拒绝。', '', '## 配对时延', '', '| 任务族 | 已配对数量 | 原版任务 p95 | 新模式任务 p95 | p95 比值 |', '| --- | ---: | ---: | ---: | ---: |']
for family,value in sorted(models.get('paired_latency',{}).items()):
 a=value['legacy']['p95_seconds'];b=value['enforce']['p95_seconds'];ratio=value['p95_ratio']
 lines.append(f"| {family} | {value['paired_observations']} | {a:.2f}s | {b:.2f}s | {ratio:.3f} |")
lines += ['', '任务计时在夹具准备完成后重新起表，total_seconds 已排除 setup；原生阶段计时和最终 prepare_ms 另列。当前机器同时承担原服务和验证，数据是本机观察；不得以短任务、提前停止或未完成业务降低时延来宣布改进。', '', '## 原生工具、投递与语义判定的边界', '', '原生硬检查只核对其明确列出的对象、版本、状态和次数，不代表全部业务语义通过。完整判定及未知项保留在 model-summary.json；前置条件缺口见 fixture-mapping-notes.json。', '',
'## 最终源码补充验证','', '正式测量为e86a4433，最终源码为f767cea9。11项增量反例补齐已批准动作回执恢复；另有3个场景×2模式的6条真实Qwen主循环观察，目标状态、项目事项、次数与回读核对通过。原48场景的分母、首轮盲评和输出不改写。详见evidence/supplementary-summary.json及05_验收状态.md。', '', '## 资格、采用和验收','',
'- schema、冻结绑定、事实覆盖、语义判定、最终选择、投递和自然度分别记录。回溯校验不改变原实际选择；不给旧候选补新 hash。',
'- 原文投影、保护块、canonical、shadow、fallback、权限抑制及无候选均不计自由采用。',
'- 停止/取消/来源失效及预算不足样本保留；业务未完成带来的更短耗时不能视为性能改善。整体、已展示答复与各状态分层并列，保留超时和调用预算。',
'- 模型实测使用原 Qwen、原协调器，业务数据库和平台接口为隔离合成。平台端真实送达另看本人通道证据。',
'- 48 项盲评固定使用第一重复，随机 A/B，保留平局、两者不合格和无候选。未有人评，不给自然度胜率。',
'- 当前不启用新表达；任务族须同时满足事实/动作正确、覆盖采用、性能和相应人工验收条件。', '',
'原生计时与终态：evidence/native-measurements、evidence/native-measurement-index.json；只读提取自本批次已关闭的合成库，未读取生产库。模型实际客户端请求在 evidence/model-request-capsules；保留原指纹，脱敏字节另有清单，不给旧提案绑定新 hash。', '',
'原始文件：evidence/model-pairs、evidence/full-model、evidence/model-input-projections.json、evidence/model-summary.json。早期不同源码/工装批次分别保留，不累计为最终成绩。']
(TASK/'02_验证与模型评估.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'source':sha,'phase':phase,'model_observations':models['recorded_observations']}))
