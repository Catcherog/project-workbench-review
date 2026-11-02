# R5 真实训练接续合同

## 本轮推进到哪里

R5 把“新增反馈已入库”接到“能启动的受控 pilot”，复用 R4 的训练器、数值补丁、原协调锁、资源检查与新进程回载。准备和预检不会启动模型；只有显式执行命令才进入原trainer或生成worker。接口不会安装依赖、下载模型、创建消费者或改变生产配置。生成执行参数也不等于已经训练。

固定接续依据是审核提交 `0641a282584a68f60ddaf198326fc431ba67ee13` 中的 R4。其 mechanics-002 实际使用旧 R3 train1/dev1 完成一步；R4 新增8条反馈未参加该步更新。R5 首次 pilot 才会使用新增认可与原9/1合并后的完整数据。

## 数据、版本与数量

训练输入只能来自 `dataset.export_gold_snapshot()` 生成并经 `verify_gold_snapshot()` 回读的快照。快照携带原反馈文件、完整候选上下文、场景组注册表、逐文件SHA、原R4数据前缀与新追加行。执行前重放 R4 的人工标签导入，不能只写 `human_approved=true` 或篡改统计字段补足数量。

| 项目 | 固定要求 |
| --- | --- |
| 继承数据 | R4 9条train、1条dev原始字节作前缀；旧R3 1/1随此前缀保留 |
| 首次pilot数量 | train24–48、dev8–16；训练/验证场景组至少8/4且不交叉 |
| 目前真实数据 | 仍为9/1；新增草案均待审，测试中的合成标签不计入真实数量 |
| 补足最低门槛 | 至少再认可15条train、7条dev；验证至少新增3个场景组 |
| 旧dev | 不进入训练、gold anchor；不移动或复制来凑数 |
| 同组衍生 | 固定在同一split；实体替换和改写不能制造跨组独立证据 |
| 风格合同 | 沿用`muyi-style/3.0-draft.1`；R5批次标记放批次字段 |
| 独立效果测试 | 已展示的新校准资料不能再称为盲测；另采未暴露场景组 |

旧gold绑定旧policy和native prompt。若真的修改policy或prompt构造器，不能只重标旧行的版本号，必须重新对齐、核验并取得对应完整文本认可。本轮首次pilot不进行这种迁移。

## 如何绑定实际 mechanics

`pilot.py`固定接受R4 mechanics-002的原始`result.json`：

`bf4ac5775e61e9626fb92460a49b197045a4b2d310090e70a39257e9dda6d7b6`

该值直接取自固定R4的`EVIDENCE_SHA256.json`，其中此文件的`original_sha256`和`audit_sha256`相同。随后必须在同目录找到并核对`request.json`、`fit.json`、`reload.json`、`kernel-validation.json`、`steps.json`、`adapters.safetensors`、`adapter_config.json`，并由原`validate_mechanics_gate()`再次验证完整关联。

**公开审核包不能代替原机训练材料。**其request中的本机路径经过脱敏，原始request文件SHA为`de7afd3237f83676bf16111b0768a778dd51c74505360606b3bba7d443d0f024`，公开副本为`537fb821a40e78c95f11991cad3bf49bf0e2b8fad3637bc0868be82b01f9d125`；adapter权重也不在公开包中。不能手改路径或哈希让公开副本通过。

传入的manifest必须与该实际request中的manifest完全一致，指向已核验的官方独立4-bit文本基线。它与生产Q8上游快照的等价性仍未证明，训练结果不能直接归为生产Q8效果。

若真实最新宿主已经修改相关训练实现，先保存当前提交与差异，判断旧mechanics是否仍适用；如需重新运行mechanics，要记录新的真实证据及复审选择。不要覆盖后续代码，也不要修改本包的固定哈希来绕过这一判断。

## 真实执行端接口

调用前将本包`src`、所选宿主的`am_style`父目录及`training`父目录加入Python搜索路径。执行端优先选择原工程的最新真实路径，并核对本轮相关文件。示例中的路径需要用原机实读结果替换；它们不是可直接执行的原机凭据。

```python
from am_style_r5.pilot import prepare_pilot, preflight_pilot, execution_argv

prepared = prepare_pilot(
    snapshot_path="/absolute/new-gold-snapshot/snapshot.json",
    mechanics_result_path="/absolute/original-mlx-mechanics-002/result.json",
    manifest_path="/absolute/original-base-manifest.json",
    output_dir="/absolute/r5-runs/pilot-plan-001",  # 必须尚不存在
    python_executable="/absolute/existing-mlx-venv/bin/python",
    runtime_source_roots={
        "training": "/absolute/current-am/am-style-r3",
        "am_style": "/absolute/current-am/am-conversation-r1/src",
    },
)
plan_path = prepared["plan_path"]
report = preflight_pilot(plan_path)
# report不代表已取得资源锁或已加载模型；失败时保留具体阻塞项。
command = execution_argv(plan_path)  # 内部重新预检；未通过则抛出R5Error
```

