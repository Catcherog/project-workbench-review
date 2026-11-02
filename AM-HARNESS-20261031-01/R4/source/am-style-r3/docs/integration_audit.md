# R3 真实接入复核与 R4 三项限定补修

## 结论和证据范围

复核确认三项能沿真实宿主接口复现的问题：来源引文限定丢失、最终预览正文与已核验文本分离、完整读取被误算为回答了所问字段。R4 提供两个宿主覆盖文件及定向检查。**原 R3、原服务配置和生产文件未修改；本次没有调用真实模型，也没有实际发送。** 以下通过结果只证明这些离线修补边界，不表示整体启用、通用语义或业务验收通过。

固定审核提交为 `7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757`，对应源码提交 `0ce6dcde237b669efbc263623fe4c95f068bd201`。R3 是相对 R2-FIX2 的增量；未改依赖按同一固定审核提交下的 R2-FIX2 读取。共核对 38 个必要源码、说明及证据文件，下载字节与固定 MANIFEST 一致，清单为 `evidence/integration-audit/readback.json`。没有进行全仓审计，也没有在本环境重跑原工程 798/27 的整套测试。

固定来源：[R3 terminal.py](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/source/am-conversation-r1/src/am_conversation/terminal.py)、[engine.py](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/source/am-conversation-r1/src/am_conversation/engine.py)、[legacy.py](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/source/am-conversation-r1/src/am_conversation/legacy.py)、[gateway.py](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/source/am-conversation-r1/src/am_response/gateway.py)。

## 三项问题及即时修补

| 问题 | 修补前的可复现行为 | R4 的限定处理 |
|---|---|---|
| 引文限定丢失 | `value=完成`、`source.quote=未完成` 被投影为“演示项目目前完成。”，并记录 `semantic_pass=true`、`adopted=true`。预计、仅试制阶段、负责人实体冲突也能通过。 | 非空引文必须与完整 typed value 逐字一致，只忽略首尾空白；不一致或非文本引文拒绝投影，保持原 legacy。不会凭否定词表推断引文含义或反向补造确定事实。 |
| UI 之后丢事实 | 混合查询的准备文本包含负责人事实及批准正文；`text_ui.display` 只保留批准预览。旧 gateway 仍接受已丢事实的 body，并记下转换前的 semantic hash。 | `needs_confirmation`、`knowledge_candidate` 两状态直接标记 unsupported、保持原回复及原 UI、零表达调用。原事务另加最终正文门禁；任何新表达正文变化均不能继续借用原语义哈希。 |
| 回答字段错位 | 问“演示项目谁负责？”，只读到项目进展，也会被标记 `fulfilled`，移除目标未完成说明，并用进展句替换原“没有负责人信息”。 | 闭合句式必须对齐唯一 project_id、所问 predicate、required claim、完整读取及其项目/证据来源。缺字段、跨项目拼凑、同名歧义、读取绑定错误都保留 partial 和 goal-coverage，并退回原回复。 |

第一项修补会保守拒绝“林工”与“负责人为林工”这样的可能等义表达，因为当前接口没有独立证明其等义；不能以扩大自动采用率为由略过这一约束。引文与字段值逐字一致的“未完成”“预计明天完成”仍被完整保留。

第三项仅覆盖原有的“项目名＋谁负责／负责人是谁／进展怎么样／进展如何／有哪些待办”及其原有“现在／目前”变体。只对 owner、progress 和显式列出的待办字段做闭合覆盖证明。未知问法不获得新的完成推断；复合项目不能把多个读取结果拼成一个已证明的单项目义务。这不是通用意图识别或所有业务目标已完成的证明。

读取单元还必须在 `target.project_id` 或 `result.id` 中至少提供一个显式项目身份，所有已提供身份都须一致。原 `read_project` 注册要求 project_id 并校验结果 id；`read_information` 也必填 project_id。因此这一闭合支持范围无需依靠空读取绑定。即使 evidence_bundle 中存在 claim.subject，或 claim ID 正好匹配读取单元前缀，也不能单独取代读取项目身份；此类输入保留 legacy。

## 最终正文门禁与即时回退的区别

