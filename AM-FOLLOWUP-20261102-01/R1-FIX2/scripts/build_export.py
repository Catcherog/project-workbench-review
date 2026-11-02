"""Export the explicit source delta and minimal, redacted review evidence."""
from pathlib import Path
import hashlib,json,re,shutil,subprocess

T=Path(__file__).resolve().parents[1];R=T.parents[1];O=T/'review-export'
P=T/'input/AM-FOLLOWUP-R1-FIX2'
O.mkdir(exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest()
source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip()
assert source_commit=='295873a26842d696d96037af0f5a17ec913f4401'
assessment=json.loads((T/'evidence/model-assessment.json').read_text())
lines=['# 真实 Qwen 逐例观察','',
       '原模型及原协调器共 20 次新调用，每例只跑一次；原 13 输入与上轮逐字一致，另加 7 个开发后新写变体。所有业务输入均为合成，候选写临时验证库，没有生产事实写入或平台外发。',
       '', '11 例产生 34 个 unconfirmed 候选，9 例整段进入可见待核；门禁接受率不等于理解准确率。期望由 Codex 预先书写，未取得用户人工金标准，以下为逐项观察，不是独立人工验收。',
       '', '| 场景 | 本轮结果 | 逐项观察 |', '| --- | --- | --- |']
for c in assessment['cases']:
    gate=f"{c['committed_candidates']} 个待核候选" if c['gate']=='done' else '可见待核，零候选'
    lines.append(f"| [{c['case']}](evidence/qwen-native/{c['case']}.json) | {gate} | {c['observation']} |")
lines+=['','本批宿主排队到模型结果回读的耗时为 %.3f–%.3f 秒，中位数 %.3f 秒。不同场景单次观察，不构成模型性能验收。'%(assessment['latency_seconds']['min'],assessment['latency_seconds']['max'],assessment['latency_seconds']['median']),
        '', 'F07/F09 相比上轮不再因既有分类兼容问题拒绝。NEGATION 本轮补回更正内容，MULTIPROJECT 明示不完整并保留歧义原句；但转述和归属问题仍在。V02 新发现合同误拒，详见 [未完成项](04_未完成项.md)。',
        '', '冻结 7 例重放另列，不能混入以上 20 次新推理。所有原始 prompt/schema、prompt hash、完整模型输出、原模型摘要、宿主 PID、用量、候选/gap 和受测源码指纹均随逐例证据保留。']
(T/'02_真实模型观察.md').write_text('\n'.join(lines)+'\n')

def copy(source,target,exact=False):
    target.parent.mkdir(parents=True,exist_ok=True)
    b=source.read_bytes()
    if not exact:
        s=b.decode('utf-8').replace(str(R),'<SOURCE_ROOT>').replace(str(Path.home()),'<HOME>')
        b=s.encode('utf-8')
    target.write_bytes(b);target.chmod(0o644)

for f in sorted(T.glob('[0-9][0-9]_*.md')):copy(f,O/f.name)
for f in P.rglob('*'):
    if f.is_file():copy(f,O/'received-design'/f.relative_to(P),exact=True)
delta=json.loads((P/'SOURCE_DELTA.json').read_text());source={}
for entry in delta['files']:
    path=entry['path'];b=(R/path).read_bytes();assert sha(b)==entry['final_sha256']
    copy(R/path,O/'source'/path,exact=True);source[path]={'sha256':sha(b),'bytes':len(b)}
(O/'SOURCE_SHA256.json').write_text(json.dumps({'source_commit':source_commit,'files':source},indent=2)+'\n')
references={}
for name in ('am_views.py','am_presentation.py'):
    path='local-qwen3.8/feishu-bridge/'+name;b=(R/path).read_bytes()
    copy(R/path,O/'reference-source'/path,exact=True);references[path]={'sha256':sha(b),'bytes':len(b),'modified_this_round':False}
(O/'REFERENCE_SOURCE_SHA256.json').write_text(json.dumps({'source_commit':source_commit,'files':references},indent=2)+'\n')
diff=subprocess.check_output(['git','diff','--binary','4009a3ab2dc79b969ce7bf96502866dad8478072',source_commit,'--'],cwd=R)
(O/'FINAL.diff').write_bytes(diff)
for f in (T/'evidence').rglob('*'):
    if f.is_file() and f.suffix in ('.json','.xml','.log') and f.name not in ('published-commit.json','remote-readback.json','navigation-check.log','comparison.log'):
        copy(f,O/'evidence'/f.relative_to(T/'evidence'))
for f in (T/'scripts').glob('*.py'):copy(f,O/'scripts'/f.name)

# Fail closed on exact production identifiers/secrets; never copy their values
# into the review package or print them in errors.
cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
poc=json.loads(Path(cfg['poc_config']).read_text())
blocked=set()
def visit(value,key=''):
    if isinstance(value,dict):
        for k,v in value.items():visit(v,k)
    elif isinstance(value,list):
        for v in value:visit(v,key)
    elif isinstance(value,str) and len(value)>8 and (re.search(r'secret|access_token|refresh_token',key,re.I) or re.fullmatch(r'(?:ou_|oc_|od_|cli_)[A-Za-z0-9]{16,}',value)):
        blocked.add(value)
visit(cfg);visit(poc)
leaks=[]
for f in O.rglob('*'):
    if not f.is_file():continue
    s=f.read_text()
    if any(value in s for value in blocked) or re.search(r'\b(?:ou_|oc_)[a-f0-9]{32}\b',s):leaks.append(str(f.relative_to(O)))
assert not leaks,{'private_identifier_matches_in_files':leaks}
manifest={'task':'AM-FOLLOWUP-20261102-01','round':'R1-FIX2','source_commit':source_commit,
          'scope':'requested prefix only; no runtime database, raw private message or exact private identity',
          'files':{}}
for f in sorted(O.rglob('*')):
    if f.is_file() and f.name!='MANIFEST.json':manifest['files'][str(f.relative_to(O))]={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size,'mode':'100644'}
(O/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'export_files_including_manifest':len(manifest['files'])+1,'source_files':len(source),'reference_files':len(references),'private_identifier_scan':'passed','source_commit':source_commit}))
