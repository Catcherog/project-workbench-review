# Codex 原机执行交接

## 任务与授权

任务 `AM-HARNESS-20261031-01 / R5`。用户已经明确要求 GPT 完成架构与代码，由 Codex 负责实际训练和真实验证。本包已经实现可离线完成的代码，不需要重新做一轮架构设计，也不应每执行一个可逆准备步骤就向用户重复确认。

Codex 的交付是**实际原机证据及结果**：当前源码与状态、真实gold快照、受控pilot、三组推理与人评、宿主验证、完整失败分母，以及固定GitHub审核入口。缺少真实人工标签、实际未见测试材料或原件时，记录具体缺项，继续完成不依赖它的工作。不能自行填写人工认可，也不能改门槛使流程变绿。

## 1. 接收、定位与原状态记录

把交付包解压到新的实验目录；保留原工程最新提交和工作树。先读取本包 `00_当前交接.md`、架构及相关合同，运行 `verify.py`。不得将 `baseline/` 覆盖到现有项目。

实读并记录以下信息，所有路径来自原机当前状态：

- 当前源仓库、工作树分支、HEAD、未提交改动及R4之后的相关差异。
- 已存在的MLX虚拟环境Python、独立基座manifest与本地权重、R4 mechanics-002原始目录。
- 原服务主config、poc config、协调锁、数据库、原合成探针队列、唯一消费者PID。
- 原Q8模型名与digest、运行/安装源码、原生产开关及其文件SHA。
- 当前待处理业务、内存与已有模型状态；原服务保持原样。

训练与生成会验证相关R4源码。若最新宿主有修改，保留差异并判断其影响；本包的固定哈希不能直接改成新值以绕过检查。可明确选择包内已审源码进行独立复现，须记录选择，不得声称已经测试较新的宿主。

以下变量只是命令槽位。Codex必须替换为实际读到的绝对路径，不要照抄 `/absolute/...`：

```bash
AM_R5_PACKAGE="/absolute/new-experiment/AM-HARNESS-20261031-01_R5"
AM_R5_WORK="/absolute/new-experiment/r5-run-001"
AM_R5_PYTHON="/absolute/existing-mlx-venv/bin/python"
AM_R5_MANIFEST="/absolute/original-base-manifest.json"
AM_R5_MECHANICS="/absolute/original-mlx-mechanics-002/result.json"
AM_R5_HOST_SRC="/absolute/current-project/am-conversation-r1/src"
AM_R5_TRAINING_ROOT="/absolute/current-project/am-style-r3"
export AM_R5_HOST_SRC AM_R5_TRAINING_ROOT
mkdir "$AM_R5_WORK"

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/verify.py" \
  --output "$AM_R5_WORK/offline-verification"
```

`verify.py` 检查本包固定依赖并使用临时夹具，不测试生产。其source_mode明确为pinned_delivery_baseline。主工程真实回归另外运行原有命令，并逐名称/断言核对已知失败；不要把新增测试数量与上轮843/27混合。若后续源码已变，分别记录当前结果与相对R4差异。

## 2. 准备22条待评答复与实际反馈

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" prepare \
  --output "$AM_R5_WORK/prepared"
```

输出 `review.md`、`review-batch.json`、`feedback.pending.json`、冻结组清单，以及保持旧9/1的 `current-gold`。已随包提供同内容示例，但原机应使用本次固定文件作为反馈绑定目标。

向用户展示问题、事实、完整候选和需判断的维度。反馈支持认可、拒绝、无法判断和改写，不能把“相对更好”解释成“能直接采用”。`origin=human`、reviewer、带时区时间和布尔判断必须对应真实意见。

如果用户直接填写JSON，以该文件为原始反馈。若从聊天转写，另保存原始消息导出；导入时用 `--raw-feedback` 指向它。路径和人名只在原机证据保留，公开导出另外脱敏。

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" import-feedback \
  --batch "$AM_R5_WORK/prepared/review-batch.json" \
  --feedback "$AM_R5_WORK/feedback.filled.json" \
  --raw-feedback "$AM_R5_WORK/feedback.original.txt" \
  --output "$AM_R5_WORK/feedback.imported.json"

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" snapshot \
  --registry "$AM_R5_WORK/prepared/group-registry.json" \
  --imports "$AM_R5_WORK/feedback.imported.json" \
  --output "$AM_R5_WORK/gold-001"

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" verify-snapshot \
  --snapshot "$AM_R5_WORK/gold-001/snapshot.json"
```

