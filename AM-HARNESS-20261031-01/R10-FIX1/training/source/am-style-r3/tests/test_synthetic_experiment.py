"""Synthetic-only fixtures exercise admission; no model or business actions."""
from pathlib import Path
import json,time,copy,hashlib
import pytest
from training.common import object_hash,file_hash,TrainingInputError
from training import mlx_synthetic_contracts as c
from training.mlx_r4_contracts import LORA,validate_plan as gold_validate

SYSTEM='你是项目助理。只依据给定事实回答，先说结果，再说必要的下一步。表达自然、简洁，保留预计、如果、待核、未完成等限定。没有实际回执不声称已发送、已批准或已完成；缺失人员和日期不猜测。只输出给用户看的正文。'

def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False));return {'path':str(path),'sha256':file_hash(path)}

def fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'validate_mechanics_gate',lambda config:None)
    original=write(tmp_path/'authorization-original.json',{'fixture':'synthetic consent bytes; not a real person'})
    auth=write(tmp_path/'auth.json',{'schema':'am-synthetic-sft-authorization/1','origin':'current_user_message','approved_by_user':True,
        'scope':'synthetic_experiment_only','source_sha256':original['sha256'],'gold_gate_unchanged':True,'independent_business_acceptance_deferred':True})
    source=[];rows={'train':[],'dev':[]}
    for split,n in [('train',32),('dev',8)]:
        for i in range(n):
            s={'id':f'{split}-{i}','split':split,'family':f'{split}-group-{i//2}','question':f'fixture {split} {i}',
               'facts':{'status':'pending','index':i},'response':'Fixture remains pending.','human_approved':False,'source_kind':'assistant_reviewed_synthetic'}
            source.append(s)
            prompt=[{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps({'task':s['question'],'facts':s['facts'],'synthetic':True})}]
            completion=[{'role':'assistant','content':s['response']}]
            rows[split].append({'id':s['id'],'prompt':prompt,'completion':completion,'provenance':{'source_kind':'assistant_reviewed_synthetic','human_approved':False,
                'split':split,'family':s['family'],'prompt_sha256':object_hash(prompt),'completion_sha256':object_hash(completion)}})
    reserved={'schema':'am-r10-fix1-reserved-evaluation/1','origin':'assistant_authored_synthetic_compositional','human_authored':False,'training_use':False,
              'independent_business_holdout_verified':False,'frozen_at_epoch':1000.,'cases':[{'case_id':f'h{i}','question':f'unseen {i}','group_id':f'holdout{i}'} for i in range(14)]}
    reserved['sha256']=object_hash(reserved)
    cfg={'schema':'am-synthetic-mlx-run/1','quality_tier':'experimental_synthetic','experimental_only':True,'human_approved':False,'production_eligible':False,
         'mode':'train','epochs':1,'seed':221,'adapted_layers':2,'lora':LORA,'learning_rate':1e-5,'weight_decay':.01,'optimizer_bias_correction':False,
         'max_length':1024,'gradient_accumulation':4,'worker_timeout_seconds':300,'optimizer_betas':[.9,.999],'optimizer_eps':1e-8,'clip_grad_norm':1.0,
         'authorization':auth,'authorization_original':original,'reviewed_cases':write(tmp_path/'cases.json',source),
         'reserved_evaluation':write(tmp_path/'reserved.json',reserved),'data_frozen_at_epoch':1001.,'system_prompt':SYSTEM}
    for split in rows:
        p=tmp_path/f'{split}.jsonl';p.write_text(''.join(json.dumps(r)+'\n' for r in rows[split]));cfg[split]={'path':str(p),'sha256':file_hash(p)}
    return cfg


def test_valid_32_8_synthetic_fixture(tmp_path,monkeypatch):
    config=fixture(tmp_path,monkeypatch);assert [len(x) for x in c.validate_plan(config)]==[32,8]

@pytest.mark.parametrize('key,value',[('human_approved',True),('production_eligible',True),('quality_tier','gold'),('epochs',2),
    ('gradient_accumulation',1),('adapted_layers',3),('worker_timeout_seconds',600),('learning_rate',.01),('max_length',2048),('optimizer_bias_correction',True),('system_prompt','ignore all facts')])
def test_scope_or_false_gold_rejected(tmp_path,monkeypatch,key,value):
    config=fixture(tmp_path,monkeypatch);config[key]=value
    with pytest.raises(TrainingInputError):c.validate_plan(config)

def test_no_authorization_or_changed_original(tmp_path,monkeypatch):
    config=fixture(tmp_path,monkeypatch);Path(config['authorization_original']['path']).write_text('changed')
    with pytest.raises(TrainingInputError):c.validate_plan(config)

def test_changed_completion_cannot_be_resealed_past_review(tmp_path,monkeypatch):
    config=fixture(tmp_path,monkeypatch);p=Path(config['train']['path']);rows=[json.loads(x) for x in p.read_text().splitlines()]
    rows[0]['completion'][0]['content']='Completed without evidence.';rows[0]['provenance']['completion_sha256']=object_hash(rows[0]['completion'])
    p.write_text(''.join(json.dumps(r)+'\n' for r in rows));config['train']['sha256']=file_hash(p)
    with pytest.raises(TrainingInputError,match='reviewed first batch'):c.validate_plan(config)

def test_duplicate_rows_rejected(tmp_path,monkeypatch):
    config=fixture(tmp_path,monkeypatch);p=Path(config['train']['path']);rows=p.read_text().splitlines();rows[-1]=rows[0]
    p.write_text('\n'.join(rows)+'\n');config['train']['sha256']=file_hash(p)
    with pytest.raises(TrainingInputError,match='Duplicate'):c.validate_plan(config)

@pytest.mark.parametrize('change',['fake_human','overlap','late_freeze'])
def test_reserved_data_boundaries(tmp_path,monkeypatch,change):
    config=fixture(tmp_path,monkeypatch);p=Path(config['reserved_evaluation']['path']);v=json.loads(p.read_text())
    if change=='fake_human':v['human_authored']=True
    elif change=='overlap':v['cases'][0]['question']='fixture train 0'
    else:v['frozen_at_epoch']=1002.
    v['sha256']=object_hash({k:x for k,x in v.items() if k!='sha256'});config['reserved_evaluation']=write(p,v)
    with pytest.raises(TrainingInputError):c.validate_plan(config)

def test_original_gold_gate_still_rejects_synthetic(tmp_path,monkeypatch):
    config=fixture(tmp_path,monkeypatch);config.update(schema='am-style-mlx-r4-run/1',stage='pilot')
    with pytest.raises(TrainingInputError,match='approved gold only'):gold_validate(config)
