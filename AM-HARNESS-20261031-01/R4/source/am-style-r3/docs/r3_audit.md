# R3 定向审计与 R4 决策

## 审计范围

固定输入为 R3 审核 SHA `7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757` 与最终源码 `0ce6dcde237b669efbc263623fe4c95f068bd201`。读取了交接、比较、训练、运行状态、原机集成相关源码；复现需要的依赖来自固定 R2-FIX2。所有运行仅在临时审计工程或本包离线环境，未连接真实业务平台。

[R3 交接](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/00_当前交接.md)记载的 179 份远端一致、原工程 798 通过/27 既有失败和原服务 187 个加载文件一致，仍是已有回传事实。本轮没有据此声称重新完成了相同范围的审计。

## 一、已复现的三个接缝问题

| 问题 | 固定 R3 行为 | R4 补修 |
| --- | --- | --- |
| 引文限定与 typed value 不一致 | claim value 为“完成”、source.quote 为“未完成”，仍形成“完成”的可采用末端答复；预计/阶段范围/负责人冲突也可复现 | 有非空 quote 时先要求文本型且与 value 完整一致；复杂不等价情况拒绝投影、保留原答复，不先删否定或范围词 |
| 问题目标与字段覆盖脱节 | 问“谁负责”，工具只返回 progress，仍依据“闭合问题 + 有 claim + 完整 read”标 fulfilled | 闭合语法确定字段、唯一项目身份、required claim 和同一完整 read 的证据绑定；缺字段、跨项目、同名歧义不完成 |
| 验证后正文被 UI 改写 | query+needs_confirmation 的准备答复包含事实，text UI 只保留确认块，旧 semantic hash 仍用于入队 | 两类未支持确认 UI 先保留原路径；对实际采用的 candidate/canonical，在原 outbox 事务中比对最终 kind/body/artifact 和文本 hash，丢事实即回滚 |

这些是实际复现的代码缺陷，不是根据 16 条 indeterminate 推断出来的模型缺陷。新 quote 规则刻意保守：它可能减少表达层覆盖，不能被描述成通用引文理解器。原答复保留也不意味着原答复因此获新语义认证。

详见 `docs/integration_audit.md`、`evidence/integration-audit/` 与两个 overlay。实际业务写入/平台投递均为 0。

## 二、26 条 Qwen 的解释

[原比较证据](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/evidence/comparison.json)包含 13 个原型各两个实体变体。26 次均返回 JSON，原自动语义结果 10 pass、16 indeterminate。逐条读文本，没有依据将 16 个 unknown 整体标为事实错误；多数差异是同义词、合句、连接词、主语或指代。此处助手审计不能替代新增人工标签。

可选 natural profile 对相同旧候选回放后为 14/12，新增认可的 4 个表述只涉及已验证发送回执与取消后续处理。它没有改变原记录、没有新增模型生成、没有重新评分自然度，更不是新盲测。原 owner gold 中“现在”等说法仍未被通用化接受；具体人审只作用于那一条原情境。

“测试的开始时间和预计时长具体需要包含哪些内容？”来自宿主 content gap 模板。R4 增加 start_time/duration/start_and_duration 等 typed slots；原错误 frame 不自动变成修好后的 frame。修复后必须新建 prompt、新生成，不能把前后不同 prompt 的答案配成 DPO。

Qwen 原队列端到端耗时重新计算：p50 4.073s、p95 5.258s、最大 15.673s，保留最长项。26 条都缺少加载/排队/纯推理拆分与可靠 cold/warm 标记。原 legacy 26 条缺失、Codex 26 条阻塞，不纳入模型胜负。

## 三、训练输入与训练结论

实际 gold 输入是单条 user 的 native envelope；内部包含逻辑 system/user 和 tools=[]。旧 silver 却比较裸 logical prompt 与裸 host version，会拒绝正确 wire，或诱导用错误角色训练。R4 新 transport 绑定 logical、producer、judge、student 的不同输入；以 student wire 导出训练集。

[R3 SFT 实录](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/evidence/sft-attempt.json)中的单步事实与 gold 哈希成立；train1/dev1 没有泄漏互换。dev loss 从 0.126229926943779 到 0.12616302073001862，绝对变化约 -0.0000669062，只有一个验证样本，不能推出自然度提升。三个已暴露诊断场景训练前后文本相同，也不能推出 adapter 未更新。

公开证据仍欠缺：初始/更新后参数差异、实际非零有限梯度、绑定安装源码的自定义 kernel 数值结果，以及完整 adapter keyset/重载诊断绑定。辅助 `sft-source-sha256.json` 的一个 smoke 脚本 hash 过期，主运行记录的脚本 hash 正确。R4 以真实参数和重载证据补齐 mechanics，不用重复跑相同文字来代替。

## 四、Codex 与证据真实性

R3 本机 CLI 0.163.0 的禁用覆盖未消除 functions/collaboration。mock provider 的一次本地 HTTP 捕获不能证明同一真实远端模型工具面。R4 仍保持 blocked；新配置候选不是已经解决。

本包自审还发现：仅比较声明的 request/catalog SHA，临时 fixture 可填写相同字符串而无真实工件。R4 升级为 capabilities/2，读回原始文件、检查 hash、model、明确空 tools、未检查 harness，并保持 fixture=true 必拒绝。测试进程/argv 使用显式 mock gate，不把测试材料标为真实。

这些检查证明内容一致性；真实性仍依赖可信原机执行器和实际捕获。任何可手写 JSON 的检查都不能自证来源。本轮没有生成有效 Codex capability proof。

## 五、继续保留的边界

- 确认卡片/交互式 artifact 与自由末端表达尚未通用组合。
- projector 尚未完整串联 sources_requested/source_links；内部 provenance 不等于对用户给出了来源。
- terminal_json 保存原 outcome/frame，重放可读；普通 conversation_messages/host_context 仍主要使用最终文本，不能声称原始事实自动完整恢复到下一轮。
- 原始 Q8 与独立官方 HF 快照同源关系未证明；MLX 权重不能直接冒充生产模型版本。
- 没有新的独立业务验收或启用结论。
