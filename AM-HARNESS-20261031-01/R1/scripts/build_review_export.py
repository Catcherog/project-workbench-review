"""Export immutable source and scoped, body-free evidence for the authorized review repository."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-HARNESS-20261031-01/R1';OUT=TASK/'review-export'
SHA='c968eca58f3ed8a3acfbccce1e3dc53b12836e16';FIX='8c25340dd5b9e97ec0354b19ab61f7e877401f9f'
if OUT.exists():raise RuntimeError('EXPORT_ALREADY_EXISTS')
OUT.mkdir()
source_names=[]
for line in subprocess.check_output(['git','ls-tree','-rz',SHA],cwd=ROOT).split(b'\0'):
 if not line:continue
 info,name=line.split(b'\t',1);name=name.decode();mode,kind,blob=info.decode().split()
 fs='FS-AGENT-GROK-POC-20261017-01_R1_Studio/'
 allowed=(name.startswith((fs+'src/',fs+'tests/','am-conversation-r1/','am-harness-r1/')) or name in (fs+'pyproject.toml',fs+'uv.lock') or name.startswith(fs+'config/') and name.endswith('.example.json') or name.startswith('local-qwen3.8/feishu-bridge/') and (name.endswith('.py') or Path(name).name.startswith('requirements')))
 if not allowed or kind!='blob' or '__pycache__' in name or name.startswith('am-conversation-r1/integration/'):continue
 data=subprocess.check_output(['git','cat-file','blob',blob],cwd=ROOT);data.decode('utf-8')
 dest=OUT/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);dest.chmod(int(mode,8)&0o777)
 source_names.append(name)
pkg=TASK/'input/AM-HARNESS-20261031-01'
for name in ('00_当前交接.md','docs/01_详细设计.md','docs/02_AM接入与迁移.md','docs/03_验证与验收.md','docs/04_资料依据.md','integration/engine.patch'):
 dest=OUT/'received-design'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(pkg/name,dest)
shutil.copytree(pkg/'baseline/reference_am',OUT/'fixtures/reference_am',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
def copy_evidence(src,dest):
 dest.parent.mkdir(parents=True,exist_ok=True)
 content=src.read_text();content=content.replace(str(ROOT),'/workspace/am').replace(str(Path.home()),'/home/am')
 dest.write_text(content)
for name in ('received-package','final-original'):
 for src in (TASK/'verification'/name).rglob('*'):
  if src.is_file():copy_evidence(src,OUT/'verification'/name/src.relative_to(TASK/'verification'/name))
for name in ('preexisting-pytest.xml','runtime-harness-before-r2.json','runtime-later-r2.json','runtime-later-r2-verified.json','later-r2-reconciliation.json','live-summary.json','live-cancel.json','live-revise.json','live-revise-source-access-rejected.json','live-self-send.json'):
 copy_evidence(TASK/'verification'/name,OUT/'verification'/name)
(OUT/'diffs').mkdir();(OUT/'diffs/harness-vs-fix1.patch').write_bytes(subprocess.check_output(['git','diff',FIX,SHA,'--'],cwd=ROOT))
for name in ('live_control_scenario.py','live_owner_send_scenario.py','build_review_export.py'):
 copy_evidence(TASK/'scripts'/name,OUT/'scripts'/name)
(OUT/'received-design/package.json').write_text(json.dumps({'zip':'AM-HARNESS-20261031-01_R1.zip','sha256':'691ada5a795710781aa1b17e025177a7e96892984e4bdd8cca015e8078ff6cfe','initial_runtime_source':'cd59333c8fdb3d57d045a9ac571bf3c17321d54a','parallel_fix_source':FIX,'source_commit':SHA,'baseline_policy':'reference_am is an offline fixture only; no baseline files were installed over the latest runtime'},indent=2)+'\n')
# Match against actual runtime identifiers without writing or printing them.
private=Path.home()/'.local/share/local-qwen-feishu';cfg=json.loads((private/'config.json').read_text());pc=json.loads(Path(cfg['poc_config']).read_text())
identifiers=set()
def walk(v):
 if isinstance(v,dict):
  for x in v.values():walk(x)
 elif isinstance(v,list):
  for x in v:walk(x)
 elif isinstance(v,str) and (v.startswith(('ou_','oc_','od_','cli_')) or v.startswith('o-')) and len(v)>20:identifiers.add(v)
walk(cfg);walk(pc)
bad=[]
for file in OUT.rglob('*'):
 if file.is_file():
  data=file.read_text()
  if any(value in data for value in identifiers):bad.append(str(file.relative_to(OUT)))
if bad:raise RuntimeError('EXACT_RUNTIME_IDENTIFIER_IN_EXPORT:'+','.join(bad))
print(json.dumps({'source_commit':SHA,'source_files':len(source_names),'files_before_handoff':sum(p.is_file() for p in OUT.rglob('*')),'exact_runtime_identifier_scan_passed':True}))
