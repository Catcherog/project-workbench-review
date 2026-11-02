"""Export this task only; private conversations, databases and credentials excluded."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess
T=Path(__file__).resolve().parents[1];R=T.parents[1]
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
O=args.output.resolve();O.mkdir(parents=True,exist_ok=False)
BASE='9255a70154ca82c0b9e2c0dbdb14a90cf94cbbde'
def git(*values):return subprocess.check_output(['git',*values],cwd=R,text=True)
HEAD=git('rev-parse','HEAD').strip()
assert not git('status','--short','--untracked-files=no').strip()
settings=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
poc=json.loads(Path(settings['poc_config']).read_text())
identifiers=set();secrets=set()
def inspect(value,key=''):
 if isinstance(value,dict):
  for k,v in value.items():inspect(v,k)
 elif isinstance(value,list):
  for v in value:inspect(v,key)
 elif isinstance(value,str):
  if value.startswith(('ou_','oc_','od_','cli_','o-')) and len(value)>20:identifiers.add(value)
  if re.search(r'(?i)secret|password|access_token|refresh_token|api_key',key) and len(value)>12:secrets.add(value)
inspect(settings);inspect(poc)
redactions={v:v.split('_')[0]+'_SYNTHETIC_'+hashlib.sha256(('audit:'+v).encode()).hexdigest()[:12] for v in identifiers}
redactions.update({v:'SYNTHETIC_REDACTED_SECRET' for v in secrets})
redactions.update({str(R):'/workspace/am',str(Path.home()):'/home/am','example.feishu.cn':'example.feishu.cn',
 'SYNTHETIC_TH2_LEDGER_TOKEN':'SYNTHETIC_TH2_LEDGER_TOKEN','所有者':'所有者','AR900合成甲':'AR900合成甲',
 'AR901合成乙':'AR901合成乙','AR901 合成乙':'AR901 合成乙','合成乙':'合成乙','合成甲':'合成甲'})
def redact(text):
 text=re.sub(r'/(?:private/)?var/folders/[^/]+/[^/]+/T/','/tmp/audit/',text)
 text=re.sub(r'pytest-of-[A-Za-z0-9_.-]+','pytest-of-audit',text)
 for old,new in sorted(redactions.items(),key=lambda x:-len(x[0])):text=text.replace(old,new)
 return text
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(relative,text,mode=0o644):
 path=O/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(redact(text));path.chmod(mode)
changed=git('diff','--name-only',BASE,HEAD).splitlines();sources={}
for rel in changed:
 assert rel.startswith(('local-qwen3.8/feishu-bridge/','FS-AGENT-GROK-POC-20261017-01_R1_Studio/','docs/'))
 source=R/rel;assert source.is_file() and not source.is_symlink() and source.suffix in ('.py','.md','.json')
 save('source/'+rel,source.read_text(),source.stat().st_mode&0o777)
 sources[rel]={'source_sha256':sha(source),'audit_sha256':sha(O/'source'/rel)}
save('SOURCE_SHA256.json',json.dumps({'source_commit':HEAD,'base_source':BASE,'base_review_commit':'0641a282584a68f60ddaf198326fc431ba67ee13',
 'base_review_directory':'AM-HARNESS-20261031-01/R4','kind':'incremental_overlay','files':sources},indent=2)+'\n')
save('FINAL.diff',git('diff',BASE,HEAD))
save('OWNER_VALIDATION.diff',git('diff','c79384511b01fca9219d277f615d27f53b770db8',HEAD))
for name in ('00_当前交接.md','01_集成与复现.md','02_原失败分类.md','03_分层验收.md','04_模型观察.md','06_本人私聊联调回读.md'):
 save(name,(T/name).read_text())
for path in (T/'scripts').glob('*.py'):save('scripts/'+path.name,path.read_text())
pkg=T/'input/AM-FOLLOWUP-20261102-01_R1-FIX1-GPT'
for name in ('00_当前交接.md','01_详细架构与实现.md','02_验证结果.md','03_Codex真实环境验收.md','SOURCE_DELTA.json','PACKAGE_SHA256.json','LOCAL_COMMITS.txt','changes.patch'):
 save('received-design/'+name,(pkg/name).read_text())
for path in (pkg/'scripts').glob('*.py'):save('received-design/scripts/'+path.name,path.read_text())
evidence={}
for path in (T/'evidence').rglob('*'):
 if not path.is_file() or path.suffix not in ('.json','.xml','.log','.txt'):continue
 if path.name in ('source-status-before.txt','published-commit.json','remote-readback.json'):continue
 rel='evidence/'+path.relative_to(T/'evidence').as_posix();save(rel,path.read_text());evidence[rel]={'original_sha256':sha(path),'audit_sha256':sha(O/rel)}
save('EVIDENCE_SHA256.json',json.dumps({'files':evidence,'scope':'deidentified runtime metadata and synthetic model/test data; audit bytes distinct from original evidence'},indent=2)+'\n')
save('EXPORT_BOUNDARY.json',json.dumps({'source_commit':HEAD,'runtime_overlay_files':17,'source_overlay_files':len(sources),
 'credentials_included':False,'private_message_bodies_included':False,'runtime_databases_included':False,
 'public_data':'sanitized code, synthetic model scenarios, minimal runtime metadata and owner UAT acknowledgement',
 'publication_scope':'AM-FOLLOWUP-20261102-01/R1-FIX1/'},indent=2)+'\n')
for path in O.rglob('*'):
 if path.is_file():
  text=path.read_text();assert not any(v in text for v in identifiers|secrets),str(path)
  assert str(Path.home()) not in text,str(path)
  assert not re.search(r'\b(?:ou|oc|od|cli)_[a-f0-9]{24,}\b',text),str(path)
files={path.relative_to(O).as_posix():{'sha256':sha(path),'bytes':path.stat().st_size,'mode':oct(path.stat().st_mode&0o777)} for path in O.rglob('*') if path.is_file()}
save('MANIFEST.json',json.dumps({'source_commit':HEAD,'files':files},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'source_commit':HEAD,'source_overlay_files':len(sources),'export_files':len(files)+1,'privacy_scan_passed':True}))
