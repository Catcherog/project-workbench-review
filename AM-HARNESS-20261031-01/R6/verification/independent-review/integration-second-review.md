# 第二轮独立代码审查：资源维护窗口与跟进表达接入

## 结论与范围

**代码审查通过，交付给 Codex 做原机接入与实测；不构成真实训练、模型效果、平台送达或业务完成验收。**

本轮独立审查覆盖资源维护窗口状态机、原协调锁适配、原 R5 输入门禁适配、原宿主任务 claim 屏障、跟进事实投影、原 outbox 发送前复核，以及“跟进状态”实际文字入口。没有修改受审实现文件。下表 SHA256 固定本次实际读取的代码版本；后续文件变化须重新核对差异，不能自动沿用本结论。

已完成的初始 R5-FIX1 审核另见 `review.md`、`summary.json` 和 `tests.log`：固定审核提交 `78407b22c18dbb17c0bd79f1c8486d896bf5ebe2` 下 175 份下载文本文件 Git blob 一致；四文件补丁符合输入绑定；134 项 R5 测试实际通过。主代理另已读取本轮原始 ZIP 并验算所给 SHA256，故初审期间“尚未取得附件字节”的限制已由主代理补齐。本次没有重复执行这 134 项测试。

## 审查发现及闭环

| 发现 | 已接入修复 | 本次确认方式 |
|---|---|---|
| 模型恢复及解除维护围栏成功后，进程在写最终日志前退出，旧恢复逻辑不能接受“模型已恢复、围栏已解除”的状态。 | 恢复路径接受已经验证恢复且无围栏的只读核验；若曾调用 trainer，仍须独立证明 worker 已停止。不会重启训练。 | 阅读状态机及恢复测试，并曾用 open_admission 完成后抛异常的注入情景确认下一次 recover 能完成。 |
| 卸载之后日志写入失败可阻断后续恢复；磁盘满不能成为不尝试恢复 Q8 的理由。 | `_cleanup_record` 将日志异常与恢复动作分开，保留内存内错误及持久化未确认状态；不会把日志失败报告为成功完成。 | 阅读错误路径及磁盘写入失败测试。 |
| 单独设置 provider_pause 会让宿主继续 claim 新任务，真实 TaskRuntime 遇 MODEL_PAUSED 将 run 置 unknown、lane 置 quarantined，反而使原 R4 pending 检查漏掉这类任务。 | 原 Harness DurableStore、原 tasks Store 在同一 SQLite claim 事务检查维护 owner；原 AM 入口暂停新模型任务 claim；已 claim 但尚未执行的 conversation 可退回 received。元数据 admission、控制与只读查看继续。 | 在未改动的真实 TaskRuntime + DurableStore 上，合成 runner 仅抛实际 BoundaryError('MODEL_PAUSED')，实际复现 `status=unknown`、`lane=quarantined`；随后审查新事务门禁。 |
| 若先 provider_pause 后 drain，已经运行的多轮任务也可能在下一次模型调用被打断；模型调用锁暂时空闲不等于整个业务 turn 已完成。 | 两阶段维护屏障：先仅写 owner 阻止新 claim；保留既有任务的模型调用；完整 pending/active 检查通过后，才 seal provider_pause。忙时保留阻塞并恢复 admission；未发生任何停载时，仅核对原模型并释放本窗口 owner，不夺取在跑业务持有的模型锁。 | 阅读 `StoreMaintenanceFence.claim/seal/release`、`ExistingCoordinatorHost.drain` 以及原宿主 claim 修改。 |
| 原 R5 门禁抛出的具体缺材料、声明或绑定变化原因可能被外层统一改写为 native_operation_failed。 | `OriginalR5InputGate` 保留真实 R5Error 原因并包装为 WindowError；GateObservation 的 blockers 也保留在失败记录中。 | 阅读最新适配器及 `_check_gate`。 |
| 跟进表达在 enqueue 后可能已过时，且 owner 权限撤回时异常曾可能漏出原 gateway。 | 同原 outbox 事务保存 snapshot/text/frame 绑定；原 `AMService.valid_notification` 调用 fresh 复核；state/source/feedback/text 变化拒绝。BoundaryError、FollowupError 和 stale/contract 错误均转换为拒绝发送。 | 对照真实 Store 的 raw text body 格式、原 gateway 的发送前 guard 和最新 bridge。 |
| 模型表达尝试及采用信息原先未与新输出持久绑定，原通用 projection 会把未知 kind 记作受保护旧输出。 | 单独保存 metrics_json、frame_hash 与 outbox 关联；delivery_state 从 queued 到 native_sent 仅由原真实 delivery callback 更新，明确 native_sent 不是独立平台回读证明。 | 阅读绑定表、enqueue、delivered、原 AMService callback 及相应测试。 |
| 只有表达对象初始化，未有业务入口调用 prepare/enqueue，不能称原宿主调用链已经接通。 | 实际“跟进状态”文字入口调用 `FollowupTextUI.status`；默认 off 返回原完整详情；显式启用时在读事务外 fastpath prepare，再 fresh enqueue 到原 outbox。 | 对照真实 ingress 路由、handle/status、snapshot baseline 生成及新增 4 个入口情景测试。测试由主代理统一执行，未重复计数。 |

