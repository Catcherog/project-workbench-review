# R4：独立 MLX 基线的训练复核与最小实验

## 当前结论

R3 已有一条可信度有限、范围明确的真实单步训练记录：本机独立官方 HF 基线的 MLX 4-bit 文本分支，在 1 条 gold train、1 条 gold dev 上完成 1 次更新，保存 adapter 并在后续新进程中加载。它不是原生产 Q8 的同基座微调，不能把独立基线的结果归给生产 Q8，也没有表达改善或业务验收结论。

R4 新增的是机制证据与小规模试验入口。本轮只做源码复核、Python 协议测试及元数据预检查；**没有调用 MLX、运行真实数值/梯度核验、加载模型、训练、下载、安装、付费、量化、回导或切换生产。** 下文标为运行时核验的步骤，是代码下一次在原机执行的工作，不是本轮已通过的结果。

## 1. R3 证据独立复核

审核仓库固定到 `Catcherog/project-workbench-review@7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757`，目录 `AM-HARNESS-20261031-01/R3/`。

| 项目 | 已有证据与复核结果 | 不能推出的结论 |
|---|---|---|
| 基座身份 | 原生产 Q8 摘要为 `52b6ea169d93070c185373f6ff9ec33a7a5e88cfe9c844fc225ed4214683baef`；独立 HF revision 为 `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`。记录明确保留两者不可变 revision 等价性未证明。 | 不能称为原 Q8 的同基座 SFT。 |
| 本地文件 | weight-readback 记录原始与 MLX 共40个文件相对既有 manifest 哈希一致。MLX 与原始的 chat template 哈希一致，tokenizer 文件字节不同。 | 本次云端没有原机权重；文件记录不等于云端重新核验权重，也不能仅由模板一致推出两个 tokenizer 的全部 token ID 等价。 |
| 训练数据 | 两条公开 JSONL 的文件、prompt、completion 哈希一致；train/dev 场景组不重叠；与冻结场景重建的 `coordinator_messages(build_messages(...))`、原队列保存的 prompt 精确一致。 | 两条绝对认可不是 DPO 相对偏好；旧48项不变成训练对。 |
| 实际角色封装 | prompt 的真实外层是一个 `user` 消息，内容是 `{"messages":[...],"tools":[]}`；内层 system/user 只是 JSON 内容。 | 不能擅自展开成原生 system/user 角色后仍沿用相同 tokenization/审核。 |
| mask | 源码的 next-token 索引 `prompt_tokens-1 ... len(ids)-2` 正确覆盖 completion；记录为 prompt 542/500、completion 28/14、最长570，无截断。 | 公开包没有实际 tokenized.json，本次未加载 tokenizer，故未独立重算 token ID、EOS 和长度。 |
| 参数更新 | 代码实际调用 AdamW 一次，报告 dev loss `0.1262299269 → 0.1261630207`。保存文件逐张量回读一致。 | 缺少更新前后参数差、梯度 finite/nonzero 和保存前后完整键集合的远端记录，不能仅凭 optimizer_steps=1 完成这些证明。 |
| 新进程加载 | eval 脚本在训练进程之外先加载 base，再在同一个 eval 进程中加载 adapter。 | 不是每个臂单独一个进程；eval 未显式核对 adapter SHA 和加载后完整参数集合。 |
| 3 个诊断 | 六条记录的冻结 prompt 与每对输出完全一致：每个臂1项 bounded pass、2项 indeterminate；无新人评。 | 只证明这3个已暴露场景的 greedy 文本未变；不能推出参数没更新、概率没变、全体任务无改善或训练有效。 |

dev loss 绝对变化为 `-6.690621376e-5`，相对约 `-0.0530%`，来自单个开发样例。这个量不能充当自然度效果。

发现一项可定位的证据整理问题：`sft-source-sha256.json` 的 smoke 脚本指纹仍是旧值 `23815ba6…`；实际回传脚本 SHA256 是 `129d1e10…`，与 **sft-attempt.json 中实际运行来源一致**。helper 两份指纹及 eval 脚本指纹一致。这里应修正辅助索引，不能反过来宣称主训练来源不匹配。

