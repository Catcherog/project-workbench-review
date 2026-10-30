from __future__ import annotations

import dataclasses
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from am_doc_engine.adapters import EvidenceBoundModelComposer, ExtractiveComposer, ProviderSession, extractive_text
from am_doc_engine.models import (
    ContractError, DraftDocument, DraftField, DraftRequest, Evidence, FieldResolution,
    FieldRule, SectionSpec, SourceAsset, TemplateProfile, RevisionConflict, fingerprint,
)
from am_doc_engine.rendering import (
    FieldSlot, build_feishu_write_plan, build_report, render_html, render_markdown,
)
from am_doc_engine.sources import candidate_outline, parse_feishu_blocks, read_source


def fixture(mode="extractive", value="已完成样机装配"):
    asset = SourceAsset("template-source", "template", "fixture://template", "1", "# 项目目标\n{{goal}}")
    section = SectionSpec("summary", "目标情况")
    rule = FieldRule("goal", "summary", "项目目标", ("goal",), "据项目记录填写", ("template-source",), mode=mode)
    profile = TemplateProfile("tenant", "template", "1", "rules-1", "charter", "项目章程",
                              ("light",), ("start",), (section,), (rule,), (asset,),
                              "effective", "2026-10-01T00:00:00Z", "fixture://ledger/effective")
    request = DraftRequest("request", "tenant", "project", "charter", "light", "start")
    evidence = Evidence("e1", "tenant", "project", "goal", value, "actual", "confirmed",
                        "fact-source", "fixture://record", "1", "line:1", "2026-10-30T00:00:00Z")
    resolution = FieldResolution("goal", (evidence,))
    result = ExtractiveComposer().compose(rule, resolution, request, profile)
    document = DraftDocument("doc", "tenant", "project", "charter", "项目章程", "template", "1",
                             profile.content_hash, "rules-1", "snapshot", "snapshot-hash",
                             "2026-10-30T00:00:00Z", 1, (section,), (result,), (), (),
                             "draft_complete", "2026-10-30T00:00:00Z")
    return profile, request, rule, evidence, resolution, document


class Provider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return SimpleNamespace(text=self.response, model="fixture", elapsed=0)


def response(text="已完成样机装配", **changes):
    body = {"field_id": "goal", "text": text, "evidence_ids": ["e1"]}
    body.update(changes)
    return json.dumps({"fields": [body]}, ensure_ascii=False)


