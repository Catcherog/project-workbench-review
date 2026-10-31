# 本设计包的实际验证记录

日期：2026-10-31（Asia/Shanghai）。这是设计参考验证，不是新机器人版本验收。

## 已完成

| 检查 | 实际结果 | 适用边界 |
|---|---|---|
| FIX1 定向远端材料 | 入口、说明、差异、12 个运行源码，共 15 个对象 Git blob SHA 一致 | 静态设计依据；未独立复验 158 个实际加载文件 |
| Python 参考合同 | 26 通过，0 失败，0 跳过；一次最终打包副本完整运行约 0.006 秒 | 使用 fixture；未调用真实模型/业务/DB/outbox |
| Python 语法 | 7 个 Python 文件 AST 解析通过 | 不是生产集成 |
| 验收种子 | 48 条，12 组各 4；JSONL 可解析、case_id 唯一 | 全部合成；产品场景执行数为 0 |
| 节点与边 | 13 个唯一节点、21 条边，端点均存在 | 目标设计目录；不是运行图覆盖率 |
| DDL 草案 | 会话与 gateway 两部分分别在空内存 SQLite 成功解析 | 未应用真实数据库；不是 migration/回滚验证 |
| JSON Schema | JSON 解析完成；本机未提供 jsonschema 元校验库 | 不宣称已完成 Draft2020-12 元校验或供应商 schema 实测 |

完整参考测试命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=reference python3 -m unittest response_reference.test_reference -v
```

原始结果见 `reference_checks.txt`；其他设计检查摘要见 `design_checks.json`。

## 定向复核发现并修正的风险

- 必须把另一项任务的 failed/unknown、receipt、重要 gap 绑定为 required host block，防止提案通过 claim 检查却遗漏失败项。
- canonical 路径也检查保护块顺序。
- durable expression 路由必须有 RunBinding，不能用 EventBinding 假装进入真实调度。
- 候选 intent 为数组/对象时返回 PlanError，不能泄漏 TypeError 破坏降级。
- 增加 SCHEDULE 任务族，保留原计划批准/预览/回执语义。
- 提案绑定前冻结完成度；状态变化生成新 Outcome hash，不能事后给旧提案补 hash。
- 查询缺口解释不能被计为用户目标已经 fulfilled；配对盲评含平局/不合格分母。

一个测试刻意证明：合法 claim 引用可以附着于错误语句，机械校验仍可能通过。因此语义等价证明字段始终为 False；缺少合格语义 profile 时不采用自由候选。

## 明确未完成

真实工程适配与安装、原 Qwen 自由表达效果、完整宿主集成回归、真实数据库迁移、业务工具路由/执行、飞书发送和独立回读、性能目标、精确依赖启用、手机、独立真人、正式业务及生产回退演练。

本轮没有改机器人、改变表达模式、向外发送业务消息或写入 GitHub。Codex 应按交接完成后续验证，保留每一层证据的真实状态。

