"""Twenty reviewed semantic skeletons. Recommendations are labelled as such."""
from datetime import date, timedelta

FAMILIES = ['progress', 'conditional_purchase', 'supplier_date', 'missing_owner', 'review_pending',
            'project_summary', 'followup_preview', 'pause', 'resume', 'unknown_send', 'node_vs_task',
            'estimate_unit', 'partial_done', 'conflict', 'material_gap', 'meeting_invite',
            'report_summary', 'outside_item', 'scope_missing', 'late_feedback']
DEV = {'supplier_date', 'partial_done', 'outside_item', 'late_feedback'}


def semantic_case(family, index):
    day = date(2099, 1, 1) + timedelta(days=index)
    when, later = day.isoformat(), (day + timedelta(days=7)).isoformat()
    p, n, done = f'合成项目{index + 1:03d}', index + 2, index + 1
    # question, facts, factual statements, labelled recommendation, incorrect boundary example
    cases = {
      'progress': ('现在进展怎么样？', {'project': p, 'reported': '样机已到', 'test_started': False, 'next_check': when},
          [f'{p}样机已到，测试还没开始', f'下一检查点是{when}'], '届时核对测试进展', f'{p}测试已完成'),
      'conditional_purchase': ('整理采购安排。', {'project': p, 'planned_quantity': n, 'condition': '样机测试无问题', 'order_placed': False},
          [f'{p}如果样机测试无问题，计划按{n}件下单', '目前还未下单'], '', f'{p}已下单{n}件'),
      'supplier_date': ('交期怎么回复？', {'project': p, 'estimated_arrival_date': when, 'supplier_confirmed': False},
          [f'{p}目前预计{when}到料', '供应商还未确认'], '核对供应商的预计交期', f'{p}供应商已确认{when}到料'),
      'missing_owner': ('这件事谁负责？', {'project': p, 'owner': None, 'next_check': when},
          [f'{p}现有资料没有明确负责人', f'{when}是下一检查点，现有资料未提供确认期限'], '核对负责人', f'{p}由同事甲负责'),
      'review_pending': ('这个交付物算完成了吗？', {'project': p, 'submitted': True, 'reviewed': False, 'count': n},
          [f'{p}的{n}份材料已提交，审核还未完成', '暂不能按验收完成记录'], '', f'{p}的{n}份材料已验收完成'),
      'project_summary': ('说一下计划、进展、卡点和下一步。', {'project': p, 'planned_test_completion_date': when, 'progress': '样机已到', 'blocker': '台架未排定'},
          [f'{p}计划{when}完成测试，目前样机已到', '卡在台架尚未排定'], '确认台架档期及对计划的影响', f'{p}已按{when}完成测试，没有卡点'),
      'followup_preview': ('准备一条跟进消息。', {'project': p, 'target': '同事甲', 'quantity': n, 'response_deadline': when, 'approved': False, 'item_type': None, 'followup_topic': None},
          [f'拟跟进{p}，对象是同事甲，涉及{n}件，反馈期限为{when}', '物料类型和跟进主题缺失，正文尚未批准'], '补充物料类型和需要跟进的主题', f'已通知同事甲在{when}前完成{n}件样机'),
      'pause': ('这个事项怎么处理？', {'project': p, 'decision': '暂停', 'next_check': when, 'completed': False},
          [f'{p}当前决定为暂停，下一检查点为{when}', '事项还未完成'], '', f'{p}已完成并关闭'),
      'resume': ('可以说恢复测试了吗？', {'project': p, 'status': '待恢复', 'planned_date': None, 'estimate': n, 'estimate_unit': '点'},
          [f'{p}保留{n}点估分，目前仍为待恢复', '恢复时间未定，不能说已恢复测试'], '', f'{p}已恢复测试，将投入{n}人天'),
      'unknown_send': ('上一条消息发出去了吗？', {'project': p, 'delivery': 'unknown', 'message_id': None},
          [f'{p}这条消息的发送结果还不明确，尚未取得消息回执'], '先核对原请求，避免重复发送', f'{p}消息已发送成功，我再发一遍'),
      'node_vs_task': ('子任务完成就代表节点完成吗？', {'project': p, 'finished_subtasks': done, 'all_subtasks': n, 'node': '进行中'},
          [f'{p}的{n}项子任务中有{done}项已标记完成，节点仍为进行中', '不能写成整个节点已完成'], '', f'{p}节点已完成'),
      'estimate_unit': ('这些估分是多少人天？', {'project': p, 'estimate': n, 'unit': None},
          [f'{p}记录的估分数值为{n}', '没有注明工时单位，暂不能换算成人天'], '', f'{p}投入{n}人天'),
      'partial_done': ('这批任务是否都结束了？', {'project': p, 'total': n, 'done': done, 'remaining': 1},
          [f'{p}共{n}项，已完成{done}项，还剩1项未完成', '不能按全部结束记录'], '', f'{p}共{n}项，已经全部完成'),
      'conflict': ('两个进度反馈不一致怎么办？', {'project': p, 'report_a': '已完成', 'report_b': '仍在测试', 'accepted_evidence': None},
          [f'{p}一份反馈说已完成，另一份说仍在测试', '当前没有验收依据，结论待核'], '核实两份反馈的差异', f'{p}已完成，另一份反馈可以忽略'),
      'material_gap': ('先给我一份草稿。', {'project': p, 'known_quantity': n, 'approval': None, 'responsible_person': None},
          [f'{p}草稿：已知数量为{n}件', '批准状态和负责人缺少依据，标为待补'], '', f'{p}数量为{n}件，已批准，由同事甲负责'),
      'meeting_invite': ('拟一句会议邀请。', {'project': p, 'meeting_topic': '问题确认', 'time': when + ' 10:00–11:00', 'sent': False},
          [f'邀请草稿：{p}的问题确认会议拟于{when} 10:00–11:00，方便参加吗', '还未发送'], '', f'{p}会议已邀请所有人参加'),
      'report_summary': ('这周进度怎么概括？', {'project': p, 'submitted': n, 'reviewed': done, 'next_check': when},
          [f'{p}本周提交{n}份材料，其中{done}份已审核，剩余1份未审核', f'下一检查点是{when}'], '', f'{p}本周{n}份材料均已审核'),
      'outside_item': ('这条应该放到哪个项目？', {'topic': p + '模板协调', 'explicit_outside': True, 'linked_project': None},
          [f'{p}模板协调已明确为项目外事项，当前没有关联项目'], '按原主题继续跟进', f'已将{p}模板协调归入项目乙'),
      'scope_missing': ('能直接采用这个结论吗？', {'project': p, 'reported_scope': '首轮样机', 'mass_production_verified': False},
          [f'{p}现有结论只覆盖首轮样机', '尚未验证量产适用性，不能直接扩展到量产'], '', f'{p}结论已适用于量产'),
      'late_feedback': ('检查点到了但没反馈，怎么写？', {'project': p, 'as_of_date': when, 'new_feedback': None, 'next_check': later},
          [f'{p}截至{when}还没有收到新反馈，不能据此判定已完成', f'下一检查点为{later}'], '核实当前进度', f'{p}在{when}已经完成'),
    }
    question, facts, statements, suggestion, bad = cases[family]
    if family == 'followup_preview' and index % 2:
        facts.update(item_type='试制件', followup_topic='回样时间')
        statements = [f'拟发给同事甲：{p}这{n}件试制件的回样时间确认了吗？请在{when}前同步一下', '正文待你确认后发送']
        suggestion = ''
    return {'family': family, 'question': question, 'facts': facts, 'statements': statements,
            'suggestion': suggestion, 'incorrect_boundary_example': bad}


def render(case, style):
    statements = list(case['statements'])
    if case['suggestion']:
        action = case['suggestion']
        statements.append(('建议' + action) if style['request_register'] == 'direct' else ('建议下一步请' + action))
    if style['layout'] == 'structured':
        return '\n'.join(f'{i + 1}. {text}。' for i, text in enumerate(statements))
    return '。'.join(statements) + '。'


def alternate_style(style):
    return {'layout': 'structured' if style['layout'] == 'compact' else 'compact',
            'request_register': 'polite' if style['request_register'] == 'direct' else 'direct'}
