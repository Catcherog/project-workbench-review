# 当前 Harness 基线定向核对与集成设计

审查对象：`Catcherog/project-workbench-review@cd35c28d4524284b52e77763784ac4c2d15cd3e4 / AM-HARNESS-20261031-01/R1-FIX1`。交接报告的最终源码为 `d3e40b0d27517d75e850613c4eaecec107efa0ea`，起点为保留 R2 的 `b9b0444edf34aeb962b982fca0501dc7df7d83da`。

本文件供 GPT 设计与 Codex 后续实施使用，不是部署批准或新验收结论。

## 1. 结论与证据边界

F01—F05 的修复实现已进入固定 FIX1 源码，不能再把“停止后本地工具仍提交、已投递历史没有进入下一轮提示、快慢路焦点分裂、派发前预算拒绝隔离全局 lane、维护过期不收尾”原样列作当前五个未修缺陷。下一步应在现有宿主上增加统一 Outcome/Response、结构化事实与来源依赖、分层恢复接口，保留既有本地提交 fence、原 outbox、批准凭据、唯一消费者和原模型仲裁。

三类证据分别标注：

| 标记 | 本轮实际取得 | 能支持的结论 |
| --- | --- | --- |
| 实读 | FIX1 当前交接、修复验证说明、FINAL.diff、12 个受影响运行文件；15 个保存对象的 Git blob SHA 均与工具返回一致 | 修复代码和设计集成点确实存在于固定审核副本；可做静态路径分析 |
| 报告 | 原机/重建逐用例结果、158 个加载文件一致、唯一消费者及限定实测均来自 FIX1 执行报告 | 可如实引用执行方报告，不能写成本轮已独立复跑或已连接运行服务 |
| 推断/设计 | 依据实读代码分析剩余结构限制及提出新接口 | 不是已经实现的功能，也不是已证明的生产缺陷或性能提升 |

本轮没有下载全部 FIX1 资料，没有复跑任何测试，没有连接原机器人，没有写入 GitHub、飞书、运行配置或数据库。定向源索引见 `fix1/source_index.json`。

未变更模块在本文引用既有冻结 R2 副本，且未出现在 FIX1 的 16 文件差异列表中。这属于“旧基线实读 + 本次差异表确认未改”，不是对这些文件再次作 FIX1 远端逐个读回。下文用 `FIX1:` 和 `R2-unchanged:` 明示来源。

## 2. 已修项目：具体代码与不能重开的旧结论

| 项目 | 当前实读行为 | 精确锚点 | 继续设计时的保留要求 |
| --- | --- | --- | --- |
| F01 本地工具提交 | `local_executor` 将普通本地工具绑定当前任务 fence；同库在实际事务开始/提交前检查；跨库先持久占用，再在取消锁内完成本地事务及本地回执；未知只对账 | `FIX1: am_harness_host.py:88–93,373–377`；`engine.py:418–428,449–452`；`am_harness/reservation.py:76–152,167–203`；`fs_agent/store.py:78–99` | 普通登记/暂停/恢复不新增用户批准；取消不能抹去已经提交的业务结果；跨库不是分布式原子提交；未知不能自动重放 |
| F02 实际送达历史 | 读取稳定消息 ID 和原 event_id；Harness 回答须当前 revision/epoch/generation 有效、sent+verified；再要求原 outbox sent、conversation output acknowledged、精确正文匹配；沿被选历史传播依赖与绝对有效期 | `FIX1: am_harness/history_adapter.py:40–82`；`host_context.py:52–79,102–112` | 统一表达必须在历史入库前定稿；禁止按相同正文猜身份或给历史事实续期 |
| F03 同一焦点 | 原会话与快路共用 `HostFocus`；以 `am_inbox.rowid` 的事件顺序更新，核对权限/项目/任务版本；有效期上限原消息创建后 600 秒；新未解析输入先使旧焦点失效 | `FIX1: am_harness_host.py:94–99,220–223`；`am_harness/host_focus.py:14–71` | 不再建设第二个并行 focus store；对象解析失败要澄清，不能回用旧项目 |
| F04 预算拒绝 | 可选任务/知识按完整条目选取；省略原因有遥测；只有专用 `LocalPreparationRefusal` 且 proof 指向本次执行、dispatches 为空，才按确定性派发前拒绝收尾 | `FIX1: host_context.py:80–114`；`context.py:216–311`；`runtime.py:20–40,107–163`；`am_harness_host.py:438–445` | 不以任意异常字符串认定“未派发”；模型、local tool、external action 派发后发生的未知仍隔离 |
| F05 终态同步 | 维护得到的终态生成 `run/revision/state` 幂等同步记录；更新 inbox；failed/expired/unknown 在身份、TTL 有效时由原 notify 发送，暂时失败重试通知、过期 suppress | `FIX1: am_harness_host.py:112–116,274–331,359–370` | 这是状态/通知收尾，不是业务重试；不清 provider pause，不延长内容期限，不重启旧任务 |

