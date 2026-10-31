"""Freeze current R2 source and redact only the explicitly selected audit files."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[3]
TASK=ROOT/'AM-CONVERSATION-20261030-01/R2'
OUT=TASK/'review-export'
SHA='b9b0444edf34aeb962b982fca0501dc7df7d83da'
BASE='c968eca58f3ed8a3acfbccce1e3dc53b12836e16'
OUT.mkdir(exist_ok=True)
for cache in list(OUT.rglob('__pycache__'))+list(OUT.rglob('.pytest_cache')):
    shutil.rmtree(cache)
private=Path.home()/'.local/share/local-qwen-feishu'
settings=json.loads((private/'config.json').read_text())
environment=json.loads(Path(settings['poc_config']).read_text())
identifiers=set()
def identify(value):
    if isinstance(value,dict):
        for v in value.values():identify(v)
    elif isinstance(value,list):
        for v in value:identify(v)
    elif isinstance(value,str) and value.startswith(('ou_','oc_','od_','cli_','o-')) and len(value)>20:
        identifiers.add(value)
identify(settings);identify(environment)
redactions={v:v.split('_')[0]+'_'+hashlib.sha256(('audit:'+v).encode()).hexdigest()[:32] for v in identifiers}
redactions.update({str(ROOT):'/workspace/am',str(Path.home()):'/home/am',
    'example.feishu.cn':'example.feishu.cn','SYNTHETIC_TH2_LEDGER_TOKEN':'SYNTHETIC_TH2_LEDGER_TOKEN',
    '所有者':'所有者','AR900合成甲':'AR900合成甲'})
def redact(text):
    for before,after in sorted(redactions.items(),key=lambda p:-len(p[0])):text=text.replace(before,after)
    return text
def save(relative,content,mode=0o644):
    path=OUT/relative;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(redact(content));path.chmod(mode)
files={}
for item in subprocess.check_output(['git','ls-tree','-rz',SHA],cwd=ROOT).split(b'\0'):
    if not item:continue
    meta,name=item.split(b'\t',1);name=name.decode();mode,kind,blob=meta.decode().split()
    allowed=(name.endswith('.py') and name.startswith(('am-conversation-r1/src/','am-conversation-r1/tests/',
        'am-harness-r1/tests/','FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/',
        'FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests/','local-qwen3.8/feishu-bridge/')))
    allowed=allowed or name in ('am-conversation-r1/scripts/install_rewrite_runtime.py','am-conversation-r1/scripts/verify.py',
        'am-conversation-r1/scripts/build_legacy_patch.py','am-conversation-r1/examples/knowledge.example.jsonl',
        'am-harness-r1/scripts/verify_runtime.py','am-harness-r1/scripts/live_probe.py',
        'FS-AGENT-GROK-POC-20261017-01_R1_Studio/pyproject.toml','FS-AGENT-GROK-POC-20261017-01_R1_Studio/uv.lock')
    if not allowed or kind!='blob':continue
    raw=subprocess.check_output(['git','cat-file','blob',blob],cwd=ROOT)
    save('source/'+name,raw.decode(),int(mode,8)&0o777)
    files[name]={'source_sha256':hashlib.sha256(raw).hexdigest(),
        'audit_sha256':hashlib.sha256((OUT/'source'/name).read_bytes()).hexdigest()}
save('SOURCE_SHA256.json',json.dumps({'source_commit':SHA,'base_source':BASE,'files':files},ensure_ascii=False,indent=2)+'\n')
save('FINAL.diff',subprocess.check_output(['git','diff',BASE,SHA],cwd=ROOT,text=True))
pkg=TASK/'input/am-conversation-humanize'
for name in ('00_当前交接.md','docs/02_架构设计.md','docs/03_Codex接入与真实验收.md'):
    save('received-design/'+name,(pkg/name).read_text())
for name in ('package-checks.json','installer-dry-run.json','current-regression-final.xml',
             'runtime-before.json','runtime-after.json','runtime-final-source.json','update-race-reconciliation.json',
             'live-model-final.json','coverage-final.json','live-business-cases.json','style-comparison.json',
             'human-review.json','mobile-observation.json','desktop-observation.json','final-validation.json',
             'ABC-real-observed.json','history-binding-observation.json','rollout-final.json',
             'protected-business-state.json','live-model-initial.json','coverage-initial.json'):
    path=TASK/'evidence'/name
    if path.exists():save('evidence/'+name,path.read_text())
for name in ('00_当前交接.md','01_逐项验证.md'):
    save(name,(TASK/name).read_text())
for name in ('run_scoped_checks.py','collect_evidence.py'):
    save('scripts/'+name,(TASK/'scripts'/name).read_text())
for group in ('final-offline-original','final-offline-reconstructed','final-offline-original-02','final-offline-reconstructed-02'):
    for name in ('scoped.json','scoped.xml'):
        path=TASK/'evidence'/group/name
        if path.exists():save('evidence/'+group+'/'+name,path.read_text())
save('scripts/build_export.py',Path(__file__).read_text())
bad=[]
for path in OUT.rglob('*'):
    if not path.is_file():continue
    content=path.read_text()
    if any(v in content for v in identifiers) or str(Path.home()) in content:bad.append(str(path.relative_to(OUT)))
if bad:raise RuntimeError('REDACTION_FAILED:'+','.join(bad))
print(json.dumps({'source_files':len(files),'export_files':sum(p.is_file() for p in OUT.rglob('*')),
    'original_source':SHA,'exact_private_identifier_scan_passed':True}))
