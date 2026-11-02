import argparse,subprocess,sys,os,json,hashlib,time,tempfile,shutil
from pathlib import Path
import xml.etree.ElementTree as ET
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
r=a.source.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
source_manifest=r.parent/'SOURCE_SHA256.json'
frozen=None
if source_manifest.exists():
    files=json.loads(source_manifest.read_text())['files']
    frozen=tempfile.TemporaryDirectory(prefix='am-harness-fix1-recheck-')
    target=Path(frozen.name)/'source'
    for relative,entry in files.items():
        data=(r/relative).read_bytes()
        assert hashlib.sha256(data).hexdigest()==entry['audit_sha256'], relative
        dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);dest.chmod((r/relative).stat().st_mode&0o777)
    r=target
studio=r/'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
base=Path(__file__).resolve().parents[3]
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=os.pathsep.join(str(x) for x in (studio/'src',studio/'tests',r/'am-conversation-r1/src',r/'local-qwen3.8/feishu-bridge')),AM_REFERENCE_ROOT=str((Path(__file__).resolve().parents[1]/'fixtures/reference_am') if (Path(__file__).resolve().parents[1]/'fixtures/reference_am').exists() else (base/'AM-HARNESS-20261031-01/R1/review-export/fixtures/reference_am')))
# Independent suites keep their own true return codes and complete JUnit.
commands={
'harness':[sys.executable,'-m','pytest',str(r/'am-harness-r1/tests'),'-q','-p','no:cacheprovider','--junitxml='+str(out/'harness.xml')],
'original':[sys.executable,'-m','pytest',str(studio/'tests'),'-q','-p','no:cacheprovider','--junitxml='+str(out/'original.xml')],
'conversation':[sys.executable,str(r/'am-conversation-r1/scripts/verify.py'),'--output-dir',str(out/'conversation')],
'r2':[sys.executable,'-m','pytest',str(r/'am-conversation-r1/tests'),'-q','-p','no:cacheprovider','--junitxml='+str(out/'r2.xml')]
}
from concurrent.futures import ThreadPoolExecutor
# Do not run suites in one interpreter: imported fixture modules would alias.
def execute(item):
    name,cmd=item
    with (out/(name+'.txt')).open('w') as f:code=subprocess.run(cmd,cwd=r,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
    return name,code
with ThreadPoolExecutor(max_workers=4) as pool:codes=dict(pool.map(execute,commands.items()))
summary={'returncodes':codes,'synthetic_only':True,'frozen_source_verified_before_run':len(files) if frozen else None,'tests_ran_in_temporary_copy':frozen is not None}
for name in ('harness','original','r2'):
    cases=list(ET.parse(out/(name+'.xml')).iter('testcase'))
    summary[name]={'tests':len(cases),'passed':sum(not any(x.find(tag) is not None for tag in ('failure','error','skipped')) for x in cases),'failures':[x.attrib.get('classname','')+'.'+x.attrib['name'] for x in cases if x.find('failure') is not None],'errors':[x.attrib.get('classname','')+'.'+x.attrib['name'] for x in cases if x.find('error') is not None],'skips':[x.attrib.get('classname','')+'.'+x.attrib['name'] for x in cases if x.find('skipped') is not None]}
summary['conversation']=json.loads((out/'conversation/validation.json').read_text())
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ('returncodes','harness','original','r2')},ensure_ascii=False))
sys.exit(1 if any(codes.values()) else 0)