F01 覆盖的是本地工具 executor 与实际 store 事务的集成。新增 Outcome 适配时，需逐路径核对 `_control`、草稿创建、presentation ack 等既有事务边界，不能仅因存在 `local_executor` 就在新设计中声称任意来源的数据库写入都处于同一事务。此处是集成范围提醒，未将这些旧直达路径认定为新缺陷。

### 执行报告的正确引用

FIX1 报告称：五条原回归从 5 失败变为 5 通过；新增宿主检查共 54 项（包含上述五条，不重复累计）；Harness 130 项、会话含 R2 193 项通过且无跳过；完整工程 638 项为 611 通过、27 个已存在失败，退出码为 1。报告还称 256 源码指纹、158 加载文件一致，运行消费者为 1。

这些数字不能与 R2 的“276 通过、3 跳过”拼接成全套当前验收结果。FIX1 自己明确保留 27 个旧失败及未完成验收。限定真实验证由 Codex 沿原 CLI 发起，不能改称用户手机或独立真人验收。[报告锚点：`FIX1: 00_当前交接.md:25–54`，`01_修复与验证.md:31–46`]

## 3. 仍存在的结构限制与证据

### 3.1 末端表达没有一个覆盖全部路径的语义出口

普通 `_run` 的模型回答仅在没有 local_results、没有 pending、没有 protected_answer 时进入现有 R2 finalizer。预览、可信本地回执、知识候选、context/round limit、内部控制及 Harness control/terminal notice 都有自己的出口。当前关闭 R2 不等于这些出口没有回复，而是它们不具备统一的结构化内容及表达策略。

关键路径：

| 路径 | 当前出口 | 推荐适配方式 |
| --- | --- | --- |
| 模型问答 | `engine._run:350–395` | 形成含事实/缺口的 Outcome，再统一 renderer；旧 finalizer 避免重复调用 |
| 快路 | `engine.handle_fastpath:147–189` | 从可信项目字段直接形成 Outcome；确定性自然语句；保留 5 秒快路无模型等待的约束 |
| 本地可信记录 | `engine._run:433–438,461–462` | 业务 receipt 成为不可虚构的 effect summary；只自然化外围语句 |
| 外部预览 | `engine._preview_reply:483–489` | protected block 精确保存 preview/action/version/digest；渲染器不得改批准载荷 |
| 批准/取消/执行结果 | `engine._control:198–263` | 从 action 状态和凭据构建 Outcome；unknown/failed/succeeded 必须分别表达 |
| Harness 停止/状态/更正 | `am_harness_host._admit_source:190–205` | deterministic control Outcome；不要为了统一接口新建 Run |
| 排队过期/失败/未知 | `am_harness_host.failure_notice:308–331` | data-free terminal Outcome；沿 FIX1 terminal sync 原幂等键发送 |
| 原专业流程和卡片 | 原 service/views/document 路径 | 分期加兼容适配；首期精确保留原文本/卡片，不把“有 envelope”记作已完成拟人化覆盖 |

**不能只在 `LegacyConversationBridge.prepare_reply` 做二次改写。** `_finish` 已在 `engine.py:191–196` 持久化 reply 和 assistant 历史，宿主随后才调用 `prepare_reply`（`am_harness_host.py:50–53`）。在后者首次变更语义文本，会破坏 F02 刚修好的历史与发送一致性。统一语义最终化应位于 `_finish` 写入之前；`prepare_reply` 保留确定性的 display、授权复核与 outbox 绑定职责。

### 3.2 R2 事实合同覆盖低，结构问题早于遣词造句

