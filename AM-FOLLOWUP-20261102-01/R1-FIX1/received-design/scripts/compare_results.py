#!/usr/bin/env python3
"""Compare exact test IDs; a stable failure count is not sufficient."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('final', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    old = json.loads(args.baseline.read_text())['tests']
    new = json.loads(args.final.read_text())['tests']
    bad = {'failure', 'error'}
    result = {
        'new_failures': sorted(k for k, v in new.items() if v['status'] in bad
                               and old.get(k, {}).get('status') not in bad),
        'new_errors': sorted(k for k, v in new.items() if v['status'] == 'error'
                             and old.get(k, {}).get('status') != 'error'),
        'new_skips': sorted(k for k, v in new.items() if v['status'] == 'skipped'
                            and old.get(k, {}).get('status') != 'skipped'),
        'missing_tests': sorted(set(old) - set(new)),
        'existing_failures': sorted(k for k, v in new.items() if v['status'] in bad
                                   and old.get(k, {}).get('status') in bad),
        'fixed_baseline_failures': sorted(k for k, v in old.items() if v['status'] in bad
                                         and new.get(k, {}).get('status') == 'passed'),
        'added_passes': sorted(k for k, v in new.items() if k not in old and v['status'] == 'passed'),
        'existing_failure_mode_changes': sorted(k for k, v in new.items() if v['status'] in bad
            and old.get(k, {}).get('status') in bad and v['status'] != old[k]['status']),
        'existing_failure_message_changes': sorted(k for k, v in new.items() if v['status'] in bad
            and old.get(k, {}).get('status') in bad and v['message'] != old[k]['message']),
    }
    result['no_new_regression'] = not any(result[k] for k in (
        'new_failures', 'new_errors', 'new_skips', 'missing_tests', 'existing_failure_mode_changes'))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered)
    print(rendered)
    return 0 if result['no_new_regression'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
