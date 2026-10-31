"""Only sanitized R2-FIX1 review artifacts. Never deploy this review copy."""
from pathlib import Path
import hashlib,json,re,subprocess,time
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1];SRC=TASK/'worktree';FINAL=TASK/'review-export';OUT=TASK/('review-export-build-'+str(time.time_ns()));OUT.mkdir()
SHA=subprocess.check_output(['git','rev-parse','HEAD'],cwd=SRC,text=True).strip();BASE='60f60f564080b75206cd80b35597c1d086925354'
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());pc=json.loads(Path(settings['poc_config']).read_text())
identifiers=set();secrets=set()
def inspect(v,key=''):
 if isinstance(v,dict):
  for k,x in v.items():inspect(x,k)
 elif isinstance(v,list):
  for x in v:inspect(x,key)
 elif isinstance(v,str):
  if v.startswith(('ou_','oc_','od_','cli_','o-')) and len(v)>20:identifiers.add(v)
  if re.search(r'(?i)secret|password|access_token|refresh_token|api_key',key) and len(v)>12:secrets.add(v)
inspect(settings);inspect(pc)
redactions={v:v.split('_')[0]+'_SYNTHETIC_'+hashlib.sha256(('audit:'+v).encode()).hexdigest()[:12] for v in identifiers}
redactions.update({v:'SYNTHETIC_REDACTED_SECRET' for v in secrets})
redactions.update({str(ROOT):'/workspace/am',str(Path.home()):'/home/am','example.feishu.cn':'example.feishu.cn','SYNTHETIC_TH2_LEDGER_TOKEN':'SYNTHETIC_TH2_LEDGER_TOKEN','所有者':'所有者','AR900合成甲':'AR900合成甲'})
def redact(text):
 text=re.sub(r'/private/var/folders/[^/]+/[^/]+/T/', '/tmp/audit/', text)
 text=re.sub(r'/var/folders/[^/]+/[^/]+/T/', '/tmp/audit/', text)
 text=re.sub(r'pytest-of-[A-Za-z0-9_.-]+', 'pytest-of-audit', text)
 for before,after in sorted(redactions.items(),key=lambda kv:-len(kv[0])):text=text.replace(before,after)
 return text
def save(name,text,mode=0o644):
 p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(redact(text));p.chmod(mode)
files={}
for part in subprocess.check_output(['git','ls-tree','-rz',SHA],cwd=SRC).split(b'\0'):
 if not part:continue
 meta,name=part.split(b'\t',1);name=name.decode();mode,kind,blob=meta.decode().split();fs='FS-AGENT-GROK-POC-20261017-01_R1_Studio/'
 allowed=(name.startswith((fs+'src/',fs+'tests/','am-conversation-r1/','am-harness-r1/')) or name in (fs+'pyproject.toml',fs+'uv.lock') or name.startswith(fs+'config/') and name.endswith('.example.json') or name.startswith('local-qwen3.8/feishu-bridge/') and (name.endswith('.py') or Path(name).name.startswith('requirements')))
 if not allowed or kind!='blob' or '__pycache__' in name or name.startswith('am-conversation-r1/integration/'):continue
 data=subprocess.check_output(['git','cat-file','blob',blob],cwd=SRC);save('source/'+name,data.decode(),int(mode,8)&0o777)
 files[name]={'source_sha256':hashlib.sha256(data).hexdigest(),'audit_sha256':hashlib.sha256((OUT/'source'/name).read_bytes()).hexdigest()}
fixtures=ROOT/'AM-HARNESS-20261031-01/R1/review-export/fixtures/reference_am'
for p in fixtures.rglob('*'):
 if p.is_file() and not p.is_symlink() and not any(x in p.parts for x in ('__pycache__','.pytest_cache')):save('fixtures/reference_am/'+p.relative_to(fixtures).as_posix(),p.read_text(),p.stat().st_mode&0o777)
