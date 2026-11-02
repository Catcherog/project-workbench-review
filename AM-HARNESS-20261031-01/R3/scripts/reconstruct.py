"""Verify fixed baseline and overlay hashes, then build an isolated review tree."""
from pathlib import Path
import argparse,hashlib,json,shutil
p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--overlay',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if a.output.exists():raise SystemExit('Output must not exist; do not overwrite a worktree')
def copy_verified(root):
    manifest=json.loads((root/'SOURCE_SHA256.json').read_text())
    for relative,row in manifest['files'].items():
        source=root/'source'/relative
        if source.is_symlink() or '..' in Path(relative).parts or Path(relative).is_absolute():raise ValueError('unsafe path')
        data=source.read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['audit_sha256']:raise ValueError('source fingerprint mismatch: '+relative)
        target=a.output/'source'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(source.stat().st_mode&0o777)
    return len(manifest['files'])
base=json.loads((a.baseline/'SOURCE_SHA256.json').read_text())
if base['source_commit']!='aab37396ea86b6e742eed79369583801664d1f35':raise ValueError('wrong R2-FIX2 baseline')
counts=[copy_verified(a.baseline),copy_verified(a.overlay)]
if (a.baseline/'fixtures').exists():shutil.copytree(a.baseline/'fixtures',a.output/'fixtures')
print(json.dumps({'baseline_files':counts[0],'overlay_files':counts[1],'output':str(a.output),'production_touched':False}))
