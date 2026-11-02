"""One-step isolated gold SFT smoke on the user-authorized independent HF base.

Never unload production Qwen, alter its configuration, or bypass resource gates.
One train and one dev row are a mechanics check, not an effectiveness experiment.
"""
from pathlib import Path
import argparse,hashlib,json,sys,time,fcntl,sqlite3
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1]
OLD=ROOT/'SFT训练/R6-FIX1_20261021_01';DATA=TASK/'private/training-data'
sys.path[:0]=[str(ROOT/'am-conversation-r1/src'),str(ROOT/'am-style-r3')]
from training.common import file_hash,load_training_data,validate_tokenization
parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
def write(name,value):
    path=TASK/'evidence'/name
    if path.exists():
        previous=path.with_name(path.stem+'-prior-'+str(time.time_ns())+'.json')
        previous.write_bytes(path.read_bytes())
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(value,ensure_ascii=False),flush=True)
report={'schema':'r3-mlx-smoke/1','execute_requested':args.execute,'training_started':False,'training_completed':False,
    'optimizer_steps':0,'quality_tier':'gold','experiment_scope':'independent_official_HF_base_not_proven_identical_to_production_Q8',
    'base_revision':'1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0','source':'existing_local_snapshot',
    'independent_base_authorization':'Current user explicitly approved independent baseline smoke after revision difference was disclosed.',
    'production_configuration_changed':False,'production_model_unloaded':False,'business_acceptance':False}
data_report=json.loads((TASK/'evidence/data-preparation.json').read_text())
cfg={'quality_tier':'gold','train_file':str(DATA/'sft.train.jsonl'),'dev_file':str(DATA/'sft.dev.jsonl'),
     'train_sha256':data_report['hashes']['sft.train'],'dev_sha256':data_report['hashes']['sft.dev'],
     'style_policy_version':'muyi-style/3.0-draft.1','host_contract_version':'am-terminal-presenter/3.0.1+coordinator-native-envelope/1'}
train,dev=load_training_data(cfg,'sft')
weights=json.loads((TASK/'evidence/weight-readback.json').read_text())
assert all(x['all_match'] for x in weights['snapshots'])
from transformers import AutoTokenizer
tok=AutoTokenizer.from_pretrained(str(OLD/'models/mlx-4bit'),local_files_only=True,trust_remote_code=False)
class Tokenizer:
    def apply_chat_template(self,messages,**kw):
        return tok.apply_chat_template(messages,return_dict=False,enable_thinking=False,preserve_thinking=False,**kw)
tokenizer=Tokenizer();mask_summary=validate_tokenization(tokenizer,train+dev,4096,'sft')
encoded=[]
for row in train+dev:
    prompt=tokenizer.apply_chat_template(row['prompt'],tokenize=True,add_generation_prompt=True)
    full=tokenizer.apply_chat_template(row['prompt']+row['completion'],tokenize=True,add_generation_prompt=False)
    assert full[:len(prompt)]==prompt
    encoded.append({'id':row['id'],'split':row['provenance']['split'],'input_ids':full,
        'labels':[-100]*len(prompt)+full[len(prompt):], 'prompt_tokens':len(prompt),
        'completion_tokens':len(full)-len(prompt),'truncated':False})
(DATA/'tokenized.json').write_text(json.dumps(encoded,ensure_ascii=False)+'\n')
report.update(data_validation='pass',train_examples=len(train),dev_examples=len(dev),tokenization=mask_summary,
              mask=[{k:r[k] for k in ('id','split','prompt_tokens','completion_tokens','truncated')} for r in encoded])
if not args.execute:
    report['status']='prepared_not_executed';write('sft-attempt.json',report);raise SystemExit(0)
