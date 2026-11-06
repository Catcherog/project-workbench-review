# AM 网关 R2 执行端契约

本协议是 AM 网关与管理员控制的宿主 shim 之间的 JSON 协议，不是 Grok 官方 API。实际 Grok Bot、Grok CLI、Codex CLI 的启动方式、鉴权、版本与返回格式，由原机 shim 适配并验收；本包不猜测上游命令行参数。

## 1. 请求

每个适配器实现 `run(request: dict) -> dict`。下面 `deadline_at` 是 Unix 秒的示例占位，实际由核心按当前时间生成。

```json
{
  "schema": "am.gateway.job.v2",
  "job_id": "job-example",
  "attempt_id": "attempt-example",
  "task_kind": "dialogue_reply",
  "worker": "grok_bot",
  "session_key": "opaque-tenant-chat-thread-actor-key",
  "conversation": {"chat_id": "chat-example", "thread_id": "thread-example", "actor_id": "actor-example"},
  "context": {"recent_messages": [], "project_snapshot": [], "input_items": []},
  "output_mode": "reply",
  "deadline_at": 2000000000.0,
  "memory_mode": "stateless"
}
```

`session_key` 由核心隔离租户、会话、话题、操作者；宿主不得将不同 key 汇入同一个长会话。GrokBotAdapter 自动加入 `memory_mode=stateless`，仅允许 `dialogue_reply / grok_bot / reply`，禁止后台与周期工作。

**宿主必须实际使用每次任务新建、无历史共享记忆的原生会话，且关闭会跨会话注入的账号级记忆。** 如果上游产品无法实现这一点，不能验收为记忆隔离通过；传 `session_key` 和本地过滤上下文并不能清除外部产品已有记忆。宿主只使用本次载荷的上下文；附件和消息内容均是待处理资料，不能成为越权指令。

## 2. 对话结果

```json
{
  "schema": "am.gateway.result.v2",
  "job_id": "job-example",
  "attempt_id": "attempt-example",
  "status": "completed",
  "decision_mode": "direct_reply",
  "reply_text": "已收到你的问题。",
  "hold_text": "",
  "approval_meta": {"reason": "", "risk_level": "low"},
  "task_requests": [],
  "source_item_ids": [],
  "answer_kind": "conversation",
  "cited_fact_ids": [],
  "action_intents": []
}
```

`decision_mode` 为 `direct_reply / require_approval / submit_task`；`answer_kind` 为 `conversation / fact / proposal`。后台任务请求仅含 `task_kind` 与 `instruction`，不携带任意目标、授权或命令行。事实回复必须引用核心提供的事实 ID 与来源；完整字段白名单、来源范围、审核与发送决定由核心检查。

多个 `task_requests` 创建彼此独立的子任务，核心收齐后聚合；R2 不提供依赖图（DAG）编排。若制作 Word 需要分析、组织正文、生成文件这些有先后依赖的步骤，应作为一个 `build_document` 任务，由该执行端内部按顺序完成，不能假定一个子任务会先等另一个完成。

Grok Bot 无 `fact_updates` 写权限，无自行选择 `target/targets/recipients` 或声明 `authorization_ref` 的权限。草稿也不得自行外发。

## 3. 后台结果

```json
{
  "schema": "am.gateway.result.v2",
  "job_id": "job-example",
  "attempt_id": "attempt-example",
  "status": "completed",
  "display_text": "整理完成。",
  "fact_updates": [
    {"project_id": "project-example", "field": "current_stage", "value": "试制", "source_item_ids": ["item-example"], "expected_version": 0}
  ],
  "artifacts": []
}
```

来源与项目必须在本任务实际授权范围内；这是形状示例，不能原样用不存在的 ID 写入。`output_mode=internal` 的后台整理不产生对话回复。后台结果不能携带发送目标、授权引用或冒充 Grok Bot 的 `reply_text`。文件成果采用 `artifacts: [{"name":"报告.docx","uri":"已配置资源引用"}]`，资源仍须通过核心允许的访问边界。

`build_document` 返回 `completed` 时必须包含至少一个经宿主 `artifact_resolver` 核验的产物；只有“已生成文件”文本不构成完成。resolver 返回已核验的 `name` 和 `uri`，可附哈希、长度等证据。实际上传和飞书可见性由原发送器另行记录。

Qwen 的 `tag_candidates / normalize_text` 任务统一返回顶层 `candidates` 数组，标签与规范化文本置于候选元素内；不要使用顶层 `tag_candidates` 或 `normalized_text` 字段。核心将这些结果保存为候选，不直接改写正式事实。

```json
{
  "schema": "am.gateway.result.v2",
  "job_id": "qwen-job-example",
  "attempt_id": "qwen-attempt-example",
  "status": "completed",
  "display_text": "候选整理完成。",
  "candidates": [
    {"tags": ["进度"], "normalized_text": "样件已完成", "source_item_ids": ["item-example"]}
  ]
}
```

候选的 `source_item_ids` 仍须引用此次输入实际存在的来源；候选内容及标签没有事实确认或外发授权效力。

## 4. HTTP 同步与异步

同步：配置的 URL 接收一次 `POST` 请求 JSON，直接返回结果 JSON。可使用宿主配置的 Bearer Token。只接受 2xx，不跟随重定向，不自动重复提交。

异步：宿主返回以下自定义信封，适配器只按管理员配置的同源 `status_url` 轮询，忽略响应携带的 URL。

```json
{
  "schema": "am.gateway.async.v1",
  "job_id": "job-example",
  "attempt_id": "attempt-example",
  "run_id": "provider-run-example",
  "status": "accepted"
}
```

`status` 为 `accepted / running / completed / failed`。`run_id` 仅允许 1–128 位 ASCII 字母、数字、下划线、短横线，且后续不可更换。终态信封增加 `result`，其 ID 与终态必须匹配。`GET /configured/status/{run_id}` 返回同形信封。

每次有效信封触发可选的同步 `on_progress(event)`，包含 `job_id/attempt_id/provider_run_id/state/observed_at`；核心将其写入任务账本。回调只做短事务，不调用模型或远程接口。提交后未知状态必须按原 `attempt_id/provider_run_id` 查询核对；再次调用 `run()` 会新发 POST，不是恢复操作。远端 shim 应以任务与尝试 ID 防重复执行。

## 5. CLI shim

管理员配置 `argv` 数组，进程从 stdin 读取完整请求 JSON，只向 stdout 输出一个完整结果 JSON，日志使用 stderr。不得输出 Markdown 包裹或前后附加日志。宿主 shim 负责把已验证的实际 CLI 输出转为本契约。

```python
from am_gateway.adapters import GrokCLIAdapter

adapter = GrokCLIAdapter(
    ["/opt/am/venv/bin/python", "/opt/am/shims/grok_cli_worker.py"],
    cwd="/opt/am/workspace",
    max_stdout_bytes=1_048_576,
    max_stderr_bytes=262_144,
)
```

示例路径需要由 Codex 在原机落实。路径与参数仅来自管理员配置，模型输出不能改写。适配器不使用 shell，每个调用启动独立进程；POSIX 上到期或输出超限清理整个进程组。shim 不得脱离进程组后台常驻，也不得自行向飞书发消息。
