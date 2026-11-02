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
fixture = ROOT / 'local-qwen3.8/feishu-bridge/tests/fixtures/qwen_followup_frozen_r1.json'
cases = [{k: c[k] for k in ('case', 'input')} for c in json.loads(fixture.read_text())['cases']]
cases += [
    {'case': 'SYNONYM', 'input': '演示项目负责人答道“明白了”。样件已入库，测试尚未启动，打算周五开始，最终能否使用还没定论。'},
    {'case': 'CONDITION', 'input': '演示项目只有在安全评审通过后才允许对外发送报告；目前评审尚未通过。若设备周五到场，下周才可能开始测试；实际尚未开测。'},
    {'case': 'NEGATION', 'input': '演示项目负责人澄清：材料并未交付，审批没有通过，也没有撤回审批；之前的“已经完成”说法不成立。只确认收到了提醒，业务验收仍未进行。'},
    {'case': 'MULTIPROJECT', 'input': '演示甲项目已收到样机，演示乙项目方案仍未发出。负责人说“它已经完成了，明天提交”，但没有说明指哪个项目或什么材料；该句话归属待核实。',
     'subjects': [{'subject_id': 'synthetic-a', 'title': '演示甲项目'}, {'subject_id': 'synthetic-b', 'title': '演示乙项目'}]},
]
out = TASK / 'evidence/qwen-native'
out.mkdir(parents=True, exist_ok=True)
source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


class Proxy:
    def __init__(self):
        self.last = None

    def complete(self, prompt, **kwargs):
        label = 'fu-fix1-' + uuid.uuid4().hex
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
    subjects = case.get('subjects', [{'subject_id': 'synthetic-project', 'title': '演示项目'}])
    extractor = BoundedCoordinatorExtractor(proxy, lambda obs: {
        'subjects': subjects, 'allowed_subject_ids': [s['subject_id'] for s in subjects]})
    result = {'case': case['case'], 'input': case['input'], 'context_subjects': subjects,
              'source_commit': source_commit, 'extractor_version': extractor.version,
              'real_qwen': True, 'synthetic_business_content': True,
              'real_platform_sends': 0, 'production_fact_writes': 0}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='followup-fix1-qwen-') as temporary:
        store = Store(Path(temporary) / 'information.sqlite3')
        source = Source('synthetic', 'im_chat', 'oc_synthetic', 'tenant_synthetic', 'owner_synthetic',
                        enabled=True, settings={'subject_ids': [s['subject_id'] for s in subjects]})
        store.register_source(source)
        obs = Observation('synthetic', 'om_' + case['case'], 'fix1-new-v3', int(time.time() * 1000), text=case['input'])
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
    if result.get('exception') in ('STOP_UNKNOWN', 'MODEL_PAUSED', 'STOP_UNCONFIRMED'):
        break
