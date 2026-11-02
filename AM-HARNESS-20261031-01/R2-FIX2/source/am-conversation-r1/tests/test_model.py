"""Protocol and boundary tests; no live Qwen quality/latency claims."""
from __future__ import annotations

import json
from types import SimpleNamespace
import unittest

from am_conversation.model import CoordinatorModel, ScriptedModel, validate_arguments
from am_conversation.types import ConversationError, ModelTurn, ToolCall, canonical


MESSAGES = [{"role": "user", "content": "合成项目 Aurora 现在怎么样了？"}]
PARAMETERS = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "project_id": {"type": "string", "minLength": 1, "maxLength": 40},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "required": ["project_id"],
}
TOOLS = [{"type": "function", "function": {
    "name": "project_read", "description": "读取已授权项目的合成资料", "parameters": PARAMETERS,
}}]


class CoordinatorStub:
    def __init__(self, text=None, error=None):
        self.text = text if text is not None else '{"type":"answer","text":"资料还不齐，我先核对当前进展。"}'
        self.error, self.calls = error, []

    def complete(self, prompt, **options):
        self.calls.append((prompt, options))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.text, model="existing-qwen", elapsed=0.01)


def tool_output(arguments=None, **overrides):
    call = {"id": "call_1", "name": "project_read", "arguments": arguments or {"project_id": "synthetic-A"}}
    call.update(overrides)
    return json.dumps({"type": "tool_calls", "tool_calls": [call]}, ensure_ascii=False)


