"""Synthetic host-readback/normalized-callback tests; no SDK or real sending."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from am_followup.confirmation import (
    ConfirmationBridge, DeliveredPreview, PreviewRowBinding, VerifiedCallback,
    manifest_hash,
)
from am_followup.followup import (
    Actor, Draft, EvidenceSnapshot, FollowupCoordinator, FollowupError,
    GateResult, SendWindow, Target,
)


NOW = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = NOW
        self.denied_recipient = None
        self.coordinator = FollowupCoordinator(
            Path(self.temp.name) / "confirmation.sqlite3",
            signing_key=b"synthetic-confirmation-key-32-bytes",
            owner_ids={"tenant-a": "owner-a"},
            evidence_gate=lambda tenant, owner, draft: GateResult(True),
            recipient_gate=lambda tenant, target, now: GateResult(
                target.target_id != self.denied_recipient, "recipient_unavailable"
            ),
            clock=lambda: self.now,
        )
        self.actor = Actor("tenant-a", "owner-a", "authenticated-session", NOW + timedelta(hours=1))
        self.previews = [self.make_preview("a"), self.make_preview("b")]
        rows = tuple(PreviewRowBinding(p.preview_id, p.content_hash, p.token) for p in self.previews)
        self.delivered = DeliveredPreview(
            tenant_id="tenant-a", owner_id="owner-a", chat_id="owner-chat-a",
            message_id="actual-preview-message-a", view_id="view-a", rows=rows,
            delivered_at=NOW - timedelta(seconds=1), valid_until=NOW + timedelta(minutes=5),
            source_record_id="host-precise-readback-a", verified=True,
        )
        self.callback = VerifiedCallback(
            tenant_id="tenant-a", app_id="am-app-a", actor_id="owner-a",
            chat_id="owner-chat-a", source_message_id="actual-preview-message-a",
            event_id="verified-callback-event-a", occurred_at=NOW,
            view_id="view-a", manifest_hash=manifest_hash(rows),
            selected_preview_ids=tuple(row.preview_id for row in rows),
            action="confirm_send_once",
        )
        self.read_calls = []

        def read_delivered(tenant, view_id):
            self.read_calls.append((tenant, view_id))
            return self.delivered

        self.bridge = ConfirmationBridge(
            self.coordinator, expected_app_id="am-app-a",
            read_delivered=read_delivered, clock=lambda: self.now,
        )

    def tearDown(self):
        self.temp.cleanup()

    def make_preview(self, suffix):
        task = "task-" + suffix
        episode = self.coordinator.register_episode("tenant-a", task, "request_update", "request-event-" + suffix)
        draft = Draft(
            task_id=task, purpose="request_update", episode_id=episode,
            body="请反馈本项测试是否已开始。",
            target=Target(
                kind="recipient_p2p", target_id="recipient-" + suffix,
                attention_ids=("recipient-" + suffix,), directory_version="directory-1",
                valid_until=NOW + timedelta(minutes=30),
            ),
            evidence=EvidenceSnapshot(
                versions={"evidence-" + suffix: "1"}, acl_versions={"evidence-" + suffix: "acl-1"},
                task_version="task-version-1", disclosure_scopes=("internal-team",),
            ),
            window=SendWindow(
                not_before=NOW - timedelta(seconds=2), expires_at=NOW + timedelta(minutes=20),
                working_dates=("2026-11-02",), calendar_version="calendar-1",
            ),
        )
        return self.coordinator.create_preview(self.actor, draft)

    def test_delivered_preview_and_verified_callback_approve_exact_batch(self):
        results = self.bridge.confirm(self.actor, self.callback)
        self.assertEqual([r.result.status for r in results], ["approved", "approved"])
        self.assertEqual(self.read_calls, [("tenant-a", "view-a")])
        self.assertEqual(
            [self.coordinator.get_intent(self.actor, r.result.intent_id).state for r in results],
            ["queued", "queued"],
        )

    def test_generated_but_not_delivered_preview_is_rejected(self):
        self.delivered = replace(self.delivered, verified=False)
        with self.assertRaisesRegex(FollowupError, "preview_delivery_not_verified"):
            self.bridge.confirm(self.actor, self.callback)

    def test_truthy_string_does_not_prove_delivery(self):
        self.delivered = replace(self.delivered, verified="false")
        with self.assertRaisesRegex(FollowupError, "preview_delivery_not_verified"):
            self.bridge.confirm(self.actor, self.callback)

    def test_view_or_edit_action_cannot_become_send_approval(self):
        for action in ("view", "edit", "", "approve_all_future"):
            with self.subTest(action=action):
                with self.assertRaisesRegex(FollowupError, "callback_is_not_send_confirmation"):
                    self.bridge.confirm(self.actor, replace(self.callback, action=action))

    def test_clock_tolerance_does_not_extend_preview_validity(self):
        self.delivered = replace(self.delivered, valid_until=NOW + timedelta(seconds=5))
        with self.assertRaisesRegex(FollowupError, "preview_or_callback_time_invalid"):
            self.bridge.confirm(self.actor, replace(self.callback, occurred_at=NOW + timedelta(seconds=10)))

    def test_missing_actual_readback_record_is_rejected(self):
        self.delivered = replace(self.delivered, source_record_id="")
        with self.assertRaisesRegex(FollowupError, "preview_delivery_not_verified"):
            self.bridge.confirm(self.actor, self.callback)

    def test_wrong_callback_owner_is_rejected(self):
        wrong = replace(self.callback, actor_id="other-user")
        with self.assertRaisesRegex(FollowupError, "callback_actor_scope_mismatch"):
            self.bridge.confirm(self.actor, wrong)
        self.assertEqual(self.read_calls, [])

    def test_wrong_callback_tenant_is_rejected(self):
        wrong = replace(self.callback, tenant_id="other-tenant")
        with self.assertRaisesRegex(FollowupError, "callback_actor_scope_mismatch"):
            self.bridge.confirm(self.actor, wrong)

    def test_wrong_callback_app_is_rejected(self):
        wrong = replace(self.callback, app_id="another-app")
        with self.assertRaisesRegex(FollowupError, "callback_actor_scope_mismatch"):
            self.bridge.confirm(self.actor, wrong)

    def test_callback_must_have_host_verified_event_id(self):
        with self.assertRaisesRegex(FollowupError, "callback_actor_scope_mismatch"):
            self.bridge.confirm(self.actor, replace(self.callback, event_id=""))

    def test_wrong_preview_chat_is_rejected(self):
        wrong = replace(self.callback, chat_id="other-chat")
        with self.assertRaisesRegex(FollowupError, "callback_preview_binding_mismatch"):
            self.bridge.confirm(self.actor, wrong)

    def test_wrong_preview_message_is_rejected(self):
        wrong = replace(self.callback, source_message_id="other-message")
        with self.assertRaisesRegex(FollowupError, "callback_preview_binding_mismatch"):
            self.bridge.confirm(self.actor, wrong)

    def test_wrong_view_id_is_rejected(self):
        wrong = replace(self.callback, view_id="other-view")
        with self.assertRaisesRegex(FollowupError, "callback_preview_binding_mismatch"):
            self.bridge.confirm(self.actor, wrong)

    def test_delivered_record_must_match_owner_and_tenant(self):
        for field, value in (("owner_id", "other-owner"), ("tenant_id", "other-tenant")):
            original = self.delivered
            self.delivered = replace(original, **{field: value})
            with self.subTest(field=field):
                with self.assertRaisesRegex(FollowupError, "callback_preview_binding_mismatch"):
                    self.bridge.confirm(self.actor, self.callback)
            self.delivered = original

    def test_old_manifest_is_rejected(self):
        stale = replace(self.callback, manifest_hash="old-manifest")
        with self.assertRaisesRegex(FollowupError, "displayed_manifest_changed"):
            self.bridge.confirm(self.actor, stale)

    def test_option_not_shown_in_preview_cannot_be_selected(self):
        not_shown = self.make_preview("c")
        wrong = replace(self.callback, selected_preview_ids=(not_shown.preview_id,))
        with self.assertRaisesRegex(FollowupError, "selection_not_in_displayed_preview"):
            self.bridge.confirm(self.actor, wrong)

    def test_selected_subset_only_approves_that_subset(self):
        selected = replace(self.callback, selected_preview_ids=(self.previews[1].preview_id,))
        results = self.bridge.confirm(self.actor, selected)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].preview_id, self.previews[1].preview_id)
        first = self.previews[0]
        independently_approved = self.coordinator.approve(self.actor, first.preview_id, first.token, first.content_hash)
        self.assertEqual(independently_approved.status, "approved")

    def test_empty_and_duplicate_selections_rejected(self):
        for selected in ((), (self.previews[0].preview_id, self.previews[0].preview_id)):
            with self.subTest(selected=selected):
                with self.assertRaisesRegex(FollowupError, "selection_not_in_displayed_preview"):
                    self.bridge.confirm(self.actor, replace(self.callback, selected_preview_ids=selected))

    def test_callback_before_preview_delivery_rejected(self):
        early = replace(self.callback, occurred_at=NOW - timedelta(seconds=2))
        with self.assertRaisesRegex(FollowupError, "preview_or_callback_time_invalid"):
            self.bridge.confirm(self.actor, early)

    def test_callback_too_far_in_future_rejected(self):
        future = replace(self.callback, occurred_at=NOW + timedelta(seconds=31))
        with self.assertRaisesRegex(FollowupError, "preview_or_callback_time_invalid"):
            self.bridge.confirm(self.actor, future)

    def test_expired_delivered_preview_rejected(self):
        self.now += timedelta(minutes=6)
        with self.assertRaisesRegex(FollowupError, "preview_or_callback_time_invalid"):
            self.bridge.confirm(self.actor, self.callback)

    def test_naive_time_is_rejected(self):
        self.delivered = replace(self.delivered, delivered_at=NOW.replace(tzinfo=None))
        with self.assertRaisesRegex(FollowupError, "preview_delivery_not_verified"):
            self.bridge.confirm(self.actor, self.callback)

    def test_empty_or_duplicate_preview_rows_rejected(self):
        original = self.delivered
        for rows in ((), (original.rows[0], original.rows[0])):
            self.delivered = replace(original, rows=rows)
            with self.subTest(rows=rows):
                with self.assertRaisesRegex(FollowupError, "preview_rows_invalid"):
                    self.bridge.confirm(self.actor, self.callback)

    def test_callback_replay_does_not_create_a_second_intent(self):
        first = self.bridge.confirm(self.actor, self.callback)
        replay = self.bridge.confirm(self.actor, self.callback)
        self.assertEqual([r.result.intent_id for r in first], [r.result.intent_id for r in replay])
        self.assertEqual([r.result.status for r in replay], ["replay", "replay"])

    def test_two_rows_one_recipient_failure_reports_partial_success(self):
        self.denied_recipient = "recipient-b"
        results = self.bridge.confirm(self.actor, self.callback)
        self.assertEqual(results[0].result.status, "approved")
        self.assertIsNone(results[0].error)
        self.assertIsNone(results[1].result)
        self.assertEqual(results[1].error, "recipient_blocked")

    def test_expired_actual_actor_not_replaced_by_callback_identity(self):
        actor = replace(self.actor, expires_at=NOW - timedelta(seconds=1))
        with self.assertRaisesRegex(FollowupError, "actor_expired"):
            self.bridge.confirm(actor, self.callback)


if __name__ == "__main__":
    unittest.main()

