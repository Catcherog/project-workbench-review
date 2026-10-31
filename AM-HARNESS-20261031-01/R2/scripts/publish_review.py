"""Use the pre-existing project review credential; no secrets are exported."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,subprocess,hashlib,time
TASK=Path(__file__).resolve().parents[1];OUT=TASK/'review-export';UPLOAD=TASK/'upload';INDEX=json.loads((UPLOAD/'index.json').read_text());REPO='Catcherog/project-workbench-review';PREFIX=INDEX['prefix'];GH=Path.home()/'.local/bin/gh'
def api(path,method='GET',data=None):
 args=[str(GH),'api','repos/'+REPO+('/'+path if path else '')]
 if method!='GET':args+=['--method',method]
 if data is not None:args+=['--input','-']
 r=subprocess.run(args,input=json.dumps(data,ensure_ascii=False) if data is not None else None,text=True,capture_output=True)
 if r.returncode:raise RuntimeError('GITHUB_API_FAILED:'+path+':'+r.stderr[:200])
 return json.loads(r.stdout)
repo=api('');assert repo['permissions']['push'] and repo['default_branch']=='main'
for e in INDEX['entries']:
 data=(OUT/e['path']).read_bytes();assert hashlib.sha256(data).hexdigest()==e['sha256']
receipt=UPLOAD/'uploaded-blobs.json';completed=json.loads(receipt.read_text()) if receipt.exists() else {}
missing={e['blob_sha']:e for e in INDEX['entries'] if not e['existing_blob']}
def upload(e):
 data=api('git/blobs','POST',{'encoding':'utf-8','content':(OUT/e['path']).read_text()})
 assert data['sha']==e['blob_sha'];return data['sha'],e['path']
todo=[e for sha,e in missing.items() if sha not in completed]
with ThreadPoolExecutor(max_workers=4) as pool:
 for i,future in enumerate(as_completed([pool.submit(upload,e) for e in todo]),1):
  sha,path=future.result();completed[sha]=path;receipt.write_text(json.dumps(completed,ensure_ascii=False,indent=2)+'\n')
  if i%20==0 or i==len(todo):print(json.dumps({'uploaded_new_blobs':i,'total':len(todo)}),flush=True)
elements=[{'path':PREFIX+e['path'],'mode':e['mode'],'type':'blob','sha':e['blob_sha']} for e in INDEX['entries']]
for attempt in range(3):
 parent=api('git/ref/heads/main')['object']['sha'];parent_commit=api('git/commits/'+parent)
 subprocess.run(['git','--git-dir',str(UPLOAD/'base.git'),'fetch','--quiet','--depth=1','https://github.com/'+REPO+'.git',parent],check=True,capture_output=True)
 existing=subprocess.check_output(['git','--git-dir',str(UPLOAD/'base.git'),'ls-tree','-r','--name-only',parent,'--',PREFIX],text=True)
 assert not existing.strip(),'TARGET_PREFIX_ALREADY_EXISTS'
 tree=api('git/trees','POST',{'base_tree':parent_commit['tree']['sha'],'tree':elements})
 commit=api('git/commits','POST',{'message':'AM Harness R2 v2.0-design.1: incremental outcomes and response protocol; generation remains unaccepted','tree':tree['sha'],'parents':[parent],'author':{'name':'Project Review','email':'noreply@users.noreply.github.com'},'committer':{'name':'Project Review','email':'noreply@users.noreply.github.com'}})
 if api('git/ref/heads/main')['object']['sha']!=parent:continue
 try:api('git/refs/heads/main','PATCH',{'sha':commit['sha'],'force':False})
 except RuntimeError:
  head=api('git/ref/heads/main')['object']['sha']
  if head==commit['sha']:break
  if head==parent:raise
 else:break
else:raise RuntimeError('REVIEW_HEAD_CHANGED_REPEATEDLY')
sha=commit['sha'];published={'review_commit':sha,'source_commit':INDEX['source_commit'],'previous_review_head':parent,'files':INDEX['files'],'prefix':PREFIX}
(TASK/'evidence/published-commit.json').write_text(json.dumps(published,indent=2)+'\n');print(json.dumps(published),flush=True)
bare=UPLOAD/'readback.git';subprocess.run(['git','init','--bare','-q',str(bare)],check=True,capture_output=True)
subprocess.run(['git','--git-dir',str(bare),'fetch','--quiet','--depth=1','https://github.com/'+REPO+'.git',sha,parent],check=True,capture_output=True)
def rows(ref):
 result={}
 for part in subprocess.check_output(['git','--git-dir',str(bare),'ls-tree','-rz',ref]).split(b'\0'):
  if not part:continue
  meta,path=part.split(b'\t',1);mode,kind,blob=meta.decode().split();result[path.decode()]=(mode,kind,blob)
 return result
before=rows(parent);after=rows(sha)
assert {p:v for p,v in before.items() if not p.startswith(PREFIX)}=={p:v for p,v in after.items() if not p.startswith(PREFIX)}
expected={PREFIX+e['path']:e for e in INDEX['entries']};actual={p:v for p,v in after.items() if p.startswith(PREFIX)};assert set(actual)==set(expected)
for path,(mode,kind,blob) in actual.items():
 e=expected[path];assert (mode,kind,blob)==(e['mode'],'blob',e['blob_sha'])
 data=subprocess.check_output(['git','--git-dir',str(bare),'cat-file','blob',blob]);assert hashlib.sha256(data).hexdigest()==e['sha256'] and data==(OUT/e['path']).read_bytes()
record=dict(published,remote_bytes_and_modes_match=True,readback_files=len(actual),non_target_paths_unchanged=True,verified_at=time.time())
(TASK/'evidence/remote-readback.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
