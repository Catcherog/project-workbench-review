"""Prepare explicitly synthetic, pending revisions from the owner's feedback.

No human label is copied to changed facts, prompts, candidate text, or context.
The original accepted snapshot remains independent and immutable.
"""
from copy import deepcopy
from pathlib import Path
import json
import os
import sys

sys.dont_write_bytecode = True
TASK = Path(__file__).resolve().parents[1]
SOURCE = TASK / 'worktree'
PACKAGE = SOURCE / 'am-style-r5'
sys.path[:0] = [str(PACKAGE / 'src'), str(SOURCE / 'am-conversation-r1/src'), str(SOURCE / 'am-style-r3')]
from am_style.contracts import StylePolicy
from am_style.render import make_frame
from am_style_r5.common import object_hash, read_json, write_json, file_hash
from am_style_r5.dataset import freeze_group_registry, build_review_batch, feedback_template

OUT = TASK / 'private/feedback-001/revision-001'
OUT.mkdir(exist_ok=False)
old_specs = read_json(TASK / 'private/run-001/prepared/scenarios.json')
old_batch = read_json(TASK / 'private/run-001/prepared/review-batch.json')
numbers = [4, 5, 6, 7, 8, 9, 10, 11, 12, 16, 20, 21]
specs, mapping = [], []

def statement(ident, value):
    return {'id': ident, 'kind': 'statement', 'value': value}

for number in numbers:
    old = old_specs[number - 1]
    facts = deepcopy(old['fixture_source']['facts'])
    effects = deepcopy(old['fixture_source']['effects'])
    gaps = deepcopy(old['fixture_source']['gaps'])
    previews = deepcopy(old['fixture_source']['previews'])
    context, additions = [], []
    text = old['proposal']
    role = 'unspecified_not_inferred'
    if number == 4:
        additions = ['新增虚构评审条件：样件已备齐，供应商已确认按原计划发货；已记录的风险评估为到货风险较低。此为新拟场景，非真实业务判断。']
        facts += [statement('readiness', '样件已备齐，供应商已确认按原计划发货'),
                  statement('risk-assessment', '根据当前备货与发货安排的已有评估，样件按计划到齐的风险较低，但不保证必然兑现')]
        text = '标定项目甲预计11月20日完成测试，前提是样件按计划到齐。目前样件已备齐，发货安排也已确认，到货风险不大，预计可以按时完成。'
    elif number == 5:
        additions = ['新增虚构评审条件：接口版本还有两项关键问题未解决，尚未确认解决时间；已有评估为冻结延期风险较高。此为新拟场景，非真实业务判断。']
        facts += [statement('unresolved-items', '接口版本还有两项关键问题未解决，尚未确认解决时间'),
                  statement('risk-assessment', '已有评估认为接口冻结可能推迟，原预计完成日期的延期风险较高')]
        text = '控制项目乙预计11月23日完成测试，前提是接口版本按计划冻结。目前还有两项关键问题未解决，冻结时间可能推迟，延期风险较高。'
    elif number == 6:
        additions = ['本例保留证据不足：没有试验台可用时间的确认信息，也没有可用的风险评估；不能自动断言低风险或高风险。']
        facts += [statement('assessment-missing', '目前没有试验台可用时间的确认信息，也没有足够资料判断延期风险')]
        text = '验证项目丙预计11月26日完成测试，前提是试验台按计划空出。目前还没有试验台可用时间的确认信息，暂时判断不了延期风险。'
    elif number in (7, 8, 9):
        additions = ['新增虚构执行前提：宿主已承接并安排只读的送达结果核实，尚未获得核实结果；没有再次发送的批准。该设定不代表本轮实际创建了业务任务。']
        context = ['宿主已安排可执行的只读回执核实任务，结果尚未返回；允许表述即将核实，不得说已核实成功或承诺重复发送。']
        text = old['proposal'].replace('需要先查回执。', '我确认一下。')
    elif number in (10, 11, 12):
        role = 'other_requester'
        activity = ['样件耐久测试', '驱动板复测', '工装标定试验'][number - 10]
        additions = ['本例提问者为其他同事，身份由宿主确定。新增虚构执行前提：宿主已承接核实开始时间和预计时长、取得结果后向原提问者同步的任务；尚未取得结果。']
        context = ['当前提问者是其他同事，不是所有者。',
                   '这是业务资料缺项，不把核实工作反问给提问者。',
                   '宿主已安排可执行的核实与结果同步任务；结果尚未返回，不声称已核实。']
        gaps = []  # Preserve missing facts, remove the owner-directed question obligation.
        text = f'{activity}的材料已经到齐了，但开始时间和预计时长还不确定。等信息明确后，我再同步给你。'
    elif number == 16:
        role = 'other_requester'
        additions = ['本例提问者为其他同事，身份由宿主确定。新增虚构执行前提：宿主已承接核实有效验收日期、取得结果后向原提问者同步的任务。仍然没有日期变更批准记录。']
        context = ['当前提问者是其他同事，不是所有者。',
                   '宿主已安排核实有效验收日期并同步结果的任务；尚未确认哪一版有效。']
        text = '仿真项目的验收日期有冲突：台账是11月18日，会议纪要是11月21日，目前还没有日期变更的批准记录。我核实后再同步给你。'
    elif number == 20:
        text = '草稿已经改成版本4，和你刚才看到的内容不同。等你确认一下新版正文后，我再发送。'
    elif number == 21:
        text = '接收对象已经从装配组甲改成装配组乙，原来的确认不能沿用。等你确认一下新的接收对象和正文后，我再发送。'
    ident = old['id'] + '-feedback-revision-001'
    scenario_source = {'facts': facts, 'effects': effects, 'gaps': gaps, 'previews': previews,
                       'context': context, 'authority': 'assistant_authored_fictional_revision_pending_human_review',
                       'actual_business': False, 'actual_followup_created': False,
                       'requester_role': role, 'supersedes': old['id']}
    frame = make_frame(binding={'turn_id': ident, 'scope_id': 'r5-public-feedback-revision-001',
             'outcome_hash': object_hash(scenario_source), 'source_revision': 'r5-feedback/1',
             'revision': 1, 'cancel_epoch': 0}, expires_at=2000000000,
             question=old['frame']['question'], family='calibration', facts=facts, effects=effects,
             gaps=gaps, previews=previews, context=context, policy=StylePolicy(**old['style_policy']))
    fact_text = '\n'.join(f['value'] for f in facts)
    if effects:
        fact_text += '\n' + '\n'.join('动作 ' + e['object'] + '：' + e['state'] + '；属于虚构回执场景。' for e in effects)
    if additions:
        fact_text += '\n\n' + '\n'.join(additions)
    if number in (10, 11, 12, 16):
        fact_text += '\n本人提问时的原全文获得了有条件认可，保留该意见；本条只评阅其他同事提问的新版本。'
    specs.append({'id': ident, 'group_id': old['group_id'], 'split': old['split'],
                  'frame': frame.data, 'style_policy': old['style_policy'], 'proposal': text,
                  'facts_for_review': fact_text, 'synthetic': True, 'fixture_source': scenario_source,
                  'human_approved': False, 'independent_test_eligible': False, 'original_number': number})
    mapping.append({'original_number': number, 'original_case_id': old['id'], 'revision_case_id': ident,
                    'frame_changed': frame.data != old['frame'], 'requester_role': role,
                    'new_fictional_conditions': additions, 'human_approval': 'pending'})

