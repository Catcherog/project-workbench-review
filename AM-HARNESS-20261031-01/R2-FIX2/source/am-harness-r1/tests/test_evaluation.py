import unittest
from am_harness.evaluation import analyze, EvaluationError
from am_harness.demo import run_demo


def record(arm, **changes):
    value={"case_id":"exact-query","trial_id":"1","environment_id":"same-model-source-cache",
           "arm":arm,"live_model":True,"live_transport":True,"success":True,
           "first_useful_ms":1000 if arm=="baseline" else 500,"final_ms":1500,
           "model_calls":1,"unauthorized_reads":0,"duplicate_effects":0,"stale_publications":0}
    value.update(changes);return value


class EvaluationTests(unittest.TestCase):
    def test_synthetic_and_unpaired_data_cannot_claim_speedup(self):
        data=[record("baseline"),record("candidate",live_model=False)]
        result=analyze(data,minimum_pairs=1)
        self.assertFalse(result["performance_claim_allowed"])
        self.assertEqual(result["paired_live_trials"],0)
        result=analyze([record("baseline"),record("candidate",environment_id="different-cache")],minimum_pairs=1)
        self.assertEqual(result["paired_live_trials"],0)

    def test_same_environment_pair_compares_only_after_gates(self):
        result=analyze([record("baseline"),record("candidate")],minimum_pairs=1)
        self.assertTrue(result["performance_claim_allowed"])
        self.assertEqual(result["latency"]["first_useful_ms"]["p50_change_percent"],-50)
        result=analyze([record("baseline"),record("candidate",stale_publications=1)],minimum_pairs=1)
        self.assertEqual(result["status"],"failed_invariants")
        self.assertIsNone(result["latency"]["first_useful_ms"]["p50_change_percent"])

    def test_missing_quality_and_duplicate_records_do_not_pass(self):
        result=analyze([record("baseline"),record("candidate",success=None)],minimum_pairs=1)
        self.assertFalse(result["performance_claim_allowed"])
        self.assertEqual(result["correctness_regressions"],1)
        with self.assertRaises(EvaluationError): analyze([record("baseline"),record("baseline")])
        failed=analyze([record("baseline",success=False),record("candidate",success=False)],minimum_pairs=1)
        self.assertFalse(failed["performance_claim_allowed"])
        self.assertEqual(failed["successful_live_pairs"],0)

    def test_runnable_demo_exercises_real_sqlite(self):
        result=run_demo()
        self.assertTrue(result["all_checks_passed"])
        self.assertFalse(result["live_model"])
