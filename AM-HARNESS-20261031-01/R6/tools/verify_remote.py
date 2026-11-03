"""Read back a fixed AM R6 review commit and verify every delivered byte.

Read-only GitHub access. This script never creates commits, branches, or files
in the review repository. The local JSON receipt is explicitly requested.
"""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPOSITORY = 'Catcherog/project-workbench-review'
PREFIX = 'AM-HARNESS-20261031-01/R6/'


def read(url):
    request = Request(url, headers={'User-Agent':'AM-R6-fixed-review-readback',
                                   'Accept':'application/vnd.github+json'})
    with urlopen(request, timeout=30) as response:
        return response.read()


def tree(commit):
    result=json.loads(read('https://api.github.com/repos/'+REPOSITORY+'/git/trees/'+commit+'?recursive=1'))
    if result.get('truncated'):
        raise RuntimeError('remote_tree_truncated; obtain complete tree before accepting preservation')
    return {entry['path']:entry['sha'] for entry in result['tree'] if entry['type']=='blob'}


def main():
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--commit',required=True)
    parser.add_argument('--base-sha',required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    for value in (args.commit,args.base_sha):
        if not re.fullmatch('[0-9a-f]{40}',value):parser.error('use exact lowercase 40-character commit SHA')
    root=args.package.resolve(strict=True)
    receipt=args.receipt.resolve()
    if receipt.is_relative_to(root):parser.error('keep the readback receipt outside the immutable package')
    manifest=json.loads((root/'MANIFEST_SHA256.json').read_text(encoding='utf-8'))
    expected={}
    for entry in manifest['files']:
        relative=PurePosixPath(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('invalid package path')
        path=root/str(relative)
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('invalid package link')
        actual=sha256(path.read_bytes()).hexdigest()
        if actual!=entry['sha256']:raise ValueError('local package mismatch: '+str(relative))
        expected[str(relative)]=actual
    expected['MANIFEST_SHA256.json']=sha256((root/'MANIFEST_SHA256.json').read_bytes()).hexdigest()
    actual_paths={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual_paths!=set(expected):raise ValueError('package contains unlisted or missing files')

    def one(pair):
        relative,wanted=pair
        url='https://raw.githubusercontent.com/'+REPOSITORY+'/'+args.commit+'/'+quote(PREFIX+relative,safe='/')
        try:
            body=read(url)
            actual=sha256(body).hexdigest()
            return {'path':PREFIX+relative,'expected_sha256':wanted,'actual_sha256':actual,
                    'bytes':len(body),'matched':actual==wanted}
        except (HTTPError,URLError,TimeoutError) as error:
            return {'path':PREFIX+relative,'matched':False,'error':type(error).__name__,
                    'http_status':getattr(error,'code',None)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        files=list(pool.map(one,sorted(expected.items())))
    before,after=tree(args.base_sha),tree(args.commit)
    changed_other_paths=sorted(path for path in set(before)|set(after)
        if not path.startswith(PREFIX) and before.get(path)!=after.get(path))
    remote_paths={p[len(PREFIX):] for p in after if p.startswith(PREFIX)}
    result={'repository':REPOSITORY,'commit':args.commit,'parent_review_baseline':args.base_sha,
        'task_prefix':PREFIX,'verified_files':sum(f['matched'] for f in files),'expected_files':len(files),
        'all_files_match':all(f['matched'] for f in files),'remote_task_file_set_matches':remote_paths==set(expected),
        'changed_other_paths':changed_other_paths,'other_task_directories_unchanged':not changed_other_paths,
        'files':files,'fixed_review_url':'https://github.com/'+REPOSITORY+'/blob/'+args.commit+'/'+PREFIX+'00_当前交接.md'}
    result['success']=(result['all_files_match'] and result['remote_task_file_set_matches']
                       and result['other_task_directories_unchanged'])
    receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False,indent=2))
    return 0 if result['success'] else 1


if __name__=='__main__':raise SystemExit(main())