`R2-unchanged: am_reply/compiler.py:186–270` 只为无歧义的单项目单字段查询构建合同，拒绝复杂/来源问题、未合并 information facts、冲突投影、非 verified 身份。只有人员职责能够拆出有等价 variants 的结构；进展、日期、待办大多保持完整原文块。`pipeline.py:73–76` 明确将这类 `ledger_source_block` 记作 source_projection 并不调用表达模型。

因此，扩大末端提示词无法自动扩大业务覆盖。需要先把工具/投影层的权威事实转成带实体、关系、时间类型、状态、否定、条件、冲突、缺口和来源的结构。模型原草稿不是新证据；不能让 renderer 自行从混合原文“认领”事实为权威。未完成结构化的内容保留完整受保护块，并诚实记录为未覆盖。

### 3.3 全局来源权限 epoch 仍会导致无关来源变化使当前请求中止

`R2-unchanged: am_info_sync/store.py:133–155,185–188,457–469,529–531` 维护单例 `namespace:revision`，在来源启停/reader/output 范围、读取身份、撤权、恢复等相关变化时推进。`LegacyConversationBridge.authorize:275–278`、`delivery_source_authorized:269–273`、`am_query.py:279–283` 和 `am_service.notify:228–235` 都比对这一全局版本。FIX1 `host_context.py:19` 与 `host_focus.py:21` 的权限指纹也包含它。

它是保守的撤权机制，不能直接删除。结构限制在于未区分本轮实际依赖来源与其他来源的权限变化；FIX1 执行报告也记录一条测试笔记关闭被 `SOURCE_ACCESS_CHANGED` 拦截（当前仍 open v1）。这并不证明所有内容刷新都会推进全局 epoch，更不能用它证明撤权守卫本身有错。

### 3.4 状态需要分轴，不能从 run.succeeded 生成“业务已完成”

`TaskRuntime.run_once` 在 runner 返回并与 outbox 入队同事务成功后完成 Run（`FIX1: runtime.py:114–127`）；`R2-unchanged: effects.py:103–130` 在之后的发送前再核对 fence。`engine._control:253–263` 可返回 execution_unknown/failed 的正常回复，外层任务本身仍能成功生成并排队。

统一协议必须同时保留：任务运行状态、业务动作状态、本地记录状态、投递/核对状态。控制响应可以引用既有 Run 而不创建新 Run。`waiting_review` 是现有 store 可表示的状态，不应仅因“需要用户确认”就把当前执行器所有 preview 转成该状态；当前预览的事实载体是 action draft 和 reply.needs_confirmation。

### 3.5 恢复基础已具备，但尚不是任意图节点断点续跑

`FIX1: host_context.py:36–51` 实际缓存的是 `source_projection` 纯投影。任务/模型 lease、action journal、本地跨库 receipt、outbox 与 terminal sync 各有自己的状态。

`reservation.reconcile_local_commit:177–203` 只读取两个配置原库的本地回执；缺失回执返回 unknown，不能推断回滚；它不重放工具，也不释放模型 lane。`R2-unchanged: am_harness/store.py:738–796` 的解除隔离需要可信停止/未派发证明。下一步应做“可观察的恢复目录与分层 reconciler”，而不是画一个通用 resume 箭头让同一工具再次执行。

### 3.6 工具选择与端到端延迟仍有实际限制

FIX1 报告中，含糊登记先因项目不明被拒绝，另一次模型创建了工作笔记而非跟进；第一次自然语言取消只有回复，明确参数诊断后才真取消。创建/暂停实测约 54.71/93.27 秒；常规问答约 16–39 秒。应区分权限正确拒绝、对象/工具路由错误、模型时延、队列时延、表达增量时延和投递回读时延，不能将这些问题统称为“不够拟人”。[报告：`00_当前交接.md:37–46`]

## 4. Outcome / Response 的最小集成契约

本节是设计，不是现有代码声明。建议新增小模块，第一期不替换原 runtime/store/provider，也不迁入新的 SDK 或新增消费者。

### 4.1 保留三种身份

`origin_event_id` 对应真实入站；`engine_event_id` 对应 `harness:{run}:v{revision}`；可选 `run_binding` 包括 run_id/scope/revision/cancel_epoch/generation。控制和快路没有新 Run 时允许 binding 缺省。不能把目标任务 ID 当作控制事件自身的执行身份，也不能按文本反推身份。

