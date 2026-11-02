# F02 / F05 / F06：候选、依据重审与反馈闭环

## 范围

此变更只在原 AM、ActionItems、Information Store 与原 Scheduler 内修复状态闭环。
没有新增权威事项库、发送客户端、模型调用或后台 worker。单条确认发送、群与私聊共享
业务注意力、unknown 阻断、人验关闭、原始聊天 24 小时保留期继续生效。

实现基于 `31f744a` 的 R4 运行时基线，并使用 F01 的
`FactEngine.query(..., connection=...)` 与最终发送门禁。集成时只采用本次 state 提交；
F01 的依赖提交由主分支单独合入。

## F02：候选采用必须完整提交

`am_followup_state.validate_candidate()` 验证根字段及每层 identity、item、assignees、
fact_ids、history 的类型、取值、数量与长度。缺失业务信息可以保持候选；采用要求完整身份、
描述、负责人及证据。多余可执行字段、错误历史类型不会创建原事项。

`FollowupHost.adopt_candidate()` 的远端授权与事实预读先完成，再进入共享事务：

1. AM Store mutex。
2. Information Store `BEGIN IMMEDIATE`，保持当前事实/来源的本地写入屏障。
3. 原 AM Store 事务。
4. 重读候选 payload、恢复状态与当前 facts；创建或准确复用原事项；规范化历史；写 alias、
   semantics 与 semantic history；最后标记 adopted。

`ActionItems.create(..., conn=c)` 借用同一原生 SQLite 事务，不会内部提交。
任何异常都回滚 item、operation、alias、semantics 和候选采用状态。重试使用同一原操作键，
不会制造第二个事项。相同 canonical 的第二来源允许关联同一项，但描述、要求、负责人、
期限、期限类型与项目必须一致；交付物身份仍走原来的明确冲突检查。

候选确认卡片绑定准确 payload 与迁移恢复状态，并核验真实已投递卡片的原回读内容。
旧卡不能确认后来修改的候选。对已隔离、needs_review 的候选，原导入命令可以提交同一
identity 的明确更正；不会猜测缺失身份或自动选择冲突项。

### 旧孤项迁移的边界

服务启动时只检查：本 owner 的原事项；没有 alias；没有 semantics；source 中的
producer / external_id 与已有候选准确一致。

唯一候选还必须满足完整 canonical identity、所有业务字段一致，以及原
`followup-import/<canonical_id>` 操作记录确实指向该事项，才建立 `linked` 恢复记录。
启动阶段未初始化信息服务，因而只暂停并要求候选复核；owner 确认后以当前证据原子接回
**同一个 item_id**。候选卡片、事项页及 dashboard 提供这一复核入口。

无法唯一确定、内容冲突、身份不全或多个孤项时记录 conflict，暂停且拒绝继续采用，
不任意选择、不删除、不创建替代项。迁移使用 `followup_import_recovery` 和
`followup_import_migration_audit` 记录源内容以外的身份及结果，重复启动幂等。
仅当版本仍是迁移刚暂停的版本时，确认采用才撤销迁移自己的暂停；后续人工暂停不被覆盖。

已有发送、收据、原 occurrence、unknown 及原 request UUID 均不改写。
未完成导入被新预览和旧 Scheduler 两侧共同隔离。无 item_id 的原 owner briefing 保持原行为。

## F05：同一事项的明确依据重审

原生入口：

- 事项页的“重审跟进依据”。
- `/followup 重审 事项ID`：从原来的 source / object / field 取得当前可读版本。
- `/followup 重审 事项ID｜fact_id1,fact_id2`：owner 明确选择本事项的新证据集合；可以明确
  替换已经不可读的旧来源，不会为读取旧原文恢复权限或延长 TTL。

`source_review_card()` 展示移出与加入的来源、准确版本及重审后的完整当前依据。
refs、value、source access epoch 和最早 raw expiry 在同一 Information 事务读取。
卡片与 outbox 到期均不晚于 `min(来源最早 raw expiry, 当前事件 expiry, now + 600s)`。
写 outbox 沿用原 notify 的 epoch 检查；读后撤权不能把旧正文绑定到新 epoch。
卡片同时接入原 query grant / query delivery 链，出队投递再次核验原 inbox 身份、scope
与权限 epoch；卡片已入队后撤权也不会继续投递。
过长正文拒绝生成卡片，不隐藏截断影响确认的内容。

`review_sources_action()` 核验 owner、原会话、真实投递/回读卡片、原 item version、
semantic version、旧 refs hash、新 refs 和权限 epoch 后，执行共享两库事务。
当前 refs 被明确替换；旧 refs 和 claims 留在 `action_semantic_history`；不再受当前证据
支持的字段从当前 claims 中移出并显示待核。该操作不改变 item_id/canonical_id，不发送消息，
也不把自报完成变成人验关闭。

