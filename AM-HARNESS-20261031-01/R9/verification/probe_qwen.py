"""One recorded pass through the original live Qwen coordinator; synthetic data.

The host queue invokes only model transport. The new extractor, original fact
worker, SQLite and pending-review view run in a temporary validation database.
No platform sending, production candidate insertion or repeated best-of runs.
"""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]
sys.path[:0] = [str(ROOT / 'local-qwen3.8/feishu-bridge'),
               str(ROOT / 'FS-AGENT-GROK-POC-20261017-01_R1_Studio/src')]
from info_extraction import BoundedCoordinatorExtractor
from info_semantics import pending_reviews
from am_info_sync.models import Observation, Source, Principal
from am_info_sync.store import Store
from am_info_sync.extraction import ExtractionWorker

cfg = json.loads((Path.home() / '.local/share/local-qwen-feishu/config.json').read_text())
poc = json.loads(Path(cfg['poc_config']).read_text())
queue = Path(poc['service']['root_directory']) / 'state/am-conversation-r2'
cases = [
 {'case':'SEM01-base','input':'演示项目没有开测记录。','expected':'缺少记录，不等于实际未开测'},
 {'case':'SEM01-related','input':'演示项目没有开测的相关记录。','expected':'保留相关记录缺口'},
 {'case':'SEM02-negative','input':'演示项目尚未开测。','expected':'直接业务否定'},
 {'case':'SEM02-both','input':'演示项目没有开测记录且尚未开测。','expected':'缺记录与未开测分别保留'},
 {'case':'SEM03-reported','input':'演示项目工程师说，材料已交付，审批已经通过。','expected':'两项均保留转述归属'},
 {'case':'SEM04-quoted','input':'演示项目工程师说：“材料已交付”，审批已经通过。','expected':'引语内保留工程师，外部独立命题不扩大转述'},
 {'case':'SEM05-ambiguous','input':'演示甲项目已收到样机，演示乙项目方案仍未发出。随后已开始测试。','subjects':[{'subject_id':'synthetic-a','name':'演示甲项目','resolved':True},{'subject_id':'synthetic-b','name':'演示乙项目','resolved':True}],'expected':'无主语测试归属不明应可见待核，不猜项目'},
 {'case':'SEM06-conflicting-hint','input':'演示乙项目尚未开测。','subjects':[{'subject_id':'synthetic-a','name':'演示甲项目','resolved':True},{'subject_id':'synthetic-b','name':'演示乙项目','resolved':True}],'hint':'synthetic-a','expected':'不把乙项目信息归入甲项目'},
 {'case':'SEM06-unauthorized-hint','input':'演示项目尚未开测。','hint':'outside-scope','expected':'模型调用前拒绝越界hint'},
 {'case':'CONDITION','input':'演示项目若样机到货，下周才可能开始测试；实际尚未开测。','expected':'条件预测及直接否定保留'},
 {'case':'CORRECTION','input':'演示项目负责人澄清：材料并未交付，审批没有通过；之前的“已经完成”说法不成立。','expected':'更正和否定完整，保留归因'},
 {'case':'REPEATED','input':'演示甲项目材料已交付。演示乙项目材料已交付。','subjects':[{'subject_id':'synthetic-a','name':'演示甲项目','resolved':True},{'subject_id':'synthetic-b','name':'演示乙项目','resolved':True}],'expected':'重复短句依明确项目分别归属'},
]
out = TASK / 'private/qwen-native'
out.mkdir(parents=True, exist_ok=True)
source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


