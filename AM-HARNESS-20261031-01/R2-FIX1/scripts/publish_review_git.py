"""Publish only the verified task prefix through the existing authorized Git login."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,time
TASK=Path(__file__).resolve().parents[1];UP=TASK/'upload';BARE=UP/'base.git';OUT=TASK/'review-export';REPO='Catcherog/project-workbench-review'
a=argparse.ArgumentParser();a.add_argument('--publish',action='store_true');args=a.parse_args()
index=json.loads((UP/'index.json').read_text());prefix=index['prefix'];assert prefix=='AM-HARNESS-20261031-01/R2-FIX1/'
def api(path):return json.loads(subprocess.check_output(['gh','api','repos/'+REPO+('/'+path if path else '')],text=True))
repo=api('');assert repo['permissions']['push'] and repo['default_branch']=='main'
assert subprocess.check_output(['git','--git-dir',str(BARE),'config','--get','remote.origin.url'],text=True).strip()=='https://github.com/'+REPO+'.git'
paths=[]
for e in index['entries']:
 p=OUT/e['path'];assert not p.is_symlink() and '..' not in Path(e['path']).parts and '.git' not in Path(e['path']).parts and '\n' not in str(p)
 raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==e['sha256'] and len(raw)==e['bytes'];assert e['mode'] in ('100644','100755');paths.append(str(p))
written=subprocess.check_output(['git','--git-dir',str(BARE),'hash-object','-w','--no-filters','--stdin-paths'],input='\n'.join(paths)+'\n',text=True).splitlines()
assert written==[e['blob_sha'] for e in index['entries']]
message=UP/'commit-message.txt';message.write_text('AM Harness R2-FIX1: audited outcome corrections and fixed validation evidence\n\nPreserve completed goal receipts, identity renewal, shadow isolation and native outbox authority. Include final source, frozen model observations and explicit remaining acceptance boundaries; new expression stays disabled.\n')
env=dict(os.environ,GIT_INDEX_FILE=str(UP/'publish-index'),GIT_AUTHOR_NAME='Project Review',GIT_AUTHOR_EMAIL='noreply@users.noreply.github.com',GIT_COMMITTER_NAME='Project Review',GIT_COMMITTER_EMAIL='noreply@users.noreply.github.com')
def git(*v,input=None):return subprocess.check_output(['git','--git-dir',str(BARE),*v],input=input,env=env)
for attempt in range(3):
 parent=api('git/ref/heads/main')['object']['sha']
 subprocess.run(['git','--git-dir',str(BARE),'fetch','--quiet','--depth=2','origin',parent],check=True,capture_output=True)
 assert not git('ls-tree','-r','--name-only',parent,'--',prefix).strip(),'TARGET_PREFIX_ALREADY_EXISTS'
 git('read-tree',parent)
 data=b''.join((e['mode']+' '+e['blob_sha']+'\t'+prefix+e['path']).encode()+b'\0' for e in index['entries'])
 git('update-index','-z','--index-info',input=data);tree=git('write-tree').decode().strip()
 changed=git('diff-tree','--name-only','-r','-z',parent+'^{tree}',tree).split(b'\0');changed=[x.decode() for x in changed if x]
 assert set(changed)=={prefix+e['path'] for e in index['entries']},'NON_TARGET_CHANGE'
 commit=git('commit-tree',tree,'-p',parent,'-F',str(message)).decode().strip()
 prepared={'review_commit':commit,'source_commit':index['source_commit'],'parent_review_commit':parent,'tree':tree,'prefix':prefix,'files':len(index['entries']),'local_manifest_sha256':hashlib.sha256((OUT/'MANIFEST.json').read_bytes()).hexdigest(),'method':'authorized_native_git_after_connector_integration_403','force_push':False,'prepared_at':time.time()}
 (UP/'publication-attempt.json').write_text(json.dumps(prepared,indent=2)+'\n')
 if not args.publish:print(json.dumps(dict(prepared,published=False)));raise SystemExit(0)
 if api('git/ref/heads/main')['object']['sha']!=parent:continue
 result=subprocess.run(['git','--git-dir',str(BARE),'-c','credential.helper=','-c','credential.helper=!gh auth git-credential','push','origin',commit+':refs/heads/main'],capture_output=True,text=True)
 head=api('git/ref/heads/main')['object']['sha']
 if head==commit:break
 if result.returncode and head==parent:raise RuntimeError('GIT_PUSH_FAILED: '+result.stderr[-1500:])
else:raise RuntimeError('CONCURRENT_REVIEW_HEAD_CHANGES')
# Keep the verified parent explicit for the separate fresh remote readback.
index['base_commit']=parent;index['base_tree']=git('rev-parse',parent+'^{tree}').decode().strip();(UP/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
prepared.update(published=True,published_at=time.time());(TASK/'evidence/published-commit.json').write_text(json.dumps(prepared,indent=2)+'\n');print(json.dumps(prepared))
