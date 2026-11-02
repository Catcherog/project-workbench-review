# 本轮执行交接：原机集成、真实验证与回传

任务：`AM-FOLLOWUP-20261102-01 / R1-FIX2`；需求增量 `v1.2-implementation`。

本包由 GPT 完成详细设计和核心代码。Codex 负责核对真实工作树、集成、原服务加载、真实 Qwen/飞书/手机验证和必要的环境接口适配；遇到新的语义或业务反例，保留原始证据回传，不用修改断言或放松门禁取得通过。

## 1. 输入与已有授权

必读本包 00、01、02、本文件、SOURCE_DELTA 和 verification/verification.json。上轮固定审核提交 `68efbab9b11c26ea5bdd64c23be63079160cdc68`，对应源工程 `4009a3ab2dc79b969ce7bf96502866dad8478072`。当前真实源码若有后续有效修改，优先保留并三方合并；不能按本包旧版本回退。

在原任务记录简记本轮用户要求、包文件校验值、实际源 HEAD、未提交/未跟踪状态、采用需求和覆盖关系。本轮补充上一轮的语义、导航及来源页面一致性，不覆盖发送授权、业务核验、训练或其他并行任务。

继承已授权的原环境开发/集成/限定测试，不重复询问普通实现细节。真实外发仍由有效具体预览和本人点击批准；不复活上轮过期卡或用本包代替批准。没有工程师有效私聊会话时，记录当前缺口，其他验证继续。

## 2. 先检查再合并

在隔离 worktree 核对实际源 HEAD 和人工改动。使用现有测试解释器，以下命令中的路径由你填入实际读取到的项目及包目录：

```sh
python /path/to/package/scripts/verify_delta.py --repo /path/to/real/repo --output /path/to/evidence/preflight.json
git -C /path/to/isolated/repo apply --check /path/to/package/changes.patch
git -C /path/to/isolated/repo apply /path/to/package/changes.patch
```

verify_delta 返回 already_applied 时核对最终指纹，不重复应用。conflict_requires_merge 表示已有变更，保留双方有效行为并审查差异；不 reset、不覆盖整文件、不复制运行数据库。精确补丁不含生产配置，也不替换整个项目。

基线未包含新测试时，先使用上轮既有相关集合取得当前 baseline；最终使用本包以下检查：

```sh
python /path/to/package/scripts/run_local_checks.py --repo /path/to/isolated/repo --output /path/to/evidence --suite focused --label final
python /path/to/package/scripts/run_local_checks.py --repo /path/to/isolated/repo --output /path/to/evidence --suite information --label final
python /path/to/package/scripts/run_local_checks.py --repo /path/to/isolated/repo --output /path/to/evidence --suite independent --label final
python /path/to/package/scripts/replay_frozen_outputs.py --repo /path/to/isolated/repo --output /path/to/evidence/frozen-replay.json
```

原工程门禁要求全量时，用原可运行解释器和项目依赖执行，按当前 baseline 逐个测试 ID、断言消息比对。保留实际退出码。原 27 个失败可沿用对应版本证据，但不能预先声明它们永远不变。代码加载指纹与实际受测源码对应，未跟踪的新测试和 fixture 必须纳入。

## 3. 原服务加载

按已有原机维护方式核对唯一消费者、在途任务、协调器、配置和真实 SQLite；必要备份保留。原 Qwen、query 600 秒、ledger_write、response、goal_tracking、terminal_expression 等有效值保持，除非用户已有更新决定。保留 R4 及后续真实有效代码。

本轮没有数据库迁移，不需要替换或重建运行库。若集成后的实际情况需要新增迁移，应先说明具体原因及差异，继续完成不依赖迁移的验证。

## 4. 真实导航与来源页面

