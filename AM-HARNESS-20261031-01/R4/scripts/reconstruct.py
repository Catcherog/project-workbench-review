"""Reconstruct the four fixed review layers, checking every packaged file first."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--review-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--r4-overlay', type=Path)
parser.add_argument('--followup-overlay', type=Path)
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Output must not exist; do not overwrite a worktree')
layers = [
    ('AM-HARNESS-20261031-01/R2-FIX2', 'aab37396ea86b6e742eed79369583801664d1f35'),
    ('AM-HARNESS-20261031-01/R3', '0ce6dcde237b669efbc263623fe4c95f068bd201'),
    ('AM-FOLLOWUP-20261102-01/R1', '73c1f9e11ec8b1ea9c3e36060a2522fab3676480'),
    ('AM-HARNESS-20261031-01/R4', '9255a70154ca82c0b9e2c0dbdb14a90cf94cbbde'),
]
combined, results, verified = {}, [], []
for relative, expected in layers:
    root = args.r4_overlay if relative.endswith('/R4') and args.r4_overlay else args.review_root / relative
    if relative == 'AM-FOLLOWUP-20261102-01/R1' and args.followup_overlay:
        root = args.followup_overlay
    if not (root / 'SOURCE_SHA256.json').is_file() and (root / 'review-export').is_dir():
        root = root / 'review-export'
    manifest = json.loads((root / 'MANIFEST.json').read_text())
    for name, row in manifest['files'].items():
        path = root / name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink():
            raise ValueError('Unsafe review path')
        data = path.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Review fingerprint mismatch: ' + name)
    source = json.loads((root / 'SOURCE_SHA256.json').read_text())
    if source['source_commit'] != expected:
        raise ValueError('Wrong source layer: ' + relative)
    for name, row in source['files'].items():
        path = root / 'source' / name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink():
            raise ValueError('Unsafe source path')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['audit_sha256']:
            raise ValueError('Source fingerprint mismatch: ' + name)
    verified.append((relative, root, source))
    results.append({'directory': relative, 'source_commit': expected,
                    'manifest_files_verified': len(manifest['files']), 'source_files': len(source['files'])})
# Do not expose a partial reconstruction if a later baseline layer is stale.
for relative, root, source in verified:
    for name, row in source['files'].items():
        path = root / 'source' / name
        target = args.output / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        target.chmod(path.stat().st_mode & 0o777)
        combined[name] = row
    if relative.endswith('/R2-FIX2') and (root / 'fixtures').is_dir():
        shutil.copytree(root / 'fixtures', args.output / 'fixtures')
(args.output / 'SOURCE_SHA256.json').write_text(json.dumps({'files': combined}, indent=2) + '\n')
report = {'layers': results, 'reconstructed_files': len(combined), 'production_touched': False}
(args.output / 'reconstruction.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