原生JSON反馈可省略 `--raw-feedback`。多份有效导入文件可以一并传给 `--imports`；同一个case不能重复计数。如果只认可了部分条目，快照就只追加相应gold。

改稿时使用 case ID→**完整新答复** 的JSON对象，不写局部字符串替换。以下命令产生新的批次，旧反馈不得直接复用：

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" revise \
  --batch "$AM_R5_WORK/prepared/review-batch.json" \
  --replacements "$AM_R5_WORK/replacements.json" \
  --version R5-calibration-02 \
  --output "$AM_R5_WORK/review-revision-002"
```

若要从同一批次分多次汇总认可，应把真实意见合并到一个完整绑定的反馈版本，或用互不重复的case集合导入。不要把同一case的旧认可和改稿后认可同时计入快照。

## 3. 训练前冻结独立效果测试

公开22条和R3/R4已展示材料可做calibration，不能作为未见测试。原机另取真实、已获读取授权的业务场景或此前未参与调参的人工场景；冻结事实截面、来源、问题、场景组、typed frame、policy与实际prompt。

建议至少8个新场景组、每组2例，优先覆盖主体与责任、否定、时间/范围、未执行/部分执行/未知、同名项目、冲突记录和资料不足。不得只是把旧问题换人名或项目名后标新组。数量不足如实报告。

场景格式见 `docs/04_evaluation_contract.md`。使用原 `build_messages()` 和 `coordinator_messages()` 构造两个输入字段，不能手改prompt来改变事实。`split=sealed_test`、`independent_test_eligible=true`、`public_exposed=false` 只有事实符合时才能填写。

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" eval-freeze \
  --cases "$AM_R5_WORK/holdout.cases.json" \
  --output "$AM_R5_WORK/holdout.frozen.json"
```

该命令不需要adapter，可以在训练前完成。保存冻结时间、`case_manifest_sha256` 与真实的未用于训练/调参声明。声明结构如下，占位内容必须由真实来源填入，不能让模型伪造：

```json
{
  "case_manifest_sha256": "由holdout.frozen.json读取的精确值",
  "not_used_for_tuning": true,
  "declared_by": "真实声明人",
  "declared_at": "真实带时区时间",
  "source_evidence_sha256": "真实声明原件的SHA256"
}
```

冻结只锁定内容，不自动判定独立性。正式计划还会重读最终gold快照做组与近重复排除。私有测试输入、声明原件和盲评映射都留在原机，不提前展示给用于调参的流程。

## 4. 从实际mechanics生成并执行pilot

真实快照至少 train24/dev8、组8/4且不交叉，才开始此步。若22条全部认可，本轮将是train24/dev8、组14/5；实际数以快照回读为准。

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" pilot-plan \
  --snapshot "$AM_R5_WORK/gold-001/snapshot.json" \
  --mechanics "$AM_R5_MECHANICS" \
  --manifest "$AM_R5_MANIFEST" \
  --python "$AM_R5_PYTHON" \
  --host-src "$AM_R5_HOST_SRC" \
  --training-root "$AM_R5_TRAINING_ROOT" \
  --run-dir "$AM_R5_WORK/pilot-run-001" \
  --output "$AM_R5_WORK/pilot-plan-001"

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" pilot-preflight \
  --plan "$AM_R5_WORK/pilot-plan-001/plan.json"

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" pilot-command \
  --plan "$AM_R5_WORK/pilot-plan-001/plan.json"
```

`pilot-command` 返回结构化argv及环境，不执行。既有授权、数据与原件门禁均满足且原机空闲时继续：

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" pilot-execute \
  --plan "$AM_R5_WORK/pilot-plan-001/plan.json" --execute
```

不要重复mechanics仅为了把R5标签加到旧成功上。只有实际相关代码/环境改变导致原证据不再适用时，才明确记录新的复审与实验选择。完整独立基座、原始私有request及adapter不在本公开包中，必须读取原机原件。

成功时回读全部文件和actual consumed IDs：一遍数据、每步4个不同样本（末尾按实际余数）、有限非零梯度和参数变化、adapter保存、fit停止、独立reload PID、完整keyset/逐张量相等及teacher诊断。300秒、内存、业务抢占或停止未知时保留真实失败，不自动延长、重启或增加训练步数。

