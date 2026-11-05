"""Source-driven, reviewable synthetic candidates. Never manufacture human gold."""
from pathlib import Path
import argparse
import hashlib
import json
import re
from .profile import profile_from_owner_messages, require_style
from .scenarios import FAMILIES, DEV, semantic_case, render, alternate_style

SYSTEM = '你是项目助理。只依据给定事实回答，先说结果，再说必要的下一步。表达自然、简洁，保留预计、如果、待核、未完成等限定。没有实际回执不声称已发送、已批准或已完成；缺失人员和日期不猜测。只输出给用户看的正文。'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def scenario(family, index, style=None):
    case = semantic_case(family, index)
    style = style or {'layout': 'compact', 'request_register': 'direct'}
    return case['question'], case['facts'], render(case, style), case['incorrect_boundary_example']


def generate(profile, out, per_family=120):
    style = require_style(profile)
    if type(per_family) is not int or per_family < 4:
        raise ValueError('per_family must be >=4')
    out = Path(out)
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    sft, dpo, provenance = {'train': [], 'dev': []}, {'train': [], 'dev': []}, []
    for family in FAMILIES:
        split = 'dev' if family in DEV else 'train'
        for i in range(per_family):
            case = semantic_case(family, i)
            chosen = render(case, style)
            user = json.dumps({'task': case['question'], 'facts': case['facts'], 'synthetic': True}, ensure_ascii=False, sort_keys=True)
            messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]
            sid = f'r10-fix1-{family}-{i:04d}'
            sft[split].append({'messages': messages + [{'role': 'assistant', 'content': chosen}]})
            provenance.append({'sample_id': sid, 'previous_sample_id': f'r10-{family}-{i:04d}',
                'family': family, 'split': split, 'input_sha256': digest(messages), 'output_sha256': digest(chosen),
                'semantic_sha256': digest(case), 'style_profile_sha256': digest(profile), 'style_used': style,
                'style_evidence_keys': [p['key'] for p in profile['observed_preferences']],
                'data_classification': 'synthetic', 'generator': 'source_driven_semantic_templates_v2',
                'human_approved': False, 'training_eligible': False})
            if i % 2 == 0:
                style_only = i % 4 == 0
                negative = render(case, alternate_style(style)) if style_only else case['incorrect_boundary_example']
                dpo[split].append({'prompt': messages, 'chosen': [{'role': 'assistant', 'content': chosen}],
                    'rejected': [{'role': 'assistant', 'content': negative}], 'metadata': {
                        'sample_id': sid, 'preference_kind': 'style_only' if style_only else 'factual_boundary',
                        'preference_source': 'synthetic_rule_with_observed_style' if style_only else 'synthetic_fact_rule',
                        'both_fact_correct_by_semantic_construction': style_only,
                        'style_profile_sha256': digest(profile),
                        'chosen_style': style,
                        'rejected_style': alternate_style(style) if style_only else None,
                        'preference_reason': ('同一事实，以有来源的表达配置为偏好；另一表达也是自然且事实正确的候选'
                                              if style_only else '负例有意违反当前家族的事实或动作边界，独立于表达偏好'),
                        'chosen_semantic_sha256': digest(case),
                        'rejected_semantic_sha256': digest(case) if style_only else None,
                        'human_approved': False, 'family': family, 'split': split}})
    manifest = {'schema': 'am-synthetic-training-candidates/2', 'style_profile_sha256': digest(profile),
        'scenario_families': len(FAMILIES), 'train_families': sorted(set(FAMILIES) - DEV), 'dev_families': sorted(DEV),
        'independent_test_cases': 0, 'training_executed': False, 'human_approved_samples': 0, 'training_eligible': False,
        'limitations': ['Template variants are not independent semantic cases', 'Style is rule-derived, not user-confirmed',
                       'Synthetic candidates do not satisfy the existing human-gold MLX gate',
                       'Reserved synthetic evaluation is not independent human business acceptance'],
        'counts': {}, 'files': {}}
    for kind, groups in [('sft', sft), ('dpo', dpo)]:
        for split, rows in groups.items():
            if len({digest(row) for row in rows}) != len(rows):
                raise ValueError('duplicate candidates')
            name = f'{kind}.{split}.jsonl'
            content = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
            if re.search(r'ou_[a-f0-9]{12}|oc_[a-f0-9]{12}|om_[a-f0-9]{12}|IRAD-2026|RA-2026|AR221', content):
                raise ValueError('real identity in synthetic corpus')
            path = out / name
            path.write_text(content)
            path.chmod(0o600)
            manifest['counts'][name] = len(rows)
            manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name, value in [('profile.json', profile), ('provenance.json', provenance), ('manifest.json', manifest)]:
        path = out / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        path.chmod(0o600)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner-messages', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(generate(profile_from_owner_messages(json.loads(Path(args.owner_messages).read_text())), args.output), ensure_ascii=False))
