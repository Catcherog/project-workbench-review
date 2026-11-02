"""Behavioral tests for exact one-shot authorization and shared attention keys.

No test opens a network socket or contacts a person.  Sender doubles implement
the existing-AM adapter contract; platform permissions/readback remain a real
environment acceptance requirement.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from am_followup.followup import (
    Actor, ApprovalRequest, Draft, EvidenceSnapshot, FollowupCoordinator,
    FollowupError, GateResult, ReadbackEvidence, SendOutcome, SendWindow, Target,
)


NOW = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)  # 10:00 Asia/Shanghai


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


class Gates:
    def __init__(self):
        self.source_version = "v1"
        self.acl_version = "acl1"
        self.task_version = "task1"
        self.task_completed = False
        self.recipient_ok = True

    def evidence(self, tenant, owner, draft):
        if self.task_completed:
            return GateResult(False, "task_completed")
        if draft.evidence.versions != {"source:synthetic": self.source_version}:
            return GateResult(False, "source_changed")
        if draft.evidence.acl_versions != {"source:synthetic": self.acl_version}:
            return GateResult(False, "acl_changed")
        if draft.evidence.task_version != self.task_version:
            return GateResult(False, "task_changed")
        if "team:synthetic" not in draft.evidence.disclosure_scopes:
            return GateResult(False, "disclosure_denied")
        return GateResult(True)

    def recipient(self, tenant, target, now):
        return GateResult(self.recipient_ok, "membership_or_reachability_changed")


class RecordingSender:
    def __init__(self, clock, *, mode="confirmed", before_guard=None, after_guard=None):
        self.clock = clock
        self.mode = mode
        self.before_guard = before_guard
        self.after_guard = after_guard
        self.calls = []
        self.requests = []

    def receipt(self, request):
        return ReadbackEvidence(
            request_uuid=request.request_uuid,
            external_action_id="old_am_action:" + request.intent_id,
            message_id="synthetic_message:" + request.intent_id,
            target_kind=request.draft.target.kind,
            target_id=request.draft.target.target_id,
            body_sha256=hashlib.sha256(request.draft.body.encode()).hexdigest(),
            mention_ids=request.draft.target.mention_ids,
            correlation="send_response_message_id",
            source_record_id="synthetic_exact_readback:" + request.intent_id,
            observed_at=self.clock(),
        )

    def dispatch(self, request, before_send):
        self.requests.append(request)
        if self.before_guard:
            self.before_guard(request)
        if self.mode != "missing_gate":
            before_send()
        if self.after_guard:
            self.after_guard(request)
        self.calls.append(request.intent_id)
        if self.mode == "timeout":
            raise TimeoutError("simulated timeout after remote side effect")
        if self.mode == "unknown":
            return SendOutcome("unknown", external_action_id="old_am_action:" + request.intent_id)
        if self.mode == "accepted":
            return SendOutcome("accepted", external_action_id="old_am_action:" + request.intent_id)
        if self.mode == "failed":
            return SendOutcome("failed", reason="definitive_provider_rejection", definitive_no_send=True)
        receipt = self.receipt(request)
        if self.mode == "bad_body":
            receipt = replace(receipt, body_sha256="wrong")
        if self.mode == "bad_target":
            receipt = replace(receipt, target_id="another_chat")
        if self.mode == "text_search":
            receipt = replace(receipt, correlation="same_text_search")
        if self.mode == "missing_readback":
            receipt = None
        return SendOutcome(
            "confirmed", external_action_id="old_am_action:" + request.intent_id,
            message_id="synthetic_message:" + request.intent_id, readback=receipt,
        )


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "followup.sqlite3"
        self.clock = Clock()
        self.gates = Gates()
        self.service = self.new_service()
        self.actor = Actor("tenant-a", "owner-a", "verified-session-a", NOW + timedelta(hours=3))
        self.episode = self.service.register_episode("tenant-a", "task-a", "request_update", "new-request:1")
        self.draft = Draft(
            task_id="task-a", purpose="request_update", episode_id=self.episode,
            body="请确认测试是否已经开始；如未开始，请说明阻碍。",
            target=Target(
                kind="group", target_id="group-a", attention_ids=("engineer-a",),
                mention_ids=("engineer-a",), directory_version="directory1",
                valid_until=NOW + timedelta(hours=2),
            ),
            evidence=EvidenceSnapshot(
                versions={"source:synthetic": "v1"}, acl_versions={"source:synthetic": "acl1"},
                task_version="task1", disclosure_scopes=("team:synthetic",),
            ),
            window=SendWindow(
                not_before=NOW - timedelta(seconds=1), expires_at=NOW + timedelta(hours=1),
                working_dates=("2026-11-02",), calendar_version="calendar-synthetic-1",
            ),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def new_service(self):
        return FollowupCoordinator(
            self.path, signing_key=b"synthetic-signing-key-32-bytes-only",
            owner_ids={"tenant-a": "owner-a", "tenant-b": "owner-b"},
            evidence_gate=self.gates.evidence, recipient_gate=self.gates.recipient,
            clock=self.clock,
        )

    def preview(self, draft=None):
        return self.service.create_preview(self.actor, draft or self.draft)

    def approve(self, preview=None):
        p = preview or self.preview()
        return self.service.approve(self.actor, p.preview_id, p.token, p.content_hash)

    def test_one_click_queues_exact_message_replay_is_same_intent(self):
        p = self.preview()
        first = self.approve(p)
        second = self.approve(p)
        self.assertEqual(first.intent_id, second.intent_id)
        self.assertEqual(second.status, "replay")
        sender = RecordingSender(self.clock)
        sent = self.service.dispatch_once("tenant-a", first.intent_id, sender, worker_id="worker-a")
        again = self.service.dispatch_once("tenant-a", first.intent_id, sender, worker_id="worker-b")
        self.assertEqual(sent.state, "confirmed")
        self.assertEqual(again.message_id, sent.message_id)
        self.assertEqual(len(sender.calls), 1)

    def test_preview_is_not_send_authorization(self):
        p = self.preview()
        sender = RecordingSender(self.clock)
        with self.assertRaisesRegex(FollowupError, "intent_not_found"):
            self.service.dispatch_once("tenant-a", p.preview_id, sender, worker_id="worker-a")
        self.assertEqual(sender.calls, [])

    def test_wrong_owner_cannot_approve(self):
        p = self.preview()
        other = replace(self.actor, user_id="engineer-a")
        with self.assertRaisesRegex(FollowupError, "owner_required"):
            self.service.approve(other, p.preview_id, p.token, p.content_hash)

    def test_tenant_isolation(self):
        p = self.preview()
        actor_b = Actor("tenant-b", "owner-b", "verified-session-b", self.actor.expires_at)
        with self.assertRaisesRegex(FollowupError, "preview_not_found"):
            self.service.approve(actor_b, p.preview_id, p.token, p.content_hash)
        approved = self.approve(p)
        with self.assertRaisesRegex(FollowupError, "intent_not_found"):
            self.service.get_intent(actor_b, approved.intent_id)
        self.assertEqual(self.service.audit(actor_b, approved.intent_id), [])

    def test_expired_authenticated_actor_rejected(self):
        with self.assertRaisesRegex(FollowupError, "actor_expired"):
            self.service.create_preview(replace(self.actor, expires_at=NOW), self.draft)

    def test_modified_display_hash_cannot_approve(self):
        p = self.preview()
        with self.assertRaisesRegex(FollowupError, "displayed_preview_changed"):
            self.service.approve(self.actor, p.preview_id, p.token, "different")

    def test_tampered_token_cannot_approve(self):
        p = self.preview()
        with self.assertRaisesRegex(FollowupError, "invalid_approval_token"):
            self.service.approve(self.actor, p.preview_id, p.token + "x", p.content_hash)

    def test_other_preview_token_cannot_be_reused(self):
        first, second = self.preview(), self.preview()
        with self.assertRaisesRegex(FollowupError, "invalid_approval_token"):
            self.service.approve(self.actor, second.preview_id, first.token, second.content_hash)

    def test_expired_preview_not_approved(self):
        p = self.preview()
        self.clock.value += timedelta(minutes=11)
        with self.assertRaisesRegex(FollowupError, "preview_expired"):
            self.approve(p)

    def test_approved_replay_after_preview_expiry_does_not_renew_authorization(self):
        p = self.preview()
        first = self.approve(p)
        self.clock.value += timedelta(minutes=61)
        replay = self.approve(p)
        self.assertEqual(replay.intent_id, first.intent_id)
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", first.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.reason, "authorization_expired")
        self.assertEqual(sender.calls, [])

    def test_source_change_before_approval_rejected(self):
        p = self.preview()
        self.gates.source_version = "v2"
        with self.assertRaisesRegex(FollowupError, "evidence_blocked"):
            self.approve(p)

    def test_source_change_before_send_blocks_old_approval(self):
        approved = self.approve()
        self.gates.source_version = "v2"
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "blocked")
        self.assertEqual(sender.calls, [])

    def test_acl_change_before_send_blocks_old_approval(self):
        approved = self.approve()
        self.gates.acl_version = "acl2"
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "blocked")
        self.assertEqual(sender.calls, [])

    def test_completed_task_cancels_stale_followup(self):
        approved = self.approve()
        self.gates.task_completed = True
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "blocked")
        self.assertEqual(sender.calls, [])

    def test_changed_membership_blocks_old_approval(self):
        approved = self.approve()
        self.gates.recipient_ok = False
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "blocked")
        self.assertEqual(sender.calls, [])

    def test_recipient_expiry_checked_at_send_time(self):
        p = self.preview(replace(self.draft, target=replace(self.draft.target, valid_until=NOW + timedelta(minutes=1))))
        approved = self.approve(p)
        self.clock.value += timedelta(minutes=2)
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.reason, "recipient_snapshot_expired")
        self.assertEqual(sender.calls, [])

    def test_semantic_duplicate_across_producers_and_draft_rewording(self):
        first = self.approve()
        other = self.preview(replace(self.draft, body="请反馈开测情况。", producer_id="personal-assistant"))
        duplicate = self.approve(other)
        self.assertEqual(duplicate.status, "already_reserved")
        self.assertEqual(duplicate.intent_id, first.intent_id)
        self.assertIn("not_sent", duplicate.reason)

    def test_group_and_private_same_attention_are_deduplicated(self):
        first = self.approve()
        dm = replace(self.draft.target, kind="recipient_p2p", target_id="engineer-a", mention_ids=())
        second = self.approve(self.preview(replace(self.draft, target=dm)))
        self.assertEqual(second.intent_id, first.intent_id)
        self.assertEqual(second.status, "already_reserved")

    def test_group_cannot_partially_send_when_one_person_reserved(self):
        first = self.approve()
        group = replace(self.draft.target, attention_ids=("engineer-a", "engineer-b"), mention_ids=("engineer-a", "engineer-b"))
        second = self.approve(self.preview(replace(self.draft, target=group)))
        self.assertEqual(second.status, "already_reserved")
        self.assertEqual(second.intent_id, first.intent_id)

    def test_new_verified_episode_allows_a_distinct_followup(self):
        first = self.approve()
        new_episode = self.service.register_episode("tenant-a", "task-a", "request_update", "new-request:2")
        second = self.approve(self.preview(replace(self.draft, episode_id=new_episode)))
        self.assertNotEqual(second.intent_id, first.intent_id)

    def test_unknown_episode_not_accepted(self):
        with self.assertRaisesRegex(FollowupError, "unknown_or_mismatched_episode"):
            self.preview(replace(self.draft, episode_id="model-invented-random-nonce"))

    def test_episode_registration_is_idempotent_across_instances(self):
        other = self.new_service()
        self.assertEqual(self.episode, other.register_episode("tenant-a", "task-a", "request_update", "new-request:1"))

    def test_owner_channel_cannot_be_reused_as_engineer_dm(self):
        wrong = replace(self.draft.target, kind="owner", target_id="engineer-a", mention_ids=())
        with self.assertRaisesRegex(FollowupError, "owner_is_not_engineer_dm"):
            self.preview(replace(self.draft, target=wrong))

    def test_exact_engineer_dm_is_supported_separately(self):
        target = replace(self.draft.target, kind="recipient_p2p", target_id="engineer-a", mention_ids=())
        approved = self.approve(self.preview(replace(self.draft, target=target)))
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "confirmed")
        self.assertEqual(sender.requests[0].draft.target.kind, "recipient_p2p")

    def test_external_target_and_at_all_are_rejected(self):
        with self.assertRaisesRegex(FollowupError, "unsupported_target"):
            self.preview(replace(self.draft, target=replace(self.draft.target, audience="external")))
        bad_target = replace(self.draft.target, attention_ids=("all",), mention_ids=("all",))
        with self.assertRaisesRegex(FollowupError, "broadcast_forbidden"):
            self.preview(replace(self.draft, target=bad_target))

    def test_llm_cannot_inject_mention_markup(self):
        with self.assertRaisesRegex(FollowupError, "inline_mention_markup_forbidden"):
            self.preview(replace(self.draft, body='<at user_id="unapproved">工程师</at> 请处理'))

    def test_body_change_after_preview_storage_detected(self):
        p = self.preview()
        with sqlite3.connect(self.path) as db:
            raw = json.loads(db.execute("SELECT draft_json FROM followup_previews WHERE preview_id=?", (p.preview_id,)).fetchone()[0])
            raw["body"] = "changed-after-preview"
            db.execute("UPDATE followup_previews SET draft_json=? WHERE preview_id=?", (json.dumps(raw), p.preview_id))
        with self.assertRaisesRegex(FollowupError, "stored_preview_changed"):
            self.approve(p)

    def test_body_change_after_approval_storage_blocks_send(self):
        approved = self.approve()
        with sqlite3.connect(self.path) as db:
            raw = json.loads(db.execute("SELECT draft_json FROM followup_intents WHERE intent_id=?", (approved.intent_id,)).fetchone()[0])
            raw["body"] = "changed-after-approval"
            db.execute("UPDATE followup_intents SET draft_json=? WHERE intent_id=?", (json.dumps(raw), approved.intent_id))
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.reason, "stored_intent_changed")
        self.assertEqual(sender.calls, [])

    def test_pause_before_send_stops_it(self):
        approved = self.approve()
        stopped = self.service.pause(self.actor, approved.intent_id)
        self.assertEqual(stopped.effect, "unsent_stopped")
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "paused")
        self.assertEqual(sender.calls, [])

    def test_revoke_between_claim_and_final_guard_prevents_send(self):
        approved = self.approve()
        sender = RecordingSender(self.clock, before_guard=lambda req: self.service.revoke(self.actor, req.intent_id))
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "revoked")
        self.assertEqual(sender.calls, [])

    def test_final_guard_rechecks_evidence_after_adapter_preparation(self):
        approved = self.approve()
        sender = RecordingSender(self.clock, before_guard=lambda req: setattr(self.gates, "source_version", "v2"))
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "blocked")
        self.assertEqual(sender.calls, [])

    def test_revoke_after_send_boundary_does_not_claim_recall(self):
        approved = self.approve()
        effects = []
        sender = RecordingSender(self.clock, after_guard=lambda req: effects.append(self.service.revoke(self.actor, req.intent_id)))
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(effects[0].effect, "in_flight_not_recalled")
        self.assertEqual(result.state, "confirmed")
        self.assertEqual(result.stop_requested, "revoke")

    def test_timeout_is_unknown_and_never_blind_retried(self):
        approved = self.approve()
        sender = RecordingSender(self.clock, mode="timeout")
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        second = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-b")
        self.assertEqual(result.state, "unknown")
        self.assertEqual(second.state, "unknown")
        self.assertEqual(len(sender.calls), 1)
        duplicate = self.approve(self.preview(replace(self.draft, producer_id="personal-assistant")))
        self.assertEqual(duplicate.intent_id, approved.intent_id)

    def test_unknown_reconciles_only_exact_request_target_body_and_action(self):
        approved = self.approve()
        sender = RecordingSender(self.clock, mode="unknown")
        self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        receipt = sender.receipt(sender.requests[0])
        bad_variants = (
            replace(receipt, request_uuid="other-request"),
            replace(receipt, target_id="other-chat"),
            replace(receipt, body_sha256="other-body"),
            replace(receipt, external_action_id="other-action"),
            replace(receipt, mention_ids=("other-person",)),
            replace(receipt, correlation="same_text_search"),
        )
        for bad in bad_variants:
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(FollowupError, "readback_mismatch"):
                    self.service.reconcile("tenant-a", approved.intent_id, bad)
        confirmed = self.service.reconcile("tenant-a", approved.intent_id, receipt)
        self.assertEqual(confirmed.state, "confirmed")
        self.assertEqual(confirmed.message_id, receipt.message_id)
        self.assertEqual(len(sender.calls), 1)

    def test_missing_or_inexact_readback_never_counts_as_confirmed(self):
        for mode in ("accepted", "bad_body", "bad_target", "text_search", "missing_readback", "missing_gate"):
            with self.subTest(mode=mode):
                task = "task:" + mode
                episode = self.service.register_episode("tenant-a", task, "request_update", "case:" + mode)
                approved = self.approve(self.preview(replace(self.draft, task_id=task, episode_id=episode)))
                sender = RecordingSender(self.clock, mode=mode)
                result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
                self.assertEqual(result.state, "unknown")

    def test_two_connections_approve_one_attention_only(self):
        first, second = self.preview(), self.preview(replace(self.draft, producer_id="other-producer"))
        other = self.new_service()
        barrier = threading.Barrier(2)

        def call(service, preview):
            barrier.wait()
            return service.approve(self.actor, preview.preview_id, preview.token, preview.content_hash)

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(call, self.service, first)
            f2 = pool.submit(call, other, second)
            results = [f1.result(), f2.result()]
        self.assertEqual(len({r.intent_id for r in results}), 1)
        self.assertEqual({r.status for r in results}, {"approved", "already_reserved"})

    def test_two_consumers_cannot_dispatch_same_intent(self):
        approved = self.approve()
        other = self.new_service()
        entered, release = threading.Event(), threading.Event()

        def pause_at_provider(request):
            entered.set()
            self.assertTrue(release.wait(3))

        first_sender = RecordingSender(self.clock, after_guard=pause_at_provider)
        second_sender = RecordingSender(self.clock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(self.service.dispatch_once, "tenant-a", approved.intent_id, first_sender, worker_id="worker-a")
            self.assertTrue(entered.wait(3))
            second = other.dispatch_once("tenant-a", approved.intent_id, second_sender, worker_id="worker-b")
            release.set()
            first = pending.result()
        self.assertEqual(second.state, "sending")
        self.assertEqual(first.state, "confirmed")
        self.assertEqual(len(first_sender.calls) + len(second_sender.calls), 1)

    def test_recovery_fences_claimed_worker_without_retry(self):
        approved = self.approve()
        sender = RecordingSender(self.clock, before_guard=lambda req: self.service.recover_in_flight("tenant-a", "worker-a"))
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "unknown")
        self.assertEqual(sender.calls, [])
        another = RecordingSender(self.clock)
        self.new_service().dispatch_once("tenant-a", approved.intent_id, another, worker_id="worker-b")
        self.assertEqual(another.calls, [])

    def test_recovery_after_boundary_keeps_unknown_until_exact_reconcile(self):
        approved = self.approve()
        sender = RecordingSender(self.clock, after_guard=lambda req: self.service.recover_in_flight("tenant-a", "worker-a"))
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "unknown")
        self.assertEqual(len(sender.calls), 1)
        recovered = self.new_service().reconcile("tenant-a", approved.intent_id, sender.receipt(sender.requests[0]))
        self.assertEqual(recovered.state, "confirmed")

    def test_quiet_hours_defer_without_send(self):
        self.clock.value = datetime(2026, 11, 2, 0, 30, tzinfo=timezone.utc)  # 08:30
        draft = replace(self.draft, window=replace(self.draft.window, not_before=self.clock() - timedelta(seconds=1)))
        approved = self.approve(self.preview(draft))
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "queued")
        self.assertEqual(result.reason, "quiet_hours")
        self.assertEqual(sender.calls, [])

    def test_unknown_working_date_does_not_send(self):
        draft = replace(self.draft, window=replace(self.draft.window, working_dates=("2026-11-03",)))
        approved = self.approve(self.preview(draft))
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.reason, "not_approved_working_date")
        self.assertEqual(sender.calls, [])

    def test_batch_preserves_individual_outcomes(self):
        first, second = self.preview(), self.preview()
        result = self.service.approve_batch(self.actor, [
            ApprovalRequest(first.preview_id, first.token, first.content_hash),
            ApprovalRequest(second.preview_id, second.token + "bad", second.content_hash),
        ])
        self.assertEqual(result[0].result.status, "approved")
        self.assertEqual(result[1].error, "invalid_approval_token")

    def test_explicit_replacement_only_before_send(self):
        first = self.approve()
        self.service.pause(self.actor, first.intent_id)
        replacement = replace(self.draft, body="请反馈测试是否开测。", supersedes_intent_id=first.intent_id)
        second = self.approve(self.preview(replacement))
        self.assertNotEqual(second.intent_id, first.intent_id)
        self.assertEqual(self.service.get_intent(self.actor, first.intent_id).state, "superseded")
        sender = RecordingSender(self.clock)
        old = self.service.dispatch_once("tenant-a", first.intent_id, sender, worker_id="worker-a")
        new = self.service.dispatch_once("tenant-a", second.intent_id, sender, worker_id="worker-a")
        self.assertEqual(old.state, "superseded")
        self.assertEqual(new.state, "confirmed")
        self.assertEqual(len(sender.calls), 1)

    def test_unknown_intent_cannot_be_replaced_to_bypass_uncertainty(self):
        first = self.approve()
        sender = RecordingSender(self.clock, mode="unknown")
        self.service.dispatch_once("tenant-a", first.intent_id, sender, worker_id="worker-a")
        replacement = self.preview(replace(self.draft, supersedes_intent_id=first.intent_id))
        with self.assertRaisesRegex(FollowupError, "cannot_replace_executed_or_claimed_intent"):
            self.approve(replacement)

    def test_owner_configuration_change_blocks_pending_send(self):
        approved = self.approve()
        self.service.owner_ids["tenant-a"] = "new-owner-a"
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "blocked")
        self.assertEqual(sender.calls, [])

    def test_receipt_from_future_is_not_confirmed(self):
        approved = self.approve()
        sender = RecordingSender(self.clock, mode="unknown")
        self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        receipt = replace(sender.receipt(sender.requests[0]), observed_at=NOW + timedelta(minutes=2))
        with self.assertRaisesRegex(FollowupError, "readback_mismatch"):
            self.service.reconcile("tenant-a", approved.intent_id, receipt)

    def test_replay_persists_after_new_coordinator_instance(self):
        p = self.preview()
        first = self.approve(p)
        replay = self.new_service().approve(self.actor, p.preview_id, p.token, p.content_hash)
        self.assertEqual(first.intent_id, replay.intent_id)

    def test_unknown_cannot_be_bypassed_by_new_episode(self):
        first = self.approve()
        sender = RecordingSender(self.clock, mode="unknown")
        self.service.dispatch_once("tenant-a", first.intent_id, sender, worker_id="worker-a")
        later_episode = self.service.register_episode("tenant-a", "task-a", "request_update", "later-reminder-window")
        preview = self.preview(replace(self.draft, episode_id=later_episode))
        with self.assertRaisesRegex(FollowupError, "prior_delivery_uncertain"):
            self.approve(preview)
        self.assertEqual(len(sender.calls), 1)

    def test_prequeued_new_episode_waits_for_old_exact_readback(self):
        first = self.approve()
        later_episode = self.service.register_episode("tenant-a", "task-a", "request_update", "later-reminder-window")
        second = self.approve(self.preview(replace(self.draft, episode_id=later_episode)))
        first_sender = RecordingSender(self.clock, mode="unknown")
        self.service.dispatch_once("tenant-a", first.intent_id, first_sender, worker_id="worker-a")
        second_sender = RecordingSender(self.clock)
        blocked = self.service.dispatch_once("tenant-a", second.intent_id, second_sender, worker_id="worker-b")
        self.assertEqual(blocked.reason, "prior_delivery_uncertain")
        self.assertEqual(second_sender.calls, [])
        self.service.reconcile("tenant-a", first.intent_id, first_sender.receipt(first_sender.requests[0]))
        after = self.service.dispatch_once("tenant-a", second.intent_id, second_sender, worker_id="worker-b")
        self.assertEqual(after.state, "confirmed")
        self.assertEqual(len(first_sender.calls) + len(second_sender.calls), 2)

    def test_new_episode_group_dm_cross_channel_unknown_barrier(self):
        first = self.approve()
        first_sender = RecordingSender(self.clock, mode="unknown")
        self.service.dispatch_once("tenant-a", first.intent_id, first_sender, worker_id="worker-a")
        later_episode = self.service.register_episode("tenant-a", "task-a", "request_update", "different-channel-window")
        dm = replace(self.draft.target, kind="recipient_p2p", target_id="engineer-a", mention_ids=())
        p = self.preview(replace(self.draft, episode_id=later_episode, target=dm))
        with self.assertRaisesRegex(FollowupError, "prior_delivery_uncertain"):
            self.approve(p)

    def test_new_episode_after_confirmed_old_send_is_allowed(self):
        first = self.approve()
        sender = RecordingSender(self.clock)
        self.service.dispatch_once("tenant-a", first.intent_id, sender, worker_id="worker-a")
        later_episode = self.service.register_episode("tenant-a", "task-a", "request_update", "explicit-new-request")
        second = self.approve(self.preview(replace(self.draft, episode_id=later_episode)))
        self.assertEqual(second.status, "approved")

    def test_truthy_string_gate_is_not_permission(self):
        approved = self.approve()
        self.service.evidence_gate = lambda tenant, owner, draft: GateResult("false")
        sender = RecordingSender(self.clock)
        result = self.service.dispatch_once("tenant-a", approved.intent_id, sender, worker_id="worker-a")
        self.assertEqual(result.state, "blocked")
        self.assertEqual(sender.calls, [])

    def test_truthy_string_failure_does_not_release_unknown_barrier(self):
        approved = self.approve()

        class MalformedFailureSender:
            def dispatch(self, request, before_send):
                before_send()
                return SendOutcome("failed", definitive_no_send="false")

        result = self.service.dispatch_once("tenant-a", approved.intent_id, MalformedFailureSender(), worker_id="worker-a")
        self.assertEqual(result.state, "unknown")
        later_episode = self.service.register_episode("tenant-a", "task-a", "request_update", "later-window")
        with self.assertRaisesRegex(FollowupError, "prior_delivery_uncertain"):
            self.approve(self.preview(replace(self.draft, episode_id=later_episode)))

    def test_truthy_string_cannot_override_quiet_hours(self):
        draft = replace(self.draft, window=replace(self.draft.window, allow_outside_hours="false"))
        with self.assertRaisesRegex(FollowupError, "invalid_quiet_hours_override"):
            self.preview(draft)


if __name__ == "__main__":
    unittest.main()