原 `display` 有两类整体替换：待确认动作预览、待采用知识预览；通用分支还有一处“带上预览中的动作编号”到“说明预览中的事项序号”的固定替换。R4 不改这些批准与采用界面的内容、版本或操作授权。

`require_terminal_rendered_payload()` 仅约束 `prepared.selected` 为 `canonical` 或 `candidate` 且 `metrics.mode=enforce` 的实际新表达。canonical 也必须检查：已复现的问题在没有表达模型、直接使用 canonical 时同样发生。`selected=legacy` 且 mode 为 shadow/off 时保留原显示路径，不因历史格式变化扩大阻塞。

新表达只支持实际 `kind=text`、`artifact=None`，并同时要求 `body == prepared.text` 和 `fingerprint(body) == semantic_hash`。未知载荷、正文被删改或哈希不一致抛 `TERMINAL_RENDERED_PAYLOAD_MISMATCH`，不重算哈希后冒充语义通过。原 `Store.add_outbox` 先插入 outbox，再在同一事务调用 `GatewayProjection.bind`；异常使 outbox 与投影记录共同回滚。已用原 Store 的真实 SQLite 事务证明该行为。

这项即时修补意味着上述两种预览状态暂不进入新的表达采用范围。**它没有解决原 UI 在混合查询中怎样同时呈现事实与批准正文的问题。** 下一阶段需让最终显示正文承担事实、状态、批准版本和操作控件的统一合同，再验证完整最终消息。未经该合同核验的卡片、附件或重排版式不能沿用当前文本通过记录。

固定来源：[原 text_ui.py](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R2-FIX2/source/am-conversation-r1/src/am_conversation/text_ui.py)、[原 Store.add_outbox/tx](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R2-FIX2/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/store.py)。

## 接口和已经核实的边界

| 接口 | 实际行为与边界 |
|---|---|
| `OutcomeCollector` | 独立 ContextVar。`response=legacy` 的旧 begin 仍返回 None，不因 collector token 开启旧任务模型 response protocol。 |
| 默认 off | 不建立 collector state，不进行目标解析、依赖采集或表达模型调用；仍有对象初始化、钩子调用与 prefetch 列表遍历开销，不能写成“零开销”。 |
| `handle` / `handle_fastpath` | 普通入口中的 fastpath 与独立 fastpath 均把 `fastpath=True` 送入末端，原 13 项接入检查中两条路径均零模型调用。 |
| `TerminalExpression.finish` | 在 `store.finish_event` 前准备一次表达。原 envelope、frame、prepared 与所用文本哈希冻结为 terminal_json。 |
| `coordinator_provider` | 仍使用原 ModelCoordinator，native_chat 的外层单 user JSON 消息，tools 为空；共享 monotonic deadline，协调器从 timeout 扣除排队耗时，未另造完整预算。 |
| 撤销、过期及停止未知 | 生成前后及入队边界保留原权限、revision/cancel_epoch/generation、依赖绑定、TTL 检查。STOP_UNKNOWN 传播，不以旧文案回退冒充正常完成。 |
| `prepare_reply` / `enqueue_reply` | 原 UI 显示后准备；事务前与事务内重复检查 reply 绑定。新 gateway 门禁补上实际 body 与准备文本的一致性。 |
| `GatewayProjection.receipt` | 投影仍不是发送权威；原 outbox 状态、message_id、实际载荷 hash 与有效期决定回执。没有第二个发送器。 |

terminal_json 的当前结构为：

```json
{
  "schema_version": "am-terminal/3",
  "outcome": "完整冻结 Outcome 对象",
  "frame": "SpeechFrame.data 对象",
  "prepared": {
    "text": "准备采用或保留的文本",
    "frame_fingerprint": "sha256",
    "selected": "legacy | canonical | candidate",
    "reason": "原因",
    "candidate": "候选或 null",
    "metrics_json": "含 mode/adopted 等的 JSON 字符串",
    "delivery": "prepared"
  },
  "semantic_hash": "fingerprint(reply.text)",
  "expires_at": "源有效期"
}
```