未传`runtime_source_roots`时，使用包内固定R4源码，计划明确标为`bundled_r4_optional_isolated_runtime`，仅作为离线复现或明确选择的隔离运行依据。它不会自动替换原服务。显式传入host路径时，检查实际训练所需的11份代码与固定来源；遇到差异直接报告并保留原文件。

`execution_argv()`返回结构化对象：`argv`、`cwd`、`env`（覆盖项）、`shell=false`，不会启动进程。Codex在已有授权范围内完成原机核验、确认当前空闲窗口后，可明确执行：

```python
import os
import subprocess

env = os.environ.copy()
env.update(command["env"])
completed = subprocess.run(command["argv"], cwd=command["cwd"],
                           env=env, shell=False, check=False)
```

真正启动的仍是原`python -m training.mlx_r4 ... --execute`。执行前重新核对原文件字节；原训练器还会在自己的进程内再次核对数据、源码、模型、锁、资源和生产身份。路径含空格不会经shell重新解释。所选虚拟环境Python路径保留，不能把其符号链接解析为基础Python后丢失环境。

## 原训练配置与运行窗口

R5从原mechanics request复制配置，仅替换训练/验证数据路径与SHA、阶段为`pilot`、梯度累积为4，并绑定原mechanics结果。其余值不得通过R5接口覆盖：一遍数据、seed221、最后2层、LoRA rank8/scale2/dropout0、713472参数、lr1e-5、weight_decay0.01、bias_correction=false、max_length1024、worker300秒。长度超限拒绝，不截断事实；每步最多累积4个不同样本，最后不足4个时沿用原训练器处理。

延续原资源约束：加载前可用内存至少24GiB；运行中至少5GiB；临界内存压力、swap增加超过1GiB、业务任务到来或资源窗口结束时停止；MLX内存上限22GiB。复用原`model-coordinator.lock`，不新建模型服务，不卸载原Qwen，也不自动重试。

fit与reload仍是两个独立进程，fit必须退出并确认停止后才可开始reload。每次使用新目录，禁止覆盖已有训练记录。输出目录不能进入模型快照、原服务状态/配置或输入证据目录。

## 预检与失败行为

预检使用所选Python的新子进程，调用原`validate_plan()`、`validate_mechanics_gate()`和`preflight()`。只读取元数据、数据和已完成mechanics文件，不执行数值kernel，不取得业务协调锁，不导入MLX，不加载模型。真实资源可用性只能由开始训练时的原worker判断。

| 发现的问题 | 行为 |
| --- | --- |
| 仍只有9/1，或验证组不足 | 不生成可启动训练计划，先补认可数据 |
| 修改已审候选、反馈、快照或拆分 | 回读拒绝；完整修订文本重新审核 |
| 只有成功布尔值、mock记录或公开脱敏request | 不接受为原mechanics证明 |
| 实际源文件、Python或manifest改变 | 重新定位差异；旧绿色报告不能放行 |
| 依赖/平台不符合、模型/服务路径缺失 | 输出具体blocked原因，不安装、不下载 |
| 请求目录已存在或进入受保护位置 | 拒绝创建；换新实验目录 |
| 训练中忙碌、内存不足、超时 | 沿用原训练器停止与停止确认，不自动开第二次 |

`plan.json`、`pilot.config.json`和`preflight.json`形成准备记录；`preflight.json`不是可重复使用的执行许可。每次获取执行argv都会重新读取输入并预检，任何旧`ready_for_launch=true`自报字段都不能代替检查。

## 真实验收和回传

执行端分别记录：实际消费的样本ID、优化步数、有限非零梯度、真实参数变化、adapter保存与逐张量回读、fit退出、独立reload进程、回载诊断、峰值内存、资源暂停、源码与环境版本。原trainer返回`mechanics_closed=true`也只表示保存/回载机制完成；pilot自然度还需单独效果评价。

训练比较需要固定相同输入和生成设置。三组为生产Q8参照、同prompt下的MLX base、同基座的gold SFT；报告事实正确性、自然度、可直接采用率及延迟，保留无改善或变差的结果。不得用单条dev NLL代替自然度，不把已暴露的校准样本算作独立效果测试。

Codex隔离、silver、DPO继续各自保留原完成条件。它们未完成不阻断没有依赖关系的gold准备；也不能通过增加训练步数或换模型规避其缺口。生产表达仍关闭，手机、独立人员和真实业务验收分别记录，训练闭环不会授予整体启用。

本包本地故障测试使用临时合成标签验证拒绝路径，真实人工反馈新增数、真实训练次数、真实Qwen/Codex调用数均保持0。测试结果只支持代码和协议的本地验证。
