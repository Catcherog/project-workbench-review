"""R4 Codex proof and latency tests use local in-memory fixtures only."""
import json
import tempfile
import unittest
from pathlib import Path

from am_style.codex_isolation import explicit_schema_path, inspect_tool_inventory, propose_isolation
from am_style.contracts import canonical, digest
from am_style.latency import LatencyTrace, summarize_latency
from am_style.providers import ModelUnavailable, _file_sha, validate_codex_proof, _validate_codex_request_artifacts


class CodexIsolationTests(unittest.TestCase):
    def test_unrecognized_tools_are_visible_in_report(self):
        r = inspect_tool_inventory({"tools": [{"type": "namespace", "name": "functions", "tools": [{"type": "function", "name": "exec"}]}, {"type": "new_hosted_tool"}]})
        self.assertEqual(r["declared_tool_names"], ["functions.exec", "new_hosted_tool"])
        self.assertFalse(r["sufficient_for_generation"])

    def test_empty_declared_tools_do_not_certify_a_hidden_harness(self):
        r = inspect_tool_inventory({"tools": [], "agent": {"tools": []}})
        self.assertTrue(r["has_uninspected_harness"])
        self.assertFalse(r["full_effective_surface_verified"])
        with self.assertRaises(ValueError):
            inspect_tool_inventory({"model": "model-with-missing-tools-field"})

    def test_schema_wildcards_do_not_prove_feature_support(self):
        self.assertFalse(explicit_schema_path({"additionalProperties": True}, "features.code_mode.enabled"))
        schema = {"properties": {"features": {"$ref": "#/$defs/F"}}, "$defs": {"F": {"properties": {"code_mode": {"properties": {"enabled": {"type": "boolean"}}}}}}}
        self.assertTrue(explicit_schema_path(schema, "features.code_mode.enabled"))
        self.assertFalse(explicit_schema_path(schema, "features.multi_agent"))
        result = propose_isolation(cli_version="fixture-0.163", model="explicit-fixture", schema=schema, previous_observation={"observed_tool_names": ["functions.exec"]})
        self.assertFalse(result["candidate_switches_may_be_probed"])
        self.assertFalse(result["sufficient_for_generation"])

    def test_wrong_model_or_mock_tool_capture_cannot_unlock_provider(self):
        # Import only the explicit unit-test fixture; no account configuration.
        from test_providers import proof_fixture
        with tempfile.TemporaryDirectory() as tmp:
            binary, proof = proof_fixture(Path(tmp))
            with self.assertRaisesRegex(ModelUnavailable, "exact_real_model"):
                validate_codex_proof(str(binary), proof["profile"], proof, model="a-different-model")
            evidence = Path(proof["tool_surface_evidence"]["path"])
            observed = json.loads(evidence.read_text())
            observed["is_fixture"] = True
            evidence.write_text(canonical(observed))
            proof["tool_surface_evidence"]["sha256"] = _file_sha(evidence)
            with self.assertRaisesRegex(ModelUnavailable, "exact_real_model"):
                validate_codex_proof(str(binary), proof["profile"], proof, model=proof["model"])

    def test_nonfinite_expiry_is_not_freshness_evidence(self):
        from test_providers import proof_fixture
        with tempfile.TemporaryDirectory() as tmp:
            binary, proof = proof_fixture(Path(tmp))
            proof["valid_until_unix"] = float("nan")
            with self.assertRaisesRegex(ModelUnavailable, "fresh_real"):
                validate_codex_proof(str(binary), proof["profile"], proof, model=proof["model"])

    def test_forged_real_capture_flags_cannot_replace_missing_raw_artifacts(self):
        from test_providers import proof_fixture
        with tempfile.TemporaryDirectory() as tmp:
            binary, proof = proof_fixture(Path(tmp))
            evidence = Path(proof["tool_surface_evidence"]["path"])
            observed = json.loads(evidence.read_text())
            # Deliberately falsified flags in a negative test, never a usable
            # attestation: the required actual artifact graph is absent.
            proof["provider_id"] = "negative-test-declared-provider"
            observed.update(is_fixture=False, provider_override_used=False,
                provider_id=proof["provider_id"], request_tool_inventory_complete=True,
                uninspected_harness_present=False)
            evidence.write_text(canonical(observed))
            proof["tool_surface_evidence"]["sha256"] = _file_sha(evidence)
            with self.assertRaisesRegex(ModelUnavailable, "raw_model_request_artifacts"):
                validate_codex_proof(str(binary), proof["profile"], proof, model=proof["model"])

    def test_raw_request_and_catalog_are_read_and_tools_model_harness_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog.fixture.json"
            request = root / "request.fixture.json"
            catalog.write_text(canonical({"models": [{"slug": "fixture-model"}]}))
            request.write_text(canonical({"model": "fixture-model", "tools": []}))
            def artifacts():
                return {"model_catalog": {"path": str(catalog), "sha256": _file_sha(catalog)},
                    "captured_request": {"path": str(request), "sha256": _file_sha(request)},
                    "model_catalog_sha256": _file_sha(catalog), "request_sha256": _file_sha(request)}
            proof = artifacts()
            # Test only content validation; no successful real-proof fixture.
            _validate_codex_request_artifacts(proof, proof, "fixture-model")
            for payload in ({"model": "fixture-model", "tools": [{"type": "function", "name": "exec"}]},
                            {"model": "other-model", "tools": []},
                            {"model": "fixture-model"},
                            {"model": "fixture-model", "tools": [], "agent": {}}):
                with self.subTest(payload=payload):
                    request.write_text(canonical(payload))
                    proof = artifacts()
                    with self.assertRaises(ModelUnavailable):
                        _validate_codex_request_artifacts(proof, proof, "fixture-model")
            request.write_text(canonical({"model": "fixture-model", "tools": []}))
            proof = artifacts()
            catalog.write_text(canonical({"models": [{"slug": "other-model"}]}))
            with self.assertRaisesRegex(ModelUnavailable, "missing_or_changed"):
                _validate_codex_request_artifacts(proof, proof, "fixture-model")
            proof = artifacts()
            with self.assertRaisesRegex(ModelUnavailable, "missing_from_captured_catalog"):
                _validate_codex_request_artifacts(proof, proof, "fixture-model")


class LatencyTests(unittest.TestCase):
    def test_missing_phases_stay_unknown_and_slowest_stays_in_population(self):
        rows = [{"arm": "qwen", "attempted": True, "duration_ms": x} for x in [3000, 4000, 16000]]
        result = summarize_latency(rows)["qwen"]
        self.assertEqual(result["latency_n"], 3)
        self.assertEqual(result["max_ms"], 16000)
        self.assertEqual(result["load_state_unknown"], 3)
        self.assertIsNone(result["stages"]["model_load"]["p50_ms"])
        self.assertEqual(result["stages"]["model_load"]["measured"], 0)

    def test_monotonic_trace_records_only_measured_spans(self):
        clock = iter([1000000, 3000000])
        trace = LatencyTrace(clock_id="fixture-boot", clock=lambda: next(clock))
        trace.mark("enqueued"); trace.mark("claimed")
        result = trace.report()
        self.assertEqual(result["queue_wait_ms"], 2.0)
        self.assertIsNone(result["inference_ms"])
        with self.assertRaises(ValueError):
            trace.mark("claimed")


if __name__ == "__main__":
    unittest.main()
