# Qwen 表达训练：可执行方案与已核实边界

日期：2026-11-02（Asia/Shanghai）。本轮交付训练入口、数据契约、版本核验和离线检查；没有启动训练，没有训练后的权重，也没有 SFT/DPO 效果结论。原 AM 服务、Ollama 模型和启用开关不由这些脚本修改。

## 1. 训练目标

训练输入与在线表达器使用同一个 `am_style.prompt.build_messages(frame, policy)`；输出是 `{"text":"最终自然回复"}` 的 JSON 字符串。业务事实、操作结果、身份、时间、范围和是否允许再次执行由宿主提供。模型只学习怎么在这个已核实状态下答话。

SFT 学习完整合格示范，例如直接答结果、必要时补一项关联信息、自然地补问缺口、准确说明执行结果。DPO 在同一输入下学习两个事实都正确的表达何者更适合所有者。事实错误的候选进入独立修复/安全数据，不混进默认的风格 DPO，避免把“更自然”和“是否说真话”当成同一个标签。

旧 48 项已经用于本轮设计，属于校准资料；相对 A/B 偏好不能自动升级成绝对合格示范。正式 gold 数据需要人工核对 `facts_pass/style_pass/acceptable/human_approved`，且审核绑定输入与输出哈希。为免让用户逐条审核几百条才允许实验，另提供 `experimental_silver` SFT：小批人审锚点确定原则，大批合成候选经宿主事实核验和两个独立来源模型评审后进入明确隔离的弱监督实验；`human_approved=false`，不替代独立人评。银标 DPO 本轮不启用。当前 gold SFT/DPO 与 experimental silver SFT 均为 0，不能为跑通训练补造审核。详见 `silver_training.md`。

## 2. Qwen tag 不能代替训练基座

已知运行标识是 `qwen3.8:27b-bartowski-q8_0`。这是当前服务的 Ollama tag，尚未取得其原始模型仓库、不可变 revision、精确架构、tokenizer 或训练机内存。不能把 tag 文字当成 Hugging Face 模型 ID，也不能自行替换成 Qwen3-8B、Qwen3-32B 等其他模型。

`model_manifest.example.json` 故意保留未知值为空。由 Codex 在原机核对原模型 metadata/Modelfile/来源记录，形成原 tag 到可训练权重的对应证据；同时记录原始权重、tokenizer、chat template、架构和训练依赖。模板未确定、权重不是精确基座或哈希不一致时拒绝训练。

