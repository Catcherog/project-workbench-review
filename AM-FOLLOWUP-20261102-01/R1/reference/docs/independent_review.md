# 本轮独立审阅记录

任务：`AM-FOLLOWUP-20261102-01 / R1`  
日期：2026-11-02（Asia/Shanghai）  
性质：固定原 AM 审核源码定向阅读、新增参考内核独立代码审阅与限定隔离反例复核。

## 1. 结论适用范围

这份交付具备可继续接入原 AM 的架构、可运行的合同内核和隔离验证材料。**它没有在真实原 AM 服务中完成部署、真实群 @、工程师私聊或业务验收。**

本轮重点检查的不是测试数量，而是：是否复用原能力、是否会重复催办、来源改变后是否继续沿用旧批准、是否把收到/方案交付误认为执行完成、是否精确绑定被确认内容和真实发送回执。

最终完整隔离测试结果，以本包 `verification` 目录及当前交接中记录的代码版本为准。本审阅不把组件作者的测试摘要重复累计为独立实测。

## 2. 原 AM 实读依据

固定审核提交：`9ef8076b32ecb5800c70a4f531fa2a859fb6c790`。  
[当前交接入口](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/DESIGN_HANDOFF.md)记录对应最终源码 `aab37396ea86b6e742eed79369583801664d1f35`。

已定向读取的源码族：

- `fs_agent/action_items.py`：原事项、版本、核验人、期限性质、反馈、关闭与暂停。
- `fs_agent/scheduler.py`：原计划、批准、实例、窗口、claim、未知结果屏障与回读。
- `fs_agent/business_port.py`、`reminder.py`、`reminder_feishu.py`、`feishu.py`：原发送端口、群与成员核实、@、uuid、发送异常分类。
- `am_service.py`、`am_business.py`、`am_harness_host.py`：原通知账本、业务入口、反馈绑定与宿主关系。
- `am_info_sync/models.py`、`store.py`、`ingest.py`、`facts.py`、`extraction.py`、`policy.py`、`am_information.py`：来源注册、消息版本、水位、事实候选、权限过滤与来源依赖。

实读支持的判断：

1. 原 AM 已有持久事项、计划、批准、发送实例和 unknown 处理，新模块不应再独立开启发送 worker。
2. 原 `BusinessPort` 私聊分支只支持配置 owner；工程师 `recipient_p2p` 是新增目标类型，不能用修改 owner 来模拟。
3. 原 `ActionItems.feedback(received)` 已不把“收到”当完成，`submitted` 也仍需核验；本轮应保持。
4. 原 `Scheduler.current` 尚未直接涵盖本次要求的全部精确来源版本、外发策略版本与当前覆盖状态，因此新增 EvidenceGate 有实际必要。
5. 原 `Source.readers` 是读取范围，`output_chats` 是对指定聊天回答的可见范围；二者不构成完整的字段/附件/用途外发授权。
6. 已读回执载明 `response=legacy`、旧重写 off、`goal_tracking=false`、`ledger_write=false`。这些只是固定历史执行记录，本轮没有重新观测本机服务。

原 27 项失败也已实读分类：1 项 owner 私聊查询断言、1 项禁用写入批准状态断言、25 项 UX1（其中 24 项落在旧导航共同前置）。这不等于 27 个真实漏洞，也不等于全部与本次无关；本轮真实新入口必须覆盖其重复确认、旧批准、unknown、错误 actor/chat、过期与功能关闭等有效业务意图。

## 3. 新内核审读与本轮修正

