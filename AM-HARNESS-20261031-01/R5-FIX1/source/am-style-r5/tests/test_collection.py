"""Interrupted-run recovery from actual local files, with no provider calls."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from am_style.contracts import SpeechFrame
from am_style.render import render_canonical
from am_style_r5.collection import collect_run_records
from am_style_r5.common import R5Error, canonical, file_hash, read_jsonl, seal, write_json
from am_style_r5.evaluation import build_plan, make_result_record
from am_style_r5.scenarios import calibration_specs, evaluation_cases


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = [self.root / "qwen", self.root / "mlx"]
        for path in self.runs:
            path.mkdir()
        shared = {"base_revision": "a" * 40, "model_manifest_sha256": "b" * 64,
                  "tokenizer_sha256": "c" * 64, "generation_settings": {"max_tokens": 192, "temperature": 0}}
        arms = {"production_q8": {"model_digest": "d" * 64, "generation_settings": {"max_tokens": 650, "temperature": None}},
                "mlx_base": {**deepcopy(shared), "adapter_sha256": None},
                "mlx_sft": {**deepcopy(shared), "adapter_sha256": "e" * 64}}
        self.plan = build_plan(evaluation_cases(calibration_specs()[:2]), arms, mode="fixture")
        self.output = self.root / "collected.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def record(self, index, arm, status="completed"):
        case = self.plan["cases"][index]
        raw = canonical({"text": render_canonical(SpeechFrame.freeze(case["frame"]))}) if status == "completed" else ""
        return make_result_record(self.plan, case["case_id"], arm, status=status, runner_source_sha256="f" * 64,
            capture_kind="fixture", request_artifact=canonical({"actual_messages": case["student_wire_messages"],
                "generation_settings": self.plan["arms"][arm]["generation_settings"]}),
            response_artifact=canonical({"text": raw, "stop_confirmed": False if status == "stop_unknown" else True}),
            raw_output=raw, latency_ms={"end_to_end": 250},
            request_binding={"wire_messages": {"path": ["actual_messages"]}, "generation_settings": {"path": ["generation_settings"]}},
            response_binding={"path": ["text"]})

    def test_recovers_completed_and_parent_interruption_without_results_file(self):
        records = [self.record(0, "production_q8"), self.record(0, "mlx_base"), self.record(1, "mlx_base", "stop_unknown")]
        source_paths = [self.runs[0] / "001-record.json", self.runs[1] / "001-record.json", self.runs[1] / "parent-interruption-record.json"]
        for path, record in zip(source_paths, records):
            write_json(path, record)
        nested = self.runs[0] / "unrelated-subdirectory"
        nested.mkdir()
        (nested / "999-record.json").write_text("not JSON and outside direct-child scope")
        self.assertFalse(any((root / "results.jsonl").exists() for root in self.runs))
        report = collect_run_records(self.plan, self.runs, self.output)
        self.assertEqual((report["planned"], report["recorded"], report["missing"]), (6, 3, 3))
        self.assertEqual(report["recorded_statuses"], {"completed": 2, "stop_unknown": 1})
        self.assertEqual(read_jsonl(self.output), records)
        self.assertEqual(report["synthetic_missing_records_written"], 0)
        self.assertEqual(report["new_model_calls"], 0)
        self.assertEqual(report["current_worker_stop_status"], "not_checked")
        self.assertTrue(all(source["sha256"] == file_hash(source["path"]) for source in report["sources"]))

    def test_worker_and_parent_duplicate_case_arm_is_not_chosen_automatically(self):
        write_json(self.runs[0] / "001-record.json", self.record(0, "mlx_base"))
        write_json(self.runs[1] / "parent-interruption-record.json", self.record(0, "mlx_base", "stop_unknown"))
        with self.assertRaisesRegex(R5Error, "duplicate result"):
            collect_run_records(self.plan, self.runs, self.output)
        self.assertFalse(self.output.exists())

    def test_one_corrupt_record_blocks_entire_collection_without_silent_skip(self):
        write_json(self.runs[0] / "001-record.json", self.record(0, "production_q8"))
        bad = self.runs[1] / "002-record.json"
        changed = self.record(1, "mlx_base")
        changed["status"] = "failed"  # The original seal no longer matches.
        for payload in ('{"broken":', '{"duplicate":1,"duplicate":2}', canonical(changed)):
            with self.subTest(payload=payload[:30]):
                bad.write_text(payload)
                with self.assertRaisesRegex(R5Error, "damaged record"):
                    collect_run_records(self.plan, self.runs, self.output)
                self.assertFalse(self.output.exists())

    def test_resealed_wrong_plan_or_input_still_fails_import_validation(self):
        path = self.runs[0] / "001-record.json"
        for field in ("plan_sha256", "input_sha256"):
            with self.subTest(field=field):
                record = self.record(0, "mlx_base")
                record[field] = "0" * 64
                path.write_text(canonical(seal(record)))
                with self.assertRaises(R5Error):
                    collect_run_records(self.plan, self.runs, self.output)
                self.assertFalse(self.output.exists())

    def test_failed_and_timeout_records_retained_and_output_never_overwritten(self):
        write_json(self.runs[0] / "001-record.json", self.record(0, "production_q8", "failed"))
        write_json(self.runs[1] / "001-record.json", self.record(1, "mlx_base", "timeout"))
        report = collect_run_records(self.plan, self.runs, self.output)
        self.assertEqual(report["recorded_statuses"], {"failed": 1, "timeout": 1})
        before = self.output.read_bytes()
        with self.assertRaisesRegex(R5Error, "fresh file"):
            collect_run_records(self.plan, self.runs, self.output)
        self.assertEqual(self.output.read_bytes(), before)

    def test_missing_directory_and_record_symlink_are_not_silently_ignored(self):
        with self.assertRaises(R5Error):
            collect_run_records(self.plan, [self.root / "does-not-exist"], self.output)
        source = self.root / "outside.json"
        write_json(source, self.record(0, "mlx_base"))
        (self.runs[0] / "001-record.json").symlink_to(source)
        with self.assertRaisesRegex(R5Error, "direct regular file"):
            collect_run_records(self.plan, self.runs, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
