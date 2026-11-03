# Codex 原机执行交接

任务：`AM-HARNESS-20261031-01 / R6`，关联通知补修 `AM-FOLLOWUP-20261102-01 / R1-FIX3`。

## 1. 可直接使用的执行指令

> 执行 AM-HARNESS-20261031-01 / R6，合并后训练与通知两条主线。读取本轮固定审核入口的 `00_当前交接.md`、`INPUT_BINDINGS.json`、`PATCH_BINDINGS.json`、`verification/summary.json` 及 `docs/`。源码基线是 R5-FIX1 `63d8afdcac2ca440846cb22237fc5b097a074941`，其中已保留通知 R1-FIX2 `295873a26842d696d96037af0f5a17ec913f4401`；以原机最新工作树为准，保留后续有效修改及其他任务目录。
>
> 检查并接入 `changes.patch` 和 `files/`，不要整树覆盖。完成原机相关回归和实际加载证明，落实跟进主路径纯文字及准确引用／确认码批准。复用当前24/8 gold和三轮反馈，不重复要求用户评价已经认可的内容；独立工程师业务验收继续按用户原决定暂缓。
>
> 优先确认原Qwen3.8的真实管理器、模型/digest、worker PID和占用，在可恢复的原运行窗口中临时卸载该模型，实际测量可用内存／压力／swap，再恢复同模型及配置。先停止领取新模型任务，排空已有业务后才暂停推理；保留所有pending，新业务由原R4让路。兼容metadata服务必须保持可读。此诊断可在独立测试不足时先做，trainer启动次数必须为0。
>
> 在已有读取授权范围继续检查独立测试候选来源，冻结材料、声明、原件和计划绑定；不伪造人工声明，不把既有gold、三轮反馈、公开回归或合成数据当独立测试。缺材料或资源条件时保留具体阻塞，继续其他已授权工作。
>
> 训练只有在全部原R5真实前置条件满足后才执行。窗口开始前和启动前都调用原R5fresh gate，最终重新进入原`pilot-execute`，不能缓存R4 argv；原R4在自己的原协调锁内执行资源检查。保持原训练参数、24 GiB启动／5 GiB运行／swap增长1 GiB策略，原Q8、唯一消费者、600秒身份及既定关闭项不变。确认全部fit/reload工作者停止后恢复Q8；未知停止或恢复失败必须保留维护状态和具体恢复项。
>
> 真实pilot完成后，按已有授权进行原Q8与候选的对照及后续验证。分别回传训练、效果人评、宿主接入、业务验收；没有完成的明确写未完成。提交实际源码、最终差异、相关验证、运行配置及加载指纹、具体未完成项到本轮任务目录；保留其他任务目录。固定源码和审核提交，独立远端逐文件回读后给审核入口。

## 2. 先核对当前树，再接入

保存原机 `git status`、当前HEAD、分支、已跟踪差异和未跟踪清单。禁止清理用户的既有文件。对有并行修改的路径逐项合并，不要求退回固定旧提交。

本包运行时和测试按原仓相对路径提供；`am-integrated-r6/`是新增控制／测试包。先执行只读清单检查：

```bash
python3 /absolute/package/files/am-integrated-r6/tools/inspect_patch.py --repo /absolute/current/repo --manifest /absolute/package/PATCH_BINDINGS.json
git -C /absolute/current/repo apply --check /absolute/package/changes.patch
```

检查结果为`before_matches`或`new_path_available`才可按补丁应用；`already_applied`不重复写；`current_differs`逐项保留当前有效修改后合并。不要用删除目录或强制reset解决冲突。合并后的after哈希若因合理后续代码而不同，应给出解释与实际源码，不伪报精确匹配。

`am_service.py`、`am_query.py`、`am_harness_host.py`、两个Store及资源模块是相互配套的维护改动，不能只装provider_pause。文字UI及表达新增文件也须同时部署；默认off仍会加载相关模块并建输出元数据表。

