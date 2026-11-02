# 小批人工校准与隔离 silver SFT

目的：让用户先用少量样本确定输出原则，再由 Qwen、Codex CLI 等生成和筛查大批合成候选，用于隔离 SFT 效果实验；不要求用户先逐条审核几百条。机器筛选的数据叫 **experimental silver（实验银标）**，始终是弱监督，不等于人工认可或业务验收。

当前实际状态：**正式 gold SFT = 0，gold DPO = 0，experimental silver SFT = 0**。26 条随包种子没有真实模型生成/评审记录，也没有已核验的小批人审锚点；本轮没有填造 judge 记录、没有运行模型或训练。

## 1. 数据路线

1. 小批人工校准：选代表性场景，用户评价或修订完整答复，核对事实和可采用性，形成版本化 gold anchor。
2. 冻结 `frame`、`StylePolicy` 和 `build_messages()` 结果，同一场景及派生预先分组，使用原协调器 Qwen 或隔离 Codex CLI 生成候选。
3. 宿主事实核验：本包内置 `BoundedVerifier` 必须通过且覆盖全部必答。它只认识已核对语义单元的组合；自由改述不能证明时保持未知，不因两模型都称好就放行。接入其他真实证据语义核验器需要另行验证，当前没有伪造这种通用能力。
4. 两个不同 provider identity 的模型分别评审事实、风格、用户规则，绑定同一候选、prompt、frame、policy 和 gold anchor。不同调用 ID 的同一模型不算两个独立来源。
5. 通过者导出为 silver SFT，`human_approved=false`，`experimental_only=true`。同一组不能跨 train/dev；calibration、sealed_test 不导出。
6. 对比原模型、加强提示词、gold SFT、silver SFT 与混合试验；用未参与调参的独立人评判定是否改善。DPO 继续只使用人工偏好，机器 judge 结果不进入 gold DPO。

Gold anchor 的例子只能来自 **train/calibration**。dev、test、sealed_test 答案不能放进 judge 的参考锚点，避免通过机器筛选把评估答案间接带回训练。

## 2. 可执行接口

`am_style.silver.judge_candidate(provider, record, candidate_key, gold_anchor)` 可以直接接现有 Provider 的 `generate(ModelRequest)`。Qwen 使用原 `CoordinatorProvider`；Codex 使用已隔离的 `CodexCLIProvider`。函数只有被显式调用才请求模型，没有自动调用或隐式重试。

```python
from am_style.silver import judge_candidate, export_silver_sft

# providers 均由真实环境按已有隔离、身份、取消和预算规则构造。
# generated_record 来自冻结快照；candidate 必须记录真实 provider/model/run_id。
record["silver_selection"] = "qwen_candidate"
record["silver_judges"] = [
    judge_candidate(qwen_provider, record, "qwen_candidate", gold_anchor),
    judge_candidate(codex_provider, record, "qwen_candidate", gold_anchor),
]
prepared = export_silver_sft(
    records, gold_anchor=gold_anchor, experimental_only=True
)
# prepared["outputs"] 为 sft.train/sft.dev；未通过原因保留在 skipped。
```

`build_judge_messages()` 会把候选的实际 runtime prompt、冻结 frame、完整风格 policy 与小批 gold anchor 放入评审输入，明确资料中的指令仅为数据。评审输出必须包含：

```json
{
  "decision": "pass",
  "facts_pass": true,
  "style_pass": true,
  "rules_pass": true,
  "reason": "评审者根据具体事实与原则给出的解释"
}
```

这是格式示例，**不是任何实际样本的通过记录**。可返回 `reject` 或 `uncertain`。为兼容当前 Provider 的 `{text}` schema，外层返回 `{"text":"上述评审JSON字符串"}`；适配器负责严格解析。

每次真实调用会记录 provider、model、独立 run ID、duration、judge 请求 hash、原始响应及 hash、结构化评审及 hash、provider metadata，以及候选、prompt、frame、policy、anchor 的绑定 hash。训练入口重新构建实际评审问题，核对所有绑定、原始响应一致性与宿主事实验证，不能仅凭几项手填布尔值进入训练。

这些 JSON 证据来自受信任的本机评测运行器；hash 用于防止内容被改动，不能认证一个恶意写入者自行编造的 provider 名称或调用历史。保留真实调用日志用于复核。不同模型也可能共享偏见，两者同意仍不等于人工认可。

## 3. Gold anchor 契约

```text
schema: am-style-gold-anchor/1
version: 明确版本
policy_sha256: 当前 StylePolicy 字典的 canonical SHA-256
examples: 小批完整人审样本
```

每个 example 使用 gold SFT 的 `prompt/completion/provenance` 结构，须有事实合格、风格合格、可采用、人工认可、reviewer/time，以及 prompt/completion hash。保存 manifest 后取其 canonical SHA，填入 silver 配置的 `gold_anchor_sha256`；同时填当前 `style_policy_sha256`。本包不附虚假的已通过 anchor。

## 4. 训练与隔离

使用 `training/sft.silver.example.json` 建立单独实验配置。只有以下条件同时满足，SFT 入口才接受银标：

- `quality_tier=experimental_silver`。
- `experimental_only=true`。
- 数据集文件 hash、gold anchor hash、policy hash 与全部证据一致。
- 统一宿主合同与风格版本，训练/开发场景组互斥。
- 每条记录的 `human_approved` 明确为 false。

默认配置仍是 gold。DPO 拒绝 silver tier。模型运行记录会写入 quality tier 和实验状态；训练完成不启用原 AM，也不等于正式认可。后续量化、回归、独立人评仍需分别比较。

建议先拿一小批机器筛查通过的样本做短实验，看可采用率、自然度、错误完成声明与时延是否改善。银标量再大，也不能靠训练 loss 下降替代用户效果判断。
