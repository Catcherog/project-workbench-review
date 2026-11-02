# R4 表达、发送与训练架构

## 目标

拟人化优先解决“答得对、答到所问、状态清楚、追问自然”。自然词语只是最后一层。事实不完整时保留未知；没有真实执行回执时不说“已完成”；问题缺的是开始时间就问开始时间，不要求用户重复已知信息。

表达层继续不拥有业务工具。它接收一次冻结 outcome 的表达任务，返回 `{"text":"..."}`。运行身份、权限、批准、任务期限、重试与取消仍由原宿主决定。

## 一、合同分层

| 层 | 输入/输出 | 核心责任 |
| --- | --- | --- |
| 原 ConversationAgent | 用户问题、工具回读、动作回执 → FrozenOutcome | 记录真实执行与资料覆盖 |
| closed_query_support | 闭合单字段问题 + claims/read → 字段覆盖结论 | 项目、字段、required claim、来源 read 一致；不把“读过”当“答过” |
| project_outcome | 原 outcome → SpeechFrame | 保护来源限定、主体、状态、预览和义务集合 |
| prompt/transport | logical task → 实际 provider wire | 分清 producer/judge/student，绑定每层 hash |
| TerminalPresenter | 冻结 frame → canonical/candidate | 超时与 stop-unknown 使用原协调器状态；无新业务执行 |
| Bounded + 可选 Natural | 全文 + frame → pass/reject/indeterminate | 完整义务覆盖；unknown 不可自动采用 |
| 原 UI/outbox | 准备答复 → 最终正文 | 在事务内核对真实 kind/body/artifact，禁止验证后悄悄丢事实 |
| 原投递/回读 | 已入队消息 → 平台结果 | 原幂等、过期、取消、身份、权限与送达证据继续有效 |

`needs_confirmation` 与 `knowledge_candidate` 当前直接保留原路径，0 次表达模型调用。后续若要支持自然引导句，应把最终 UI 正文也变成冻结合同的一部分，再证明 preview bytes 与事实部分都保留；不能仅刷新旧 hash 来适配被截短的文本。

## 二、有限自然表达的实现

默认仍为 `BoundedVerifier`。离线或 shadow 实验可显式组合：

```python
from am_style.natural import NaturalSurfaceVerifier
from am_style.verify import CompositeVerifier

verifier = CompositeVerifier(NaturalSurfaceVerifier())
```

`natural-typed-surfaces/4.0.1` 从可信 typed facts/effects 枚举少量等价表达。新增前先用原 fact_unit/effect_unit 重建并比对 authority、covers、原 variants。发送成功需要原回执；预计日期保留“预计”；未确认负责人保留未确认；取消后续不变成删除历史。

允许完整语义单元之间使用逗号、分号或“另外、此外”等相加连接。不会因出现“因为、所以”而自行推导因果；不会给 bare owner 加“现在”；不会删除词语再比较；不会用无主语的句子覆盖不同项目。

`with_natural_surfaces(frame)` 用于新的 prompt-only 实验：返回新冻结 frame，记录 parent_frame_sha256，保留 exact_preview 与原 frame。新 frame、prompt、候选必须重新绑定；旧 gold 与旧记录不迁移标签。现有 26 条只作为开发回放。

## 三、输出原则草案与示例

以下是工程默认草案，不是新增用户认可。

| 情境 | 表达要求 | 待审示例 |
| --- | --- | --- |
| 单一事实查询 | 首句直接回答所问字段，其他信息仅在相关时补充 | “演示项目由林工负责。测试方案已整理好，测试还没开始。” |
| 一件已成功、一件未知 | 分别陈述，不能总括“已处理” | “第一条跟进已建立。第二条提交超时，结果还没确认，需要先核对。” |
| 草稿/批准 | 明确未执行，保留实际确认文本 | “消息已准备好，尚未发送。请确认下面的内容。” |
| 提醒缺时间 | 不把保存事项说成已安排提醒 | “事项已记下。你希望什么时候提醒？” |
| 缺开始时间和时长 | 一次合并问两个缺口 | “测试准备什么时候开始，预计需要多久？” |
| 实际重试已排队 | 只有真实队列回执才说已排队 | “刚才查询超时，还没取得结果。重试任务已排入队列。” |

避免每次固定“收到/好的/已为您”、堆内部字段名、机械地复述全量资料或以结束套话延长答复。称呼、主动建议、情绪温度等偏好由少量真实人工校准决定；不会从两条已认可样本推断所有偏好。

## 四、实际模型输入和数据衔接

一个任务保留四个相互关联但不同的身份：

1. `logical_messages`：原表达合同的 system/user。
2. `producer_binding`：Qwen native envelope 或 Codex stdin 等实际生产输入。
3. `judge_binding`：每位评审模型的实际输入，不能替代学生 prompt。
4. `target_binding`：学生 Qwen 真正训练/推理的 chat messages。

native profile 把 logical messages 封装一次。provider 继续接收 logical input，不能把 wire 再交给会自行封装的 provider。Codex stdin 只覆盖传入文字，不覆盖保留的系统与 AGENTS 上下文，因此 Qwen/Codex 比较是 provider+harness 的联合效果，不是纯模型因果比较。

gold：逐条绝对可用标注。silver：明确机器筛选的弱监督 SFT 实验，需要冻结 policy/anchor、宿主语义通过和两份真实独立评审。style DPO：相同 student prompt、两条事实合格答复、chosen 绝对可用和真实相对偏好。unknown、两个都差、缺失候选均不能直接做 rejected。

## 五、延迟与可观测性

`LatencyTrace` 用同一 monotonic clock 记录 enqueued/claimed、load、inference、verify、render、outbox 等有真实事件的位置。未知阶段为 null，不把端到端时间拆成猜测。不同进程/机器的时钟不可直接相减；使用明确 clock_id。批次结果保留 attempted、blocked、missing、stop_unknown 和最长项。

本包只实现可观测模块和旧记录回放，尚未把事件钩子全部插入原机 coordinator。Codex 接入时应在真实事件处打点并证明其来源。cold/warm 只能由实际加载记录确定，不能把第一条自动算冷启动。

## 六、训练与验收分开

先验证参数确实更新、保存完整、新进程加载等价，再衡量答复。teacher-forced NLL/logprob/logit 是诊断；自然度由盲化的人类比较和任务场景结果评价。已暴露的 R3 场景只能用于开发。新独立场景组封存后不得调 prompt、阈值或词表再重命名为盲测。

任何阶段失败只阻塞依赖该证据的下游。例如 Codex blocked 不阻塞三个宿主修复、Qwen prompt-only 与 gold 收集；它阻塞当前需要第二真实模型的 silver 通路及完整比较。