原机有稳定依赖就复用，安装或改版本需遵循原环境约束。本轮云端用pytest8.4.2和lark-oapi1.7.5，未变更用户生产依赖。运行：

```bash
python3 /absolute/current/repo/am-integrated-r6/tools/run_validation.py --repo /absolute/current/repo --output /absolute/private/r6/offline-validation --with-r5
```

该脚本只运行合同／临时数据库验证，不读取生产数据库，不启动真实模型、trainer或发送真实消息。原机仍需按以下矩阵做真实连接验证，不能用这些离线结果替代。

## 3. 原机验证矩阵

| ID | 验证内容 | 必须记录 |
| --- | --- | --- |
| B01 | 本轮源码与当前树合并；保留原后续修改 | HEAD、差异、before/after及冲突说明 |
| B02 | 相关用例与原机基线比较 | 失败ID、断言消息、新增／既有区别；旧27失败不得直接套用 |
| B03 | 原服务实际加载本轮文件 | loaded-source哈希、唯一消费者、原实例锁、配置指纹 |
| U01 | 手机“我的跟进”列表及详情、分区、分页 | 实际消息type=text，文字完整，不生成新小卡片 |
| U02 | 完整预览和正文修改 | 实际目标与正文逐字回读；修改后旧预览失效 |
| U03 | 引用预览“确认发送”及带码确认 | 同一应用／租户／本人／会话，真实parent和新thread关联 |
| U04 | 重复批准、旧预览、错误引用、跨会话、过期 | 拒绝原因、同一request UUID仅一条发送 |
| U05 | 取消／修改与发送边界竞态 | 不误取消其他任务，不重发unknown，不伪称撤回 |
| U06 | 来源或权限在准备／批准／发送前变化 | 旧快照拒绝；没有把旧正文重新标成新epoch |
| U07 | 反馈原话、准确“收到”、自报进展 | 精确关联原发送；事项未凭自报自动关闭 |
| U08 | 原文到期与超24小时相关保留策略 | 内容清理而幂等身份保留；不能用虚拟时钟代替真实等待结论 |
| E01 | 新“跟进状态”默认off；shadow／enforce隔离检查 | off保持原详情；事实快路径模型0；生产仍off |
| E02 | 已发、unknown、有／无准确回读任务 | 只有真实任务才承诺核实；回执不能借用其他发送 |
| E03 | 入队后来源、反馈、负责人、取消、权限变化 | 原gateway最后一跳拒绝旧文字；表达metrics与平台回执分开 |
| S01 | SEM-01原V02重放及反例 | 缺证据与明确未执行区分；否定／转述／条件保护保留 |
| S02 | 原20次真实观察的剩余缺口 | 保留原输入和既有结果；新增运行单列，不用门禁拦截算准确 |
| R01 | Q8进程／模型／管理器／监听映射 | 精确身份、RSS及其他主要占用；不导出敏感参数 |
| R02 | 两阶段owner→drain→pause | 已有多步任务正常完成，新任务received/queued，attempts不变 |
| R03 | 所有队列和推理路径覆盖 | 特别是普通私聊另库queued/processing；原R4pending可见 |
| R04 | 临时Q8释放／metadata保持／实际量测 | before、after-unload、available/pressure/swap、耗时，trainer0 |
| R05 | 新业务／取消／回读在窗口中到达 | 原业务可见，按原R4让路，不能漏队列或自动唤醒模型 |
| R06 | 同模型恢复及故障恢复 | 同digest／配置、消费者、队列；partial unload和stop_unknown边界 |
| H01 | 既有24/8gold和三轮反馈复用 | 内容摘要不变；不重新要求已认可内容评分 |
| H02 | 缺材料仍可prepare/preflight | 准备成功与execution blocked分别记录 |
| H03 | pilot-command／pilot-execute缺材料 | 具体原因、trainer启动尝试0 |
| H04 | 材料／声明／原件／计划改变 | 旧通过状态失效，实际执行再验证 |
| H05 | 合格独立来源 | 权限、原件、冻结、case-bound声明、暴露状态；不公开原文 |
| T01 | 满足真实前置后原pilot | 原R4参数／原锁／24GiB策略、fit/reload与进程组停止 |
| T02 | 原Q8／候选对照与新增人评 | 同冻结输入、盲化映射、真实生成与新评价，旧认可沿用 |
| T03 | 宿主接入与生产配置 | 影子及回退验证，生产表达off保持到独立接入条件成立 |
| A01 | 独立工程师业务验收 | 当前按用户决定暂缓；恢复验收后另记真实证据 |

