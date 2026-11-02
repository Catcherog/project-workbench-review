# R4 experimental silver SFT：独立运输绑定与弱监督

## 状态

固定 R3 **正式 gold SFT train 1、dev 1；DPO 0**，本轮保持原文件字节和批准记录。**experimental silver SFT 仍为 0**：尚没有同一候选的两份独立真实模型评审。R4 8 条待评也没有自动批准。此模块没有调用真实 Qwen/Codex、没有下载权重或实际训练。

银标路线的用途是“少量人工校准锚点 → 有边界事实核验 → 两个独立来源模型按同一用户规则筛查 → 明确隔离的 SFT 弱监督实验 → 新场景独立人评”。机器一致不等于人工认可，实验记录必须保持 `human_approved=false`、`experimental_only=true`、`quality_tier=experimental_silver`。DPO 本轮仍只接受人工偏好数据。

## 已复现并修复的接线问题

固定 R3 实际 gold prompt 是 LocalQwenClient native_chat 的单 user envelope，合同为 `am-terminal-presenter/3.0.1+coordinator-native-envelope/1`。旧 silver 验证器只认裸 `am-terminal-presenter/3.0.1` 并拿输入与内层 system/user messages 直接比较，因此即使后续获得真实双评审，真实 Qwen 输入仍会被拒绝。

R4 新增 `am_style.transport`，**不升级 PROMPT_VERSION、不迁移原两条 gold**。三种 profile 分别记录：

| profile | 实际可知的 provider 输入 | 允许作为目标 Qwen 训练输入 |
|---|---|---|
| `direct-chat/1` | logical messages 直接送 chat 接口 | 仅显式选择该真实运行配置时 |
| `coordinator-native-envelope/1` | `[{role:user, content:canonical({messages:logical, tools:[]})}]` | 是，本项目原 Qwen 目标配置 |
| `codex-canonical-messages-stdin/1` | canonical logical messages 的 stdin UTF-8 文本 | 否，只作为 producer 或 judge 证据 |

Codex CLI 仍保留其系统、AGENTS 和既有策略上下文。stdin 哈希只界定可知输入，不声称是完整模型上下文，也不声称这是纯模型能力的公平对照。生成者、评审者、待训练学生各有 `purpose=producer/judge/student` binding；不能用 teacher wire 冒充 student prompt。

## API 和调用顺序

```python
from copy import deepcopy
from am_style.transport import (
    runtime_binding, student_prompt, student_contract_version,
    COORDINATOR_NATIVE, CODEX_STDIN,
)
from am_style.silver import (
    generate_silver_candidate, judge_candidate, prepare_silver_sft_row,
)

# record 必须为有冻结 frame/policy、source SHA、预分组 split 的 synthetic 样本。
# 新建记录，不能把已有 gold 的批准字段复制到新文本。
record = deepcopy(unreviewed_record)
target = runtime_binding(record["frame"], record["style_policy"],
                         profile=COORDINATOR_NATIVE, purpose="student")
record.update(target_binding=target, prompt=student_prompt(target),
              host_contract_version=student_contract_version(target),
              runtime_prompt_alignment="aligned", human_approved=False)

# 这些函数会真的调用已配置的 provider；包内构建/测试不会自动执行它们。
# 只有实际 Codex capability preflight 已通过时，才能传入相应 provider。
record["candidates"]["teacher"] = generate_silver_candidate(
    codex_provider, record, producer_profile=CODEX_STDIN)
record["silver_selection"] = "teacher"
record["semantic_profile"] = "bounded-surfaces/1"
record["silver_judges"] = [
    judge_candidate(qwen_provider, record, "teacher", train_gold_anchor,
                    judge_profile=COORDINATOR_NATIVE),
    judge_candidate(codex_provider, record, "teacher", train_gold_anchor,
                    judge_profile=CODEX_STDIN),
]
row = prepare_silver_sft_row(record, gold_anchor=train_gold_anchor,
                             experimental_only=True)
```

现有 provider 接收的仍是 logical `ModelRequest`，由各自既有 adapter 只封装一次。上面 `wire_payload` 用于证据和学生数据，不应再传给会封装的 adapter。接口要求明确选 profile；执行端应核对它与真实 adapter 一致。哈希不能证明任意手填的 provider 声明。

`bind_prompt()` 保存 logical prompt 及其 SHA、profile/purpose、wire payload 及其 SHA、frame/policy SHA 和完整 binding SHA。`validate_student_record()` 重算真实 target prompt，并要求与 record.prompt、host_contract_version 完全相符。

## 可执行评审证据

`build_judge_messages()` 以被冻结的 candidate prompt、候选 JSON completion、frame、policy、gold anchor、target binding 和 semantic profile 构建实际评审请求。`judge_candidate()` 调用 provider 后保留原始响应和响应 SHA、逻辑请求 SHA、judge transport binding、model/provider/run ID、target/frame/policy/candidate/anchor SHA。

响应外层仍为 provider 支持的 `{"text":"..."}`；text 是下列完整 JSON 对象的字符串：

```json
{
  "decision": "pass",
  "facts_pass": true,
  "style_pass": true,
  "rules_pass": true,
  "reason": "实际评审模型给出的具体依据"
}
```

这只是 schema 示例，不能用作实际评审记录。代码同时核对原始响应、解析结果、请求及全部 binding，不接受只有几项手填 bool 的证据。两个评审需来自不同 provider identity，且 provider/model 身份和 run ID 不得重复或重用生成调用；它们是独立评审调用，允许其中一个与教师来自同一 provider。不同名字本身仍不证明服务独立，需真实执行日志支撑。

默认事实核验为 `bounded-surfaces/1`；可显式选择 `natural-typed-surfaces/4.0.1`，映射到 `CompositeVerifier(NaturalSurfaceVerifier())`。未知 profile 直接拒绝。请求的 profile 写入评审请求及证据，实际通过的 verifier/version 另外记录。默认语法已经通过时，使用 natural profile 的实际 verdict 仍可能是 bounded verifier。模型双评审不能覆盖 host 的 unknown/reject。

gold anchor 必须有真实人工认可、准确政策 hash 和版本；锚点只取 train/calibration，不能含 dev/test/sealed_test。目标 dev 不能与任何 anchor 的场景组重叠。候选必须 synthetic、同 frame/policy 投影；训练和开发按原场景组归属；sealed/calibration 不导出银标。

## 验证与剩余边界

相关标准库测试覆盖实际 R3 gold native wire、不改原文件、Codex teacher 与 Qwen student 分离、错误 purpose、双 envelope、judge wire 篡改、切换 semantic profile 后复用旧评审、无锚点、锚点泄漏、伪人工标记和全未评种子导出 0。模型调用均为明确的 test double；没有将测试夹具写入正式训练数据。

这些验证说明数据与调用合同一致，不证明通用自然语言事实核验已经解决，不证明当前 Qwen 表达已通过整体业务验收。完整表达效果仍应由独立人评判断。
