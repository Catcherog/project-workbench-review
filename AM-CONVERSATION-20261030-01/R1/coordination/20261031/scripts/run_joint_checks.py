"""Joint synthetic checks for the three modules; no live API calls or services."""
import hashlib,importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).parent
STUDIO=ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
sys.path[:0]=[str(STUDIO/'src'),str(STUDIO/'tests'),str(ROOT/'local-qwen3.8/feishu-bridge'),str(ROOT/'am-conversation-r1/src')]
if importlib.util.find_spec('pytest') is None:sys.path.append(str(STUDIO/'.venv/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'))
import pytest
roots=[ROOT/'local-qwen3.8/feishu-bridge',STUDIO/'src',ROOT/'am-conversation-r1/src']
def hashes():
 return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for root in roots for p in root.rglob('*.py') if '.venv' not in p.parts}
before=hashes();started=time.time()
files=[STUDIO/'tests/test_conversation_integration.py',STUDIO/'tests/test_document_standards.py',ROOT/'local-qwen3.8/feishu-bridge/test_am_information.py',ROOT/'local-qwen3.8/feishu-bridge/test_info_sources.py',ROOT/'local-qwen3.8/feishu-bridge/test_info_cloud.py']
code=pytest.main([*[str(p) for p in files],'-q','--tb=short',f'--junitxml={OUT}/joint-tests.xml'])
after=hashes();result={'started_at':started,'finished_at':time.time(),'exit_code':code,'source_unchanged_during_test':before==after,'source_hashes':before,'synthetic_only':True,'real_model_calls':0,'real_platform_calls':0}
(OUT/'joint-checks.json').write_text(json.dumps(result,indent=2)+'\n')
if before!=after:raise SystemExit('SOURCE_CHANGED_DURING_TEST')
raise SystemExit(code)
