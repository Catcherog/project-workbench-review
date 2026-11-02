# R5 数据与人工反馈合同

## 1. 本轮交付的状态

`src/am_style_r5/dataset.py` 提供可执行的数据准备、改稿、人评导入和训练快照管线，复用固定 R4 的 `am_style.review.import_feedback()`、`am_style.data.export_training()`、运行时 prompt/transport 合同和分组泄露检查。

本包新增的 22 条答复都是**助手撰写的待审草案**。当前没有新增真实人工标签，没有调用真实模型生成这些草案，没有执行训练。固定 R4 gold 仍为 train 9 条、dev 1 条。

22 条待评场景预先划分为 15 条 train、7 条 dev，分别涉及 5 个新训练场景组、4 个新验证场景组。只有全部得到对完整文本的有效人工认可，并通过导入、去重和数据合同后，才可能形成 train 24 / dev 8、场景组 14 / 5 的快照。这个数量是条件计算，不能报告为已经取得的数据。未认可、无法判断和待修改项不补造标签；不够数就继续保留数据门禁失败。

这些公开样例都是开发校准资料。dev 可用于既定的训练诊断，但不能因为名称为 dev 就称为独立效果验收。真正未暴露的效果测试集应另行预留为 `sealed_test`，在后续效果实验开始前冻结；本轮代码不把该类样本放入人评校准批次或训练文件。旧固定资料中已有的 `sealed_test` 标签也不证明其内容仍然未暴露。

## 2. 固定数据和组归属

| 文件 | 固定 SHA256 | 处理方式 |
|---|---|---|
| `baseline/data/r4-gold/sft.train.jsonl` | `4392819139bddfa3cae18ec8f0f0a3ac82f4d27a8194050ed3e80e82137b0398` | 9 条旧 gold，作为每份新训练文件的原样字节前缀。 |
| `baseline/data/r4-gold/sft.dev.jsonl` | `151a8f426722d0298dcf785c1fac45fe287d3717be4d7ca0cdd21d27226a3009` | 1 条旧 gold，保留在 dev；不搬到 train。 |
| `baseline/data/r3-frozen-comparison.json` | `ad0b1bfb7501d11c34d5350e07cf9633663affceda220c099054e0ed498b4916` | 固定 R3 审核提交中的原始冻结输入；保留 26 个旧场景、13 个旧组的归属，用于检查新输入是否泄露。 |

旧组继续使用其原有的 R4/R3 `split_for_group()` 结果。新组允许在设计阶段明确指定 `train`、`dev` 或 `sealed_test`，不要求为了满足散列结果去反复改组名。分组一经写入封存清单，后续生成、评审和导出都核对同一清单。

`freeze_group_registry()` 同时冻结新 case ID、group ID、split、frame、policy 和实际训练 prompt 的哈希。修改候选措辞不改变场景归属；修改宿主事实、问题或 policy 必须先重新建立清楚的新场景版本，不能沿用旧反馈。

完整性检查分两层：

1. 复用 R4 `assert_split_integrity()`，检查重复 ID、父场景归属、同组跨 split、跨 split 近重复；沿用其 0.96 相似度边界，不自行放宽。
2. 拒绝重复的逻辑 prompt。拷贝一条 prompt 换 ID、再次导入同一反馈、同时导入同一 case 的两个版本，都不能增加样本数。不同实体/条件的变体仍归原场景组，不能充作独立新组。

哈希是内容绑定，不是访问控制或身份认证。代码还把旧 gold 与旧场景源的已审固定 SHA 写死；仅重算某个 JSON 的封存哈希，不能把旧 dev 转成 train。

## 3. 场景输入与待评批次

场景输入是列表，核心结构如下：

```python
{
    "id": "R5-CAL-example-1",
    "group_id": "r5-example",
    "split": "train",
    "frame": frozen_speech_frame,
    "style_policy": frozen_style_policy,
    "facts_for_review": "供人阅读的事实与限制说明",
    "proposal": "供人判断的完整答复",
    "synthetic": True,
}
```

frame 使用固定 `SpeechFrame` 合同；prompt 由原 `runtime_binding()` 和 `student_prompt()` 生成，继续使用 `coordinator-native-envelope/1` 的实际单 user 外层封装。不得把逻辑 messages 的哈希冒充实际训练输入的哈希。

`build_review_batch()` 输出兼容 R4 的 `am-style-human-review-batch/1`，并增加冻结组清单。每条草案固定为：

```json
{
  "origin": "assistant_authored_proposal",
  "human_approved": false,
  "model_run": false
}
```

记录的 `reviews`、`selection` 为空，`training_approved=false`，批次新人工认可数与新可训练数均为 0。代码会拒绝把人工认可标签嵌入输入场景或 pending 批次。

可选的 `model_records` 是观测文件引用列表，每个引用含 `path` 与原文件 `sha256`。对应 JSON 的合同为：

```json
{
  "schema": "am-style-r5-model-observation/1",
  "status": "completed",
  "actual_model_call": true,
  "provider": "真实执行时记录的 provider",
  "model": "真实执行时记录的 model",
  "run_id": "真实运行标识",
  "frame_sha256": "完整 frame 的 canonical JSON SHA256",
  "policy_sha256": "完整 policy 的 canonical JSON SHA256",
  "prompt_sha256": "student_prompt 返回值的 canonical JSON SHA256",
  "raw_response": "原始响应 JSON 文本",
  "candidate_text": "从该响应读取的完整 text",
  "raw_response_sha256": "原始响应 UTF-8 字节 SHA256"
}
```

只有完整响应可读、原文件哈希匹配、frame/policy/prompt 对应同一冻结任务时才接受。来源标记为 `model_call`，仍不取得人工认可。这里的 `actual_model_call` 是执行方的显式观察声明；代码和哈希不能认证远程调用确实发生，真实调用仍需 Codex 回传实际 request/response 与运行证据。

