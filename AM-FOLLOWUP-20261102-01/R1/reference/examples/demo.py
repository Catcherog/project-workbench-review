"""Run with PYTHONPATH=src python3 examples/demo.py.

All data, identity checks, live attestations, provider calls and readbacks below
are synthetic. This demonstrates module wiring and cannot send a real message.
"""

from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from am_followup.bridges import EvidenceBridge, LiveAttestation
from am_followup.evidence import (
    CoverageKey, EvidenceLedger, FactProposal, QuoteSpan, ReadResult,
    SourceEvidence, TaskSeed,
)
from am_followup.followup import Actor, Draft, FollowupCoordinator, SendOutcome, SendWindow, Target
from am_followup.rendering import DisclosedFact, DraftSelection, compose, describe_receipt
from am_followup.transport_contract import (
    NormalizedMessage, PinnedRecipientGate, RecipientPin, SendRecordBinding,
    envelope, exact_readback,
)


def run_demo() -> dict:
    now = datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    tenant, owner, engineer, group = "tenant_demo", "ou_owner_demo", "ou_engineer_demo", "oc_project_demo"
    task_id, disclosure_policy = "task_start_demo", "disclosure_policy_v1"
    clock = lambda: now
    with tempfile.TemporaryDirectory(prefix="am_followup_demo_") as directory:
        path = str(Path(directory) / "isolated.sqlite3")
        ledger = EvidenceLedger(path, tenant)
        coverage = CoverageKey("authorized_scanner_demo", "message", group)
        instruction = SourceEvidence(
            tenant, "synthetic_lark", "message", group, "om_instruction_demo", "v1",
            "请跟进演示项目的测试启动，负责人为演示工程师。",
            now.isoformat(), now.isoformat(), "acl_demo_v1",
            ("chat:" + group, "user:" + owner, "user:" + engineer), version_seq=1,
        )
        ledger.ingest_batch([instruction], ReadResult(coverage, "success", now.isoformat(),
                                                     now.isoformat(), 0, cursor="cursor_demo_1", cursor_seq=1))
        ledger.create_task(TaskSeed(task_id, "project_demo:test_start", "确认是否已开测",
                                    (instruction.ref,), "project_demo", engineer,
                                    origin="user_direct", business_timezone="Asia/Shanghai"))

        def verified_fixture_fact(field, value, native_id, text, *, supersedes=(), response_to=None):
            source = replace(instruction, native_id=native_id, text=text)
            ledger.ingest(source)
            proposal = FactProposal(task_id, field, value,
                                    (QuoteSpan(source.ref, 0, len(text), text),), now.isoformat(),
                                    supersedes=tuple(supersedes), response_to=response_to)
            claim = ledger.propose(proposal)
            ledger.accept_claim(claim, "trusted_synthetic_reviewer", ledger.task_view(task_id)["version"],
                                reviewed_at=now.isoformat())
            return claim, source

        plan_claim, plan_source = verified_fixture_fact("plan_delivery", "delivered", "om_plan_demo", "测试方案已经发送。")
        pending, _ = verified_fixture_fact("response", "pending", "om_request_demo", "请确认收到方案。")
        verified_fixture_fact("response", "acknowledged", "om_ack_demo", "收到。",
                              supersedes=(pending,), response_to=pending)

        def synthetic_attestor(t, o, snapshot, audience, body_hash):
            # Production replaces this with authorized current-source/ACL checks.
            return LiveAttestation(t, o, snapshot.digest, audience, body_hash, now,
                                   now + timedelta(seconds=30), True, disclosure_policy)

        bridge = EvidenceBridge(path, ledger, required_coverage=lambda _: (coverage,),
                                live_attestor=synthetic_attestor, clock=clock)

        def synthetic_resolver(t, target, current_time):
            return RecipientPin(t, "app_demo", target.kind, target.target_id, group,
                                "directory_demo_v1", current_time + timedelta(minutes=5),
                                target.attention_ids, "ou_am_bot_demo", True, True, True)

        recipients = PinnedRecipientGate("app_demo", synthetic_resolver)
        coordinator = FollowupCoordinator(
            path, signing_key=b"synthetic-demo-key-do-not-deploy-0000000000",
            owner_ids={tenant: owner}, evidence_gate=bridge, recipient_gate=recipients, clock=clock,
        )
        audience = "chat:" + group
        fact = DisclosedFact(plan_claim, "测试方案已经发送", plan_source.source_key, plan_source.version,
                             disclosure_policy, (audience,))
        composed = compose("演示项目", "测试启动", audience, "confirm_start", (fact,),
                           DraftSelection("confirm_start", (plan_claim,)))
        snapshot = bridge.capture(task_id, audience, composed.body, disclosure_policy_revision=disclosure_policy)
        target = Target("group", group, (engineer,), (engineer,), "directory_demo_v1", now + timedelta(minutes=10))
        episode = coordinator.register_episode(tenant, task_id, "request_update", "verified_reminder_window_demo")
        draft = Draft(task_id, "request_update", episode, composed.body, target, snapshot,
                      SendWindow(now - timedelta(seconds=1), now + timedelta(minutes=10),
                                 ("2026-11-02",), calendar_version="calendar_demo_v1"))
        actor = Actor(tenant, owner, "authenticated_demo_session", now + timedelta(minutes=10))
        preview = coordinator.create_preview(actor, draft)
        approved = coordinator.approve(actor, preview.preview_id, preview.token, preview.content_hash)

        class SyntheticExistingAMSender:
            calls = 0

            def dispatch(self, request, before_send):
                pin = recipients.pin(tenant, request.draft.target, now)
                wire = envelope(request, pin)
                before_send()
                self.calls += 1
                assert wire.receive_id == group
                binding = SendRecordBinding(request.request_uuid, "am_action_demo", "om_sent_demo")
                message = NormalizedMessage(tenant, "om_sent_demo", group, "ou_am_bot_demo", "app", False,
                                            request.draft.body, (engineer,), "readback_record_demo", now)
                readback = exact_readback(request, pin, binding, message)
                return SendOutcome("confirmed", binding.external_action_id, binding.response_message_id, readback)

        sender = SyntheticExistingAMSender()
        delivered = coordinator.dispatch_once(tenant, approved.intent_id, sender, worker_id="original_consumer_demo")
        coordinator.approve(actor, preview.preview_id, preview.token, preview.content_hash)
        coordinator.dispatch_once(tenant, approved.intent_id, sender, worker_id="original_consumer_demo")
        task = ledger.task_view(task_id)
        return {
            "mode": "synthetic_only_no_network",
            "facts": {"plan_delivery": task["fields"]["plan_delivery"]["values"][0],
                      "response": task["response"], "execution": task["execution"],
                      "business_completed": task["business_completed"]},
            "preview": {"scope": preview.approval_scope, "body": draft.body},
            "delivery": {"state": delivered.state, "mock_provider_calls": sender.calls,
                         "duplicate_click_caused_extra_send": sender.calls != 1,
                         "receipt": describe_receipt(delivered.state, delivered.message_id)},
            "real_messages_sent": 0,
        }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