save('SOURCE_SHA256.json',json.dumps({'source_commit':SHA,'base_source':BASE,'files':files},ensure_ascii=False,indent=2)+'\n')
save('FINAL.diff',subprocess.check_output(['git','diff',BASE,SHA],cwd=SRC,text=True))
MEASURED=json.loads((TASK/'input/evaluation-lock.json').read_text())['source_commit']
save('MEASURED_TO_FINAL.diff',subprocess.check_output(['git','diff',MEASURED,SHA],cwd=SRC,text=True))
measured_files={}
for name in files:
 data=subprocess.check_output(['git','show',MEASURED+':'+name],cwd=SRC)
 measured_files[name]={'source_sha256':hashlib.sha256(data).hexdigest(),'audit_sha256':hashlib.sha256(redact(data.decode()).encode()).hexdigest()}
save('MEASURED_SOURCE_SHA256.json',json.dumps({'source_commit':MEASURED,'reconstruct_from':'source/ plus reverse MEASURED_TO_FINAL.diff in an isolated audit copy only','files':measured_files},ensure_ascii=False,indent=2)+'\n')
for p in (TASK/'scripts').glob('*.py'):save('scripts/'+p.name,p.read_text())
inputs={}
for folder,prefix in [(ROOT/'AM-HARNESS-20261031-01/R2/input/am_harness_r2_design','input-design'),(TASK/'input','input')]:
 for p in folder.rglob('*'):
  if p.is_file() and not p.is_symlink() and p.suffix in ('.md','.json','.jsonl','.py','.sql','.mmd','.txt'):
   rel=prefix+'/'+p.relative_to(folder).as_posix();save(rel,p.read_text());inputs[rel]={'original_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'audit_sha256':hashlib.sha256((OUT/rel).read_bytes()).hexdigest()}
save('INPUT_SHA256.json',json.dumps({'requirement':'v2.0-design.1 + supplied independent R2 audit','files':inputs},ensure_ascii=False,indent=2)+'\n')
for p in TASK.glob('*.md'):
 if p.name!='WORK_STATE.md':save(p.name,p.read_text())
evidence_files={}
for p in (TASK/'evidence').rglob('*'):
 if p.is_file() and not p.is_symlink() and p.suffix in ('.json','.jsonl','.xml','.txt') and '__pycache__' not in p.parts and '.private.' not in p.name:
  rel='evidence/'+p.relative_to(TASK/'evidence').as_posix();save(rel,p.read_text())
  evidence_files[rel]={'original_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'audit_sha256':hashlib.sha256((OUT/rel).read_bytes()).hexdigest()}
save('EVIDENCE_SHA256.json',json.dumps({'files':evidence_files,'original_proposal_fingerprints_retained':True,'sanitized_text_is_not_a_new_proposal':'Do not attach new outcome hashes to old proposals. Public sanitized bytes have separate hashes; original prompt/candidate fingerprints refer to private originals.'},ensure_ascii=False,indent=2)+'\n')
for p in (TASK/'blind-public').glob('*'):
 if p.is_file() and not p.is_symlink() and p.suffix in ('.md','.html','.json','.txt'):save('blind/'+p.name,p.read_text())
for p in OUT.rglob('*'):
 if p.is_file():
  text=p.read_text();assert not any(v in text for v in identifiers|secrets),'PRIVATE_VALUE_IN_EXPORT:'+str(p.relative_to(OUT));assert str(Path.home()) not in text,'PRIVATE_PATH_IN_EXPORT'
save('EXPORT_BOUNDARY.json',json.dumps({'source_commit':SHA,'source_files':len(files),'exact_private_value_scan_passed':True,'production_database_included':False,'credentials_included':False,'real_chat_bodies_included':False,'model_inputs_synthetic':True,'unblinding_key_included':False,'private_original_blind_material_included':False},indent=2)+'\n')
manifest={}
for p in OUT.rglob('*'):
 if p.is_file() and not p.is_symlink() and p.relative_to(OUT).as_posix()!='MANIFEST.json':manifest[p.relative_to(OUT).as_posix()]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'mode':oct(p.stat().st_mode&0o777)}
save('MANIFEST.json',json.dumps({'source_commit':SHA,'files':manifest},ensure_ascii=False,indent=2)+'\n')
if FINAL.exists():FINAL.rename(TASK/('review-export-previous-'+str(time.time_ns())))
OUT.rename(FINAL)
print(json.dumps({'source_files':len(files),'review_files':len(manifest)+1,'scan_passed':True}))
