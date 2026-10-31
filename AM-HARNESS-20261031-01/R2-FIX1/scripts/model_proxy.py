"""Private synthetic model transport into the ORIGINAL consumer/coordinator."""
from pathlib import Path
from types import SimpleNamespace
import json,os,time,uuid

class OriginalCoordinatorProxy:
    def __init__(self,case):
        cfg=json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
        poc=json.loads(Path(cfg['poc_config']).read_text())
        self.directory=Path(poc['service']['root_directory'])/'state/am-conversation-r2'
        self.case=case;self.records=[]
    def complete(self,prompt,**kw):
        import subprocess
        source=Path(__file__).resolve().parents[1]/'worktree'
        expected=os.environ.get('AM_R2_EVAL_SHA')
        if expected and (subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()!=expected or subprocess.run(['git','diff','--quiet','HEAD'],cwd=source).returncode):
            raise RuntimeError('EVALUATION_SOURCE_CHANGED')
        from am_conversation.types import ConversationError
        label='r2fix1-'+uuid.uuid4().hex
        request={'operation':'task_model_probe','case':self.case,'expires_at':time.time()+180,
            'model_request':{'prompt':prompt,'json_schema':kw['json_schema'],'max_tokens':kw.get('max_tokens',1024),'timeout':min(110,kw.get('timeout',110))}}
        target=self.directory/'requests'/(label+'.json');temporary=target.with_suffix('.tmp')
        data=json.dumps(request,ensure_ascii=False,allow_nan=False).encode()
        if len(data)>50000:raise ConversationError('EVALUATION_REQUEST_TOO_LARGE')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data)
        temporary.replace(target);start=time.monotonic();result=self.directory/'results'/(label+'.json')
        while time.monotonic()-start<150 and not result.exists():time.sleep(.2)
        if not result.exists():raise ConversationError('EVALUATION_MODEL_RESULT_UNKNOWN')
        output=json.loads(result.read_text());output['proxy_wait_seconds']=time.monotonic()-start
        self.records.append(output)
        if not output.get('ok'):raise ConversationError(output.get('error','EVALUATION_MODEL_FAILED'))
        usage=output.get('model_calls',{}).get('calls',[])
        return SimpleNamespace(text=output['text'],model=output['model'],elapsed=time.monotonic()-start,usage=(usage[-1].get('usage') or {}) if usage else {})
