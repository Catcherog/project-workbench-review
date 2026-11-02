"""R3 independent collect-only outcome and one expression call, off by default.

The collector reuses the original adapters in a separate ContextVar. It never
becomes the task model's response protocol, goal executor, or business gateway.
"""
from contextvars import ContextVar
from dataclasses import replace, asdict
import time
import uuid

from .types import ConversationError
from am_outcome.types import fingerprint
from am_response.pipeline import ResponsePipeline
from am_style.contracts import ContractError, ModelResult, StylePolicy, canonical, digest, SpeechFrame, PreparedResponse
from am_style.providers import CoordinatorProvider
from am_style.runtime import TerminalPresenter, ModelUnavailable, StopUnconfirmed, StaleFrame
from am_style.integration import prepare_terminal_reply, gateway_text
from am_style.render import make_frame


class OutcomeCollector(ResponsePipeline):
    def __init__(self, **kwargs):
        super().__init__({'mode':'shadow','profile_version':'r3-collector/1'}, **kwargs)
        self._state = ContextVar('am_terminal_collector', default=None)

    def before_model(self, messages):
        return messages  # Collector must never add response_plan or model instructions.

    def envelope(self,reply=None):
        envelope=super().envelope(reply)
        if envelope is None:return None
        d=envelope.data
        import re
        # The old goal resolver only models business actions. Its blanket
        # "whole goal unknown" footer is not a query fact. Remove it only for
        # this closed query grammar with complete typed reads.
        labels={c.get('subject_label') for c in d['claims'] if isinstance(c.get('subject_label'),str) and c['subject_label']}
        simple=any(re.fullmatch(re.escape(label)+r'(?:现在|目前)?(?:谁负责|负责人是谁|进展怎么样|进展如何|有哪些待办)[？?]?',
                               d['intent']['user_request']) for label in labels)
        units=d['work_units']
        if (simple and units and d['claims'] and not d['pending_actions']
                and all(u['effect']=='read' and u['coverage']['complete'] for u in units)
                and not re.search(r'并|然后|还要|生成|写|发送|通知|提醒|创建|取消',d['intent']['user_request'])):
            d['protected_blocks']=[x for x in d['protected_blocks'] if x['id']!='goal-coverage']
            d['completion']='fulfilled'
            d['intent']['completion_basis']='closed_query_grammar_complete_typed_reads'
            d.pop('outcome_hash',None)
            from am_outcome.types import OutcomeEnvelope
            return OutcomeEnvelope.freeze(d)
        return envelope