class Proxy:
    def __init__(self):
        self.last = None

    def complete(self, prompt, **kwargs):
        label = 'r9-sem-' + uuid.uuid4().hex
        request = {'operation': 'task_model_probe', 'case': 'SYN-QRY-01', 'expires_at': time.time() + 150,
                   'model_request': {'prompt': prompt, 'json_schema': kwargs['json_schema'],
                                     'max_tokens': kwargs['max_tokens'], 'timeout': 90}}
        self.last = {'request': request, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()}
        target = queue / 'requests' / (label + '.json')
        temporary = target.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(request, stream, ensure_ascii=False)
        temporary.replace(target)
        started = time.monotonic()
        result = queue / 'results' / (label + '.json')
        while not result.exists() and time.monotonic() - started < 145:
            time.sleep(.2)
        if not result.exists():
            raise RuntimeError('STOP_UNKNOWN')
        value = json.loads(result.read_text())
        self.last.update(result=value, elapsed_seconds=time.monotonic() - started)
        if not value.get('ok'):
            raise RuntimeError(value.get('error', 'FAILED'))
        return SimpleNamespace(text=value['text'], model=value['model'], usage=value['model_calls'])


summary = []
for case in cases:
    destination = out / (case['case'] + '.json')
    if destination.exists():
        raise RuntimeError('DO_NOT_REPLAY_BATCH')
    proxy = Proxy()
    subjects = case.get('subjects', [{'subject_id': 'synthetic-project', 'name': '演示项目', 'aliases': [], 'resolved': True}])
    extractor = BoundedCoordinatorExtractor(proxy, lambda obs: {
        'subjects': subjects, 'allowed_subject_ids': [s['subject_id'] for s in subjects], 'conversation_hint': {'subject_id':case['hint']} if case.get('hint') else {}})
    result = {'case': case['case'], 'input': case['input'], 'context_subjects': subjects,
              'source_commit': source_commit, 'extractor_version': extractor.version,
              'runtime_sha256': {n:hashlib.sha256((ROOT/'local-qwen3.8/feishu-bridge'/n).read_bytes()).hexdigest() for n in ('info_extraction.py','info_semantics.py')},
              'expected_before_call':case.get('expected'), 'human_gold_approved':False,'evidence_class':'development_regression',
              'real_qwen': True, 'synthetic_business_content': True,
              'real_platform_sends': 0, 'production_fact_writes': 0}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='followup-fix2-qwen-') as temporary:
        store = Store(Path(temporary) / 'information.sqlite3')
        source = Source('synthetic', 'im_chat', 'oc_synthetic', 'tenant_synthetic', 'owner_synthetic',
                        enabled=True, settings={'subject_ids': [s['subject_id'] for s in subjects]})
        store.register_source(source)
        obs = Observation('synthetic', 'om_' + case['case'], 'r9-v5', int(time.time() * 1000), text=case['input'])
        store.record(obs)
        worker = ExtractionWorker(store, extractor, max_attempts=1)
        try:
            result['worker_result'] = worker.run_once()
        except Exception as exc:
            result['exception'] = str(exc)
        principal = Principal('owner_synthetic', 'tenant_synthetic')
        facts = [fact for subject in subjects for fact in worker.facts.query(subject['subject_id'], principal)['facts']]
        result.update(call=proxy.last, extraction_metadata=extractor.last_call,
                      committed_facts=facts, pending_reviews=pending_reviews(store, principal),
                      all_committed_model_facts_unconfirmed=all(f['authority'] == 'unconfirmed' for f in facts))
        result['elapsed_seconds'] = time.monotonic() - started
        store.close()
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    brief = {k: result[k] for k in ('case', 'worker_result', 'elapsed_seconds') if k in result}
    brief.update(committed_facts=len(result['committed_facts']), pending_reviews=result['pending_reviews']['total'])
    summary.append(brief)
    (out / 'summary.json').write_text(json.dumps({'cases': summary, 'single_pass': True,
        'real_platform_sends': 0, 'business_accuracy_requires_manual_assessment': True}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(brief, ensure_ascii=False), flush=True)
    if result.get('exception') in ('STOP_UNKNOWN', 'MODEL_PAUSED', 'STOP_UNCONFIRMED') or (proxy.last or {}).get('result',{}).get('error') in ('STOP_UNKNOWN','MODEL_PAUSED','STOP_UNCONFIRMED'):
        break
