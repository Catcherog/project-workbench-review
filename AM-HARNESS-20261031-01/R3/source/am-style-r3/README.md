# R3 原机接入版

运行源码位于 `../am-conversation-r1/src/am_style`。下文及 docs/ 保留收到的设计说明，其初始“未接入、未训练”状态不代表原机本轮结果；本轮实际状态以 `../AM-HARNESS-20261031-01/R3/00_当前交接.md` 为准。

本目录命令须设置 `PYTHONPATH=../am-conversation-r1/src:.`。原始评分属私有校准材料，公开复跑会跳过其专用检查；本机通过 `AM_R3_INPUT_DIR` 指向原包 data/input 可执行该项。

# AM-HARNESS-20261031-01 / R3

**末端拟人化表达、Qwen/Codex 对照、合成数据与 SFT/DPO 准备。**

需求版本 v3.0-design.1；日期 2026-11-02，Asia/Shanghai。

本包包含独立表达核心、原 AM 接入接口、标注处理、模型对照入口、训练入口及检查。尚未安装到 Studio，不包含训练后的模型权重。

## 先读

1. [当前交接](00_当前交接.md)：执行顺序、有效基线、已完成与待完成。
2. [框架与输出原则](docs/architecture.md)：为何先改表达合同、末端节点、数据与评测。
3. [原标注分析](docs/annotation_analysis.md)：48条评分、原始配对缺口和数据界限。
4. [训练方案](docs/training_research.md)：模型身份、SFT/DPO、MLX/CUDA与官方依据。
5. [原 AM 接入](docs/integration.md)：共享预算、唯一消费者、守卫和真实回执。
6. [合成数据实验](docs/silver_training.md)：小批人审校准、双模型筛查和隔离银标 SFT。

## 边界

- 原 Qwen、唯一消费者、600秒身份及 ledger_write=false 保留；本包没有改动 response=legacy、旧重写 off、goal_tracking=false。
- 表达核心默认 mode=off。shadow 记录候选并保留旧输出；enforce 是测试和未来受控采用能力，本地检查不能替代启用验收。
- 现有语义语法能验证已支持的主谓改写、结果合并、追问和排版；任意自由表达尚无通用正确性证明。
- 语义通过、语言像人、业务已投递分别记录。
- 原盲评 A/B 文本和随机 key 留在本机。当前 SFT/DPO 正式训练文件保持为空；26条新虚构样本仍未审核。
- CUDA/TRL 的已实现加载路径仅覆盖经版本和权重映射核对的 Qwen3.5 架构文本分支。它不保留完整 VLM 视觉能力；原27B实际加载、训练、MLX兼容与Ollama回导均须另验。

## 本地运行

核心需要 Python 3.11+ 标准库，不安装 Torch/TRL 即可：

~~~bash
python -m unittest discover -s tests -v
python scripts/demo_expression.py
python scripts/build_data.py --help
python -m training.preflight --help
python scripts/run_model_comparison.py --help
~~~

demo 使用明确标记的 fixture，没有真实模型调用。可选训练依赖在 training/requirements-cuda.in；缺少基座或审核数据时训练正确阻断，不会下载模型补位。

## 代码导航

| 模块 | 能力 |
| --- | --- |
| am_style/contracts.py | 冻结合同、作用域和版本绑定 |
| am_style/render.py | 自然宿主兜底、事实、缺口、动作状态及独立结果合并 |
| am_style/prompt.py | 推理、合成、训练共用消息构建；bounded/free实验模式 |
| am_style/verify.py | 有边界的语义组合、精确人审绑定、未知拒绝自动采用 |
| am_style/runtime.py | 一次末端调用、共享预算、调用前后及发送前检查 |
| am_style/integration.py | 原 _finish/gateway 接口；不执行业务或发送 |
| am_style/providers.py | 原协调器回调、隔离 Ollama、受限 Codex CLI |
| am_style/evaluation.py | 固定分母，区分生成、通过、采用、投递、人评和耗时 |
| am_style/data.py / synthetic.py | 标注绑定、数据溯源、人审、分组与训练导出 |
| am_style/silver.py | 小批人审锚点、真实双模型评审、实验银标 SFT；保留弱监督身份 |
| training/ | 环境/模型核对、SFT、固定参考DPO、MLX导出和adapter合并 |

原 AM 按当前工作树增量接入；不要用审核副本覆盖原工作树、配置、数据库或后续有效改动。
