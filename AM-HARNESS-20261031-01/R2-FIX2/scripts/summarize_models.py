"""Observation denominators remain fixed; failures and non-adoptions stay visible."""
from pathlib import Path
import json,math,statistics
TASK=Path(__file__).resolve().parents[1]
def percentile(values,q):
    if not values:return None
    values=sorted(values);position=(len(values)-1)*q;lo=int(position);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(position-lo)
def summarize(folder,manifest):
    records=[json.loads(p.read_text()) for p in sorted(folder.glob('*.json'))]
    expressions=[r for r in records if 'expression_only' in r['layer']]
    loops=[r for r in records if 'original_loop' in r['layer']]
    expected_expr=manifest['expression'];expected_loops=manifest['full_loop']
    out={'batch':manifest['batch'],'source_commit':manifest['source_commit'],'record_count':len(records),
         'expected_observations':len(expected_expr)+2*len(expected_loops),'model_calls':sum(r.get('provider_transport_calls',0) for r in records),
         'expression':{'denominator':len(expected_expr),'observed':len(expressions),'correct_expected_decision':sum(r.get('checks',{}).get('expected_acceptance') is True for r in expressions),
             'adversarial_observed':sum(r.get('adversarial',False) for r in expressions),'adversarial_accepted':sum(r.get('adversarial',False) and r.get('candidate_accepted',False) for r in expressions),
             'normal_observed':sum(not r.get('adversarial',False) for r in expressions),'normal_free_selected':sum(not r.get('adversarial',False) and r.get('isolated_pipeline_selected_free',False) for r in expressions),
             'actual_delivery':False,'business_completion':'not_measured_expression_only','seconds_p50':percentile([r['seconds'] for r in expressions],.5),'seconds_p95':percentile([r['seconds'] for r in expressions],.95)},
         'full_loop':{},'naturalness':'not_evaluated','real_feishu_delivery':False,'old_288_records_and_123_denominator':'unchanged'}
    for mode in ('legacy','enforce'):
        rows=[r for r in loops if r['mode']==mode]
        presentations=[r.get('presentations',[])[-1] for r in rows if r.get('presentations')]
        out['full_loop'][mode]={'denominator':len(expected_loops),'observed':len(rows),'bounded_native_checks_passed':sum(bool(r.get('checks')) and all(r['checks'].values()) for r in rows),
            'errors':sum(bool(r.get('error')) for r in rows),'free_adopted':sum(p.get('adopted',False) for p in presentations),
            'readback_passed':sum(r.get('checks',{}).get('reply_readback',False) for r in rows),'business_completion':[{'case':r['case_id'],'states':r.get('business_completion',[])} for r in rows],
            'model_calls':sum(r.get('provider_transport_calls',0) for r in rows),'task_seconds_p50':percentile([r['seconds'] for r in rows],.5),'task_seconds_p95':percentile([r['seconds'] for r in rows],.95)}
    a=out['full_loop']['legacy']['task_seconds_p95'];b=out['full_loop']['enforce']['task_seconds_p95']
    out['p95_relative_change']=b/a-1 if a and b else None
    out['rows']=[{'case':r['case_id'],'mode':r['mode'],'checks':r.get('checks'),'reason':r.get('validation_reason'),'error':r.get('error'),'reconciliation_observed':r.get('reconciliation_observed'),'seconds':r['seconds']} for r in records]
    return out
outputs=[]
for directory,manifest in [('model-batch','model-batch.json'),('model-supplement','model-supplement.json')]:
    p=TASK/'input'/manifest
    if p.exists():outputs.append(summarize(TASK/'evidence'/directory,json.loads(p.read_text())))
(TASK/'evidence/model-summary.json').write_text(json.dumps({'batches':outputs,'counting':'batches are separate observations; no retrospective qualification changes; full-loop checks do not imply arbitrary task completion; expression adversarial probes are not naturalness tests'},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(outputs,ensure_ascii=False))
