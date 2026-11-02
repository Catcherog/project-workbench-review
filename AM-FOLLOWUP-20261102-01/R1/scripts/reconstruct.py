"""Verify fixed review layers and compose a test-only tree, never production."""
from pathlib import Path
import argparse,hashlib,json,shutil
p=argparse.ArgumentParser();p.add_argument('--r2',type=Path,required=True);p.add_argument('--r3',type=Path,required=True);p.add_argument('--overlay',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if a.output.exists():raise ValueError('OUTPUT_MUST_NOT_EXIST')
def layer(root,expected=None):
 m=json.loads((root/'SOURCE_SHA256.json').read_text())
 if expected and m['source_commit']!=expected:raise ValueError('BASELINE_MISMATCH')
 for rel,v in m['files'].items():
  path=Path(rel);src=root/'source'/path
  if path.is_absolute() or '..' in path.parts or src.is_symlink():raise ValueError('UNSAFE_PATH')
  data=src.read_bytes()
  if hashlib.sha256(data).hexdigest()!=v['audit_sha256']:raise ValueError('SOURCE_HASH_MISMATCH')
  dst=a.output/'source'/path;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(data);dst.chmod(src.stat().st_mode&0o777)
 return len(m['files'])
counts=[layer(a.r2,'aab37396ea86b6e742eed79369583801664d1f35'),layer(a.r3,'0ce6dcde237b669efbc263623fe4c95f068bd201'),layer(a.overlay)]
shutil.copytree(a.r2/'fixtures',a.output/'fixtures')
print(json.dumps({'verified_layers':counts,'production_modified':False}))
