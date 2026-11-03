"""Inspect existing authorized local provenance and source metadata; never label it as independent."""
from pathlib import Path
from collections import Counter
import hashlib, json, sqlite3, sys, time
from datetime import datetime, timezone

TASK = Path(__file__).resolve().parents[1]; ROOT = TASK.parents[1]
sys.path.insert(0, str(ROOT / 'local-qwen3.8/feishu-bridge'))
from am_info_sync.models import Principal, Source
from am_info_sync.policy import can_read
def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
files = [
    ROOT / 'AM-HARNESS-20261031-01/R5/private/feedback-003/calibration-current.frozen.json',
    ROOT / 'AM-HARNESS-20261031-01/R5/private/feedback-003/independent-holdout-user-response.json',
    ROOT / 'SFT训练/R6-FIX1_20261021_01/provenance/data_manifest.json',
    ROOT / 'SFT训练/R6-FIX1_20261021_01/evaluation/frozen_evaluation_manifest.json',
    ROOT / 'SFT训练/R6-FIX1_20261021_01/evaluation/baseline_holdout.jsonl',
    ROOT / 'SFT训练/R6-FIX1_20261021_01/evaluation/selected_holdout.jsonl',
    ROOT / 'SFT资料整合/模板关联指南修订_R6-FIX1_20261021/05_SFT训练数据/dataset_manifest.json',
    ROOT / 'SFT资料整合/模板关联指南修订_R6-FIX1_20261021/08_检索参考库/reference_manifest.json',
]
records = [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in files]
calibration, response, training, old_holdout = [read(p) for p in files[:4]]
assert len(calibration['cases']) == 22
assert '没有独立测试材料' in response['answer']
assert training['splits']['train']['samples'] == 214
old_evaluation_counts = {p.name: sum(bool(x.strip()) for x in p.read_text().splitlines()) for p in files[4:6]}
# Only already retained task-private JSON is scanned for a case-bound declaration.
# Do not include tests, examples, exports, model weights, browser profiles or unrelated user files.
declarations = []; frozen = []; scanned = 0
for relative in ('AM-HARNESS-20261031-01/R4/private', 'AM-HARNESS-20261031-01/R5/private'):
    for p in (ROOT / relative).rglob('*.json'):
        if p.stat().st_size > 10_000_000: continue
        scanned += 1
        try: value = read(p)
        except (ValueError, OSError): continue
        if not isinstance(value, dict): continue
        if value.get('not_used_for_tuning') is True and value.get('case_manifest_sha256'):
            declarations.append({'path': str(p.relative_to(ROOT)), 'sha256': sha(p)})
        if value.get('schema_version') == 'am-r5-frozen-cases/1':
            cases = value.get('cases', [])
            frozen.append({'path': str(p.relative_to(ROOT)), 'sha256': sha(p), 'count': len(cases),
                           'splits': dict(Counter(c.get('split') for c in cases)),
                           'eligible_private_sealed': sum(c.get('split') == 'sealed_test' and c.get('public_exposed', c.get('public_example')) is False and c.get('independent_test_eligible', c.get('independent')) is True for c in cases)})

cfg = read(Path.home() / '.local/share/local-qwen-feishu/config.json'); poc = read(Path(cfg['poc_config']))
principal = Principal(poc['feishu']['owner_notification_open_id'], poc['feishu']['tenant_key'])
db_path = Path(cfg['state_directory']) / 'information/information.sqlite3'
now = int(time.time() * 1000); sources = []; candidate_metadata = []; status = Counter()
with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
    db.row_factory = sqlite3.Row
    db.execute('BEGIN')
    for row in db.execute('SELECT source_id,config_json,availability FROM sources'):
        source = Source.from_dict(json.loads(row['config_json']))
        if not can_read(source, principal): continue
        status[row['availability']] += 1
        sources.append({'source_id': source.source_id, 'kind': source.kind, 'availability': row['availability']})
        if row['availability'] != 'ok': continue
        # Do not select raw text or payloads; metadata alone is sufficient to identify unresolved provenance.
        rows = db.execute('''SELECT o.object_id,o.current_version,r.occurred_at_ms,r.body_hash,r.raw_expires_at_ms
            FROM objects o JOIN observations r ON o.source_id=r.source_id AND o.object_id=r.object_id AND o.current_version=r.version
            WHERE o.source_id=? AND o.state='active' AND r.deleted=0 AND r.purged=0
              AND r.completeness='complete' AND r.raw_expires_at_ms>? ORDER BY r.occurred_at_ms DESC''',
            (source.source_id, now)).fetchall()
        for r in rows: candidate_metadata.append({'source_id': source.source_id, 'kind': source.kind, **dict(r)})
    db.rollback()
private = {'sources': sources, 'candidate_object_metadata': candidate_metadata, 'scanned_private_json': scanned,
           'declaration_records': declarations, 'frozen_bundles': frozen, 'evidence_files': records}
(TASK / 'private/candidate-source-index.json').write_text(json.dumps(private, ensure_ascii=False, indent=2) + '\n')
public = {'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'read_only': True,
          'scope': ['existing R4/R5 private experiment provenance', 'existing SFT dataset/evaluation provenance',
                    'current enabled owner-readable information source metadata; no remote collection or raw business text export'],
          'existing_gold': {'train': 24, 'dev': 8, 'use': 'already approved train/dev; excluded from holdout'},
          'r5_calibration': {'cases': 22, 'use': 'already used in three feedback rounds; excluded from independent test'},
          'older_sft': {'dataset_counts': {k: v['samples'] for k, v in training['splits'].items()},
                        'holdout_count': old_holdout['files']['holdout']['count'],
                        'synthetic': old_holdout['independent_synthetic_cases'],
                        'existing_generation_rows': old_evaluation_counts,
                        'disposition': 'already evaluated synthetic development material; not silently promoted to new human independent holdout'},
          'reference_library': read(files[7]),
          'source_metadata': {'authorized_enabled_sources': len(sources), 'kinds': dict(Counter(x['kind'] for x in sources)),
                              'availability': dict(status), 'current_complete_unexpired_objects': len(candidate_metadata),
                              'object_kinds': dict(Counter(x['kind'] for x in candidate_metadata)),
                              'raw_text_read': False, 'independence_verified': False,
                              'disposition': 'prospective source inventory only; no case freeze, unused-for-tuning provenance or case-bound human declaration'},
          'existing_private_json_scanned': scanned, 'case_bound_unused_declarations_found': len(declarations),
          'frozen_bundles_checked': len(frozen), 'private_sealed_case_candidates_in_existing_bundles': sum(x['eligible_private_sealed'] for x in frozen),
          'eligible_frozen_independent_test_cases': 0, 'human_declaration_created': False, 'new_feedback_requested': False,
          'new_hard_quantity_threshold': None,
          'blocking_reason': 'No verified private independent case bundle with case-bound human unused-for-tuning declaration and readable original.',
          'limitations': ['Metadata inventory does not establish that all authorized business sources are exhausted.',
                         'Existing ingestion or extraction does not by itself prove training contamination; scenario independence remains unverified.',
                         'Prior user response is retained, not treated as a new declaration for any candidate source.'],
          'evidence_files': records, 'private_index_sha256': sha(TASK / 'private/candidate-source-index.json'),
          'raw_business_data_published': False, 'production_changed': False}
(TASK / 'evidence/candidate-source-audit.json').write_text(json.dumps(public, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: public[k] for k in ('source_metadata', 'existing_private_json_scanned', 'case_bound_unused_declarations_found', 'frozen_bundles_checked', 'eligible_frozen_independent_test_cases')}, ensure_ascii=False))
