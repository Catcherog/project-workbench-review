# AM Harness 框架与表达设计包

任务：AM-HARNESS-20261031-01 / R2-DESIGN  
版本：v2.0-design.1 · 2026-10-31（Asia/Shanghai）

## 阅读顺序

1. `INPUT_BASELINE.md`：用户原文、固定版本、继承与替代关系。
2. `AM-Harness-Framework-and-Expression-Design.md`：完整研究、架构、状态、数据、代码接线、性能与验收设计。
3. `HOST_ADAPTER_SPEC.md`：Python 参考与真实工程的映射及待完成端口。
4. `CODEX_HANDOFF.md`：实施与验证交接。
5. `VALIDATION.md`：本包已经做过和没有做过的检查。

## 可直接检查的设计材料

- `reference/response_reference/`：标准库 Python 参考，含 26 项纯协议测试。模型、权限、语义评估、业务渲染、数据库和投递端口未接生产。
- `schema/response_plan.schema.json`：宿主的规范 JSON Schema，供应商可能只支持子集，需适配并保留完整本地校验。
- `schema/migration_reference.sql`：会话侧和 gateway 侧分离的 DDL 草案，不可整份直接应用生产。
- `topology.json` / `target-topology.mmd`：13 个职责节点、21 条条件边；描述目标设计，未声称现系统已有此图执行器。
- `prompts/`：自然表达与工具选择规则。
- `evals/acceptance_seed.jsonl`：48 条合成验收种子，12 组各 4 条；产品测试尚未执行。
- `research/`：固定源码定向核对、官方来源索引、协议复审与源码指纹。

## 运行参考检查

在解压后的本目录执行；不安装模型 SDK，不需要 API key：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=reference python3 -m unittest response_reference.test_reference -v
```

测试中的 Assessor/Guard/Model/HostRenderer 是 fixture，不可用于生产。通过只证明局部控制流合同符合断言；不证明中文语义、真实权限、模型停止、实际动作或投递。

## 验收种子分组与代码枚举

种子的 family 是便于人工验收的产品分组，不是要求机械填入一个 Enum。query 映射 READ，multi_source_analysis 映射 ANALYZE，worknote 映射 NOTE，knowledge_candidate 映射 KNOWLEDGE，preview_confirmation 映射 PREVIEW，outbound_mount 映射相应 DOCUMENT/EXECUTION_RECEIPT，reminder_plan 映射 SCHEDULE。partial_completion 应保留真实业务 family 并设置各 WorkUnit 的 partial/failed 等状态；failure_unknown 根据当前事实分别映射 FAILURE/UNKNOWN。混合任务逐工作单元保留原业务类型。

最终指标按真实 task_family、策略和状态分层，不因验收分组便利而把失败移出原业务任务的分母。

## 实施基线

固定 FIX1 审核：`cd35c28d4524284b52e77763784ac4c2d15cd3e4`；报告对应源码：`d3e40b0d27517d75e850613c4eaecec107efa0ea`。实施前核对真实当前树及后续修改，保留原模型、唯一消费者、600 秒身份、台账写入关闭和 FIX1 行为。