最终增量亦已定点复核：`am_information.interactive_busy` 与群查询 busy 识别维护 owner；am_query 复用原 AMService.training_requires_model，避免重复分类。资源代理提供的最终验证文件记录 34 项单元合同及 7 个真实原类／临时 SQLite 情景通过；本审查读取其结果文件，不将它们重复计作审查人另一次执行。

## 最终通过的具体合同

### 资源维护窗口

- diagnostic 方法没有 trainer 参数或 trainer 调用入口，因此缺独立测试材料不阻塞已获授权的资源诊断；training 方法仍先运行 fresh R5 输入门禁。
- 卸载前取得原 `model-coordinator.lock`；维护阶段释放该锁后，才进入原 R5 pilot-execute。没有持同一个外层锁再等待 R4 worker 的自锁死锁。
- 维护前及卸载后重新检查输入绑定；实际执行回调必须进入原 R5 pilot-execute，不得缓存或直接复用先前返回的 R4 argv。
- 原 R4 仍独占训练准入判断：同一原协调锁内执行原 24 GiB、内存压力、swap 增长及 pending business 检查。本模块的页统计和 RSS 不构成训练放行。
- 发生 partial unload、训练失败或执行结果异常时，恢复路径按持久日志处理。trainer stop_unknown 时不重载 Q8、不解除围栏；外部 STOP_UNKNOWN 或其他 pause 原因不由维护窗口清除。
- 恢复只能匹配原 service/config/model/digest，保持唯一 consumer 及元数据入口，不能换模型或用新消费者完成恢复。
- 维护 owner 建立后，新业务保持 received/queued 并继续对原 R4 可见。legacy chat 使用另一个数据库，因此真实 read_observation 必须覆盖该库 queued/processing 全阶段；这一端口的真实覆盖仍待原机验收。

### 跟进事实与表达

- delivery、反馈、业务完成为三个独立事实。verified 需复用原完整 receipt/payload/target 核验；自报进展和收到回复不变成业务验收完成。
- “我确定一下／已安排核对”只在原 scheduler 的 durable readback 条件成立、确切 message_id 存在、尝试未耗尽、且仍是原 scheduler/consumer 时可用。此用语表达已排队核对，不承诺核对成功。
- frame 绑定 owner/requester、source revision、item/semantic/cancel version、具体 occurrence/intent/request/message/body/target。发送前重新捕获完整事实并比较指纹。
- 原 exact preview、确认命令和通知正文不经过表达器重写。“跟进状态”是独立只读入口，默认 off；开启入口 fastpath 仍不调用模型，因此维护窗口内可查看事实。
- legacy_text=None 时，基准文字来自同一冻结 snapshot，避免从另一时刻的原详情拼接旧事实。StaleFrame 不落入 ContractError 的旧详情 fallback；后续变化触发静态失败反馈。
- 原平台发送通道、outbox 幂等键、owner 范围与权限检查复用，不新增 sender、scheduler 或消费者。

## 证据限制与 Codex 原机工作

本次云端审查未连接用户 Mac，未执行卸载或终止进程、未启动 trainer、未调用实际平台发送。临时数据库、临时文件锁和合成 provider 的验证只能证明代码合同。

以下仍需分别完成并记录，不能互相代替：

1. 实际 `read_observation`：唯一 consumer、真实 queue/pending、运行中任务、原 model/digest、配置哈希和 metadata 存活；覆盖 legacy chat 与所有真实模型调用路径。
2. 原 llama.cpp manager 的 exact suspend/restore 生命周期端口；暂停后 API 元数据保持可读，恢复后原 Q8 身份与配置一致。不能按进程名盲杀或假定一个 PID 就是完整模型生命周期。
3. 同一宿主/启动周期的 before、after unload、after restore 观测；比较实际可用内存、压力及 swap，不把进程 RSS 加到可用内存。旧记录只能支持“Q8 是主要候选占用”，不能证明现在退出它就一定达到 24 GiB。
4. 独立测试仍须符合原 R5 材料、声明、原件、分组独立性及训练前冻结要求。不能把新合成测试当作独立 gold，也不能重新要求用户评价已认可的 24/8 gold 和三轮反馈。
5. 原 R5/R4 受控 pilot 的真实执行与 worker 停止证据、模型效果 shadow 对照、人评、生产宿主表达接入、业务验收分别报告。此次入口接线完成不代表生产表达已开启或效果已通过。