所有旧 preview binding 失效。仅 `crossed_send_boundary=0` 且 queued/claimed 的 intent 被明确
阻止、增加 generation，并在同一事务删除这些**准确 intent** 的 delivery barriers。
这样正在 recipient preflight 的旧 worker 不能再发送，新预览经新的确认可继续。
unknown、crossed=1、已发送历史及其 barriers 保持原样，不靠重审规避对账。

内部 `bind(..., refs=...)` 也采用明确替换语义；`record_claim()` 如发现其他当前 refs 已失效，
要求先重审，不用单字段更新悄悄丢掉其他依赖。bind、adopt、record_claim、review 的本地写入
统一上述 Information → AM 事务顺序；远端刷新和人员授权全部在事务外。

## F06：准确回复独立核验并进入可见反馈

入站仅接收原跟进 occurrence 的准确 reply，保留原 24 小时期限。
处理时独立回读**当前回复 message_id**，检查 sender、chat、parent、类型、时间、删除状态及
正文一致性。私聊当前回复自行证明当前会话，不访问或复活过期 hello 锚点；原 profile 授权
仍保留。群回复保留原群权限核验。正常化的 SDK 回读增加 parent_id / root_id。

准确回复在一个原 AM 事务中写：

- 原 `ActionItems.feedback(..., conn=c)`。
- 原有回复关联 `followup_reply_links`。
- 原反馈幂等 claim / operation。

“收到”等短确认记录为 received；其他内容记录为 reported_update（自报进展、待核对）。
两者都不自动确认交付，不自动关闭。原事项页、历史页和跟进状态可以看到回应；owner 通知
仅显示中性提醒，具体自报文字从历史页在有效期内查看。链接失败会与反馈一起回滚，重试只产生
一次反馈。

### 保留期

当前回复原文只放在新增的 `item_feedback_raw`（带准确 expiry），以及原来同期限的 inbox。
长期 item_feedback.body、latest_feedback、item_operations.result 只留中性状态与源身份；
request_hash 保留幂等校验，不保留正文。历史 UI 的卡片和 outbox 也封顶最早 raw expiry。
`AmSelfService.step()` 清理过期 raw 表，原归档流程同步删除 raw；到期后 UI 只显示
“原文已过留存期，回应记录保留”。

## 本地验证与真实环境验收

专项测试由原 native fixture、真实 SQLite 事务及模拟平台构成，不接真实飞书、网络或模型。
原 `test_followup_native.py` 的 45 个断言保持；fixture 增加“平台持有入站消息”的模拟数据，
以支持独立回读当前 reply。四个原正确行为回归已原样纳入 state 回归文件，再补充：

- 嵌套 schema、采用事务中途失败、并发幂等、同 canonical 字段冲突与合法第二 alias。
- 旧孤项单例复用、多项冲突与原 unknown 保留。
- 原生重审卡、旧卡失效、后续来源变动、权限 epoch / TTL、4 个入口跨库锁序。
- 已 claimed 且占有 barrier 时重审：旧 SDK 0 次，新确认可发送；unknown barrier 原样保留。
- 当前回复身份/会话/parent/正文不匹配，反馈事务回滚、幂等、自报未完成以及 raw 到期清理。

本分支最终专项运行：`95 passed, 2 warnings in 21.31s`，退出码 0。
构成为原 native 45 项、state 回归 35 项、已集成 F01 回归 15 项；两个 warning 为既有
Lark SDK 的弃用提示。运行命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/r2-audit-python-deps:FS-AGENT-GROK-POC-20261017-01_R1_Studio/src:FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests:local-qwen3.8/feishu-bridge:am-conversation-r1/src python -m pytest FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests/test_followup_native.py FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests/test_followup_state_regressions.py FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests/test_followup_final_dependencies.py -q -p no:cacheprovider
```

另针对 `test_am_self_fix1.py::test_F04_next_briefing_body_and_attempt_association` 原有
4 种结局回归，结果 `4 passed, 2 warnings in 5.35s`，退出码 0；其断言保持不变。

主审整合后负责完整工程回归。Codex 在真实环境仍须核对：Feishu SDK 的实际 parent/root
字段与 message readback；群/私聊及手机卡片展示；来源刷新适配器；历史孤项和 unknown
迁移数据；权限变化与原文到期的真实 outbox 行为。本地测试不构成 Qwen 9 个场景的业务
准确性验收，也不构成真实业务人验关闭。
