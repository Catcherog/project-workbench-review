"""Real native AM SQLite/coordinator/scheduler, synthetic platform ports only."""
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import uuid

import pytest

HERE = Path(__file__).resolve().parents[1]
AM_ROOT = Path(os.environ["LEDGER_AM_SOURCE_ROOT"]).resolve() if os.environ.get("LEDGER_AM_SOURCE_ROOT") else None
HOST_ROOT = AM_ROOT / "local-qwen3.8/feishu-bridge" if AM_ROOT else HERE
sys.path.insert(0, str(HOST_ROOT))
from am_workbench_adapter import WorkbenchAdapter, signature, install_from_env, WebBoundaryError

# Native acceptance uses the actual merged host, never the bundled old snapshot.
host_file = HOST_ROOT / "am_followup_host.py" if AM_ROOT else HERE / "patch/am_followup_host.py"
spec = importlib.util.spec_from_file_location("am_followup_host", host_file)
module = importlib.util.module_from_spec(spec)
sys.modules["am_followup_host"] = module
spec.loader.exec_module(module)

from test_followup_native import native
from test_am_self_fix1 import service, am_rig, base_rig
from am_info_sync.runtime import InformationService
from am_info_sync.catalog import EntityCatalog
from am_info_sync.models import Source, Observation, Principal

KEY = b"offline-test-fixture-only-0000000000000000"


@pytest.fixture(autouse=True)
def isolated_web_configuration(monkeypatch):
    monkeypatch.delenv("AM_WORKBENCH_KEY_FILE", raising=False)
    monkeypatch.delenv("AM_WORKBENCH_WORKSPACE_ID", raising=False)


@pytest.fixture
def web(native, monkeypatch):
    n = native
    monkeypatch.delenv("AM_WORKBENCH_KEY_FILE", raising=False)
    n.am.information.service = InformationService(n.reader)
    n.catalog = EntityCatalog(n.reader)
    n.catalog.register(n.item["project_ref"], "合成项目")
    n.web = WorkbenchAdapter(n.f, KEY)
    n.f.workbench = n.web
    return n


def envelope(n, method, params=None, *, ident=None, session=None):
    now = int(n.clock() * 1000)
    value = {"schema": "am-workbench.rpc/v1", "audience": "am-ledger-workbench",
        "requestId": ident or str(uuid.uuid4()), "method": method,
        "issuedAtMs": now, "expiresAtMs": now + 60000,
        "session": {"id": "test-session-0001", "userId": n.am.owner,
            "tenantId": n.f.tenant, "workspaceId": n.f.tenant,
            "projectIds": [n.item["project_ref"]], "expiresAtMs": now + 3600000,
            "scopes": ["ledger:read", "am:prepare", "am:approve", "review:resolve", "reminder:manage"]},
        "params": params or {}}
    if session:
        value["session"].update(session)
    value["signature"] = signature(KEY, value)
    return value


def call(n, method, params=None, **kwargs):
    value = envelope(n, method, params, **kwargs)
    result = n.web.handle(value)
    assert result["signature"] == signature(KEY, {k: v for k, v in result.items() if k != "signature"})
    return result


def prepare(n, body=None):
    sem = n.s.rows("SELECT version FROM action_semantics WHERE item_id=?", (n.item["id"],))
    item = n.am.items.get(n.item["id"])
    params = {"itemId": item["id"], "expectedItemVersion": item["version"],
              "expectedSemanticVersion": sem[0]["version"] if sem else 0}
    if body is not None:
        params["body"] = body
    result = call(n, "prepare", params)
    assert result["ok"], result
    return result["data"]


def presented(n, p):
    result = call(n, "present", {"previewId": p["previewId"], "displayHash": p["displayHash"]})
    assert result["ok"], result
    return result["data"]


def approve(n, p, shown):
    return call(n, "approve", {"previewId": p["previewId"], "displayHash": p["displayHash"],
                              "presentationId": shown["presentationId"]})


