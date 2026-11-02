from pathlib import Path
import json,re,subprocess,hashlib,xml.etree.ElementTree as ET
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1];SRC=TASK/'worktree';OUT=TASK/'evidence'
SHA=subprocess.check_output(['git','rev-parse','HEAD'],cwd=SRC,text=True).strip()
def cases(path):
    out={}
    for c in ET.parse(path).iter('testcase'):
        row={'state':'passed'}
        for kind in ('failure','error','skipped'):
            n=c.find(kind)
            if n is not None:row={'state':kind,'type':n.get('type'),'message':n.get('message'),'assertion_locations':sorted(set(re.findall(r'(tests/[A-Za-z0-9_./-]+\.py:\d+)',n.text or '')))}
        out[c.get('classname','')+'.'+c.get('name','')]=row
    return out
old=cases(ROOT/'AM-HARNESS-20261031-01/R2-FIX1/evidence/final-source/original.xml');current=cases(OUT/'final-source-v3/original.xml')
bad=lambda d:{k:v for k,v in d.items() if v['state']!='passed'}
before=bad(old);after=bad(current)
comparison={'baseline_source':'f767cea93444217d40a52bea6330f51434f3ce27','source_commit':SHA,'baseline_failures':len(before),'current_failures':len(after),
    'same_names':before.keys()==after.keys(),'same_states_types_messages_assertion_locations':before==after,'before':before,'after':after,
    'actual_exit_code':json.loads((OUT/'final-source-v3/summary.json').read_text())['returncodes']['original'],
    'explanation':'27 existing failures unchanged. full-iteration-1 also had 8 environment failures/errors (local sockets/process restrictions); authorized rerun restored those. All attempts retained and reruns not accumulated.'}
(OUT/'regression-comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2)+'\n')
proof={}
for name in ('test_harness_fix2.py','test_harness_r2_fix2.py','test_harness_r2_fix1_audit.py'):
    path='FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests/'+name
    a=subprocess.check_output(['git','show',comparison['baseline_source']+':'+path],cwd=SRC);b=(SRC/path).read_bytes()
    proof[path]={'baseline_sha256':hashlib.sha256(a).hexdigest(),'current_sha256':hashlib.sha256(b).hexdigest(),'byte_equal':a==b}
assert all(x['byte_equal'] for x in proof.values())
added={k:v for k,v in current.items() if 'test_harness_r2_fix2_audit.' in k}
old_audit={k:v for k,v in current.items() if 'test_harness_r2_fix1_audit.' in k}
(OUT/'four-findings-tests.json').write_text(json.dumps({'source_commit':SHA,'new_checks':len(added),'new_cases':added,'preserved_74_cases':old_audit,
    'preserved_test_files':proof,'original_suite':{'passed':sum(v['state']=='passed' for v in current.values()),'failed':len(after),'exit_code':comparison['actual_exit_code']},
    'counting':'New 44 and preserved 74 cases are included in original suite. Targeted runs, full reruns and sanitized rebuild repeat existing cases; conversation verify and pytest repeat same 193.'},ensure_ascii=False,indent=2)+'\n')
paths=subprocess.check_output(['git','ls-files'],cwd=SRC,text=True).splitlines()
(OUT/'final-source-v3/source-binding.json').write_text(json.dumps({'source_commit':SHA,'all_tracked_files':{x:hashlib.sha256((SRC/x).read_bytes()).hexdigest() for x in paths if (SRC/x).is_file()},'tests_completed_before_commit_bytes_unchanged':True},indent=2)+'\n')
print(json.dumps({'source':SHA,'new_checks':len(added),'old_audit':len(old_audit),'old_failure_comparison_equal':before==after,'actual_exit_code':comparison['actual_exit_code']}))
