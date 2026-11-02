# AM 现有能力定向核验（只读）
日期：2026-11-02（Asia/Shanghai）
任务：AM-FOLLOWUP-20261102-01 / R1
核验范围：附件第八至十三章提出的待办、跟进、授权、去重、发送、回读及信息层复用。
本报告是本轮对固定审核提交的代码阅读；没有读取用户本机运行进程、没有运行旧工程完整测试、没有改配置、没有发消息。

## 1. 固定依据
- 审核 SHA：`9ef8076b32ecb5800c70a4f531fa2a859fb6c790`。
- 入口：[R2-FIX2 当前交接](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/DESIGN_HANDOFF.md)。
- 该入口记录最终源码：`aab37396ea86b6e742eed79369583801664d1f35`。
- 该提交的 source 是脱敏审核副本；只能证明此固定副本的实现，Codex 必须以本机原 AM 当前工作树接入，不能用审核副本覆盖原树。
- [运行记录](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/evidence/runtime-final.json)载明：174 份加载文件、原 Qwen、唯一消费者、600 秒身份、`ledger_write=false`、`response=legacy`、旧重写 off、`goal_tracking=false`。这是已有执行记录，本轮未在本机重验。
- [未完成边界](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/03_未完成与验收边界.md)明确：通用目标、专业异步、完整共享事实、精确依赖、自然度与真人验收均有未闭合部分。

## 2. 结论
应新增“证据与业务动作之间的语义层”，并桥接现有事项和发送链路。现有 AM 已经有持久事项、计划、批准、发送实例、unknown、回读和反馈；从零再造 scheduler、outbox、群发送器，会产生双重调度与双重批准问题。

必须新增或扩展的重点：
1. 消息事实转待办候选的受约束映射，允许负责人/项目/日期缺项。
2. 同一业务动作在个人助手与 AM 之间的稳定关联，以及跨生产者的通知账本。
3. 私聊工程师这一明确目标类型；当前业务发送器私聊分支仅支持本人。
4. 来源对象版本、权限/外发规则版与批准绑定，发送前重新校验。
5. 读到“回应”与“执行完成”“验收完成”的独立投影。
6. 有界消息回执关联；无原始ID或结果未知时不自动发出第二条。

## 3. 已实读的能力与复用入口

| 层 | 已实现的代码 | 本轮应复用什么 | 尚缺什么 |
| --- | --- | --- | --- |
| 采集/水位 | am_info_sync.Store, EventBridge, EventWorker | 注册来源、不可变观察、source/object/version、队列租约、重叠窗口、缺口、成功才推进水位 | 不能据此承诺全账号私聊或编辑事件全量覆盖 |
| 事实投影 | FactEngine.process/query | 精确摘录、来源版、主体验证、unconfirmed/source_confirmed/owner_confirmed、权限过滤、冲突、新鲜度 | 尚无本请求完整业务动作/完成条件/回复状态模型 |
| 待办 | ActionItems.create/change/feedback | 原 action_items ID、版本、负责人、核验人、期限性质、暂停、反馈历史、核验关闭 | 无项目或负责人候选不能直接入该表；来源变更不自动影响其 version |
| 调度 | Scheduler.create/approve_plan/scan/approve_occurrence/control/revise/dispatch/reconcile | 原 reminder_plans / action_approvals / reminder_occurrences 和唯一调度器 | 跨个人助手动作去重；精确证据依赖；工程师 p2p |
| 群即时发送 | ReminderService + ReminderPort | 实际预览送达绑定、完整正文批准、群与成员刷新、uuid、发送 guard、unknown、回读 | 不应另开一套群发送执行器 |
| 业务发送 | BusinessPort.prepare/refresh/send/verify/reconcile | 已有 SDK client、群@与正文分离、本人私聊、文本模式与卡片模式、回读 | 当前 target.kind 只有 owner/group；owner 只能 config.owner |
| 反馈 | BusinessCommands.handle_feedback + ActionItems.feedback | 绑定实际消息/occurrence/群/actor；received只记回应；submitted仍待核验 | 自然语言回复需要可靠 reply/thread/action 关联与候选解释 |
| 个人通知 | AmSelfService.notify/delivered | am_notice_keys、outbox、am_notifications 以及私聊回执 | 当前键未证明跨其他助手共享 |

