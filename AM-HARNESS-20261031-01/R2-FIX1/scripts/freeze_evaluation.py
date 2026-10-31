from pathlib import Path
import json,hashlib
p=Path(__file__).resolve().parents[1];cases=[json.loads(x) for x in (p/'input/acceptance_seed.jsonl').read_text().splitlines()]
rows=[]
for c in cases:
 state=c['starting_state'];e=c['evidence_or_receipt'];ident=c['case_id']
 # Frozen before outputs. Unsupported profiles and failed outputs stay in denominator.
 nofree=(ident in ('SYN-QRY-01','SYN-CTL-01','SYN-CTL-02','SYN-CTL-03','SYN-CTL-04','SYN-ANA-03','SYN-ERR-03'))
 rows.append(dict(c,eligible_free_expression=not nofree,
                  eligibility_basis='deterministic_control_or_access_suppression' if nofree else 'requested_explanation_or_content',
                  fixture_project_mapping={'合成青岚':'需求75:合成青岚','合成星榆':'需求76:合成星榆','合成海棠':'需求77:合成海棠'},
                  fixture_clock='2030-03-01T09:00:00+08:00'))
manifest={'version':'r2-fix1-eval/1','seed_sha256':hashlib.sha256((p/'input/acceptance_seed.jsonl').read_bytes()).hexdigest(),
 'repetitions':3,'variants':['legacy','enforce'],'pair_order':'alternating_by_case_and_repetition','blind_selection':'repetition_1_all_48',
 'eligibility_frozen_before_outputs':True,'cases':rows,'thresholds':{'candidate_rate':.9,'adoption_rate':.85,'severe_errors':0,'p95_ratio':1.1,'blind_win_rate':.6},
 'non_evaluable_reasons':['no_candidate','technical_transport_error','access_suppression'],'no_result_based_exclusions':True}
target=p/'input/evaluation-manifest.json'
if target.exists():raise SystemExit('already frozen; do not overwrite')
target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(hashlib.sha256(target.read_bytes()).hexdigest())
