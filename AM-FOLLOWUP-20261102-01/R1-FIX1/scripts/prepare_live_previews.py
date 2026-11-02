"""Request only owner-visible synthetic previews on the existing consumer."""
from pathlib import Path
import json,os,time,uuid,sqlite3,hashlib
TASK=Path(__file__).resolve().parents[1]
cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
poc=json.loads(Path(cfg['poc_config']).read_text());state=Path(poc['service']['root_directory'])/'state';queue=state/'followup-operator'
observed=json.loads((TASK/'private/live-inspect.json').read_text())
assert observed['ok'] and len(observed['groups'])==1
group=observed['groups'][0]
owner=poc['owner_open_id'] if 'owner_open_id' in poc else None
# Select the single explicitly known non-owner from the original two-member test
# group, using exact configured owner identity. Names are never authorization.
with sqlite3.connect('file:'+str(state/'gateway.sqlite3')+'?mode=ro',uri=True) as db:
 configured_owner=db.execute("SELECT DISTINCT owner_id FROM followup_previews LIMIT 1").fetchone()
if not owner:
 from fs_agent.config import Config
 owner=Config.load(Path(cfg['poc_config'])).owner
recipients=[p for p in group['people'] if p['id']!=owner]
assert len(recipients)==1
recipient=recipients[0]
results=[]
for channel in ('group','recipient_p2p'):
 label='fix1-preview-'+channel+'-'+uuid.uuid4().hex;p=queue/(label+'.request.json');tmp=p.with_suffix('.tmp')
 request={'operation':'validation_preview','group_id':group['id'],'recipient':recipient['id'],'channel':channel,'expires_at':time.time()+180}
 fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(request,f)
 tmp.replace(p);start=time.monotonic();out=queue/(label+'.result.json')
 while not out.exists() and time.monotonic()-start<150:time.sleep(.25)
 if not out.exists():raise RuntimeError('PREVIEW_PREPARATION_PENDING')
 result=json.loads(out.read_text());result.update(channel=channel,elapsed_seconds=time.monotonic()-start)
 results.append(result);print(json.dumps({k:v for k,v in result.items() if k not in ('nonce','item_id')},ensure_ascii=False),flush=True)
private=TASK/'private/live-previews.json';private.write_text(json.dumps({'group':group,'recipient':recipient,'results':results},ensure_ascii=False,indent=2));private.chmod(0o600)
summary={'source_commit':__import__('subprocess').check_output(['git','rev-parse','HEAD'],text=True).strip(),
 'previews':[{k:v for k,v in r.items() if k not in ('nonce','item_id')} for r in results],
 'recipient_identifiers':'retained privately; no engineer sends approved or performed by this script'}
(TASK/'evidence/live-preview-preparation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