def test_web_admission_uses_original_scheduler_and_does_not_close_business(web):
    n = web
    p = prepare(n, "请核对本轮实际开测时间。")
    assert p["body"] == "请核对本轮实际开测时间。" and "token" not in p
    assert not n.calls and not n.s.rows("SELECT * FROM reminder_occurrences")
    shown = presented(n, p)
    assert not n.calls and not n.s.rows("SELECT * FROM followup_intents")
    first = approve(n, p, shown)
    assert first["ok"] and first["data"]["state"] == "queued"
    assert not n.calls
    second = approve(n, p, shown)
    assert second["ok"] and second["data"]["requestId"] == first["data"]["requestId"]
    assert len(n.s.rows("SELECT * FROM reminder_occurrences")) == 1
    n.am.scheduler.dispatch()
    n.am.scheduler.dispatch()
    assert len(n.calls) == 1
    receipt = call(n, "status", {"requestId": first["data"]["requestId"]})
    assert receipt["ok"] and receipt["data"]["state"] == "sent_confirmed"
    assert receipt["data"]["businessCompleted"] is False
    assert n.am.items.get(n.item["id"])["state"] == "waiting"


@pytest.mark.parametrize("change", ["no_presentation", "wrong_hash", "wrong_session"])
def test_unpresented_or_changed_web_view_cannot_approve(web, change):
    n = web; p = prepare(n); shown = presented(n, p)
    params = {"previewId": p["previewId"], "displayHash": p["displayHash"],
              "presentationId": shown["presentationId"]}
    session = None
    if change == "no_presentation": params["presentationId"] = "missing-presentation"
    if change == "wrong_hash": params["displayHash"] = "0" * 64
    if change == "wrong_session": session = {"id": "different-session"}
    result = call(n, "approve", params, session=session)
    assert not result["ok"]
    assert not n.calls and not n.s.rows("SELECT * FROM followup_intents")


@pytest.mark.parametrize("session", [
    {"userId": "ou_someone_else"}, {"tenantId": "other_tenant"},
    {"workspaceId": "other_workspace"}, {"projectIds": []}, {"scopes": ["ledger:read"]},
])
def test_native_owner_workspace_project_and_scope_fences(web, session):
    n = web
    result = call(n, "prepare", {"itemId": n.item["id"], "expectedItemVersion": 1, "expectedSemanticVersion": 0}, session=session)
    assert not result["ok"] and not n.s.rows("SELECT * FROM followup_previews")


def test_signature_and_replay_fences(web):
    n = web; request = envelope(n, "snapshot")
    request["signature"] = "0" * 64
    assert n.web.handle(request)["error"]["code"] == "WEB_SIGNATURE_INVALID"
    p = prepare(n); params = {"previewId": p["previewId"], "displayHash": p["displayHash"]}
    request = envelope(n, "present", params)
    one = n.web.handle(request); two = n.web.handle(request)
    assert one == two and len(n.s.rows("SELECT * FROM wb_presentations")) == 1
    request["params"]["displayHash"] = "0" * 64
    request["signature"] = signature(KEY, {k: v for k, v in request.items() if k != "signature"})
    assert n.web.handle(request)["error"]["code"] == "WEB_REQUEST_ID_REUSED"


def test_source_change_after_presentation_blocks_native_admission(web):
    n = web; p = prepare(n); shown = presented(n, p)
    n.reader.record(replace(n.obs, version="v2", occurred_at_ms=n.obs.occurred_at_ms + 1, text="更新后的依据"), authoritative=True)
    result = approve(n, p, shown)
    assert not result["ok"] and not n.s.rows("SELECT * FROM followup_intents")
    assert not n.calls


def test_source_change_after_approval_blocks_original_scheduler(web):
    n = web; p = prepare(n); result = approve(n, p, presented(n, p))
    assert result["ok"]
    n.reader.record(replace(n.obs, version="v2", occurred_at_ms=n.obs.occurred_at_ms + 1, text="更新后的依据"), authoritative=True)
    n.am.scheduler.dispatch()
    assert not n.calls


