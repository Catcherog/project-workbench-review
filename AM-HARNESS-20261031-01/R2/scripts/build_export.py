"""Rebuild only the explicitly authorized, sanitized R2 review directory."""
from pathlib import Path
import hashlib,json,re,subprocess,time
ROOT=Path(__file__).resolve().parents[3];TASK=ROOT/'AM-HARNESS-20261031-01/R2';FINAL=TASK/'review-export';OUT=TASK/('review-export-build-'+str(time.time_ns()));OUT.mkdir()
SHA='60f60f564080b75206cd80b35597c1d086925354';BASE='714b1af93a2cb4090f3c8166296455c0035d5730';FIX1='d3e40b0d27517d75e850613c4eaecec107efa0ea'
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
 if p.is_file() and not any(x in p.parts for x in ('__pycache__','.pytest_cache')):save('fixtures/reference_am/'+p.relative_to(fixtures).as_posix(),p.read_text(),p.stat().st_mode&0o777)
save('SOURCE_SHA256.json',json.dumps({'source_commit':SHA,'base_source':BASE,'fix1_source':FIX1,'files':files},ensure_ascii=False,indent=2)+'\n')
for name,base in [('FINAL.diff',BASE),('FIX1_TO_CURRENT.diff',FIX1)]:save(name,subprocess.check_output(['git','diff',base,SHA],cwd=ROOT,text=True))
for p in (TASK/'scripts').glob('*.py'):save('scripts/'+p.name,p.read_text())
inputs={}
for p in (TASK/'input/am_harness_r2_design').rglob('*'):
 if p.is_file() and p.suffix in ('.md','.json','.jsonl','.py','.sql','.mmd','.txt'):
  rel=p.relative_to(TASK/'input/am_harness_r2_design').as_posix();save('input-design/'+rel,p.read_text())
  inputs[rel]={'original_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'audit_sha256':hashlib.sha256((OUT/'input-design'/rel).read_bytes()).hexdigest()}
save('INPUT_SHA256.json',json.dumps({'zip_sha256':'c206fc20fd078478df0a589a49d871f2f659f4a1f9c9713139563e52bce1ada3','version':'v2.0-design.1','files':inputs},ensure_ascii=False,indent=2)+'\n')
for p in TASK.glob('*.md'):save(p.name,p.read_text())
include={'before','final-source-02','final-reconstructed-02','model-pairs','model-pairs-01','host-cases','input-baseline.json','runtime-before.json','runtime-after.json','runtime-final.json','install-result.json','L0-reference.txt','response-final.xml','regression-comparison.json','task-family-metrics.json','wiring-matrix.json','topology.json','model-summary.json','uncompleted.json','runtime-loaded-map.json','legacy-channels.xml','channel-outcomes.xml','install-initial.json'}
for p in (TASK/'evidence').rglob('*'):
 if not p.is_file():continue
 relative=p.relative_to(TASK/'evidence')
 if relative.parts[0] not in include or p.suffix not in ('.json','.xml','.txt'):continue
 if relative.parts[0]=='final-reconstructed-02':relative=Path('final-reconstructed')/Path(*relative.parts[1:])
 save('evidence/'+relative.as_posix(),p.read_text())
for p in OUT.rglob('*'):
 if p.is_file():
  text=p.read_text();assert not any(v in text for v in identifiers|secrets),'PRIVATE_VALUE_IN_EXPORT:'+str(p.relative_to(OUT));assert str(Path.home()) not in text,'PRIVATE_PATH_IN_EXPORT'
save('EXPORT_BOUNDARY.json',json.dumps({'source_commit':SHA,'source_files':len(files),'exact_private_values_scan_passed':True,'real_chat_bodies_included':False,'production_database_included':False,'credentials_included':False,'model_pairs_synthetic_only':True},indent=2)+'\n')
manifest={}
for p in OUT.rglob('*'):
 if p.is_file() and p.relative_to(OUT).as_posix()!='MANIFEST.json':manifest[p.relative_to(OUT).as_posix()]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'mode':oct(p.stat().st_mode&0o777)}
save('MANIFEST.json',json.dumps({'source_commit':SHA,'files':manifest},ensure_ascii=False,indent=2)+'\n')
if FINAL.exists():FINAL.rename(TASK/('review-export-previous-'+str(time.time_ns())))
OUT.rename(FINAL)
print(json.dumps({'source_files':len(files),'review_files':len(manifest)+1,'scan_passed':True}))
