# AM 表达与训练闭环 · R5

本包把 R4 已验证的训练机制接到可执行的样本准备、人工反馈、gold 快照、pilot、三组生成和盲评流程。GPT 完成架构和代码；Codex 在原机完成实际训练、真实推理、宿主验证及证据回传。

**当前交付：可运行的代码、22 条待评草案、离线验证及完整执行交接。真实 gold 仍为 train 9 / dev 1；本包没有执行训练、调用真实模型或取得新增人工认可。**

## 从这里开始

| 文件 | 内容 |
| --- | --- |
| `00_当前交接.md` | 任务、版本、实际完成状态和仍需 Codex 完成的事项 |
| `docs/01_architecture.md` | 模块边界、数据流、接口、状态、训练及评测设计 |
| `docs/02_data_contract.md` | 分组、完整文本人评、改稿失效、训练快照 |
| `docs/03_training_contract.md` | 原 mechanics 绑定、实际 pilot 门禁和执行参数 |
| `docs/04_evaluation_contract.md` | 三组比较、独立测试、原始工件、盲评与报告 |
| `docs/05_codex_execution.md` | Codex 按顺序执行的命令、停止条件及回传要求 |
| `examples/prepared/review.md` | 22 条可直接阅读的待评答复 |
| `examples/demo/report.md` | 明确标注为 fixture 的报告示例 |
| `verification/summary.json` | 本包实际离线验证结果；不代表训练或效果验收 |

## 离线运行

准备与检查只需 Python 3.11 或更新版本及标准库。使用包内已经固定来源的 R4 Python 模块，不需要安装依赖、联网、下载权重或启动服务。

从解压目录执行，输出目录必须尚不存在：

```bash
python run.py prepare --output /tmp/am-r5-prepared-001
python run.py demo --output /tmp/am-r5-demo-001
python verify.py --output /tmp/am-r5-check-001
python run.py --help
```

`prepare` 生成 15 条 train 草案、7 条 dev 草案及全 pending 反馈；当前快照保持旧 9/1。`demo` 用 3 个开发场景、3 个模型位置形成 9 条计划结果，故意留 1 条缺失，验证报告不会删掉失败分母；8 条文本来自明确的程序夹具，人工标签仍为空。

`run.py` 使用绝对导入根，可从其他工作目录调用。实际训练仍须选择原机已有的 Apple Silicon / MLX 环境和原始 R4 证据。`pilot-execute`、`eval-qwen`、`eval-mlx` 必须带 `--execute` 才会执行；其他命令准备文件或读取元数据。

## 原工程接入

新增代码位于 `src/am_style_r5`，不向现有生产入口插入调用。`baseline/` 是有逐文件来源的已审依赖快照，用于离线运行和显式选择的隔离实验。它不应覆盖原机最新工程。

原机定位真实路径后，可以显式选择现有源码：

```bash
export AM_R5_HOST_SRC="/absolute/current-project/am-conversation-r1/src"
export AM_R5_TRAINING_ROOT="/absolute/current-project/am-style-r3"
```

`pilot-plan` 还要求传入 `--host-src` 与 `--training-root` 以保存所选执行根。相关代码与固定 R4 版本不一致时会报告差异，必须保留较新宿主代码并审查，不会自动回滚它。

## 交付边界

固定审核：`0641a282584a68f60ddaf198326fc431ba67ee13`。固定源提交：`9255a70154ca82c0b9e2c0dbdb14a90cf94cbbde`。`baseline/PROVENANCE.json` 给出实际使用的 R3/R4 文件来源与 SHA256。

生产开关、原 Q8、唯一消费者、身份 600、`ledger_write=false`、legacy 响应通道、rewrite 关闭、goal tracking 关闭、terminal expression 关闭继续沿用原值。包内没有部署、自动开关、合并 adapter、替换生产权重或发送业务消息的命令。

Codex 隔离、silver、DPO 各自保留未完成状态。无独立人评的 JSON 成功、NLL 下降、参数更新或保存重载，均不构成自然度改善或业务验收。
