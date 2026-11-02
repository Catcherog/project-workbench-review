import unittest
from am_style.evaluation import summarize, paired_preferences


class EvaluationTests(unittest.TestCase):
    def test_missing_case_cannot_shrink_denominator(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            summarize([{"case_id": "c1", "arm": "qwen"}], expected_cases=["c1","c2"], arms=["qwen"])

    def test_projection_and_unreceipted_output_are_not_delivery_or_adoption(self):
        report = summarize([{"case_id": "c1", "arm": "qwen", "eligible": True,
                             "attempted": True, "semantic_pass": True, "delivered": True,
                             "adopted": False, "duration_ms": 100}],
                           expected_cases=["c1"], arms=["qwen"])["arms"]["qwen"]
        self.assertEqual(report["adopted"], 0)
        self.assertEqual(report["delivered_with_receipt"], 0)
        self.assertIsNone(report["human_acceptance_rate"])

    def test_missing_pair_or_unverified_mapping_does_not_score_win(self):
        report = paired_preferences([
            {"left_available": False, "right_available": True, "human": True,
             "identity_join_verified": True, "choice": "right"},
            {"left_available": True, "right_available": True, "human": True,
             "identity_join_verified": False, "choice": "left"},
        ])
        self.assertEqual(report["excluded"], 2)
        self.assertIsNone(report["left_win_rate_decisive"])


if __name__ == "__main__":
    unittest.main()
