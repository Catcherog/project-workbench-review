# 最后发送门禁：本机精确依赖的一致性

## 修复目标

本轮修复审核中的 F01：远端来源核验已经通过，但随后较慢的目录核验期间，
本机已经提交来源版本、披露范围或披露批准变化，原发送边界仍可能继续发送。
本轮仍使用原 `Scheduler`、`BusinessPort`、SDK 和一次性 `before_send`；不创建新消费者。

## 两类核验各自承担的工作

1. **实时核验**：原来源精确重读、目录/群成员/机器人会话核验。
   它们可能等待网络，全部在数据库发送事务外完成。
2. **最终本机核验**：在取得一致的本机状态之后，只用数据库读取重新核对已批准的
   精确依赖。它与 `followup_intents` 的 `claimed → sending` 提交受同一组锁保护。

最终本机核验包含：

- 绑定存在、唯一、未失效，native target 与实时核验对象一致；
- 事项仍有效、正文/规范任务 ID/引用集合及事项语义版本与批准一致；
- 原 `FactEngine` 对同一事务内的事实仍可见，原始证据未过期，引用值和来源版本一致；
- 关联源对象仍为有效当前版本，源权限、群披露范围、私聊披露策略未改变；
- 同一 AM 事务内的披露行仍为 `current`，其 revision 与已批准依赖指纹一致；
- 关联对象的覆盖缺口、待处理变更仍满足原规则；
- 原计划、occurrence、approval、暂停状态及发送时间窗仍满足原门禁。

继续按精确来源和对象比较；无关项目新增来源不会使该事项批准失效。

## 固定锁序及线性化位置

涉及两个存储的跟进读取统一使用以下顺序：

1. 原 AM Store 的进程内互斥锁；
2. Information Store 的 `BEGIN IMMEDIATE`；
3. 原 AM coordinator 的 `BEGIN IMMEDIATE`。

Information 数据库使用 WAL。单纯读快照不能阻止另一个连接在检查之后提交权限撤销，
因此最终核验短暂取得 SQLite 写预留，但本身不写 Information 内容。
原 AM 事务负责冻结披露、绑定、计划、批准及 intent 等本机状态。

`FollowupCoordinator.final_native_guard` 是可选的向后兼容接口：
host 进入该上下文，获取前两层保护，并交给 coordinator 一个只做本地读取的检查函数；
coordinator 获取第三层保护，执行该函数和原 `final_native_check`，然后提交 `sending`。
顺序为 AM 事务提交、Information 事务结束、进程内锁释放，最后才进入 SDK create。

`sending` 的成功提交是本机发送控制的线性化位置：

- 关联变化先完成提交：最终核验会看到变化，旧批准被阻止，SDK 调用为 0。
- 最终门禁先取得保护：另一个写连接必须等到 `sending` 提交后才能完成其变化。
  此时已越过本机控制边界，不能再承诺“未发送”或把这次发送的记录删除。
- 在 SDK 请求中或之后收到的新事件继续按原实际回执、unknown 与对账规则处理。

最终准入范围内的普通读取异常（包括原适配器的 `LedgerError` 和超时）会转为
`DispatchBlocked`，再由原 `_finish_blocked` 用新事务读取 durable boundary。
若本机记录证明 `sending` 尚未提交，则记为 blocked，释放屏障，允许用户重新预览批准；
若 `sending` 已经提交，或无法可靠读取提交结果，仍保留未知状态或恢复证据。
这个异常范围在 SDK 调用前结束，不会把请求期间的异常当成“确定未发送”。
`KeyboardInterrupt` 等进程级 `BaseException` 不被转写，继续交给原崩溃恢复路径。

两个数据库不需要分布式提交：最终门禁只读取 Information，唯一业务状态提交在原 AM 库。
若 AM 提交后进程退出，已有原发送状态恢复规则仍适用；本轮不改变恢复实现。

## 避免重复过滤与事务内网络

`FactEngine.query(..., connection=...)` 复用原事实过滤语义，避免另写一套来源授权、
过期、结构化映射和人工更正判定。没有传 connection 的调用保留原行为。
`Store.read_in_transaction()` 仅接受本 Store 的活动连接，不开启或结束调用者事务，
并通过原 Store 互斥锁阻止其他线程借用别人的活动事务。

`FollowupSources.snapshot_locked()` 只做本地读取，使用同一 Information 连接及
最终 AM 连接。私聊的源群成员查询提前在事务外完成，并把已读取成员集合交给本地核验；
这个查询期间发生的本机来源/策略变化仍会被后面的本地核验捕捉。
常规 `snapshot()` 同样遵守 AM → Information 锁序，不再在 Information 事务内访问目录。

## 验证

本轮在隔离的脱敏重建源码中验证，平台为模拟；没有真实飞书或模型调用。

- 原 `test_followup_native.py`：45 项通过。
- 新 `test_followup_final_dependencies.py`：15 项通过。
- 受影响信息源回归 `test_info_cloud.py`、`test_info_sources.py`、
  `test_info_url_metadata.py`：26 项通过。
- `git diff --check` 通过。

新增验证不是只调整三个断言：包括原来源/ACL/披露反例、binding 失效、
无关来源保持发送、真实第二 Information 连接在门禁前提交撤销，
以及 Information/AM 两种真实线程写者在最后核验之后尝试提交。
后两项证明写者提交后读取到的 intent 已是 `sending, crossed_send_boundary=1`。
模拟 SDK 入口还以两个独立 SQLite 连接成功获取并释放写事务，证明数据库保护没有跨越网络调用。
另有 5 项覆盖最终目录的 `TimeoutError` / `LedgerError`、纯本地检查回滚、
AM 发送边界提交后外层 guard 退出失败及进程级中断，保留对应的实际确定性边界。

## 真实边界

这保证的是本机已经观察或提交的精确依赖一致性。它无法令远端飞书状态变化和
本机 SQLite/HTTP 请求形成一个原子事务；实时重读之后仍可能发生尚未同步的远端变化。
真正越过本机发送边界后的撤销、网络超时、进程退出仍须按实际回执和原 unknown
处理规则报告，不能声称已撤回消息。

真实目录返回格式、锁等待和端到端延迟仍需 Codex 在原环境验证；
本轮的模拟平台检查不替代工程师收件、手机操作或业务准确性验收。
