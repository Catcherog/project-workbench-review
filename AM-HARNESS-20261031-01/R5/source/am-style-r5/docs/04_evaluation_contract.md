# R5 三臂评测、盲评及证据合同

本模块实现冻结评测计划、导入生成记录、制作匿名评审任务和汇总结果。模型调用由原环境适配器完成。模块不会训练、发送业务消息或修改生产开关。

## 1. 比较问题与固定分母

主三臂为 `production_q8`、`mlx_base`、`mlx_sft`，每条已计划场景都包含三臂。`legacy`、`codex` 可以另列为 `unavailable` 或 `blocked`，但不得用不可用替代三主臂或从总分母中删除它们。

| 对比 | 可回答的问题 | 不能据此声称 |
| --- | --- | --- |
| MLX base → MLX SFT | 同一基座、分词器、输入、生成设置和运行代码下，adapter 对输出产生的变化 | 小样本自然度已显著提高、真实业务已验收 |
| production Q8 → MLX base/SFT | 两个运行环境在相同逻辑任务上的表现差异 | 差异全部由训练造成、独立基座与生产 Q8 权重等价 |

MLX 两臂必须有相同 `base_revision`、`model_manifest_sha256`、`tokenizer_sha256` 和完整 `generation_settings`。base 不加载 adapter；SFT 使用固定 adapter SHA256。revision 必须是 40 或 64 位不可变哈希，不接受浮动的 `main` 或模型简称。生产臂记录自身 `model_digest` 和真实参数，未知的原服务默认值明确用 `null` 保留。

为保证公平，MLX 配对报告还检查两次运行的 `runner_source_sha256`。真实runner中该字段是 `execution_sources` 列明的R4/R5执行源码集合及来源的整体摘要，不只hash入口文件；第三方MLX代码还由固定环境合同单独校验。源码不一致的两条输出可以保留和人工阅读，但不计入“同代码 adapter 对照”的相对票数。真实适配器另外负责核对本机实际加载的权重和 tokenizer；纯 JSON 记录不具备证明远程执行真实性的能力。

每条场景固定 `frame`、`style_policy`、`logical_messages`、`student_wire_messages`。`build_plan()` 使用本包固定的 R4 `SpeechFrame`、`build_messages()` 与 `coordinator_messages()` 重建后逐值核对。`validate_plan()` 重新构造整个计划，不能仅靠重算 SHA 把旧 prompt 与新事实拼在一起。

## 2. 开发观察与独立留出集

`split=calibration` 用于公开开发材料，可以真实调用模型，也可以使用 fixture。它始终标记 `sample_status=not_independent`；补齐了真实推理记录也不能改写成未见过的测试集。

`split=sealed_test` 用于 Codex 在原机准备的独立留出场景，要求：

- 场景组不与任何 train、dev 场景组重合。一个场景换项目名或人员名不能冒充新组。
- 真实 sealed_test 计划必须传入 `exclusion_snapshot_path`。模块调用 `verify_gold_snapshot()` 读取已经验证的 train/dev 原文，并用 R4 `assert_split_integrity()` 比较逻辑任务的近重复；只换 case ID 或 group 名的旧 prompt 仍会被拒绝。
- `independent_test_eligible=true`、`public_exposed=false`。兼容旧字段 `independent`、`public_example`；冲突字段以更严格规则拒绝。
- 真实运行计划附有人类“未用于训练或调参”声明，包含 `declared_by`、`declared_at`、`source_evidence_sha256`、`not_used_for_tuning=true`，并绑定本次 `case_manifest_sha256`。
- 声明记录和原始人工来源由执行端留存。内容哈希能绑定声明，不能认证声明者或证明他从未看过样本。
- 若一个计划混合 calibration 和 sealed_test，整体报告仍标为 `not_independent`。应分开生成计划和报告，以便判断独立样本效果。

`mode=fixture` 用于代码和流程验证。fixture 即使字段完整也不会获得独立效果结论。`mode=real` 仅表示本批要求提供真实生成证据，不自动意味着独立样本、合格数据、人工认可或可启用生产。

排除快照的文件哈希、内容哈希、train/dev 文件哈希和最小 prompt/group 记录一并进入计划。`validate_plan()` 每次从该固定原快照重新验证并重建排除集合；因此原机必须保留快照和它引用的人工数据工件。修改计划内的排除记录再重算 seal，也不能跳过这项检查。只有模型生成记录需要的 prompt 进入最小排除集合，人工回复原文不因此进入公开盲评任务。

真实 sealed_test 还要求所选 pilot 的 `mlx_sft.train_file_sha256`、`dev_file_sha256` 与排除快照的两份文件哈希完全一致；这两项身份由实际 pilot request 派生并在 runner 中回读，不能用快照 A 的隔离检查替代实际在数据 B 上训练的 adapter。

## 3. Python 接口

