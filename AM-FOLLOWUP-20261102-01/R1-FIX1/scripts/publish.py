"""Single prefix, non-force publication; fresh remote object readback afterwards."""
from pathlib import Path
import subprocess,os,json,hashlib,time
T=Path(__file__).resolve().parents[1];O=T/os.environ.get('AM_REVIEW_DIRECTORY','review-export');U=T/'upload';U.mkdir(exist_ok=True)
B=U/'base.git';REPO='Catcherog/project-workbench-review';PREFIX='AM-FOLLOWUP-20261102-01/R1-FIX1/'
def call(args,**kw):return subprocess.check_output(args,**kw)
def api(path):return json.loads(call(['gh','api','repos/'+REPO+('/'+path if path else '')],text=True))
info=api('');assert info['permissions']['push'] and info['default_branch']=='main'
if not B.exists():
 subprocess.run(['git','init','--bare',str(B)],check=True,capture_output=True)
 subprocess.run(['git','--git-dir',str(B),'remote','add','origin','https://github.com/'+REPO+'.git'],check=True)
assert call(['git','--git-dir',str(B),'remote','get-url','origin'],text=True).strip()=='https://github.com/'+REPO+'.git'
manifest=json.loads((O/'MANIFEST.json').read_text());entries=[]
for rel in sorted([*manifest['files'],'MANIFEST.json']):
 p=O/rel;assert not p.is_symlink() and '..' not in Path(rel).parts and not Path(rel).is_absolute()
 raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest();mode='100755' if p.stat().st_mode&0o111 else '100644'
 if rel!='MANIFEST.json':assert digest==manifest['files'][rel]['sha256'] and len(raw)==manifest['files'][rel]['bytes']
 blob=call(['git','--git-dir',str(B),'hash-object','-w','--stdin'],input=raw).decode().strip()
 assert blob==hashlib.sha1(('blob '+str(len(raw))+'\0').encode()+raw).hexdigest()
 entries.append({'path':rel,'blob':blob,'sha256':digest,'mode':mode})
env=dict(os.environ,GIT_INDEX_FILE=str((U/'index').resolve()),GIT_AUTHOR_NAME='Project Review',GIT_AUTHOR_EMAIL='noreply@users.noreply.github.com',GIT_COMMITTER_NAME='Project Review',GIT_COMMITTER_EMAIL='noreply@users.noreply.github.com')
def git(*a,input=None):return call(['git','--git-dir',str(B),*a],env=env,input=input)
message=U/'message.txt';message.write_text('AM Followup R1-FIX1: verify owner private send and mobile feedback\n\nRecord one owner-approved private followup, two exact replies, one feedback record per reply and independently read-back mobile history. Preserve expired-card rejection and unthreaded-message boundaries. Runtime source is unchanged; model accuracy, independent-person and business acceptance remain incomplete.\n')
for _ in range(3):
 parent=api('git/ref/heads/main')['object']['sha']
 subprocess.run(['git','--git-dir',str(B),'fetch','--quiet','--depth=1','origin',parent],check=True,capture_output=True)
 existing=[x.decode() for x in git('ls-tree','-r','--name-only','-z',parent,'--',PREFIX).split(b'\0') if x]
 if existing:
  previous=json.loads((T/'evidence/published-commit.json').read_text())
  assert previous['prefix']==PREFIX,'UNEXPECTED_PREFIX_CONTENTS'
  subprocess.run(['git','--git-dir',str(B),'fetch','--quiet','--depth=2','origin',previous['review_commit']],check=True,capture_output=True)
  assert git('rev-parse',parent+':'+PREFIX.rstrip('/'))==git('rev-parse',previous['review_commit']+':'+PREFIX.rstrip('/')),'CONCURRENT_PREFIX_CHANGED'
 git('read-tree',parent)
 desired={PREFIX+e['path'] for e in entries}
 removals=b''.join(('0 '+'0'*40+'\t'+obsolete).encode()+b'\0' for obsolete in set(existing)-desired)
 if removals:git('update-index','-z','--index-info',input=removals)
 git('update-index','-z','--index-info',input=b''.join((e['mode']+' '+e['blob']+'\t'+PREFIX+e['path']).encode()+b'\0' for e in entries))
 tree=git('write-tree').decode().strip()
 changed=[x.decode() for x in git('diff-tree','--name-only','-r','-z',parent+'^{tree}',tree).split(b'\0') if x]
 assert changed and set(changed)<=desired|set(existing)
 commit=git('commit-tree',tree,'-p',parent,'-F',str(message)).decode().strip()
 if api('git/ref/heads/main')['object']['sha']!=parent:continue
 pushed=subprocess.run(['git','--git-dir',str(B),'-c','credential.helper=','-c','credential.helper=!gh auth git-credential','push','origin',commit+':refs/heads/main'],capture_output=True,text=True)
 if api('git/ref/heads/main')['object']['sha']==commit:break
 if pushed.returncode:raise RuntimeError('PUSH_FAILED: '+pushed.stderr[-1000:])
else:raise RuntimeError('CONCURRENT_HEAD_CHANGED')
published={'review_commit':commit,'source_commit':manifest['source_commit'],'parent_review_commit':parent,'prefix':PREFIX,'files':len(entries),'method':'native_git_after_connector_write_403','force_push':False,'published_at':time.time()}
(T/'evidence/published-commit.json').write_text(json.dumps(published,indent=2)+'\n');print(json.dumps(published),flush=True)
fresh=U/('remote-readback-'+commit+'.git');assert not fresh.exists()
subprocess.run(['git','init','--bare',str(fresh)],check=True,capture_output=True)
subprocess.run(['git','--git-dir',str(fresh),'fetch','--quiet','--depth=2','https://github.com/'+REPO+'.git',commit],check=True,capture_output=True)
actual={}
for record in call(['git','--git-dir',str(fresh),'ls-tree','-r','-z',commit,'--',PREFIX]).split(b'\0'):
 if not record:continue
 metadata,path=record.split(b'\t',1);mode,kind,blob=metadata.decode().split();actual[path.decode()]={'mode':mode,'blob':blob}
assert set(actual)=={PREFIX+e['path'] for e in entries}
for e in entries:
 full=PREFIX+e['path'];record=actual[full]
 assert record=={'mode':e['mode'],'blob':e['blob']}
 data=call(['git','--git-dir',str(fresh),'show',commit+':'+full])
 assert hashlib.sha256(data).hexdigest()==e['sha256']
changed=[x.decode() for x in call(['git','--git-dir',str(fresh),'diff-tree','--no-commit-id','--name-only','-r','-z',commit]).split(b'\0') if x]
assert changed and set(changed)<=set(actual)|set(existing)
proof=dict(published,verified_at=time.time(),fresh_remote_fetch=True,all_bytes_and_modes_match=True,only_requested_prefix_changed=True)
(T/'evidence/remote-readback.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof),flush=True)