## 所审文件 SHA256

审查快照时间：**2026-11-03T00:55:09.073414+00:00**。

| 文件（工作区相对路径） | SHA256 |
|---|---|
| `development/resource_window/am_training_window/window.py` | `f57de3b1a11dddc7ef247c9598643f4d804ada5be6170945e6c8a0731231298b` |
| `development/resource_window/am_training_window/host.py` | `ef61eb79a44bf81c2e64e8146c19f4cdd4fa4e7bc27940f119169e4efe7b420a` |
| `development/resource_window/am_training_window/original_r4.py` | `fcc799f62d9c9b05a8b088b412835b6f12b2dd04db2bcdf353522ecd25892157` |
| `development/resource_window/am_training_window/r5_gate.py` | `4793e7a83267b31d558bf8f8f2b7312e00529290cd938bc1cc82305590ae75c2` |
| `development/resource_window/am_training_window/mac_probe.py` | `3f1bcc13a578b0cc8e4e4185572e7579c2235d0110509b20a19db1d03a3c081b` |
| `development/resource_window/host_overlay/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_harness/store.py` | `24083eb8faa8c3a093d3119b5daffb9446ac0579d42ab5af9163ba166103c912` |
| `development/resource_window/host_overlay/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/store.py` | `738ded41c12c7a56782edc4129de4defa068bf725613b5e49ca4972302829fde` |
| `development/resource_window/host_overlay/local-qwen3.8/feishu-bridge/am_harness_host.py` | `2c662982cd6f01b32bd70d3b3c9575654aac0de2b60e12a9d6b81fb9ba120d73` |
| `development/resource_window/host_overlay/local-qwen3.8/feishu-bridge/am_query.py` | `df5c41df91168f7ea7034fb1eb124554270435ab7d77670388f50a6504a50216` |
| `development/resource_window/host_overlay/local-qwen3.8/feishu-bridge/bridge.py` | `0aece849d453f2bf50f6ccac6520e79aef9fe2ba39790ac41de238de4fe205c4` |
| `development/resource_window/host_overlay/local-qwen3.8/feishu-bridge/am_information.py` | `b131fd34b8f6113d0adfd85c4aea634b9da1f80736fb6787b5ad2e3ef911e077` |
| `development/followup/source/local-qwen3.8/feishu-bridge/am_service.py` | `41aeed49b6851b98d5b4e4abd36558ea0d8f0255a6038aeda0021132d906469d` |
| `development/followup/source/local-qwen3.8/feishu-bridge/am_followup_host.py` | `b6d660c2e8f3b5f75879c92cb549c09e72e6b7dd54883200330cc67bdab94485` |
| `development/followup/source/local-qwen3.8/feishu-bridge/am_followup_text.py` | `860a521c96da2fc917552d4a3e946459c05aecf0844db926f6cc0f82a8b79d0e` |
| `development/integration/source/am-conversation-r1/src/am_style/followup.py` | `cfbf7f6e24d4a92cf362fada4fe4ec09168e2aa6c3b9ef7ce55f24271531fa6b` |
| `development/integration/source/local-qwen3.8/feishu-bridge/am_followup_expression.py` | `b85bc1725b766a4704da4035155e6c24f6b43647bfa01909edb0f74c9b96e6d2` |
| `development/integration/tests/test_followup_speech.py` | `602e85a9d95d4cda145cbe9313c8d5c24c295a7963faf7344b7d5da81e16753a` |
| `development/integration/tests/test_followup_expression_native.py` | `54c621cc9ec39122f82afdb2214a68c009a94721814ef24ddc12e0ae2b91ecb7` |
| `development/resource_window/tests/test_window.py` | `3373bdd4c49eb13a734e5093498b30e1f71207ec12023a062fb10f4a549bbba5` |
| `development/resource_window/tests/test_host.py` | `cc10897a7f171706ee0861f7dbc6bdfb33680c387c64376c1b6b73d4e6fce7c8` |

这些哈希固定代码审查对象，不是原机部署、平台回读或训练结果证明。