### 3.1 采集与事实层
当前源码：
- [models.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/local-qwen3.8/feishu-bridge/am_info_sync/models.py)
- [store.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/local-qwen3.8/feishu-bridge/am_info_sync/store.py)
- [ingest.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/local-qwen3.8/feishu-bridge/am_info_sync/ingest.py)
- [facts.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/local-qwen3.8/feishu-bridge/am_info_sync/facts.py)
- [extraction.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/local-qwen3.8/feishu-bridge/am_info_sync/extraction.py)

实读要点：
- Observation 用 source_id/object_id/version，occurred_at_ms 是来源更新时刻，不是本地获取时刻。
- Source 固定 kind/remote_id/tenant/owner/start_ms，改变历史授权边界不能静默复用原 source。
- EventBridge 只接受 im.message.receive_v1 与 im.message.recalled_v1；未注册会话不保留正文，重复捕获仍执行原路由，避免“先落库后路由失败”被重试去重吞掉。
- Store 累积水位只有 incremental 且 time_coverage 完整成功才推进；reconcile 不伪造连续历史证明。
- FactEngine.process 检查持久观察完全一致、当前版本、未删除、完整、未过原文保留期；模型候选一律 unconfirmed。
- query 在统计冲突和摘要前过滤权限；保留 stale / incomplete_reasons；源记录不会因一次读取失败被当作“无事实”清掉。
- authority 与 assertion_type 分开。forecast 不能冒充 plan。人工已确认决定不会被晚到消息随意覆盖。
- 普通模型精确摘录只能证明“引文在来源中”，不能证明模型推断的业务含义必然正确；本轮仍须结构化判断和业务验收。

适配建议：
- CandidateBuilder 消费 FactEngine 当前可读事实，不自行读取另一份全量聊天或另建抓取器。
- 候选记录允许未知 project_ref / assignee；只有明确关联后才调用 ActionItems.create。
- 给本人摘要可以写“来源称/尚未核实”，不得为了简洁把未确认候选升级为已确认项目状态。
- source retention 和隐私规则沿用现有体系；长期待办保留必要结构化字段与受控引用，不能借导入延长原始私人消息保留期。

### 3.2 原待办 ActionItems
[源码 action_items.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/action_items.py)

已有字段：id/version/owner/project_ref/description/requirements/assignees/verifier/source/deadline/deadline_kind/timezone/state/paused/latest_feedback/next_check/closed_by/close_evidence/decision_version。
已有状态：waiting, in_progress, blocked, submitted, closed, cancelled。
deadline_kind：unspecified, estimate, commitment, requirement, check。

实际约束：
- create 只允许 owner，要求 project_ref 与 assignees(open_id)非空。
- op/request_hash 实现同一提交幂等；同 op 不同正文拒绝。
- feedback(received) 不改变业务 state；eta 不改正式承诺期限；not_mine 不自动改负责人。
- feedback(submitted) 只到 submitted；close 需要 verifier 与非空核验依据。
- 迟到反馈保留历史但不跨过 decision_version 覆盖新决定。
- 暂停独立 paused；取消与关闭各自保留。

建议最小扩展：
- 用 sidecar action_semantics（item_id 外键）保存 response_status、delivery_status、verification_status、completion_rule、evidence_refs、quality_flags；不要把旧 state 全部推倒。
- 来源已证实审批通过，关闭“待提审”动作时标记 superseded/fulfilled，审批对象状态仍是通过；不能生成“审批撤回”事件。
- 用户“收到”只更新与该消息对应的待回应记录，不能随意关闭所有同项目跟进。

### 3.3 原计划/实例/批准 Scheduler
[源码 scheduler.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/scheduler.py)