## 4. 改稿和真实反馈导入

调用 `feedback_template(batch)` 得到全 pending 表单。每个候选都有独立的事实、语气、绝对可用性判断，并绑定完整候选文本、prompt、frame、policy 与批次上下文。相对偏好不能代替“可直接采用”。

`revise_review_batch(batch, replacements, version=...)` 接受 case ID 到新完整草案文本的映射。它创建新的 batch SHA、review-context SHA 和候选 SHA，保留父批次引用；旧反馈提交到新版会被拒绝。原批次不变。不能只取得一句修改意见，就把旧认可转贴到自动修改后的全文。

`import_feedback_file(batch, feedback_path, raw_feedback_path=...)` 读取真实文件，再调用原 R4 导入逻辑。有效人工判断必须明确带有：

- `origin="human"`。
- 非空 reviewer 和带时区的 reviewed_at。
- 对应本批次、case、prompt/frame/policy 上下文的绑定。
- 完整候选文本的 SHA256。
- 被绝对认可的候选同时满足 facts_pass、style_pass、acceptable 为显式布尔 true。

没有这些判断的行继续 pending 或进入修复队列，不生成 gold。模型评价、自动语义通过、相对更好、未勾选严重错误，均不能转换为人工认可。

原生填写 JSON 表单时，feedback JSON 文件本身就是原始反馈工件。若 Codex 把用户聊天转写成结构化反馈，应通过 `raw_feedback_path` 指向保留的真实原文导出。输出同时记录结构化文件和原始文件的 SHA；**文件哈希只能证明内容未变，不能证明 reviewer 的真实身份或其实际意愿**。执行方必须据真实用户意见填写，不能自行勾选 true 来让数据门禁通过。

导入结果保存原 batch、原 feedback、原始文件引用及 R4 完整 import 结果。导出训练快照时会重新读取原文件、检查哈希、重新运行 R4 导入与导出逻辑，再比对保存结果；不能直接编辑 `r4_import.exports` 塞入 gold。

## 5. SFT 快照和训练接口

```python
registry = freeze_group_registry(
    specs, baseline_train=old_train, baseline_dev=old_dev)
batch = build_review_batch(specs, registry, version="R5-calibration-01")

# 先将 batch、可读评审文件与全 pending 表单交给用户。
# 下面只在实际收到相应反馈文件之后调用。
imported = import_feedback_file(
    batch, feedback_path, raw_feedback_path=original_feedback_path)
snapshot = export_gold_snapshot(
    registry, [imported], baseline_train=old_train,
    baseline_dev=old_dev, output_dir=new_snapshot_directory)
```

没有新反馈时可以用 `imports=[]` 生成只包含原 9/1 的检查快照。它仍然不满足 pilot 数据门槛；不能因导出成功就运行 pilot。

快照使用新目录和独占文件创建；不覆盖旧文件。完成验证后最后写 `snapshot.json`，并立即用 `verify_gold_snapshot()` 读回。结构如下：

```json
{
  "schema": "am-style-r5-gold-snapshot/1",
  "files": {
    "train": {"path": "sft.train.jsonl", "sha256": "...", "rows": 9, "groups": 9},
    "dev": {"path": "sft.dev.jsonl", "sha256": "...", "rows": 1, "groups": 1}
  },
  "counts": {"train": 9, "dev": 1, "train_groups": 9, "dev_groups": 1},
  "baseline": {"train": {"sha256": "...", "rows": 9, "byte_length": 0},
               "dev": {"sha256": "...", "rows": 1, "byte_length": 0}},
  "baseline_preserved": true,
  "group_registry_sha256": "...",
  "registry": {"path": "group-registry.json", "sha256": "..."},
  "imports": [],
  "sealed_test": {"exported_rows": 0, "groups": 1},
  "sft_only": true,
  "training_executed": false,
  "sha256": "去除本字段后的 canonical JSON SHA256"
}
```

上例只示意字段关系；`byte_length` 等必须由实际文件计算，不能照抄占位值。快照中的文件路径相对 `snapshot.json` 所在目录。实现会保存 feedback/import 原文件的副本，使快照能在原临时输入路径已不存在时独立读回验证。新增行的 provenance 另记录 import SHA、原始反馈 SHA 和 group-registry SHA；旧 9/1 行完全不改。

pilot 模块调用 `from am_style_r5.dataset import verify_gold_snapshot`，取得已核验的 paths、hashes、counts，再执行既定 R4 MLX 的数据和 mechanics 门禁。snapshot 校验会重新推导全部新增 SFT 后缀，因此“改 JSONL 后同时重算文件 SHA 和 snapshot SHA”仍然无法加入未评审数据。

R4 导入函数可能形成满足其合同的 DPO 相对偏好记录，这些只留在 import 证据中。本轮 snapshot 是 SFT-only，不导出 DPO 训练文件，不启动 silver、DPO 或实际模型训练。

## 6. 已执行的离线检查与限制

`tests/test_dataset.py` 的 15 项检查覆盖 pending 零标签、原 9/1 字节保留、对完整文本的反馈绑定、改稿失效、raw feedback 改动拒绝、重复导入和重复 prompt、旧 dev 禁止搬移、跨 split 近重复、frame 改动、sealed-test 排除、模型来源绑定，以及重算哈希后仍无法注入未评审 gold。

测试里的 reviewer 和模型记录都是明确标注的临时测试夹具，用于验证拒绝与导入逻辑。它们不是用户反馈、真实模型观测或可用于实际训练的数据；测试只写入会删除的临时目录。本模块本身没有调用真实模型、没有训练、没有变更生产开关，也不提供自然度改善结论。