class AdapterTests(unittest.TestCase):
    def test_extract_preserves_confirmed_and_reported_semantics(self):
        *_, evidence, resolution, document = fixture()
        reported = dataclasses.replace(evidence, evidence_id="e2", semantic="decision", state="reported")
        text = extractive_text([evidence, evidence, reported])
        self.assertEqual(text.count("实际结果："), 1)
        self.assertIn("待核实反馈（决定信息）", text)

    def test_missing_field_does_not_call_model(self):
        profile, request, rule, _, _, _ = fixture("narrative")
        provider = Provider(response())
        result = EvidenceBoundModelComposer(provider).compose(rule, FieldResolution("goal", ()), request, profile)
        self.assertEqual(result.status, "missing")
        self.assertEqual(provider.calls, [])

    def test_missing_subset_preserves_known_content(self):
        profile, request, rule, evidence, _, _ = fixture()
        result = ExtractiveComposer().compose(rule, FieldResolution("goal", (evidence,), missing_keys=("other",)), request, profile)
        self.assertEqual(result.status, "missing")
        self.assertIn(evidence.value, result.text)

    def test_extractive_rejects_wrong_fact_semantics(self):
        profile, request, rule, evidence, _, _ = fixture()
        for invalid in [dataclasses.replace(evidence, semantic="forecast"), dataclasses.replace(evidence, state="reported")]:
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                ExtractiveComposer().compose(rule, FieldResolution("goal", (invalid,)), request, profile)

    def test_model_uses_existing_provider_and_validates_result(self):
        profile, request, rule, _, resolution, _ = fixture("narrative")
        provider = Provider(response())
        result = EvidenceBoundModelComposer(provider, run_id="a" * 32).compose(rule, resolution, request, profile)
        self.assertEqual(result.origin, "model")
        self.assertEqual(result.evidence_ids, ("e1",))
        self.assertEqual(provider.calls[0][1]["run_id"], "a" * 32)
        self.assertLessEqual(provider.calls[0][1]["timeout"], 60)
        self.assertIn("json_schema", provider.calls[0][1])

    def test_duplicate_and_extra_model_keys_rejected(self):
        profile, request, rule, _, resolution, _ = fixture("narrative")
        for raw in ['{"fields":[],"fields":[]}', '{"fields":[],"approved":true}', '{"fields":[]}']:
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                EvidenceBoundModelComposer(Provider(raw)).compose(rule, resolution, request, profile)

    def test_model_wrong_field_or_foreign_evidence_rejected(self):
        profile, request, rule, _, resolution, _ = fixture("narrative")
        for raw in [response(field_id="foreign"), response(evidence_ids=["foreign"]), response(evidence_ids=[]), response(evidence_ids=["e1", "e1"])]:
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                EvidenceBoundModelComposer(Provider(raw)).compose(rule, resolution, request, profile)

    def test_model_novel_number_or_approval_claim_rejected(self):
        profile, request, rule, _, resolution, _ = fixture("narrative")
        for raw in [response("已完成 8 台样机装配"), response("已批准，验收通过")]:
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                EvidenceBoundModelComposer(Provider(raw)).compose(rule, resolution, request, profile)

    def test_model_input_excludes_foreign_projects_and_examples(self):
        profile, request, rule, evidence, _, _ = fixture("narrative")
        for modified in [dataclasses.replace(evidence, project_id="other"), dataclasses.replace(evidence, role="example")]:
            provider = Provider(response())
            with self.subTest(evidence=modified), self.assertRaises(ContractError):
                EvidenceBoundModelComposer(provider).compose(rule, FieldResolution("goal", (modified,)), request, profile)
            self.assertEqual(provider.calls, [])

    def test_total_budget_shared_by_composer_and_reviewer(self):
        profile, request, rule, _, resolution, _ = fixture("narrative")
        provider = Provider(response())
        session = ProviderSession(provider, run_id="b" * 32, timeout=10)
        EvidenceBoundModelComposer(session=session).compose(rule, resolution, request, profile)
        provider.response = '{"ok":true}'
        self.assertEqual(session.complete_json("review", {"type": "object"}), {"ok": True})
        self.assertLessEqual(provider.calls[1][1]["timeout"], provider.calls[0][1]["timeout"])
        self.assertEqual(provider.calls[1][1]["run_id"], provider.calls[0][1]["run_id"])

    def test_expired_deadline_stops_before_call(self):
        provider = Provider('{}')
        session = ProviderSession(provider, run_id="b" * 32, deadline_monotonic=time.monotonic() - 1)
        with self.assertRaises(TimeoutError):
            session.complete_json("p", {})
        self.assertEqual(provider.calls, [])

    def test_guard_rechecked_after_model_response(self):
        count = [0]
        def guard():
            count[0] += 1
            return count[0] == 1
        provider = Provider('{}')
        session = ProviderSession(provider, run_id="b" * 32, ensure_current=guard)
        with self.assertRaises(RevisionConflict):
            session.complete_json("p", {})
        self.assertEqual(len(provider.calls), 1)

    def test_false_guard_before_call_is_revision_conflict(self):
        provider = Provider('{}')
        session = ProviderSession(provider, run_id="c" * 32, ensure_current=lambda: False)
        with self.assertRaises(RevisionConflict):
            session.complete_json("p", {})
        self.assertEqual(provider.calls, [])