已有：
- reminder_plans，action_approvals，reminder_occurrences。
- instance UNIQUE(plan_id,plan_version,scheduled_at)，request_key UNIQUE。
- once/daily/workdays/briefing；preview_each/fixed_rule/owner_subscription。
- 批准绑定版本与快照 hash；改计划、暂停、恢复清空旧批准并递增版本。
- scan 跳过错过窗口，不积压补发；有 unknown 或未完成回读实例时先阻断同事项/计划新发送。
- current 检查 plan版本/有效期/cancel_requested、item_version/paused/closed/cancelled、payload hash。
- guard 在调用发送前再次检查；明确拒绝进入 confirmed_not_sent，可在窗口内沿用原 key 尝试；超时或未知进入 unknown，不盲重发。
- 重启把 sending 变为 unknown。
- 工作日依赖已核实 Calendar(source/version/verified_at/start/end/days)，不擅自以周一至周五替代公司工作日。

新增关键依赖：
- current 尚未直接检查 Observation.version、source.access_version、外发限制策略、source freshness/completeness。应在原 current/preflight 中挂 EvidenceGate。
- 固定规则的变量只允许已批准字段；模型重新改写正文不是“变量填充”，必须按草稿变化处理。
- 原计划批准与实例批准机制应保留；默认单次“确认并发送本次”可合并为一次用户操作，但后台不得省去批准快照和实例记录。
- 跨生产者动作键不能以 plan_id 或草稿hash为核心，否则换计划/润色后又催一次。应采用 canonical_action_id + reason/change_revision + cadence_slot + target identity；稿件hash仅用于批准一致性。

### 3.4 工程师私聊是真缺口
[源码 business_port.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/business_port.py)

当前只有：
- owner -> receive_id_type=open_id，且 target.user 必须是 config.owner。
- group -> receive_id_type=chat_id，经 ReminderPort 的允许群、内部租户、机器人在群、人员在群等校验。

因此不能说“当前已支持向任意工程师私聊跟进”。应新增独立 recipient_p2p 类型，保留 owner 原语义。至少绑定 tenant/app/recipient_open_id/经核实chat_id/target_snapshot_version，确认收件人实际是目标人、机器人具备可发送范围，发送后读回到该确切会话。需要审视对方 p2p 回复的合法来源登记；不能因为给对方发了消息就开放读取用户与对方的个人私聊历史。

不建议靠改 owner 字段、放宽 group 分支或把 p2p 伪装成 group 实现。

### 3.5 群@和未知结果
[reminder.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/reminder.py)
[reminder_feishu.py](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/reminder_feishu.py)

已有的好做法应继承：
- 预览必须实际送达后，才可确认该 revision/hash/nonce 对应草稿。
- 刷新目标群和人，变化就阻止旧批准。
- code-owned @ 标签与用户正文分开，不让正文制造 @all。
- 发送调用 uuid 沿用 request_key。
- 结果未知不换键重发。
- 有 message_id 才精确读回；无 ID 时只在已批准群及小时间窗内读取自身消息，并要求唯一匹配。
- 对账没找到不证明“肯定没发”。未知可能只能人工核对。

新增业务账本必须把“采用旧计划/旧实例”和“已发出/未知”导入同一个动作身份，不得在新模块里以 fresh uuid 当新发送绕过旧屏障。

## 4. 27 项失败的相关性
[regression-comparison.json](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/evidence/regression-comparison.json)

实读分组：
- test_am_self_b：1项，owner private query 不伪装群的返回语义断言。
- test_am_self_entrypoints：1项，disabled write 的批准状态断言（proposed vs approved）。
- test_am_ux1：25项，其中24项在旧导航找按钮的共同前置失败，另1项是 untrusted actor/event key 的处理标记断言。

这不直接证明 27 个业务漏洞，也不证明全部可忽略。多项测试名称覆盖本轮核心场景：旧批准失效、重复确认只建一项一计划、unknown只对账、wrong actor/chat、过期卡、群反馈、多线程绑定、feature关闭等。Codex 应先区分过时测试断言与真实回归，并在本轮实际新入口执行等价场景；只比较失败名称不构成本功能可上线证据。

