"""Cross-module synthetic scenarios: no real network, credentials or accounts."""

from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from am_followup.bridges import EvidenceBridge, LiveAttestation
from am_followup.evidence import (
    CoverageKey, EvidenceLedger, FactProposal, QuoteSpan, ReadResult,
    SourceEvidence, TaskSeed,
)
from am_followup.followup import (
    Actor, Draft, FollowupCoordinator, FollowupError, SendOutcome, SendWindow, Target,
)
from am_followup.rendering import DisclosedFact, DraftSelection, compose
from am_followup.transport_contract import (
    NormalizedMessage, PinnedRecipientGate, RecipientPin, SendRecordBinding,
    envelope, exact_readback,
)


class SyntheticProcessCrash(BaseException):
    """Simulate a killed worker, not a recoverable provider exception."""


class FakeExistingAMSender:
    """Only a fake provider call; every admission/readback uses production contracts."""

    def __init__(self, environment, mode="confirmed"):
        self.env = environment
        self.mode = mode
        self.calls = 0
        self.requests = []
        self.envelopes = []
        self.readbacks = []
        self.bindings = []
        self.messages = []

    def dispatch(self, request, before_send):
        pin = self.env.recipient_gate.pin(request.tenant_id, request.draft.target, self.env.now)
        wire = envelope(request, pin)
        before_send()
        self.calls += 1
        self.requests.append(request)
        self.envelopes.append(wire)
        binding = SendRecordBinding(request.request_uuid, "am_demo_action_" + str(self.calls), "om_demo_" + str(self.calls))
        message = NormalizedMessage(request.tenant_id, binding.response_message_id, pin.exact_chat_id,
                                    pin.bot_open_id, "app", False, request.draft.body,
                                    request.draft.target.mention_ids, "readback_demo_" + str(self.calls), self.env.now)
        if self.mode == "wrong_sender":
            message = replace(message, sender_id="ou_some_other_app")
        elif self.mode == "wrong_message_id":
            message = replace(message, message_id="om_unrelated_same_text")
        readback = exact_readback(request, pin, binding, message)
        self.bindings.append(binding)
        self.messages.append(message)
        self.readbacks.append(readback)
        if self.mode == "crash":
            raise SyntheticProcessCrash()
        if self.mode == "timeout":
            return SendOutcome("unknown", external_action_id=binding.external_action_id,
                               reason="synthetic_timeout_after_provider_acceptance")
        return SendOutcome("confirmed", binding.external_action_id, binding.response_message_id, readback)


