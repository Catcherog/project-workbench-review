"""Tokenizer-only diagnostics on frozen proposals; never approve or train them."""
from pathlib import Path
import json
import os
import sys

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]
SOURCE = TASK / 'worktree'
sys.path[:0] = [str(SOURCE / 'am-style-r5/src'), str(SOURCE / 'am-conversation-r1/src'), str(SOURCE / 'am-style-r3')]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
from transformers import AutoTokenizer
from am_style_r5.common import read_json, write_json, canonical, object_hash
from training.mlx_r4_contracts import encode_row

manifest = read_json(ROOT / 'AM-HARNESS-20261031-01/R4/private/mlx-base.json')
tokenizer = AutoTokenizer.from_pretrained(manifest['local_model_path'], local_files_only=True, trust_remote_code=False)
prepared = TASK / 'private/run-001/prepared'
cases = read_json(prepared / 'evaluation.calibration.json')
specs = {s['id']: s for s in read_json(prepared / 'scenarios.json')}
rows = []
for case in cases:
    spec = specs[case['case_id']]
    row = {'id': case['case_id'], 'prompt': case['student_wire_messages'],
           'completion': [{'role': 'assistant', 'content': canonical({'text': spec['proposal']})}],
           'provenance': {'split': spec['split'], 'prompt_sha256': object_hash(case['student_wire_messages'])}}
    try:
        result = encode_row(tokenizer, row, 1024)
        rows.append({'id': row['id'], 'status': 'within_length_boundary',
                     'prompt_tokens': result['prompt_tokens'], 'completion_tokens': result['completion_tokens'],
                     'full_tokens': len(result['input_ids']), 'token_ids_sha256': result['token_ids_sha256']})
    except Exception as exc:
        rows.append({'id': row['id'], 'status': 'blocked', 'reason': type(exc).__name__ + ': ' + str(exc)})
report = {'schema': 'am-r5-pending-length-diagnostic/1', 'max_length': 1024, 'cases': rows,
          'human_approval_status': 'pending', 'new_gold_rows': 0, 'training_executed': False,
          'tokenizer_only': True, 'model_loaded': False, 'max_observed_tokens': max([r.get('full_tokens', 0) for r in rows])}
write_json(TASK / 'evidence/pending-lengths.json', report)
print(json.dumps({'count': len(rows), 'blocked': sum(r['status'] == 'blocked' for r in rows),
                  'max_observed_tokens': report['max_observed_tokens'], 'model_loaded': False}))
