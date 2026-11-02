"""Fresh process base/one-step-SFT diagnostic; no claimed blind evaluation."""
from pathlib import Path
import json,sys,time,fcntl,hashlib
TASK=Path(__file__).resolve().parents[1];ROOT=TASK.parents[1];OLD=ROOT/'SFT训练/R6-FIX1_20261021_01'
sys.path[:0]=[str(ROOT/'am-conversation-r1/src'),str(OLD/'scripts')]
from am_style.prompt import build_messages,coordinator_messages
from am_style.contracts import SpeechFrame,StylePolicy,digest
from am_style.verify import parse_candidate,BoundedVerifier
from runtime_common import guard
cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text());poc=json.loads(Path(cfg['poc_config']).read_text())
lease=(Path(poc['service']['root_directory'])/'state/model-coordinator.lock').open('r+')
fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);resources=guard(allow_loaded=True)
assert resources['available_memory_GiB']>=24
import mlx.core as mx
from mlx_lm import load,stream_generate
from mlx_lm.sample_utils import make_sampler
from mlx_lm.tuner.utils import load_adapters
mx.set_memory_limit(22*2**30);mx.set_cache_limit(128*2**20)
frozen=json.loads((TASK/'input/frozen-comparison.json').read_text());policy=StylePolicy(**frozen['policy'])
selected=[frozen['cases'][i] for i in (6,22,24)]
manifest={'case_ids':[x['case_id'] for x in selected],'arms':['independent_mlx_base','independent_mlx_sft_1step'],
    'usage':'diagnostic_exposed_design_scenarios_not_sealed_test','max_new_tokens':160,'temperature':0,
    'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
path=TASK/'evidence/mlx-eval-input.json';assert not path.exists();path.write_text(json.dumps(manifest,indent=2)+'\n')
model,tok=load(str(OLD/'models/mlx-4bit'),tokenizer_config={'trust_remote_code':False})
rows=[]
for arm in manifest['arms']:
    if arm.endswith('1step'):load_adapters(model,str(TASK/'private/sft-independent-smoke-v2'))
    model.eval()
    for case in selected:
        guard(allow_loaded=True)
        frame=SpeechFrame.freeze(case['frame']);messages=coordinator_messages(build_messages(frame,policy))
        prompt=tok.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False,preserve_thinking=False)
        start=time.monotonic();text='';last=None
        for last in stream_generate(model,tok,prompt,max_tokens=160,sampler=make_sampler(temp=0),prefill_step_size=256):text+=last.text
        candidate=parse_candidate(text);verdict=BoundedVerifier().verify(frame,candidate,policy) if candidate else None
        row={'case_id':case['case_id'],'arm':arm,'raw_text':text,'candidate_text':candidate,
             'prompt_sha256':digest(messages),'elapsed_ms':(time.monotonic()-start)*1000,
             'tokens':getattr(last,'generation_tokens',None),'finish_reason':getattr(last,'finish_reason',None),
             'schema_pass':candidate is not None,'bounded_decision':verdict.decision if verdict else 'not_checked',
             'human_review':None,'adopted':False,'delivered':False}
        rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        (TASK/'evidence/mlx-eval.json').write_text(json.dumps({'rows':rows,'complete':len(rows)==6,'fresh_process':True,
            'production_changed':False,'peak_memory_bytes':mx.get_peak_memory(),'model_scope':'independent_HF_text_branch',
            'quality_conclusion':'not_established; 3 exposed diagnostic scenarios, no new human preference'},ensure_ascii=False,indent=2)+'\n')