来源：[R3模型训练说明](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/02_%E6%A8%A1%E5%9E%8B%E6%95%B0%E6%8D%AE%E4%B8%8E%E8%AE%AD%E7%BB%83.md)、[SFT记录](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/evidence/sft-attempt.json)、[诊断结果](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/evidence/mlx-eval.json)。

## 2. 自定义 delta-rule 补丁的支持边界

R3 补丁用 FP32 三角块重排 scalar-gated delta recurrence。公开源码包含小张量 forward/state/gradient 检查，但固定 R3 树中没有其真实 `chunk_delta_validation.json` 结果，也没有与当时安装源码绑定的运行记录。`verify()` 函数存在不代表该次已通过。

本轮查到 MLX-LM `v0.32.2` 的不可变 commit 为 `93e6d4a6447b3080861985947f0820e76fcb957d`。官方 Qwen3.5 实现在 `use_kernel=not self.training` 下选择训练 reference 路径；`grad_checkpoint(layer)` 会修改该 decoder layer **类**的 `__call__`；`load_adapters` 使用 `strict=False`，虽验证所提供张量是否为允许的 adapter 参数及形状，却不会单凭这一调用证明所有预期 adapter 叶子均存在。

R4 把这些事实落实为门禁：

- 精确绑定 MLX 0.32.4、MLX-LM 0.32.2、Transformers 5.20.2、tokenizers 0.23.3；psutil 使用原机已安装版本并明确填写。对6份已审 MLX-LM 源文件核对 Git blob，不接受改版本或修改源码后直接复用证明。
- 在模型加载前，真实运行小张量数值核验：31/32/33 token 块边界、不同 batch 与 head ratio、原模型实际 key/value head 尺寸、FP32/BF16 的输出、递归 state 和 q/k/v/g/beta/state 梯度；另查高相关三角求逆残差、zero-decay 的输出与 state，以及 mask/vector-gate 回退。
- 误差容限在代码中预先固定；失败立即退出，不自动放宽。报告记录测得误差、dtype、形状、容限、补丁和上游模块 SHA、依赖版本及完整本轮代码指纹。
- zero-decay 只核验输出和 state，不声称证明该边界的 Jacobian。小张量验证也不等于完整27B模型的梯度等价性证明；该未完成项明确保留。
- 补丁使用 context manager 恢复；decoder 类的 checkpoint 补丁由独立 worker 进程隔离。生产 Ollama 的进程、模型和推理内核不受该 Python 补丁影响。

