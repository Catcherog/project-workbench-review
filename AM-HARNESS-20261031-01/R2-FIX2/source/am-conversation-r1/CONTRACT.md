# R1 模块契约

这是增量模块，已有 Python/Qwen/飞书链路为集成基础。所有外部调用通过注入端口完成，不另起飞书消费者、不绕过 ModelCoordinator。

## 共同类型

`src/am_conversation/types.py` 是单一契约：AccessContext 由可信入站适配器构造，模型不能提供身份、角色、项目范围。完整隔离键是 tenant/app/actor/chat/thread，session_id 为该键的哈希。所有数据库记录保留 app 与 tenant；owner 管理权不扩大知识可见范围。

模型方法：`complete(messages: list[dict], tools: list[dict], *, request_id='') -> ModelTurn`。messages 用 role/content，工具结果也用可序列化内容。tools 为 OpenAI 兼容函数描述 `{type:'function',function:{name,description,parameters}}`。ToolCall 为 id/name/arguments；ModelTurn 为 text/tool_calls。每轮只能调用已提供的工具。只产生文本或工具调用，不直接做任何业务副作用。

## KnowledgeStore

构造 `KnowledgeStore(db_path, *, owner_ids=None, clock=time.time)`；owner_ids 为 `(tenant_id,app_id) -> set[actor_id]` 的可信配置，必须配置才能批准。方法使用 AccessContext；记录返回 dict，含 id/logical_id/version/kind/content/source/scope/status/project_id/session_id/actor_id/created_at。source 是含 uri 与 observed_at 的对象；kind 支持 business/rule/fact/case/style；scope 为 tenant/project/private；默认 private。

`submit(ctx, *, kind, content, source, scope='private', project_id=None, logical_id=None, expected_version=None)` 生成 candidate；非 owner 只能提交 fact，且 private。`approve(ctx, record_id, expected_version)` 批准确切版本并替代同逻辑对象旧批准版本；`reject(...)`；`search(ctx, query, *, project_id=None, kinds=None, limit=6)` 仅返回 authorized+approved 活跃版本；`get(ctx, record_id)` 要检查可见范围；`review_candidates(ctx, limit=20)` 只在当前可见范围审阅。非当前私有会话永不隐式检索。SQLite 独立连接+事务；实现 close()。

## ConversationStore

构造 `ConversationStore(db_path, *, clock=time.time)`；返回 dict，所有方法首参 ctx:AccessContext。

事件：`claim_event(ctx,event_id,text)` -> `{state:'claimed'|'completed'|'in_progress'|'unknown', reply:dict|None}`；同 event_id 不同正文或scope拒绝。`finish_event(ctx,event_id,reply:dict)`；`fail_event(ctx,event_id,code)`；`append_message(ctx,role,content,event_id=None)`；`history(ctx,limit=20)` 返回 role/content dict。

话题：`set_focus(ctx,project_id,event_id=None)` 只接受当前可访问的项目；若提供 event_id，须为本会话已 claim 事件。`get_focus(ctx)` 返回当前可访问的 project_id 或 None，按 tenant/app/actor/chat/thread 持久保存，可跨天。当前权限不再覆盖原项目时返回 None，不暴露旧项目标识。history 同时按当前权限指纹过滤，避免撤权后从旧回复恢复已不可见的资料。

任务：`create_task(ctx, *, project_id,title,details='',due_at=None,status='open',event_id=None)`；`get_task(ctx,task_id)`；`list_tasks(ctx, *, project_id=None,include_closed=False,limit=30)`；`update_task(ctx,task_id, *, expected_version, changes:dict)`。记录含 id/project_id/title/details/due_at/status/version；状态 open/waiting/closed/cancelled。日期绝对ISO带时区；未确定不猜。

动作：`create_action(ctx, *, tool_name,arguments:dict,project_id=None,preview:str,ttl_seconds=1800)`；`get_action(ctx,action_id)`；`list_actions(ctx, *, active_only=True)`；`revise_action(ctx,action_id, *, expected_version, arguments,preview)`；`mark_presented(ctx,action_id, *, expected_version,event_id)`；`approve_action(ctx,action_id, *, expected_version,digest)`；`cancel_action(ctx,action_id, *, expected_version)`；`begin_execution(ctx,action_id, *, expected_version)` -> `{claimed:bool,action:dict}`；`finish_execution(ctx,action_id, *, status,result)`。记录含 id/tool_name/arguments/project_id/preview/version/digest/status/presented_version/expires_at/result；状态 draft/approved/executing/succeeded/failed/unknown/cancelled/expired。

审批需 owner、已展示同版本、未过期，修改后授权失效；begin_execution为原子领取，unknown不自动重发；recover_inflight()仅显式维护调用，将未完成执行标unknown，不在构造时擅自改变其他进程正在执行的状态。

## 测试

只使用 Python 标准库 unittest，不依赖 pytest。数据使用合成项目与身份，不写真实业务状态。核心验收是隔离、实际本地状态变化、并发/重复/取消、正确恢复。真实模型与外部业务能力需另行验证，不能由替身测试推定。