def test_revise_invalidates_old_display_and_requires_new_presentation(web):
    n = web; p = prepare(n); shown = presented(n, p)
    result = call(n, "revise", {"previousPreviewId": p["previewId"], "itemId": n.item["id"],
        "expectedItemVersion": 1, "expectedSemanticVersion": 1, "body": "请补充可用台架和明确时间。"})
    assert result["ok"] and result["data"]["contentHash"] != p["contentHash"]
    assert not approve(n, p, shown)["ok"]
    assert not n.s.rows("SELECT * FROM reminder_occurrences")


def test_existing_future_checkpoint_returns_wait_without_preview_or_timer(web):
    n = web
    n.f.bind(n.row, n.item["id"])
    n.s.execute("UPDATE action_items SET next_check=? WHERE id=?", (n.clock() + 86400, n.item["id"]))
    result = prepare(n)
    assert result["kind"] == "wait" and result["nextCheckAt"]
    assert not n.s.rows("SELECT * FROM followup_previews")
    assert not n.s.rows("SELECT * FROM reminder_plans")


def test_missing_native_group_does_not_guess_recipient(web):
    n = web
    n.s.execute("UPDATE action_items SET source='{}' WHERE id=?", (n.item["id"],))
    result = prepare(n)
    assert result["kind"] == "choose_route" and result["assigneeIds"] == ["ou_engineer_a"]
    assert not n.s.rows("SELECT * FROM followup_previews")


def test_unknown_receipt_is_not_success_or_business_completion(web):
    n = web; p = prepare(n); result = approve(n, p, presented(n, p))
    n.fault["send"] = True
    n.am.scheduler.dispatch()
    receipt = call(n, "status", {"requestId": result["data"]["requestId"]})["data"]
    assert receipt["state"] == "unknown" and receipt["mayResend"] is False
    assert receipt["businessCompleted"] is False and len(n.calls) == 1


def test_receipt_remains_bound_to_original_web_session(web):
    n = web; p = prepare(n); result = approve(n, p, presented(n, p))
    receipt = call(n, "status", {"requestId": result["data"]["requestId"]}, session={"id": "another-session"})
    assert not receipt["ok"] and receipt["error"]["code"] == "WEB_RECEIPT_SESSION_MISMATCH"


def test_snapshot_scopes_and_reminder_ack_do_not_change_business(web):
    n = web
    n.s.execute("UPDATE action_items SET state='blocked',deadline='2026-01-01' WHERE id=?", (n.item["id"],))
    raw = call(n, "snapshot")["data"]
    assert len(raw["projects"]) == 1 and raw["reminderCoverage"]["status"] == "complete"
    assert raw["reminders"]
    r = raw["reminders"][0]; before = n.am.items.get(n.item["id"])
    result = call(n, "reminder", {"reminderId": r["id"], "basis": r["basis"], "action": "ack"})
    assert result["ok"] and result["data"]["businessStateChanged"] is False
    assert n.am.items.get(n.item["id"]) == before
    raw = call(n, "snapshot")["data"]
    assert next(x for x in raw["reminders"] if x["id"] == r["id"])["displayState"] == "read"
    assert all(r["result_json"] is None for r in n.s.rows("SELECT result_json FROM wb_rpc_requests WHERE method='snapshot'"))


def outside_subject(n, *, kind="outside", parent=None, owner=None):
    n.catalog.register("outside-team", "部门协同", kind=kind, project_id=parent)
    source = Source("outside-source", "im_chat", "synthetic-outside-chat", n.f.tenant, owner or n.am.owner,
        enabled=True, settings={"subject_ids": ["outside-team"]})
    n.reader.register_source(source)
    return source


