"""Real fixed prompt bytes plus clearly fictional model-call test doubles."""
import copy
import json
from pathlib import Path
import unittest

from am_style.contracts import digest as object_hash
from am_style.data import DataError, normalized_prompt
from am_style.silver import prepare_silver_sft_row
from am_style.transport import (CODEX_STDIN, COORDINATOR_NATIVE, DIRECT_CHAT, bind_prompt,
    runtime_binding, student_contract_version, student_prompt, validate_binding, validate_student_record)
from tests.test_silver import fixture

ROOT = Path(__file__).resolve().parents[1]


class TransportTests(unittest.TestCase):
    def test_actual_r3_gold_native_wire_is_accepted_without_changing_bytes(self):
        frozen = json.loads((ROOT / "data/r3/frozen-comparison.json").read_text())
        cases = {r["case_id"]: r for r in frozen["cases"]}
        for name in ("sft.train.jsonl", "sft.dev.jsonl"):
            path = ROOT / "data/r3" / name
            before = path.read_bytes()
            gold = json.loads(before)
            target = runtime_binding(cases[gold["id"]]["frame"], frozen["policy"])
            record = {"frame": cases[gold["id"]]["frame"], "style_policy": frozen["policy"],
                "target_binding": target, "prompt": gold["prompt"],
                "host_contract_version": gold["provenance"]["host_contract_version"],
                "runtime_prompt_alignment": "aligned"}
            validate_student_record(record)
            self.assertEqual(student_prompt(target), gold["prompt"])
            self.assertEqual(object_hash(gold["prompt"]), gold["provenance"]["prompt_sha256"])
            self.assertEqual(path.read_bytes(), before)

    def test_codex_teacher_wire_stays_separate_from_native_student_prompt(self):
        record, anchor = fixture()
        producer = record["candidates"]["model_fixture"]["producer_binding"]
        self.assertEqual(producer["profile"], CODEX_STDIN)
        self.assertEqual(producer["wire_payload"]["kind"], "stdin_utf8")
        row = prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)
        self.assertEqual(row["prompt"], student_prompt(record["target_binding"]))
        self.assertEqual(row["provenance"]["target_transport_profile"], COORDINATOR_NATIVE)
        record["prompt"] = producer["logical_messages"]
        with self.assertRaisesRegex(DataError, "student wire"):
            prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)

    def test_wrong_role_and_double_envelope_cannot_be_silent_alignment(self):
        record, anchor = fixture()
        record["target_binding"] = record["candidates"]["model_fixture"]["producer_binding"]
        with self.assertRaisesRegex(DataError, "wrong purpose"):
            prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)
        record, _ = fixture()
        b = record["target_binding"]
        twice = bind_prompt(student_prompt(b), profile=COORDINATOR_NATIVE, purpose="student",
            frame_sha256=b["frame_sha256"], policy_sha256=b["policy_sha256"])
        record.update(target_binding=twice, prompt=student_prompt(twice))
        with self.assertRaisesRegex(DataError, "logical_messages differs"):
            validate_student_record(record)

    def test_judge_transport_and_semantic_profile_are_bound(self):
        record, anchor = fixture()
        record["silver_judges"][0]["judge_binding"]["wire_payload"]["messages"][0]["content"] += "tampered"
        with self.assertRaisesRegex(DataError, "binding bytes"):
            prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)
        record, anchor = fixture()
        record["semantic_profile"] = "llm-says-pass"
        with self.assertRaisesRegex(DataError, "unsupported semantic profile"):
            prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)
        record, anchor = fixture()
        record["semantic_profile"] = "natural-typed-surfaces/4.0.1"
        with self.assertRaisesRegex(DataError, "bound assessment question"):
            prepare_silver_sft_row(record, gold_anchor=anchor, experimental_only=True)

    def test_shared_native_wrapper_does_not_distort_split_similarity(self):
        record, _ = fixture()
        logical = dict(record, prompt=record["target_binding"]["logical_messages"])
        self.assertEqual(normalized_prompt(record), normalized_prompt(logical))
        target = record["target_binding"]
        with self.assertRaisesRegex(DataError, "not a Qwen"):
            bind_prompt(target["logical_messages"], profile=CODEX_STDIN, purpose="student",
                frame_sha256=target["frame_sha256"], policy_sha256=target["policy_sha256"])


if __name__ == "__main__":
    unittest.main()
