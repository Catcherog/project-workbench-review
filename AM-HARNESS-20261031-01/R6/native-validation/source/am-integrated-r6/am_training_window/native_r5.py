"""Actual original R5 CLI callback and independent original R4 stop proof.

This is supplied to TrainingWindow.train, after its maintenance lock is released.
The diagnostic control port never imports or invokes it. No R4 argv is cached.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from .r5_gate import OriginalR5InputGate
from .window import ExecutionObservation, WindowError


def group_gone(pid):
    if type(pid) is not int or pid<=1:return False
    try:os.killpg(pid,0)
    except ProcessLookupError:return True
    except PermissionError:return False
    return False


def phase_stop_proof(result, check_group=group_gone):
    phases=result.get('phases')
    if not isinstance(phases,list) or not phases:return False
    names=[p.get('phase') for p in phases]
    if names!=['fit','reload']:return False
    if any(p.get('attempted') is not True and not (p.get('phase')=='reload'
            and p.get('attempted') is False and p.get('status')=='skipped_fit_not_completed_or_stop_unconfirmed') for p in phases):return False
    attempted=[p for p in phases if p.get('attempted') is True]
    if not attempted:return False
    return all(p.get('stop_confirmed') is True and check_group(p.get('pid')) for p in attempted)


class OriginalPilotExecutor:
    def __init__(self, plan_path, evidence_directory):
        self.plan=Path(plan_path)
        self.evidence=Path(evidence_directory)
        if not self.plan.is_absolute() or not self.evidence.is_absolute():raise ValueError('absolute original paths required')
        self.process=None;self.run_directory=None;self.result=None;self.cli_start_attempts=0

    def stopped(self):
        # Called independently by TrainingWindow before any Q8 restoration.
        if self.process is None:return self.cli_start_attempts==0
        if self.process.poll() is None:return False
        if not group_gone(self.process.pid):return False
        if self.result is None:
            # A denied original CLI created no run. Otherwise absence of result
            # is an unknown worker state, even if the parent has exited.
            return self.run_directory is not None and not self.run_directory.exists()
        return phase_stop_proof(self.result)

    def __call__(self):
        if self.process is not None or self.cli_start_attempts:raise WindowError('pilot_callback_already_used')
        OriginalR5InputGate(self.plan)()  # Missing inputs do not even spawn a CLI.
        from am_style_r5 import pilot
        from am_style_r5.common import read_json
        plan=read_json(self.plan)
        self.run_directory=Path(plan['run_directory'])
        if self.run_directory.exists():raise WindowError('original_run_directory_already_exists')
        python=plan['python_interpreter']['path']
        package_root=Path(pilot.__file__).resolve().parents[1]
        self.evidence.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.evidence.is_symlink():raise WindowError('execution_evidence_symlink')
        label=uuid.uuid4().hex;log=self.evidence/(label+'.log')
        env=dict(os.environ,PYTHONPATH=str(package_root),PYTHONDONTWRITEBYTECODE='1')
        command=[python,'-m','am_style_r5','pilot-execute','--plan',str(self.plan),'--execute']
        started=time.time()
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            self.cli_start_attempts+=1
            self.process=subprocess.Popen(command,cwd=package_root,env=env,stdin=subprocess.DEVNULL,
                stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            # The unchanged R4 owns the reviewed fit/reload timeout policy.
            # On interruption the caller retains maintenance until stopped().
            code=self.process.wait()
        result_path=self.run_directory/'result.json'
        result_hash=None
        if result_path.is_file() and not result_path.is_symlink() and result_path.stat().st_mtime>=started:
            self.result=read_json(result_path)
            if self.result.get('schema')!='am-style-mlx-r4-result/1':raise WindowError('original_r4_result_schema')
            result_hash=hashlib.sha256(result_path.read_bytes()).hexdigest()
        stopped=self.stopped()
        completed=(code==0 and stopped and self.result is not None and self.result.get('mechanics_closed') is True
                   and [p.get('phase') for p in self.result['phases']]==['fit','reload']
                   and all(p.get('attempted') is True and p.get('status')=='completed' for p in self.result['phases']))
        evidence={'schema':'am-original-r5-execution-observation/1','started':started,'finished':time.time(),
            'cli_pid':self.process.pid,'cli_returncode':code,'cli_start_attempts':self.cli_start_attempts,
            'original_r4_result_sha256':result_hash,'original_phases':None if self.result is None else self.result.get('phases'),
            'original_cli_group_gone':group_gone(self.process.pid),'independent_worker_groups_gone':stopped,
            'status':'completed' if completed else 'blocked_or_failed','log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
        raw=(json.dumps(evidence,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
        path=self.evidence/(label+'.json');fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
        return ExecutionObservation(evidence['status'],stopped,hashlib.sha256(raw).hexdigest())