# Read-only shared-resource guard, using the already reviewed original training policy.
sys.path.insert(0,str(OLD/'scripts'))
from runtime_common import guard,ResourcePause
runtime_cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
poc=json.loads(Path(runtime_cfg['poc_config']).read_text());state=Path(poc['service']['root_directory'])/'state'
lease=(state/'model-coordinator.lock').open('r+')
def resource_guard():
    r=guard(allow_loaded=True)
    if r['available_memory_GiB']<24:
        raise ResourcePause('less_than_24_GiB_available_before_large_model_load',r)
    with sqlite3.connect((state/'gateway.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as c:
        for sql in ("SELECT count(*) FROM am_harness_runs WHERE state IN ('queued','running')",
                    "SELECT count(*) FROM am_inbox WHERE state IN ('received','processing','harness_admitting') AND expires>strftime('%s','now')"):
            if c.execute(sql).fetchone()[0]:raise ResourcePause('new_business_work_present',r)
    return r
try:
    fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    resource=resource_guard()
    report.update(resources=resource,original_model_lease_held=True,
        resource_policy='Existing Q8 may stay resident while idle; nonblocking original lease prevents concurrent Qwen inference. 24 GiB available required before loading; MLX capped at 22 GiB. No unload or restart.')
except BlockingIOError:
    report.update(status='blocked_before_model_load',blocking_reason='original_model_lease_busy',new_adapter_files=0,model_loads=0)
    write('sft-attempt.json',report);raise SystemExit(2)
except ResourcePause as exc:
    report.update(status='blocked_before_model_load',blocking_reason=str(exc),resources=exc.metrics,
                  new_adapter_files=0,model_loads=0)
    write('sft-attempt.json',report);raise SystemExit(2)
# Reached only with sufficient resources and no production work; Q8 stays intact.
import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
from mlx_lm import load
from mlx_lm.tuner.utils import linear_to_lora_layers
from mlx_lm.tuner.trainer import grad_checkpoint
from mlx.utils import tree_flatten
import chunk_gated_delta
out=TASK/'private/sft-independent-smoke-v2';out.mkdir(exist_ok=False)
mx.set_memory_limit(22*2**30);mx.set_cache_limit(128*2**20);mx.random.seed(221)
model,actual_tok=load(str(OLD/'models/mlx-4bit'),tokenizer_config={'trust_remote_code':False})
assert len(model.layers)==64 and model.model_type=='qwen3_5'
for row,enc in zip(train+dev,encoded):
    observed=actual_tok.apply_chat_template(row['prompt']+row['completion'],tokenize=True,return_dict=False,
        add_generation_prompt=False,enable_thinking=False,preserve_thinking=False)
    assert observed==enc['input_ids']
model.freeze()
config={'rank':8,'scale':2.0,'dropout':0.0,'keys':['self_attn.q_proj','self_attn.k_proj','self_attn.v_proj','self_attn.o_proj',
        'linear_attn.in_proj_qkv','linear_attn.in_proj_z','linear_attn.in_proj_a','linear_attn.in_proj_b','linear_attn.out_proj']}
linear_to_lora_layers(model,2,config);chunk_gated_delta.install()
grad_checkpoint(model.layers[0])
params=dict(tree_flatten(model.trainable_parameters()))
assert params and all(k.endswith(('lora_a','lora_b')) for k in params)
def loss(m,row):
    ids=row['input_ids'];positions=list(range(row['prompt_tokens']-1,len(ids)-1))
    hidden=m.model(mx.array([ids[:-1]],dtype=mx.int32))
    hidden=mx.take(hidden,mx.array(positions),axis=1)[0]
    logits=m.language_model.lm_head(hidden).astype(mx.float32)
    return nn.losses.cross_entropy(logits,mx.array([ids[i+1] for i in positions]),reduction='mean')
model.eval();before=loss(model,encoded[1]);mx.eval(before)
# After load, available-memory naturally includes this owned model. Retain the
# original service/pending guards without applying the pre-load threshold again.
guard(allow_loaded=True);model.train()
for layer in model.layers[:-2]:layer.eval()
report['training_started']=True
value,grads=nn.value_and_grad(model,loss)(model,encoded[0]);mx.eval(value,grads)
assert bool(mx.isfinite(value))
opt=optim.AdamW(learning_rate=1e-5);opt.update(model,grads);mx.eval(model.trainable_parameters(),opt.state)
model.eval();after=loss(model,encoded[1]);mx.eval(after)
mx.save_safetensors(str(out/'adapters.safetensors'),dict(tree_flatten(model.trainable_parameters())))
reloaded=mx.load(str(out/'adapters.safetensors'))
actual=dict(tree_flatten(model.trainable_parameters()))
assert set(actual)==set(reloaded) and all(bool(mx.array_equal(actual[k],reloaded[k])) for k in actual)
(out/'adapter_config.json').write_text(json.dumps({'fine_tune_type':'lora','num_layers':2,'lora_parameters':config},indent=2))
report.update(status='one_step_completed',training_completed=True,optimizer_steps=1,model_loads=1,
              train_loss=float(value),dev_loss_before=float(before),dev_loss_after=float(after),
              adapter_sha256=file_hash(out/'adapters.safetensors'),peak_memory_bytes=mx.get_peak_memory(),
              adapter_tensor_roundtrip_verified=True,full_model_reload_verified=False,
              adapted_layers=2,lora_parameters=config,trainable_parameters=sum(v.size for v in actual.values()),
              data_sha256={'train':cfg['train_sha256'],'dev':cfg['dev_sha256']},
              source_sha256=file_hash(Path(__file__)),quality_conclusion='not_evaluated')
write('sft-attempt.json',report)
