from pathlib import Path
import json,hashlib,math
R=Path(__file__).resolve().parents[3];T=Path(__file__).resolve().parents[1];run=R/'AM-HARNESS-20261031-01/R7/private/r10-synthetic-run-001'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=read(run.with_name(run.name+'-plan')/'plan.json');request=read(run/'request.json');fit=read(run/'fit.json');reload=read(run/'reload.json');result=read(run/'result.json');steps=read(run/'steps.json');tokens=read(run/'tokenized.json')
sub=read(T/'private/synthetic-training-submission.json');ident=sub['request']['request_id'];ctrl=T/'private/control-results'/ident;window=read(ctrl/(ident+'.result.json'));execution=read(ctrl/'execution-evidence/execution.json')
assert request['config']==read(Path(plan['config']['path']))
assert result['complete'] and result['plan_sha256']==plan['sha256']
assert len(steps)==8 and fit['train_examples']==32 and fit['dev_examples']==8 and len(set(fit['consumed_train_ids']))==32
assert fit['adapter_sha256']==reload['adapter_sha256']==sha(run/'adapters.safetensors')
assert reload['fit_record_sha256']==sha(run/'fit.json') and reload['fresh_load_verified']
assert all(sha(run/name)==value for name,value in result['files_sha256'].items())
assert all(sha(R/name)==value for name,value in plan['source_files_sha256'].items())
errors=[]
for s in steps:
 n=sum(x['completion_tokens'] for x in s['per_example_losses']);loss=sum(x['completion_tokens']*x['mean_token_cross_entropy'] for x in s['per_example_losses'])/n
 errors.append(abs(loss-s['loss']));assert n==s['completion_tokens'] and errors[-1]<1e-10
 assert s['gradient']['all_finite'] and s['gradient']['l2_norm']>0 and s['parameter_delta']['all_finite'] and s['parameter_delta']['changed_lora_b']>0
for t in tokens:
 p=t['prompt_tokens'];assert t['labels'][:p]==[-100]*p and t['labels'][p:]==t['input_ids'][p:]
 assert t['loss_positions']==list(range(p-1,len(t['input_ids'])-1))
assert window['ok'] and window['window']['status']=='completed' and window['window']['restore_verified']
assert execution['independent_worker_groups_gone'] and execution['status']=='completed'
report={'schema':'am-synthetic-training-verified/1','source_commit':'0abc359c1e7b15b0cf8e289dcfb63d397ee95bc7','request_id':ident,
 'optimizer_steps':8,'unique_train_examples':32,'dev_examples':8,'trainable_parameters':fit['trainable_parameters'],
 'all_per_example_weighted_losses_recomputed':True,'max_weighted_loss_error':max(errors),'completion_only_masks_verified':40,
 'prompt_token_range':[min(t['prompt_tokens'] for t in tokens),max(t['prompt_tokens'] for t in tokens)],
 'completion_token_range':[min(t['completion_tokens'] for t in tokens),max(t['completion_tokens'] for t in tokens)],
 'trailing_template_tokens_after_eos':sorted(set(len(t['input_ids'])-t['eos_position']-1 for t in tokens)),
 'all_finite_nonzero_updates':True,'adapter_sha256':fit['adapter_sha256'],'fresh_load_verified':True,
 'reload_diagnostic_max_abs_delta':max(max(x['max_target_logprob_abs_delta'],x['max_probe_logit_abs_delta']) for x in reload['teacher_reload_comparison']['rows']),
 'final_parameter_delta':fit['parameter_delta'],'fit_peak_memory_GiB':fit['peak_memory_bytes']/2**30,'reload_peak_memory_GiB':reload['peak_memory_bytes']/2**30,
 'worker_phase_seconds':execution['finished']-execution['started'],'fit_resource_checks':len(fit['resource_checks']),'reload_resource_checks':len(reload['resource_checks']),
 'training_start_attempts':window['trainer_start_attempts'],'cli_start_attempts':window['cli_start_attempts'],'workers_stopped':True,'original_q8_restored':True,
 'experimental_only':True,'independent_business_acceptance':False,'production_model_changed':False}
(T/'evidence/actual-synthetic-training-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