def project_outcome(envelope):
    """Bounded typed projection; unsupported facts keep the complete old answer.

    No parser promotes arbitrary prose to a verified receipt. Original claim
    objects and all semantic qualifiers remain in frame provenance.
    """
    data=envelope.data; b=data['binding']; facts=[]; previews=[]
    for claim in data['claims']:
        if claim['id'] not in data['required_claim_ids']:
            continue
        value=claim.get('value'); subject=claim.get('subject_label') or claim.get('subject')
        if not isinstance(value,str) or not value.strip() or not subject:
            raise ContractError('unsupported_nonatomic_claim')
        pred=claim.get('predicate'); mode=claim.get('modality','unknown')
        if mode not in ('recorded','confirmed','estimated','unverified'):
            raise ContractError('unsupported_claim_modality')
        qualifiers={k:claim[k] for k in ('scope','time','time_scope','polarity','business_state','conflict_group') if claim.get(k) is not None}
        # Unknown qualifiers are not silently discarded or guessed from words.
        if any(k in qualifiers for k in ('scope','time','time_scope','polarity','conflict_group')):
            raise ContractError('unsupported_qualified_claim')
        if qualifiers.get('business_state') not in (None,'reported','unconfirmed'):
            raise ContractError('unsupported_business_state')
        if qualifiers.get('business_state')=='unconfirmed': mode='unverified'
        kind={'owner':'owner','负责人':'owner','progress':'progress','项目进展':'progress'}.get(pred)
        if not kind or '\n' in value or len(value)>500:
            # Exact field projection preserves structured dates, scope and every
            # line; it is explicitly not credited as semantic paraphrasing.
            facts.append({'id':claim['id'],'kind':'statement','value':f'{subject}的{pred}：{value}', 'modality':mode})
        else:
            facts.append({'id':claim['id'],'kind':kind,'subject':subject,'value':value,'modality':mode})
    for block in data['protected_blocks']:
        if not isinstance(block.get('text'),str) or not block['text'].strip():
            raise ContractError('unprojectable_protected_block')
        # Preserve approval bodies and individual execution statuses exactly.
        # A model-generated terminal answer is not trusted host fact evidence.
        if block['role']=='terminal' and data['completion']=='awaiting_input':
            raise ContractError('clarification_requires_typed_gap')
        previews.append({'id':'block:'+block['id'],'text':block['text']})
    if not facts and not previews:
        raise ContractError('no_typed_outcome')
    binding={'turn_id':b['engine_event_id'],'scope_id':digest(b['scope']),
             'outcome_hash':envelope.digest,'source_revision':str(b.get('source_access_version')),
             'revision':b.get('revision',0),'cancel_epoch':b.get('cancel_epoch',0),
             'generation':b.get('generation',0)}
    frame=make_frame(binding=binding, expires_at=data['expires_at'], question=data['intent']['user_request'],
                     family='todos' if '待办' in data['intent']['user_request'] else data['families'][0],
                     facts=facts,previews=previews)
    frozen=frame.data
    frozen['provenance']['original_claims']=data['claims']
    frozen['provenance']['original_work_units']=data['work_units']
    frozen['provenance']['allowed_omission_ids']=data['allowed_omission_ids']
    return SpeechFrame.freeze(frozen)


def coordinator_provider(coordinator):
    def invoke(request):
        from am_style.prompt import RESPONSE_SCHEMA, coordinator_messages
        started=time.monotonic()
        try:
            result=coordinator.complete(coordinator_messages(request.messages)[0]['content'],
                run_id=uuid.uuid4().hex,json_schema=RESPONSE_SCHEMA,native_chat=True,
                max_tokens=request.max_output_tokens,timeout=request.timeout_seconds,
                _queue_timeout=min(30,request.timeout_seconds))
        except Exception as exc:
            code=str(exc)
            if code=='STOP_UNKNOWN': raise StopUnconfirmed(code) from exc
            if code in ('MODEL_BUSY','MODEL_NOT_DISPATCHED','MODEL_BUDGET_EXHAUSTED'):
                raise ModelUnavailable(code) from exc
            raise
        return ModelResult(result.text,'original-coordinator',result.model,(time.monotonic()-started)*1000,
                           canonical({'run_id':getattr(result,'run_id',None),'tools':[],'delivery':'none'}))
    return CoordinatorProvider(invoke)