## 5. 最小接入方案
1. 保持原入口、Qwen ModelCoordinator、唯一消费者、原事务/队列。
2. AMInformation + FactEngine 输出受权限过滤的 evidence/facts；新 CandidateBuilder 生成候选，不直接发消息。
3. ActionRegistry 把个人待办 legacy_id/source alias 与原 action_items.id 关联；原事项存在则补充证据，不重复 create。
4. PreviewAssembler 生成本人简洁预览、精确收件人/渠道/正文/来源与缺项。
5. 用户一次明确确认通过原卡片/会话回调鉴权，生成绑定 batch/各动作证据版/正文hash/目标hash 的批准。
6. 原 Scheduler 建单次或已明确周期 occurrence，原 BusinessPort/ReminderPort发送；新 EvidenceGate 和 NotificationLedger 作为必要前置守卫。
7. 回执写回原实例，同时向统一通知账本同步实际 message_id、未知与回读状态。
8. 工程师回应先关联原 occurrence，再经状态 reducer 只更新被证据支持维度；业务验收仍按原 verifier 规则。
9. 迁移或故障回退使用 ownership_epoch/fencing，停止旧执行器的同一事项发送后才切主；没有可靠消息ID的旧提醒维持 legacy_unknown，不能假定从未发送。

## 6. 实施边界
本轮可产出纯 Python 语义核心、合同、示例、适配接口、故障单元/集成测试；真实 AM 模块映射、原 SQLite 事务接入、SDK 的 recipient_p2p、真实帐号群成员与消息读回由 Codex 在用户授权范围内验证。

不需要先开启未验收的 goal_tracking 或新表达重写才能实现上述单次有证据跟进。普通确定性查询可以直接走现有快路径；模型用于增量事实候选和确认前文案，批准后正文冻结。

## 7. 具体接线合同（新增代码对应位置）

### 7.1 原事实与事项

`evidence.py` 的领域reducer映射到原 `FactEngine.process/query` 和 `ActionItems`。生产继续用原 `action_items.id`；为 response/delivery/acceptance、精确证据依赖等增加附属表或已有JSON字段，不通过复制一个新任务库实现同步。

`TaskSeed`是合成参考对象，不可直接拿其project/owner字段越过原真实映射。先将候选存入候选区，核实project_ref与assignees后再调用旧 `ActionItems.create`。同canonical事项重试使用稳定operation_id；create后别名写回失败时，以该operation_id读回/重放得到原item，禁止重新生成UUID再create。

建议生产新增附属记录：

| 记录 | 关键约束 |
| --- | --- |
| `action_aliases` | tenant/producer/external_id唯一，指向canonical_id与原item_id |
| `action_semantics` | 原item_id外键，四维状态、完成规则、缺项与关联交付对象 |
| `action_evidence_refs` | item/field对应source/object/version/digest，来源改变定位受影响动作 |
| `disclosure_bindings` | 精确目标/字段/附件/用途/策略版，独立于读权限 |
| 本包准入/attention表或等价原表扩展 | 与原action/occurrence保持一一映射，不能自主网络发送 |

以上表名是接入建议，不是声称当前生产已有这些表。迁移以原schema和事务能力为准。

### 7.2 一个按钮对应的后台操作

用户看到的一个“确认并发送本次”，由原鉴权回调启动：

1. 证明点击来自已实际送达的本人预览；action必须是 `confirm_send_once`，核对原消息/会话/选中行manifest。
2. `ConfirmationBridge.confirm`将相应精确token/hash提交 `approve_batch`，逐行登记批准和注意对象占位。
3. 原消费者用稳定intent_id/request_uuid采用已有事项与一个原发送实例；已经采用则返回原实例。
4. 同一批准事件可在后台完成原计划/实例所需记录；用户不需要再点“批准建计划”和“批准发消息”。后台保存原层的完整批准快照，不能将计划状态改为active后跳过实例内容约束。
5. 原实例与准入状态双向绑定；任何崩溃按实际已存在记录恢复。只有后端事务、idempotent op与精确mapping共同成立，才允许进入网络边界。

`ConfirmationBridge.read_delivered`必须从原AM的实际送达/回读记录取得对象，不能从模型文本或调用方传入的`verified=true`构造。`VerifiedCallback`由原SDK验证之后产生；本包不提供HTTP验签服务，字符串ID本身也不是认证。

### 7.3 原发送守卫的准确放置

