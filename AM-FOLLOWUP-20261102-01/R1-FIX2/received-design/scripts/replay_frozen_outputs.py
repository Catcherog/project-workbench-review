#!/usr/bin/env python3
"""Re-run archived model JSON through current guards; never calls a real model.

Output measures deterministic gate changes only. 'accepted_unconfirmed' is
not a business-accuracy verdict and cannot be counted as human acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    bridge = repo / 'local-qwen3.8/feishu-bridge'
    sys.path.insert(0, str(bridge))
    from am_info_sync.extraction import ExtractionError
    from am_info_sync.models import Observation
    from info_extraction import BoundedCoordinatorExtractor
    fixture_path = bridge / 'tests/fixtures/qwen_followup_frozen_fix1.json'
    fixture = json.loads(fixture_path.read_text(encoding='utf-8'))
    results = []
    for case in fixture['cases']:
        response = json.dumps(case['output'], ensure_ascii=False)
        class ReplayOnly:
            calls = 0
            def complete(self, *a, **kw):
                self.calls += 1
                return SimpleNamespace(text=response, usage=None, elapsed=0)
        coordinator = ReplayOnly()
        extractor = BoundedCoordinatorExtractor(coordinator, lambda observation: {
            'subjects': case['subjects'],
            'allowed_subject_ids': [s['subject_id'] for s in case['subjects']]})
        observation = Observation('synthetic', 'replay_' + case['case'], 'v1', 100,
                                  text=case['input'])
        item = {'case': case['case'], 'input_sha256': hashlib.sha256(
            case['input'].encode('utf-8')).hexdigest(), 'fresh_model_calls': 0,
            'semantic_accuracy': 'not_measured', 'human_acceptance': 'not_performed'}
        try:
            candidates = extractor(observation)
            item.update(gate='accepted_unconfirmed', count=len(candidates))
        except ExtractionError as exc:
            item.update(gate='review_gap', code=str(exc), count=0)
        item['coverage'] = (extractor.last_call or {}).get('coverage')
        item['mock_provider_calls'] = coordinator.calls
        results.append(item)
    report = {'mode': 'offline_frozen_replay', 'extractor_version': extractor.version,
              'fixture_sha256': hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
              'fresh_model_calls': 0, 'platform_sends': 0,
              'semantic_accuracy': 'not_measured', 'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
