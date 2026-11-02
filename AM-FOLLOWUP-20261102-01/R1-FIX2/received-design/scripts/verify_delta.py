#!/usr/bin/env python3
"""Read-only integration preflight. Never modifies the target checkout.

The exact prior bytes are required for an unreviewed application. A newer
checkout is not reset: divergent files are reported for a three-way merge.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_path(root, value):
    rel = PurePosixPath(value)
    if rel.is_absolute() or not rel.parts or any(p in ('..', '.') for p in rel.parts):
        raise ValueError('invalid_relative_path')
    path = root.joinpath(*rel.parts)
    if any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
        raise ValueError('symlink_path_requires_manual_review')
    path.resolve().relative_to(root)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--manifest', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'SOURCE_DELTA.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    results = []
    for entry in manifest['files']:
        path = checked_path(repo, entry['path'])
        actual = sha256(path) if path.is_file() else None
        if actual == entry['final_sha256']:
            state = 'already_applied'
        elif actual == entry['base_sha256'] and (actual is not None or not path.exists()):
            state = 'base_matches' if actual is not None else 'new_path_available'
        else:
            state = 'conflict_requires_merge'
        results.append({'path': entry['path'], 'state': state, 'actual_sha256': actual,
                        'base_sha256': entry['base_sha256'],
                        'final_sha256': entry['final_sha256']})
    conflicts = [v['path'] for v in results if v['state'] == 'conflict_requires_merge']
    report = {'mode': 'read_only', 'reference_source_commit': manifest['base_source_commit'],
              'conflicts': conflicts, 'files': results,
              'action': 'review_and_merge_conflicts' if conflicts else 'review_patch_then_git_apply_check'}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered, encoding='utf-8')
    print(rendered)
    return 1 if conflicts else 0


if __name__ == '__main__':
    sys.exit(main())
