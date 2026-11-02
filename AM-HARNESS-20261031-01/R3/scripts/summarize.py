from pathlib import Path
import json,sys,hashlib
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1]
sys.path.insert(0,str(ROOT/'am-conversation-r1/src'))
from am_style.evaluation import summarize
from am_style.contracts import SpeechFrame,StylePolicy
from am_style.verify import BoundedVerifier
frozen=json.loads((TASK/'input/frozen-comparison.json').read_text());cases=frozen['cases'];policy=StylePolicy(**frozen['policy'])
by={r['case_id']:r for r in cases};rows=[]
for p in sorted((TASK/'private/qwen-comparison').glob('[0-9][0-9].json')):
    for row in json.loads(p.read_text())['rows']:
        r=dict(row);r.pop('coordinator_record',None)
        if r['arm']=='host_canonical':
            v=BoundedVerifier().verify(SpeechFrame.freeze(by[r['case_id']]['frame']),r['candidate_text'],policy)
            r['semantic_pass']=v.decision=='pass';assert r['semantic_pass']
        if r['arm']=='qwen' and r['case_id'] in ('R3-SEED-owner-and-relevant-progress-1','R3-SEED-empty-todo-complete-read-1'):
            r['human_review']={'source':'human','reviewer':'current_user','acceptable':True,'critical_error':False,
                               'scope':'complete shown answer under stated fictional facts; no relative preference'}
        rows.append(r)
for c in cases:
    rows.append({'case_id':c['case_id'],'arm':'codex','eligible':False,'attempted':False,'schema_pass':False,
        'semantic_pass':False,'adopted':False,'delivered':False,'human_review':None,'candidate_text':None,
        'status':'blocked_preflight','reason':'empty_effective_tool_surface_not_proven'})
report={'schema':'am-r3-actual-comparison/1','frozen_cases':26,'arms':frozen['arms'],'rows':rows,
    'summary':summarize(rows,expected_cases=[c['case_id'] for c in cases],arms=frozen['arms']),
    'no_model_win_rate':'Codex and matching historical legacy candidates unavailable; do not compute paired ranking.',
    'additional_original_qwen_terminal_probe_calls':1,'old_288_observations_and_123_denominators':'unchanged; not combined',
    'business_deliveries':0}
(TASK/'evidence/comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report['summary'],ensure_ascii=False))
old=json.loads((TASK/'private/retained-before-install.json').read_text());assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in old.items())
(TASK/'evidence/preservation.json').write_text(json.dumps({'old_local_evidence_files':len(old),'unchanged_since_preinstall':True,
    'old_blind_dataset_sha256':'6fb6d4fe17fa4daa94cdfca7fed28d03b95f61feeb9655b2885fd0e2f6f04309',
    'key_regenerated':False,'old_scores_modified':False},indent=2)+'\n')