## 5. 固定实际三组身份和计划

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" eval-arms \
  --manifest "$AM_R5_MANIFEST" \
  --sft-run "$AM_R5_WORK/pilot-run-001" \
  --output "$AM_R5_WORK/arms.real.json"

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" eval-plan \
  --cases "$AM_R5_WORK/holdout.frozen.json" \
  --arms "$AM_R5_WORK/arms.real.json" \
  --mode real \
  --snapshot "$AM_R5_WORK/gold-001/snapshot.json" \
  --declaration "$AM_R5_WORK/holdout.declaration.json" \
  --output "$AM_R5_WORK/evaluation.real.plan.json"
```

如果另外观察公开开发材料，用 `prepared/evaluation.calibration.json` 另建real计划，结果始终标记not_independent，不与独立测试混算。

原队列配置由真实路径和已观察的原消费者PID生成：

```bash
AM_R5_HOST_CONFIG="/absolute/original-service/config.json"
AM_R5_QUEUE="/absolute/original-service/poc/state/am-conversation-r2"
AM_R5_CONSUMER_PID="原机实读的整数PID"

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" queue-config \
  --manifest "$AM_R5_MANIFEST" \
  --host-config "$AM_R5_HOST_CONFIG" \
  --queue-root "$AM_R5_QUEUE" \
  --consumer-pid "$AM_R5_CONSUMER_PID" \
  --output "$AM_R5_WORK/queue.real.json"
```

命令会验证主配置和poc配置的既有保护SHA、实际队列推导路径、已存在requests/results及PID可观测存活。PID存活不等于身份认证；Codex仍需保存原机进程及唯一消费者证据。不得创建新消费者补这个条件。

## 6. 依次运行三个真实生成组

按原资源窗口串行执行。原Qwen和MLX不能在未核清前一个调用是否停止时接连启动。

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" eval-qwen \
  --plan "$AM_R5_WORK/evaluation.real.plan.json" \
  --queue-config "$AM_R5_WORK/queue.real.json" \
  --output "$AM_R5_WORK/qwen-001" --execute

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" eval-mlx \
  --plan "$AM_R5_WORK/evaluation.real.plan.json" \
  --manifest "$AM_R5_MANIFEST" --arm mlx_base \
  --worker-timeout 300 \
  --output "$AM_R5_WORK/mlx-base-001" --execute

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" eval-mlx \
  --plan "$AM_R5_WORK/evaluation.real.plan.json" \
  --manifest "$AM_R5_MANIFEST" --arm mlx_sft \
  --sft-run "$AM_R5_WORK/pilot-run-001" \
  --worker-timeout 300 \
  --output "$AM_R5_WORK/mlx-sft-001" --execute
```

这三条是顺序步骤，不是遇到错误也继续执行的shell脚本。每条后先读run/parent-result及停止确认。实际生成失败或停止未知返回exit2；预检有阻塞也返回exit2。`stop_unknown`时先核清该调用，禁止直接启动下一条。

可以在执行前用 `--case-ids ID1 ID2` 明确拆分互不重叠的小批次，每批输出新目录、单worker仍不超过300秒。不要把同一case重试结果混入同一个冻结计划；需要重试必须另建attempt计划并保留首次失败。

MLX结果的end_to_end计单条生成，不含一次model_load；原Qwen计入原队列等待至回读。两组MLX可对照同口径；Q8仅作外部参照，不能将这些数值当成完整业务响应延迟。

## 7. 汇总所有结果与匿名人评

每条实际记录会先落盘，异常退出也尽量保留当前失败及已完成记录。使用collect从明确的运行目录汇总原记录，完整校验后导出新JSONL，不自行挑选最好结果：

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" collect \
  --plan "$AM_R5_WORK/evaluation.real.plan.json" \
  --runs "$AM_R5_WORK/qwen-001" "$AM_R5_WORK/mlx-base-001" "$AM_R5_WORK/mlx-sft-001" \
  --output "$AM_R5_WORK/all-records.jsonl"

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" eval-import \
  --plan "$AM_R5_WORK/evaluation.real.plan.json" \
  --records "$AM_R5_WORK/all-records.jsonl" \
  --output "$AM_R5_WORK/evaluation.results.json"

"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" blind \
  --plan "$AM_R5_WORK/evaluation.real.plan.json" \
  --results "$AM_R5_WORK/evaluation.results.json" \
  --output "$AM_R5_WORK/blind-001"