def test_registered_outside_items_are_read_through_original_store(web):
    n = web; outside_subject(n)
    n.s.execute("UPDATE action_items SET project_ref=? WHERE id=?", ("outside-team", n.item["id"]))
    result = call(n, "snapshot", session={"projectIds": [n.item["project_ref"], "outside-team"]})
    assert result["ok"], result
    topic = next(p for p in result["data"]["projects"] if p["key"] == "outside-team")
    assert topic["kind"] == "outside" and topic["status"] == "unknown"
    assert [i["id"] for i in result["data"]["items"]] == [n.item["id"]]
    assert n.s.rows("SELECT COUNT(*) AS n FROM action_items")[0]["n"] == 1
    assert not n.calls and not n.s.rows("SELECT * FROM reminder_occurrences")


@pytest.mark.parametrize("missing", ["catalog", "web_scope", "source_scope", "enabled", "permission", "kind", "parent", "conflicting_scope"])
def test_outside_registration_never_creates_permission_or_guesses_attribution(web, missing):
    n = web
    source = outside_subject(n, kind="deliverable" if missing == "kind" else "outside",
        parent=n.item["project_ref"] if missing == "parent" else None,
        owner="another-owner" if missing == "permission" else None)
    if missing == "catalog":
        with n.reader.transaction() as db:
            db.execute("DELETE FROM entity_catalog WHERE subject_id='outside-team'")
    if missing == "source_scope": source = replace(source, settings={})
    if missing == "enabled": source = replace(source, enabled=False)
    if missing == "conflicting_scope": source = replace(source, settings={"subject_ids":["outside-team"], "subject_id":"different"})
    n.reader.register_source(source)
    scope = [n.item["project_ref"]] if missing == "web_scope" else [n.item["project_ref"], "outside-team"]
    result = call(n, "snapshot", session={"projectIds":scope})
    assert result["ok"], result
    assert all(p["key"] != "outside-team" for p in result["data"]["projects"])
    assert "outside-team" not in result["data"]["queries"]


def test_revoking_outside_source_removes_it_from_the_next_read(web):
    n = web; source = outside_subject(n)
    params = {"projectId":"outside-team"}
    session = {"projectIds":["outside-team"]}
    assert call(n, "snapshot", params, session=session)["ok"]
    n.reader.register_source(replace(source, enabled=False))
    result = call(n, "snapshot", params, session=session)
    assert not result["ok"] and result["error"]["code"] == "WEB_PROJECT_NOT_AVAILABLE"


def add_ambiguous(n):
    source = Source("conversation-test", "im_chat", "synthetic-chat", n.f.tenant, n.am.owner,
        enabled=True, settings={"subject_ids": [n.item["project_ref"]]})
    n.reader.register_source(source)
    obs = Observation(source.source_id, "message-test", "rev-one", int(n.clock()*1000), text="评审资料 2026-11-05 给你；是否完成另行核对。")
    n.reader.record(obs)
    n.reader.open_gap(source.source_id, obs.object_id, "extraction", "semantic_coverage_incomplete:subject_binding_ambiguous")
    return source, obs


def test_native_read_ack_preserves_active_snooze_and_original_deadline(web):
    n = web
    n.s.execute("UPDATE action_items SET state='blocked' WHERE id=?", (n.item["id"],))
    before = n.am.items.get(n.item["id"])
    reminder = call(n, "snapshot")["data"]["reminders"][0]
    params = {"reminderId": reminder["id"], "basis": reminder["basis"]}
    until = n.web.now() + 3600000
    assert call(n, "reminder", dict(params, action="snooze", untilMs=until))["ok"]
    assert call(n, "reminder", dict(params, action="ack"))["data"]["untilMs"] == until
    current = next(r for r in call(n, "snapshot")["data"]["reminders"] if r["id"] == reminder["id"])
    assert current["displayState"] == "snoozed"
    assert n.am.items.get(n.item["id"]) == before


