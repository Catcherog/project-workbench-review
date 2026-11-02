# R4：真实候选、少量人工校准和训练输入闭环

## 当前可确认的数量

固定 R3 回传包含 26 条真实 Qwen 候选，来自 13 个场景原型的两个实体变体。原有校验结果为 **10 pass、16 indeterminate**。后者表示受限语法不能认定，不能记作 16 条错误。按实际文本比较，26 条中有 25 个不同 logical prompt、22 个不同输出文本；不能把重复变体当作独立能力覆盖。

R3 已有 **gold SFT train 1、dev 1；DPO 0；experimental silver SFT 0**。这两条完整答复的人工认可继续有效。R4 没有新增真实人工评分，没有调用真实模型，也没有训练。R4 新评审包有 8 条待评、2 条已审引用、2 条宿主缺陷待重生成；默认回读导出新增 SFT/DPO 均为 0。

这些数量来自固定 [comparison.json](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/evidence/comparison.json) 和 [data-preparation.json](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/evidence/data-preparation.json)。

## 为什么只发这一小批

`data/r4-review/review.md` 按场景族各选一条，覆盖事项保存但提醒未定、文档缺资料、草稿待确认、发送回执、取消保留历史、部分成功且第二条未知、真实重试、规则拒绝范围。A 为固定真实 Qwen 输出；B 为助手提出的草案，来源明确，未获用户认可。

`owner-and-relevant-progress-1` 和 `empty-todo-complete-read-1` 已获认可，不重复索审。后者属于 dev，不能移进训练或 gold anchor。两个 `empty-analysis-known-gap` 属于 dev，且最后一句“测试的开始时间和预计时长具体需要包含哪些内容？”由错误的宿主 content slot 生成；应先修成 start_time/duration 等明确缺口，再形成新 frame、新 prompt 和新候选。不能将修改前后的答案放进同 prompt 的 DPO 对。

原 R3 的组划分继续保留；这批是开发校准，不是新盲测。后续扩写先冻结新 scenario group 的 split，再生成措辞、实体、事实反例。同组衍生保持同 split。独立效果验收应使用尚未展示过的新场景组。

## 可执行操作

包内 `data/r4-review/` 已生成，不需要重跑。若要从固定输入重建一个新批次，在项目根目录选择尚不存在的输出目录：

```bash
python scripts/review_batch.py build --input-dir data/r3 --out-dir data/r4-review-new-01
python scripts/review_batch.py import \
  --batch data/r4-review-new-01/batch.json \
  --feedback data/r4-review-new-01/feedback.pending.json \
  --out-dir data/r4-review-new-01-pending-import
```

第二条只是验证全 pending 的通路，必然输出新增 0。build/import 都先验证输入，再创建新输出目录；普通路径、解析后的目录别名或 symlink 已存在时均拒绝覆盖，重复运行必须换一个新目录。真实回读时保存一份新的 feedback 文件，填写 `origin=human`、真实 `reviewer`、带时区的 `reviewed_at`。逐条分别标注 `facts_pass`、`style_pass`、`acceptable`；`accepted_candidate` 只有在三者都明确为 true 时才可导出 SFT。`preference` 可为空。需要 DPO 时，再明确 chosen/rejected；两者必须有事实核验、文本不同、共用同一个目标 prompt，chosen 必须绝对可接受。

`both_bad` 进入 repair queue；`cannot_judge` 不产生标签；`pending` 不得藏有批准字段。自然语言修改建议保留为 comment，不会自动成为已认可的训练文本。助手意见、模型评分不能把 origin 填成人。

回读同时核对 batch SHA、场景 ID、frame/policy/student binding、实际 wire prompt SHA 和两条候选文本 SHA。换一句话、换事实、换 prompt、换运输配置，都不能复用旧评审。回读写入新目录，保留原始 R3 gold 和原待评包。

## 数据安全边界与可解释限制

这些 SHA 用于检测内容和上下文错配，不证明标注者身份或模型日志真实。模型调用记录仍需来自受信任执行器并保存原始证据。人工审核者的意见只作用于对应完整文本和情境，不自动扩展到另一个实体变体。

`normalized_prompt()` 现在识别严格的 native envelope 并在 logical user 内容上比较相似度；共同的 system 文本不能制造跨场景近重复。组冲突检查、同组衍生约束、实体归一化和跨 split 近重复检测继续保留。

逐条人工核验用于正式 gold SFT/DPO。它不要求所有隔离训练实验都逐条人审；机器筛选的 experimental silver SFT 使用另一套明确的弱监督入口，见 `docs/silver_training.md`。两条路线都不能把本轮可见开发数据称作独立效果验收。