registry = freeze_group_registry(specs, baseline_train=PACKAGE / 'baseline/data/r4-gold/sft.train.jsonl',
                                baseline_dev=PACKAGE / 'baseline/data/r4-gold/sft.dev.jsonl')
batch = build_review_batch(specs, registry, version='R5-feedback-revision-001',
                          source_files={'original_batch_sha256': old_batch['batch_sha256'],
                                        'human_feedback_original_sha256': file_hash(TASK / 'private/feedback-001/original-user-message.json')})
write_json(OUT / 'scenarios.json', specs)
write_json(OUT / 'group-registry.json', registry)
write_json(OUT / 'review-batch.json', batch)
write_json(OUT / 'feedback.pending.json', feedback_template(batch))
write_json(OUT / 'original-number-map.json', mapping)
lines = ['# R5 修改稿：按原编号评阅', '',
         '本轮只评阅以下12条新全文。1–3、13–15、17–19、22原文的认可已经记录，不重复询问。',
         '10–12、16的本人提问版本按用户给出的条件保留认可意见；下文展示的是其他同事提问的新版本。',
         '全部业务情境仍为虚构校准材料。新增风险依据和核实/同步任务是待评的场景前提，不是实际业务事实或已执行动作。',
         '没有实际风险依据时不得说风险不大或很高；没有可执行的核实/同步安排时，不得空口承诺会再同步。',
         '新全文、新上下文和新增前提均未取得人工认可，不计入gold；它们也不是独立测试。', '']
for spec in specs:
    lines += [f"## 原编号 {spec['original_number']}", '', '**问题：**' + spec['frame']['question'], '',
              '**完整场景与前提：**\n' + spec['facts_for_review'], '',
              '**修改后完整答复：**' + spec['proposal'], '', '**待反馈：**事实准确、语气合适、可直接采用／需要修改／无法判断。', '']
(OUT / 'review.md').write_text('\n'.join(lines) + '\n')
write_json(OUT / 'status.json', {'new_proposals': len(specs), 'new_human_approvals': 0,
         'train_proposals': sum(s['split'] == 'train' for s in specs),
         'dev_proposals': sum(s['split'] == 'dev' for s in specs),
         'training_executed': False, 'production_changed': False,
         'current_accepted_snapshot_untouched': True,
         'snapshot_merge_status': 'new_context_registry_is_separate; no old feedback rebind or cross-registry merge performed'})
print(json.dumps({'prepared': len(specs), 'new_approvals': 0, 'batch_sha256': batch['batch_sha256']}, ensure_ascii=False))