class RendererTests(unittest.TestCase):
    def test_html_and_markdown_escape_untrusted_content(self):
        profile, _, _, _, _, document = fixture(value='<script>alert("x")</script> [go](javascript:alert(1))')
        html = render_html(document, profile)
        markdown = render_markdown(document, profile)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("href=", html)
        self.assertNotIn("[go]", markdown)

    def test_profile_revision_mismatch_rejected(self):
        profile, _, _, _, _, document = fixture()
        with self.assertRaises(ContractError):
            render_html(dataclasses.replace(document, template_hash="other"), profile)

    def test_binding_rejects_changed_type_rules_or_sections(self):
        profile, _, _, _, _, document = fixture()
        variants = [
            dataclasses.replace(document, doc_type="closeout"),
            dataclasses.replace(document, rule_version="wrong-rules"),
            dataclasses.replace(document, sections=(SectionSpec("summary", "被替换的章节"),)),
            dataclasses.replace(document, sections=()),
        ]
        for modified in variants:
            for render in [render_markdown, render_html, build_report]:
                with self.subTest(document=modified, render=render.__name__), self.assertRaises(ContractError):
                    render(modified, profile)
            with self.subTest(document=modified, render="write_plan"), self.assertRaises(ContractError):
                build_feishu_write_plan(modified, profile, document_token="target", expected_revision="42",
                                         slots={}, current_blocks={})

    def test_binding_rejects_missing_duplicate_or_extra_fields(self):
        profile, _, _, _, _, document = fixture()
        variants = [
            dataclasses.replace(document, fields=()),
            dataclasses.replace(document, fields=(document.fields[0], document.fields[0])),
            dataclasses.replace(document, fields=(document.fields[0], DraftField("extra", "外来文字", ()))),
        ]
        for modified in variants:
            for render in [render_markdown, render_html, build_report]:
                with self.subTest(document=modified, render=render.__name__), self.assertRaises(ContractError):
                    render(modified, profile)
            with self.subTest(document=modified, render="write_plan"), self.assertRaises(ContractError):
                build_feishu_write_plan(modified, profile, document_token="target", expected_revision="42",
                                         slots={}, current_blocks={})

    def test_approval_state_not_rendered(self):
        profile, _, _, _, _, document = fixture()
        with self.assertRaises(ContractError):
            render_markdown(dataclasses.replace(document, state="approved"), profile)

    def test_report_carries_provenance_separately(self):
        profile, _, _, _, _, document = fixture()
        report = build_report(document, profile)
        self.assertEqual(report["field_evidence"]["goal"], ["e1"])
        self.assertEqual(report["business_approval"], "not_performed")
        self.assertNotIn("snapshot-hash", render_markdown(document, profile))

    def plan(self, *, human=(), current="占位", expected=None, revision="42", include_slot=True):
        profile, _, _, _, _, document = fixture()
        slots = {"goal": FieldSlot("b1", expected or fingerprint("占位"), profile.content_hash)} if include_slot else {}
        return build_feishu_write_plan(document, profile, document_token="docx-token", expected_revision=revision,
                                       slots=slots, current_blocks={"b1": current, "human": "人工段落"}, human_block_ids=human)

    def test_plan_preserves_unmapped_blocks(self):
        plan = self.plan()
        self.assertTrue(plan["ready_for_execution"])
        self.assertEqual(plan["preserved_block_ids"], ["human"])
        self.assertFalse(plan["executes_external_action"])

    def test_plan_rejects_missing_mapping_or_latest_revision(self):
        for plan in [self.plan(include_slot=False), self.plan(revision=-1), self.plan(revision="latest")]:
            self.assertFalse(plan["ready_for_execution"])
            self.assertEqual(plan["operations"], [])

    def test_plan_preserves_changed_or_human_block(self):
        for plan in [self.plan(current="人工修改"), self.plan(human=("b1",))]:
            self.assertFalse(plan["ready_for_execution"])
            self.assertEqual(plan["operations"], [])
            self.assertEqual(plan["preserved_block_ids"], ["b1", "human"])


class SourceTests(unittest.TestCase):
    def test_markdown_outline_candidate_with_image_limitation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "template.md"
            path.write_text("# 目标\n{{goal}}\n![图](image.png)\n```\n# 非标题\n```\n", encoding="utf-8")
            parsed = read_source(path, source_id="t1")
            outline = candidate_outline(parsed)
            self.assertEqual(parsed.read_state, "partial")
            self.assertEqual(outline["status"], "candidate")
            self.assertEqual(len(outline["sections"]), 1)
            self.assertEqual(outline["unmapped_fields"][0]["field_id"], "goal")
            self.assertFalse(outline["activation_allowed"])

    def test_json_duplicate_key_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.json"
            path.write_text('{"field":1,"field":2}', encoding="utf-8")
            with self.assertRaises(ContractError):
                read_source(path, source_id="t1")

    def test_docx_text_and_image_completeness(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.docx"
            body = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Test</w:t></w:r></w:p></w:body></w:document>'
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", body)
                archive.writestr("word/media/image.png", b"not-read")
            parsed = read_source(path, source_id="t1")
            self.assertEqual(parsed.content, "Test")
            self.assertEqual(parsed.read_state, "partial")
            self.assertIn("embedded_media_not_read", parsed.unsupported)

    def test_feishu_pagination_not_claimed_complete(self):
        blocks = [{"block_id": "b1", "kind": "heading", "level": 1, "text": "目标"}]
        parsed = parse_feishu_blocks(blocks, source_id="t1", title="T", revision="12")
        self.assertEqual(parsed.read_state, "partial")
        complete = parse_feishu_blocks(blocks, source_id="t1", title="T", revision="12", complete=True)
        self.assertEqual(complete.read_state, "complete")

    def test_feishu_unknown_and_missing_child_mark_partial(self):
        blocks = [{"block_id": "b1", "kind": "container", "children": ["missing"]}, {"block_id": "b2", "kind": "image"}]
        parsed = parse_feishu_blocks(blocks, source_id="t1", title="T", revision="1", complete=True)
        self.assertEqual(parsed.read_state, "partial")
        self.assertIn("missing_child:missing", parsed.unsupported)

    def test_feishu_cycles_and_duplicate_content_rejected(self):
        cases = [
            [{"block_id": "a", "kind": "container", "children": ["b"]}, {"block_id": "b", "kind": "container", "children": ["a"]}],
            [{"block_id": "a", "kind": "text", "text": "one"}, {"block_id": "a", "kind": "text", "text": "two"}],
        ]
        for blocks in cases:
            with self.subTest(blocks=blocks), self.assertRaises(ContractError):
                parse_feishu_blocks(blocks, source_id="t1", title="T", revision="1", complete=True)


if __name__ == "__main__":
    unittest.main()