旧 `BusinessPort.send` 的原guard有两次检查。新before_send只执行一次：

```python
# 位于原 BusinessPort.send 内，复用原 self.g.api.client，不新起发送客户端。
self.refresh(payload)                 # 原来源、群/人和权限核验
if not old_guard():
    raise SendRejected("SCHEDULER_SEND_GUARD")
request = build_original_request(...) # 由本次已批准内容构造原SDK请求
if not old_guard():
    raise SendRejected("SCHEDULER_SEND_GUARD")
new_before_send()                    # 单次、持久化claim/fencing/最终证据检查
response = self.g.api.client.im.v1.message.create(request)
```

此片段说明准确插入点，不是可脱离原服务运行的客户端。不要用 `lambda: old_guard() and new_before_send()`替换原guard；它会被调用两次且new_before_send返回None。

`ExistingAMSender.dispatch`的生产适配器必须在原唯一消费者实际发送该动作时同步完成这段流程；不能先返回queued，随后另一个worker绕开hook裸发。若选择将新契约直接融合到原Scheduler，则保留同样的最终claim和回读语义，不需要并行调用第二轮dispatch。

### 7.4 工程师私聊目标

保持 `owner` 严格等于原config.owner。新增 `recipient_p2p`：

- prepare：R1可发普通text，减少卡片；不把p2p塞进group payload。
- refresh：核对tenant/app/内部用户/open_id、精确机器人私聊chat、目录版和可达范围；读用户与工程师个人私聊不是此动作的副作用。
- send：`receive_id_type=open_id`，收件人为已核验工程师；使用同一原SDK及固定request UUID。
- verify/reconcile：精确message_id、sender bot、chat、正文与mention核对；没有ID时保持unknown，不用同文搜索唯一候选就冒充精确动作证明。
- feedback：使用对方与机器人的真实reply/thread/source_message关联；“谢谢/收到”只记录response，“已交付”先记录交付证据，仍按原verifier核验。

`transport_contract.py`已实现纯请求结构与归一化回读检查。实际SDK类型构造、目录读取和readback reader由原已认证client承接。必须验证消息是否可读回，不因send返回success就标业务完成。

### 7.5 Live gate与缓存

`EvidenceBridge.capture(..., disclosure_policy_revision=...)`绑定服务端已取得的策略版本。`live_attestor`应读原Source/Observation的最新元数据、受影响dirty事件、披露策略及必要覆盖；它返回绑定snapshot/body/audience的短期证明。示例60秒实时证明/15分钟预览快照是参考配置，不是承诺或用户已要求的固定阈值。

缓存以tenant+source/object/version+policy revision+target membership snapshot为键。新消息、撤回、权限变化或业务反馈触发依赖dirty；旧证明立即失效。签名token有效不代表源数据新鲜。不要每次发前无条件全量扫描所有来源，也不要永远用“上次可读”当实时授权。

### 7.6 个人助手接入与切换

R1可以先用一次授权导出/import，逐条建立canonical alias；旧待办和原提醒记录必须一起导入，保留未确认项目/期限与legacy_unknown。双方临时无法共用准入服务时，把该批事项的发送责任留给AM；个人助手继续产生候选并展示AM返回状态。

生产可用同机调用或经过身份验证的内部HTTP/IPC，但接口注册和部署尚未实现。不能假设云端ChatGPT与Studio天然共享数据库或拥有访问本机的网络通道。`IdentityRegistry`和准入核心可测试映射；端到端跨系统重复催办是否消失仍需真实双端验证。

### 7.7 禁止的接入捷径

- 不把旧owner改成任意工程师；不替换Qwen；不启动第二长连接消费者。
- 不给 `evidence_gate/recipient_gate`配置常量True；测试fake不得带入生产。
- 不把LLM输出直接送入 `accept_claim`、`approve`或`close`。
- 不用草稿hash/新plan_id/新episode规避旧unknown。
- 不清空来源依赖或删除旧unknown来解锁发送。
- 不为通过测试直接启用goal_tracking、新重写或ledger_write。
- 不把原27失败全部当本轮通过，也不无理由把全部历史失败变成本轮大重构。

