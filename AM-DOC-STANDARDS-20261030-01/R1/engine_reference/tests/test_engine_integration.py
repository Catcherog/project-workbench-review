"""Cross-module scenarios using the distributed synthetic fixture, without live services."""
from __future__ import annotations

import dataclasses
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from am_doc_engine.adapters import EvidenceBoundModelComposer, ExtractiveComposer, ProviderSession
from am_doc_engine.catalog import TemplateCatalog
from am_doc_engine.engine import DocumentEngine
from am_doc_engine.evidence import scoped_snapshot
from am_doc_engine.models import (
    AccessDenied, IdempotencyConflict, RevisionConflict, SelectionError, SemanticReview,
)
from am_doc_engine.review import EvidenceSemanticReviewer
from am_doc_engine.storage import SQLiteRunStore
from tests.helpers import demo


class CountingComposer(ExtractiveComposer):
    def __init__(self, after_compose=None):
        self.batch_calls = 0
        self.after_compose = after_compose

    def compose_many(self, pairs, request, profile):
        self.batch_calls += 1
        output = super().compose_many(pairs, request, profile)
        if self.after_compose:
            self.after_compose()
        return output


class TwoPhaseProvider:
    """The fake records host integration calls and returns fixture-bound output."""
    def __init__(self, profile, snapshot):
        self.calls = []
        self.narrative = [rule for rule in profile.fields if rule.mode == "narrative"]
        self.facts = {item.key: item for item in snapshot.evidence}

    def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if prompt.startswith("你是文档内容核对器"):
            payload = {"checks": [{"field_id": rule.field_id, "verdict": "supported",
                                    "reason": "合成样例正文与所引事实一致。"} for rule in self.narrative]}
        else:
            payload = {"fields": [{"field_id": rule.field_id,
                                   "text": self.facts[rule.fact_keys[0]].value,
                                   "evidence_ids": [self.facts[rule.fact_keys[0]].evidence_id]}
                                  for rule in self.narrative]}
        return SimpleNamespace(text=json.dumps(payload, ensure_ascii=False), model="fixture", elapsed=0)


class EngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        clock = patch("am_doc_engine.engine.now_iso", return_value="2026-10-30T10:00:00+08:00")
        clock.start()
        self.addCleanup(clock.stop)

    def store(self, **kwargs):
        store = SQLiteRunStore(**kwargs)
        self.addCleanup(store.close)
        return store

    def engine(self, profile, **kwargs):
        store = self.store()
        return DocumentEngine(TemplateCatalog([profile]), store, **kwargs), store

    @staticmethod
    def narrative_profile(profile, count=1):
        return dataclasses.replace(profile, fields=tuple(
            dataclasses.replace(rule, mode="narrative") if index < count else rule
            for index, rule in enumerate(profile.fields)))

    @staticmethod
    def field(document, field_id):
        return next(item for item in document.fields if item.field_id == field_id)

    def test_complete_charter_and_change_are_reviewable_and_bound(self):
        for kind in ["charter", "change"]:
            with self.subTest(kind=kind):
                profile, request, access, snapshot = demo(kind)
                engine, _ = self.engine(profile)
                document = engine.generate(request, access, snapshot)
                self.assertEqual(document.state, "ready_for_review")
                self.assertTrue(all(field.status == "filled" for field in document.fields))
                self.assertFalse(any(issue.severity == "error" for issue in document.issues))
                self.assertEqual(document.template_hash, profile.content_hash)
                self.assertEqual(document.rule_version, profile.rule_version)
                self.assertEqual(document.snapshot_hash, scoped_snapshot(snapshot, request, access).content_hash)
                self.assertEqual(document.as_of, snapshot.as_of)
                text = "\n".join(field.text for field in document.fields)
                for foreign_value in ["ALPHA", "张示例", "999999", "2999-12-31"]:
                    self.assertNotIn(foreign_value, text)
                self.assertNotEqual(document.state, "approved")

    def test_closure_without_acceptance_remains_a_useful_incomplete_draft(self):
        profile, request, access, snapshot = demo("closure")
        engine, _ = self.engine(profile)
        document = engine.generate(request, access, snapshot)
        self.assertEqual(document.state, "draft_with_gaps")
        self.assertEqual(self.field(document, "acceptance").status, "missing")
        self.assertEqual(self.field(document, "result").status, "filled")
        self.assertTrue(any("验收" in question for question in document.questions))
        self.assertLessEqual(len(document.questions), 3)
        self.assertNotIn("验收通过", "\n".join(field.text for field in document.fields))

    def test_candidate_template_is_not_activated_by_generation(self):
        profile, request, access, snapshot = demo()
        candidate = dataclasses.replace(profile, status="candidate")
        engine, store = self.engine(candidate)
        with self.assertRaises(SelectionError):
            engine.generate(request, access, snapshot)
        self.assertEqual(store.conn.execute("SELECT COUNT(*) FROM amdoc_runs").fetchone()[0], 0)

    def test_ambiguous_effective_versions_require_an_explicit_selection(self):
        profile, request, access, snapshot = demo()
        newer = dataclasses.replace(profile, revision="demo-2", rule_version="rules-2")
        store = self.store()
        engine = DocumentEngine(TemplateCatalog([profile, newer]), store)
        with self.assertRaises(SelectionError):
            engine.generate(request, access, snapshot)
        explicit = dataclasses.replace(request, template_id=newer.template_id, template_revision="demo-2")
        result = engine.generate(explicit, access, snapshot)
        self.assertEqual(result.template_revision, "demo-2")
        self.assertEqual(result.rule_version, "rules-2")

    def test_partial_required_source_blocks_but_partial_example_is_visible(self):
        profile, request, access, snapshot = demo()
        broken = dataclasses.replace(profile, assets=tuple(
            dataclasses.replace(asset, read_state="partial") if asset.role == "template" else asset
            for asset in profile.assets))
        engine, _ = self.engine(broken)
        with self.assertRaises(SelectionError):
            engine.generate(request, access, snapshot)
        optional = dataclasses.replace(profile, assets=tuple(
            dataclasses.replace(asset, read_state="partial") if asset.role == "example" else asset
            for asset in profile.assets))
        engine, _ = self.engine(optional)
        result = engine.generate(request, access, snapshot)
        self.assertEqual(result.state, "ready_for_review")
        self.assertTrue(any(issue.code == "reference_partial" for issue in result.issues))

    def test_actor_and_project_visibility_filter_facts_before_filling(self):
        profile, request, access, snapshot = demo()
        owner = next(item for item in snapshot.evidence if item.key == "project.owner")
        hidden = dataclasses.replace(owner, value="另一员工专属人员", allowed_actor_ids=("another_actor",))
        foreign = dataclasses.replace(owner, evidence_id="foreign_owner", project_id="another_project", value="另一项目负责人")
        mixed = dataclasses.replace(snapshot, evidence=tuple(
            hidden if item.evidence_id == owner.evidence_id else item for item in snapshot.evidence) + (foreign,))
        engine, _ = self.engine(profile)
        result = engine.generate(request, access, mixed)
        self.assertEqual(self.field(result, "owner").status, "missing")
        self.assertEqual(result.state, "draft_with_gaps")
        text = "\n".join(item.text for item in result.fields)
        self.assertNotIn(hidden.value, text)
        self.assertNotIn(foreign.value, text)
        safe = scoped_snapshot(mixed, request, access)
        self.assertNotIn(owner.evidence_id, {item.evidence_id for item in safe.evidence})
        self.assertNotIn(foreign.evidence_id, {item.evidence_id for item in safe.evidence})
        self.assertEqual(result.snapshot_hash, safe.content_hash)
        self.assertNotEqual(result.snapshot_hash, mixed.content_hash)

    def test_unauthorized_target_project_fails_before_any_run_is_saved(self):
        profile, request, access, snapshot = demo()
        request = dataclasses.replace(request, project_id="another_project")
        engine, store = self.engine(profile)
        with self.assertRaises(AccessDenied):
            engine.generate(request, access, snapshot)
        self.assertEqual(store.conn.execute("SELECT COUNT(*) FROM amdoc_runs").fetchone()[0], 0)

    def test_actor_and_chat_are_part_of_idempotency_identity(self):
        profile, request, access, snapshot = demo()
        actors = (access.actor_id, "second_actor")
        profile = dataclasses.replace(profile, allowed_actor_ids=actors)
        snapshot = dataclasses.replace(snapshot, evidence=tuple(
            dataclasses.replace(item, allowed_actor_ids=actors) for item in snapshot.evidence))
        engine, store = self.engine(profile)
        first = engine.generate(request, access, snapshot)
        second = engine.generate(request, dataclasses.replace(access, actor_id="second_actor"), snapshot)
        another_chat = engine.generate(request, dataclasses.replace(access, chat_id="another_chat"), snapshot)
        self.assertEqual(len({first.document_id, second.document_id, another_chat.document_id}), 3)
        self.assertEqual(store.conn.execute("SELECT COUNT(*) FROM amdoc_runs WHERE status='complete'").fetchone()[0], 3)

    def test_explicit_confirmed_supersession_replaces_only_the_matching_baseline(self):
        profile, request, access, snapshot = demo()
        before = next(item for item in snapshot.evidence if item.key == "project.planned_finish")
        after = dataclasses.replace(before, evidence_id="baseline_revision", value="2026-11-28",
                                    source_revision="demo-2", supersedes=(before.evidence_id,))
        changed = dataclasses.replace(snapshot, evidence=snapshot.evidence + (after,))
        engine, _ = self.engine(profile)
        result = engine.generate(request, access, changed)
        finish = self.field(result, "finish")
        self.assertEqual(result.state, "ready_for_review")
        self.assertEqual(finish.evidence_ids, (after.evidence_id,))
        self.assertIn(after.value, finish.text)
        self.assertNotIn(before.value, finish.text)

    def test_conflicting_baselines_are_not_resolved_by_upload_order(self):
        profile, request, access, snapshot = demo()
        before = next(item for item in snapshot.evidence if item.key == "project.planned_finish")
        conflicting = dataclasses.replace(before, evidence_id="unresolved_baseline", value="2026-11-28", source_revision="demo-2")
        changed = dataclasses.replace(snapshot, evidence=snapshot.evidence + (conflicting,))
        engine, _ = self.engine(profile)
        result = engine.generate(request, access, changed)
        finish = self.field(result, "finish")
        self.assertEqual(result.state, "draft_with_gaps")
        self.assertEqual(finish.status, "conflict")
        self.assertEqual(set(finish.evidence_ids), {before.evidence_id, conflicting.evidence_id})
        self.assertTrue(any(issue.code == "fact_conflict" for issue in result.issues))

    def test_forecast_does_not_replace_the_approved_baseline(self):
        profile, request, access, snapshot = demo()
        baseline = next(item for item in snapshot.evidence if item.key == "project.planned_finish")
        forecast = dataclasses.replace(baseline, evidence_id="same_key_forecast", semantic="forecast", value="2026-11-30")
        changed = dataclasses.replace(snapshot, evidence=snapshot.evidence + (forecast,))
        engine, _ = self.engine(profile)
        result = engine.generate(request, access, changed)
        finish = self.field(result, "finish")
        self.assertEqual(result.state, "ready_for_review")
        self.assertEqual(finish.evidence_ids, (baseline.evidence_id,))
        self.assertIn(baseline.value, finish.text)
        self.assertNotIn(forecast.value, finish.text)

    def test_replaying_completed_request_returns_same_result_without_regeneration(self):
        profile, request, access, snapshot = demo()
        profile = self.narrative_profile(profile)
        composer = CountingComposer()
        engine, _ = self.engine(profile, composer=composer)
        first = engine.generate(request, access, snapshot)
        replay = engine.generate(request, access, snapshot)
        self.assertEqual(replay, first)
        self.assertEqual(composer.batch_calls, 1)

    def test_same_request_with_changed_facts_rules_or_instructions_conflicts(self):
        profile, request, access, snapshot = demo()
        engine, store = self.engine(profile)
        original = engine.generate(request, access, snapshot)
        modified_fact = dataclasses.replace(snapshot.evidence[0], value="经过业务确认的新背景。", source_revision="demo-2")
        updated = dataclasses.replace(snapshot, evidence=(modified_fact,) + snapshot.evidence[1:])
        with self.assertRaises(IdempotencyConflict):
            engine.generate(request, access, updated)
        with self.assertRaises(IdempotencyConflict):
            engine.generate(dataclasses.replace(request, instructions="本次改为简洁表达"), access, snapshot)
        new_rules = dataclasses.replace(profile, rule_version="rules-2")
        with self.assertRaises(IdempotencyConflict):
            DocumentEngine(TemplateCatalog([new_rules]), store).generate(request, access, snapshot)
        self.assertEqual(engine.generate(request, access, snapshot), original)

    def test_expired_sqlite_lease_cannot_overwrite_a_new_owner(self):
        profile, request, access, snapshot = demo()
        engine, _ = self.engine(profile)
        document = engine.generate(request, access, snapshot)
        clock = [100.0]
        store = self.store(clock=lambda: clock[0])
        stale = store.claim("lease-run", "same-input", lease_seconds=1)
        clock[0] = 102.0
        with self.assertRaises(RevisionConflict):
            store.complete(stale, document)
        current = store.claim("lease-run", "same-input", lease_seconds=10)
        self.assertNotEqual(stale.owner, current.owner)
        with self.assertRaises(RevisionConflict):
            store.complete(stale, document)
        store.complete(current, document)
        store.fail(stale, "late-error")
        self.assertEqual(store.claim("lease-run", "same-input").cached, document)

    def test_false_guard_before_generation_has_no_saved_run(self):
        profile, request, access, snapshot = demo()
        engine, store = self.engine(profile, ensure_current=lambda: False)
        with self.assertRaises(RevisionConflict):
            engine.generate(request, access, snapshot)
        self.assertEqual(store.conn.execute("SELECT COUNT(*) FROM amdoc_runs").fetchone()[0], 0)

    def test_cancellation_after_composition_does_not_fallback_or_save_document(self):
        profile, request, access, snapshot = demo()
        profile = self.narrative_profile(profile)
        active = [True]
        composer = CountingComposer(after_compose=lambda: active.__setitem__(0, False))
        engine, store = self.engine(profile, composer=composer, ensure_current=lambda: active[0])
        with self.assertRaises(RevisionConflict):
            engine.generate(request, access, snapshot)
        row = store.conn.execute("SELECT status,result_json,error_code FROM amdoc_runs").fetchone()
        self.assertEqual(composer.batch_calls, 1)
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["result_json"])
        self.assertEqual(row["error_code"], "RevisionConflict")

    def test_two_narrative_fields_share_one_generation_and_one_review_call(self):
        profile, request, access, snapshot = demo()
        profile = self.narrative_profile(profile, count=2)
        provider = TwoPhaseProvider(profile, snapshot)
        session = ProviderSession(provider, run_id="e" * 32, timeout=120)
        composer = EvidenceBoundModelComposer(session=session)
        reviewer = EvidenceSemanticReviewer(session)
        engine, _ = self.engine(profile, composer=composer, reviewer=reviewer)
        result = engine.generate(request, access, snapshot)
        self.assertEqual(result.state, "ready_for_review", result.issues)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(sum(field.origin == "model" for field in result.fields), 2)
        self.assertIn('"fields":[', provider.calls[0][0])
        self.assertTrue(provider.calls[1][0].startswith("你是文档内容核对器"))
        self.assertEqual(provider.calls[0][1]["run_id"], provider.calls[1][1]["run_id"])
        self.assertLessEqual(provider.calls[1][1]["timeout"], provider.calls[0][1]["timeout"])
        self.assertFalse(any(issue.code == "semantic_review_required" for issue in result.issues))
        self.assertEqual(result.template_hash, profile.content_hash)
        self.assertEqual(result.snapshot_hash, scoped_snapshot(snapshot, request, access).content_hash)

    def test_review_for_another_basis_does_not_release_current_draft(self):
        profile, request, access, snapshot = demo()
        profile = self.narrative_profile(profile, count=2)
        provider = TwoPhaseProvider(profile, snapshot)
        session = ProviderSession(provider, run_id="f" * 32)
        def stale_review(_profile, _request, fields, resolutions):
            ids = tuple(field.field_id for field in fields if field.origin == "model")
            return SemanticReview("another-template-or-snapshot", ids, (), "stale-fixture")
        engine, _ = self.engine(profile, composer=EvidenceBoundModelComposer(session=session), reviewer=stale_review)
        result = engine.generate(request, access, snapshot)
        self.assertEqual(result.state, "draft_with_gaps")
        self.assertTrue(any(issue.code == "semantic_review_failed" for issue in result.issues))
        self.assertTrue(any(issue.code == "semantic_review_required" for issue in result.issues))


if __name__ == "__main__":
    unittest.main()
