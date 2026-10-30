# AM 自然对话工作代理 · R1

本包完成了自然对话框架、持久工作上下文、知识学习入口、受控工具执行协议，以及现有 AM 的增量接线补丁。开发目标是让日常沟通逐步接近项目负责人的处理方式，并保留既有项目查询、跟进与反馈能力。

**当前交付是可运行、可验证的开发版本。真实 Qwen 的判断质量、飞书端到端交互和生产部署仍需 Codex 在本机继续完成。**

- 先读：[`00_当前交接.md`](00_当前交接.md)
- 给 Codex 的启动说明：[`START_CODEX.md`](START_CODEX.md)
- 设计与接口：[`ARCHITECTURE.md`](ARCHITECTURE.md)、[`CONTRACT.md`](CONTRACT.md)
- 补充个人工作原则和公司业务知识：[`KNOWLEDGE_GUIDE.md`](KNOWLEDGE_GUIDE.md)
- 实际验证证据：[`evidence/validation.json`](evidence/validation.json)、[`evidence/demo.json`](evidence/demo.json)

## 1. 现在已经实现什么

| 能力 | 已交付的实现 | 当前边界 |
|---|---|---|
| 自然对话入口 | 普通私聊文字进入新的有界工具循环；直接输出文本 | 旧命令、附件和群聊继续原链路；尚未把全部交互改成自然对话 |
| 模型连接 | `CoordinatorModel` 复用原 `gateway.provider` / `ModelCoordinator.complete` | 本轮未连接真实 Qwen；不新增 provider 或第二个飞书消费者 |
| 项目理解与续接 | 授权项目查询、持久话题焦点、对话历史、跨项目工作笔记 | 工作笔记是本会话记录，不改变正式台账或原 `action_items` |
| 业务事实 | 当前状态通过注入的项目端口读取，保留来源与快照信息 | 历史对话不能取代新的业务事实；模型理解效果需要真实场景评价 |
| 个人工作规则 | 规则、案例、风格、业务知识、事实的候选与批准版本 | 没有假定已掌握用户全部习惯；知识导入不等于模型微调 |
| 知识补充 | JSONL 批量导入、dry-run、去重、修订；对话中提出候选并按版本批准 | 暂无附件自动解析与自然语言批量审核界面 |
| 事务执行基础 | 完整预览、修改后确认失效、一次领取执行、结果凭据、取消、unknown 状态 | 生产适配器尚未绑定真实发送/正式写入工具，外部执行开关默认关闭且强制拒绝误开 |
| 原系统兼容 | 两文件补丁；原授权、入站、出站、跟进事项读取与耗时记录继续复用 | 只针对固定 UX3 审阅快照验证；需要在当前 Studio 分支上核对并合并 |
| 验证与评价 | 标准库测试、合成演示、24 个真实模型待评场景、分段耗时指标 | 自动化通过不代表“与本人基本无区别”，也不代表三秒端到端达标 |

## 2. 离线运行

解压后保持两个目录并列：

```text
am-conversation-r1/
reference_am/
```

`reference_am/` 是固定 GitHub 审阅提交的 90 个公开脱敏源文件，用于重现接线验证。它不是本次读取到的 Studio 生产目录，也不能覆盖当前本机代码。

需要 Python 3.10 或以上。新模块与测试仅使用标准库；本次实际验证使用的 Python 版本记录在证据中。

```bash
cd am-conversation-r1
python3 scripts/verify.py
PYTHONPATH=src python3 -m am_conversation demo
PYTHONPATH=src python3 -m am_conversation demo --json
```

`verify.py` 自动加入本包 `src/`，生成测试日志、JUnit、语法检查和源码 SHA-256 清单。补丁应用检查需要 `git`；缺失基线或 `git` 时相应检查会明确标记跳过，不能把跳过当作通过。

演示实际使用本包的存储、工具和执行状态机；模型与业务端口均为合成替身，不联网。演示会查询合成项目、分别记录两项目事项、重建存储后读取、修改动作草稿、确认一次执行、验证重复事件与取消。

## 3. 知识导入

先将 `examples/import-config.example.json` 复制到受控本地配置文件，把身份、项目范围和数据库路径替换为本机可信值。示例占位值不能直接使用。

```bash
PYTHONPATH=src python3 -m am_conversation import-knowledge \
  --config /absolute/path/import-config.json \
  --file examples/knowledge.example.jsonl \
  --namespace first-training --dry-run
```

检查预览后按相同参数去掉 `--dry-run` 可导入候选；`--approve` 只适用于配置中的管理人。不要将合成示例当成公司的正式规则。完整操作和范围说明见知识指南。

## 4. 接入原 AM

`integration/legacy-am-conversation.patch` 修改原工程的两个文件：

- `local-qwen3.8/feishu-bridge/am_service.py`：普通私聊入站与纯文本返回、投递确认回调。
- `local-qwen3.8/feishu-bridge/bridge.py`：配置传入、关闭时释放新增存储。

新 Python 包必须安装到原 AM 的同一个运行环境或加入该进程的模块路径。`examples/am-conversation.config-fragment.json` 是合并到原配置的**片段**，不能替换整个配置。默认 `enabled=false`。

生成或核验补丁：

```bash
python3 scripts/build_legacy_patch.py --reference-root ../reference_am
```

生成器先核对两个输入文件的固定 SHA-256；输入不同即拒绝输出。当前 Studio 若已有后续修改，应由 Codex按差异合并，不强制覆盖或回退到 UX3。

## 5. 评价真实模型

`evaluations/scenarios.json` 有 24 个合成业务场景，包括指代续接、两项目切换、预计与承诺的区别、首批完成与整体验收的区别、延期处理、知识修订和权限边界。每个场景包含人工评价标准。

Codex 在本机提供受信工厂函数，返回原有的共享 `ModelCoordinator`，然后执行：

```bash
PYTHONPATH=src python3 -m am_conversation.evaluation \
  --coordinator-factory LOCAL_MODULE:FUNCTION \
  --cases evaluations/scenarios.json \
  --output evidence/qwen-evaluation.json \
  --limit 24
```

`LOCAL_MODULE:FUNCTION` 是必须实现的本机接入点。不要为运行评价绕过原协调器另起模型通道。评价器只使用合成项目端口；它不发送真实飞书消息，不改真实台账。自动检查读取范围和状态变化，人工仍需判断事实、追问必要性、管理判断和语气是否符合项目负责人。

## 6. 需要保留的实现边界

1. 新自然对话接管的是普通私聊文字；完整取消所有卡片还需要逐项迁移旧交互能力。
2. 真实外部动作尚未接线。执行协议已完成，但原发送、跟进登记、计划变更、定时提醒等业务适配仍需本机实现。
3. 新工作笔记与原跟进事项分别存放，避免把一句话误当作正式项目变更；后续应补明确的晋升/关联动作。
4. 同事自报目前存为其会话私有的候选事实，管理人不会自动看到。反馈共享须新增明确的项目级流转机制。
5. 知识检索使用带范围过滤的词项匹配，尚无向量库；知识版本批准后生效，模型参数不变。
6. “已发送/已完成”等措辞检查是保守启发式，不能证明所有语义真实；合法的历史状态改写也可能被拦截。真实模型评价必须覆盖这个问题。
7. 本包没有访问个人 ChatGPT 记忆，没有运行后台定时任务，没有更改真实服务、权限、台账或模型配置。

需求、代码和证据在本包中分别保存，便于 Codex 直接继续实现与回归。
