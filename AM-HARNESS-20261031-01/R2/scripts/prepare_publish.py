from pathlib import Path
import json,hashlib,subprocess
TASK=Path(__file__).resolve().parents[1];OUT=TASK/'review-export';UP=TASK/'upload';BARE=UP/'base.git';PREFIX='AM-HARNESS-20261031-01/R2/'
base=subprocess.check_output(['git','--git-dir',str(BARE),'rev-parse','FETCH_HEAD'],text=True).strip()
rows={};known=set()
for p in subprocess.check_output(['git','--git-dir',str(BARE),'ls-tree','-rz',base]).split(b'\0'):
 if not p:continue
 meta,path=p.split(b'\t',1);mode,kind,sha=meta.decode().split();rows[path.decode()]=(mode,kind,sha);known.add(sha)
if any(p.startswith(PREFIX) for p in rows):raise RuntimeError('TARGET_PREFIX_ALREADY_EXISTS')
entries=[];chunks=[];current=[];size=0
for p in sorted(OUT.rglob('*')):
 if not p.is_file():continue
 rel=p.relative_to(OUT).as_posix();data=p.read_bytes();sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest();mode='100755' if p.stat().st_mode&0o111 else '100644'
 entry={'path':PREFIX+rel,'mode':mode,'type':'blob'}
 if sha in known:entry['sha']=sha
 else:entry['content']=data.decode()
 n=len(json.dumps(entry,ensure_ascii=False).encode())
 if current and size+n>120000:chunks.append(current);current=[];size=0
 current.append(entry);size+=n
 entries.append({'path':rel,'mode':mode,'blob_sha':sha,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'existing_blob':sha in known})
if current:chunks.append(current)
for i,c in enumerate(chunks):(UP/f'chunk-{i:03}.json').write_text(json.dumps(c,ensure_ascii=False))
index={'prefix':PREFIX,'base_commit':base,'source_commit':'60f60f564080b75206cd80b35597c1d086925354','files':len(entries),'chunks':len(chunks),'entries':entries}
(UP/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'files':len(entries),'chunks':len(chunks),'new_blobs':sum(not e['existing_blob'] for e in entries),'max_chunk_bytes':max(len(json.dumps(c,ensure_ascii=False).encode()) for c in chunks)}))
