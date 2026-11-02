"""Audit the real overlay projector without importing an unavailable host service.

Only the project_outcome function is compiled from the delivered overlay. Its
SpeechFrame/render/verifier dependencies are the real package modules. This
isolated contract test is not a claim of original-host or platform acceptance;
the separate host reconstruction probe exercises TerminalExpression.finish.
AM_TERMINAL_PROJECTION_SOURCE can select the fixed R3 file for a red regression.
"""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

from am_style.contracts import ContractError, SpeechFrame, StylePolicy, digest
from am_style.integration import prepare_terminal_reply
from am_style.render import make_frame, render_canonical
from am_style.runtime import TerminalPresenter
from am_style.verify import BoundedVerifier


DEFAULT_SOURCE = (Path(__file__).resolve().parents[1] / "overlay" /
                  "am-conversation-r1/src/am_conversation/terminal.py")
SOURCE = Path(os.environ.get("AM_TERMINAL_PROJECTION_SOURCE", DEFAULT_SOURCE))
tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in ("closed_query_support", "project_outcome")]
namespace = {"ContractError": ContractError, "SpeechFrame": SpeechFrame,
             "digest": digest, "make_frame": make_frame}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), namespace)
project_outcome = namespace["project_outcome"]


def envelope(value="林工", predicate="负责人", source=None, **qualifiers):
    claim = {"id": "fact", "subject": "p", "subject_label": "演示项目",
             "predicate": predicate, "value": value, "modality": "recorded",
             "source": source, **qualifiers}
    data = {"binding": {"kind": "event", "scope": ["t", "a", "u", "c", ""],
                         "origin_event_id": "event", "engine_event_id": "event",
                         "source_access_version": "v1"},
            "claims": [claim], "required_claim_ids": ["fact"], "allowed_omission_ids": [],
            "protected_blocks": [], "work_units": [{"id":"read","effect":"read",
                "coverage":{"complete":True},"target":{"project_id":"p"},
                "result":{"id":"p","evidence_bundle":{"claims":[claim]}}}], "expires_at": 4102444800,
            "intent": {"user_request": "演示项目进展如何？" if predicate == "progress" else "演示项目谁负责？"}, "families": ["query"],
            "completion": "fulfilled"}
    return SimpleNamespace(data=data, digest=digest(data))


