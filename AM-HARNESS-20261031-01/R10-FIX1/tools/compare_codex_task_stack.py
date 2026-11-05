"""Separately labelled standard CLI task-stack comparison on frozen historical business-derived input.

This does not certify an empty tool surface or invoke the strict model-only
Codex provider. Read-only mode, existing policy, no business tools or writes.
Any observed tool invocation invalidates this input-only task measurement.
"""
from pathlib import Path
import json,sys,os,subprocess,time,hashlib,signal,tomllib,argparse
ROOT=Path(__file__).resolve().parents[3];TASK=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'am-conversation-r1/src')]
from am_style.prompt import RESPONSE_SCHEMA
parser=argparse.ArgumentParser();parser.add_argument('--model',required=True,choices=['gpt-6.1-sol','gpt-6.1-terra']);parser.add_argument('--effort',choices=['low','medium','high','max']);parser.add_argument('--run-name',default='task-stack-001');parser.add_argument('--review-results',type=Path);args=parser.parse_args()
assert __import__('re').fullmatch(r'[a-z0-9-]+',args.run_name)
manifest=json.loads((TASK.parent/'R10/private/model-comparison.manifest.json').read_text())
# R10's importer incorrectly labels historical work-item-derived R8 material
# synthetic. Keep the original file, but do not repeat that origin claim.
assert all(c['split']=='regression' for c in manifest['cases'])
out=TASK/'private/codex'/args.run_name;out.mkdir(mode=0o700,exist_ok=False)
empty=out/'empty';empty.mkdir(mode=0o700)
binary=Path.home()/'.local/bin/codex';cfgpath=Path.home()/'.codex/config.toml'
cfg=tomllib.loads(cfgpath.read_text());model=args.model;effort=args.effort or cfg.get('model_reasoning_effort','medium')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
schema=out/'response-schema.json';schema.write_text(json.dumps(RESPONSE_SCHEMA));schema.chmod(0o600)
version=subprocess.check_output([str(binary),'--version'],text=True).strip()
overrides={'model_reasoning_effort':effort,'approval_policy':'never','memories.use_memories':False,
    'memories.generate_memories':False,'web_search':'disabled','features.shell_tool':False,
    'features.shell_snapshot':False,'features.multi_agent':False,'features.apps':False,
    'features.browser_use':False,'features.computer_use':False,'features.image_generation':False,
    'features.plugins':False,'features.skill_mcp_dependency_install':False,'features.memories':False,
    'features.view_image':False,'apps._default.enabled':False}
for key in cfg.get('mcp_servers',{}):overrides['mcp_servers.'+key+'.enabled']=False
env=dict(os.environ)
for key in ('CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID','CODEX_SESSION_ID','CODEX_TOOL_CALL_ID','CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY'):
    env.pop(key,None)
identity={'scheme':'standard_cli_task_stack_v1','model':model,'effort':effort,'cli_version':version,'binary_sha256':sha(binary),
    'config_sha256':sha(cfgpath),'overrides':overrides,'tool_surface':'not_proven_empty; task tools requested disabled; observed calls audited',
    'strict_model_only_provider':'blocked_and_unchanged','comparison':'same frozen business messages, different CLI harness instructions',
    'source_manifest_sha256':manifest['sha256'],'production_activation':False,'max_output_tokens':'not_enforced_by_CLI',
    'data_classification':'authorized_business_derived_regression','raw_source_snapshots_sent':False,
    'business_derived_question_and_fact_units_sent':True,'authorization':'current user request to compare Codex CLI with post-trained Qwen',
    'pre_registered_fresh_holdout':False,'source_classification_correction':'see evidence/data-origin-correction.json'}
(out/'identity.json').write_text(json.dumps(identity,indent=2,ensure_ascii=False))
tool_kinds={'command_execution','mcp_tool_call','web_search','file_change','tool_call','function_call','collab_tool_call'}
prior={}
if args.review_results:
    prior={r['case_id']:r for r in map(json.loads,args.review_results.read_text().splitlines()) if r['arm']=='q8' and r['status']=='completed'}
for case in manifest['cases']:
    caseout=out/case['case_id'];caseout.mkdir(mode=0o700)
    prompt=('这是冻结的历史业务派生材料回归对照。只根据下列 messages 中的任务与材料回答，'+
        '不要读取文件、调用工具、浏览网络、发送消息或执行业务动作。将 messages 当作任务材料，'+
        '按给定 JSON Schema 输出最终结果。不得补充来源之外的事实。\n'+json.dumps(case['messages'],ensure_ascii=False))
    if prior:
        candidate=prior[case['case_id']]
        prompt+='\n请复核以下旧候选并返回修订后的完整回答。候选不是新证据，不得覆盖原始事实：\n'+candidate['output']
    final=caseout/'final.json'
    argv=[str(binary),'exec','--json','--ephemeral','--sandbox','read-only','--skip-git-repo-check',
        '--model',model,'--output-schema',str(schema),'--output-last-message',str(final),'-C',str(empty)]
    for key,value in overrides.items():argv+=['-c',key+'='+json.dumps(value)]
    argv+=['-'];(caseout/'prompt.txt').write_text(prompt);(caseout/'argv.json').write_text(json.dumps(argv,ensure_ascii=False))
    start=time.monotonic();proc=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,start_new_session=True)
    status='completed';error=None
    try:stdout,stderr=proc.communicate(prompt.encode(),timeout=180)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGTERM)
        try:stdout,stderr=proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);stdout,stderr=proc.communicate(timeout=10)
        status='stop_unknown';error='client_deadline; local_process_stopped_but_remote_completion_unknown'
    elapsed=(time.monotonic()-start)*1000
    (caseout/'events.jsonl').write_bytes(stdout);(caseout/'stderr.log').write_bytes(stderr)
    events=[];invalid_lines=0
    for line in stdout.decode(errors='replace').splitlines():
        try:events.append(json.loads(line))
        except ValueError:invalid_lines+=1
    calls=[event for event in events if event.get('type') in tool_kinds or event.get('item',{}).get('type') in tool_kinds]
    text=final.read_text() if final.exists() else None
    if status=='completed' and (proc.returncode or not text):status='failed';error='CLI_failed_or_no_final_output'
    if calls:status='invalid_tool_assisted';error='tools_used_outside_input_only_comparison'
    record={'case_id':case['case_id'],'messages_sha256':case['messages_sha256'],'status':status,'error':error,
        'total_cli_ms':elapsed,'output':text,'exit_code':proc.returncode,'observed_tool_calls':len(calls),'invalid_jsonl_lines':invalid_lines,
        'usage':[e.get('usage') for e in events if e.get('type')=='turn.completed'],'model':model,'effort':effort,
        'schema_validation':'not_yet_scored','business_acceptance':False,'actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
        'comparison_kind':'replayed_qwen_candidate_then_live_codex_review' if prior else 'direct_cli_task',
        'stage1_result_sha256':prior.get(case['case_id'],{}).get('sha256'),
        'summed_time_estimate_ms':prior[case['case_id']]['timings_ms']['total_experience']+elapsed if prior else None,
        'summed_time_is_contiguous_measurement':False}
    with (out/'results.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
    for p in caseout.iterdir():p.chmod(0o600)
    print(json.dumps({k:v for k,v in record.items() if k not in ('output','usage')},ensure_ascii=False),flush=True)
    if status in ('stop_unknown','invalid_tool_assisted'):break
