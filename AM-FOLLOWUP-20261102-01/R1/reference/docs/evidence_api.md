# 证据与待办语义内核：API 和接入边界

任务：AM-FOLLOWUP-20261102-01 / R1。该模块是可执行的隔离参考实现，没有接入真实飞书，没有调用 Qwen，没有修改台账，也没有给任何人发消息。

## 1. 生产接入位置

`src/am_followup/evidence.py` 用标准库 SQLite 展示领域不变量，并为合成验收提供可复现状态。在真实 AM 中，应把接口映射回已有 `fs_agent/information` 的 FactEngine、Observation、来源版本与权限过滤，以及已有 `action_items.py` 的 ActionItems。**不要同时把本模块 SQLite 与旧 ActionItems 作为两份可写的权威待办。**

推荐保留原待办 ID；`TaskSeed.canonical_key` 记录经过明确映射的业务身份，如既有工作项 ID + 事项类型 + 交付对象。它不使用文字相似度自动合并不同业务事项，也不把模型猜出的项目号当成正式身份。冲突映射需要显式协调。`create_task` 对同一 tenant 的 task ID / canonical key 设置唯一约束，重复完全相同的导入返回已有对象；同键不同内容报错，不覆盖用户修改。

本模块中的 `ef_` 表允许与其他模块同库存在，但这仅方便隔离演示。它没有实现生产数据迁移、双写、后台守护进程或旧库替换。

## 2. 数据边界

### SourceEvidence

必填字段：

| 字段 | 含义 |
| --- | --- |
| `tenant_id` | 租户隔离边界，与当前 EvidenceLedger 一致 |
| `namespace` | 来源平台命名空间；同一平台的不同采集器使用相同值 |
| `source_type`、`scope_id`、`native_id` | 来源种类、原会话/文档范围、稳定原始 ID |
| `version` | 上游原始版本标识；不可根据读取时钟伪造“新版本” |
| `text` | 已获授权、用于核验的最小必要原文片段；不要求复制整个会话 |
| `event_time`、`observed_at` | 来源时间、采集时间；必须有明确 UTC offset |
| `acl_version` | 已核实的来源可见策略版本 |
| `audience_keys` | 可披露给哪些精确受众，如 `person:ou_demo`、`chat:oc_demo` |

可选字段：`version_seq` 是上游可证明的整数顺序，`replaces_version` 是可信上游明确给出的前驱版本；两者都没有时，不按字母顺序或时间戳猜版本先后。`stable_id=False` 用于历史截图、手工摘录等缺乏可靠原始 ID 的导入；可保留候选，但不得自动对外发送。`sensitivity=private` 表示与项目无关的私人信息，不能建立项目任务或事实候选；**不等于“飞书私聊渠道”本身**，有授权的工作私聊仍可标为 internal/restricted。

同消息跨采集器共用 `source_key`，但各采集器的读取水位分开。`observed_at` 不计入版本摘要，因此同一消息再次读到不会制造新的事实版本。正文或 ACL 等受控信息变化会影响摘要；相同版本号却出现不同内容记为冲突。

### TaskSeed 与事实字段

`TaskSeed` 包含 task ID、canonical key、动作、最小来源引用、可选项目/责任人/原文期限/业务时区、导入来源、事项目的、是否要求验收和 `deliverable_key`（本事项约定的目标交付物身份）。缺失值保留 `None`。没有稳定来源的导入保留为 provisional，直到在现有 AM 的受信流程中补齐依据；不会因本轮页面读取失败而消失。

四个核心状态独立存储：

| 字段 | 支持值 | 业务解释 |
| --- | --- | --- |
| `execution` | unknown / planned / in_progress / done / blocked / cancelled | 执行事实 |
| `response` | not_required / pending / acknowledged | 对具体消息的回应 |
| `delivery` | unknown / pending / delivered | 交付事实 |
| `acceptance` | not_required / pending / accepted / rejected | 验收事实 |

补充字段包括 `approval`、`external_release`、`actual_start`、`actual_release`、`planned_start`、`planned_release`、`deadline_text`、`owner_id`、`project_id`、`action`、`risk`、`blocker`、`completion_condition` 和 `test_overview`。上下文材料另有 `plan_delivery`（方案交付）、`release_materials`（发布准备材料）、`sample_arrival`（样机到货）。枚举字段会校验允许值；开放字段保留受核实的字符串，不自行推算日期和百分比。

“执行 done + 要求验收时 acceptance accepted”才形成 `business_completed=True`，并输出完成所依据的 claim IDs。对于“确认是否开测”任务，方案已发送只变更 `plan_delivery`，开测事项仍 open / waiting；开测计划只变更 planned_start；“本周发布”只变更 planned_release。`delivery` 只能表达本事项的目标交付物，候选的 `subject_key` 必须与 seed 的 `deliverable_key` 精确匹配，否则拒绝。发布准备材料齐备不把发布事项标为 submitted。“收到/OK”必须绑定具体 pending response claim，并明确 supersede 它；不能跨事项解除等待，更不能改变 execution。

