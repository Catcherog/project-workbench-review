# 48 项标注：可采用的原则、数据边界与训练准备

本文件依据用户本轮附件、固定 GitHub 审核提交与原盲评构建脚本。结论仅针对已实际读到的材料；没有恢复、猜测或重造原文 A/B。

## 1. 数据身份与实读结果

| 项目 | 结果 |
| --- | --- |
| 用户附件 | `R2-FIX1-盲评评分 (1).json`；包内无损副本 `data/input/ratings.json` |
| 附件 SHA-256 | `593992ee2b25288dd5e533699fcd274ff340b02ed9aa7f6af3ef7364624505a6` |
| 标注版本 | `r2-fix1-blind/1` |
| 绑定的原始数据集 SHA-256 | `6fb6d4fe17fa4daa94cdfca7fed28d03b95f61feeb9655b2885fd0e2f6f04309` |
| 与远端公开索引一致性 | 数据集 SHA、48 个 case ID 一致 |
| 标注数量 | 48 项条目，47 项有判断；1 项未评分 |
| A / B 相对偏好 | A 更好 20；B 更好 23 |
| 两者都不合格 | 4 项：QRY-03、ANA-03、REM-04、ERR-03 |
| 未评分 | KNW-04 |
| 严重错误标记 | QRY-03 的 B；REM-04 的 A、B，共 3 个标记，涉及 2 项 |
| 原盲评双侧都有实际答复 | 10/48；38 项至少一侧未产生答复 |
| 本轮能够完整核验的原文配对 | 0：原文 pairs 与随机揭盲 key 未在公开审核包中 |
| 当前可直接进入正式 gold SFT / DPO 的行数 | 0 / 0 |
| 当前可直接进入 experimental silver SFT 的行数 | 0；没有给候选伪造模型评审或人工锚点 |

**23 次偏好 B、20 次偏好 A，不能解释为新模型获胜 23 次、旧模型获胜 20 次。** 原构建脚本逐项随机 A/B；key 留在本机。即使找回 key，单侧占位条目也不能参与双侧自然度胜率。索引只告诉我们共有 10 对双侧可呈现，不告诉我们这些对应哪几个用户偏好；本轮不估算比例。

用户的“更好”是相对比较，含义不等于“这条已经可以对外使用”。未勾选严重错误也不等于完成了事实逐项复核。43 项相对偏好进入待复核队列，4 项双差进入修复队列，1 项未评分保留，不补成偏好、平局或失败。

## 2. 已明确的表达原则

| 原则 | 用户标注依据 | 对运行时的要求 |
| --- | --- | --- |
| 直接回答结果，像同事日常说话 | QRY-01、QRY-02、QRY-04 | 不把“备注”“来源”“本轮可呈现结果”等内部说明塞进正文。 |
| 可以带必要的关联信息 | QRY-01 | 只补有证据且帮助用户行动的一两句，不能借机扩写未知业务事实。 |
| 默认不显示来源，追问再展示 | QRY-04 | 来源仍在内部绑定和审计中保留；展示策略与证据核验独立。 |
| 待办有就分点列，没有就自然说明 | QRY-03 | 只有成功读取且范围完整才能说“暂时没有”；读取失败须说未查到，不能说没有。 |
| 没答案时回应具体问题并说明原因 | ANA-03 | 说明已经证实的信息缺口或读取失败；未知原因不编成确定解释。 |
| 缺信息时具体追问 | FUP-01、FUP-04、DOC-01/02/04、APR-04、OUT-02/04、ERR-01 | 结合问题合并问关键缺口，不机械要求“补齐字段”，也不反复索取已有材料。 |
| 可以有轻微口语感 | FUP-01、FUP-04、NOT-03 | “你说的是哪位？”“我没太搞懂”可作为候选风格；具体语气强度仍由本轮合并提问收敛。 |
| 笔记与提醒状态分清 | NOT-01 | 有保存回执才说“记下了”；提醒时间不明就问，不假称已安排。 |
| 范围和时间限制要问清 | KNW-03 | “不要采用”可能只针对项目、时间或某条规则；不自动推成永久全局停用。 |
| 执行结果要明确 | REM-04 | 完成、失败、未知、部分完成分别说清楚；未知不能伪装成失败或成功。 |
| 多项结果先概括 | CAN-04、PAR-01 | 只有两项都取得对应回执，才说“两个需求都建立好了跟进”；不能用汇总抹掉其中的未知。 |
| 错误先说原因，再交代后续 | ERR-03 | “会再处理”必须对应真实已安排的重试或继续执行；否则应说明“需要先核对”“你补充后我再继续”。 |

这里的重点是**先把用户需要的答复内容组织正确，再换成自然说法**。仅删除来源标签、添加“好的”“呢”，既不能补齐遗漏的执行结果，也无法修复没有针对问题作答的情况。

## 3. 已实现的数据处理

`am_style/data.py` 提供：

