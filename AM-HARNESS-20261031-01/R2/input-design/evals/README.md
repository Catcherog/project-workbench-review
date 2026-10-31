# 合成验收种子说明

`acceptance_seed.jsonl` 含48条声明式用例，12个任务族各4条。全部项目、人名、对象、时间和回执均为合成fixture，不能作为真实资料或实际授权使用。本轮只检查JSONL形状、字段、唯一ID、任务族分布；产品测试执行数为0。

## 用途与边界

用例描述输入状态、证据/回执和预期行为，供Codex在真实工程补齐fixture adapter、执行观察与断言。它不是可直接运行的测试，不含预设必须逐字相同的回复，也不能证明业务拟人化通过。

确定性验证可以检查对象类型、版本、scope、回执、状态变化、工具调用次数、重复副作用、授权/来源拒绝和发送正文来源。语言验证应检查命题、关系、否定、模态、范围和完成状态是否保真。自然度由配对盲评判断清楚程度、是否贴合本轮关注点、多轮承接和可读性；不使用字符串相等作为自然表达验收。

同一用例可以分别使用legacy、canonical、shadow、enforce运行；必须保存真实输出来源。canonical和fallback的正确回答可计入各自体验指标，不能进入LLM采用或生成改善分子。所有候选因indeterminate回退，意味着该生成路径尚未通过验收。

## 任务族

| family | 任务 | 数量 |
|---|---|---:|
| query | 人员/进展/日期/待办查询 | 4 |
| multi_source_analysis | 多来源分析、冲突、撤权和判断更新 | 4 |
| followup | 正确跟进对象、缺参、取消与结案 | 4 |
| worknote | 内部笔记、对象歧义、未知提交与更正 | 4 |
| knowledge_candidate | 候选、适用范围、拒绝与精确批准 | 4 |
| document | 草稿、缺项、取消与采用hash失效 | 4 |
| preview_confirmation | 完整预览、目标核实、取消与修改后再确认 | 4 |
| outbound_mount | 已核发送、挂载缺项、未知对账与多轮挂载 | 4 |
| reminder_plan | 持久计划、时刻缺失、未知阻塞和恢复 | 4 |
| correction_cancel | 停止、目标歧义、已提交部分和项目纠正 | 4 |
| partial_completion | 逐目标结果、分页缺口、部分未知和续接 | 4 |
| failure_unknown | 有界安全重试、负向查询、停止未知和重新授权读取 | 4 |

本种子集不声称穷尽所有出口。正式接线矩阵还应补充业务实际可达的卡片、维护、任务过期、异常、平台payload转换和真实手机流程。每个任务族开放前仍需足够独立样本、真实原模型输出、反例以及用户评审。

## 字段

- `case_id`：稳定合成ID。
- `family`：任务族。
- `intent`：用户需求或跨轮简述。
- `starting_state`：起始对象、身份与状态；`fixture_kind=synthetic_only`。
- `evidence_or_receipt`：用例给定的合成事实、缺口、版本、回执或不确定结果。
- `expected_behavior`：必须满足的任务和表达语义。
- `forbidden_behavior`：须拦截或判失败的行为。
- `verification_layer`：建议负责验证的层，不是已取得的验证结果。

`build_acceptance_seed.py` 仅从内嵌合成数据写出JSONL并做格式断言，可复现种子文件；不连接模型、业务存储或外部服务。