审批已通过可以令 `purpose=approval_submission` 的旧提审动作成为 `obsolete_action=True`，但不会写入 withdrawn，不会将项目标为完成。真实审批撤回需要另外一条已核实的 withdrawn 事实。

### 旧 ActionItems 的映射

`task_view` 输出 `legacy_action_status`，它是建议映射，不直接写旧库：

| 新视图 | 旧状态建议 | 仍须保留的附加含义 |
| --- | --- | --- |
| open / needs_verification | waiting | 待核实、来源失效、冲突等原因 |
| in_progress | in_progress | 执行依据 |
| blocked | blocked | 阻塞事实 |
| delivered_waiting_acceptance | submitted | 已交付但未验收 |
| completed | closed | 原 close 接口要求的 verifier 和 evidence |
| superseded_action | closed | `close_reason=obsolete_action`，不等于项目完成 |
| cancelled | cancelled | 明确取消依据 |

生产适配器仍须经过旧服务的权限、版本、验证人和 evidence 检查，不可直接把字符串写进数据库。暂停计划不改变这些业务状态。

## 3. 可调用接口

```python
ledger = EvidenceLedger("/tmp/demo.sqlite3", tenant_id="tenant_demo")

result = ledger.ingest(source_evidence)
# result.ref: EvidenceRef; result.status:
# inserted / duplicate / advanced / historical / conflict / unordered

task = ledger.create_task(task_seed)
claim_id = ledger.propose(fact_proposal)
view = ledger.task_view(task_id)

# 仅内部可信语义审核调用；不暴露给 LLM，也不把用户传入的名字当认证。
view = ledger.accept_claim(claim_id, reviewer_id, expected_task_version)
# 或 ledger.reject_claim(claim_id, reviewer_id, expected_task_version)

project = ledger.project_view(project_id)

snapshot = ledger.snapshot(
    [task_id],
    required_coverage=[CoverageKey("approved_scanner", "message", "oc_demo")],
)
wire_value = snapshot.to_dict()
snapshot = EvidenceSnapshot.from_dict(wire_value)
reasons = ledger.check_snapshot(
    snapshot, ["chat:oc_demo"], now=now_iso, max_age_seconds=300,
)
```

`check_snapshot` 返回空 tuple 表示本地证据依赖检查未发现阻塞，**不授予发送权限**。发送模块还须检查实际用户批准、收件人解析、现场 ACL、旧 AM ActionHub 的守卫、真正的发送目的和信息限制。一个群的受众是全体可读成员，不能用仅被 @ 的成员代替群可见范围。

快照包括 tenant、每个 task 的版本、所有相关来源精确版本与 ACL 版本，以及指定覆盖检查点版本。删掉来源依赖会被拒绝。task 候选新增、事实接受、来源编辑/撤回/冲突都会改变相关任务版本，使旧预览失效。快照的 required_coverage 必须由服务端政策确定；不能由客户端任意删减。

生产 `EvidenceGate` 应把领域快照和原系统的 permission/dependency hash 一起绑定到预览。实时核验不能只看本地库是否没变：本地没有收到更新不代表远端没有编辑、撤回或 ACL 变化。事件能力缺失时，发送前必须在已有授权范围内定向重读关键依赖；重读失败则阻止该次外发并保留草稿。

## 4. 候选抽取和语义审核

`FactProposal` 一次只表达一个 task 的一个字段，带有一组 `QuoteSpan(ref,start,end,quote)`。代码按 Python Unicode 字符位置校验引文确实存在于对应来源版本。它验证归属与来源完整性，**不能证明引文在语义上蕴含候选值**。

因此 `propose` 只创建 candidate，永远不直接更新事实。`accept_claim` 是受信的服务内部 API：可以由已核实平台结构化事件映射器、经真实验收的严格语义校验器或用户人工核实流程调用。传入 `reviewer_id` 仅用于审计，身份必须由原 AM 的认证上下文提供。不要把“带了原文 quote 的模型输出”直接传给 accept_claim。

同字段两个已核实但不同值会并存，视图标 conflict，不采取最后写入覆盖。解决冲突时新候选必须显式列出需要替代的 accepted claim IDs。supersedes 只能指向同一 task 的同一字段。旧事实保留 superseded 状态以便审计。

模型不得生成发送授权、修改原始 ACL、选择群成员可见范围或决定无证据的“验收通过”。包含命令式文本的消息仍只是待解释的来源文本。模块不提供工具执行功能。

## 5. 读取事务和覆盖缺口

`CoverageKey(producer,source_type,scope_id)` 是检查点唯一范围。网页检查、一次性 CLI 补读和 AM 事件摄取使用不同 producer；消息、日历、审批与不同会话分别记录。

