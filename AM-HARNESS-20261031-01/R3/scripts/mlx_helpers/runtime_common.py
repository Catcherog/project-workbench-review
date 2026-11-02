import csv
import hashlib
import json
import re
import sqlite3
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import psutil

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261021

def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
    return h.hexdigest()

def write_json(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(p)

def read_jsonl(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]

def append_jsonl(path,row):
    with Path(path).open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')

def service_state():
    result={'pending':0,'loaded_models':0,'available':True}
    try:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/ps',timeout=2) as f:models=json.load(f)['models']
        result['loaded_models']=len(models)
        result['loaded_bytes']=sum(x.get('size_vram',0) for x in models)
        result['model_expiry']=[x.get('expires_at') for x in models]
        closed={'done','completed','expired','timed_out','failed','cancelled','canceled','rejected'}
        base=Path.home()/'.local/share/local-qwen-feishu'
        for fn,table in [('state/chat.sqlite3','inbox'),('poc/state/gateway.sqlite3','tasks')]:
            db=base/fn
            with sqlite3.connect(f'file:{db}?mode=ro',uri=True,timeout=.2) as c:
                counts=list(c.execute('select state,count(*) from '+table+' group by state'))
            result['pending']+=sum(n for s,n in counts if s not in closed)
    except Exception as e:
        result['available']=False;result['error']=type(e).__name__
    return result

def resources(include_service=True):
    mem=psutil.virtual_memory();swap=psutil.swap_memory()
    pressure=int(subprocess.check_output(['sysctl','-n','kern.memorystatus_vm_pressure_level'],text=True).strip())
    r={'time':now(),'available_memory_GiB':mem.available/2**30,'memory_used_GiB':mem.used/2**30,'memory_pressure':pressure,'swap_used_GiB':swap.used/2**30,'swap_total_GiB':swap.total/2**30}
    if include_service:r['service']=service_state()
    return r

def guard(allow_loaded=False):
    r=resources()
    s=r['service']
    reasons=[]
    if not s['available']:reasons.append('shared_service_status_unavailable')
    if s['pending']:reasons.append('shared_service_request_pending')
    if s['loaded_models'] and not allow_loaded:reasons.append('shared_Q8_model_loaded')
    if r['memory_pressure']>=4:reasons.append('critical_system_memory_pressure')
    if r['available_memory_GiB']<5:reasons.append('less_than_5_GiB_available')
    if reasons:raise ResourcePause(','.join(reasons),r)
    return r

class ResourcePause(RuntimeError):
    def __init__(self,reason,metrics):
        super().__init__(reason);self.metrics=metrics

def score_case(case,text):
    checks=[]
    for s in case.get('must_include',[]):checks.append({'criterion':'contains '+s,'pass':s in text})
    for choices in case.get('any_groups',[]):checks.append({'criterion':'one_of '+repr(choices),'pass':any(s in text for s in choices)})
    for pattern in case.get('forbidden_regex',[]):checks.append({'criterion':'excludes '+pattern,'pass':re.search(pattern,text) is None})
    for name,full in case.get('name_mapping',{}).items():
        bad=[]
        for m in re.finditer(re.escape(name),text):
            if text[max(0,m.end()-len(full)):m.end()] != full:bad.append(m.start())
        checks.append({'criterion':'every_occurrence '+full,'pass':bool(name in text) and not bad,'bare_name_positions':bad})
    if case['id']=='GEN-03':
        try:valid_json=json.loads(text.strip())=={'temperature_c':19.5,'count':7}
        except (ValueError,TypeError):valid_json=False
        checks.append({'criterion':'exact JSON values and no surrounding prose','pass':valid_json})
    if case['id'] in ('GEN-01','GEN-06'):
        expected='22' if case['id']=='GEN-01' else '1,2,6,9'
        checks.append({'criterion':'exact requested output','pass':text.strip()==expected})
    return {'passed':sum(x['pass'] for x in checks),'total':len(checks),'automatic_status':'scored' if checks else 'not_scored','all_automatic_checks_pass':bool(checks) and all(x['pass'] for x in checks),'checks':checks,'semantic_review':'pending','rubric':case.get('manual_rubric')}

class Metrics:
    def __init__(self,stage):
        from tensorboardX import SummaryWriter
        self.stage=stage;self.dir=ROOT/'runs'/stage;self.dir.mkdir(parents=True,exist_ok=True)
        self.path=self.dir/'metrics.jsonl';self.writer=SummaryWriter(str(self.dir/'tensorboard'))
    def log(self,kind,step,**data):
        row={'time':now(),'stage':self.stage,'kind':kind,'step':int(step),**data}
        append_jsonl(self.path,row)
        for k,v in data.items():
            if isinstance(v,(int,float)) and not isinstance(v,bool):self.writer.add_scalar(kind+'/'+k,v,step)
        self.writer.flush()
        write_json(ROOT/'dashboard/latest.json',row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
        # JSONL remains authoritative. Recreate a complete CSV with union of keys.
        rows=read_jsonl(self.path);keys=list(dict.fromkeys(k for r in rows for k in r))
        with (self.dir/'metrics.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
    def close(self):self.writer.close()
