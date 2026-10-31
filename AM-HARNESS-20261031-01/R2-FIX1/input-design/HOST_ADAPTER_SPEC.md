# 正式宿主接线规格

此文件补充主报告；不是已接入声明。

## 1. 参考类型与正式接口的关系

| 主报告概念 | Python 参考 | Codex 必须补齐 |
|---|---|---|
| 不可变 OutcomeEnvelope | `types.OutcomeEnvelope` | schema_version、完整 IntentFrame/GoalProgress、全来源 DependencyManifest、版本化存储 |
| 任务完成条件 | `WorkUnit` 的 requested_operation/target/result | 从真实用户目标和业务状态计算，不由模型文本反推 |
| 类型化事实 | `SemanticClaim` | 当前参考 value 为字符串；实际进度/日期/数值/角色可用类型联合，防止 stringly-typed 值失真 |
| 来源依赖 | `SourceStamp` + `EnvelopeGuard` | 原 scope/identity TTL、集合/负向查询依赖、ACL继承、历史来源；不能只比较内存 hash |
| 计划与提醒 | `TaskFamily.SCHEDULE` | 原 plan/occurrence 状态、批准与实际发送回执 |
| 回复计划 | `ResponsePlan.segments` | 外层 CoordinatorModel `type=response_plan` 分支，schema 大小与原传输预算 |
| 关键呈现块 | `ProtectedBlock` / `LockedSegment` | 真实 preview/action/version/payload hash、卡片及链接渲染，禁止模型构造权威对象 |
| 允许的下一步 | `TextSegment.intent=recommendation` | 真实能力、授权、持久计划与 GoalProgress 的约束；参考枚举本身不构成约束实现 |
| 候选语义风险控制 | `SemanticAssessor` | 有效 profile、领域判定和离线资格证据；无能力时 unavailable，不使用测试 Assessor |
| 最终呈现 | `PreparedResponse` | 稳定 presentation ID、语义/平台载荷 hash、schema/profile版本、TTL、旧 outbox 关联 |
| 提交与投递 | `PresentationCommitter` | `_finish`、原 Store/事务、原 outbox、实际独立回读、旧事件重放 |

## 2. 安全的总入口

使用独立总接入开关，选择 legacy renderer 或新 pipeline；新 pipeline 内的 mode=off 仅表示 HostRenderer，不等于原 R2 off。

每条入口都必须保存真实 `origin_event_id`。Harness 内部事件 ID 与原事件可不同，另存 `engine_event_id`。快路和控制使用 EventBinding；需要模型的独立表达必须有真实 RunBinding 和原调度 admission。

ConversationAgent 的语义准备在 `_finish` 内调用 `finish_event` 之前完成。不要把模型工作放进原数据库事务。原专业卡片的发送入口没有 `_finish` 时，也必须在该路径的第一次正文持久化/排队前调用相同协议接口。

## 3. 校验与保存序列

1. 适配真实工具结果，验证目标类型和回执完整性。
2. 计算宿主完成度，冻结 Outcome；记录版本和依赖。
3. 选择已有主提案、HostRenderer 或已独立 admission 的一次生成。
4. 验证候选及 profile；再检查 live scope、fence、source、TTL。
5. 生成 PreparedResponse，保存最终语义文本与事件的关联。
6. 在原 publication 事务中保存 outbox 绑定；外部网络仍在事务之外。
7. 原 dispatcher 重新检查上下文和依赖，执行原发送/核验。
8. 仅经原规则确认已送达的正文成为后续模型可见历史。

阶段 5 与 6 跨库时不声称原子性：用稳定 ID 关联及幂等对账，继续依赖原历史过滤。禁止用重新生成或重新执行业务来修补记录缺失。

## 4. 模型协议能力合同

建议正式实现声明：provider/protocol/model版本、schema子集、可控制的reasoning模式、工具消息回放规则、私有回放字段、developer role语义、流结束条件、输出截断标志、取消证明、并发控制和服务端会话支持。未知能力应为 unknown，并按保守分支处理。

原 Qwen 适配先复用现有 CoordinatorModel，不引入新 SDK 或模型。若另做 OpenAI/DeepSeek 对照，分别执行协议测试：重复工具ID、工具结果配对、输出为空、截断、不支持参数、取消未知、跨轮回放、thinking/final分离。不能将某端点 HTTP 200 当作这些检查通过。

## 5. 映射必须登记的终端出口

普通模型 answer、context/round limit、快查命中/缺失、跟进、笔记、知识候选与批准、文档生成/采用/发布/挂载、外部预览/确认/取消、计划/提醒/occurrence、Harness状态/停止/更正、失败/过期/未知、重复事件、原卡片和专业路径。

每项记录实际函数、task family、business status、source/receipt来源、required host blocks、使用的renderer、历史/投递路径、测试case IDs、验证状态。被保留为 legacy protected 的出口明确列出剩余工作。

