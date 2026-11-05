"""Separate synthetic pilot/evaluation entry; no production adapter installation."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import signal

from training.common import file_hash,object_hash,read_json,TrainingInputError
from training.mlx_r4_contracts import validate_base,validate_environment
from training.mlx_synthetic_contracts import validate_envelope
from training.mlx_synthetic_runtime import atomic_json,code_hashes,run_worker


def execute_worker(kind,request_path,timeout):
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
    argv=[sys.executable,'-m','training.mlx_synthetic','--worker',kind,'--request',str(request_path),'--execute']
    with (request_path.parent/f'{kind}.log').open('wb') as log:
        p=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        timed_out=False
        try:code=p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            try:os.killpg(p.pid,signal.SIGTERM);code=p.wait(timeout=5)
            except (ProcessLookupError,subprocess.TimeoutExpired):
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                try:code=p.wait(timeout=5)
                except subprocess.TimeoutExpired:code=None
        try:os.killpg(p.pid,0);gone=False
        except ProcessLookupError:gone=True
        stopped=code is not None and gone
        return {'phase':kind,'attempted':True,'pid':p.pid,'exit_code':code,'timed_out':timed_out,
                'stop_confirmed':stopped,'status':'completed' if stopped and code==0 and not timed_out else 'failed_or_stop_unconfirmed'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path);p.add_argument('--execute',action='store_true')
    p.add_argument('--worker',choices=('fit','reload','eval'));p.add_argument('--request');a=p.parse_args()
    if a.worker:
        if not a.execute or not a.request:raise TrainingInputError('Explicit worker request required')
        return run_worker(a.worker,a.request)
    plan=read_json(a.plan);config=validate_envelope(plan);manifest=read_json(plan['manifest']['path'])
    validate_base(manifest);validate_environment(manifest)
    if not a.execute:return 0
    out=Path(plan['run_directory'])
    if out.exists():raise TrainingInputError('Never overwrite a synthetic run')
    out.mkdir(mode=0o700)
    request={'schema':'am-synthetic-mlx-request/1','manifest':manifest,'config':config,'plan_sha256':plan['sha256'],'code_sha256':code_hashes()}
    rp=out/'request.json';atomic_json(rp,request)
    phases=[]
    for kind in (('fit','reload') if config['mode']=='train' else ('eval',)):
        phase=execute_worker(kind,rp,config['worker_timeout_seconds']);phases.append(phase)
        if phase['status']!='completed' or not phase['stop_confirmed']:break
    complete=(len(phases)==(2 if config['mode']=='train' else 1) and all(x['status']=='completed' and x.get('stop_confirmed') is True for x in phases))
    if complete and config['mode']=='train':
        fit=read_json(out/'fit.json');reload=read_json(out/'reload.json')
        complete=fit.get('training_completed') is True and reload.get('fresh_load_verified') is True and reload['fit_record_sha256']==file_hash(out/'fit.json')
    if complete and config['mode']=='evaluation':
        evaluation=read_json(out/'evaluation.json')
        complete=(evaluation.get('completed')==14 and evaluation.get('request_sha256')==object_hash(request))
    files={x.name:file_hash(x) for x in out.iterdir() if x.is_file() and x.name!='result.json'}
    atomic_json(out/'result.json',{'schema':'am-synthetic-mlx-result/1','mode':config['mode'],'plan_sha256':plan['sha256'],
         'request_sha256':object_hash(request),'complete':complete,'phases':phases,'files_sha256':files,
         'experimental_only':True,'human_approved':False,'independent_business_acceptance':False,'production_eligible':False})
    return 0 if complete else 2

if __name__=='__main__':raise SystemExit(main())