class Environment:
    tenant = "tenant_demo"
    owner = "ou_owner_demo"
    engineer = "ou_engineer_demo"
    group = "oc_project_demo"
    task_id = "task_confirm_start_demo"
    policy = "disclosure_policy_v1"

    def __init__(self, directory):
        self.now = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.path = str(Path(directory) / "integration.sqlite3")
        self.key = CoverageKey("authorized_scanner", "message", self.group)
        self.required = [self.key]
        self.live_mode = "valid"
        self.pin_mode = "valid"
        self.live_calls = 0
        self.ledger = EvidenceLedger(self.path, self.tenant)
        self.seed = SourceEvidence(self.tenant, "synthetic_lark", "message", self.group, "om_instruction_demo",
                                   "v1", "请跟进演示项目的测试启动，负责人是演示工程师。",
                                   self.now.isoformat(), self.now.isoformat(), "acl_v1",
                                   ("user:" + self.owner, "user:" + self.engineer, "chat:" + self.group),
                                   version_seq=1)
        self.ledger.ingest_batch([self.seed], ReadResult(self.key, "success", self.now.isoformat(),
                                                      self.now.isoformat(), 0, cursor="cursor_demo_1", cursor_seq=1))
        self.ledger.create_task(TaskSeed(self.task_id, "project_demo:test_start", "确认是否已经开测",
                                        (self.seed.ref,), "project_demo", self.engineer,
                                        origin="user_direct", business_timezone="Asia/Shanghai"))
        self.bridge = EvidenceBridge(self.path, self.ledger, required_coverage=lambda task: tuple(self.required),
                                     live_attestor=self.attest, clock=lambda: self.now)
        self.recipient_gate = PinnedRecipientGate("app_demo", self.resolve)
        self.coordinator = self.new_coordinator()
        self.actor = Actor(self.tenant, self.owner, "session_demo", self.now + timedelta(minutes=10))

    def new_coordinator(self):
        return FollowupCoordinator(self.path, signing_key=b"synthetic-test-key-do-not-use-in-prod" * 2,
                                   owner_ids={self.tenant: self.owner}, evidence_gate=self.bridge,
                                   recipient_gate=self.recipient_gate, clock=lambda: self.now)

    def attest(self, tenant, owner, snapshot, audience, body_hash):
        self.live_calls += 1
        checked = self.now
        expiry = self.now + timedelta(seconds=30)
        policy = self.policy
        if self.live_mode == "old":
            checked -= timedelta(minutes=2)
        elif self.live_mode == "expired":
            expiry = self.now - timedelta(seconds=1)
        elif self.live_mode == "wrong_body":
            body_hash = "0" * 64
        elif self.live_mode == "policy_changed":
            policy = "disclosure_policy_v2"
        return LiveAttestation(tenant, owner, snapshot.digest, audience, body_hash,
                               checked, expiry, True, policy)

    def resolve(self, tenant, target, now):
        pin = RecipientPin(tenant, "app_demo", target.kind, target.target_id,
                           target.target_id if target.kind == "group" else "oc_private_demo",
                           target.directory_version, now + timedelta(minutes=5), target.attention_ids,
                           "ou_am_bot_demo", True, True, True)
        if self.pin_mode == "wrong_tenant":
            return replace(pin, tenant_id="tenant_other")
        if self.pin_mode == "wrong_chat":
            return replace(pin, exact_chat_id="oc_other_group")
        if self.pin_mode == "wrong_attention":
            return replace(pin, attention_ids=("ou_other_engineer",))
        return pin

    def target(self, kind="group"):
        identifier = self.group if kind == "group" else self.engineer
        return Target(kind, identifier, (self.engineer,), (self.engineer,) if kind == "group" else (),
                      "directory_v1", self.now + timedelta(minutes=10))

    def draft(self, *, kind="group", producer="am", trigger="verified_due_window_demo", body=None, bridge=None):
        target = self.target(kind)
        audience = ("chat:" if kind == "group" else "user:") + target.target_id
        body = body or compose("演示项目", "测试启动", audience, "confirm_start").body
        evidence = (bridge or self.bridge).capture(self.task_id, audience, body,
                                                   disclosure_policy_revision=self.policy)
        episode = self.coordinator.register_episode(self.tenant, self.task_id, "request_update", trigger)
        window = SendWindow(self.now - timedelta(seconds=1), self.now + timedelta(minutes=10),
                            ("2026-11-02",), calendar_version="calendar_demo_v1")
        return Draft(self.task_id, "request_update", episode, body, target, evidence, window, producer)

    def approve(self, draft=None):
        preview = self.coordinator.create_preview(self.actor, draft or self.draft())
        result = self.coordinator.approve(self.actor, preview.preview_id, preview.token, preview.content_hash)
        return preview, result

    def accept(self, field, value, text, *, supersedes=(), response_to=None):
        counter = self.ledger.task_view(self.task_id)["version"]
        source = replace(self.seed, native_id=f"om_fact_demo_{counter}", text=text)
        self.ledger.ingest(source)
        proposal = FactProposal(self.task_id, field, value,
                                (QuoteSpan(source.ref, 0, len(text), text),), self.now.isoformat(),
                                supersedes=tuple(supersedes), response_to=response_to)
        claim = self.ledger.propose(proposal)
        self.ledger.accept_claim(claim, "trusted_demo_reviewer",
                                 self.ledger.task_view(self.task_id)["version"], reviewed_at=self.now.isoformat())
        return claim, source


class CrossModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = Environment(self.temp.name)

    def test_string_permissions_cannot_authorize_live_evidence(self):
        attestor = self.env.bridge.live_attestor
        self.env.bridge.live_attestor = lambda *args: replace(attestor(*args), allowed="false")
        with self.assertRaises(FollowupError):
            self.env.approve()

    def test_string_permissions_cannot_authorize_recipient(self):
        resolver = self.env.recipient_gate.resolve
        self.env.recipient_gate.resolve = lambda *args: replace(resolver(*args), members_verified="false")
        with self.assertRaises(FollowupError):
            self.env.approve()

    def dispatch(self, result, sender=None):
        sender = sender or FakeExistingAMSender(self.env)
        state = self.env.coordinator.dispatch_once(self.env.tenant, result.intent_id, sender, worker_id="original_am_consumer_demo")
        return state, sender

    def test_one_approval_replay_and_dispatch_create_one_exact_readback(self):
        preview, approved = self.env.approve()
        state, sender = self.dispatch(approved)
        replay = self.env.coordinator.approve(self.env.actor, preview.preview_id, preview.token, preview.content_hash)
        second, _ = self.dispatch(approved, sender)
        self.assertEqual(state.state, "confirmed")
        self.assertEqual(second.state, "confirmed")
        self.assertEqual(replay.intent_id, approved.intent_id)
        self.assertEqual(sender.calls, 1)
        self.assertEqual(sender.readbacks[0].message_id, state.message_id)
        post = json.loads(sender.envelopes[0].content)
        self.assertEqual(post["zh_cn"]["content"][0], [{"tag": "at", "user_id": self.env.engineer}])

    def test_restricted_source_cannot_be_disclosed_to_another_group(self):
        normal = self.env.draft()
        other = replace(normal.target, target_id="oc_unapproved_group")
        other_evidence = self.env.bridge.capture(self.env.task_id, "chat:oc_unapproved_group", normal.body,
                                                 disclosure_policy_revision=self.env.policy)
        with self.assertRaises(FollowupError) as caught:
            self.env.coordinator.create_preview(self.env.actor, replace(normal, target=other, evidence=other_evidence))
        self.assertEqual(caught.exception.code, "evidence_blocked")
        self.assertIn("audience_not_allowed", caught.exception.detail)

    def test_source_edit_after_approval_stops_before_fake_network(self):
        _, approved = self.env.approve()
        self.env.ledger.ingest(replace(self.env.seed, version="v2", version_seq=2, text="项目执行安排有变化，需要核实。"))
        state, sender = self.dispatch(approved)
        self.assertEqual(state.state, "blocked")
        self.assertEqual(sender.calls, 0)

    def test_acl_change_after_approval_stops_before_fake_network(self):
        _, approved = self.env.approve()
        self.env.ledger.ingest(replace(self.env.seed, version="v2", version_seq=2,
                                      acl_version="acl_v2", audience_keys=("user:" + self.env.owner,)))
        state, sender = self.dispatch(approved)
        self.assertEqual(state.state, "blocked")
        self.assertEqual(sender.calls, 0)

    def test_failed_coverage_after_approval_stops_before_fake_network(self):
        _, approved = self.env.approve()
        self.env.ledger.record_read(ReadResult(self.env.key, "failed", self.env.now.isoformat(),
                                              self.env.now.isoformat(), 1, reason="synthetic_failure"))
        state, sender = self.dispatch(approved)
        self.assertEqual(state.state, "blocked")
        self.assertEqual(sender.calls, 0)

    def test_snapshot_omitting_server_coverage_is_rejected(self):
        incomplete_bridge = EvidenceBridge(self.env.path, self.env.ledger, required_coverage=lambda _: (),
                                           live_attestor=self.env.attest, clock=lambda: self.env.now)
        draft = self.env.draft(bridge=incomplete_bridge)
        with self.assertRaises(FollowupError) as caught:
            self.env.coordinator.create_preview(self.env.actor, draft)
        self.assertEqual(caught.exception.detail, "required_coverage_changed")

    def test_server_coverage_addition_invalidates_existing_approval(self):
        _, approved = self.env.approve()
        self.env.required.append(CoverageKey("approval_reader", "approval", "approval_demo"))
        state, sender = self.dispatch(approved)
        self.assertEqual(state.state, "blocked")
        self.assertEqual(sender.calls, 0)

    def test_no_live_attestor_cannot_authorize_from_local_snapshot(self):
        draft = self.env.draft()
        self.env.bridge.live_attestor = None
        with self.assertRaises(FollowupError) as caught:
            self.env.coordinator.create_preview(self.env.actor, draft)
        self.assertEqual(caught.exception.detail, "evidence_or_live_policy_unavailable")

    def test_stale_expired_or_wrong_body_attestation_blocks_preview(self):
        for mode in ("old", "expired", "wrong_body"):
            with self.subTest(mode=mode):
                self.env.live_mode = mode
                with self.assertRaises(FollowupError):
                    self.env.coordinator.create_preview(self.env.actor, self.env.draft())

    def test_disclosure_policy_changed_even_if_live_allowed_is_true(self):
        _, approved = self.env.approve()
        self.env.live_mode = "policy_changed"
        state, sender = self.dispatch(approved)
        self.assertEqual(state.state, "blocked")
        self.assertEqual(sender.calls, 0)

    def test_body_changed_after_capture_cannot_reuse_evidence_binding(self):
        draft = self.env.draft()
        with self.assertRaises(FollowupError) as caught:
            self.env.coordinator.create_preview(self.env.actor, replace(draft, body=draft.body + "另加未核实内容。"))
        self.assertEqual(caught.exception.detail, "disclosure_body_or_audience_changed")

    def test_wrong_current_recipient_pin_stops_before_fake_network(self):
        for mode in ("wrong_tenant", "wrong_chat", "wrong_attention"):
            with self.subTest(mode=mode):
                self.env.pin_mode = "valid"
                _, approved = self.env.approve(self.env.draft(trigger="pin_test_" + mode))
                self.env.pin_mode = mode
                state, sender = self.dispatch(approved)
                self.assertEqual(state.state, "blocked")
                self.assertEqual(sender.calls, 0)

    def test_wrong_message_id_or_sender_cannot_fake_confirmed(self):
        for mode in ("wrong_sender", "wrong_message_id"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as directory:
                    env = Environment(directory)
                    _, approved = env.approve()
                    sender = FakeExistingAMSender(env, mode)
                    state = env.coordinator.dispatch_once(env.tenant, approved.intent_id, sender, worker_id="worker_demo")
                    self.assertEqual(state.state, "unknown")
                    self.assertIsNone(sender.readbacks[0])
                    env.coordinator.dispatch_once(env.tenant, approved.intent_id, sender, worker_id="worker_demo")
                    self.assertEqual(sender.calls, 1)

    def test_wrong_pin_cannot_construct_exact_readback(self):
        _, approved = self.env.approve()
        _, sender = self.dispatch(approved)
        request = sender.requests[0]
        pin = self.env.recipient_gate.pin(self.env.tenant, request.draft.target, self.env.now)
        wrong = replace(pin, target_id="oc_other_group")
        self.assertIsNone(exact_readback(request, wrong, sender.bindings[0], sender.messages[0]))

    def test_two_producers_group_and_dm_share_attention_reservation(self):
        group_preview, group = self.env.approve(self.env.draft(producer="am"))
        dm_preview, dm = self.env.approve(self.env.draft(kind="recipient_p2p", producer="personal_assistant"))
        self.assertEqual(dm.status, "already_reserved")
        self.assertEqual(dm.intent_id, group.intent_id)
        state, sender = self.dispatch(group)
        self.dispatch(dm, sender)
        self.assertEqual(state.state, "confirmed")
        self.assertEqual(sender.calls, 1)
        self.assertNotEqual(group_preview.preview_id, dm_preview.preview_id)
        self.assertEqual(sender.envelopes[0].receive_id_type, "chat_id")

    def test_p2p_uses_open_id_and_exact_chat_readback(self):
        _, approved = self.env.approve(self.env.draft(kind="recipient_p2p"))
        state, sender = self.dispatch(approved)
        self.assertEqual(state.state, "confirmed")
        self.assertEqual(sender.envelopes[0].receive_id_type, "open_id")
        self.assertEqual(sender.envelopes[0].receive_id, self.env.engineer)
        self.assertEqual(sender.messages[0].chat_id, "oc_private_demo")
        self.assertEqual(sender.messages[0].mention_ids, ())

    def test_plan_delivered_and_acknowledged_still_asks_if_started(self):
        plan_claim, plan_source = self.env.accept("plan_delivery", "delivered", "测试方案已经发送。")
        pending, _ = self.env.accept("response", "pending", "请确认已收到测试方案。")
        self.env.accept("response", "acknowledged", "收到。", supersedes=(pending,), response_to=pending)
        audience = "chat:" + self.env.group
        fact = DisclosedFact(plan_claim, "测试方案已经发送", plan_source.source_key, plan_source.version,
                             self.env.policy, (audience,))
        composed = compose("演示项目", "测试启动", audience, "confirm_start", (fact,),
                           DraftSelection("confirm_start", (plan_claim,)))
        _, approved = self.env.approve(self.env.draft(body=composed.body))
        state, sender = self.dispatch(approved)
        task = self.env.ledger.task_view(self.env.task_id)
        self.assertEqual(state.state, "confirmed")
        self.assertIn("是否已经开始", sender.requests[0].draft.body)
        self.assertEqual(task["response"], "acknowledged")
        self.assertEqual(task["execution"], "unknown")
        self.assertEqual(task["legacy_action_status"], "waiting")
        self.assertFalse(task["business_completed"])

    def test_process_crash_after_provider_acceptance_stays_unknown_on_restart(self):
        _, approved = self.env.approve()
        sender = FakeExistingAMSender(self.env, "crash")
        with self.assertRaises(SyntheticProcessCrash):
            self.dispatch(approved, sender)
        self.env.coordinator = self.env.new_coordinator()
        self.assertEqual(self.env.coordinator.recover_in_flight(self.env.tenant, "original_am_consumer_demo"), 1)
        recovered = self.env.coordinator.get_intent(self.env.actor, approved.intent_id)
        self.assertEqual(recovered.state, "unknown")
        self.dispatch(approved, sender)
        self.assertEqual(sender.calls, 1)
        final = self.env.coordinator.reconcile(self.env.tenant, approved.intent_id, sender.readbacks[0])
        self.assertEqual(final.state, "confirmed")
        self.assertEqual(sender.calls, 1)


if __name__ == "__main__":
    unittest.main()
