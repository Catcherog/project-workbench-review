"""Freeze the combined version; export only source, synthetic tests and metadata."""
from pathlib import Path
import hashlib,json,re,subprocess,shutil
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-HARNESS-20261031-01/R1-FIX2';OUT=TASK/'review-export';OUT.mkdir(exist_ok=True)
SHA='714b1af93a2cb4090f3c8166296455c0035d5730';BASE='d3e40b0d27517d75e850613c4eaecec107efa0ea'
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());pc=json.loads(Path(settings['poc_config']).read_text())
identifiers=set();secrets=set()
def inspect(value,key=''):
    if isinstance(value,dict):
        for k,v in value.items():inspect(v,k)
    elif isinstance(value,list):
        for v in value:inspect(v,key)
    elif isinstance(value,str):
        if value.startswith(('ou_','oc_','od_','cli_','o-')) and len(value)>20:identifiers.add(value)
        if re.search(r'(?i)secret|password|access_token|refresh_token|api_key',key) and len(value)>12:secrets.add(value)
inspect(settings);inspect(pc)
redactions={v:v.split('_')[0]+'_SYNTHETIC_'+hashlib.sha256(('audit:'+v).encode()).hexdigest()[:12] for v in identifiers}
redactions.update({v:'SYNTHETIC_REDACTED_SECRET' for v in secrets})
redactions.update({str(ROOT):'/workspace/am',str(Path.home()):'/home/am','example.feishu.cn':'example.feishu.cn','SYNTHETIC_TH2_LEDGER_TOKEN':'SYNTHETIC_TH2_LEDGER_TOKEN','所有者':'所有者','AR900合成甲':'AR900合成甲'})
def redact(text):
    for before,after in sorted(redactions.items(),key=lambda kv:-len(kv[0])):text=text.replace(before,after)
    return text

def save(path,text,mode=0o644):
    p=OUT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(redact(text));p.chmod(mode)
files={}
for part in subprocess.check_output(['git','ls-tree','-rz',SHA],cwd=ROOT).split(b'\0'):
    if not part:continue
    meta,name=part.split(b'\t',1);name=name.decode();mode,kind,blob=meta.decode().split()
    fs='FS-AGENT-GROK-POC-20261017-01_R1_Studio/'
    allowed=(name.startswith((fs+'src/',fs+'tests/','am-conversation-r1/','am-harness-r1/')) or name in (fs+'pyproject.toml',fs+'uv.lock') or name.startswith(fs+'config/') and name.endswith('.example.json') or name.startswith('local-qwen3.8/feishu-bridge/') and (name.endswith('.py') or Path(name).name.startswith('requirements')))
    if not allowed or kind!='blob' or '__pycache__' in name or name.startswith('am-conversation-r1/integration/'):continue
    data=subprocess.check_output(['git','cat-file','blob',blob],cwd=ROOT)
    save('source/'+name,data.decode(),int(mode,8)&0o777)
    files[name]={'source_sha256':hashlib.sha256(data).hexdigest(),'audit_sha256':hashlib.sha256((OUT/'source'/name).read_bytes()).hexdigest()}
fixtures=ROOT/'AM-HARNESS-20261031-01/R1/review-export/fixtures/reference_am'
for p in fixtures.rglob('*'):
    if p.is_file() and not any(x in p.parts for x in ('__pycache__','.pytest_cache')):
        save('fixtures/reference_am/'+p.relative_to(fixtures).as_posix(),p.read_text(),p.stat().st_mode&0o777)
save('SOURCE_SHA256.json',json.dumps({'source_commit':SHA,'base_source':BASE,'files':files},ensure_ascii=False,indent=2)+'\n')
save('FINAL.diff',subprocess.check_output(['git','diff',BASE,SHA],cwd=ROOT,text=True))