class TerminalProjectionTests(unittest.TestCase):
    def test_quote_constraints_and_conflicting_entities_are_refused(self):
        cases = (("完成", "未完成", "progress"),
                 ("明天完成", "预计明天完成", "progress"),
                 ("林工", "仅试制阶段由林工负责", "负责人"),
                 ("林工", "王工", "负责人"),
                 ("完成", "材料到齐后才能完成", "progress"),
                 ("林工", "林工已离岗，改由王工负责", "负责人"))
        for value, quote, predicate in cases:
            with self.subTest(value=value, quote=quote):
                with self.assertRaisesRegex(ContractError, "unsupported_source_quote"):
                    project_outcome(envelope(value, predicate, {"quote": quote}))

    def test_matching_negative_or_forecast_quote_retains_the_whole_value(self):
        for value in ("未完成", "预计明天完成", "仅试制阶段完成"):
            with self.subTest(value=value):
                original = envelope(value, "progress", {"quote": "  " + value + "\n"})
                frame = project_outcome(original)
                rendered = render_canonical(frame)
                self.assertIn(value, rendered)
                self.assertEqual(frame.data["provenance"]["original_claims"], original.data["claims"])
                self.assertEqual(BoundedVerifier().verify(frame, rendered, StylePolicy()).decision, "pass")

    def test_similarity_is_not_treated_as_semantic_identity(self):
        # Even harmless punctuation/paraphrases remain unsupported without a
        # separately validated equivalence rule; no bag-of-keywords approval.
        for quote in ("林工。", "负责人为林工", "未 完成"):
            with self.subTest(quote=quote):
                value = "未完成" if quote == "未 完成" else "林工"
                with self.assertRaisesRegex(ContractError, "unsupported_source_quote"):
                    project_outcome(envelope(value=value, source={"quote": quote}))

    def test_nontext_quote_and_nonobject_source_are_not_discarded(self):
        for quote in (False, 0, [], {"text": "未完成"}):
            with self.subTest(quote=quote):
                with self.assertRaisesRegex(ContractError, "unsupported_source_quote"):
                    project_outcome(envelope(source={"quote": quote}))
        for source in ("引用材料", [], False):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ContractError, "unsupported_claim_source"):
                    project_outcome(envelope(source=source))

    def test_source_metadata_without_a_quote_preserves_supported_owner_case(self):
        for source in (None, {}, {"version": "r1"}, {"quote": None}, {"quote": "   "},
                       {"quote": "林工", "url": "https://example.test/source"}):
            with self.subTest(source=source):
                frame = project_outcome(envelope(source=source))
                self.assertEqual(render_canonical(frame), "演示项目由林工负责。")

    def test_unsupported_quote_stops_before_any_presenter_call(self):
        calls = []
        class Provider:
            def generate(self, request):
                calls.append(request)
                raise AssertionError("unsupported source must not reach the model")
        original = envelope("完成", "progress", {"quote": "未完成"})
        with self.assertRaisesRegex(ContractError, "unsupported_source_quote"):
            prepare_terminal_reply(
                presenter=TerminalPresenter(Provider(), mode="enforce"),
                agent=SimpleNamespace(_guard=lambda *a: None, _checkpoint=lambda *a: None),
                ctx=SimpleNamespace(is_owner=True), reply=SimpleNamespace(text="旧回复"),
                envelope=original, frame_projector=project_outcome,
                task_deadline_monotonic=30, outcome_getter=lambda: original,
                require_current=lambda: None)
        self.assertEqual(calls, [])

    def test_existing_typed_scope_and_modality_constraints_still_fail_closed(self):
        for changes in ({"scope": "仅样机"}, {"time_scope": "截至昨天"},
                        {"polarity": "negative"}, {"business_state": "accepted"}):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                project_outcome(envelope(source={"quote": "林工"}, **changes))
        original = envelope(source={"quote": "林工"})
        original.data["claims"][0]["modality"] = "unknown"
        with self.assertRaisesRegex(ContractError, "unsupported_claim_modality"):
            project_outcome(original)

    def test_missing_requested_field_and_other_project_owner_do_not_answer_owner(self):
        missing = envelope("测试未完成", "progress", {"quote":"测试未完成"})
        missing.data['intent']['user_request'] = "演示项目谁负责？"
        with self.assertRaisesRegex(ContractError, "closed_query_required_field_missing"):
            project_outcome(missing)
        other = {"id":"other-owner","subject":"q","subject_label":"另一项目",
                 "predicate":"负责人","value":"王工","modality":"recorded"}
        missing.data['claims'].append(other)
        missing.data['required_claim_ids'].append(other['id'])
        missing.data['work_units'].append({"id":"other-read","effect":"read","coverage":{"complete":True},
            "target":{"project_id":"q"},"result":{"id":"q","evidence_bundle":{"claims":[other]}}})
        with self.assertRaisesRegex(ContractError, "closed_query_required_field_missing"):
            project_outcome(missing)

    def test_same_label_different_projects_or_wrong_read_binding_are_refused(self):
        ambiguous = envelope()
        other = dict(ambiguous.data['claims'][0], id='other', subject='q')
        ambiguous.data['claims'].append(other)
        ambiguous.data['required_claim_ids'].append('other')
        with self.assertRaisesRegex(ContractError, "closed_query_target_ambiguous"):
            project_outcome(ambiguous)
        wrong_read = envelope()
        wrong_read.data['work_units'][0]['target']['project_id'] = 'q'
        with self.assertRaisesRegex(ContractError, "closed_query_field_source_unbound"):
            project_outcome(wrong_read)

    def test_complete_same_project_field_supports_only_the_closed_question(self):
        original = envelope()
        support = namespace['closed_query_support'](original.data)
        self.assertTrue(support['supported'])
        self.assertEqual((support['project_id'], support['field']), ('p', 'owner'))
        self.assertEqual(render_canonical(project_outcome(original)), '演示项目由林工负责。')
        original.data['intent']['user_request'] = '演示项目和另一项目谁负责？'
        with self.assertRaisesRegex(ContractError, 'closed_query_target_unresolved'):
            project_outcome(original)
        original.data['intent']['user_request'] = '分析这些资料'
        self.assertIsNone(namespace['closed_query_support'](original.data))

    def test_read_without_explicit_project_identity_cannot_borrow_claim_binding(self):
        for has_bundle in (False, True):
            with self.subTest(has_bundle=has_bundle):
                original = envelope()
                read = original.data['work_units'][0]
                read['target'] = {}
                read['result'].pop('id')
                if not has_bundle:
                    # A valid adapter-style prefix still cannot prove which
                    # project the actual read was bound to.
                    read['result'].pop('evidence_bundle')
                    read['result']['fields'] = {'负责人':'林工'}
                    original.data['claims'][0]['id'] = 'read:负责人'
                    original.data['required_claim_ids'] = ['read:负责人']
                support = namespace['closed_query_support'](original.data)
                self.assertFalse(support['supported'])
                with self.assertRaisesRegex(ContractError, 'closed_query_field_source_unbound'):
                    project_outcome(original)


if __name__ == "__main__":
    unittest.main()