def test_attribution_review_uses_original_fact_engine_without_approval(web):
    n = web; add_ambiguous(n)
    review = call(n, "snapshot")["data"]["semanticReviews"][0]
    request = envelope(n, "review")
    request["params"] = {"reviewId": review["id"], "reviewHash": review["reviewHash"],
        "choiceId": n.item["project_ref"], "choice": {"kind": "associate", "projectId": n.item["project_ref"]},
        "evidence": [], "factIds": [], "projectId": None, "requestId": request["requestId"]}
    request["signature"] = signature(KEY, {k: v for k, v in request.items() if k != "signature"})
    result = n.web.handle(request)
    assert result["ok"] and result["data"]["authority"] == "unconfirmed"
    q = n.f.sources.facts(n.item["project_ref"])
    f = next(x for x in q["facts"] if x["field"] == "reported_feedback")
    assert f["value"] == {"retentionBoundExcerpt": True} and f["authority"] == "unconfirmed"
    shown = call(n, "snapshot")["data"]["queries"][n.item["project_ref"]]["facts"]
    assert next(x for x in shown if x["field"] == "reported_feedback")["value"] == f["evidence"]["quote"]
    assert not n.s.rows("SELECT * FROM followup_intents") and not n.calls


def test_classification_does_not_keep_raw_text_in_durable_fact_value(web):
    n = web; _, obs = add_ambiguous(n)
    review = call(n, "snapshot")["data"]["semanticReviews"][0]
    assert call(n, "review", {"reviewId": review["id"], "reviewHash": review["reviewHash"], "targetSubjectId": n.item["project_ref"]})["ok"]
    n.clock.now += 86401
    n.am.information.service.maintenance()
    fact = next(x for x in n.f.sources.facts(n.item["project_ref"])["facts"] if x["field"] == "reported_feedback")
    assert fact["evidence"]["quote"] is None
    assert obs.text not in json.dumps(fact, ensure_ascii=False)
    result = call(n, "snapshot")
    assert result["ok"] and obs.text not in json.dumps(result, ensure_ascii=False)


def test_attribution_cannot_silently_become_project_outside(web):
    n = web; add_ambiguous(n)
    review = call(n, "snapshot")["data"]["semanticReviews"][0]
    result = call(n, "review", {"reviewId": review["id"], "reviewHash": review["reviewHash"], "targetSubjectId": "outside"})
    assert not result["ok"] and not n.s.rows("SELECT * FROM wb_review_audit")


def test_semantic_processing_gaps_are_coverage_not_attribution_work(web):
    n = web; source, obs = add_ambiguous(n)
    for code in ("negation_or_correction_uncovered", "condition_scope_uncovered", "attribution_uncovered"):
        n.reader.open_gap(source.source_id, obs.object_id, "extraction", "semantic_coverage_incomplete:" + code)
        raw = call(n, "snapshot")["data"]
        assert not any(r["sourceId"] == source.source_id for r in raw["semanticReviews"])
        gap = next(g for g in raw["processingGaps"] if g["sourceId"] == source.source_id)
        assert gap["kind"] == "processing" and gap["projectIds"] == [n.item["project_ref"]]
        assert gap["text"] == obs.text and gap["rawAvailable"] is True
        assert "choices" not in gap and "reviewHash" not in gap
        query = raw["queries"][n.item["project_ref"]]
        assert query["coverage"]["processing_pending"] is True
        assert gap in query["coverage"]["processingGaps"]
        assert gap["reason"] in query["incomplete_reasons"]
    assert not n.s.rows("SELECT * FROM wb_review_audit")
    assert not n.s.rows("SELECT * FROM followup_intents") and not n.calls
    n.clock.now += 86401
    expired = call(n, "snapshot")["data"]
    gap = next(g for g in expired["processingGaps"] if g["sourceId"] == source.source_id)
    assert gap["rawAvailable"] is False and gap["text"] == ""
    assert obs.text not in json.dumps(expired, ensure_ascii=False)
    assert expired["queries"][n.item["project_ref"]]["coverage"]["processing_pending"] is True


