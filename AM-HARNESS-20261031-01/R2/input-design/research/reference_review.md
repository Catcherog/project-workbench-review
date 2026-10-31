# Outcome/Response 参考代码定向复审

范围：只读 `response_reference/types.py`、`protocols.py`、`policy.py`、`validation.py`、`orchestrator.py` 及相应修改说明，检查事务、来源变化、fallback、批准/取消/unknown 路径。不连接机器人，不跑生产测试，不证明语义或真人验收通过。

## 结论

参考包适合用作 Codex 实施设计起点。核心边界与 FIX1 现状相容：表达准备与持久化分离；在 `_finish` 前定稿；快路/控制无附加模型；主模型末次候选可零附加调用；独立 durable expression 路最多一次；guard 和未知停止继续交给原宿主；控制用 EventBinding，不伪造 Run。

初审发现的两项具体缺口已在源码中补齐并定向读回确认：

| 初审缺口 | 当前修复 | 实读锚点 |
| --- | --- | --- |
| 候选机械校验只检查 claim/block，可能略掉另一工作单元的 failed/unknown 或覆盖缺口 | WorkUnit 增 effect，CoverageGap 成为类型，ProtectedBlock 显式绑定 work_unit_ids/gap_ids/receipt_ids；boundary 要求每个 effect、非 complete、含未决/receipt 的单元及重要 gap、receipt 都有 required block；plan 不可省略 required block | `types.py:134–164`；`validation.py:23–53`，后续 required block 检查 |
| canonical fallback 只查 protected block 子串，未保证宿主指定的保护块顺序 | 按 block.order 遍历，从前一块结束位置开始找后续块，缺失或顺序改变直接拒绝 | `orchestrator.py:45–52` |

代码作者报告参考测试 22 项通过；本定向复审没有重复执行它们。它们是原型合同测试，不是当前机器人、实际数据库、Qwen、飞书投递或业务验收。

## 已确认保留的关键语义

1. `host()` 每次回退前后都调用 live `EnvelopeGuard`；guard 异常不进入生成失败兜底。撤权、过期、取消、版本变化不能使用旧文本 fallback。
2. `ModelNotDispatched`、有停止证明的 `ModelStoppedFailure` 分开；`STOP_UNKNOWN`、原始 TimeoutError、未分类错误向原宿主传播，不能据此释放 lane。
3. free text 只有经可用 SemanticAssessor 的适用 profile 准入；claim IDs 与结构检查明确不证明任意转述语义等价；未接 assessor 时返回当前 canonical Outcome。
4. preview、execution_receipt、cancel、unknown、failure 被 policy 锁为宿主表达。其他可生成 family 也不能略掉已绑定的业务状态/凭据/重要缺口保护块。
5. 模型接口仅 proposal，不携工具、不建 coordinator、不执行副作用、不内部重试。模型生成不在原 SQL 事务内。
6. 生产接入需保留 origin_event_id 和 engine_event_id；RunBinding 与 EventBinding 并不替代原真实事件身份。原 AccessContext 的序列化不能随意加字段，因为 legacy_binding 精确检查字段集合。
7. 文档已说明新 ResponsePolicy.mode=off 仍调用 HostRenderer，其语义不同于旧 R2 off；生产另设总接入开关和兼容 renderer，避免误复用旧开关改变所有回复。

## 仍由生产适配器完成的阻断门

- OutcomeAdapter 只接受已知宿主 schema；校验真实业务对象版本、receipt 状态、目标、payload hash、批准版本和来源。不可从“message=完成”构造成功凭据；保护块内容仍须由可信适配器真实生成。
- 完整运行时类型/大小/schema/时刻/身份检查、非空保护块及元数据脱敏由生产协议适配实现；本包注明只有小型 boundary invariant，不应把 Python type hints 当运行期完整校验。
- EnvelopeGuard 必须查当前权威 scope/grant/fence/dependency/TTL；保留全局 source epoch 直到新的精确依赖全链路通过影子验证。metadata_only 不能仅把原内容标成 metadata；必须新建合法、已最小化的状态结果并重新授权。
- HostRenderer 按任务族构造完整且自然的确定性文本；长 preview/文档走原完整展示合同，不截断批准载荷；输出长度与原平台边界仍需适配。
- PresentationCommitter 对接原 `_finish`/history 与 gateway outbox。两库不是同一分布式事务，继续依 FIX1 历史可见性和精确投递绑定收敛；不得新增“先发消息后记账”的路由。
- 最后提交、dispatch、readback 时继续复查并绑定同一 envelope/payload；PreparedResponse 不表示成功发送，也不表示业务完成。
- 对 unknown 的恢复只读原凭据或执行明确 reconcile；不得因新 renderer 可用而重放业务工具。跨库 receipt 缺失仍为 unknown，不推断 rollback。
- 生产 telemetry 需保存 schema/adapter/prompt/style/renderer/profile 版本与采用/回退原因，并把未覆盖、投影、回退、guard abort 和实际采用、成功送达、真人评价分开。

没有发现需推翻“保留现有 runtime，在宿主新增协议/适配/表达模块”方向的问题。当前可交付为设计参考包；是否可进入生产仍取决于上述适配与原宿主链路验证。