可以先调用 `freeze_cases(cases)` 冻结输入，获得与后续正式计划完全相同的 `case_manifest_sha256`；此时不需要模型臂或尚未产生的 SFT adapter。`build_plan()` 同时接受原始 case 列表和冻结后的 bundle，并重新核对全部衍生字段。训练前先保存这个 bundle 及未调参声明，训练完成后再把真实 adapter 身份绑定到计划，避免为了取 case 哈希而伪造一个提前存在的 adapter。冻结输入本身不证明独立性，也不豁免真实 sealed_test 的排除快照门禁。

```python
frozen_cases = freeze_cases(cases)    # 训练前可做；不依赖arms或adapter
plan = build_plan(
    frozen_cases, arms,
    mode="fixture",                 # 原机真实调用改为 real
    training_groups=[],
    development_groups=[],
    holdout_declaration=None,
    exclusion_snapshot_path=None,    # 真实 sealed_test 必须指定原机已验证gold快照
)
validate_plan(plan)

record = make_result_record(
    plan, case_id, arm,
    status="completed",
    runner_source_sha256=source_hash,
    request_artifact=original_request_utf8,
    response_artifact=original_response_utf8,
    raw_output=exact_generated_json,
    request_binding={
        "wire_messages": {"path": ["actual_messages"]},
        "generation_settings": {"path": ["generation_settings"]},
    },
    response_binding={"path": ["text"]},
    latency_ms={"end_to_end": elapsed_ms, "provider": provider_ms},
    capture_kind="fixture",          # 原机为 actual_provider_exchange
)
results = import_results(plan, records)
public_task, private_map = blind_batch(plan, results)
report = feedback_report(plan, results, public_task, private_map, human_feedback)
```

`cases` 字段：`case_id`、`group_id`、`split`、`frame`、`style_policy`、`logical_messages`、`student_wire_messages`、`review_context`，加上述独立性字段。`review_context` 为人评需要的事实依据，允许字符串或对象，不能藏入模型臂名或展示生成结果的来源。

每个 arm 的模型身份对象被整体哈希绑定。可额外记录 `provider`、`model`、本机只读权重证据等；同一计划一经生成不能在结果导入时偷偷换参数。

## 4. 原始工件和结果导入

`make_result_record()` 自动计算 plan/input/frame/logical/wire/model identity/request/response/raw output/parsed output 的哈希，再封装记录。`import_results()` 独立复算并核对，不以记录自报 `mode=real` 为通过依据。

completed 记录必须有原始 request 和 response 工件、模型原始输出，以及能从原始工件读取输入和输出的 selector。selector 支持：

- `path`：对象键或数组下标构成的路径。
- `decode_json=true` 配合 `after_decode_path`：读取字符串内的 JSON，如旧 coordinator prompt。
- `transform=coordinator_messages`：使用固定 R4 转换重建实际单 user transport。
- `format=text`：整个原始工件文本就是被绑定的值。

原机适配器可以在真正提交请求之前，把实际消息、有效生成设置和原 provider request 一起写入 capture envelope；必须保留原始 provider payload。包中的 runner 正是先保存这一对象，再提交原队列或调用 MLX。导入器校验 envelope 中输入、设置及 response 中原始模型文本与计划完全一致。适配器源码哈希、原工件和当次运行回执共同提供证据；工件内容和哈希仍不是可信硬件证明。

每个 case/arm 只接收一条结果，重复记录直接拒绝。重试必须在另一份预先冻结的 attempt 计划中记录，不能事后只挑最好的一次。

保留 `completed`、`failed/error`、`unknown/stop_unknown`、`truncated`、`timeout`、`cancelled`、`blocked`、`unavailable` 和自动补齐的 `missing`。非 completed 记录即使留有部分文本，也不算有效输出。发生 `stop_unknown` 后由执行适配器停止后续批次，未执行的其他场景继续留在分母中。

默认机器核验分三层：JSON schema、R4 bounded/natural 事实守卫、人工评审。可注入仅用于测试的 verifier callback，但 callback 通过不算真实模型或业务证据。`NaturalSurfaceVerifier` 的名称不表示它能判断用户所说的“自然”；它依然是有限表达规则。

## 5. 匿名评审与反馈绑定

`blind_batch()` 使用 `secrets.SystemRandom` 和安全随机 token，为每批、每场景、每个选项生成新标识并随机排序。公共任务展示原始用户问题、事实依据、匿名选项、文本哈希和评价维度。模型臂、case ID、运行记录哈希及映射只进入私有对象。

私有映射应单独以 `0600` 保存，不与盲评材料一起展示，也不上传公开审核仓库。公共任务中的候选正文不允许为了隐藏模型身份而静默改写；检测到臂名或模型名泄漏时拒绝该盲评任务，原始证据保留，由执行端说明问题后重新准备。

人工评价分别填写：