### 4.2 Outcome 记录事实，Response 记录表达决定

Outcome 至少包含 schema_version、上述身份、route、intent、machine_status、权威 facts、缺失/冲突/覆盖范围、effect receipt refs、protected blocks、来源依赖、absolute expiry、原确定性 fallback，以及可表达限制。facts 的每个 claim 带 claim_id、subject、predicate、value、qualifiers、source refs；由可信读取/业务适配器构造。

Response 至少包含选定 text/blocks、semantic hash、rendered hash、Outcome hash、renderer/prompt/style 版本、采用方式、覆盖 claim IDs、必要保护块校验、预算及拒绝/回退原因。未进入模型、仅投影、模型尝试失败、候选被拒、候选最终采用、已送达并核对必须分别计数。

新模块建议：`am_conversation/outcomes.py`（数据协议/严格校验）；`outcome_adapters.py`（当前路径到协议）；`response_pipeline.py`（共同 finalization）；`am_reply/renderers.py`（确定性模板/受限模型候选）。如团队把协议包放在 `am_harness`，也应避免让业务 agent 反向依赖宿主实例；数据类型应可独立导入。

### 4.3 正确接入点

1. `_run`、`_control`、fastpath consume 和 `_preview_reply` 产出 Outcome，不在末端从一段已生成文本反向猜业务事实。过渡期可接受 `LegacyOutcome(protected original text)`，明确它不计结构化覆盖。
2. `ConversationAgent._finish` 在落库前调用共同 pipeline 得到最终 AgentReply；内部 `_run` 的旧 R2 finalizer只保留兼容/特性开关一条调用，避免双改写、双算延迟。
3. `ConversationStore.finish_event` 的 reply 保存最终选择文本与版本化 envelope 关联。重复 event 返回当初已提交结果，不因新 renderer/prompt 版本再生成。
4. `LegacyConversationBridge.prepare_reply` 仅 display 和授权/绑定，持久原语义 hash 与 rendered hash；`enqueue_reply` 在原 gateway 事务内保存 Response 引用或完整最小 payload。
5. `HarnessHost.publish`、`FencedOutbox` 继续把原 outbox 和 run fence 一次提交；不得在这一 SQL 事务里做模型、网络、重新读取来源或耗时自然化。
6. `HarnessHost._admit_source` 的 control、`failure_notice` 使用同一 Response 数据接口，但用确定性 renderer，保留各自独立授权和原去重键。`AmSelfService.notify` 可加兼容 envelope 参数，不能让每个原卡片/专业流程被动进入 LLM。
7. delivery callback 只依据精确已发送 payload 和原核对结果推进 delivery/ack。响应中“已完成”只取自对应业务 receipt，不取自 outbox.sent 或 run.succeeded。

另一个实际兼容约束是 `R2-unchanged: am_harness/legacy_binding.py:146–150` 对序列化 context 的字段集合做精确比对。首期不要把 Outcome/DependencyStamp 字段直接塞入 AccessContext 序列化；可保存为关联 envelope。若后续要升级 context schema，必须同时改 verifier、编码/解码、旧 outbox 的兼容规则，否则 durable 发布会因 `LEGACY_CONTEXT_SCHEMA_MISMATCH` 被拒绝。

### 4.4 表达行为的边界

常规问答可先给与当前问题直接相关的结论，再保留必要条件与下一步。缺项明确哪一项缺；局部成功逐项列出已登记与未处理。不得把预计日期改成承诺日期，把内部记录改成已通知，把草稿改成已批准，把已取消任务改成已撤回动作。错误/控制类可以短而自然，但必须保留失败/未知语义。

原预览、接受 hash 对应载荷、引用原文、用户要求逐字保留部分和原业务回执不做自由改写。需要自然化时只生成其外围说明，不得改变其批准绑定。低预算、快路、纯状态、小回执走确定性渲染；仅结构覆盖可靠且有剩余预算的普通问答进入可选模型表达。

Guard 失败、取消、来源撤权、TTL 到期必须继续向上传播并抑制数据输出；不能使用旧 fallback 文本跨过这些检查。只有表达候选本身失败而权威 Outcome 和全部 guard 仍有效时，才允许退回确定性 Response。模型停止未知等 provider 状态仍按原机制记录，renderer 不能清除它。

