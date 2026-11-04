"""Read-only comparison of this delivery manifest with a current source tree."""
from argparse import ArgumentParser
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    result = []
    for entry in manifest['files']:
        relative = PurePosixPath(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('invalid manifest path')
        path = (repo / str(relative)).resolve()
        if not path.is_relative_to(repo):
            raise ValueError('manifest path escapes repository')
        if path.exists() and not path.is_file():
            status, actual = 'current_path_is_not_a_file', None
        else:
            actual = sha256(path.read_bytes()).hexdigest() if path.exists() else None
            if actual == entry['after_sha256']:
                status = 'already_applied'
            elif actual == entry['before_sha256']:
                status = 'new_path_available' if actual is None else 'before_matches'
            else:
                status = 'current_differs'
        result.append({'path': str(relative), 'status': status, 'current_sha256': actual,
                       'before_sha256': entry['before_sha256'], 'after_sha256': entry['after_sha256']})
    conflicts = [r['path'] for r in result if r['status'] in ('current_differs', 'current_path_is_not_a_file')]
    print(json.dumps({'read_only': True, 'files': result, 'conflicts': conflicts,
                      'action': 'Preserve current changes and merge conflicts individually.' if conflicts
                                else 'Inspect git apply --check before applying the patch.'},
                     ensure_ascii=False, indent=2))
    return 2 if conflicts else 0


if __name__ == '__main__':
    raise SystemExit(main())
