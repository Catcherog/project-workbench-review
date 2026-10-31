from pathlib import Path
import subprocess,json,hashlib,os
TASK=Path(__file__).resolve().parents[1];OUT=TASK/'review-export';UP=TASK/'upload';BARE=UP/'base.git';PREFIX='AM-HARNESS-20261031-01/R2-FIX1/'
chunk_limit=int(os.environ.get('AM_REVIEW_TREE_CHUNK_BYTES','70000'));blob_threshold=int(os.environ.get('AM_REVIEW_BLOB_THRESHOLD','35000'))
assert 20000<=chunk_limit<=500000 and 20000<=blob_threshold<=250000
UP.mkdir(exist_ok=True);base=subprocess.check_output(['git','--git-dir',str(BARE),'rev-parse','HEAD'],text=True).strip();tree=subprocess.check_output(['git','--git-dir',str(BARE),'rev-parse',base+'^{tree}'],text=True).strip()
known=set();paths=[]
for part in subprocess.check_output(['git','--git-dir',str(BARE),'ls-tree','-rz',base]).split(b'\0'):
 if not part:continue
 meta,path=part.split(b'\t',1);mode,kind,sha=meta.decode().split();known.add(sha);paths.append(path.decode())
assert not any(p.startswith(PREFIX) for p in paths),'TARGET_PREFIX_ALREADY_EXISTS'
chunks=[];chunk=[];size=0;large=[];entries=[]
for p in sorted(OUT.rglob('*')):
 if not p.is_file():continue
 rel=p.relative_to(OUT).as_posix();data=p.read_bytes();sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest();mode='100755' if p.stat().st_mode&0o111 else '100644'
 entry={'path':PREFIX+rel,'mode':mode,'type':'blob'}
 if sha in known or len(data)>blob_threshold:
  entry['sha']=sha
  if sha not in known:large.append({'path':rel,'sha':sha,'bytes':len(data)})
 else:entry['content']=data.decode('utf-8')
 n=len(json.dumps(entry,ensure_ascii=False).encode())
 if chunk and size+n>chunk_limit:chunks.append(chunk);chunk=[];size=0
 chunk.append(entry);size+=n
 entries.append({'path':rel,'blob_sha':sha,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'mode':mode})
if chunk:chunks.append(chunk)
for i,c in enumerate(chunks):(UP/f'tree-chunk-{i:03}.json').write_text(json.dumps(c,ensure_ascii=False))
index={'batch_settings':{'chunk_bytes':chunk_limit,'blob_threshold':blob_threshold},'prefix':PREFIX,'base_commit':base,'base_tree':tree,'source_commit':json.loads((OUT/'SOURCE_SHA256.json').read_text())['source_commit'],'chunks':len(chunks),'large_blobs':list({r['sha']:r for r in large}.values()),'entries':entries}
(UP/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'files':len(entries),'chunks':len(chunks),'large_blobs':len(index['large_blobs']),'base':base,'tree':tree}))
