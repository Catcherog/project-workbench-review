"""Publishable R3 increment only; original private blind/review/auth data excluded."""
from pathlib import Path
import hashlib,json,re,subprocess,time,shutil
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1];OUT=TASK/'review-export'
if any(OUT.iterdir()):raise ValueError('Freeze existing export; use a new directory for rebuild')
SHA=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();BASE='aab37396ea86b6e742eed79369583801664d1f35'
private=Path.home()/'.local/share/local-qwen-feishu';settings=json.loads((private/'config.json').read_text());poc=json.loads(Path(settings['poc_config']).read_text())
identifiers=set();secrets=set()
def inspect(v,key=''):
    if isinstance(v,dict):
        for k,x in v.items():inspect(x,k)
    elif isinstance(v,list):
        for x in v:inspect(x,key)
    elif isinstance(v,str):
        if v.startswith(('ou_','oc_','od_','cli_','o-')) and len(v)>20:identifiers.add(v)
        if re.search(r'(?i)secret|password|access_token|refresh_token|api_key',key) and len(v)>12:secrets.add(v)
inspect(settings);inspect(poc)
redactions={v:v.split('_')[0]+'_SYNTHETIC_'+hashlib.sha256(('audit:'+v).encode()).hexdigest()[:12] for v in identifiers}
redactions.update({v:'SYNTHETIC_REDACTED_SECRET' for v in secrets})
redactions.update({str(ROOT):'/workspace/am',str(Path.home()):'/home/am','example.feishu.cn':'example.feishu.cn','SYNTHETIC_TH2_LEDGER_TOKEN':'SYNTHETIC_TH2_LEDGER_TOKEN','所有者':'所有者','AR900合成甲':'AR900合成甲'})
def redact(text):
    text=re.sub(r'/private/var/folders/[^/]+/[^/]+/T/','/tmp/audit/',text)
    text=re.sub(r'/var/folders/[^/]+/[^/]+/T/','/tmp/audit/',text)
    text=re.sub(r'pytest-of-[A-Za-z0-9_.-]+','pytest-of-audit',text)
    for k,v in sorted(redactions.items(),key=lambda x:-len(x[0])):text=text.replace(k,v)
    return text
def save(rel,text,mode=0o644):
    p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(redact(text));p.chmod(mode)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
changed=subprocess.check_output(['git','diff','--name-only',BASE,SHA],cwd=ROOT,text=True).splitlines();files={}
for rel in changed:
    assert rel.startswith(('am-conversation-r1/','am-style-r3/','am-harness-r1/','local-qwen3.8/feishu-bridge/'))
    p=ROOT/rel;save('source/'+rel,p.read_text(),p.stat().st_mode&0o777)
    files[rel]={'source_sha256':sha(p),'audit_sha256':sha(OUT/'source'/rel)}
save('SOURCE_SHA256.json',json.dumps({'source_commit':SHA,'base_source':BASE,'base_review_commit':'9ef8076b32ecb5800c70a4f531fa2a859fb6c790','kind':'incremental_overlay','files':files},indent=2)+'\n')
save('FINAL.diff',subprocess.check_output(['git','diff',BASE,SHA],cwd=ROOT,text=True))
for p in TASK.glob('*.md'):save(p.name,p.read_text())
for p in (TASK/'scripts').glob('*.py'):
    if p.name not in ('prepare_gold.py','preflight.py','inspect_codex.py','probe_codex_surface.py'):
        save('scripts/'+p.name,p.read_text())
# Calibration joins are local-only; export their hashes/counts, never originals.
evidence={}
for p in (TASK/'evidence').rglob('*'):
    if not p.is_file() or p.suffix not in ('.json','.xml','.log','.txt'):continue
    if p.name in ('published-commit.json','remote-readback.json'):continue
    text=p.read_text()
    if p.name=='data-preparation.json':
        value=json.loads(text);value['human_review'].pop('answer',None);value['human_review'].pop('review_request_id',None)
        text=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    rel='evidence/'+p.relative_to(TASK/'evidence').as_posix();save(rel,text)
    evidence[rel]={'original_sha256':sha(p),'audit_sha256':sha(OUT/rel)}
save('EVIDENCE_SHA256.json',json.dumps({'files':evidence,'scope':'sanitized observational evidence; public bytes are never reattached to a live proposal'},indent=2)+'\n')
save('input/frozen-comparison.json',(TASK/'input/frozen-comparison.json').read_text())
save('input/received-MANIFEST.json',(TASK/'input/AM-HARNESS-20261031-01_R3/MANIFEST.json').read_text())
for p in (TASK/'private/qwen-comparison').glob('*.json'):
    save('model-observations/'+p.name,p.read_text())
for p in (TASK/'private/training-data').glob('sft.*.jsonl'):
    save('data/'+p.name,p.read_text())
save('data/README.md','这两条为虚构事实上的真实人审 gold，train/dev 按原场景拆分保持。实际审批原文与随机揭盲键不公开；source/prompt/completion hash 保留。本轮没有 silver 或 DPO 行。\n')
for name in ('chunk_gated_delta.py','runtime_common.py'):
    save('scripts/mlx_helpers/'+name,(TASK/'private/sft-source'/name).read_text())
for p in OUT.rglob('*'):
    if p.is_file():
        t=p.read_text();assert not any(v in t for v in identifiers|secrets),str(p)
        assert str(Path.home()) not in t,str(p)
save('EXPORT_BOUNDARY.json',json.dumps({'source_commit':SHA,'source_files':len(files),'credentials_included':False,
    'real_business_data_included':False,'private_blind_pairs_or_key_included':False,'raw_human_reply_included':False,
    'model_weights_included':False,'exact_config_value_scan_passed':True,'public_data':'fictional model scenarios and deidentified human-review provenance'},indent=2)+'\n')
manifest={}
for p in OUT.rglob('*'):
    if p.is_file() and p.name!='MANIFEST.json':manifest[p.relative_to(OUT).as_posix()]={'sha256':sha(p),'bytes':p.stat().st_size,'mode':oct(p.stat().st_mode&0o777)}
save('MANIFEST.json',json.dumps({'source_commit':SHA,'files':manifest},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'source_overlay_files':len(files),'export_files':len(manifest)+1,'scan_passed':True}))
