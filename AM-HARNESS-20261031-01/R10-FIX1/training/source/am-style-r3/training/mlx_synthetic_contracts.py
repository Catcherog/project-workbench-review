"""Explicit user-authorized synthetic pilot; original human-gold gates are unchanged."""
from pathlib import Path
import json
import math
import hashlib

from training.common import TrainingInputError, file_hash, object_hash, read_json
from training.mlx_r4_contracts import LORA, validate_mechanics_gate


def checked_file(ref):
    path=Path(ref['path'])
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or file_hash(path)!=ref['sha256']:
        raise TrainingInputError('Synthetic experiment input changed or is missing')
    return path


def check_sources(plan):
    roots=plan['runtime_source_binding']['roots']
    expected=plan['source_files_sha256']
    root=Path(__file__).resolve().parents[1]
    if Path(roots['training']).resolve()!=root or Path(roots['am_style']).resolve()!=root.parent/'am-conversation-r1/src':
        raise TrainingInputError('Synthetic experiment must use the bound installed runtime')
    for name,sha in expected.items():
        p=root.parent/name
        if not p.is_file() or p.is_symlink() or file_hash(p)!=sha:
            raise TrainingInputError('Synthetic experiment source changed: '+name)
    required={'am-style-r3/training/mlx_synthetic.py','am-style-r3/training/mlx_synthetic_runtime.py',
              'am-style-r3/training/mlx_synthetic_contracts.py','am-integrated-r6/am_training_window/native_synthetic.py',
              'local-qwen3.8/feishu-bridge/am_training_control.py'}
    if not required<=set(expected):raise TrainingInputError('Incomplete synthetic source binding')


def validate_plan(config):
    if (config.get('schema')!='am-synthetic-mlx-run/1' or config.get('quality_tier')!='experimental_synthetic'
            or config.get('experimental_only') is not True or config.get('human_approved') is not False
            or config.get('production_eligible') is not False or config.get('mode') not in ('train','evaluation')):
        raise TrainingInputError('Only explicitly labelled non-human-approved synthetic experiments are accepted')
    if config.get('system_prompt') != '你是项目助理。只依据给定事实回答，先说结果，再说必要的下一步。表达自然、简洁，保留预计、如果、待核、未完成等限定。没有实际回执不声称已发送、已批准或已完成；缺失人员和日期不猜测。只输出给用户看的正文。':
        raise TrainingInputError('Synthetic system prompt differs from reviewed data')
    exact={'epochs':1,'seed':221,'adapted_layers':2,'learning_rate':1e-5,'weight_decay':.01,
           'optimizer_bias_correction':False,'max_length':1024,'gradient_accumulation':4,'worker_timeout_seconds':300}
    if any(type(config.get(k)) is not type(v) or config[k]!=v for k,v in exact.items()) or config.get('lora')!=LORA:
        raise TrainingInputError('Synthetic pilot exceeds the reviewed one-pass resource/hyperparameter scope')
    if config.get('optimizer_betas')!=[.9,.999] or config.get('optimizer_eps')!=1e-8 or config.get('clip_grad_norm')!=1.0:
        raise TrainingInputError('Explicit optimizer settings differ')
    auth=read_json(checked_file(config['authorization']))
    original=checked_file(config['authorization_original'])
    if (auth.get('schema')!='am-synthetic-sft-authorization/1' or auth.get('origin')!='current_user_message'
            or auth.get('approved_by_user') is not True or auth.get('scope')!='synthetic_experiment_only'
            or auth.get('source_sha256')!=file_hash(original) or auth.get('gold_gate_unchanged') is not True
            or auth.get('independent_business_acceptance_deferred') is not True):
        raise TrainingInputError('Missing exact synthetic experimental authorization')
    source=json.loads(checked_file(config['reviewed_cases']).read_text())
    if len(source)!=40 or {r['split'] for r in source}!={'train','dev'}:
        raise TrainingInputError('Expected the reviewed 32/8 first batch')
    by_id={r['id']:r for r in source}
    if len(by_id)!=40:raise TrainingInputError('Duplicate reviewed sample')
    all_rows=[];groups=[]
    for split,count in [('train',32),('dev',8)]:
        path=checked_file(config[split])
        rows=[json.loads(s) for s in path.read_text().splitlines()]
        if len(rows)!=count:raise TrainingInputError('Synthetic first-batch count differs')
        group=set()
        for row in rows:
            p=row['provenance'];s=by_id.get(row['id'])
            if (not s or s['split']!=split or s.get('human_approved') is not False
                    or p.get('source_kind')!='assistant_reviewed_synthetic' or p.get('human_approved') is not False
                    or p.get('split')!=split or p.get('family')!=s['family']
                    or p.get('prompt_sha256')!=object_hash(row['prompt'])
                    or p.get('completion_sha256')!=object_hash(row['completion'])):
                raise TrainingInputError('Synthetic provenance/row binding differs')
            expected_input={'task':s['question'],'facts':s['facts'],'synthetic':True}
            if (len(row['prompt'])!=2 or row['prompt'][0]!={'role':'system','content':config['system_prompt']}
                    or row['prompt'][1]['role']!='user' or json.loads(row['prompt'][1]['content'])!=expected_input
                    or row['completion']!=[{'role':'assistant','content':s['response']}]
                    or s.get('source_kind')!='assistant_reviewed_synthetic'):
                raise TrainingInputError('Training text differs from the reviewed first batch')
            group.add(s['family'])
        if len({r['id'] for r in rows})!=count:raise TrainingInputError('Duplicate training rows')
        all_rows.append(rows);groups.append(group)
    if len(groups[0])!=16 or len(groups[1])!=4 or groups[0]&groups[1]:
        raise TrainingInputError('Synthetic family split leaked')
    reserved=read_json(checked_file(config['reserved_evaluation']))
    if (reserved.get('schema')!='am-r10-fix1-reserved-evaluation/1'
            or reserved.get('origin')!='assistant_authored_synthetic_compositional'
            or reserved.get('human_authored') is not False or reserved.get('training_use') is not False
            or reserved.get('independent_business_holdout_verified') is not False
            or len(reserved.get('cases',[]))!=14):
        raise TrainingInputError('Reserved synthetic tests must not impersonate independent human holdout')
    if reserved['sha256']!=object_hash({k:v for k,v in reserved.items() if k!='sha256'}):
        raise TrainingInputError('Reserved test seal changed')
    if config['data_frozen_at_epoch']<reserved['frozen_at_epoch']:
        raise TrainingInputError('Reserved tests were not frozen before the training batch')
    questions={r['question'] for r in source}
    if any(c['question'] in questions or c['group_id'] in groups[0]|groups[1] for c in reserved['cases']):
        raise TrainingInputError('Reserved examples overlap training/development')
    if config['mode']=='evaluation':
        if config.get('arm') not in ('base','sft') or config.get('generation')!={'temperature':0.0,'max_tokens':384,'seed':221}:
            raise TrainingInputError('Unsupported evaluation settings')
        if config['arm']=='sft':
            artifact=read_json(checked_file(config['fit_result']))
            if not artifact.get('training_completed') or artifact.get('schema')!='am-synthetic-mlx-fit/1':
                raise TrainingInputError('Evaluation requires a real completed synthetic fit')
            reload=read_json(checked_file(config['reload_result']))
            if reload.get('fresh_load_verified') is not True or reload.get('fit_record_sha256')!=config['fit_result']['sha256']:
                raise TrainingInputError('Evaluation requires verified independent adapter reload')
            for key in ('adapter','adapter_config'):
                checked_file(config[key])
            if artifact['adapter_sha256']!=config['adapter']['sha256'] or artifact['adapter_config_sha256']!=config['adapter_config']['sha256']:
                raise TrainingInputError('Adapter does not match the fit result')
    validate_mechanics_gate(config)
    return all_rows


