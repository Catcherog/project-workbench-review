#!/usr/bin/env python3
"""Check only this handoff package; does not exercise product behavior."""
from pathlib import Path
from html.parser import HTMLParser
import hashlib,json,re
root=Path(__file__).resolve().parent
digest=lambda b:hashlib.sha256(b).hexdigest()
manifest=json.loads((root/'baseline-manifest.json').read_text(encoding='utf-8'))
entries={}
for line in (root/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
    value,name=line.split('  ',1)
    p=root/name
    assert p.resolve().is_relative_to(root)
    assert name not in entries
    assert digest(p.read_bytes())==value,name
    entries[name]=value
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='SHA256SUMS.txt'}
assert set(entries)==actual,sorted(set(entries)^actual)
for entry in manifest['snapshots']:
    p=root/entry['path']
    assert digest(p.read_bytes())==entry['sha256'],entry['path']
    assert p.stat().st_size==entry['bytes']
assert manifest['productCommit']=='319869a4ae35be801ec3120884cefa2951d8ce19'
assert manifest['uiReviewCommit']=='0921a71ad60e2e3b300500acdbb5cd0d04ec0735'
release=json.loads((root/'source/core/release.json').read_text())
assert release['version']=='2.17.0-core.3'
assert release['build']=='20261014.uat-ui01.1'
source=(root/'source/ui/workbench-apple-glass.html').read_text()
assert digest(source.encode())=='2b20289aa64784788397e5cf0a2236b9d0ace3aacac3adec9ecf994f3c27e0e2'
class Frames(HTMLParser):
    def __init__(self):super().__init__();self.frames=[]
    def handle_starttag(self,tag,attrs):
        if tag=='iframe':self.frames.append(dict(attrs))
frames=Frames();frames.feed((root/'source/ui/preview/light.html').read_text())
assert len(frames.frames)==1
assert source.replace("appearance:'跟随系统'","appearance:'浅色'") in frames.frames[0]['data-srcdoc']
for p in list(root.glob('*.md')):
    for ref in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' in ref or ref.startswith('#'):continue
        assert (p.parent/ref.split('#')[0]).is_file(),(p.name,ref)
print(json.dumps({'status':'passed','packageFilesIncludingChecksumList':len(entries)+1,'manifestEntriesVerified':len(entries),'sourceSnapshotsVerified':len(manifest['snapshots']),'uiImages':4,'productTestsRerun':False,'browserTestsRerun':False},ensure_ascii=False))