对真实外发沿用既有明确授权的目标、完整预览与批准。没有具体批准的同事消息先准备，不自行发送。测试本人既有批准内容无需重新评价，但新正文／目标仍遵循完整预览绑定。

## 4. 原机必须接上的端口

`ExistingCoordinatorHost`复用原ModelCoordinator和Store，控制算法及CAS实现已提供。公开审核源码缺真实llama.cpp proxy/manager端，因此Codex需在原机实现薄适配并附源码：

- `read_observation()`返回`HostObservation`：原服务实例、配置hash、模型identity/runner、消费者数、入站/metadata活性、全部pending/active。不能只统计一个SQLite。`fence_owner`由`ExistingCoordinatorHost`再从真实Store读取并覆盖，不能用观察端自报绕过围栏。
- `ExactProviderLifecycle.suspend(binding)`和`restore(binding)`：经实际管理器验证的精确操作；保持metadata，不使用模糊杀进程命令；幂等且具备独立验证。
- `fresh_r5_gate`直接复用`OriginalR5InputGate(原绝对plan路径)`，调用实际R5检查并保留具体原因，不另写一套门禁。
- `execute_original_r5()`：调用实际原CLI入口，返回`ExecutionObservation(status, stop_confirmed, evidence_sha256)`。该对象必须由真实原R4 result／phase及停止证据摘要生成，不能直接返回CLI整数returncode，也不能为了符合接口伪造receipt。禁止缓存R4 argv。
- `trainer_stopped()`：独立核实原fit/reload工作者及进程组停止，与上述`stop_confirmed`交叉检查；不是看一个PID或单纯returncode。

如果原机已有等效控制口，应复用而非再造服务。若缺接口或无法确认恢复，记录精确阻塞并继续其他准备；不能把合成端口连接生产，也不能为省事降低门禁。

## 5. 四类验收结果分开回传

1. **训练执行**：真实是否启动、fit/reload分别完成与否、产物hash、资源／中断／停止／恢复证据。
2. **效果人评**：实际候选、固定对照、事实错误、新评价、旧三轮反馈复用情况；未有人评则明确未做。
3. **宿主接入**：实际加载文件、原消费者／模型／配置、文字交互、来源和最终出口保护、shadow／回退实测。
4. **业务验收**：独立工程师真实业务闭环；当前仍按用户原决定暂缓，不由以上三项替代。

`00_当前交接.md`应把通过、失败、未完成和用户暂缓分别列明。资源不足具体到指标与时间；材料不足具体到来源／声明／原件／冻结绑定缺什么；不能只写“条件不满足”。

## 6. 回传与审核

本轮开发按新R6目录组织，旧R5-FIX1及通知历史目录保留。本轮GitHub发布API返回403，尚无新远端固定提交；Codex可先按 [发布与回读](05_发布与远端回读.md) 用原机已授权Git凭据原样发布。实测回传在R6之下新建 `native-validation/` 或约定子轮，不覆盖本轮开发基线及证据。

包含实际源码与差异、SOURCE_SHA256、原机验证、最小脱敏运行证据、加载指纹、未完成项及回退说明。私有业务原文、真实会话ID、密钥、运行数据库与人工声明原件保留原机，仅回传必要摘要和绑定证据。固定源码提交与审核提交后，对远端所有本轮文件重新下载核hash，提供固定审核URL；核对其他任务树未变。
