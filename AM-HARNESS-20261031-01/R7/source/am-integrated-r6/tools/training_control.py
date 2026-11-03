"""Submit or inspect one exact private R7 request; never run a shell or worker.

The original bridge performs all fresh gates, ownership checks and execution.
Submitting a request is not proof that a trainer started or completed.
"""
from pathlib import Path
import argparse
import json
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'am-integrated-r6'))
from am_training_window.process_guard import digest, private_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('train', 'eval-mlx', 'cancel', 'recover', 'inspect'))
    p.add_argument('--plan', type=Path)
    p.add_argument('--pilot-plan', type=Path)
    p.add_argument('--arm', choices=('mlx_base', 'mlx_sft'))
    p.add_argument('--run-id')
    p.add_argument('--request-id')
    p.add_argument('--expires-seconds', type=int, default=900)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    cfg = json.loads((Path.home()/'.local/share/local-qwen-feishu/config.json').read_text())
    control = Path(cfg['state_directory'])/'training-window-r7'
    if not control.is_dir() or control.is_symlink():
        p.error('original live training control directory is not installed')
    if not 1 <= a.expires_seconds <= 3600:
        p.error('expiry must be within 1..3600 seconds')
    request_id = a.request_id or str(uuid.uuid4())
    if str(uuid.UUID(request_id)) != request_id:
        p.error('request ID must be a canonical UUID')
    if a.operation in ('cancel', 'recover', 'inspect') and not a.request_id:
        p.error('supply the original --request-id')
    if a.operation == 'inspect':
        files = [control/(request_id+suffix) for suffix in ('.receipt.json', '.journal.json', '.result.json')]
        print(json.dumps({x.name: json.loads(x.read_text()) for x in files if x.is_file()}, ensure_ascii=False, indent=2))
        return 0
    request = {'operation': a.operation, 'request_id': request_id,
               'expires_at': time.time()+a.expires_seconds}
    suffix = '.request.json'
    if a.operation in ('train', 'eval-mlx'):
        if a.plan is None or not a.plan.is_absolute():
            p.error('supply the actual absolute --plan')
        plan = json.loads(a.plan.read_text())
        run_id = Path(plan['run_directory']).name if a.operation == 'train' else a.run_id
        request.update(plan=str(a.plan), plan_sha256=digest(a.plan), run_id=run_id)
        if a.operation == 'eval-mlx':
            if not a.pilot_plan or not a.pilot_plan.is_absolute() or not a.arm or not run_id:
                p.error('evaluation requires --pilot-plan, --arm and new --run-id')
            request.update(pilot_plan=str(a.pilot_plan), pilot_plan_sha256=digest(a.pilot_plan), arm=a.arm)
    elif a.operation == 'cancel':
        original = json.loads((control/(request_id+'.receipt.json')).read_text())
        request = {'request_id': request_id, 'plan_sha256': original['plan_sha256'],
                   'expires_at': request['expires_at']}
        suffix = '.cancel.json'
    # Recovery uses a fresh envelope filename while retaining the original ID.
    name = request_id if a.operation != 'recover' else request_id+'-recover-'+uuid.uuid4().hex
    destination = control/(name+suffix)
    if a.execute:
        private_json(destination, request, exclusive=True)
    print(json.dumps({'submitted': a.execute, 'request_id': request_id, 'path': str(destination),
                      'request': request, 'training_status': 'not_observed'}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
