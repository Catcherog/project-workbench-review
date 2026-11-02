#!/usr/bin/env python3
"""Read-only inventory before integrating a sanitized review-source delta.

Never copies files or mutates a checkout. A differing baseline requires a
per-hunk merge in the real repository, preserving newer code and real IDs.
"""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parents[1] / 'SOURCE_DELTA.json')
    args = parser.parse_args()
    root = args.repo.resolve()
    manifest = json.loads(args.manifest.read_text())
    results = []
    for item in manifest['files']:
        relative = Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid manifest path')
        path = root / relative
        if not path.resolve().is_relative_to(root):
            raise ValueError('Target escapes repository')
        current = sha(path)
        state = ('already_final' if current == item['final_sha256'] else
                 'base_matches' if current == item['baseline_sha256'] else 'needs_merge')
        results.append({'path': item['path'], 'state': state, 'current_sha256': current})
    print(json.dumps({'read_only': True, 'files': results,
        'note': 'Review source may be sanitized. Preserve real configuration and newer work; do not overwrite full files.'},
        ensure_ascii=False, indent=2))
    return 1 if any(r['state'] == 'needs_merge' for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
