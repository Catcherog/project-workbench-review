# AM 多 AI 网关开发包

当前候选为 AM-GROK-REALTIME-20261105-01 / R3，版本 0.3.0，2026-11-06。唯一当前交接见 [R3 交接](../../00_当前交接.md)，有效基线及复审落实见 [phase1 文档](docs/phase1/01_有效执行基线.md)。Grok Bot 领取、回传及记忆边界未接通，生产激活被拒绝；本轮不切换 Grok CLI。

以下保留 R2 兼容部分的阅读和运行说明。其“全量采集接口”等是接口设计，不能当作实际覆盖或 R3 的启用范围；新候选使用 `src/am_gateway/phase1`，旧 Router 与新 Harness 不得对同一数据库同时受理任务。

## 开始阅读

1. ../../00_当前交接.md：R3 本轮范围、状态及接续；本目录旧 00 文件仅保留 R2 来源记录。
2. docs/01_架构设计.md：详细设计。
3. docs/02_原机验收与接续.md：原机接线与验收。
4. integration/README.md：Bridge 端口。
5. examples/worker_contract_r2.md：执行端协议。

## 本地验证

运行时使用 Python 3.11+ 标准库。测试另需 pytest。宿主飞书 SDK 和 CLI 由原环境提供。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pytest
PYTHONPATH=src .venv/bin/python -m pytest -q
python3 tools/verify_delivery.py
PYTHONPATH=src python3 tools/run_r2_demo.py
```

演示使用本地替身，不接入 Grok 或飞书。演示毫秒数不代表手机端实际时延。

## 原机诊断

```bash
PYTHONPATH=src python3 -m am_gateway metrics --db /actual/gateway.sqlite
PYTHONPATH=src python3 -m am_gateway jobs --db /actual/gateway.sqlite
PYTHONPATH=src python3 -m am_gateway outbox --db /actual/gateway.sqlite
PYTHONPATH=src python3 -m am_gateway coverage --db /actual/gateway.sqlite
```

诊断只读指定的现有数据库。输出可能包含业务原文，审核回传须按必要范围脱敏。

## 源码

| 路径 | 用途 |
| --- | --- |
| src/am_gateway | 本轮 R2 实现 |
| integration/am_multi_ai_host.py | 入站、审核编辑、原发送器及内部状态投影 |
| integration/r2_runtime.py | 真实宿主端口装配，不创建长连接 |
| tools/patch_bridge_r2.py | 生成局部候选及差异，不改输入文件 |
| tests/r2 | 本轮场景及独立检查 |
| verification | 交付版本验证证据 |
| src/am_grok_gateway 与原 tests/test_*.py | 保留的 R1 兼容实现及测试；R2 服务不调用它 |

R1 和 R2 只选择一个接管同一消息的回复。已运行 R1 时先核对待回包和未知发送、导入完成收据、移除旧钩子。不要同时启动两个回复通道。

实际 Studio 版本、Grok Bot 实时入口、全会话发现、业务资源、真实发送和手机体验由 Codex 在原机绑定并验收。开发验证详见 verification/results.json。