1. JSON 重复键、非有限数拒绝；版本、数据集 SHA、case ID 集合强绑定。
2. 原私有 `pairs.json` 的 SHA 按原脚本公式复现：`json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')`。不是对美化后的 JSON 文件字节取 hash。
3. 随机 A/B key 仅用于本机解盲归因，必须与同一数据集 metadata、case 顺序、行号一致。原 metadata 不含 key 自身指纹，因此历史 key 并没有密码学绑定；本轮明确保留这个证据限制。
4. 偏好获胜侧同时标为严重错误时隔离；both-bad、未评分、平局、无法评分别保留。
5. 在生成实体替换、改述、反事实之前，按 scenario group 固定 train/dev/test 归属；同一原型及派生都留在同一组。
6. 对跨 split 的同 group、实体/数字替换后的重复、文本近重复进行拒绝。该检测是保守防线，不能声称识别了所有语义近重复。
7. 正式 gold 路线只接受经过人审并绑定当前 prompt 与候选文本 hash 的记录。另有隔离的 experimental silver SFT 路线，允许小批人工锚点加双模型机器筛查，不要求用户逐条评几百条；仍明确属于弱监督，不伪造人工认可，见 `silver_training.md`。
8. SFT 输出标准对话 `prompt` + `completion`；completion 是 `{"text":"最终答复"}` 的 JSON 字符串，与运行时输出合同一致。
9. 风格 DPO 需要同一个 prompt、不同答复、人工偏好，以及两侧事实都合格；错误事实样本不混入风格 DPO。此轮未另建事实安全 DPO 训练集。
10. `calibration` 与 `sealed_test` 均不会训练导出。当前 48 项反馈已用于设计，只作开发校准，不能再宣称是独立盲测成绩。

`align_runtime_prompt()` 用于接收宿主真正的 `am_style.prompt.build_messages(frame, policy)` 投影。重投影会清空旧审核和选择，因为 prompt 变了，之前人审不能自动继承。没有宿主对齐标记和合同版本，即使填了审核字段也不能导出训练文件。

## 4. 合成候选的实际状态

`am_style/synthetic.py` 目前包含 13 个场景原型、每个 2 个实体变体，共 **26 条待审候选场景**。每条有一份自然表达草案和一份生硬表达对照，均是助手为评审编写的合成文本；不是 Qwen 或 Codex 的真实生成结果，也不是用户已经确认的正负标签。

场景覆盖负责人、空待办、缺依据分析、人员歧义、笔记与提醒、规则范围、缺资料写文档、待确认草稿、发送完成、缺提醒时间、取消范围、部分完成与读取重试。事实全部虚构。没有使用公司真实项目状态填充训练知识。

交付时，26 条种子已经通过 `project_seed()` 的明确映射进入实际 `make_frame()` 与 `build_messages(frame, StylePolicy(realization='free'))`，记录 frame、policy、prompt hash 与 host contract 版本。它们用于快速讨论原则与接通评审流程，不能直接训练；候选仍是未审核的合成草案，不能假称模型已经生成。下一步让同一个冻结快照分别通过 Qwen 与 Codex CLI 生成候选；小批人审形成 gold 锚点，大批候选可经事实核验与双模型评审导出隔离 silver SFT，不必全部先经人审。DPO 仍只使用真实人工偏好。

另提供 6 条语义反例挑战：预计改成已确认、未知改成成功、单回执覆盖两项成功、读取失败说成无待办、无重试任务却承诺重试、扩大范围及期限。它们标记 `constructed_counterexample`，用于核验器回归，既不是用户打出的负标签，也不进入风格 DPO。

代码中 `sealed_test` 表示预留测试分组。当前种子内容随包可见，没有独立封存管理，不宣称已经形成有效的独立密封测试集。正式验收应另外准备从未用于调参或提示词修改的场景组，并冻结再评。

## 5. 本机找回原盲评的最小步骤

Codex 在原任务目录寻找 `blind-private/pairs.json` 或 `blind-private/48项盲评.html`；揭盲 key 与 metadata 位置由原构建脚本规定：

```text
~/.local/share/local-qwen-feishu/validation/am-harness-r2-fix1/blind-key.json
~/.local/share/local-qwen-feishu/validation/am-harness-r2-fix1/blind-key-metadata.json
```

这些是源码给出的预期路径，本轮云端没有实测本机文件存在。**不要重跑旧构建脚本重新生成随机 key，也不要改旧 pairs 以迎合评分 hash。** 找到原文件后，执行：

```bash
python scripts/build_data.py \
  --pairs /absolute/path/to/original/blind-private/pairs.json \
  --key /absolute/path/to/original/blind-key.json \
  --key-metadata /absolute/path/to/original/blind-key-metadata.json \
  --output /absolute/path/to/private/r3-data-analysis
```

脚本只有读入和分析，不上传私有原文。若原件丢失，继续使用这 48 条反馈提取原则，另做新的候选和人评即可；不能用脱敏输出或新生成文本冒充当时 A/B。

## 6. 复现

```bash
python scripts/build_data.py
python -m unittest discover -s tests -p test_data.py -v
```

默认输出 48 项分析、26 条已对齐宿主提示词但未审核的候选、6 条语义反例、4 份空 gold 训练 JSONL、2 份空 silver SFT JSONL 及各自 manifest。当前没有真实小批人工锚点和双模型评审，所以 gold 与 silver 都是 0。运行训练脚本遇到空数据应明确停止，不能把空导出描述为已经训练。

22 项数据检查已在本轮本地运行通过，覆盖 hash 篡改、重复键、单侧缺失、严重错获胜侧、随机 A/B 归因、机器标签冒充人审、prompt 或答复变更、测试集泄漏、跨组近重复、DPO 事实错误、重新投影后失效，以及实际统一 prompt 的同一性。它们是数据管线检查，不是模型自然度、SFT 收敛或真实业务验收。

## 来源

- 本轮用户附件及其包内无损副本 `data/input/ratings.json`。
- [固定提交：原盲评 README](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX1/blind/README.md)
- [固定提交：原盲评公开索引](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX1/blind/pair-index.json)
- [固定提交：原盲评构建脚本](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX1/scripts/build_blind_review.py)
