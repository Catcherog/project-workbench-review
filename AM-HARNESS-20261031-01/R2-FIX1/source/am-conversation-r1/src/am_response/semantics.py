"""Executable, conservative Chinese proposition checker. Unknown is not pass."""
import re

PROFILE = 'bounded-zh/2'
# These are lexical equivalences inside an ordered proposition, not bags of words.
_EQUIVALENTS = (('还没有','尚未'),('还没','尚未'),('暂时没有','尚无'),('预估','预计'),
               ('估计会','预计'),('已经','已'),('已完成了','已完成'),('尚未完成','未完成'))

def proposition(text):
    text=str(text).strip()
    text=re.sub(r'^(?:目前|当前|资料显示|记录显示|根据当前资料|根据记录)[，,：:\s]*','',text)
    for before,after in _EQUIVALENTS:text=text.replace(before,after)
    text=text.replace('，',',').replace('：',':')
    return re.sub(r'[\s。；;！？!?“”"]+','',text)


def atoms(text):
    # Split only sentence/semicolon boundaries: polarity/role clauses stay bound.
    return [proposition(x) for x in re.split(r'[。；;\n]',str(text)) if proposition(x)]


class SemanticAssessor:
    profile_version=PROFILE
    def __call__(self,plan,envelope):
        data=envelope.data;claims={c['id']:c for c in data['claims']};steps={s['id']:s for s in data['allowed_next_steps']}
        checks=[];verbatim=True
        for segment in plan['segments']:
            if segment['kind']!='text':continue
            text=segment['text'];refs=[claims[i] for i in segment['claim_ids']]
            intent=segment['intent']
            if intent in ('question','recommendation'):
                choices=[steps[i] for i in segment.get('next_step_ids',[]) if i in steps]
                matched=any(s['intent']==intent and (proposition(text) in [proposition(t) for t in s['permitted_utterances']] or intent=='question' and question_matches(text,s)) for s in choices)
                if matched and not any(proposition(text)==proposition(s['text']) for s in choices):verbatim=False
                checks.append({'decision':'pass' if matched else 'indeterminate','rule':'host_allowed_next_step'})
                continue
            if not refs:
                checks.append({'decision':'reject','rule':'unreferenced_statement'});continue
            permitted=[]
            for c in refs:
                value=c['value']
                if not isinstance(value,(str,int,float)):continue
                permitted+=atoms(value)
                # A typed field may be expressed as predicate + value, preserving order.
                permitted+=atoms(str(c.get('predicate',''))+'：'+str(value))
            raw=lambda x:re.sub(r'[\s。；;，,:：]','',str(x))
            segment_verbatim=any(raw(text)==raw(c['value']) or raw(text)==raw(str(c.get('predicate',''))+str(c['value'])) for c in refs)
            verbatim=verbatim and segment_verbatim
            actual=atoms(text)
            if actual and all(a in permitted for a in actual):
                decision,rule='pass','ordered_source_propositions'
                if len({c.get('subject') for c in refs})>1:
                    decision,rule='indeterminate','multiple_subject_binding_unproven'
                elif any(not set(atoms(c['value'])).issubset(set(actual)) and not set(atoms(str(c.get('predicate',''))+'：'+str(c['value']))).issubset(set(actual)) for c in refs):
                    decision,rule='reject','referenced_claim_partially_expressed'
                attribution=bool(re.match(r'^(?:目前|当前)?(?:资料显示|记录显示|根据当前资料|根据记录|资料记载|台账记载|台账显示)',text))
                unconfirmed=any(c.get('modality') in ('recorded','reported','unknown') or c.get('business_state') not in ('confirmed','verified') for c in refs)
                if decision=='pass' and not segment_verbatim and unconfirmed and not attribution:
                    decision,rule='indeterminate','source_attribution_required'
            else:
                # A clear change to an explicit temporal/modal/negative qualifier is rejected.
                source='；'.join(str(c['value']) for c in refs)
                altered=any(token in source and token not in text for token in ('预计','尚未','未确认','待核','可能','建议','仅','如果'))
                decision,rule=('reject','qualifier_or_scope_changed') if altered else ('indeterminate','unsupported_proposition')
            checks.append({'decision':decision,'rule':rule,'render_as_source_quote':segment_verbatim})
        decision='reject' if any(c['decision']=='reject' for c in checks) else 'indeterminate' if any(c['decision']=='indeterminate' for c in checks) else 'pass'
        return {'profile_version':PROFILE,'decision':decision,'checks':checks,'general_semantic_equivalence_proven':False,'expression_class':'source_projection' if verbatim else 'free_text'}


def next_steps(goals, units):
    out=[]
    for goal in goals:
        if goal.get('completion')=='fulfilled':continue
        op=goal.get('operation');span=' '.join(goal.get('request_spans',[]))
        slot=None;question=None
        if op in ('create_followup','save_work_note') and not goal.get('matter'):
            slot='content';question='请补充这条跟进的具体内容。' if op=='create_followup' else '请补充这条笔记的具体内容。'
        elif op=='schedule_reminder' and not re.search(r'\d{1,2}[:点时]|[一二三四五六七八九十两]+点',span):
            slot='clock';question='请补充具体的提醒时间。'
        elif op=='send_message' and not goal.get('matter'):
            slot='message';question='请补充要发送的具体内容。'
        if slot:
            out.append({'id':'ask:'+goal['step_id'],'intent':'question','goal_id':goal['step_id'],
                'missing':slot,'text':question,'date_context':'明天' if '明天' in span else None,
                'permitted_utterances':[question]})
    for u in units:
        if u['status']=='unknown':
            sentence='建议先核对这项操作的结果，核清前不重复办理。'
            out.append({'id':'reconcile:'+u['id'],'intent':'recommendation','operation':'reconcile',
                        'text':sentence,'permitted_utterances':[sentence]})
    return out


def question_matches(text,step):
    """Parse an ask(slot) speech act; no assertions or arbitrary named targets."""
    value=re.sub(r'[\s。？！?!]','',text)
    slots={'content':r'(?:具体内容|具体事项|事项内容|要跟进什么|要记录什么)',
           'clock':r'(?:具体时间|提醒时间|具体的提醒时间|几点|什么时间)',
           'message':r'(?:要发送的具体内容|要发送什么|消息内容)'}
    slot=slots.get(step.get('missing'))
    if slot is None:return False
    pattern=r'(?:请|麻烦|能否|可以)?(?:补充|提供|说明|告诉我|确认)?(?:一下)?(?:这条跟进的|这条笔记的|这项事项的)?'+slot+r'(?:吗|呢)?'
    if re.fullmatch(pattern,value):return True
    return step.get('missing')=='clock' and step.get('date_context')=='明天' and bool(re.fullmatch(r'明天(?:的提醒)?(?:安排在|设为)?(?:几点|什么时间)(?:合适|提醒你)?',value))