来源：[官方 gated delta 实现](https://github.com/ml-explore/mlx-lm/blob/93e6d4a6447b3080861985947f0820e76fcb957d/mlx_lm/models/gated_delta.py)、[官方 Qwen3.5 训练/推理路径](https://github.com/ml-explore/mlx-lm/blob/93e6d4a6447b3080861985947f0820e76fcb957d/mlx_lm/models/qwen3_5.py)、[checkpoint 实现](https://github.com/ml-explore/mlx-lm/blob/93e6d4a6447b3080861985947f0820e76fcb957d/mlx_lm/tuner/trainer.py)、[adapter 加载实现](https://github.com/ml-explore/mlx-lm/blob/93e6d4a6447b3080861985947f0820e76fcb957d/mlx_lm/tuner/utils.py)。

## 3. 分阶段执行条件

| 阶段 | 必须满足的条件 | 实际执行及停止条件 |
|---|---|---|
| 元数据预检 | 填好原机现有路径、原始来源 manifest、实际依赖版本、原生产配置指纹、数据文件和 prompt builder 指纹。 | 不导入 MLX，不加载模型，不获取生产租约，不请求模型。当前环境缺 MLX，示例路径为空，预检应退出码2。 |
| mechanics | 严格保持 R3 的1条 train、1条 dev 文件字节、ID与场景组；不改旧审核。原始独立4-bit文件必须逐一回读哈希。 | 从同一独立 base 新建 LoRA，真实 kernel 检查后只更新1步，保存，退出训练进程，再新进程重载与诊断复现。它不是继续训练原 R3 adapter。 |
| pilot | 同一代码/基座已完成真实 R4 mechanics 证据闭环；新增足够 gold 后，24–48条 train、8–16条 dev，至少8/4个互不重叠场景组。保留 R3 owner=train、empty-todo=dev。 | 每条训练样本仅用一次，batch1，4条不同样本累积一次更新，共6–12步；不得复制单条、增加 epoch 或把旧dev放到train来凑数量。 |
| 表达效果评测 | 冻结新的、没有用于调参和设计的场景；同输入比较独立 base 与所选 SFT；另列生产 Q8，保留模型来源差异。 | 分开记录 JSON、事实、自然度、人类相对偏好、延迟与采用率。未做人评不能输出“自然度提高”。 |

24/8条及8/4个场景组是本项目第一轮小试的工程门槛，不是统计有效性保证或通用最低训练量。新数据审核未齐时，代码会阻断 pilot；不会重复原单条训练制造进展。

两阶段保留末2层、rank8、scale2、dropout0、713472训练参数、seed221、lr1e-5。R3 的 MLX AdamW 省略参数实际采用 `weight_decay=0.01, bias_correction=False`，R4 显式固定同样的值，避免把未记载的默认项当作不存在。额外记录梯度裁剪比例（上限norm1），并要求有效任务梯度和真实 LoRA-B 更新，不能让仅有 weight decay 的 A 矩阵变化充当学习证据。来源：[MLX 0.32.4 AdamW 源码](https://github.com/ml-explore/mlx/blob/v0.32.4/python/mlx/optimizers/optimizers.py)。

## 4. 输入、mask 与保存/重载

`validate_native_prompt` 用当前真实 `build_messages` + `coordinator_messages` 重建并逐字比较输入；既检查外层单user封装，也检查内层系统说明、完整 style 与 canonical payload。使用既有 gold 审核哈希与分组校验，新的封装或提示词必须重新对齐审核，不能静默重写已批准样本。

运行时将 thinking/preserve_thinking 明确关闭，比较直接 chat-template tokenization 与渲染字符串在 `add_special_tokens=False` 下的 token IDs；不采用生成器对额外 BOS 的启发式。完整序列必须以前缀 prompt 开头，completion 非空，长度不超过1024，不截断。明确核验 EOS/EOM 恰好一次及其后只有模板空白；构造完整 labels 与 next-token shifted loss positions，所有 prompt labels 为-100。实际 tokenized.json 和其 SHA 会保存供复审。

训练时在每次 optimizer 前确认所有梯度叶子正好对应 LoRA、全部有限、global norm非零；更新后检查同一参数集合、dtype/shape、有限差值、实际变化的叶子及 LoRA-B 叶子。保存初始化 adapter 与最终 adapter 的独立文件和哈希；最终文件回读后逐张量相等。

父进程不导入 MLX。fit worker 完成并确认进程组停止后，才启动 reload worker，所以两个27B实例不会由此流程同时驻留。新进程再核对精确基座、数据、代码和保存产物哈希；加载 adapter 后补做上游 `strict=False` 没有提供的完整键集合检查与逐张量相等；最后与训练末尾的 teacher-forced 诊断比较。模型权重及 adapter 留在本机，本包没有任何上传或部署命令。

## 5. 输出不变时如何诊断

R3 的3个greedy输出完全相同，应保留为“这些暴露诊断上未观察到文本变化”。下一次即使文字仍相同，也可通过以下证据区分不同原因：

1. 梯度是否有限且非零、LoRA-B 是否真实变化；这回答更新是否实际发生。
2. 同一固定输入和 target token 的条件 logprob 与 token-weighted NLL 是否变化；分别列 train 与 dev，不把训练首例和开发样例混成开发loss。
3. 首/中/尾 completion 位置，在目标词表集合及IDs0–15上的稀疏 logit 探针差异；明确这是探针，不是全词表 KL。
4. 保存后新进程是否以完整 adapter 复现这些值。容限为预先固定的绝对5e-4，失败不能继续当作有效checkpoint。

这些是机制和概率诊断。Greedy输出由最高概率token决定，概率的小变化可以不改变最高项；反过来，NLL变好也不能替代自然度和事实验收。所有报告都保留 `quality_conclusion=not_established`、`business_acceptance=false`。

## 6. 原协调器资源约束

执行前取得原 `model-coordinator.lock` 的非阻塞排他租约；绝不另建一个“自称协调器”的实验锁。保护配置文件按字节哈希回读；只读原 chat/gateway数据库，检查原 tasks/inbox 及 AM 的 harness/inbox。只读 `/api/ps`，不发送 production chat/generate、不卸载、不续租模型、不重启。

加载前至少24GiB可用；MLX限22GiB、cache限128MiB；运行中可用内存不足5GiB、critical pressure、swap增加超过1GiB或出现新业务，均停止。每个microbatch和诊断样例前重复检查，不把启动时“空闲”当作整轮空闲。单个worker墙钟上限300秒；父进程超时先终止、再必要时kill本地进程组，确认退出后才允许后续加载。停止不确定时 reload 明确标 skipped。等待业务结束后也不自动重试或续训。

这些是本机短窗口小试约束，不是持续占用生产机器训练的授权。若24–48条一次遍历无法在窗口内完成，保留失败/已完成steps记录，另外规划显式checkpoint恢复或独立机器；不要扩大超时和内存上限来绕过当前资源限制。

## 7. 运行方式

先复制三个 `config/mlx_r4*.example.json` 到原机独立运行目录，填写现有本地路径与缺失哈希。未知路径、psutil版本、prompt builder SHA保留空值时会阻断，不会自动搜索或下载模型。4-bit文件及两份来源manifest的指纹来自固定R3证据；如原文件不一致，先查明原因，不修改期望值绕过检查。

```bash
python -m training.mlx_r4 --inventory
python -m training.mlx_r4 --manifest local/r4-base.json --config local/r4-mechanics.json --report runs/r4-mechanics-preflight.json
```

原机完成可审阅的元数据和资源准备后，执行 mechanics（示例输出必须改成真实、新建的绝对路径）：

```bash
python -m training.mlx_r4 --manifest local/r4-base.json --config local/r4-mechanics.json --output /absolute/runs/r4-mechanics-001 --execute
```

`result.json` 只有在 fit、来源绑定的真实kernel核验、真实参数更新、保存回读、新进程加载与诊断复现都闭合后，才可 `mechanics_closed=true`。pilot配置中的 `mechanics_result.path/sha256` 指向该结果及完整同目录证据图；示例配置没有伪造此证明。准备新的 gold 数据、保持场景分组并填好新哈希后，再运行相同入口、改用pilot配置和另一个新目录。

本轮已完成17项纯Python协议测试，测试使用内存夹具，不会写入正式gold，也不会产出真实kernel通过声明。当前实际元数据预检查显示Linux/x86_64、MLX/MLX-LM/Transformers/tokenizers/psutil均未安装，示例执行条件未满足，退出码2、模型加载0、训练0。

## 8. DPO 下一步的边界

R4 没有 MLX DPO 实现，也不把 MLX 的 `adapters.safetensors`/`adapter_config.json` 直接交给旧 TRL/PEFT 入口。格式、权重命名、LoRA参数、基座量化方式及后端均不同；未经验证的文件重命名不是转换。

后续 DPO 应先选定可验证的后端：要么实际核对并实现对应 MLX DPO，要么在独立资源上完成可审计的 MLX→目标后端权重/adapter 转换，并验证同输入的tokenization、前向概率与checkpoint等价性。所选SFT可以是经过复核的R4 checkpoint，不是永久锁定R3的单步产物。必须固定具体SFT哈希：policy从该SFT开始，reference是同一SFT的冻结副本；禁止因格式不兼容、内存不足或加载错误退回原base当reference。

DPO数据还需要同一输入下两个事实均合格答案的真实人工相对偏好。两条gold示范、机器选择、三个相同诊断输出及旧48项暴露校准，均不能自动填成这种偏好。没有该数据及后端兼容证据时，继续保留DPO未执行。