COMBINED='60f60f564080b75206cd80b35597c1d086925354'
subprocess.run(['git','merge-base','--is-ancestor',SHA,COMBINED],cwd=ROOT,check=True)
combined={}
for part in subprocess.check_output(['git','ls-tree','-rz',COMBINED],cwd=ROOT).split(b'\0'):
    if not part:continue
    meta,name=part.split(b'\t',1);name=name.decode();mode,kind,blob=meta.decode().split()
    fs='FS-AGENT-GROK-POC-20261017-01_R1_Studio/'
    allowed=(name.startswith((fs+'src/',fs+'tests/','am-conversation-r1/','am-harness-r1/')) or name in (fs+'pyproject.toml',fs+'uv.lock') or name.startswith(fs+'config/') and name.endswith('.example.json') or name.startswith('local-qwen3.8/feishu-bridge/') and (name.endswith('.py') or Path(name).name.startswith('requirements')))
    if not allowed or kind!='blob' or '__pycache__' in name or name.startswith('am-conversation-r1/integration/'):continue
    raw=subprocess.check_output(['git','cat-file','blob',blob],cwd=ROOT)
    save('combined-source/'+name,raw.decode(),int(mode,8)&0o777)
    combined[name]={'source_sha256':hashlib.sha256(raw).hexdigest(),'audit_sha256':hashlib.sha256((OUT/'combined-source'/name).read_bytes()).hexdigest()}
save('COMBINED_SOURCE_SHA256.json',json.dumps({'source_commit':COMBINED,'includes_fix_source_commit':SHA,'files':combined},ensure_ascii=False,indent=2)+'\n')
save('LATER_CHANGES.diff',subprocess.check_output(['git','diff',SHA,COMBINED],cwd=ROOT,text=True))

for name in ('run_checks.py','live_checks.py','when_stable.py','build_export.py'):
    save('scripts/'+name,(TASK/'scripts'/name).read_text())
for p in (TASK/'input/Harness复审与补修').rglob('*'):
    if p.is_file():save('received-audit/'+p.relative_to(TASK/'input/Harness复审与补修').as_posix(),p.read_text())
input_files={}
for p in (TASK/'input/Harness复审与补修').rglob('*'):
    if p.is_file():
        name=p.relative_to(TASK/'input/Harness复审与补修').as_posix()
        input_files[name]={'received_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'audit_sha256':hashlib.sha256((OUT/'received-audit'/name).read_bytes()).hexdigest()}
save('INPUT_SHA256.json',json.dumps({'received_manifest_checked_files':23,'files':input_files},ensure_ascii=False,indent=2)+'\n')
for name in ('00_当前交接.md','01_修复与验证.md','02_复现与运行.md'):
    if (TASK/name).exists():save(name,(TASK/name).read_text())
for p in (TASK/'evidence').rglob('*'):
    if not p.is_file() or '__pycache__' in p.parts:continue
    relative=p.relative_to(TASK/'evidence')
    # Preserve final results and exact pre-fix behavior; temporary development attempts stay local.
    if relative.parts[0] in ('regression-01','after-six-01','combined-six','combined-regression','combined-latest-six','combined-latest-regression','combined-reconstructed'):continue
    if relative.name.endswith('-runner.txt'):continue
    if p.suffix not in ('.json','.xml','.txt'):continue
    if p.stat().st_size==0:continue
    save('evidence/'+relative.as_posix(),p.read_text())
for p in OUT.rglob('*'):
    if p.is_file():
        text=p.read_text();assert not any(v in text for v in identifiers|secrets), 'PRIVATE_VALUE_IN_EXPORT:'+str(p.relative_to(OUT))
        assert str(Path.home()) not in text, 'PRIVATE_PATH_IN_EXPORT'
save('EXPORT_BOUNDARY.json',json.dumps({'source_commit':SHA,'base_source':BASE,'source_files':len(files),'exact_private_values_scan_passed':True,'live_text_or_ids_included':False,'production_database_included':False,'configuration_or_credentials_included':False,'original_input_zip_sha256':'3651c6a13e04754b5ca03cf3edf8db290e5979fa7b010638fb7ffad6fe3317f4'},indent=2)+'\n')
print(json.dumps({'source_files':len(files),'export_files':sum(p.is_file() for p in OUT.rglob('*')),'scan_passed':True}))
