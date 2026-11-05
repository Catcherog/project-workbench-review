from pathlib import Path
import json,sys,hashlib,time
ROOT=Path(__file__).resolve().parents[3];T=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'am-style-r3'),str(ROOT/'am-conversation-r1/src'),str(ROOT/'am-style-r5/src')]
from training.mlx_r4_contracts import validate_plan
from am_style_r5.holdout_gate import verify_holdout
old=json.loads((ROOT/'AM-HARNESS-20261031-01/R7/private/r8-pilot-plan-94fcf093-457/pilot.config.json').read_text())
proposed=dict(old,quality_tier='experimental_silver',experimental_only=True)
results=[]
for name,fn in [('existing_mlx_data_tier',lambda:validate_plan(proposed)),('fresh_independent_holdout',lambda:verify_holdout({'holdout_gate':None}))]:
 try:fn();results.append({'check':name,'status':'pass'})
 except Exception as e:results.append({'check':name,'status':'blocked','error_type':type(e).__name__,'reason':str(e)})
files=['am-style-r3/training/mlx_r4_contracts.py','am-style-r5/src/am_style_r5/holdout_gate.py','local-qwen3.8/feishu-bridge/am_training_control.py']
report={'at_epoch':time.time(),'scope':'metadata_only; no execution request, model load, lease or production change',
 'user_training_authorized':True,'new_training_requests':0,'trainer_starts':0,'source_files':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
 'checks':results,'prepared_synthetic_first_batch':{'train':32,'dev':8,'human_approved':False},
 'reserved_synthetic_evaluation':{'count':14,'independent_human_declaration':False},
 'pending_question':'Use an explicitly labelled synthetic experimental path while preserving original human-gold gate and deferring independent business acceptance?'}
(T/'evidence/training-readiness.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
