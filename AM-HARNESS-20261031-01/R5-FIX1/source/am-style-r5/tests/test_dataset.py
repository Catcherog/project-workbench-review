"""Offline contract tests. Human/model labels below are explicit test fixtures.

The test creates temporary artifacts only. Its fabricated reviewer is not the
user, and no generated approval or gold row is packaged as actual training data.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from am_style.contracts import StylePolicy
from am_style.data import DataError
from am_style.render import make_frame
from am_style_r5.common import (R5Error, canonical, file_hash, object_hash, read_json,
                                read_jsonl, seal, text_hash, write_json)
from am_style_r5.dataset import (BASELINE_HASHES, build_review_batch,
    export_gold_snapshot, feedback_template, freeze_group_registry,
    import_feedback_file, markdown_review, revise_review_batch,
    validate_review_batch, verify_gold_snapshot)
from am_style_r5.scenarios import calibration_specs


ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "baseline/data/r4-gold/sft.train.jsonl"
DEV = ROOT / "baseline/data/r4-gold/sft.dev.jsonl"
FAILURES = (R5Error, DataError)


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs = calibration_specs()
        cls.registry = freeze_group_registry(cls.specs, baseline_train=TRAIN, baseline_dev=DEV)
        cls.batch = build_review_batch(cls.specs, cls.registry, version="R5-test-pending")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r5-data-fixture-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def fixture_feedback(self, batch=None, *, selected=None, name="feedback.json"):
        """Fabricated fixture to exercise the parser, not actual user feedback."""
        batch = batch or self.batch
        feedback = feedback_template(batch)
        selected = set(selected or [])
        if selected:
            feedback.update(origin="human", reviewer="synthetic_unit_test_reviewer_not_the_user",
                            reviewed_at="2026-11-02T19:00:00+08:00")
        for rating in feedback["ratings"]:
            if rating["id"] not in selected:
                continue
            rating.update(status="reviewed", accepted_candidate="proposed_revision")
            rating["assessments"]["proposed_revision"].update(
                facts_pass=True, style_pass=True, acceptable=True)
        path = self.root / name
        write_json(path, feedback)
        return path

    def test_pending_batch_has_no_implicit_human_or_model_approval(self):
        self.assertEqual(len(self.batch["cases"]), 22)
        self.assertEqual(sum(r["split"] == "train" for r in self.batch["cases"]), 15)
        self.assertEqual(sum(r["split"] == "dev" for r in self.batch["cases"]), 7)
        for record in self.batch["cases"]:
            self.assertEqual(record["reviews"], {})
            self.assertFalse(record["training_approved"])
            proposal = record["candidates"]["proposed_revision"]
            self.assertEqual(proposal["origin"], "assistant_authored_proposal")
            self.assertFalse(proposal["model_run"])
            self.assertFalse(proposal["human_approved"])
        imported = import_feedback_file(self.batch, self.fixture_feedback())
        self.assertTrue(all(not rows for rows in imported["r4_import"]["exports"]["outputs"].values()))

    def test_snapshot_with_no_new_acceptance_preserves_fixed_nine_and_one_bytes(self):
        snapshot = export_gold_snapshot(self.registry, [], baseline_train=TRAIN,
                                       baseline_dev=DEV, output_dir=self.root / "snapshot")
        self.assertEqual(snapshot["counts"], {"train": 9, "dev": 1, "train_groups": 9, "dev_groups": 1})
        for split, original in (("train", TRAIN), ("dev", DEV)):
            actual = self.root / "snapshot" / snapshot["files"][split]["path"]
            self.assertEqual(actual.read_bytes(), original.read_bytes())
            self.assertEqual(file_hash(actual), BASELINE_HASHES[split])
        with self.assertRaises(FileExistsError):
            export_gold_snapshot(self.registry, [], baseline_train=TRAIN,
                                 baseline_dev=DEV, output_dir=self.root / "snapshot")

    def test_real_import_contract_appends_only_exact_accepted_complete_answers(self):
        train_id = next(r["id"] for r in self.batch["cases"] if r["split"] == "train")
        dev_id = next(r["id"] for r in self.batch["cases"] if r["split"] == "dev")
        feedback_path = self.fixture_feedback(selected=[train_id, dev_id])
        original_source = self.root / "original-feedback.txt"
        original_source.write_text("SYNTHETIC UNIT TEST TRANSCRIPT; NOT A REAL HUMAN APPROVAL\n", encoding="utf-8")
        imported = import_feedback_file(self.batch, feedback_path, raw_feedback_path=original_source)
        self.assertEqual(imported["raw_feedback_file"]["sha256"], file_hash(original_source))
        snapshot = export_gold_snapshot(self.registry, [imported], baseline_train=TRAIN,
                                       baseline_dev=DEV, output_dir=self.root / "snapshot")
        self.assertEqual(snapshot["counts"]["train"], 10)
        self.assertEqual(snapshot["counts"]["dev"], 2)
        for split, original in (("train", TRAIN), ("dev", DEV)):
            actual = self.root / "snapshot" / snapshot["files"][split]["path"]
            self.assertTrue(actual.read_bytes().startswith(original.read_bytes()))
            row = read_jsonl(actual)[-1]
            self.assertEqual(row["provenance"]["raw_feedback_file_sha256"], file_hash(original_source))
            self.assertEqual(row["provenance"]["r5_import_sha256"], imported["sha256"])
        # Snapshot verification uses its retained evidence, not the original paths.
        feedback_path.unlink()
        original_source.unlink()
        self.assertEqual(verify_gold_snapshot(self.root / "snapshot/snapshot.json"), snapshot)

    def test_candidate_edit_invalidates_the_old_feedback_and_preserves_original_batch(self):
        ident = self.batch["cases"][0]["id"]
        feedback_path = self.fixture_feedback(selected=[ident])
        original_hash = self.batch["batch_sha256"]
        revised = revise_review_batch(self.batch, {ident: "新的完整答复，需要人工重新核对。"}, version="R5-revision-2")
        self.assertNotEqual(revised["batch_sha256"], original_hash)
        self.assertEqual(self.batch["batch_sha256"], original_hash)
        self.assertEqual(revised["parent_batch_sha256"], original_hash)
        with self.assertRaises(FAILURES):
            import_feedback_file(revised, feedback_path)
        pending = feedback_template(revised)
        self.assertTrue(all(r["status"] == "pending" for r in pending["ratings"]))

    def test_human_origin_reviewer_timezone_and_full_text_binding_are_required(self):
        ident = self.batch["cases"][0]["id"]
        original = read_json(self.fixture_feedback(selected=[ident]))
        mutations = [lambda f: f.update(origin="model"), lambda f: f.update(reviewer=""),
                     lambda f: f.update(reviewed_at="2026-11-02T19:00:00"),
                     lambda f: f["ratings"][0]["assessments"]["proposed_revision"].update(candidate_sha256="0" * 64),
                     lambda f: f["ratings"][0]["assessments"]["proposed_revision"].update(acceptable=None)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                feedback = deepcopy(original)
                mutate(feedback)
                path = self.root / f"bad-{index}.json"
                write_json(path, feedback)
                with self.assertRaises(FAILURES):
                    import_feedback_file(self.batch, path)

    def test_a_changed_original_feedback_file_blocks_export(self):
        path = self.fixture_feedback(selected=[self.batch["cases"][0]["id"]])
        imported = import_feedback_file(self.batch, path)
        path.write_text(path.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(R5Error, "feedback file changed"):
            export_gold_snapshot(self.registry, [imported], baseline_train=TRAIN,
                                 baseline_dev=DEV, output_dir=self.root / "snapshot")
        self.assertFalse((self.root / "snapshot").exists())

    def test_duplicate_imports_or_case_ids_cannot_increase_counts(self):
        ident = self.batch["cases"][0]["id"]
        imported = import_feedback_file(self.batch, self.fixture_feedback(selected=[ident]))
        with self.assertRaisesRegex(R5Error, "duplicate feedback import"):
            export_gold_snapshot(self.registry, [imported, imported], baseline_train=TRAIN,
                                 baseline_dev=DEV, output_dir=self.root / "same-import")
        second = import_feedback_file(self.batch, self.fixture_feedback(selected=[ident], name="again.json"))
        with self.assertRaisesRegex(DataError, "duplicate/empty record ID"):
            export_gold_snapshot(self.registry, [imported, second], baseline_train=TRAIN,
                                 baseline_dev=DEV, output_dir=self.root / "same-case")

    def test_resealed_registry_cannot_move_old_dev_to_train(self):
        registry = deepcopy(self.registry)
        registry["legacy_groups"]["empty-todo-complete-read"] = "train"
        registry["groups"]["empty-todo-complete-read"] = "train"
        registry = seal(registry)
        with self.assertRaisesRegex(R5Error, "historical scenario split"):
            build_review_batch(self.specs, registry, version="malicious-self-reseal")

    def test_cross_split_near_copy_and_exact_copies_cannot_be_added(self):
        duplicate = deepcopy(self.specs[0])
        duplicate["id"] = "R5-duplicate-prompt"
        with self.assertRaisesRegex(R5Error, "copied prompt"):
            freeze_group_registry(self.specs + [duplicate], baseline_train=TRAIN, baseline_dev=DEV)
        # New spelling in one sentence does not create an independent dev group.
        almost = deepcopy(duplicate)
        almost.update(id="R5-near-copy", group_id="r5-near-copy-dev", split="dev")
        almost["frame"]["question"] += "呀"
        with self.assertRaisesRegex(DataError, "cross-split near duplicate"):
            freeze_group_registry(self.specs + [almost], baseline_train=TRAIN, baseline_dev=DEV)

    def test_frame_or_prompt_changes_require_a_new_registry(self):
        changed = deepcopy(self.specs)
        changed[0]["frame"]["question"] += "请提供来源。"
        with self.assertRaisesRegex(R5Error, "differs from the frozen registry"):
            build_review_batch(changed, self.registry, version="changed-frame")

    def test_sealed_test_scenario_is_frozen_but_never_presented_or_exported(self):
        policy = StylePolicy(realization="free")
        frame = make_frame(binding={"turn_id": "private-fixture", "scope_id": "unit-tests",
            "outcome_hash": object_hash({"fixture": "sealed-only"}), "source_revision": "test",
            "revision": 0, "cancel_epoch": 0}, expires_at=2000000000,
            question="这份存档能证明审批有效吗？", family="control", policy=policy,
            facts=[{"id": "archive", "kind": "statement", "value": "存档的签名尚未核实，不能证明审批有效"}])
        held = {"id": "R5-sealed-fixture", "group_id": "r5-sealed-archive", "split": "sealed_test",
                "synthetic": True, "frame": frame.data, "style_policy": policy.as_dict()}
        specs = self.specs + [held]
        registry = freeze_group_registry(specs, baseline_train=TRAIN, baseline_dev=DEV)
        batch = build_review_batch(specs, registry, version="with-sealed-reservation")
        self.assertEqual(len(batch["cases"]), 22)
        self.assertIn(held["id"], batch["unselected_case_ids"])
        self.assertNotIn(held["id"], markdown_review(batch))
        snapshot = export_gold_snapshot(registry, [], baseline_train=TRAIN, baseline_dev=DEV,
                                       output_dir=self.root / "snapshot")
        self.assertEqual(snapshot["sealed_test"]["exported_rows"], 0)
        self.assertEqual(snapshot["counts"]["train"], 9)

    def test_a_new_model_record_has_explicit_origin_and_zero_human_credit(self):
        # A fabricated invocation record tests parsing only. This is not a real model run.
        spec = deepcopy(self.specs[0])
        record = self.batch["cases"][0]
        text = "测试夹具中的模型答复，不是实际模型观测。"
        raw = canonical({"text": text})
        observation = {"schema": "am-style-r5-model-observation/1", "status": "completed",
            "actual_model_call": True, "provider": "unit_test_fixture", "model": "fictional",
            "run_id": "synthetic-not-a-real-run", "frame_sha256": object_hash(record["frame"]),
            "policy_sha256": object_hash(record["style_policy"]), "prompt_sha256": object_hash(record["prompt"]),
            "raw_response": raw, "candidate_text": text, "raw_response_sha256": text_hash(raw)}
        path = self.root / "model-observation-fixture.json"
        write_json(path, observation)
        spec["model_records"] = [{"path": str(path), "sha256": file_hash(path)}]
        batch = build_review_batch([spec], self.registry, version="model-origin-fixture")
        candidate = batch["cases"][0]["candidates"]["model_1"]
        self.assertEqual(candidate["origin"], "model_call")
        self.assertFalse(candidate["human_approved"])
        self.assertEqual(batch["counts"]["new_trainable_rows"], 0)
        observation["prompt_sha256"] = "0" * 64
        changed = self.root / "wrong-request.json"
        write_json(changed, observation)
        spec["model_records"] = [{"path": str(changed), "sha256": file_hash(changed)}]
        with self.assertRaisesRegex(R5Error, "another frozen request"):
            build_review_batch([spec], self.registry, version="wrong-model-request")

    def test_rehashing_files_and_snapshot_cannot_create_an_unreviewed_gold_row(self):
        output = self.root / "snapshot"
        snapshot = export_gold_snapshot(self.registry, [], baseline_train=TRAIN,
                                       baseline_dev=DEV, output_dir=output)
        path = output / snapshot["files"]["train"]["path"]
        row = deepcopy(read_jsonl(path)[0])
        row["id"] = "injected-unreviewed-row"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(canonical(row) + "\n")
        snapshot["files"]["train"]["sha256"] = file_hash(path)
        snapshot["files"]["train"]["rows"] += 1
        snapshot["counts"]["train"] += 1
        (output / "snapshot.json").write_text(json.dumps(seal(snapshot)), encoding="utf-8")
        with self.assertRaisesRegex(R5Error, "not derived from the retained human feedback"):
            verify_gold_snapshot(output / "snapshot.json")

    def test_pending_batch_cannot_claim_approval_by_updating_its_own_hash(self):
        batch = deepcopy(self.batch)
        batch["counts"]["new_human_approvals"] = 22
        batch.pop("batch_sha256")
        batch["batch_sha256"] = object_hash(batch)
        with self.assertRaisesRegex(R5Error, "cannot claim human approvals"):
            validate_review_batch(batch)

    def test_baseline_whitespace_reformatting_is_not_accepted_as_fixed_bytes(self):
        altered = self.root / "old-train.jsonl"
        altered.write_bytes(TRAIN.read_bytes() + b"\n")
        with self.assertRaisesRegex(R5Error, "not the fixed R4 combined"):
            export_gold_snapshot(self.registry, [], baseline_train=altered,
                                 baseline_dev=DEV, output_dir=self.root / "snapshot")


if __name__ == "__main__":
    unittest.main()
