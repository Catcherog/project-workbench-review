"""Use the selected interpreter's dependencies; append pytest tooling if needed."""
import importlib.metadata,importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
TASK=ROOT/'AM-CONVERSATION-20261030-01/R1'
label=sys.argv[1] if len(sys.argv)>1 else 'runtime'
if importlib.util.find_spec('pytest') is None:
    tooling=ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/.venv/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    sys.path.append(str(tooling))
import pytest,lark_oapi,docx,pypdf,lxml
metadata={'python':sys.version.split()[0],'interpreter':sys.executable,
          'modules':{m.__name__:m.__file__ for m in (lark_oapi,docx,pypdf,lxml)},
          'versions':{n:importlib.metadata.version(n) for n in ('pytest','lark-oapi','python-docx','pypdf','lxml')},
          'tooling_note':'pytest tooling appended only when unavailable; existing runtime dependency paths retain precedence'}
(TASK/f'evidence/{label}-dependencies.json').write_text(json.dumps(metadata,indent=2)+'\n')
tests=ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests'
names=['test_conversation_integration.py','test_am_self_a.py','test_am_ux4.py','test_project_memory.py','test_am_ux3.py','test_local_api.py','test_provider.py','test_qwen_runtime_only.py','test_embedded.py','test_am_ux2.py','test_am_ux2_fix1.py','test_am_ux2_fix1_experience.py','test_gateway.py','test_am_self_c.py','test_am_self_fix1.py','test_feishu_transport.py']
raise SystemExit(pytest.main([*[str(tests/n) for n in names],*[str(ROOT/'local-qwen3.8/feishu-bridge'/n) for n in ('test_group_ai.py','test_group_ledger.py')],'-q','--tb=short',f'--junitxml={TASK}/evidence/{label}-tests.xml']))