Qwen 官方的 Axolotl 文档明确提供 Qwen3 的 SFT、LoRA/QLoRA 方案；这证明可采用的训练方法，不证明当前自定义 tag 可直接用那些示例模型替换。来源：[Qwen Axolotl 文档](https://qwen.readthedocs.io/en/latest/training/axolotl.html)。

### 2.1 Qwen3.8-27B 的真实架构与本包的支持边界

2026-11-02 定向复核发现：官方 `Qwen/Qwen3.8-27B` 是原生视觉语言模型，顶层 `model_type=qwen3_5`；官方示例使用 `AutoProcessor` 与 `AutoModelForMultimodalLM`，NVIDIA 的对应模型页列为 `Qwen3_5ForConditionalGeneration`。这仍不等于已证明原机自定义 Ollama tag 就是该仓库的某个确定 revision。来源：[Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen3.8-27B)、[NVIDIA 官方架构页](https://docs.nvidia.com/nemo/automodel/latest/model-coverage/vision-language-models/qwen/Qwen3.8-27B)。

也不能仅凭 VLM 标签断言 `AutoModelForCausalLM` 不支持它。本次实际读取并固定到 Transformers commit `e2e6cc93810bf705ac2ea0eefde4451ea032df42`（2026-11-02），官方源码具备以下三段配套逻辑：

1. `MODEL_FOR_CAUSAL_LM_MAPPING_NAMES` 同时注册 `qwen3_5` 和 `qwen3_5_text` 到 `Qwen3_5ForCausalLM`，其中顶层条目标注为 VLM compatibility。
2. `auto_factory.py` 在 `from_pretrained` 选到文本 class 时，用 `get_text_config()` 提取复合配置中的文本分支。
3. `conversion_mapping.py` 为 `qwen3_5_text` 配置 `PrefixChange(prefix_to_remove="language_model", model_prefix="model")`，把检查点中的 `model.language_model.*` 映射到文本模型的 `model.*`。该文本 class 明确忽略 `model.visual.*` 和 `mtp.*` 的额外权重。加载器仍必须检查语言权重没有缺失、形状不符或未转换。

来源：[固定 causal registry](https://github.com/huggingface/transformers/blob/e2e6cc93810bf705ac2ea0eefde4451ea032df42/src/transformers/models/auto/modeling_auto.py)、[固定 config 抽取逻辑](https://github.com/huggingface/transformers/blob/e2e6cc93810bf705ac2ea0eefde4451ea032df42/src/transformers/models/auto/auto_factory.py)、[固定权重前缀转换](https://github.com/huggingface/transformers/blob/e2e6cc93810bf705ac2ea0eefde4451ea032df42/src/transformers/conversion_mapping.py)、[固定 Qwen3.5 模型实现](https://github.com/huggingface/transformers/blob/e2e6cc93810bf705ac2ea0eefde4451ea032df42/src/transformers/models/qwen3_5/modeling_qwen3_5.py)。

本包因此实现的是**显式选择、提前阻断的纯文本候选加载路径**，没有完成原机27B的加载或训练验收。只有以下两条 route 有代码；任何其他架构、未经核实的旧版本、原生多模态训练路径均停止，不能静默换另一款 Qwen：

| manifest 的 route | 原始 config | 实际训练 class/config | 输出范围 |
|---|---|---|---|
| `qwen3_5_text_compat` | `qwen3_5`，架构 `Qwen3_5ForConditionalGeneration`，保留原 `text_config` | `Qwen3_5ForCausalLM` / `qwen3_5_text`，由官方 loader 抽取并映射 | 纯文本语言分支；不保留视觉能力 |
| `qwen3_5_native_text` | 原始检查点已明确为 `qwen3_5_text` / `Qwen3_5ForCausalLM` | 同一原始文本 class/config | 纯文本；不得通过改写 VLM config 来伪造此输入 |

`training.runtime.validate_model_architecture` 在模型加载前核对 manifest、原 `config.json` 的封存哈希、本机安装包的精确版本，以及该固定提交的8份关键源码 Git blob。它使用 AST 读取本机 causal registry，只读取本机 Safetensors 的头部元数据来检查语言权重命名、层数、embedding/norm/head 与 index 是否一致；不读取 tensor 数据、不导入 Torch、不联网、不下载权重。已量化的检查点配置不走这条路径；QLoRA 只能在后续以精确原始非量化权重加载时另行配置。代码中的源码指纹针对本次已审提交，不是任意版本的兼容声明；其他版本必须先复核源码再更新门禁。

实际加载使用 `output_loading_info=True`，要求返回的 class/config 与选择一致；任意语言 `missing_keys`、`mismatched_keys`、错误消息或未映射语言键均停止。源文件指纹、注册表和权重头检查通过只证明具备候选加载路径，不证明 CUDA/QLoRA 内核、显存、训练稳定性、模型质量或 Ollama 回导兼容。新增9项架构单元测试只检验这些阻断条件，没有模拟实际模型训练。

原机接入应按以下顺序完成：

1. 先通过当前已批准的宿主元数据通道追溯原 Ollama tag 的精确来源，记录不可变 HF revision、tokenizer revision、模板哈希和原始权重哈希。原 GGUF 的 tag、名称相似或模型卡示例不能替代这一步。
2. 检查现有本地原始权重的真实 `config.json`；若是上述复合架构，明确填写 `route=qwen3_5_text_compat`、`auto_class=AutoModelForCausalLM`、`expected_model_class=Qwen3_5ForCausalLM`、`expected_config_model_type=qwen3_5_text`、`text_only=true` 和该已审源码 commit。示例 manifest 保持未知值为空，不代填来源证据。
3. 在已批准的训练环境中准备经过兼容复核的依赖，并记录实际版本；本包不会自动安装该提交或下载模型。纯本机 manifest preflight 必须通过。若源码指纹不同，停止并重新审查该版本的 registry、config 抽取、转换和量化处理，不能修改 manifest 来跳过指纹。
4. 用同一 `build_messages` 的文本输入核对 `AutoTokenizer` 的渲染与原运行模板，尤其是 thinking 开关、generation prompt、EOS 和 JSON completion 边界；先做本机模型加载、一个批次的前向/反向和一个优化步，保存 loss mask、语言权重加载报告与资源峰值。本轮尚未做这些步骤。
5. 纯文本 LoRA 必须合并到同一路径加载的精确基座。合并产物的模型范围是文本分支，不能声称仍是原完整 VLM。随后再验证当前转换器/Ollama 对 `qwen3_5_text` 的支持和最终 GGUF 表达效果；不能把原完整 VLM 的部署兼容性直接挪用过来。

如果实际环境必须保留完整 VLM，或者当前可安装版本没有上述配套转换，原机需另外实现官方 `AutoProcessor` + `AutoModelForMultimodalLM` 路径。本包没有伪造该支持。具体接入工作包括：保持原复合 config，核对纯文本消息经 processor 后与宿主 prompt 的 token 对齐；为 SFT 增加 processor/collator 并逐 token 验证只对 completion 计算 loss；按真实模块名限定语言分支 LoRA、固定视觉分支；为 DPO 分别验证 chosen/rejected 的处理一致性及从同一 SFT 起点克隆的固定 reference；最后按完整复合模型的权重键和配置合并。当前纯文本 adapter 的模块路径不能未经映射检查就合并进完整 VLM。多模态 SFT/DPO、该架构的 MLX 训练和真实27B资源可用性均保留为未完成项。

## 3. 当前依赖与两个训练平台

### CUDA 路径：已完成脚本

API 固定到 TRL `1.17.1`。官方 tag 解引用为 commit `44809ba3f3a136f3d62859ee981fee2506bce5c9`；运行时核对精确版本，不使用浮动 `main`。

`requirements-cuda.in` 是候选依赖约束，不冒充已经跑过的完整 lockfile。Torch、Transformers、PEFT、datasets、accelerate 和 bitsandbytes 的实际版本，须在训练机按实际 CUDA/架构兼容性解析后记录到模型 manifest。运行时逐项检查精确版本。PEFT 至少 0.20，避免特定 LoRA target_parameters 条件下退回基座参考模型。

来源：[TRL 1.17.1 release](https://github.com/huggingface/trl/releases/tag/v1.17.1)、[固定 pyproject](https://github.com/huggingface/trl/blob/44809ba3f3a136f3d62859ee981fee2506bce5c9/pyproject.toml)。

### Apple Silicon 路径：官方 MLX SFT 准备

MLX-LM 官方提供 LoRA/QLoRA、`--mask-prompt`、梯度累积和梯度检查点。`export_mlx.py` 把已审核的统一消息数据导出成 MLX `messages`，生成含 `--mask-prompt` 的候选命令；不自动转换权重，也不默认原27B架构兼容。Studio 上须先核对精确 MLX 版本、模型加载、tokenizer、一条样本的 loss mask 和峰值统一内存。

MLX 数据导出默认用 gold；显式配置实验银标时复用同一套 silver 证据核验，并在候选运行计划中保留 quality tier 与 experimental_only。导出计划始终标记 architecture_verified=false；本包的 Transformers 文本兼容检查不能代替 MLX 架构验收。

本轮没有从 MLX-LM 官方文档确认内置 DPO 命令。因此不编造 `mlx_lm.dpo`，也不把第三方 `mlx-lm-lora` 当官方等价替代。DPO 的可执行入口在本包 CUDA/TRL 路径。若只有 Mac，可先做官方 MLX SFT 与效果评测，再决定是否值得准备 CUDA 训练资源。

来源：[MLX-LM 官方 LoRA 文档](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md)。

## 4. SFT 实现细节

`train_sft.py` 默认只接受人工认可的 gold 数据；配置明确 `quality_tier=experimental_silver` 且 `experimental_only=true` 时，才接受通过银标证据复核的 conversational `prompt/completion` 数据。两条路线都必须对齐运行时。`completion_only_loss=True`；旧对话与宿主事实作为条件，不作为需要模仿的预测目标。关闭 packing，先减少首轮 mask 与长度问题。训练前用精确 tokenizer 检查完整输入长度与 chat template 前缀一致性，超长样本退出并要求重新分配上下文，禁止截掉条件或事实继续训。Trainer 构建后再逐 token 核对实际 prompt 的 labels 为 -100、completion 未被误屏蔽。

候选试验参数：LoRA rank 16、alpha 32、batch 1、梯度累积16、长度2048、1 epoch、学习率5e-5。它们只是首轮实验起点，不能写成这个27B模型的最优值。目标层由真实架构检查后填写，脚本不猜 `q_proj/v_proj`。先以少量正式合格样本跑短训练、观察显存与损失，再开展整批。样本很少时，不通过增加很多 epoch 来制造“训练充分”。

来源：[TRL SFT 官方说明](https://huggingface.co/docs/trl/sft_trainer)、[固定 SFTConfig](https://github.com/huggingface/trl/blob/44809ba3f3a136f3d62859ee981fee2506bce5c9/trl/trainer/sft_config.py)。

## 5. DPO 最容易出错的地方：参考模型

本轮设计为：policy 从上一阶段 SFT adapter 出发；reference 固定为同一 SFT 起点。若错误地关闭 SFT adapter 使用原始基座当 reference，优化约束就改变了，不能仍称同一训练方案。

TRL 1.17.1 已经与旧版 `model_adapter_name/ref_adapter_name` 示例不同。本包先用 `PeftModel.from_pretrained(..., adapter_name='default', is_trainable=True)` 加载已完成 SFT adapter，再交给 DPOTrainer；固定版本会创建名为 `ref` 的副本。代码检查：ref 必须存在、与 SFT policy 初值逐参数相等、存储不同、不可训练、不在 optimizer 参数组中；训练结束后 ref 哈希仍一致。任一项不符则失败，不退回 base。`sync_ref_model=False`。

候选试验参数：sigmoid DPO、beta 0.1、学习率5e-6、1 epoch。若自然度没有胜过 SFT-only，不保留 DPO 作为必经步骤。保存时仅导出优化后的 default adapter，reference 不能被误拿去服务。

来源：[固定 DPOTrainer 源码](https://github.com/huggingface/trl/blob/44809ba3f3a136f3d62859ee981fee2506bce5c9/trl/trainer/dpo_trainer.py)、[TRL DPO 文档](https://huggingface.co/docs/trl/dpo_trainer)。

## 6. 从训练到 Ollama

截至本次实际读取，官方 Ollama import 页列的是完整 Safetensors 和 GGUF 模型导入，已不再列旧文档中的 ADAPTER 流程。因此本包不把 `FROM 原tag + ADAPTER` 写成可直接用的当前步骤。

`merge_adapter.py` 验证训练记录与精确基座对应后，在独立目录把 LoRA 合并到原始非量化权重；输出 merged Safetensors 和 merge record。然后由真实环境核对原 Ollama 版本与架构支持，必要时在已核实的 llama.cpp 转换器中转换/量化。GGUF 导入本身不会替代预先量化。任何转换后的产物都要重新评测 JSON 合规、事实不变、自然度和延迟；不能沿用训练前的成绩。

来源：[Ollama 当前官方模型导入文档](https://docs.ollama.com/import)。

## 7. 首轮实验与判断

建议先确定原则并修正一小批场景，以约24–60条人审示范建立 gold 锚点，再试做约300–800条合成候选的机器筛查，合格 silver 数据先跑隔离 SFT 实验；这些只是试验规模，不是通用最低数据量要求。DPO 等积累足够真实人工偏好再决定是否尝试，不把机器偏好换名为人工数据。按场景家族先拆 train/dev/独立评测，再扩写姓名、日期、项目、语气变体；同一根场景衍生不得跨集合。48项旧盲评只用于校准；gold 锚点仅取 train/calibration，不能吸收 dev/test 答案。

比较原 Qwen、同基座加强提示词、SFT、SFT+DPO、Codex CLI 参考输出。所有分组共享相同输入快照、事实条件、停止预算和评价口径。看可直接采用率、自然度、严重事实错误、补问必要性、执行状态错误和延迟分布；训练 loss、DPO reward margin 仅用于诊断，不能替代业务效果。先评原浮点/adapter，再评量化部署产物，区分两次误差来源。

每次训练输出 `preflight.json`、Trainer state、训练/验证指标及 `training_record.json`。`training_completed=true` 只表示训练脚本完成，`business_acceptance` 始终保持 false，直到独立真人验收另有证据。新训练产物不自动更新 AM 开关。

## 8. Codex 执行命令

在交付根目录，先做纯本机元数据检查：

```bash
python -m training.preflight --output runs/preflight-machine.json
python -m training.preflight --inspect-local-model /actual/local/model --output runs/preflight-model.json
```

第二条路径由真实环境填写，不下载模型。若已核对来源，需要完整权重哈希时显式加 `--hash-weights`。将结果与原模型来源映射证据整理进 model manifest；不要仅把检查输出复制成“已确认”。

填好 manifest、训练文件哈希和配置后：

```bash
python -m training.train_sft --manifest runs/model_manifest.json --config runs/sft.json
python -m training.train_sft --manifest runs/model_manifest.json --config runs/sft.json --execute
python -m training.train_dpo --manifest runs/model_manifest.json --config runs/dpo.json --sft-adapter runs/sft-pilot-001
python -m training.train_dpo --manifest runs/model_manifest.json --config runs/dpo.json --sft-adapter runs/sft-pilot-001 --execute
```

默认不带 `--execute` 的两类入口只核验输入。执行也只读取已存在的本机权重；`local_files_only=True` 不自动访问模型Hub。MLX 仅导出：

preflight 的 manifest 检查、SFT/DPO 的默认 dry-run 和 merge 入口都执行架构核验。merge 实际加载同样检查完整 loading_info，记录文本产物范围；不会绕过训练时的权重转换检查。

```bash
python -m training.export_mlx --manifest runs/model_manifest.json --config runs/sft.json --output runs/mlx-sft-data
```

这里的本轮环境为Linux，未安装Torch、TRL、Transformers、PEFT、MLX。训练相关检查包含22项训练契约、9项架构检查及8项silver流程检查；整包最终结果以 evidence/local-verification.json 为准。另已完成SFT/DPO导出与训练校验器的夹具互验。未做GPU导入、模型加载、短步训练、量化、真实Qwen或真人效果测试。`environment_observed.json`只记录本轮检查环境，不代表用户Mac Studio配置。
