# AM-FOLLOWUP-20261102-01 / R1

基于现有 AM 的待办、项目进展与一次确认跟进设计及可运行参考代码。

**状态：已完成详细架构、核心代码和157项合成检查；未接入用户本机原AM，未发送真实飞书消息。** 实际原AM接线、Qwen抽取、权限、群@/工程师私聊、手机及业务验收由Codex按当前交接完成。

## 阅读顺序

1. `DESIGN_HANDOFF.md`：本轮目标、版本、实际结果与Codex指令。
2. `docs/01_architecture.md`：完整产品与技术方案。
3. `docs/02_integration.md`：已实读原源码复用点、准确接线位置与风险。
4. `docs/03_acceptance.md`：原环境场景、证据和通过条件。
5. `docs/evidence_api.md`、`docs/followup_api.md`：核心API。
6. `docs/independent_review.md`：本轮独立检查与修正。

## 直接运行

运行时无第三方依赖，Python 3.11+（需系统IANA时区数据库；本轮Python 3.12.14）。在解压后的目录中：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPATH=src python3 examples/demo.py
python3 scripts/verify.py
```

演示只创建临时SQLite，使用合成身份、策略和发送端口。没有网络调用，没有配置凭据，没有后台任务。`scripts/verify.py`将测试与演示结果、受测源码指纹写入`verification/`，并返回真实退出码。

若选择安装，`python3 -m pip install -e .`使用setuptools构建；它不是运行以上命令的前置。

## 模块

| 模块 | 职责 |
| --- | --- |
| `evidence.py` | 不可变证据、候选、语义投影、覆盖、水位、冲突与受审恢复 |
| `identity.py` | 稳定业务身份和跨生产者事项别名 |
| `rendering.py` | 有依据的有限问询文案与code-owned @ |
| `followup.py` | 一次精确批准、统一注意对象去重、unknown屏障、停止与发送端口 |
| `bridges.py` | 证据快照、完整正文和披露范围、实时策略核验 |
| `confirmation.py` | 原已送达预览与真实回调绑定、一次批量确认 |
| `transport_contract.py` | 原BusinessPort可复用的请求结构与回读验证 |

## 实施约束

复用原FactEngine、ActionItems、Scheduler和发送器，不另开长连接、定时器或群发送客户端。原Qwen、唯一消费者、600秒查询身份、禁台账写入及未验收表达/目标跟踪开关保留。

包内证据SQLite是可移植领域规则的隔离实现，生产不得借此建立第二份权威事项。准入表不独立发消息。真实适配器必须把intent/request UUID映射到原action，且在真正网络调用前串接新旧守卫。

“原guard可重复调用”与“新before_send只调用一次”不同，详见接入文档。测试中的全通过gate、假目录、fake sender、合成密钥不能用于生产。

## 材料与隐私

所有可运行示例与测试均为脱敏合成数据。原始上传评估、真实业务消息、人名、原文附件与凭据不复制进代码包。仅保留输入文件校验值及固定审核源码引用。公开审核回传前，Codex仍要检查实际新增日志、截图、消息定位和原件；不能把真实验证资料原样公开。