| 维度 | 值域 | 解释 |
| --- | --- | --- |
| fact | pass / fail / cannot_judge | 是否保留事实、主体、否定、时间、范围和实际执行状态 |
| naturalness | 1–5 或 null | 读起来是否自然、简明，是否像本人对同事说话 |
| absolute_usable | true / false / null | 在事实正确之外，是否愿意直接使用这条完整回复 |
| relative outcome | left / right / tie / both_bad / cannot_judge | 同一输入下的两条完整输出谁更好，允许无胜者 |

反馈示例结构：

```json
{
  "public_sha256": "公共任务的SHA256",
  "mode": "fixture",
  "reviewer": "人工评审者标识",
  "reviewed_at": "2026-11-02T18:00:00+08:00",
  "human_authored": true,
  "source_evidence_sha256": "真实反馈原件的SHA256",
  "ratings": [
    {"option_id": "匿名选项ID", "text_sha256": "完整文本SHA256", "fact": "pass", "naturalness": 4, "absolute_usable": true}
  ],
  "preferences": [
    {"task_id": "匿名场景ID", "option_ids": ["左选项ID", "右选项ID"], "content_sha256": "preference_content_hash的返回值", "outcome": "tie"}
  ]
}
```

真实模式要求 `human_authored=true` 和原始人工反馈来源哈希。执行端必须真正保存这份人工来源，不能让另一个模型生成该声明。反馈中的文本或相对选项顺序变化都会使绑定失败；修改后的完整文本需要新一次认可，不能沿用原认可。

相对偏好可用于后续 DPO 准备的必要条件是：同输入、两边人工事实均合格、chosen 绝对可用、两条文本不同、且具有真正的相对胜者。`both_bad`、`tie`、`cannot_judge` 不产生胜负对。报表只计“合格偏好证据数量”，不自动生成训练数据或执行 DPO。

## 6. 报告口径与停止边界

报告保留每臂计划分母、各状态数、schema 数、机器事实判定、人评案例数、人评人数/票数、事实合格与绝对可用比例、各场景组状态、同代码 MLX 配对数和真实相对偏好。无返回的模型不会因缺失而获得更好成功率。

延迟统一采用线性插值：排序后位置 `(n - 1) * p`，分别给 p50、p95、max 和观测数量。`attempt_end_to_end_latency` 包含所有已观测尝试，包括 failed、timeout、stop_unknown；`completed_end_to_end_latency` 单独展示成功完成的请求，避免隐藏失败等待。缺少时长记录或从未尝试的数量另列。provider 耗时作为原始证据保留，不把排队时间、模型时间或整段用户任务时间混写成一个指标。

样本共享场景组时不能假装每条完全独立。本轮报表默认不输出未经假设说明的置信区间；优先展示逐组结果、有效配对数和全部失败。未来有足够独立场景组时，可以预先冻结组级 bootstrap 等统计方案，再执行一次独立评测，不能看完结果才改统计口径。

任何报告都保留 `production_enabled=false`、`business_acceptance=false`，自动报告不会自行认定自然度改善。自然度结论需要用户或独立评审结合有效样本、事实合格率、绝对可用性、同输入偏好及延迟判断。NLL、schema、kernel 或单步参数更新不能替代这种判断。

## 7. 中断后的只读记录恢复

每次运行由适配器逐条写入 `001-record.json` 等原记录。即使进程在写完完整 `results.jsonl` 之前中断，仍可以调用：

```python
from am_style_r5.collection import collect_run_records

summary = collect_run_records(
    plan,
    ["/absolute/qwen-run", "/absolute/mlx-base-run", "/absolute/mlx-sft-run"],
    "/absolute/new-collected-records.jsonl",
)
```

收集器只读取明确提供目录的直接子级 `*-record.json`，包括 `parent-interruption-record.json`；不递归、不搜索其他目录，不依赖可能未完成的 `results.jsonl`。它逐个严格解析 JSON、检查原 seal，再用 `import_results()` 验证全部输入、模型身份和工件绑定。任何损坏、内容变化、重复 case/arm 或不属于该计划的记录都会使整次收集失败，不会跳过坏记录，也不会替用户猜测哪个重试结果应该保留。

输出必须是新的 JSONL 文件，只包含完整验证后的原记录，不加入人工补造的 missing 行或恢复结论。返回摘要列出 planned、recorded、missing、状态计数、每个源文件的字节哈希和输出哈希；这里 missing 指计划中没有原记录的数量。计划中未执行的组合仍会在后续 `eval-import` 和报告中保留。

收集前后还会核对直接子级文件集合和已读文件哈希，若运行进程同时增加或修改记录则拒绝本次输出。收集器不启动、停止或检查 worker，`current_worker_stop_status` 始终为 `not_checked`。`stop_unknown` 只是原记录中的状态，不能据此宣布 worker 已停止。如果未确认停止的 worker 后来写出与父进程中断观察相同 case/arm 的记录，两条都保留在源目录，收集会因重复而拒绝；执行端须先完成真实状态核对，再明确选择新的可审核输入集合。
