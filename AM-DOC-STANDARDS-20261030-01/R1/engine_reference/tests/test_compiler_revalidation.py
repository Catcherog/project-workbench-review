from dataclasses import replace
import json
import unittest

from am_doc_engine.catalog import TemplateCatalog
from am_doc_engine.compiler import compile_candidate, activate_candidate
from am_doc_engine.engine import DocumentEngine
from am_doc_engine.evidence import resolve_fields
from am_doc_engine.models import (AccessContext, AccessDenied, ContractError, DraftField, FactSnapshot,
                                 Issue, RevisionConflict, SourceAsset, fingerprint, profile_from_dict, to_dict)
from am_doc_engine.rendering import FieldSlot, build_feishu_write_plan, build_report
from am_doc_engine.revalidation import revalidate_revision
from am_doc_engine.revision import plan_revision
from am_doc_engine.storage import SQLiteRunStore
from tests.helpers import demo


class FakeSession:
    def __init__(self, output):
        self.output = output
        self.calls = 0

    def complete_json(self, prompt, schema):
        self.calls += 1
        return self.output


class CompilerAndBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.profile, self.request, self.access, self.snapshot = demo()

    def compiler_args(self, session):
        p = self.profile
        return dict(assets=p.assets, tenant_id=p.tenant_id, template_id=p.template_id,
                    revision=p.revision, doc_type=p.doc_type, title=p.title,
                    project_types=p.project_types, stages=p.stages,
                    available_fact_keys=tuple(e.key for e in self.snapshot.evidence), session=session)

    def proposal(self):
        return {"sections": to_dict(self.profile.sections), "fields": to_dict(self.profile.fields)}

    def test_rule_compiler_returns_only_candidate(self):
        candidate = compile_candidate(**self.compiler_args(FakeSession(self.proposal())))
        self.assertEqual(candidate.status, "candidate")
        self.assertEqual(candidate.activation_ref, "")
        with self.assertRaises(AccessDenied):
            activate_candidate(candidate, self.access, activation_ref="demo://decision", effective_at=self.snapshot.as_of)
        admin = replace(self.access, scopes=(*self.access.scopes, "template:manage"))
        active = activate_candidate(candidate, admin, activation_ref="demo://decision", effective_at=self.snapshot.as_of)
        self.assertEqual(active.status, "effective")

    def test_model_cannot_activate_rules_or_invent_fact_keys(self):
        proposal = self.proposal()
        proposal["status"] = "effective"
        with self.assertRaises(ContractError):
            compile_candidate(**self.compiler_args(FakeSession(proposal)))
        proposal = self.proposal()
        proposal["fields"][0]["fact_keys"] = ["invented.approval"]
        with self.assertRaises(ContractError):
            compile_candidate(**self.compiler_args(FakeSession(proposal)))

    def test_partial_rule_sources_stop_before_model(self):
        session = FakeSession(self.proposal())
        args = self.compiler_args(session)
        args["assets"] = (replace(self.profile.assets[0], read_state="partial"), *self.profile.assets[1:])
        with self.assertRaises(ContractError):
            compile_candidate(**args)
        self.assertEqual(session.calls, 0)

    def test_examples_cannot_be_required_rule_authority(self):
        proposal = self.proposal()
        proposal["fields"][0]["requirement_source_ids"] = ["example"]
        with self.assertRaises(ContractError):
            compile_candidate(**self.compiler_args(FakeSession(proposal)))

    def test_permission_collections_reject_substring_coercion(self):
        for kwargs in [dict(project_ids="demo_project-secret"), dict(scopes="document:draft")]:
            params = dict(tenant_id="demo_th2", actor_id="demo_user", project_ids=("demo_project",))
            params.update(kwargs)
            with self.assertRaises(ContractError):
                AccessContext(**params)
        with self.assertRaises(ContractError):
            replace(self.profile, allowed_actor_ids="demo_user_other")
        with self.assertRaises(ContractError):
            replace(self.snapshot.evidence[0], allowed_actor_ids="demo_user_other")

    def test_json_catalog_rejects_string_for_scope(self):
        raw = to_dict(self.profile)
        raw["project_types"] = "lightweight"
        with self.assertRaises(ContractError):
            profile_from_dict(raw)


class RevisionClosureTests(unittest.TestCase):
    def setUp(self):
        self.profile, self.request, self.access, self.snapshot = demo()
        self.store = SQLiteRunStore()
        self.engine = DocumentEngine(TemplateCatalog([self.profile]), self.store)
        self.base = self.engine.generate(self.request, self.access, self.snapshot)

    def tearDown(self):
        self.store.close()

    def make_plan(self):
        old = next(e for e in self.snapshot.evidence if e.key == "project.planned_finish")
        new = replace(old, evidence_id="E_NEW", value="2026-11-28", supersedes=(old.evidence_id,))
        snap = replace(self.snapshot, snapshot_id="updated_snapshot", evidence=(*self.snapshot.evidence, new))
        generated = self.engine.generate(replace(self.request, request_id="updated_request"), self.access, snap)
        proposed = replace(generated, document_id=self.base.document_id, revision=2)
        plan = plan_revision(self.base, self.base, proposed, ["finish"], expected_current_revision=1)
        return plan, snap

    def plan_write(self, document):
        current = {f"block_{r.field_id}": "placeholder" for r in self.profile.fields}
        slots = {r.field_id: FieldSlot(f"block_{r.field_id}", fingerprint("placeholder"), self.profile.content_hash) for r in self.profile.fields}
        return build_feishu_write_plan(document, self.profile, document_token="synthetic-token",
                                       expected_revision=1, slots=slots, current_blocks=current)

    def test_unrevalidated_merge_cannot_escape_to_write_plan(self):
        plan, _ = self.make_plan()
        self.assertTrue(plan.requires_validation)
        output = self.plan_write(plan.merged)
        self.assertFalse(output["ready_for_execution"])
        self.assertEqual(output["operations"], [])

    def test_revalidation_binds_new_snapshot_before_plan(self):
        plan, snap = self.make_plan()
        checked = revalidate_revision(plan, self.profile, self.request, self.access, snap)
        self.assertEqual(checked.snapshot_hash, snap.content_hash)
        self.assertEqual(checked.state, "ready_for_review")
        self.assertNotIn("revision_requires_revalidation", {i.code for i in checked.issues})
        self.assertTrue(self.plan_write(checked)["ready_for_execution"])

    def test_old_snapshot_does_not_support_new_revision(self):
        plan, _ = self.make_plan()
        checked = revalidate_revision(plan, self.profile, self.request, self.access, self.snapshot)
        self.assertEqual(checked.state, "draft_with_gaps")
        self.assertFalse(self.plan_write(checked)["ready_for_execution"])

    def test_report_contains_original_evidence_locator(self):
        report = build_report(self.base, self.profile, self.snapshot)
        self.assertTrue(report["evidence_trace_complete"])
        self.assertTrue(report["evidence_sources"])
        self.assertEqual(report["evidence_sources"]["E001"]["source_uri"], "demo://projects/demo_project/record/1")
        with self.assertRaises(ContractError):
            build_report(self.base, self.profile, replace(self.snapshot, snapshot_id="wrong"))

    def test_scoped_snapshot_persisted_for_audit(self):
        row = self.store.conn.execute("SELECT run_key,content_hash FROM amdoc_fact_snapshots").fetchone()
        pinned = self.store.read_pinned_snapshot(row[0], row[1])
        self.assertEqual(pinned.content_hash, self.base.snapshot_hash)
        self.assertEqual(pinned.evidence[0].source_revision, "demo-1")


if __name__ == "__main__":
    unittest.main()
