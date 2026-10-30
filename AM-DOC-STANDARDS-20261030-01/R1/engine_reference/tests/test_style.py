import json
import unittest
from dataclasses import asdict, replace

from am_doc_engine.adapters import EvidenceBoundModelComposer
from am_doc_engine.models import (
    AccessContext, AccessDenied, ContractError, DraftRequest, Evidence,
    FieldResolution, FieldRule, SectionSpec, SourceAsset, TemplateProfile,
    canonical, to_dict,
)
from am_doc_engine.style import (
    activate_style_guide, apply_style_guide, derive_style_guide,
    style_guide_from_dict,
)


class FakeJSONSession:
    def __init__(self, output=None):
        self.output = output or {
            "tone": "concise", "paragraph_sentences": 3,
            "prefer_bullets": True, "lead_with_summary": True,
            "avoid_vague_claims": True,
        }
        self.calls = []

    def complete_json(self, prompt, schema):
        self.calls.append((prompt, schema))
        return json.loads(json.dumps(self.output))


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.example_text = "李范例负责紫色样例项目，2038-07-09验收通过。先简短说明结论，再列出依据。"
        self.profile = TemplateProfile(
            tenant_id="tenant-demo", template_id="charter-demo", revision="native-v1",
            rule_version="rules-v1", doc_type="charter", title="项目章程",
            project_types=("generic",), stages=("planning",),
            sections=(SectionSpec("summary-section", "项目说明"),),
            fields=(
                FieldRule("summary", "summary-section", "项目背景", ("background",),
                          "说明背景及目标", ("template-source",), mode="narrative"),
                FieldRule("finish", "summary-section", "计划结束日期", ("finish_date",),
                          "填写有效计划中的日期", ("template-source",), semantics=("baseline",), value_type="date"),
            ),
            assets=(
                SourceAsset("template-source", "template", "synthetic://template", "v1", "项目背景；计划结束日期"),
                SourceAsset("example-source", "example", "synthetic://example", "example-v1", self.example_text, title="合格范例"),
            ),
            status="effective", effective_at="2026-10-01T00:00:00Z",
            activation_ref="synthetic://ledger/effective", allowed_actor_ids=("writer-demo",),
        )
        self.access = AccessContext("tenant-demo", "writer-demo", ("project-demo",))
        self.manager = replace(self.access, scopes=("document:draft", "template:manage"))

    def candidate(self, session=None):
        return derive_style_guide(self.profile, self.access, session or FakeJSONSession())

    def effective(self):
        return activate_style_guide(self.candidate(), self.profile, self.manager,
                                    activation_ref="synthetic://decision/style-adoption")

    def test_full_body_only_enters_extraction_and_candidate_preserves_provenance(self):
        session = FakeJSONSession()
        guide = self.candidate(session)
        self.assertEqual(guide.status, "candidate")
        self.assertIn(self.example_text, session.calls[0][0])
        self.assertFalse(session.calls[0][1]["additionalProperties"])
        self.assertNotIn("李范例", canonical(guide))
        self.assertNotIn("紫色样例项目", canonical(guide))
        self.assertNotIn("2038-07-09", canonical(guide))
        self.assertEqual(guide.sources[0].source_id, "example-source")
        self.assertEqual(guide.sources[0].revision, "example-v1")
        self.assertEqual(guide.sources[0].content_hash, self.profile.assets[1].content_hash)

    def test_free_text_and_unrequested_model_fields_are_rejected(self):
        for extra in ["explanation", "person_name", "project_id", "activation_ref", "status"]:
            with self.subTest(extra=extra):
                output = dict(FakeJSONSession().output, **{extra: "李范例"})
                with self.assertRaises(ContractError):
                    self.candidate(FakeJSONSession(output))

    def test_enum_integer_and_boolean_values_are_strict(self):
        cases = [("tone", "李范例"), ("tone", 1), ("paragraph_sentences", 0),
                 ("paragraph_sentences", 9), ("paragraph_sentences", True),
                 ("paragraph_sentences", 2.0), ("prefer_bullets", "true"),
                 ("lead_with_summary", 1), ("avoid_vague_claims", None)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                output = dict(FakeJSONSession().output, **{key: value})
                with self.assertRaises(ContractError):
                    self.candidate(FakeJSONSession(output))

    def test_only_complete_nonempty_examples_can_be_read(self):
        for source in [replace(self.profile.assets[1], read_state="partial"),
                       replace(self.profile.assets[1], read_state="unavailable"),
                       replace(self.profile.assets[1], content=" ")]:
            with self.subTest(state=source.read_state, content=source.content):
                session = FakeJSONSession()
                profile = replace(self.profile, assets=(self.profile.assets[0], source))
                with self.assertRaises(ContractError):
                    derive_style_guide(profile, self.access, session)
                self.assertEqual(session.calls, [])
        with self.assertRaises(ContractError):
            derive_style_guide(self.profile, self.access, FakeJSONSession(), source_ids=("template-source",))
        with self.assertRaises(ContractError):
            derive_style_guide(self.profile, self.access, FakeJSONSession(), source_ids=("missing",))

    def test_scope_is_checked_before_the_model_receives_examples(self):
        for access in [replace(self.access, tenant_id="other-tenant"),
                       replace(self.access, actor_id="other-actor"),
                       replace(self.access, scopes=())]:
            with self.subTest(access=access):
                session = FakeJSONSession()
                with self.assertRaises(AccessDenied):
                    derive_style_guide(self.profile, access, session)
                self.assertEqual(session.calls, [])

    def test_activation_requires_management_scope_and_explicit_reference(self):
        guide = self.candidate()
        with self.assertRaises(AccessDenied):
            activate_style_guide(guide, self.profile, self.access, activation_ref="synthetic://decision")
        with self.assertRaises(ContractError):
            activate_style_guide(guide, self.profile, self.manager, activation_ref=" ")
        active = activate_style_guide(guide, self.profile, self.manager, activation_ref="synthetic://decision")
        self.assertEqual(active.status, "effective")
        self.assertEqual(active.activated_by, self.manager.actor_id)
        self.assertEqual(guide.status, "candidate")
        self.assertIs(activate_style_guide(active, self.profile, self.manager, activation_ref="synthetic://decision"), active)
        with self.assertRaises(ContractError):
            activate_style_guide(active, self.profile, self.manager, activation_ref="synthetic://other-decision")

    def test_candidate_cannot_affect_runtime_and_effective_application_is_idempotent(self):
        with self.assertRaises(ContractError):
            apply_style_guide(self.profile, self.candidate())
        guide = self.effective()
        derived = apply_style_guide(self.profile, guide)
        self.assertIs(apply_style_guide(derived, guide), derived)

    def test_application_preserves_structure_fact_rules_and_fixed_fields(self):
        guide = self.effective()
        derived = apply_style_guide(self.profile, guide)
        self.assertEqual(derived.sections, self.profile.sections)
        self.assertEqual(derived.revision, self.profile.revision)
        self.assertEqual(derived.status, self.profile.status)
        self.assertEqual(derived.allowed_actor_ids, self.profile.allowed_actor_ids)
        self.assertEqual(derived.fields[1], self.profile.fields[1])
        old, new = asdict(self.profile.fields[0]), asdict(derived.fields[0])
        for item in [old, new]:
            item.pop("instruction")
            item.pop("requirement_source_ids")
        self.assertEqual(old, new)
        self.assertTrue(derived.fields[0].instruction.startswith(self.profile.fields[0].instruction))
        self.assertIn("不超过 3 句", derived.fields[0].instruction)
        self.assertNotEqual(derived.rule_version, self.profile.rule_version)
        self.assertNotEqual(derived.content_hash, self.profile.content_hash)
        self.assertEqual(derived.assets[-1].role, "instruction")
        self.assertIn(guide.guide_id, derived.assets[-1].uri)
        self.assertNotIn("李范例", derived.assets[-1].content)
        self.assertNotIn("2038-07-09", derived.assets[-1].content)

    def test_changed_source_version_content_and_scope_invalidate_guide(self):
        guide = self.effective()
        profiles = [replace(self.profile, tenant_id="other-tenant"),
                    replace(self.profile, doc_type="closeout")]
        for source in [replace(self.profile.assets[1], revision="example-v2"),
                       replace(self.profile.assets[1], content=self.example_text + "追加内容"),
                       replace(self.profile.assets[1], read_state="partial")]:
            profiles.append(replace(self.profile, assets=(self.profile.assets[0], source)))
        profiles.append(replace(self.profile, assets=(self.profile.assets[0],)))
        for profile in profiles:
            with self.subTest(tenant=profile.tenant_id, doc_type=profile.doc_type, assets=profile.assets):
                with self.assertRaises(ContractError):
                    apply_style_guide(profile, guide)

    def test_runtime_composition_receives_generic_rules_not_example_facts(self):
        derived = apply_style_guide(self.profile, self.effective())
        request = DraftRequest("req-demo", "tenant-demo", "project-demo", "charter", "generic", "planning")
        evidence = Evidence("ev-demo", "tenant-demo", "project-demo", "background", "本项目形成初步方案",
                            "actual", "confirmed", "project-source", "synthetic://project", "r1", "line:1",
                            "2026-10-29T00:00:00Z")
        payload = EvidenceBoundModelComposer._payload(
            [(derived.fields[0], FieldResolution("summary", (evidence,)))], request, derived)
        text = canonical(payload)
        self.assertIn("不超过 3 句", text)
        self.assertIn("本项目形成初步方案", text)
        self.assertNotIn("李范例", text)
        self.assertNotIn("紫色样例项目", text)
        self.assertNotIn("2038-07-09", text)

    def test_different_style_cannot_accumulate_on_derived_profile(self):
        derived = apply_style_guide(self.profile, self.effective())
        output = dict(FakeJSONSession().output, tone="technical")
        other = self.candidate(FakeJSONSession(output))
        other = activate_style_guide(other, self.profile, self.manager, activation_ref="synthetic://new-style")
        with self.assertRaises(ContractError):
            apply_style_guide(derived, other)
        changed = apply_style_guide(self.profile, other)
        self.assertNotEqual(changed.rule_version, derived.rule_version)

    def test_host_storage_roundtrip_and_context_budget(self):
        guide = self.effective()
        self.assertEqual(style_guide_from_dict(to_dict(guide)), guide)
        bad = to_dict(guide)
        bad["rules"]["explanation"] = "自由文本"
        with self.assertRaises(ContractError):
            style_guide_from_dict(bad)
        huge = replace(self.profile.assets[1], content="范例正文" * 1000)
        profile = replace(self.profile, assets=(self.profile.assets[0], huge))
        session = FakeJSONSession()
        with self.assertRaises(ContractError):
            derive_style_guide(profile, self.access, session, max_prompt_chars=1000)
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