def validate_envelope(plan):
    if plan.get('schema')!='am-synthetic-mlx-plan/1' or plan.get('sha256')!=object_hash({k:v for k,v in plan.items() if k!='sha256'}):
        raise TrainingInputError('Synthetic plan seal differs')
    check_sources(plan)
    checked_file(plan['manifest']);checked_file(plan['config'])
    interpreter=Path(plan['python_interpreter']['path'])
    if not interpreter.is_absolute() or not interpreter.is_file() or file_hash(interpreter)!=plan['python_interpreter']['sha256'] or str(interpreter.resolve())!=plan['python_interpreter']['resolved_path']:
        raise TrainingInputError('Bound Python interpreter changed')
    config=read_json(plan['config']['path'])
    validate_plan(config)
    if config['mode']!=plan['mode']:raise TrainingInputError('Synthetic operation/config mismatch')
    run=Path(plan['run_directory']);scope=Path(plan['runtime_source_binding']['roots']['training']).parent/'AM-HARNESS-20261031-01/R7/private'
    if not run.is_absolute() or run.is_symlink() or not run.resolve().is_relative_to(scope.resolve()):
        raise TrainingInputError('Synthetic run outside original private plan scope')
    return config


def validate_completed_run(plan, output):
    result=read_json(Path(output)/'result.json')
    if result.get('schema')!='am-synthetic-mlx-result/1' or result.get('complete') is not True or result.get('plan_sha256')!=plan['sha256']:
        raise TrainingInputError('Synthetic run did not complete for this plan')
    for name,sha in result['files_sha256'].items():
        if Path(name).name!=name or file_hash(Path(output)/name)!=sha:
            raise TrainingInputError('Synthetic result artifact changed')
    return {'complete':True,'mode':plan['mode'],'result_sha256':file_hash(Path(output)/'result.json'),
            'independent_business_acceptance':False,'production_eligible':False}
