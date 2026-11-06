"""Candidate ports into the existing consumer and review area; no new connection.

This is intentionally not a Grok Bot endpoint implementation. External activation
fails while any actual receiver/result/memory/polling binding is missing.
"""
from dataclasses import dataclass
from pathlib import Path
import threading

from am_gateway.models import ContractError
from am_gateway.phase1 import Harness, HarnessConfig
from am_gateway.store import Store
from integration.am_multi_ai_host import HostAdmission, normalize_message


@dataclass
class Phase1Ports:
    config: HarnessConfig
    database_path: str
    verified_scope: object
    authorization_for: object
    projects_for: object
    legacy_control: object
    classifier: object = None
    adapters: object = None
    authenticated_actor: object = None
    normalize_recall: object = None
    # Only actual host adapter evidence may populate these, not a settings switch.
    receiver_evidence: str = ''
    result_channel_evidence: str = ''
    memory_boundary_evidence: str = ''
    polling_exclusion_evidence: str = ''


class ReviewArea:
    """Reuse the host's pending-review projection, without an external send here."""
    def __init__(self, harness):
        self.harness = harness

    def items(self):
        return self.harness.pending()

    def apply(self, *, authenticated_actor, task_id, action, intent=None, supplement=''):
        if action == 'technical_retry':
            if authenticated_actor != self.harness.config.owner_id:
                raise ContractError('operator required')
            return self.harness.retry_classification(task_id)
        if action not in {'resume','ignore'}:
            raise ContractError('unsupported review action')
        return self.harness.resume(task_id,authenticated_actor,supplement=supplement,
                                   intent=intent,ignore=action=='ignore')


class Phase1Ingress:
    def __init__(self, harness, ports, scheduler=None):
        self.gateway, self.ports, self.scheduler = harness, ports, scheduler
        self.review = ReviewArea(harness)

    def ingest(self, payload):
        if not self.ports.verified_scope(payload):
            return HostAdmission(False,False,False,'',False)
        event = normalize_message(payload,self.gateway.config,project_ids=self.ports.projects_for(payload))
        policy = self.ports.authorization_for(event)
        # Existing document commands, controls, and already-owned operations remain owned.
        legacy = self.ports.legacy_control(payload)
        admission = self.gateway.ingest(event,None if legacy else policy)
        if self.scheduler:
            self.scheduler.notify()
        return HostAdmission(True,admission.handled,admission.handled,event.item_id,not admission.inserted)

    def card_callback(self, payload):
        # Reuse an actual authenticated host callback; never trust an actor in action.value.
        event = payload.get('event',payload)
        value = event.get('action',{}).get('value',{})
        if not isinstance(value,dict) or value.get('kind')!='harness_review':
            return None
        if self.ports.authenticated_actor is None:
            raise ContractError('host callback identity binding unavailable')
        actor = self.ports.authenticated_actor(payload)
        self.review.apply(authenticated_actor=actor,task_id=value['task_id'],action=value['action'],
                          intent=value.get('intent'),supplement=value.get('supplement',''))
        if self.scheduler:
            self.scheduler.notify()
        return {'toast':{'type':'info','content':'任务记录已更新，实际执行状态以核验结果为准。'}}

    def recall(self, payload):
        # Normalize recall through the same verified source adapter before ingestion.
        if self.ports.normalize_recall is None:
            self.gateway.information.sync_failure('recalls','recall_adapter_unavailable')
            return {'status':'unsupported','source_changed':False}
        event=self.ports.normalize_recall(payload)
        if not event.is_deleted:
            raise ContractError('recall adapter must return a verified deletion')
        self.gateway.ingest(event)
        if self.scheduler:
            self.scheduler.notify()
        return {'status':'recorded','source_changed':True}


class Phase1Scheduler:
    def __init__(self,harness):
        self.harness=harness
        self.wakeup=threading.Event()
        self.stopped=threading.Event()
        self.thread=None

    def notify(self):
        self.wakeup.set()

    def start(self):
        if self.thread is not None:
            return
        self.thread=threading.Thread(target=self._run,daemon=True,name='existing-gateway-phase1')
        self.thread.start()

    def _run(self):
        while not self.stopped.is_set():
            # No fixed debounce on the first event; wake immediately after durable admission.
            self.wakeup.wait(.5);self.wakeup.clear()
            try:
                for _ in range(50):
                    if self.stopped.is_set() or self.harness.route_one() is None:
                        break
                self.harness.expire()
                self.harness.information.project_sources()
            except Exception as exc:
                with self.harness.store.transaction() as db:
                    self.harness.store.audit(db,'phase1_scheduler_error','scheduler',type(exc).__name__)

    def stop(self):
        self.stopped.set();self.wakeup.set()
        if self.thread:
            self.thread.join(self.harness.config.classification_budget_seconds+2)
        return {'stopped':not self.thread or not self.thread.is_alive()}


def install(ports, *, activate=False):
    if not isinstance(ports,Phase1Ports):
        raise ContractError('trusted phase-one host ports required')
    if activate:
        required = ('receiver_evidence','result_channel_evidence','memory_boundary_evidence','polling_exclusion_evidence')
        if any(not getattr(ports,k) for k in required):
            raise ContractError('Grok Bot activation blocked: actual receiver/result/memory/polling bindings missing')
        # No concrete Grok Bot receiver was verified in this delivery. Do not turn
        # four strings or a custom protocol into a claim of real integration.
        raise ContractError('real Grok Bot adapter not implemented; candidate-only install')
    harness=Harness(Store(ports.database_path),ports.config,classifier=ports.classifier,adapters=ports.adapters)
    scheduler=Phase1Scheduler(harness)
    return Phase1Ingress(harness,ports,scheduler),scheduler