## 5. 来源依赖版本的渐进设计

### 5.1 不把内容版本、权限版本和配置版本混成一项

拟新增 `DependencyStamp`：resource/source identity、content_version、access_epoch、mapping/parser/schema_version、observed_at、expires_at、permission scope。原全局 source_access_version 作为兼容字段保留；显式紧急撤权仍可使用 tenant/global epoch。

可信依赖登记发生在读取/投影边界。包括本轮 fresh sources、完整被选历史的所有依赖、tool read 实际读到的 sources、知识/内部记录版本、负向查询的覆盖索引或目录版本。模型不得自行缩小 dependency set；只引用一条事实不能证明没有受其他输入影响。特别是“没有待办”“所有项目”这类负向/全集结论，还依赖查询范围与覆盖水位，不能仅登记已返回的行。

### 5.2 实施顺序与具体文件

| 位置 | 需要改变的责任 | 第一阶段兼容原则 |
| --- | --- | --- |
| `am_info_sync/store.py` 的 register_source/mark_source_error/commit_page 及 access_version | 增加每来源权限 revision 和可查询的 stamped read；维护显式全局紧急 epoch | 旧全局 version 继续写，不直接删除原撤权判断 |
| `am_information.py` 的来源汇总/资料附加入口 | 返回每一事实/覆盖集合的 source refs、content/mapping version、绝对 TTL | 未具备完整 provenance 的返回值附 global sentinel |
| `am_conversation/legacy.py` request_context/authorize/delivery_source_authorized | scope/actor/grant 与实际来源依赖分开校验；调用 trusted validator | 新链路和旧链路可双判，先只记录“本可继续”的 shadow 结果 |
| `am_harness/host_context.py` 与 `am_harness_context_sources` | 从现有 ledger dependencies 扩展为版本化全来源集合，历史依赖取并集、期限取最早 | 保留 FIX1 F02 的稳定 ID、sent/ack/verified、绝对期限 |
| `am_harness/host_focus.py` | 将焦点权限指纹与相关项目/来源可见性绑定 | 仍保持事件顺序和任务 fence；不能只删 ctx.source_access_version |
| `am_service.notify`、`am_query.query_delivery_authorized`、`am_harness/legacy_binding.py` | 在入队和发送/回读检查同一持久化依赖 envelope | 不可只修改 model guard，遗漏投递链；旧 outbox 按原规则处理 |
| `am_reply` 合同与 response envelope | source_version 改为 dependencies fingerprint，并保存 schema | 指纹只是压缩标识，验证还必须能读取完整依赖集合 |

第一步只做依赖完整性与影子判定，不改变拒绝结果。第二步在有全链路证据的少量路径启用精确判定；凡未覆盖来源、未知作用域、集合查询覆盖不明、旧数据，保留全局保守失效。撤权/TTL 失败立即抑制，不把新权限快照套给旧正文；内容变化若需要更新，只能重新做无副作用的读取/纯推理，不能借机重放任何已经占用或提交的动作。

### 5.3 实现/构建依赖也需版本化

新增模块优先标准库，继续通过原 ModelCoordinator，不因参考 OpenAI/DeepSeek 就加入外部运行依赖或更换原 Qwen。协议 schema、prompt、renderer、fact mapping、adapter 版本进入 manifest 与 trace；回滚选择旧 renderer 必须兼容旧 envelope。原 pyproject 固定 `lark-oapi==1.7.5`、`pypdf==6.19.0`、`python-docx==1.2.0`，Python 要求 >=3.12，测试 pytest==8.4.2（R2-unchanged pyproject 实读）；这些是声明依赖，不是本轮对生产已安装版本的检测。

## 6. 恢复、副作用与状态展示改造点

建议增 `am_harness/recovery.py` 的只读 catalogue/显式 reconciler 分发，不写一个跨所有状态的 `retry()`。