```

将 `blind-review.md` 与待填反馈交给评审，`blind-private.json` 单独保留，不随盲评材料发送，也不公开上传。评审先判断事实，再评自然度1–5及绝对可用，最后做相对比较；tie、both_bad、cannot_judge均是有效结论。人工原件需要真实保留，不能由Codex补标签。

在模板中只把已完成的 `pending_rating_items` 复制到 `ratings`、已完成的 `pending_preference_items` 复制到 `preferences`，保留原ID与文本/顺序hash。设置真实reviewer、reviewed_at、human_authored及source_evidence_sha256。未评项继续pending。

```bash
"$AM_R5_PYTHON" "$AM_R5_PACKAGE/run.py" report \
  --plan "$AM_R5_WORK/evaluation.real.plan.json" \
  --results "$AM_R5_WORK/evaluation.results.json" \
  --public "$AM_R5_WORK/blind-001/blind-public.json" \
  --private "$AM_R5_WORK/blind-001/blind-private.json" \
  --feedback "$AM_R5_WORK/blind.feedback.filled.json" \
  --output "$AM_R5_WORK/report-001"
```

没有人工反馈时可先省略public/private/feedback生成机器结果报告；报告将保持未评状态，不能称为自然度验收。收集到多位实际评审后可传多个feedback文件。不要用模型评分伪造独立人评。

## 8. 原宿主与业务验证

本包不修改生产入口，Codex仍需在原机验证接入来源和宿主合同。复用当前工程已有合成探针与回归，记录真实加载源码。R4固定 `scripts/probe_terminal.py` 可作为调用链参考，但不能只改任务标签就重复使用旧输出，也不能把scripted task model标为真实任务模型。

| 验证项 | 最低实际证据 | 结论边界 |
| --- | --- | --- |
| 原工程回归 | 当前真实命令、exit code、JUnit/日志、失败名称和断言差异 | 新包离线测试不能替代原机回归 |
| 原Qwen接入 | 原消费者PID、模型digest、原队列request/response、保护配置前后SHA | 队列交换不等于HTTP抓包或真实业务投递 |
| `_finish` / terminal 合同 | 实际运行源码、合成事实、真实terminal调用、前置/入队前复查 | 若task model是scripted，必须明确标注 |
| 重复消息 | 同标识重放、响应一致、没有增加原模型调用 | 不因重复刷新执行状态或重发业务动作 |
| 权限/过期/访问版本 | 正常与变更后的真实测试输入、是否回落、是否拒绝采用旧候选 | 不拿旧候选跨权限或过期边界复用 |
| 执行状态表达 | 未执行、部分成功、未知、已取消的host回执与完整答复 | 模型不得把未知写成成功，不得新增外部动作 |
| 记录异常 | 损坏/缺字段/嵌套类型异常的原回归结果 | 失败必须显式保留，不能落入伪成功 |
| 手机、独立人员、真实业务 | 各自真实测试记录或明确not_run | 不能由synthetic probe替代；当前授权不包含擅自发外部消息 |

真实平台写入或对外消息仍按已经明确的业务授权执行；本交接不自动增加这项权限。可先完成本机、只读和合成验证。训练闭环与宿主探针成功不会自动改变生产开关。

## 9. R5回传与最终口径

在既有三方协作授权范围内，将本任务新增代码、设计、脱敏运行证据、逐文件清单和结论回传审核仓库的本任务R5目录；保留其他任务目录。实际源仓库也记录对应提交。不要覆盖R4固定入口。

建议审核包至少包含：

- `00_当前交接.md`：实际源SHA、审核SHA、执行环境、完成/阻塞项目、严格结论。
- `SOURCE_SHA256.json`：原机实际运行源码与本包设计源码差异。
- `DATA_SUMMARY.json`：真实train/dev/组数、反馈来源摘要、快照hash和逐行来源，不公开私有原文。
- pilot请求、预检、每步更新、fit、reload、停止与结果图的脱敏副本；权重只保留原机及摘要。
- 两类评测计划（开发/独立）、原始记录摘要、逐组与配对报告、人评事实/自然度/可用性统计、完整失败分母。
- 宿主回归、实际加载文件、原消费者/模型/生产开关前后核对。
- `EXPORT_BOUNDARY.json`：每份原件SHA与公开副本SHA、脱敏范围；私有人评/盲评映射/权重不上传。
- `MANIFEST.json`：本次实际文件数与哈希。推送后逐文件远端读回，再给固定commit链接。

结论按证据分别写：数据准备、mechanics、pilot更新与回载、开发观察、独立人评、宿主接入、生产启用、业务验收。样本不足、自然度无改善或变差、停止未知、Codex隔离未完成、silver未完成、DPO未完成均保留原状态。不要用“全部通过”概括部分成功。
