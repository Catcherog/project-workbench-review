from pathlib import Path
import json,statistics,ast,subprocess,hashlib
TASK=Path(__file__).resolve().parents[1];OUT=TASK/'evidence';ROOT=TASK.parents[1]
values=[json.loads(p.read_text()) for p in sorted((OUT/'model-pairs').glob('*.json'))]
def stats(a):
 a=sorted(a);return {'n':len(a),'p50_seconds':statistics.median(a),'p95_seconds':a[min(len(a)-1,int(len(a)*.95))]}
results=[]
for v in values:
 t=v['telemetry'];results.append({'family':v['family'],'experimental_generation_attempts':1,'production_generation_eligible':t['eligible'],'schema_decoded':v['response']['turn']['response_plan'] is not None,'candidate_accepted':t['accepted'],'adopted':t['adopted'],'selected_source':t['selected_source'],'reason':t['reason'],'legacy_seconds':v['legacy']['seconds'],'response_seconds':v['response']['seconds'],'actual_business_complete':'not_tested','actual_delivery':'not_tested','naturalness':'not_evaluated','actual_model_calls':v['model_calls']['completed']})
old='60f60f564080b75206cd80b35597c1d086925354';new='60f60f564080b75206cd80b35597c1d086925354'
symbols={'am-conversation-r1/src/am_response/pipeline.py':['before_model','finish','envelope','validate'],'am-conversation-r1/src/am_response/evaluation.py':['run_probe'],'am-conversation-r1/src/am_conversation/model.py':['complete','prompt_prefix','_parse_turn','_response_schema']}
checked={}
for path,names in symbols.items():
 def forms(ref):
  tree=ast.parse(subprocess.check_output(['git','show',ref+':'+path],cwd=ROOT,text=True))
  return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names}
 a,b=forms(old),forms(new);checked[path]={name:hashlib.sha256(a[name].encode()).hexdigest()==hashlib.sha256(b[name].encode()).hexdigest() for name in names}
assert all(all(d.values()) for d in checked.values())
data={'layer':'L2_synthetic_final_expression_only','measurement_source_commit':old,'final_source_commit':new,'expression_function_AST_identical':checked,'samples':len(values),'real_original_qwen_calls':sum(v['model_calls']['completed'] for v in values),'families':results,'legacy':stats([v['legacy']['seconds'] for v in values]),'response_plan':stats([v['response']['seconds'] for v in values]),'adopted':sum(v['telemetry']['adopted'] for v in values),'no_extra_presentation_call_in_candidate_run':True,'pair_baseline_calls_separate':True,'not_end_to_end_business_validation':True,'human_evaluation_completed':False,'production_mode':'legacy','old_rewrite':'off'}
(OUT/'model-summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:data[k] for k in ('samples','real_original_qwen_calls','legacy','response_plan','adopted')},ensure_ascii=False))