| 恢复对象 | 可做的事 | 不能自动做的事 | 现有集成点 |
| --- | --- | --- | --- |
| 纯投影/格式化 | 依据当前版本/权限/TTL 命中 cache；安全重新计算 | 恢复过期事实、把旧正文重新授权 | `CheckpointStore`，`host_context:36–51` |
| 派发前本地拒绝 | 依 FIX1 proof 标记失败并释放当前 lane | 仅按字符串或超时猜测模型已停止 | `runtime:23–40,142–148` |
| 模型执行未知 | 观察 provider/进程/lease 停止证据后显式 reconcile | 到点即释放、自动重新推理、清 provider pause | `DurableStore.resolve_quarantine/release_not_dispatched`，原 ModelCoordinator |
| 同库本地工具 | 读原业务对象版本和 reservation receipt | 用回复文字当作成功证据；取消后抹去已提交记录 | `reservation:103–110,167–174` |
| 跨库本地工具 | `reconcile_local_commit` 只验本地 commit receipt；展示 unknown 原因 | 无回执即认定失败；重新调用工具；自动解模型 lane | `reservation:114–152,177–203` |
| 外部动作 | 查原 action/accepted hash/执行 id/独立结果 receipt | 绕过批准、更换 payload、在 unknown 时重放 | `engine._control:234–263`，`HarnessHost.execute_action:379–397` |
| 消息投递 | 对原 message_id 精确回读；修复核对元数据 | unknown 直接重发、把 sent 当业务完成 | `HarnessHost.reconcile_receipt:417–426`，`verified_receipt:453–458` |
| 维护终态 | 继续 F05 的 inbox 收尾/幂等状态通知 | 重跑过期业务、更改原期限 | `HarnessHost.sync_terminal:280–306` |

统一状态视图应返回 `run_state / business_effects[] / delivery_state / reconciliation_required / next_allowed_action`，并链接原记录。它是映射现有权威状态，不是新建一张会覆盖原 action/store/outbox 的“总状态”表。

## 7. 交给 Codex 的实施边界与验收重点

1. 以 FIX1 源码提交为唯一实现基线，保留 R2 off。不要将 R2 审查旧图直接当成当前代码，也不要重新修已确认进入 FIX1 的 F01—F05。
2. 首先实现 Outcome/Response 数据和确定性 renderer；全路径登记覆盖矩阵。原流程可用保护性兼容 adapter，但未结构化不可计为事实覆盖或拟人化成功。
3. 共同 finalization 的测试必须跨真实宿主路径，证明 final text = event saved reply = 复用历史语义文本，且 display/outbox/rendered hash 绑定正确。仅测独立 dataclass 或 renderer 不足。
4. 对 approve/cancel/unknown、部分本地成功、权限变化、消息到期、重复事件、旧 revision late return、跨库 crash、投递成功但 ack 未完成保持原断言。新接口不能削弱 FIX1 的五条及39边界、10组合。
5. 来源精确依赖先 shadow；同时覆盖 query grant、generation、tool read、finalization、enqueue、dispatch、readback 和历史复用，不能只放开一处 global check。
6. 输出质量需分层计数：可结构化、可模型表达、实际尝试、通过校验、宿主采用、成功投递回读、真人盲评胜/平/负。任何 projection、未覆盖、fallback、guard abort 不计模型表达成功。
7. 用户体验验证区分工具选对/对象选对/业务实际状态/最终表达与端到端耗时。主路径降低重复模型调用，先处理语义事实和路由，不能用更华丽的失败说明替代真正业务完成。
8. 首期可随时切回确定性 renderer，不需要回滚业务数据库；未知动作继续按旧 receipt 对账。生产部署、手机和独立真人验收由后续明确执行任务完成，本轮不把设计可行性当通过。

## 8. 源文件索引及引用约定

- FIX1 定向远端读回索引：`design_research/fix1/source_index.json`，包含审核 URL、Git blob SHA、本地 SHA256 和字节一致结果。
- 当前 12 个运行文件：`design_research/fix1/source/`。
- 既有未改代码：`r2_snapshot/source/`，固定审核提交 `e69a76a15dedfd885be0068a378c010195ca0f8f`；变更列表来自当前 `FINAL.diff`。
- 本文行号取最终本地 FIX1 或冻结 R2 实际文本；`engine.py` 默认为 `am-conversation-r1/src/am_conversation/engine.py`；`am_harness_host.py` 默认为 `local-qwen3.8/feishu-bridge/am_harness_host.py`。

固定入口：https://github.com/Catcherog/project-workbench-review/blob/cd35c28d4524284b52e77763784ac4c2d15cd3e4/AM-HARNESS-20261031-01/R1-FIX1/00_%E5%BD%93%E5%89%8D%E4%BA%A4%E6%8E%A5.md
