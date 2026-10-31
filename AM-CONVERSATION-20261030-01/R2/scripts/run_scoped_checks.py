"""Run the final R2 group against a selected frozen source tree, without network."""
import argparse
import json
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();root=a.source_root.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
sys.dont_write_bytecode=True
studio=root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
sys.path[:0]=[str(root/'am-conversation-r1/src'),str(root/'am-conversation-r1/tests'),
    str(root/'local-qwen3.8/feishu-bridge'),str(studio/'src'),str(studio/'tests')]
import pytest
import lark_oapi  # Dependency architecture discovery is completed before the guard.
def offline(event,args):
    if event=='subprocess.Popen' and args[1]==[sys.executable,'-m','am_conversation','demo','--json']:
        return  # Existing CLI fixture uses ScriptedModel and temporary SQLite only.
    if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','os.posix_spawn'}:
        raise RuntimeError('R2_OFFLINE_CHECK_BLOCKED:'+event)
sys.addaudithook(offline)
files=[root/'am-conversation-r1/tests',studio/'tests/test_conversation_fix1.py',studio/'tests/test_harness_host.py']
files += [root/('am-harness-r1/tests/test_'+name+'.py') for name in ('am_adapter','fastpath','install','history_adapter')]
started=time.time();code=pytest.main([*[str(x) for x in files],'-q','--tb=short','-p','no:cacheprovider',
    '--junitxml='+str(out/'scoped.xml')])
tree=ET.parse(out/'scoped.xml');cases=tree.findall('.//testcase')
result={'exit_code':code,'case_count':len(cases),'passed':sum(not any(x.tag in ('failure','error','skipped') for x in c) for c in cases),
    'failures':len(tree.findall('.//failure')),'errors':len(tree.findall('.//error')),'skipped':len(tree.findall('.//skipped')),
    'network_blocked_in_test_runner':True,'only_allowed_subprocess':'original offline ScriptedModel CLI demo',
    'real_model_calls':0,'real_platform_calls':0,'started_at':started,'finished_at':time.time(),
    'cases':[{'name':c.attrib.get('classname','')+'.'+c.attrib['name'],'status':'skipped' if c.find('skipped') is not None else 'failed' if c.find('failure') is not None or c.find('error') is not None else 'passed'} for c in cases]}
(out/'scoped.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
raise SystemExit(code)