| 编号 | 场景 | 通过证据 |
| --- | --- | --- |
| NAV-01 | 本人私聊“我的跟进”及指定标点 | 原 inbox 路由 text；原跟进列表可见；零模型调用、零项目刷新、零跟进 intent；记录分阶段耗时 |
| NAV-02 | 活动采集或准确引用回复中出现同样文字 | 原 collection/followup_reply 语义保留，不被导航吞掉 |
| NAV-03 | 非本人或不同 app/tenant | 不扩大管理员入口、无误展示或发送 |
| NAV-04 | 来源版本变化后的恢复 | 旧结果拒绝；静态恢复页及按钮可使用；旧事实/表单/批准不复制；新页面重新查询 |
| NAV-05 | 待办与进展，某一来源不可读 | 不展示旧派生字段；其他有效事项可读；页面期限不晚于原文 |
| NAV-06 | 手机 | 看得到正文、待核提示、反馈与导航，独立记录实际反馈 |

NAV-04/05 的可控故障注入优先在原类、隔离数据库及模拟端执行；不为制造异常撤掉真实业务用户权限。现场首次 SOURCE_ACCESS_CHANGED 仍按原 event ID、来源版本前后、调用阶段调查，找不到详细证据时保持根因未知。

## 5. 真实模型复测

通过原 ModelCoordinator 和同一模型重跑上轮 13 个合成场景，逐例仅调用一次，保留原输入、prompt/schema/hash、模型摘要、原始输出、实际候选或 gap、耗时及受测文件指纹。不要只复放冻结 JSON 后称模型通过，不用“多试取最好”替换失败样本。

至少重点核对：

1. F07/F09 内容完整的分类不被无必要拒绝，原值/引文和 unconfirmed 权威不变。
2. NEGATION 保留更正说法；输出仍缺失时必须可见待核。
3. MULTIPROJECT 不丢归属未明内容；F12 不凭唯一上下文猜项目，原因显示归属待核。
4. F15 保留“工程师说”；CONDITION 的条件和结果同行，评审与执行维度准确。
5. 否定/条件的完整候选不能掩盖另一条去掉语境的候选。
6. 甲项目的内容不能挂到允许列表中的乙项目；重复短引文跨项目需待核。
7. 提示词注入内容不能生成批准、正式状态或关闭；空输出、截断和格式错误有明确结果。

增加未用于本轮代码开发的少量独立变体，并让人工先写期望事实。分开报告覆盖、归属、分类、条件否定、业务权威、误拒及延时。没有人工标准答案和独立样本时，只标观察；门禁接受和待核都不自动计准确率。正确同义改写被拒绝须保留为误拒问题。

不自动启动训练或修改其他后训练任务；本包处理运行时契约，真实模型改善继续由相应数据与验证决定。

## 6. 真实业务和可靠性

沿用原授权范围完成独立工程师的一个真实事项，具体预览由本人批准后才发送。核对目标、原文、消息 ID、准确回复归入原事项、待核标签和手机展示；收到或自报完成不自动关闭。

上一轮本人已有的一次发送、两条回复和手机证据继续有效，不为凑重复次数再次外发。真正需要新增发送的场景仍生成新预览并按原流程确认。

另外分别记录：同一有效卡真人双击、真实跨原文到期清理、平台不确定结果及进程崩溃恢复。无法安全复现真实平台故障时，保留隔离证据和未验收状态；不故意在业务发送边界强杀进程制造风险。不把正常重启或过期旧卡点击替代这些场景。

## 7. 回传与判定

沿已确认 GitHub 审核渠道，在 `AM-FOLLOWUP-20261102-01/R1-FIX2/` 维护一个 `00_当前交接.md`，包含源码提交、审核提交、实际变更、加载指纹、测试和模型观察、真实验收、未完成项。公开前排除凭据、真实原文、准确个人/会话 ID、运行数据库与无关附件。

上传后从远端固定提交回读入口、实际增量、manifest 与关键证据，给完整 SHA 固定链接。保留其他任务目录。GPT 独立复审继续由 GPT 实读执行，本机检查和远端回读不替代它。

状态分别记录：代码已合入、已加载、本地验证、真实模型观察、真实用户链路、业务验收。当前任务完成相关场景即可回传，不为无关全量审计扩展范围；任何真正阻塞只暂停依赖部分。
