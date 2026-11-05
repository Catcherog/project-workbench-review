from copy import deepcopy
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from model_lab.prepare import require_synthetic_origins
from model_lab.core import LabError
from model_lab.fixtures import fixture_spec
from model_lab.runner import _cascade

class OriginAndBudgetTests(unittest.TestCase):
    def test_real_snapshot_cannot_be_relabelled_by_execution_mode(self):
        for kind in ('real_authorized_workitem_snapshot','authorized_redacted',None):
            with self.assertRaises(LabError):
                require_synthetic_origins([{'case_id':'case','provenance':{'source_kind':kind}}])

    def test_explicit_synthetic_origin_is_preserved(self):
        require_synthetic_origins([{'case_id':'case','provenance':{'source_kind':'synthetic_scenario'}}])

    def test_known_blocked_reviewer_does_not_spend_first_call(self):
        spec=fixture_spec();spec['mode']='real'
        with tempfile.TemporaryDirectory() as directory, \
             patch('model_lab.runner.preflight_arm',return_value={'blockers':['reviewer unavailable']}), \
             patch('model_lab.runner._provider_batch',side_effect=AssertionError('must not call model')):
            result=_cascade(spec,'qwen_then_codex',spec['cases'],Path(directory))
        self.assertTrue(all(r['status']=='blocked' and not r['model_attempted'] for r in result.values()))
