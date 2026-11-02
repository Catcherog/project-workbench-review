"""Read every byte and mode from a fresh fetch of the published fixed commit."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,time
TASK=Path(__file__).resolve().parents[1]
a=argparse.ArgumentParser();a.add_argument('commit');args=a.parse_args()
assert re.fullmatch('[0-9a-f]{40}',args.commit)
idx=json.loads((TASK/'upload/index.json').read_text());prefix=idx['prefix'];bare=TASK/'upload/readback.git'
def git(*v):return subprocess.check_output(['git','--git-dir',str(bare),*v])
if not bare.exists():subprocess.run(['git','init','--bare','-q',str(bare)],check=True,capture_output=True)
subprocess.run(['git','--git-dir',str(bare),'fetch','--depth=2','https://github.com/Catcherog/project-workbench-review.git',args.commit],check=True,capture_output=True)
parent=git('rev-parse',args.commit+'^').decode().strip();assert parent==idx['base_commit']
def entries(ref):
 out={}
 for part in git('ls-tree','-rz',ref).split(b'\0'):
  if not part:continue
  head,path=part.split(b'\t',1);mode,kind,sha=head.decode().split();out[path.decode()]=(mode,kind,sha)
 return out
before=entries(parent);after=entries(args.commit)
assert {k:v for k,v in before.items() if not k.startswith(prefix)}=={k:v for k,v in after.items() if not k.startswith(prefix)}
actual={k[len(prefix):]:v for k,v in after.items() if k.startswith(prefix)}
expected={r['path']:r for r in idx['entries']};assert set(actual)==set(expected)
verified=[]
for path in sorted(expected):
 e=expected[path];mode,kind,sha=actual[path];assert kind=='blob' and mode==e['mode'] and sha==e['blob_sha']
 data=git('cat-file','blob',sha);assert len(data)==e['bytes'] and hashlib.sha256(data).hexdigest()==e['sha256']
 assert data==(TASK/'review-export'/path).read_bytes()
 verified.append({'path':path,'blob_sha':sha,'sha256':e['sha256'],'bytes':len(data),'mode':mode})
record={'review_commit':args.commit,'source_commit':idx['source_commit'],'parent_review_commit':parent,'remote_bytes_and_modes_match':True,'readback_files':len(verified),'readback_bytes':sum(r['bytes'] for r in verified),'non_target_paths_unchanged':True,'verified_at':time.time(),'entries':verified}
(TASK/'evidence/remote-readback.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in record.items() if k!='entries'},ensure_ascii=False))