class CoordinatorModelTests(unittest.TestCase):
    def test_calls_existing_coordinator_with_unique_run_ids_and_native_schema(self):
        provider = CoordinatorStub()
        model = CoordinatorModel(provider)
        first = model.complete(MESSAGES, TOOLS, request_id="event-one")
        model.complete(MESSAGES, TOOLS, request_id="event-one")
        self.assertEqual(first.text, "资料还不齐，我先核对当前进展。")
        self.assertFalse(first.tool_calls)
        ids = [options["run_id"] for _, options in provider.calls]
        self.assertNotEqual(*ids)
        for ident in ids:
            self.assertRegex(ident, r"^[0-9a-f]{32}$")
        prompt, options = provider.calls[0]
        self.assertTrue(options["native_chat"])
        self.assertEqual(options["max_tokens"], 2048)
        self.assertIn("oneOf", options["json_schema"])
        self.assertIn("Aurora", prompt)

    def test_validated_tool_proposal_does_not_execute_a_tool(self):
        provider = CoordinatorStub(tool_output({"project_id": "synthetic-A", "limit": 2}))
        turn = CoordinatorModel(provider).complete(MESSAGES, TOOLS)
        self.assertEqual(turn.text, "")
        self.assertEqual(turn.tool_calls, (ToolCall("call_1", "project_read", {"project_id": "synthetic-A", "limit": 2}),))
        self.assertEqual(len(provider.calls), 1)

    def test_invalid_or_ambiguous_json_is_rejected_without_retry(self):
        bad = [
            '```json\n{"type":"answer","text":"已完成"}\n```',
            '{"type":"answer","text":"A"}{"type":"answer","text":"B"}',
            '{"type":"answer","text":"A","text":"B"}',
            '{"type":"answer","text":"A","tool_calls":[]}',
            '{"type":"answer","text":"  "}',
            '{"type":"tool_calls","tool_calls":[]}',
            '{"type":"answer","text":NaN}',
            '[{"type":"answer","text":"A"}]',
            '{"type":"unknown","text":"A"}',
            '{"type":"answer","text":"A","actor_id":"pretend-owner"}',
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                provider = CoordinatorStub(raw)
                with self.assertRaisesRegex(ConversationError, "^MODEL_OUTPUT_INVALID$"):
                    CoordinatorModel(provider).complete(MESSAGES, TOOLS)
                self.assertEqual(len(provider.calls), 1)

    def test_unknown_tool_and_injected_arguments_cannot_pass(self):
        for raw, code in [
            (tool_output(name="shell"), "MODEL_TOOL_NOT_ALLOWED"),
            (tool_output({"project_id": "synthetic-A", "actor_id": "owner"}), "TOOL_ARGUMENTS_INVALID"),
            (tool_output({"project_id": "synthetic-A", "limit": True}), "TOOL_ARGUMENTS_INVALID"),
            (tool_output({"project_id": "synthetic-A", "limit": 11}), "TOOL_ARGUMENTS_INVALID"),
            (tool_output({"limit": 2}), "TOOL_ARGUMENTS_INVALID"),
        ]:
            with self.subTest(code=code, raw=raw):
                with self.assertRaisesRegex(ConversationError, f"^{code}$"):
                    CoordinatorModel(CoordinatorStub(raw)).complete(MESSAGES, TOOLS)

    def test_duplicate_call_ids_and_excess_calls_rejected(self):
        call = {"id": "same", "name": "project_read", "arguments": {"project_id": "synthetic-A"}}
        raws = [json.dumps({"type": "tool_calls", "tool_calls": [call, call]}),
                json.dumps({"type": "tool_calls", "tool_calls": [dict(call, id=f"call_{i}") for i in range(9)]})]
        for raw in raws:
            with self.assertRaisesRegex(ConversationError, "^MODEL_OUTPUT_INVALID$"):
                CoordinatorModel(CoordinatorStub(raw)).complete(MESSAGES, TOOLS)

    def test_no_tools_means_no_tool_proposals(self):
        provider = CoordinatorStub()
        CoordinatorModel(provider).complete(MESSAGES, [])
        self.assertEqual(provider.calls[0][1]["json_schema"]["properties"]["type"]["const"], "answer")
        with self.assertRaisesRegex(ConversationError, "^MODEL_TOOL_NOT_ALLOWED$"):
            CoordinatorModel(CoordinatorStub(tool_output())).complete(MESSAGES, [])

    def test_busy_paused_and_unknown_errors_keep_original_identity_without_retry(self):
        for code in ("MODEL_BUSY", "MODEL_PAUSED", "STOP_UNKNOWN", "LOCAL_API_CONNECTION_LOST"):
            error = RuntimeError(code)
            provider = CoordinatorStub(error=error)
            with self.assertRaises(RuntimeError) as caught:
                CoordinatorModel(provider).complete(MESSAGES, TOOLS)
            self.assertIs(caught.exception, error)
            self.assertEqual(len(provider.calls), 1)

    def test_input_and_output_limits_are_checked(self):
        provider = CoordinatorStub()
        with self.assertRaisesRegex(ConversationError, "^MODEL_CONTEXT_LIMIT$"):
            CoordinatorModel(provider, max_input_chars=100).complete(MESSAGES, TOOLS)
        self.assertFalse(provider.calls)
        with self.assertRaisesRegex(ConversationError, "^MODEL_OUTPUT_INVALID$"):
            CoordinatorModel(provider, max_output_chars=10).complete(MESSAGES, TOOLS)
        for kwargs in ({"max_tokens": True}, {"max_tokens": 4097}, {"max_input_chars": 30001},
                       {"max_output_chars": 12001}, {"max_tokens": 0}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ConversationError, "^MODEL_LIMIT_INVALID$"):
                    CoordinatorModel(provider, **kwargs)

    def test_schema_limit_uses_transport_ascii_size(self):
        tool = {"type": "function", "function": {
            "name": "project_read", "parameters": {"type": "object", "properties": {
                "project_id": {"type": "string", "description": "合成" * 1800}}},
        }}
        provider = CoordinatorStub()
        with self.assertRaisesRegex(ConversationError, "^MODEL_SCHEMA_LIMIT$"):
            CoordinatorModel(provider).complete(MESSAGES, [tool])
        self.assertFalse(provider.calls)

    def test_unsupported_schema_rejected_before_model_call(self):
        provider = CoordinatorStub()
        tools = [{"type": "function", "function": {"name": "read", "parameters": {
            "type": "object", "$ref": "https://untrusted.example/schema"}}}]
        with self.assertRaisesRegex(ConversationError, "^TOOL_SCHEMA_INVALID$"):
            CoordinatorModel(provider).complete(MESSAGES, tools)
        self.assertFalse(provider.calls)

    def test_nested_duplicate_keys_and_nonfinite_numbers_rejected(self):
        raws = [
            '{"type":"tool_calls","tool_calls":[{"id":"a","name":"project_read","arguments":{"project_id":"a","project_id":"b"}}]}',
            '{"type":"tool_calls","tool_calls":[{"id":"a","name":"project_read","arguments":{"project_id":"a","limit":1e999}}]}',
        ]
        for raw in raws:
            with self.assertRaisesRegex(ConversationError, "^MODEL_OUTPUT_INVALID$"):
                CoordinatorModel(CoordinatorStub(raw)).complete(MESSAGES, TOOLS)

    def test_context_budget_matches_actual_prompt_including_json_escaping(self):
        messages = [{"role": "user", "content": '带引号"、反斜线\\与换行\n的合成资料。'}]
        initial = CoordinatorStub()
        CoordinatorModel(initial).complete(messages, TOOLS)
        exact = len(initial.calls[0][0])
        provider = CoordinatorStub()
        fitting = CoordinatorModel(provider, max_input_chars=exact)
        self.assertEqual(fitting.context_budget(TOOLS), len(canonical(messages)))
        fitting.complete(messages, TOOLS)
        too_small = CoordinatorModel(provider, max_input_chars=exact - 1)
        self.assertEqual(too_small.context_budget(TOOLS), len(canonical(messages)) - 1)
        with self.assertRaisesRegex(ConversationError, "^MODEL_CONTEXT_LIMIT$"):
            too_small.complete(messages, TOOLS)
        self.assertEqual(len(provider.calls), 1)


class ArgumentValidationTests(unittest.TestCase):
    def test_nested_optional_time_and_array_constraints(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {
            "due_at": {"anyOf": [{"type": "null"}, {"type": "string", "format": "date-time"}]},
            "items": {"type": "array", "minItems": 1, "maxItems": 2, "uniqueItems": True,
                      "items": {"type": "object", "additionalProperties": False,
                                "properties": {"id": {"type": "string", "pattern": "^task_[0-9]+$"}},
                                "required": ["id"]}},
        }, "required": ["due_at", "items"]}
        validate_arguments({"due_at": "2026-10-30T14:00:00+08:00", "items": [{"id": "task_1"}]}, schema)
        validate_arguments({"due_at": None, "items": [{"id": "task_1"}]}, schema)
        bad = [
            {"due_at": "tomorrow", "items": [{"id": "task_1"}]},
            {"due_at": "2026-10-30T14:00:00", "items": [{"id": "task_1"}]},
            {"due_at": "2026-02-30T14:00:00+08:00", "items": [{"id": "task_1"}]},
            {"due_at": None, "items": [{"id": "task_1"}, {"id": "task_1"}]},
            {"due_at": None, "items": [{"id": "task_1", "role": "owner"}]},
        ]
        for value in bad:
            with self.assertRaisesRegex(ConversationError, "^TOOL_ARGUMENTS_INVALID$"):
                validate_arguments(value, schema)

    def test_enums_distinguish_boolean_and_number(self):
        schema = {"type": "object", "properties": {"count": {"enum": [1]}}, "required": ["count"]}
        validate_arguments({"count": 1}, schema)
        with self.assertRaisesRegex(ConversationError, "^TOOL_ARGUMENTS_INVALID$"):
            validate_arguments({"count": True}, schema)

    def test_union_rejects_multiple_matching_oneof_branches(self):
        schema = {"type": "object", "properties": {"value": {"oneOf": [{"type": "number"}, {"type": "integer"}]}}}
        with self.assertRaisesRegex(ConversationError, "^TOOL_ARGUMENTS_INVALID$"):
            validate_arguments({"value": 1}, schema)
        validate_arguments({"value": 1.5}, schema)


class ScriptedModelTests(unittest.TestCase):
    def test_script_records_inputs_and_exhaustion_is_explicit(self):
        turn = ModelTurn(text="仅供协议测试的合成回复")
        model = ScriptedModel([turn])
        self.assertIs(model.complete(MESSAGES, TOOLS, request_id="test-event"), turn)
        self.assertEqual(model.calls[0]["request_id"], "test-event")
        with self.assertRaisesRegex(ConversationError, "^SCRIPT_EXHAUSTED$"):
            model.complete(MESSAGES, TOOLS)


if __name__ == "__main__":
    unittest.main()
