from pathlib import Path
import json
TASK=Path(__file__).resolve().parents[1];E=TASK/'evidence';SHA='60f60f564080b75206cd80b35597c1d086925354'
model=json.loads((E/'model-summary.json').read_text());metrics=json.loads((E/'task-family-metrics.json').read_text());runtime=json.loads((E/'runtime-final.json').read_text())
remaining=[
 {'id':'R2-U01','priority':'P0','item':'自由表达缺少已验证的生产语义检查配置；目前不采用自由改述','evidence':'12 族候选均未采用；合法引用不能证明语义保真','status':'未完成，不启用 enforce'},
 {'id':'R2-U02','priority':'P0','item':'通用复杂目标分解与跨回合 GoalProgress 续接','evidence':'已实现明确项目的跟进/笔记建立目标与精确批准控制；其他目标集合仍保守标为未完整核实','status':'未完成；已有提交依靠原回执与历史保留，不自动重放'},
 {'id':'R2-U03','priority':'P1','item':'查询和文档共用同版 EvidenceBundle','evidence':'查询字段与信息事实已并存于 Outcome；文档事实读取仍走原独立路径','status':'未完成'},
 {'id':'R2-U04','priority':'P1','item':'精确来源依赖的影子判定及局部启用','evidence':'保留 FIX2 动态、目录、历史依赖与原全局来源权限版本拒绝；新对象/集合判定器尚未实现','status':'未完成'},
 {'id':'R2-U05','priority':'P0','item':'最终新模式的真实业务、本人/独立人员、自然度和手机验收','evidence':'本任务未开启新模式，L2 仅合成表达对照；未发起真实业务写入或外发','status':'未执行'},
 {'id':'R2-U06','priority':'P1','item':'主循环完整任务集的配对延迟与工具选择评估','evidence':'当前 L2 是固定结果后的表达阶段，短回执在正常路径保持零额外调用；不能外推全链路','status':'未完成；协议输出 token 开销明显'},
 {'id':'R2-U07','priority':'P1','item':'遗留卡片、普通私聊及旧群问答的进一步结构化','evidence':'均接保护性 Outcome 与真实原事件；不据原文反推业务成功，HTTP accepted 不记 verified','status':'兼容接线已完成；自然表达与完整业务目标未验收'},
]
(E/'uncompleted.json').write_text(json.dumps(remaining,ensure_ascii=False,indent=2)+'\n')
(TASK/'00_当前交接.md').write_text(f'''# AM-HARNESS-20261031-01 / R2 当前交接

要求版本：v2.0-design.1。日期：2026.10.31（Asia/Shanghai）。状态：**已实施待审计；整体验收未通过，要求尚未全部完成。**

本轮沿现有宿主增量实现 Outcome、主模型末次 ResponsePlan、投递前冻结、保护块、有限目标检查与中断分类，并补齐普通私聊及旧群问答的保护性记录。新自由表达没有获得采用资格，保持关闭；不能把框架接线、模板或回退算作拟人化通过。

## 固定依据与当前版本

| 项目 | 值 |
|---|---|
| 指定 FIX1 源码 | d3e40b0d27517d75e850613c4eaecec107efa0ea |
| 实际采用的后续 FIX2 | 714b1af93a2cb4090f3c8166296455c0035d5730 |
| **最终源码 SHA** | **{SHA}** |
| **审核 SHA** | **本文件所在远端固定提交；由最终回传链接与外部独立读回记录标识，不能使用源码 SHA 代替** |
| 原始 ZIP SHA256 | c206fc20fd078478df0a589a49d871f2f659f4a1f9c9713139563e52bce1ada3 |
| 引用聊天 | 6ae57e9e-d5ac-8332-a183-c51c5780c11c，展示机器人流程图 |

五份指定文档已完整读取，原包 29 项清单校验一致。参考代码没有复制成生产实现，26 项参考合同检查单独列为 L0。当前实现继承 FIX1 和真实工作树中的 FIX2；完整差异分别见 [FINAL.diff](FINAL.diff) 与 [FIX1_TO_CURRENT.diff](FIX1_TO_CURRENT.diff)。

## 运行状态

原 Qwen `{runtime['model']}`、原协调器、唯一消费者、600 秒身份、`ledger_write=false` 保持。原配置字节保持，旧 R2 `off`，新 response `legacy`。{runtime['loaded_files']} 份加载文件与最终源码一致，原连接正常、lane idle、未暂停模型。没有新建消费者或替换模型。

原消费者内完成合成模型验证，业务输入为固定合成资料。本任务未发起真实业务写入、同事/群外发或正式台账修改；运行一致性不替代新模式的真人业务验收。

## 验证结论

- L0：原设计参考 26 通过，仅协议示例。
- L1：实际宿主新增 32 项通过；包含 29 项 Outcome/业务/中断检查和 3 项普通私聊/旧群结果检查。旧通道另 51 项回归通过。
- 原工程三个独立套件：Harness 130 通过；原工程 680 通过、27 个既有失败；会话 193 通过。重复执行的同一 193 项未累计，合计 1003 通过、27 既有失败；没有新增失败。脱敏重建另行记录，不能累加成不同测试。
- L2：最终版本 12 组、24 次原 Qwen 调用；只测固定结果后的表达阶段。新候选实际采用 **0/12**，全部回退；业务完成、真实送达和自然度均未验收。旧回答中位数 {model['legacy']['p50_seconds']:.2f} 秒，新协议中位数 {model['response_plan']['p50_seconds']:.2f} 秒。
- L3/L4：新模式真实业务、人工盲评、独立人员和手机均未执行。

**当前不能宣称“所有任务已经拟人化完成”。** 优先缺口是生产语义检查、通用目标分解/续接、共享文档事实、精确依赖验证，以及业务与自然度验收。逐项见 [03_未完成项.md](03_未完成项.md)。

## 复审入口

1. [01_接线与保护边界.md](01_接线与保护边界.md)：接线、事务、状态、覆盖和保留项。
2. [02_验证与逐任务族指标.md](02_验证与逐任务族指标.md)：分层结果、每族资格/采用/回退/完成/送达/自然度/时延。
3. [03_未完成项.md](03_未完成项.md)：明确未完成与建议下一步。
4. [04_复现与回滚.md](04_复现与回滚.md)：原环境、脱敏重建、原模式恢复和权限边界。
5. [SOURCE_SHA256.json](SOURCE_SHA256.json)、[MANIFEST.json](MANIFEST.json)：源码原始/脱敏指纹、审核文件清单。

先独立复审实际接线与证据，不把 48 个设计种子或 26 个参考测试当作生产验收，不自动另起下一轮。
''')
(TASK/'01_接线与保护边界.md').write_text('''# 接线与保护边界

## 结果与表达

`am_outcome` 以完整规范 JSON 字符串冻结嵌套数据，包含真实 Event/Run 绑定、用户目标、工作单元、结构化结果、原文、覆盖、来源依赖、必要块和到期时间。模型不能更改权威状态。35 个已登记业务工具有明确任务族映射；实际源码行与出口见 evidence/wiring-matrix.json。

`CoordinatorModel` 保留原工具分支与旧 answer 解码，新增版本化 response_plan。原模型末次回答直接携带提案，不追加末端重写调用。同次任务绕过旧 finalizer；模型协议按请求隔离，新增表达仅面向管理人私聊，其他身份保留原模式。shadow 使用旧模型 answer、只记录新结果，不为候选额外调用模型。

快查询、控制、短回执仍按原路线执行。新自由文本必须通过严格结构、事实引用、保护块、指纹、长度、授权/来源和语义配置检查。当前没有可用生产语义配置，因此自由改述拒绝并回退；没有使用参考包的 allow-all Assessor。原文投影、锁定块和 canonical 均不计为生成采用。

## 正确目标与业务状态

明确项目别名的“建立跟进/保存笔记”形成逐目标集合，不再按正则估计应该创建几条。明确跟进请求在工具执行前拒绝 worknote。原精确版本确认/批准以原对象与回执核对完成；多目标失败不会被成功项覆盖。缺少可信目标集合时保守报告 partial/blocked，不能据模型“办好了”标为 fulfilled。通用意图分解和跨回合目标状态仍未完成。

跟进、笔记、知识、文档、发送、提醒、反馈等从实际结果字段适配。原 message 仅作可信兼容呈现，不能设置成功状态。文档 queued 不等于生成、adopted 不等于发布；提醒 active 不等于 occurrence 已发；未知执行保留原 action/reservation，不重放。

## 历史与投递

`_finish` 在保存助手历史前准备最终正文。最终呈现和会话回复在原会话事务中关联；网络/模型调用不进入数据库事务。原 outbox 同事务登记 semantic/rendered hash 与 presentation ID。跨库不宣称原子性，仍由 FIX1/FIX2 的已送达历史过滤、任务 fence、来源依赖和原回读保证。

正文 hash 不代替事件身份。同文不同事件有不同呈现；重复事件读取已保存结果，不受新提示词影响。预览展示仍保持实际 action/version/payload，必要状态块不会因纯展示转换而消失。过期投递与新增记录随原期限清理。

所有已发现发送出口均有登记：AM outbox 的菜单、卡片、文档、计划/提醒、维护终态为保护性 Outcome；普通私聊与旧群问答在各自原 SQLite 中登记同一正文与原事件，继续原 sender。后两者的 HTTP 接收只记 accepted，未独立回读不得记 verified；不得冒充主模型自由表达。

## 预算、中断与保持项

任务模型、一次任务纠正、额外表达及总调用分别记录。当前独立表达路线未启用，presentation_calls=0。格式错误可回到当前有效结果；SOURCE_ACCESS_CHANGED、取消、过期、STOP_UNKNOWN 与提交未知继续原处理。新中断表记录 not_dispatched / provider_stop_unknown / effect_unknown / source_invalid 等分类，不释放 lane、不重试工具。

原 5 秒只读入口、600 秒身份、唯一模型协调器和消费者保持。FIX2 全局权限版本、动态项目/目录/历史依赖继续有效。新精确依赖校验器和文档共用事实快照没有实现，不能把现有依赖透传算作这些能力完成。

节点目录为实际职责注册（13 个节点、18 条登记边），不是新的图执行器，也不是全部路径已运行覆盖率。原回执、批准、采用、业务事务和 outbox 仍是权威。
''')
lines=['# 验证与逐任务族指标','','## L1：实际宿主，合成模型/平台输入输出','','计数来自真实存储与原 outbox；均为合成环境。多任务族呈现按每个适用族列入，不能把各行相加成独立请求。生成资格、模型采用均为 0；自然度全部未评。sent 为原发送完成投影，verified 为相应原链路独立核验，两列不互相替代。','','|任务族|呈现数|生成资格|尝试|采用|回退|业务 fulfilled|partial|sent|verified|准备 p95(ms)|自然度|','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
for family,m in sorted(metrics['families'].items()):lines.append(f"|{family}|{m['presentations']}|{m['eligible']}|{m['attempted']}|{m['adopted']}|{m['fallback']}|{m['fulfilled']}|{m['partial']}|{m['sent']}|{m['verified']}|{m['prepare_ms_p95']:.3f}|未评|")
lines += ['','## L2：原 Qwen，固定合成结果的表达对照','','每族一对；是强制构造的研究样本，不能把短回执的这次强制模型调用当成生产路线。生产快查/控制/短回执保持零额外表达调用。资格按部署门槛冻结为 0；实验生成不计为有资格的生产采用。','','|任务族|实验生成|生产资格|实际采用|回退原因|旧版(s)|新协议(s)|业务完成/送达/自然度|','|---|---:|---:|---:|---|---:|---:|---|']
for v in model['families']:lines.append(f"|{v['family']}|1|0|{int(v['adopted'])}|{v['reason']}|{v['legacy_seconds']:.2f}|{v['response_seconds']:.2f}|未测/未测/未评|")
lines += ['',f"最终样本 12 对、24 次调用。旧版 p50/p95：{model['legacy']['p50_seconds']:.2f}/{model['legacy']['p95_seconds']:.2f} 秒；新协议：{model['response_plan']['p50_seconds']:.2f}/{model['response_plan']['p95_seconds']:.2f} 秒。新协议元数据增加输出 token，当前无自然度收益证据，不能据零额外调用宣称时延改善。",'', '原始输出、每次 token/排队/模型耗时见 evidence/model-pairs/；较早一批如保留，必须单独标识源码，不合并分母。候选 hash、required blocks 与实际选用来源在同一记录中。','','## 回归与复建','','完整退出码、JUnit、27 个原失败的名称/状态/错误逐项对比见 evidence/regression-comparison.json、final-source-02/ 与 final-reconstructed/。重复的会话 verify 与 pytest 193 项仅算一次；L0、L1、L2、L3、L4 不混算。48 条验收种子未全部逐条执行，已执行风险集以实际测试名称为准。']
(TASK/'02_验证与逐任务族指标.md').write_text('\n'.join(lines)+'\n')
(TASK/'03_未完成项.md').write_text('# 未完成项\n\n当前要求尚未全部满足，不标为全任务业务通过。\n\n'+'\n\n'.join(f"## {r['id']} / {r['priority']}\n\n{r['item']}。\n\n证据边界：{r['evidence']}。\n\n状态：{r['status']}。" for r in remaining)+'\n\n后续应先解决语义配置与通用目标完成口径，再做同任务集的端到端对照；通过后再准备一次本人可评的盲评材料。权限/来源前提未通过时，不反复要求手机重试。\n')
(TASK/'04_复现与回滚.md').write_text('''# 复现与回滚

## 代码与输入

source/ 是最终脱敏源码；INPUT_SHA256.json 区分原始输入与脱敏副本；SOURCE_SHA256.json 区分原始运行源码与审核源码。FINAL.diff 基于真实采用的 FIX2，FIX1_TO_CURRENT.diff 同时保留 FIX1 以来变化。不要将审核副本覆盖真实私有配置、数据库或业务正文。

## 离线复现

使用原工程已安装依赖的 Python，运行：

```sh
python scripts/run_checks.py --source source --output /tmp/am-harness-r2-review
```

脚本先核对 SOURCE_SHA256，然后在临时副本执行实际宿主、会话和旧工程检查。已有 27 个失败使完整脚本退出 1；这不是全部通过，必须比对名称与错误，不能隐藏退出码。桥接旧通道另以原工程 src、会话 src、feishu-bridge 加入 PYTHONPATH，执行 test_bridge.py、test_group_ledger.py、test_group_ai.py。模型 probe 只能在原服务/协调器已验证且空闲时运行，不创建新 provider/消费者。

## 模式与回滚

当前私有配置没有新增 response 开关，默认 legacy；原 output_rewrite 保持 off。代码支持 `am_conversation.response.mode` 为 legacy/canonical/shadow/enforce，不能直接全量启用。canonical/enforce 只为管理人私聊选择新主模型协议；enforce 仍要求真实可用、经过验证的语义配置。当前未提供该配置，因此不得把开关开启当验收。

需要停用新表达时保留 legacy，停止新 probe 入队，待原执行与 outbox 完成后使用原单消费者服务维护流程。不得回滚数据库、删除回执或恢复旧动作再执行。新增表为附加记录并按原期限清理，旧批准/采用/原回执继续保留。更换代码也不能释放未知模型 lane。

本轮安装复用原受控脚本：持有原模型租约、检查任务/投递空闲、备份原库、只停启原桥接、保留配置字节，再回读加载文件和原模型摘要。没有重启或替换 Qwen/Ollama。
''')
print('handoff documents written')
