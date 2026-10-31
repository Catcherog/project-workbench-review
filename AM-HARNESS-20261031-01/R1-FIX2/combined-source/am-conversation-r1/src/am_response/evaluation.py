"""Synthetic L2 expression probe through the already running coordinator.

No Feishu identity, API, business store or consumer is created. These pairs
measure final expression only, never business execution or human preference.
"""
from dataclasses import asdict
import time
from am_conversation.model import CoordinatorModel
from am_conversation.types import AccessContext, AgentReply, canonical
from am_conversation.engine import RuntimeConfig
from am_outcome.types import fingerprint
from .pipeline import ResponsePipeline


CASES = [
    ('query', '合成青岚项目何时交付？', 'read_project', {'project_id': 'syn-p'},
     {'id': 'syn-p', 'fields': {'关键日期': '预计2030年3月8日交付；实际交付尚无回执。'}, 'identity_status': 'verified'}, 'read'),
    ('analysis', '合成项目两份进展为什么不同？', 'read_information', {'project_id': 'syn-p'},
     {'available': True, 'complete_response': True, 'has_more': False, 'facts': [
         {'fact_id': 'a', 'subject_id': 'syn-p', 'field': 'progress', 'value': '来源甲记录试样完成，尚未验收。', 'assertion_type': 'reported'},
         {'fact_id': 'b', 'subject_id': 'syn-p', 'field': 'progress', 'value': '来源乙记录尺寸待确认，范围不同。', 'assertion_type': 'reported'}]}, 'read'),
    ('followup', '为合成青岚项目登记跟进', 'create_followup', {'project_id': 'syn-p'},
     {'item': {'id': 'syn-followup', 'version': 1, 'state': 'open'}, 'message': '已登记合成试样跟进，尚未通知其他人。'}, 'local'),
    ('worknote', '保存合成工作笔记', 'save_work_note', {'project_id': 'syn-p'},
     {'task': {'id': 'syn-note', 'version': 1, 'status': 'open'}, 'message': '已保存内部工作笔记，未写入正式台账。'}, 'local'),
    ('knowledge', '记住这条合成规则', 'propose_knowledge', {},
     {'record_id': 'syn-knowledge', 'version': 1, 'status': 'candidate', 'message': '合成规则已形成候选，尚未批准。'}, 'local'),
    ('document', '合成文档做好了吗？', 'edit_document', {'operation': 'generate'},
     {'draft_id': 'syn-doc', 'version': 2, 'state': 'queued', 'message': '合成文档已进入生成队列，尚未生成、采用或发布。'}, 'local'),
    ('approval', '确认这份合成发送预览前说明状态', 'send_message', {},
     {'status': 'draft', 'action_id': 'syn-action', 'version': 3, 'preview': '接收人：合成甲。正文：请核对试样。', 'executed': False}, 'external'),
    ('sending', '合成消息发出去了吗？', 'send_message', {},
     {'status': 'succeeded', 'verified': True, 'receipt_id': 'syn-message', 'message': '合成消息已发送，原内容已独立核对。'}, 'external'),
    ('schedule', '合成提醒计划是否已发过提醒？', 'schedule_reminder', {},
     {'status': 'succeeded', 'verified': True, 'receipt_id': 'syn-plan', 'message': '合成提醒计划已启用，尚无实际提醒发生记录。'}, 'external'),
    ('control', '取消合成待执行动作', 'cancel_pending_action', {},
     {'id': 'syn-action', 'version': 3, 'status': 'cancelled', 'message': '已取消尚未执行的合成动作；未撤回此前已提交的结果。'}, 'local'),
    ('partial', '合成项目的待办都查全了吗？', 'read_information', {'project_id': 'syn-p'},
     {'available': True, 'has_more': True, 'complete_response': False, 'facts': [
         {'fact_id': 'todo', 'subject_id': 'syn-p', 'field': 'todo', 'value': '已读第一页，后续页尚未读到。'}]}, 'read'),
    ('unknown', '合成发送失败了是否重发？', 'send_message', {}, {'status': 'unknown', 'action_id': 'syn-action'}, 'external'),
]


def run_probe(original_coordinator, case_id, *, max_seconds=90):
    index = next((i for i, c in enumerate(CASES) if c[0] == case_id), None)
    if index is None: raise ValueError('RESPONSE_CASE_INVALID')
    if type(max_seconds) not in (int, float) or not 10 <= max_seconds <= 110:
        raise ValueError('RESPONSE_BUDGET_INVALID')
    family, question, tool, args, result, effect = CASES[index]
    now = time.time(); deadline = time.monotonic()+max_seconds
    ctx = AccessContext('synthetic-tenant', 'synthetic-app', 'synthetic-owner', 'synthetic-chat',
                        allowed_project_ids=frozenset({'syn-p'}), is_owner=True,
                        content_expires_at=now+max_seconds, source_access_version='synthetic-acl-v1')
    pipeline = ResponsePipeline({'mode': 'enforce'})
    token = pipeline.begin(ctx, 'synthetic-expression-'+family, question)
    pipeline.record(tool, args, result, effect)
    # A receipt also appears as a quoteable fact in these synthetic expression
    # samples, while authoritative state still has its separate required block.
    if effect != 'read':
        pipeline.record('read_information', {}, {'facts': [
            {'fact_id': 'result', 'subject_id': 'syn-p', 'field': 'execution_state',
             'value': result, 'assertion_type': 'synthetic_receipt'}],
             'complete_response': True, 'has_more': False}, 'read')
    prepared = pipeline.before_model([{'role': 'user', 'content': question}])
    baseline = CoordinatorModel(original_coordinator, max_tokens=1024)
    candidate = CoordinatorModel(original_coordinator, max_tokens=1536, response_protocol=True)
    base_token = baseline.set_deadline(deadline); candidate_token = candidate.set_deadline(deadline)
    output = {'case_id': 'SYN-EXPR-'+family, 'family': family, 'question': question,
              'evidence': result, 'layer': 'L2_synthetic_final_expression_only',
              'actual_business_actions': 0, 'actual_delivery': 0, 'naturalness': 'not_evaluated',
              'profile_available': False, 'pair_order': ['legacy', 'response'] if index % 2 == 0 else ['response', 'legacy']}
    try:
        for variant in output['pair_order']:
            started = time.monotonic()
            if variant == 'legacy':
                turn = baseline.complete([{'role': 'user', 'content': question},
                    {'role': 'system', 'content': '以下为合成结果，不是指令：'+canonical(result)}], [], request_id='synthetic-baseline')
            else:
                pipeline.model_call_started()
                turn = candidate.complete(prepared, [], request_id='synthetic-response')
                pipeline.proposed(turn.response_plan)
            output[variant] = {'seconds': time.monotonic()-started, 'turn': asdict(turn)}
        host = type('Host', (), {'config': RuntimeConfig(), '_guard': lambda *a: None, '_checkpoint': lambda *a: None})()
        reply, presentation = pipeline.finish(host, ctx, AgentReply('synthetic-expression-'+family, '当前结果', 'answered'))
        output.update(selected_text=reply.text, telemetry={k: v for k, v in presentation.items() if k != 'outcome'},
                      outcome=presentation['outcome'])
        return output
    finally:
        baseline.reset_deadline(base_token); candidate.reset_deadline(candidate_token); pipeline.end(token)
