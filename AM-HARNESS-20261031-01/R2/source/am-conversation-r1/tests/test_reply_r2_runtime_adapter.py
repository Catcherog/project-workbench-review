import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from am_reply.contracts import parse_candidate
from am_reply.model import CoordinatorRewriteModel
from am_reply.pipeline import ReplyRewriter
from am_reply.types import Claim, ContractError, ReplyContract, RewriteConfig, RewriteRequest


class RuntimeAdapterTests(unittest.TestCase):
    def payload(self):
        c = ReplyContract("test", (Claim("owner", ("陈甲负责测试", "测试由陈甲负责"), ("source",)),), "v1", "scope")
        return {"contract_fingerprint": c.fingerprint(), "max_groups": 3, "claims": [
            {"claim_id": "owner", "variants": list(c.claims[0].variants), "required": True, "depends_on": []}]}

    def test_existing_coordinator_receives_no_tools_and_exact_shared_budget(self):
        calls = []
        def complete(prompt, **kwargs):
            calls.append((prompt, kwargs))
            return SimpleNamespace(text='{"test":1}')
        model = CoordinatorRewriteModel(SimpleNamespace(complete=complete))
        self.assertEqual('{"test":1}', model.generate(self.payload(), timeout=1.7, queue_timeout=.1, max_tokens=256))
        self.assertEqual(1, len(calls))
        _, kwargs = calls[0]
        self.assertEqual(1.7, kwargs["timeout"])
        self.assertEqual(.1, kwargs["_queue_timeout"])
        self.assertEqual(256, kwargs["max_tokens"])
        self.assertTrue(kwargs["native_chat"])
        self.assertNotIn("tools", kwargs)
        self.assertEqual(32, len(kwargs["run_id"]))
        self.assertFalse(kwargs["json_schema"]["additionalProperties"])

    def test_provider_pause_escapes_adapter_without_retry_or_reconfiguration(self):
        calls = []
        def complete(*args, **kwargs):
            calls.append(1)
            raise RuntimeError("STOP_UNKNOWN")
        model = CoordinatorRewriteModel(SimpleNamespace(complete=complete))
        with self.assertRaisesRegex(RuntimeError, "STOP_UNKNOWN"):
            model.generate(self.payload(), timeout=2, queue_timeout=.1, max_tokens=256)
        self.assertEqual([1], calls)

    def test_duplicate_json_fields_rejected(self):
        with self.assertRaisesRegex(ContractError, "DUPLICATE_JSON_KEY"):
            parse_candidate('{"lead_in":"none","lead_in":"record"}')

    def test_nonfinite_json_and_markdown_wrappers_rejected(self):
        for value in ('{"variant":NaN}', '```json\n{}\n```'):
            with self.subTest(value=value), self.assertRaises(ContractError):
                parse_candidate(value)

    def test_internal_draft_and_source_ids_never_enter_model_payload(self):
        calls = []
        class Fake:
            def generate(self, payload, **kwargs):
                calls.append(payload)
                return {"contract_fingerprint": payload["contract_fingerprint"], "lead_in": "none", "groups": [
                    {"items": [{"claim_id": "owner", "variant": 1}], "joiner": "semicolon"}]}
        contract = ReplyContract("test", (Claim("owner", ("陈甲负责测试", "测试由陈甲负责"), ("private-source-object-id",)),),
                                 "secret-access-version", "scope-identity")
        request = RewriteRequest("event", "谁负责", "内部token与完整聊天private-draft", contract, 20)
        result = ReplyRewriter(Fake(), RewriteConfig(mode="enforce"), clock=lambda: 10).rewrite(request, guard=lambda: None)
        payload = json.dumps(calls, ensure_ascii=False)
        for secret in ("private-draft", "private-source-object-id", "secret-access-version", "scope-identity"):
            self.assertNotIn(secret, payload)
        self.assertEqual("测试由陈甲负责。", result.text)

    def test_raw_projection_is_not_counted_as_llm_success_even_with_coverage_variants(self):
        class NoCalls:
            def generate(self, *args, **kwargs):
                raise AssertionError("raw block cannot become a semantic summary")
        contract = ReplyContract("test", (
            Claim("raw", ("先完成A。仅A通过后才能开始B。",), ("source",)),
            Claim("coverage", ("还有资料待核对", "部分信息仍待核对"), ("coverage",)),
        ), "v1", "scope", origin="ledger_source_block")
        result = ReplyRewriter(NoCalls(), RewriteConfig(mode="enforce"), clock=lambda: 10).rewrite(
            RewriteRequest("e", "项目进展", "原文", contract, 20), guard=lambda: None)
        self.assertFalse(result.attempted)
        self.assertEqual("source_projection", result.disposition)
        self.assertIn("仅A通过后才能开始B", result.text)


if __name__ == "__main__":
    unittest.main()
