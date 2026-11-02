"""Offline FIX1 contracts only; all people/declarations/cases here are fixtures.

No fixture is exported as a real human approval or an independent business test.
Mechanics/probe mocks isolate the new gate; no MLX, training, service or message
execution occurs in this suite.
"""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from am_style.contracts import SpeechFrame, StylePolicy
from am_style.prompt import build_messages, coordinator_messages
from am_style.render import make_frame
from am_style_r5 import pilot
from am_style_r5.cli import main
from am_style_r5.common import R5Error, canonical, file_hash, read_json, seal, write_json
from am_style_r5.evaluation import freeze_cases
from am_style_r5.holdout_gate import bind_holdout, verify_holdout
from am_style_r5.scenarios import calibration_specs
from test_pilot import _snapshot, _synthetic_request


def _replace_json(path, value):
    path.write_text(canonical(value) + "\n", encoding="utf-8")


def _case(frame=None, policy=None):
    policy = policy or StylePolicy(realization="free")
    frame = frame or make_frame(binding={"turn_id": "private-unit-holdout", "scope_id": "unit-fixture",
        "outcome_hash": "8" * 64, "source_revision": "temporary-fixture", "revision": 0, "cancel_epoch": 0},
        expires_at=2000000000, question="归档中的签字是否已经覆盖退货授权？", family="control", policy=policy,
        facts=[{"id": "signature-scope", "kind": "statement", "value":
            "仓库归档的是退件签收单，只证明已接收物件，未包含退货审批编号、批准者或核准数量；财务系统没有付款记录，不能由签收推断已获退货或退款授权。"}])
    logical = build_messages(frame, policy)
    return {"case_id": "UNIT-HOLDOUT-ONLY", "group_id": "unit-private-signature-scope", "split": "sealed_test",
            "frame": frame.data, "style_policy": policy.as_dict(), "logical_messages": logical,
            "student_wire_messages": coordinator_messages(logical),
            "review_context": "SYNTHETIC UNIT FIXTURE ONLY: a receipt is not a refund approval.",
            "independent_test_eligible": True, "public_exposed": False}


class HoldoutGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="r5-fix1-gate-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.snapshot_path, self.snapshot = _snapshot(self.root, accepted=True)
        self.work = self.root / "work"
        self.work.mkdir()
        self.base_plan = {"schema": pilot.PLAN_SCHEMA,
            "snapshot": {"path": str(self.snapshot_path), "sha256": file_hash(self.snapshot_path)},
            "snapshot_content_sha256": self.snapshot["sha256"],
            "run_directory": str(self.work / "unused-run"), "training_executed": False}
        self.manifest = {"local_model_path": str(self.root / "model"), "service": {
            "lease_file": str(self.root / "service/lease"), "gateway_db": str(self.root / "service/gateway.db"),
            "chat_db": str(self.root / "service/chat.db"),
            "protected_config_files": {str(self.root / "service/config.json"): "1" * 64}}}
        self.mechanics = self.root / "mechanics/result.json"
        self.manifest_path = self.root / "mechanics/manifest.json"
        write_json(self.mechanics, {"fixture": "NOT_REAL_MECHANICS"})
        write_json(self.manifest_path, self.manifest)
        self.request = _synthetic_request()
        self.request["code_sha256"] = {"fixture": "NOT_A_REAL_PROBE"}

    def evidence(self, *, cases=None, name="", declaration_changes=None):
        root = self.work / name
        root.mkdir(parents=True, exist_ok=True)
        cases_path, declaration_path, original_path = (root / "holdout.frozen.json",
            root / "declaration.json", root / "declaration-original.txt")
        frozen = freeze_cases(cases or [_case()])
        write_json(cases_path, frozen)
        original_path.write_text("SYNTHETIC UNIT TEST ORIGINAL. No real human declaration is asserted.\n", encoding="utf-8")
        declaration = {"case_manifest_sha256": frozen["case_manifest_sha256"], "not_used_for_tuning": True,
            "declared_by": "UNIT_TEST_FIXTURE_NOT_THE_USER",
            "declared_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "source_evidence_sha256": file_hash(original_path)}
        declaration.update(declaration_changes or {})
        write_json(declaration_path, declaration)
        return {"cases_path": cases_path, "declaration_path": declaration_path, "original_path": original_path}

    def bound_plan(self, evidence=None):
        plan = deepcopy(self.base_plan)
        plan["holdout_gate"] = bind_holdout(plan, **(evidence or self.evidence()))
        return seal(plan)

    def original_mock(self):
        return patch("am_style_r5.pilot._original_mechanics", return_value=(
            self.mechanics, self.manifest_path, self.request, self.manifest))

    def probe_mock(self, **kwargs):
        return patch("am_style_r5.pilot._run_probe", return_value={"blockers": [],
            "metadata_ready": True, "training_executed": False, "model_loaded": False}, **kwargs)

    def prepare(self, *, evidence=None, name="pilot-plan"):
        kwargs = {} if evidence is None else {"holdout_cases_path": evidence["cases_path"],
            "holdout_declaration_path": evidence["declaration_path"], "holdout_original_path": evidence["original_path"]}
        with self.original_mock(), self.probe_mock():
            return pilot.prepare_pilot(self.snapshot_path, self.mechanics, self.manifest_path,
                                       self.work / name, **kwargs)

    def test_valid_binding_rederives_without_adapter_or_private_text_in_plan(self):
        # The original R5 declaration schema has no required origin field.
        plan = self.bound_plan()
        gate = verify_holdout(plan)
        self.assertEqual(gate["case_count"], 1)
        self.assertEqual(gate["snapshot_content_sha256"], self.snapshot["sha256"])
        self.assertNotIn("arms", gate)
        self.assertNotIn("adapter_sha256", gate)
        self.assertNotIn("UNIT_TEST_FIXTURE_NOT_THE_USER", canonical(gate))
        self.assertNotIn("归档中的签字", canonical(gate))
        self.assertNotIn("SYNTHETIC UNIT TEST ORIGINAL", canonical(gate))
        self.assertIn("do_not_authenticate", gate["identity_limit"])

    def test_omitted_evidence_allows_metadata_preparation_and_preflight_exit_zero(self):
        prepared = self.prepare()
        report = prepared["preflight"]
        self.assertTrue(report["metadata_ready"])
        self.assertEqual(report["execution_gate"]["status"], "blocked")
        self.assertFalse(report["ready_for_launch"])
        self.assertEqual(report["resource_gate"]["status"], "not_checked")
        stream = io.StringIO()
        with self.original_mock(), self.probe_mock(), redirect_stdout(stream):
            code = main(["pilot-preflight", "--plan", prepared["plan_path"]])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stream.getvalue())["metadata_ready"])

    def test_legacy_plan_and_cached_green_flags_cannot_reach_any_subprocess(self):
        prepared = self.prepare()
        path = Path(prepared["plan_path"])
        plan = read_json(path)
        plan.pop("holdout_gate")
        plan.update(ready_for_launch=True, initial_preflight={"passed": True})
        _replace_json(path, seal(plan))
        with self.original_mock(), self.probe_mock():
            self.assertTrue(pilot.preflight_pilot(path)["metadata_ready"])
        for command in ("pilot-command", "pilot-execute"):
            args = [command, "--plan", str(path)] + (["--execute"] if command == "pilot-execute" else [])
            with self.subTest(command=command), self.original_mock(), \
                    patch("am_style_r5.cli.subprocess.run") as child, redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
                child.assert_not_called()

    def test_partial_holdout_paths_fail_before_plan_creation(self):
        with self.assertRaisesRegex(R5Error, "together"):
            pilot.prepare_pilot(self.snapshot_path, self.mechanics, self.manifest_path,
                self.work / "partial", holdout_cases_path=self.work / "cases.json")
        self.assertFalse((self.work / "partial").exists())
        with self.assertRaisesRegex(R5Error, "together"):
            bind_holdout(self.base_plan, cases_path=self.work / "cases.json")

    def test_case_declaration_original_and_snapshot_byte_changes_are_rejected(self):
        evidence = self.evidence()
        plan = self.bound_plan(evidence)
        for path in (*evidence.values(), self.snapshot_path):
            original = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(original + b"\n")
                with self.assertRaises(R5Error):
                    verify_holdout(plan)
                path.write_bytes(original)
        self.assertEqual(verify_holdout(plan), plan["holdout_gate"])

    def test_resealed_plan_change_does_not_reuse_old_gate(self):
        plan = self.bound_plan()
        plan["run_directory"] = str(self.work / "different-run")
        with self.assertRaisesRegex(R5Error, "plan changed"):
            verify_holdout(seal(plan))

    def test_case_group_overlap_with_actual_gold_is_rejected(self):
        for split in ("train", "dev"):
            spec = next(s for s in calibration_specs() if s["split"] == split)
            case = _case()
            case["group_id"] = spec["group_id"]
            with self.subTest(split=split), self.assertRaisesRegex(R5Error, "group overlaps"):
                bind_holdout(self.base_plan, **self.evidence(cases=[case], name="overlap-" + split))

    def test_near_duplicate_in_new_group_still_rejected(self):
        for split in ("train", "dev"):
            spec = deepcopy(next(s for s in calibration_specs() if s["split"] == split))
            spec["frame"]["question"] += "呀"
            case = _case(SpeechFrame.freeze(spec["frame"]), StylePolicy(**spec["style_policy"]))
            case["group_id"] = "unit-held-near-copy-" + split
            with self.subTest(split=split), self.assertRaisesRegex(R5Error, "leaks"):
                bind_holdout(self.base_plan, **self.evidence(cases=[case], name="near-" + split))

    def test_public_calibration_or_unqualified_cases_are_not_independent_holdout(self):
        for index, changes in enumerate(({"public_exposed": True}, {"independent_test_eligible": False},
                                         {"split": "calibration"})):
            case = _case()
            case.update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(R5Error, "private independent"):
                bind_holdout(self.base_plan, **self.evidence(cases=[case], name="public-" + str(index)))

    def test_case_bound_declaration_and_actual_original_hash_are_required(self):
        changes = [{"not_used_for_tuning": False}, {"source_evidence_sha256": "0" * 64},
                   {"case_manifest_sha256": "0" * 64}, {"origin": "model"}, {"declared_by": ""}]
        for index, change in enumerate(changes):
            with self.subTest(change=change), self.assertRaises(R5Error):
                bind_holdout(self.base_plan, **self.evidence(name="declaration-" + str(index), declaration_changes=change))

    def test_missing_original_and_malformed_inputs_raise_r5_error(self):
        evidence = self.evidence()
        evidence["original_path"].unlink()
        with self.assertRaisesRegex(R5Error, "missing holdout declaration original"):
            bind_holdout(self.base_plan, **evidence)
        evidence["declaration_path"].write_text('{"PRIVATE-DO-NOT-LOG":1,"PRIVATE-DO-NOT-LOG":2}', encoding="utf-8")
        with self.assertRaises(R5Error) as caught:
            bind_holdout(self.base_plan, **evidence)
        self.assertNotIn("PRIVATE-DO-NOT-LOG", str(caught.exception))
        with self.assertRaises(R5Error):
            verify_holdout({"holdout_gate": True})

    def test_declaration_timestamp_has_timezone_and_precedes_binding(self):
        for index, stamp in enumerate(("2026-11-02T00:00:00", "bad-time",
                                       (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())):
            with self.subTest(stamp=stamp), self.assertRaises(R5Error):
                bind_holdout(self.base_plan, **self.evidence(name="time-" + str(index),
                                                            declaration_changes={"declared_at": stamp}))

    def test_resealed_bundle_still_rechecks_frame_and_wire_prompt(self):
        evidence = self.evidence()
        bundle = read_json(evidence["cases_path"])
        bundle["cases"][0]["frame"]["question"] = "修改事实却保留旧输入？"
        _replace_json(evidence["cases_path"], seal(bundle))
        with self.assertRaisesRegex(R5Error, "disagree"):
            bind_holdout(self.base_plan, **evidence)

    def test_valid_gate_returns_original_trainer_command_but_not_resource_clearance(self):
        evidence = self.evidence()
        prepared = self.prepare(evidence=evidence)
        self.assertEqual(prepared["preflight"]["execution_gate"]["status"], "passed")
        with self.original_mock(), self.probe_mock(), patch("am_style_r5.cli.subprocess.run") as child:
            command = pilot.execution_argv(prepared["plan_path"])
            child.assert_not_called()
        self.assertEqual(command["argv"][1:3], ["-m", "training.mlx_r4"])
        self.assertIn("--execute", command["argv"])
        self.assertEqual(command["resource_status"], "not_checked")
        self.assertFalse(command["training_executed"])
        self.assertEqual(command["holdout_gate_sha256"], prepared["plan"]["holdout_gate"]["sha256"])

    def test_mutation_during_metadata_probe_blocks_cli_training_subprocess(self):
        evidence = self.evidence()
        prepared = self.prepare(evidence=evidence)
        def changed_during_probe(*args):
            evidence["original_path"].write_text("Changed original after the first gate read.\n", encoding="utf-8")
            return {"blockers": [], "metadata_ready": True, "training_executed": False}
        with self.original_mock(), patch("am_style_r5.pilot._run_probe", side_effect=changed_during_probe), \
                patch("am_style_r5.cli.subprocess.run") as child, redirect_stderr(io.StringIO()):
            code = main(["pilot-execute", "--plan", prepared["plan_path"], "--execute"])
        self.assertEqual(code, 2)
        child.assert_not_called()

    def test_consistent_plan_rebind_during_probe_cannot_reuse_stale_metadata(self):
        evidence = self.evidence()
        prepared = self.prepare(evidence=evidence)
        path = Path(prepared["plan_path"])
        def rebound_during_probe(*args):
            changed = read_json(path)
            changed["run_directory"] = str(self.work / "another-run")
            changed["holdout_gate"] = bind_holdout(changed, **evidence)
            _replace_json(path, seal(changed))
            return {"blockers": [], "metadata_ready": True, "training_executed": False}
        with self.original_mock(), patch("am_style_r5.pilot._run_probe", side_effect=rebound_during_probe), \
                patch("am_style_r5.cli.subprocess.run") as child, redirect_stderr(io.StringIO()):
            code = main(["pilot-execute", "--plan", prepared["plan_path"], "--execute"])
        self.assertEqual(code, 2)
        child.assert_not_called()

    def test_holdout_files_allow_sibling_outputs_but_cannot_be_output_directories(self):
        evidence = self.evidence()
        prepared = self.prepare(evidence=evidence)
        self.assertEqual(Path(prepared["plan_path"]).parent.parent, self.work)
        with self.assertRaises(R5Error):
            pilot._check_output(evidence["cases_path"], self.manifest, evidence_files=evidence.values())
        with self.assertRaises(R5Error):
            pilot._check_output(evidence["cases_path"] / "run", self.manifest, evidence_files=evidence.values())

    def test_cli_passes_complete_holdout_paths_without_starting_training(self):
        evidence = self.evidence()
        stream = io.StringIO()
        with self.original_mock(), self.probe_mock(), patch("am_style_r5.cli.subprocess.run") as child, redirect_stdout(stream):
            code = main(["pilot-plan", "--snapshot", str(self.snapshot_path), "--mechanics", str(self.mechanics),
                "--manifest", str(self.manifest_path), "--output", str(self.work / "cli-plan"),
                "--holdout-cases", str(evidence["cases_path"]), "--holdout-declaration", str(evidence["declaration_path"]),
                "--holdout-original", str(evidence["original_path"])])
            child.assert_not_called()
        self.assertEqual(code, 0)
        plan = read_json(self.work / "cli-plan/plan.json")
        self.assertEqual(verify_holdout(plan)["case_count"], 1)


if __name__ == "__main__":
    unittest.main()
