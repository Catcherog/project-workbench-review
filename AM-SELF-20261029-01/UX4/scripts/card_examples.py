"""Generate synthetic examples using the production renderer and isolated fixture."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests'),str(ROOT/'local-qwen3.8/feishu-bridge')]
from test_am_ux4 import ux,service,am_rig,base_rig,group_ask,group_open,bind_dm
from test_am_ux1 import latest,text,click
OUT=Path(__file__).resolve().parents[1]/'evidence/cards'

def test_export_examples(ux):
 OUT.mkdir(parents=True,exist_ok=True)
 def save(name):
  (OUT/(name+'.json')).write_text(json.dumps({'layer':'synthetic production renderer; no real business data','card':json.loads(text(ux))},ensure_ascii=False,indent=2)+'\n')
 group_ask(ux);save('group-public-answer')
 c=group_open(ux,'ou_staff');save('group-private-detail')
 bind_dm(ux,'ou_staff',c);save('group-private-people')
 click(ux,'projects',actor='ou_staff',chat='oc_ou_staff');save('group-scoped-directory')
 assert not ux[2].rows('SELECT 1 FROM action_items')