原始 claims、work_units 和 provenance 保存在 `conversation_events.reply_json` 内，并随同事件重放原样返回；不会再次调用表达模型。`conversation_messages`、`store.history` 和 host_context 实际读取的是最终 reply.text，经回执与版本筛选。它们不会自动将 terminal_json 中的原始事实重新装入下一轮模型历史。新鲜 SourceFact 仍由原 ContextBuilder 独立提供。因此可写“原始事实用于审计与重放保留”，不可写“下一轮模型历史已完整携带全部原始事实”。[原 history adapter](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R2-FIX2/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_harness/history_adapter.py)、[原 host_context](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R2-FIX2/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_harness/host_context.py)。

## 验证结果和复现

本次有 17 项新定向 unittest 通过，其中 11 项检查投影，6 项检查最终正文/预览回退。它们直接编译交付 overlay 中的对应函数或类，使用真实 am_style 和 SQLite，不加载生产服务。最后增加的读取身份反例同时覆盖无 bundle 的前缀路径和有 bundle 的 claim.subject 路径。另在固定 R3 加两文件补丁的隔离宿主树重跑原 13 项终端接入检查，全部通过。

实际原生模块复现另外验证了：4 个引文冲突拒绝、1 个逐字否定事实通过；5 个字段/项目覆盖反例保留 legacy、partial 和 goal-coverage，1 个同项目正确负责人通过；原 Store.add_outbox/tx 的插入回滚、完整文本排队及 shadow 原 UI 豁免。它们使用显式 ScriptedModel / fixture 输出，不计入真实 Qwen 样本或人工训练标签。

所有报告、日志和纯离线脚本在 `evidence/integration-audit/`。先运行独立定向检查：

```sh
python -m unittest discover -s tests -p 'test_terminal_r4_*.py' -v
```

原生复现需要先按固定 R3 的 `scripts/reconstruct.py` 重建隔离源码树；再复制一份隔离树，将本包 `overlay/` 内两个相对路径覆盖到副本。**不要把整个本包覆盖到原工程，也不要在生产树执行这些复现。** 令 `AM_R3_REVIEW_SRC` 为原重建 source 路径，`AM_R4_PATCHED_SRC` 为已覆盖两文件的副本 source 路径：

```sh
PYTHONPATH="$AM_R3_REVIEW_SRC/am-conversation-r1/src" python evidence/integration-audit/reproduce_projection.py --output /tmp/r3-projection-before.json
PYTHONPATH="$AM_R4_PATCHED_SRC/am-conversation-r1/src" python evidence/integration-audit/reproduce_projection.py --output /tmp/r4-projection-after.json
PYTHONPATH="$AM_R4_PATCHED_SRC/am-conversation-r1/src" python evidence/integration-audit/verify_closed_query.py --output /tmp/r4-query-coverage.json --expect-fixed
PYTHONPATH="$AM_R4_PATCHED_SRC/am-conversation-r1/src" python evidence/integration-audit/verify_gateway_overlay.py --original-terminal "$AM_R3_REVIEW_SRC/am-conversation-r1/src/am_conversation/terminal.py" --original-store "$AM_R3_REVIEW_SRC/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/store.py" --output /tmp/r4-gateway-overlay.json
```

两个 overlay 的原始及修补后 SHA256 记录在 `verification-summary.json`，应在原机隔离应用时核对。必要的 before/after JSON、diff 和日志随包提供；未复制原工程、模型权重、真实业务数据或私有盲评 key。

## 仍未完成的范围

当前默认仍是 bounded grammar，未知自由候选不自动变成事实正确的答复；本次没有启用新的自然语言 verifier。可见来源引用尚未接入 `project_outcome` 的 `source_links/sources_requested` 参数，内部 provenance 不等于已满足用户的来源请求。精细依赖仍保留观察性质及原全局守卫，不能据此撤掉原权限与版本防线。

R3 的[真实终端探针](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/evidence/terminal-real-probe.json)证明了一次原 Qwen 表达回调、冻结与重放、发送前复查；任务模型是脚本 fixture。该证据明确 `business_delivery=false`、`actual_platform_outbox_commit=false`。本次补修也没有平台投递、真实业务批准或生产开关变更；保持 `response=legacy`、旧重写 off、`goal_tracking=false`、`terminal_expression=off` 的现有边界。
