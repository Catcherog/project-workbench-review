#!/usr/bin/env python3
"""Verify the published R2 material, optionally against the adjacent fixed R1."""
from pathlib import Path
from html.parser import HTMLParser
import argparse, difflib, hashlib, json, re

root=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--r1',type=Path)
args=parser.parse_args()
digest=lambda b:hashlib.sha256(b).hexdigest()
manifest=json.loads((root/'source-manifest.json').read_text(encoding='utf-8'))
source=(root/'source/workbench-apple-glass.html').read_text(encoding='utf-8')
assert digest(source.encode())==manifest['source_public_after_sha256']
entries={}
for line in (root/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
    expected,name=line.split('  ',1)
    target=root/name
    assert target.resolve().is_relative_to(root.resolve())
    assert digest(target.read_bytes())==expected,name
    assert name not in entries
    entries[name]=expected
actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p.name!='SHA256SUMS.txt'}
assert set(entries)==actual

class Frames(HTMLParser):
    def __init__(self):super().__init__();self.frames=[]
    def handle_starttag(self,tag,attrs):
        if tag=='iframe':self.frames.append(dict(attrs))
for item in manifest['exports']:
    out=root/item['file'];html=out.read_text(encoding='utf-8')
    assert digest(out.read_bytes())==item['sha256']
    parsed=Frames();parsed.feed(html)
    assert len(parsed.frames)==1
    expected=source.replace("failure:'正常结果'","failure:'"+item['preset']['failure']+"'").replace("appearance:'跟随系统'","appearance:'"+item['preset']['appearance']+"'")
    assert digest(expected.encode())==item['embedded_fragment_sha256']
    assert expected in parsed.frames[0]['data-srcdoc']
    assert parsed.frames[0]['sandbox']=='allow-scripts'

checks=json.loads((root/'evidence/r2-browser-checks.json').read_text(encoding='utf-8'))
assert checks['source_sha256']==manifest['source_public_after_sha256']
assert checks['total']==32 and len(checks['checks'])==32
assert len({c['id'] for c in checks['checks']})==32
assert all(c['passed'] and c['source_sha256']==manifest['source_public_after_sha256'] for c in checks['checks'])
images=json.loads((root/'evidence/screenshot-manifest.json').read_text(encoding='utf-8'))
assert len(images['images'])==4 and images['fresh_capture']
for im in images['images']:
    assert im['source_sha256']==manifest['source_public_after_sha256']
    assert digest((root/im['file']).read_bytes())==im['sha256']

baseline='not supplied'
if args.r1:
    old=(args.r1/'source/workbench-apple-glass.html').read_text(encoding='utf-8')
    assert digest(old.encode())==manifest['source_public_before_sha256']
    expected=''.join(difflib.unified_diff(old.splitlines(True),source.splitlines(True),fromfile='a/source/workbench-apple-glass.html',tofile='b/source/workbench-apple-glass.html'))
    assert expected==(root/'changes.patch').read_text(encoding='utf-8')
    assert old.split('<script>')[0]==source.split('<script>')[0]
    assert re.search(r'let parsedDate=.*?if\(s.image',old,re.S)[0]==re.search(r'let parsedDate=.*?if\(s.image',source,re.S)[0]
    baseline='PASS: fixed R1 hash, exact diff, unchanged shell/CSS/time matcher'
print(json.dumps({'files_verified':len(entries),'exports_verified':5,'browser_evidence_records':32,'screenshots_verified':4,'r1_comparison':baseline,'note':'Package consistency only; this script does not rerun browser or product tests.'},ensure_ascii=False))