| 项目 | 审阅发现 | 当前处理 |
| --- | --- | --- |
| 跨轮次重复发送 | 只有 episode 内注意键时，同一事项/用途/人旧实例 unknown，新提醒窗口能再发 | 增加跨 episode 的 delivery barrier；claim 时原子占位，unknown/重启不释放 |
| 方案交付与事项交付混淆 | “方案已发”被写入开测事项 delivery 后，虽未完成却映射为 submitted | 方案、样机、发布材料拆为上下文字段；任务 delivery 必须匹配其 deliverable_key/subject_key |
| 证据更新后无法恢复 | seed 来源变更和来源冲突最初只能永久阻断 | 增加受审 rebase、source conflict resolution、预期版本 CAS 与历史；不能自动删除或替换来源身份 |
| 快照桥接口不一致 | binding 出现在来源版本字典，却没有对应 ACL key，预览全部被拒绝 | binding 同步纳入 ACL 集合，并绑定完整来源快照和披露策略版本 |
| 错误收件人回读 | 回读函数最初未独立核对 pin 与 request，可把错误 pin 的消息标成请求目标 | 回读独立核对租户、目标类型、目标 ID、目录版、确切会话、机器人、正文与 @ |
| 覆盖依赖被省略 | 原始 snapshot 的 required_coverage 可由调用方省略 | EvidenceBridge 使用服务端 required_coverage；持久化完整快照并对照依赖集合 |
| 原发送 guard 调用形状 | 原 BusinessPort 会调用旧 guard 两次；新 before_send 是一次性 hook | 接入说明明确：保留原两次 guard，在最后一次通过后、SDK create 前单独调用新 hook 一次 |
| 实际展示与用户确认 | HMAC token 只能证明快照，不能证明已展示 | 增加 ConfirmationBridge，读取原 AM 实际已送达预览记录并绑定 actor/app/chat/message/view/manifest/选择行 |

### 独立执行的关键反例

使用临时 SQLite、模拟时钟和无网络 sender，构造同一 tenant/task/purpose/person：

- 修正前：首实例返回 unknown，换新提醒窗口再批准，结果 `['unknown','unknown']`，模拟发送次数 2。
- 修正后：第二批准返回 `prior_delivery_uncertain`，结果 `['unknown','prior_delivery_uncertain']`，模拟发送次数 1。

这项复核证明代码中对应防重反例已修复，**不能代替飞书真实超时、原 Scheduler 与新登记簿跨数据库崩溃恢复验证**。

本轮还提出失效关闭要求：权限 gate、实时许可、真实预览 verified、收件人许可，以及 definitive_no_send 必须按严格布尔值判断；异常字符串不能当作许可或“明确未发”。原回调应显式确认是“发送本次”的动作，不能把查看/修改回调解释为发送批准。这些应纳入最终套件和宿主映射检查。

## 4. 两套状态库的接入解释

本包的参考事项/证据库用于隔离运行与验证合同。生产接入时：

- 原 FactEngine/ActionItems 继续承担其原有事实与事项职责。
- 新登记簿承担跨入口的业务动作身份、批准与注意对象占位；原消息 action/occurrence 继续是实际外发记录。
- `intent_id/request_uuid` 必须持久映射到一个原 action，重复采用返回同一个 action；不能另外新建群发送任务。
- `ExistingAMSender.dispatch` 不得先返回一个排队结果，再由另一个不带 guard 的 worker 稍后发送。
- 真正发送之前，原消费者执行原取消/权限检查，再单独执行新一次性 `before_send`；网络调用发生在这个最后边界之后。
- 原库与新库不天然构成一个事务。任何关联/发送/写回中途崩溃，都应保留 unknown 并只读对账，不能凭空重建第二个 action。
- 个人助手和旧入口未接入同一登记簿之前，不得宣称已经实现跨系统全局去重。
- 旧实例 already sent/unknown 的迁移必须保留原 action/消息身份与状态；换 producer 或版本不授予再次发送权。

## 5. 仍须 Codex 真实验证的边界

1. 原 SDK 回调认证、本人身份、实际预览送达与正确动作值。
2. 真实租户/app 下的 open_id、精确 p2p chat、内部收件人、机器人可达范围与群成员。
3. 群 @ 确实通知指定人，正文未夹带未批准对象；工程师私聊发到正确会话。
4. 当前来源版本、消息编辑/撤回、权限撤销与外发限制能否及时进入现有信息层。
5. 实时 attestor 的依据：本地新快照不能自行证明平台没有变化；不可用时必须阻止相关外发。
6. 实际平台发送响应、message_id、原 action 映射及正文/@读回；同文搜索不是本模块的送达证明。
7. 暂停/撤销与发送边界竞态；已发消息不被错误描述成全部撤回。
8. 旧 Scheduler、即时提醒、个人助手通知与新入口的共享去重接入，尤其进程重启和切换。
9. 本包源字段/候选状态由真实 Qwen 及业务样例产生时的准确性。隔离测试手工构造事实，不是模型提取准确率。
10. 保留原有效配置与后续修改。无需为了使用本轮单次跟进而先打开未验收的通用 goal_tracking 或表达重写。

本审阅到上述范围结束，不以继续增加测试或重审无关模块扩大本轮任务。