def test_original_operator_consumes_signed_web_branch_only_once(web):
    n = web; request = envelope(n, "snapshot")
    path = n.f.operator_queue / ("wb-" + request["requestId"] + ".request.json")
    path.write_text(json.dumps({"operation": "workbench", "expires_at": request["expiresAtMs"]//1000, "envelope": request}))
    path.chmod(0o600)
    assert n.f.operator_step()
    result = json.loads(path.with_name(path.name.replace(".request.json", ".result.json")).read_text())
    assert result["workbench"]["ok"] and result["workbench"]["requestId"] == request["requestId"]
    assert not n.f.operator_step() and not n.calls


def test_key_is_explicit_private_and_feature_defaults_off(web, monkeypatch, tmp_path):
    n = web; monkeypatch.delenv("AM_WORKBENCH_KEY_FILE", raising=False)
    assert install_from_env(n.f) is None
    key = tmp_path / "synthetic-test.key"; key.write_bytes(KEY); key.chmod(0o644)
    monkeypatch.setenv("AM_WORKBENCH_KEY_FILE", str(key))
    with pytest.raises(WebBoundaryError, match="WEB_SIGNING_KEY_FILE_INVALID"):
        install_from_env(n.f)
    key.chmod(0o600)
    assert isinstance(install_from_env(n.f), WorkbenchAdapter)


def test_read_remains_available_when_scheduler_is_disabled(web):
    n = web; n.am.flags["scheduler"] = False
    assert call(n, "snapshot")["ok"]
    result = call(n, "prepare", {"itemId": n.item["id"], "expectedItemVersion": 1, "expectedSemanticVersion": 0})
    assert not result["ok"] and result["error"]["code"] == "WEB_FOLLOWUP_NOT_ENABLED"


def test_native_source_review_preserves_send_history_and_business_state(web):
    n = web; n.f.bind(n.row, n.item["id"])
    newer = replace(n.obs, version="v2", occurred_at_ms=n.obs.occurred_at_ms + 1,
                    text="样机仍在准备，后续时间待核对。", payload={"record": {"todo": "核对后续安排"}, "quote": "样机仍在准备，后续时间待核对。"})
    n.reader.record(newer, authoritative=True); n.facts.process(newer, [])
    snapshot = call(n, "snapshot")["data"]
    review = next(r for r in snapshot["semanticReviews"] if r["id"].startswith("sources:"))
    before = n.am.items.get(n.item["id"])
    choice = review["choices"][0]["value"]
    result = call(n, "review", choice)
    assert result["ok"], result
    assert n.am.items.get(n.item["id"]) == before
    assert not n.s.rows("SELECT * FROM reminder_occurrences") and not n.calls
    assert n.f.semantic(n.item["id"])["version"] == 2


def test_conflict_display_choice_does_not_alter_formal_facts(web):
    n = web
    for index, value in enumerate(("2026-11-05", "2026-11-06")):
        source = Source("structured-plan-" + str(index), "task_snapshot", "source-" + str(index), n.f.tenant, n.am.owner,
            enabled=True, settings={"subject_id": n.item["project_ref"], "fact_mappings": {"plan": {"value_path": ["value"], "quote_path": ["quote"]}}})
        n.reader.register_source(source)
        obs = Observation(source.source_id, "plan-object", "plan-v1", int(n.clock()*1000), text=value, payload={"value": value, "quote": value})
        n.reader.record(obs); n.facts.process(obs, [])
    q = n.f.sources.facts(n.item["project_ref"])
    conflict = next(c for c in q["conflicts"] if c["field"] == "plan")
    facts = [f for f in q["facts"] if f["fact_id"] in conflict["fact_ids"]]
    params = {"reviewId": "conflict:synthetic-plan", "reviewHash": "current-review-hash",
        "choiceId": facts[0]["fact_id"], "choice": {"kind": "select", "factId": facts[0]["fact_id"]},
        "factIds": conflict["fact_ids"], "projectId": n.item["project_ref"],
        "evidence": [{"sourceId": f["evidence"]["source_id"], "objectId": f["evidence"]["object_id"],
                      "version": f["evidence"]["version"], "quote": f["evidence"]["quote"]} for f in facts]}
    request = envelope(n, "review", params); request["params"]["requestId"] = request["requestId"]
    request["signature"] = signature(KEY, {k: v for k, v in request.items() if k != "signature"})
    result = n.web.handle(request)
    assert result["ok"] and result["data"]["displayOnly"], result
    after = n.f.sources.facts(n.item["project_ref"])
    assert after["facts"] == q["facts"] and after["conflicts"] == q["conflicts"]
    assert not n.calls and not n.s.rows("SELECT * FROM followup_intents")


def test_snapshot_queue_original_loop_purges_expired_raw_result(web):
    n = web; request = envelope(n, "snapshot")
    path = n.f.operator_queue / ("wb-" + request["requestId"] + ".request.json")
    path.write_text(json.dumps({"operation": "workbench", "expires_at": request["expiresAtMs"]//1000, "envelope": request})); path.chmod(0o600)
    assert n.f.operator_step()
    assert not path.with_suffix(".claimed").exists()
    result_path = path.with_name(path.name.replace(".request.json", ".result.json"))
    n.clock.now += 61
    n.f.operator_step()
    result = json.loads(result_path.read_text())["workbench"]
    assert not result["ok"] and result["error"]["code"] == "WEB_SNAPSHOT_EXPIRED" and "data" not in result


def test_preview_queue_and_adapter_copies_expire_without_erasing_receipt_identity(web):
    n = web
    request = envelope(n, "prepare", {"itemId": n.item["id"], "expectedItemVersion": 1,
        "expectedSemanticVersion": 0, "body": "限时预览正文，不应长期保存在网页副本中。"})
    path = n.f.operator_queue / ("wb-" + request["requestId"] + ".request.json")
    path.write_text(json.dumps({"operation": "workbench", "envelope": request})); path.chmod(0o600)
    assert n.f.operator_step()
    result_path = path.with_name(path.name.replace(".request.json", ".result.json"))
    preview = json.loads(result_path.read_text())["workbench"]["data"]
    n.clock.now = preview["expiresAtMs"] / 1000 + 1
    n.f.operator_step()
    result = json.loads(result_path.read_text())["workbench"]
    assert not result["ok"] and result["error"]["code"] == "WEB_PREVIEW_EXPIRED"
    retained = n.s.rows("SELECT * FROM wb_web_previews WHERE preview_id=?", (preview["previewId"],))[0]
    assert retained["display_json"] == "{}" and retained["invalidated"] == 1
    saved = n.s.rows("SELECT result_json FROM wb_rpc_requests WHERE request_id=?", (request["requestId"],))[0]
    assert "限时预览正文" not in saved["result_json"]
    assert not n.calls


def test_preview_cannot_outlive_its_native_source(web):
    n = web
    expires = int(n.clock() * 1000) + 20000
    n.reader.conn.execute("UPDATE observations SET raw_expires_at_ms=?", (expires,))
    n.reader.conn.commit()
    p = prepare(n)
    assert p["expiresAtMs"] <= expires


def test_paused_item_keeps_history_without_old_date_or_checkpoint_nudges(web):
    n = web
    n.s.execute("UPDATE action_items SET paused=1,deadline='2026-01-01',next_check=? WHERE id=?",
                (n.clock()-100, n.item["id"]))
    before = n.am.items.get(n.item["id"])
    snapshot = call(n, "snapshot")["data"]
    assert not any(r["kind"] in {"date_attention", "check_due"} for r in snapshot["reminders"])
    assert n.am.items.get(n.item["id"]) == before


def test_node_python_signed_queue_full_admission_without_dispatch(web, tmp_path):
    n = web
    n.clock.now += 0.125
    original_projects = n.am.projects
    n.am.projects = lambda row: [dict(p, _sync_observed_at=n.clock()) for p in original_projects(row)]
    n.s.execute("UPDATE action_items SET created=created+0.125 WHERE id=?", (n.item["id"],))
    numeric_source = Source("decimal-source", "task_snapshot", "decimal-object", n.f.tenant, n.am.owner,
        enabled=True, settings={"subject_id": n.item["project_ref"], "fact_mappings": {"progress": {"value_path": ["ratio"], "quote_path": ["quote"]}}})
    n.reader.register_source(numeric_source)
    numeric_obs = Observation(numeric_source.source_id, "decimal-object", "v1", int(n.clock()*1000), text="0.5", payload={"ratio": 0.5, "quote": "0.5"})
    n.reader.record(numeric_obs); n.facts.process(numeric_obs, [])
    key = tmp_path / "node-python-fixture.key"; key.write_bytes(KEY); key.chmod(0o600)
    bridge = (HERE.parents[1] / "server/queue-bridge.mjs").as_uri()
    config = {"queueDir": str(n.f.operator_queue), "keyFile": str(key), "now": int(n.clock()*1000),
              "owner": n.am.owner, "tenant": n.f.tenant, "project": n.item["project_ref"]}
    script = """
import { SignedQueueBridge } from %s;
import { randomUUID } from 'node:crypto';
const config = %s;
const bridge = new SignedQueueBridge({queueDir:config.queueDir,keyFile:config.keyFile,clock:()=>config.now,timeoutMs:5000,pollMs:20});
const session = {id:'node-fixture-session',userId:config.owner,tenantId:config.tenant,workspaceId:config.tenant,projectIds:[config.project],expiresAtMs:config.now+3600000,scopes:['ledger:read','am:prepare','am:approve','review:resolve','reminder:manage']};
const raw = await bridge.call('snapshot',{},session);
if(raw.wireNumberEncoding!=='integer-or-decimal-text/v1' || raw.queries[config.project].facts.find(f=>f.field==='progress').value!=='0.5')throw new Error('fractional fact wire mismatch');
if(!raw.projects[0]._sync_observed_at.includes('.125') || raw.projects[0]._sync_observed_at.startsWith('1970'))throw new Error('native seconds were misread as milliseconds');
const item = raw.items[0];
const p = await bridge.call('prepare',{itemId:item.id,expectedItemVersion:item.version,expectedSemanticVersion:item.semanticVersion,body:'请核对实际开测时间，保留条件与否定。'},session);
const shown = await bridge.call('present',{previewId:p.previewId,displayHash:p.displayHash},session);
const requestId = randomUUID();
const result = await bridge.call('approve',{requestId,previewId:p.previewId,displayHash:p.displayHash,presentationId:shown.presentationId},session,{requestId});
console.log(JSON.stringify({result,projects:raw.projects.length,body:p.body}));
""" % (json.dumps(bridge), json.dumps(config))
    process = subprocess.Popen(["node", "--input-type=module", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 20
    try:
        while process.poll() is None and time.monotonic() < deadline:
            n.f.operator_step()
            time.sleep(0.02)
        if process.poll() is None:
            process.kill()
        out, err = process.communicate(timeout=2)
        assert process.returncode == 0, err
        result = json.loads(out)
        assert result["result"]["state"] == "queued" and result["projects"] == 1
        assert result["body"] == "请核对实际开测时间，保留条件与否定。"
        assert len(n.s.rows("SELECT * FROM reminder_occurrences")) == 1
        assert not n.calls
        assert next(f for f in n.f.sources.facts(n.item["project_ref"])["facts"] if f["field"] == "progress")["value"] == 0.5
    finally:
        if process.poll() is None:
            process.kill(); process.communicate()