class TerminalExpression:
    def __init__(self, settings=None, *, binding=None, dependency_lookup=None, targets=None,
                 provider=None, clock=time.time, observer=None):
        settings={} if settings is None else settings
        if (not isinstance(settings,dict) or set(settings)-{'mode','generation_budget_s','realization'}
                or settings.get('mode','off') not in ('off','shadow','enforce')):
            raise ConversationError('TERMINAL_SETTINGS_INVALID')
        self.mode=settings.get('mode','off'); self.clock=clock; self.binding=binding; self.observer=observer
        budget=settings.get('generation_budget_s',8.0)
        if type(budget) not in (int,float) or not 0<budget<=110:
            raise ConversationError('TERMINAL_SETTINGS_INVALID')
        self.collector=OutcomeCollector(binding=binding,dependency_lookup=dependency_lookup,targets=targets,clock=clock)
        self.presenter=TerminalPresenter(provider,mode=self.mode,policy=StylePolicy(realization=settings.get('realization','bounded')),
                                         generation_budget_s=budget,wall_clock=clock)

    def begin(self,ctx,event,text):
        return self.collector.begin(ctx,event,text) if self.mode!='off' else None
    def end(self,token): self.collector.end(token)
    def record(self,*args,**kwargs): self.collector.record(*args,**kwargs)
    def seed(self,fresh): self.collector.seed(fresh)

    def finish(self,agent,ctx,reply,*,deadline=None,fastpath=False):
        if self.collector.state() is None: return reply
        envelope=self.collector.envelope(reply)
        try:
            answer,prepared,frame=prepare_terminal_reply(presenter=self.presenter,agent=agent,ctx=ctx,reply=reply,
                envelope=envelope,frame_projector=project_outcome,task_deadline_monotonic=deadline,
                outcome_getter=lambda:self.collector.envelope(reply),
                require_current=lambda:self.collector.require_current(agent,ctx),fastpath=fastpath)
        except ContractError as exc:
            # A projection limitation cannot discard an already committed effect.
            if self.observer:self.observer({'event_id':reply.event_id,'status':'unsupported','reason':str(exc),'calls':0})
            return reply
        except StopUnconfirmed as exc:
            raise ConversationError('STOP_UNKNOWN') from exc
        except StaleFrame as exc:
            raise ConversationError('SOURCE_ACCESS_CHANGED') from exc
        payload={'schema_version':'am-terminal/3','outcome':envelope.data,'frame':frame.data,
                 'prepared':asdict(prepared),'semantic_hash':fingerprint(answer.text),'expires_at':frame.data['expires_at']}
        if self.observer:self.observer(payload)
        # Immutable bytes survive history/replay; no context-local state is used
        # as the authority at the later gateway transaction.
        return replace(answer,terminal_json=canonical(payload))

    def before_enqueue(self,agent,ctx,reply):
        if reply.terminal_json is None: return None
        import json
        from am_outcome.types import OutcomeEnvelope
        payload=json.loads(reply.terminal_json)
        if payload.get('schema_version')!='am-terminal/3' or payload['semantic_hash']!=fingerprint(reply.text):
            raise ConversationError('TERMINAL_HISTORY_MISMATCH')
        original=payload['outcome']; b=original['binding']
        unbound=dict(original);unbound.pop('outcome_hash',None)
        if OutcomeEnvelope.freeze(unbound).digest!=original['outcome_hash']:
            raise ConversationError('TERMINAL_OUTCOME_CHANGED')
        frame=SpeechFrame.freeze(payload['frame']); prepared=PreparedResponse(**payload['prepared'])
        if frame.data['binding']['outcome_hash']!=original['outcome_hash'] or frame.data['binding']['turn_id']!=reply.event_id:
            raise ConversationError('TERMINAL_OUTCOME_CHANGED')
        current=self.binding(ctx,reply.event_id) if self.binding else dict(b)
        for k in ('kind','scope','origin_event_id','engine_event_id','source_access_version','run_id','revision','cancel_epoch','generation','dependencies','dependency_expiries'):
            if b.get(k)!=current.get(k):raise ConversationError('TERMINAL_FENCE_CHANGED')
        if tuple(b['scope'])!=ctx.scope or b.get('source_access_version')!=ctx.source_access_version:
            raise ConversationError('TERMINAL_SCOPE_CHANGED')
        def guard(_):
            agent._guard(ctx,'read');agent._checkpoint(ctx,'before_finish')
            if ctx.content_expires_at is not None and ctx.content_expires_at<=self.clock():
                raise ConversationError('CONTENT_EXPIRED')
        try:
            if gateway_text(prepared,frame,guard)!=reply.text:
                raise ConversationError('TERMINAL_HISTORY_MISMATCH')
        except StaleFrame as exc: raise ConversationError('CONTENT_EXPIRED') from exc
        return payload