```python
read = ReadResult(
    key=CoverageKey("approved_scanner", "message", "oc_demo"),
    status="success", started_at=start_iso, finished_at=end_iso,
    expected_version=old_checkpoint_version, cursor=actual_processed_cursor,
    cursor_seq=verified_sequence_if_available,
)
ledger.ingest_batch(observations, read)
```

`ingest_batch` 把证据记录和对应水位置于一个 SQLite 事务。任何校验失败会同时回滚。只有该精确范围完整成功才可以提供并推进 cursor；partial / failed / skipped 不允许给新 cursor。部分会话成功应拆为各自成功范围，未读范围另记失败/缺口。并发扫描使用 expected_version，旧读取结果或旧游标不能覆盖较新检查点。

`add_gap` 明确保留历史缺口；普通读取成功不会清除它。`resolve_gap` 要求受信覆盖对账生成的、稳定且当前有效的 `coverage_proof` 来源，范围必须一致，并记录审核人。范围核对的真实性仍取决于真实采集适配器，不能让 LLM 自称“全部补齐”来生成证明。

`display_time` 只转换来源时间戳。正文“10 点前”“本周”等业务时间保留原文，无法确认业务时区时不生成绝对期限。

## 6. 受审恢复与纠正

来源冲突和旧 seed 版本不会自动恢复，也不需要手改数据库绕过。新增两个明确的受审接口：

```python
state = ledger.source_state(source_key)
ledger.resolve_source_conflict(
    source_key, explicitly_selected_ref, reviewer_id,
    expected_state_version=state["state_version"],
    explanation="已回读权威来源并核实明确版本",
)
view = ledger.task_view(task_id)
ledger.review_rebase_task(
    task_id, new_seed_refs, reviewer_id,
    expected_task_version=view["version"],
    explanation="已核实原项目、责任人、动作等字段仍由新版本支持",
)
history = ledger.seed_history(task_id)
```

`resolve_source_conflict` 必须明确选定已存储的来源版本；受审期间来源世代发生变化即拒绝。它保留冲突原文和恢复审计，不采取时间最新即权威。选择必须属于同一 source key，provisional 来源不能解决权威来源冲突。对于同版本号的两份异文，不能把任意新 payload 当作已核验版本；可以选择原存储版本，或者在获取到真正的后续来源版本后明确选择该新版本。来源版本号与摘要不能偷偷改写。

`review_rebase_task` 只更新同一来源身份的引用版本；不能删除来源、换成无关消息、改 task/canonical identity、项目、负责人、动作或完成规则。所有来源必须当前有效、无冲突且可用于项目任务。原 seed 和每次恢复都保留历史；任务版本递增，旧预览和批准失效。若实际业务字段也变化，应另用经过核实的字段 claim 与 supersedes 更新，不能借 rebase 掩盖。原 claim 不会被此操作自动改写；它自己的旧依据仍需独立重核。

这两个接口与 accept_claim 一样，是服务内可信操作，不是公开授权接口。恢复仅恢复事实可用性，不恢复发送授权、不创建消息。

## 7. 边界与未实现部分

- 同源不可排序版本或同版本异文会 fail closed。以上恢复接口需要可信语义审核与现有权限上下文；代码不会自动决定谁是权威。真实 AM 应经已有 FactEngine/ActionItems 的明确纠正流程映射这些接口，再重新形成有效快照。
- 没有完整自然语言抽取器；没有宣称语义准确率。代码提供候选契约、出处校验和人工/可信规则接受边界。真实 Qwen 的 JSON 输出、原文蕴含、项目关联、责任人解析、回复关联需要 Codex 补齐并真实评估。
- audience_keys 是已核实策略的快照，不会自己查询最新群成员。附件访问与外发许可、字段级脱敏、个人工作私聊是否可读，都要由现有权限层和外部策略处理。
- 没有对所有附件自动解析；没有自动补齐历史消息；没有把日历空网格转为“没有工作”。
- `project_view` 是读取视图，返回有证据字段、候选、冲突、缺项与覆盖状态，不生成进度百分比或暗示账户全部同步。生产渲染必须先做原用户可见范围过滤；此类内部 API 不直接提供给未认证用户。
- SQLite 事务验证用于单机文件数据库；没有声明跨机或分布式事务保证。没有启动新的消息消费者。

## 8. 本轮检查

运行：`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_evidence.py' -v`。

测试数据全为合成项目、合成账号和合成消息 ID。涵盖回应与完成分离、审批旧待办清理、发布/开测计划与实际分离、限制外发状态不被概述覆盖、编辑撤回、同版本冲突、乱序、私密材料、时区、缺ID导入、检查点故障、持久缺口、原子回滚、线程并发 CAS、重启及跨 tenant 隔离。检查数量与最终命令结果以总包 verification 记录为准。
