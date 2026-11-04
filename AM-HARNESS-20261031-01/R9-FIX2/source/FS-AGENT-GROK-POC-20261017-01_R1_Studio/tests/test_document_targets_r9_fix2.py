"""Offline target contracts. Every ID, field, candidate and response is synthetic."""
import copy
import json
import time

import pytest

from fs_agent.config import BoundaryError
from fs_agent.document_delivery import discover_targets, render_targets
from fs_agent.meegle_port import BusinessNotStarted
from test_doc_logic import rig, ready
from test_gateway import rig as base_rig
from test_meegle_port import bound, port_fixture


@pytest.fixture
def target_rig(rig):
    g, store, row, draft = ready(rig)
    port, state, settings = port_fixture(g)
    return g, store, row, draft, port, state, settings["targets"]["report"]


def field(state, key):
    return next(item for item in state["metadata"] if item["field_key"] == key)


def assert_no_write(state):
    assert state["uploads"] == state["updates"] == 0
    assert ["attachment", "+upload"] not in state["calls"]
    assert ["workitem", "update"] not in state["calls"]


def discover(port, row):
    return discover_targets(port, row, project_code="IRAD-2099-001", doc_type="charter",
                            guard=lambda: True, deadline=time.monotonic() + 10)


def charter(state, binding):
    state["kind"] = "项目章程"
    binding["document_type"] = "charter"


def test_legacy_ambiguous_config_fails_before_metadata_and_has_reviewable_diagnostic(target_rig):
    _, _, row, _, port, state, binding = target_rig
    for key in ("document_kind_field", "document_link_field", "project_code", "project_type", "document_type"):
        binding.pop(key)
    state["kind"] = ["https://files.invalid/old-document"]
    result = discover(port, row)
    assert result["state"] == "unresolved" and result["targets"] == []
    diagnostic = result["diagnostics"][0]
    assert diagnostic["error_code"] == "BUSINESS_TARGET_CONFIG_INCOMPLETE"
    assert "document_kind_field" in diagnostic["detail"]["missing_config"]
    assert state["calls"] == [["user", "me"]]
    assert_no_write(state)


@pytest.mark.parametrize("key,typ", [("doc", "file"), ("doc", "multi_select"),
    ("files", "url"), ("files", "text"), ("parent", "text"), ("node", "file")])
def test_role_type_mismatch_is_blocked_before_item_reads(target_rig, key, typ):
    _, _, row, _, port, state, _ = target_rig
    field(state, key)["field_type"] = typ
    with pytest.raises(BoundaryError, match="BUSINESS_FIELD_TYPE_UNSUPPORTED") as error:
        port.resolve(row, "report")
    assert error.value.diagnostic["field_key"] == key
    assert ["workitem", "get"] not in state["calls"]
    assert_no_write(state)


@pytest.mark.parametrize("value", [["https://files.invalid/document"], ["测试报告"],
                                     {"url": "https://files.invalid/document"}])
def test_list_of_urls_or_multiple_kind_values_never_becomes_identity(target_rig, value):
    _, _, row, _, port, state, _ = target_rig
    state["kind"] = value
    with pytest.raises(BoundaryError, match="BUSINESS_FIELD_VALUE_UNVERIFIED"):
        port.resolve(row, "report")
    assert_no_write(state)


@pytest.mark.parametrize("legacy,current", [("document_field", "files"), ("attachment_field", "doc"),
                                             ("document_kind_field", "files")])
def test_conflicting_field_roles_or_aliases_are_not_silently_repaired(target_rig, legacy, current):
    _, _, row, _, port, state, binding = target_rig
    binding[legacy] = current
    with pytest.raises(BoundaryError, match="BUSINESS_TARGET_FIELD_CONFLICT"):
        port.resolve(row, "report")
    assert_no_write(state)


@pytest.mark.parametrize("response", [{}, {"list": []}, {"list": [], "pagination": {"has_more": False}},
    {"list": [], "pagination": {"has_more": "false"}}])
def test_absent_or_incomplete_metadata_cannot_be_inferred_from_config(target_rig, response):
    _, _, row, _, port, state, _ = target_rig
    state["metadata_response"] = response
    result = discover(port, row)
    assert result["state"] == "unresolved" and not result["targets"]
    assert result["diagnostics"][0]["error_code"] in (
        "BUSINESS_METADATA_UNAVAILABLE", "BUSINESS_FIELD_METADATA_MISSING")
    assert "元数据" in render_targets(result)
    assert_no_write(state)


def test_metadata_call_failure_is_explicit_and_read_only(target_rig):
    _, _, row, _, port, state, _ = target_rig
    state["metadata_error"] = "BUSINESS_CALL_FAILED"
    result = discover(port, row)
    assert result["diagnostics"][0]["error_code"] == "BUSINESS_METADATA_UNAVAILABLE"
    assert result["diagnostics"][0]["detail"]["cause"] == "BUSINESS_CALL_FAILED"
    assert_no_write(state)


def test_paged_metadata_requires_all_pages_and_rejects_duplicate_field_definitions(target_rig):
    _, _, row, _, port, state, _ = target_rig
    state["metadata_pages"] = {
        1: {"list": state["metadata"][:3], "pagination": {"has_more": True}},
        2: {"list": state["metadata"][3:], "pagination": {"has_more": False}},
    }
    assert port.resolve(row, "report")["document_identity"]["doc_type"] == "test"
    pages = [args[args.index("--page-num") + 1] for args in state["commands"] if args[:2] == ["workitem", "meta-fields"]]
    assert pages == ["1", "2"]
    state["metadata_pages"][2]["list"].append(copy.deepcopy(field(state, "doc")))
    with pytest.raises(BoundaryError, match="BUSINESS_FIELD_METADATA_AMBIGUOUS"):
        port.resolve(row, "report")
    assert_no_write(state)


def test_incomplete_metadata_has_a_fixed_page_budget(target_rig):
    _, _, row, _, port, state, _ = target_rig
    state["metadata_response"] = {"list": [], "pagination": {"has_more": True}}
    with pytest.raises(BoundaryError, match="BUSINESS_METADATA_LIMIT"):
        port.resolve(row, "report")
    assert state["calls"].count(["workitem", "meta-fields"]) == 20
    assert_no_write(state)


def test_select_kind_requires_actual_metadata_candidate_and_matching_label(target_rig):
    _, _, row, _, port, state, binding = target_rig
    field(state, "doc").update(field_type="select", options=[{"value": "kind-test", "label": "测试报告"}])
    state["kind"] = {"value": "kind-test", "label": "测试报告"}
    target = port.resolve(row, "report")
    assert port.document_identity(row, target) == {"project_code": "IRAD-2099-001", "doc_type": "test"}
    state["kind"]["label"] = "项目章程"
    with pytest.raises(BoundaryError, match="BUSINESS_FIELD_CANDIDATE_MISMATCH"):
        port.resolve(row, "report")
    state["kind"] = "not-a-candidate"
    binding["document_type_bindings"] = {"not-a-candidate": "test"}
    with pytest.raises(BoundaryError, match="BUSINESS_FIELD_CANDIDATE_MISMATCH"):
        port.resolve(row, "report")
    assert_no_write(state)


@pytest.mark.parametrize("options", [None, [], [{"value": "v", "label": "测试报告"},
    {"value": "v", "label": "项目章程"}], [{"value": ["v"], "label": "测试报告"}]])
def test_missing_or_ambiguous_select_candidates_fail_closed(target_rig, options):
    _, _, row, _, port, state, _ = target_rig
    field(state, "doc").update(field_type="select", options=options)
    state["kind"] = {"value": "v"}
    with pytest.raises(BoundaryError, match="BUSINESS_FIELD_CANDIDATES_UNVERIFIED"):
        port.resolve(row, "report")
    assert_no_write(state)


def test_configured_document_type_does_not_override_observed_kind(target_rig):
    _, _, row, _, port, state, binding = target_rig
    binding["document_type"] = "charter"
    with pytest.raises(BoundaryError, match="BUSINESS_DOCUMENT_KIND_MISMATCH"):
        port.resolve(row, "report")
    binding["document_type_bindings"] = {"测试报告": "charter"}
    with pytest.raises(BoundaryError, match="BUSINESS_DOCUMENT_KIND_MISMATCH"):
        port.resolve(row, "report")
    assert_no_write(state)


@pytest.mark.parametrize("attribute,value,error", [
    ("work_item_name", "IRAD-2099-002 合成项目", "BUSINESS_PROJECT_CODE_MISMATCH"),
    ("work_item_name", "IRAD-2099-001 / IRAD-2099-002", "BUSINESS_PROJECT_CODE_UNVERIFIED"),
    ("work_item_name", "没有业务编号", "BUSINESS_PROJECT_CODE_UNVERIFIED"),
    ("work_item_id", "101", "BUSINESS_PROJECT_IDENTITY_CHANGED"),
    ("owned_project", {"key": "another-space"}, "BUSINESS_PROJECT_IDENTITY_CHANGED"),
    ("work_item_type", {"key": "deliverable"}, "BUSINESS_PROJECT_IDENTITY_CHANGED"),
])
def test_project_identity_is_proved_by_independent_project_read(target_rig, attribute, value, error):
    _, _, row, _, port, state, _ = target_rig
    state["project_attribute"][attribute] = value
    with pytest.raises(BoundaryError, match=error):
        port.resolve(row, "report")
    assert_no_write(state)


def test_missing_project_relation_has_specific_diagnostic_even_when_node_contains_member(target_rig):
    _, _, row, _, port, state, _ = target_rig
    state["missing_fields"] = ["parent"]
    result = discover(port, row)
    assert result["state"] == "unresolved" and result["targets"] == []
    assert result["diagnostics"][0]["error_code"] == "BUSINESS_PROJECT_RELATION_MISSING"
    request = next(args for args in state["commands"] if args[:2] == ["workitem", "get"] and "--fields" in args)
    assert "parent" in request[request.index("--fields") + 1].split(",")
    assert "项目关系" in render_targets(result)
    assert_no_write(state)


@pytest.mark.parametrize("overrides,error", [({"parent": {"id": 101}}, "BUSINESS_TARGET_CHANGED"),
    ({"parent": [{"id": 100}, {"id": 101}]}, "BUSINESS_PROJECT_RELATION_UNVERIFIED"),
    ({"node": "state-other"}, "BUSINESS_TARGET_CHANGED")])
def test_membership_does_not_override_conflicting_or_ambiguous_relation_fields(target_rig, overrides, error):
    _, _, row, _, port, state, _ = target_rig
    state["field_overrides"] = overrides
    with pytest.raises(BoundaryError, match=error):
        port.resolve(row, "report")
    assert_no_write(state)


@pytest.mark.parametrize("pagination", [None, [], {}, {"has_more": "false"}, {"has_more": True}])
def test_unknown_or_partial_node_pagination_is_structured_unresolved(target_rig, pagination):
    _, _, row, _, port, state, _ = target_rig
    state["node_pagination"] = pagination
    result = discover(port, row)
    assert result["state"] == "unresolved" and not result["targets"]
    assert result["diagnostics"][0]["error_code"] == "BUSINESS_NODE_UNVERIFIED"
    assert_no_write(state)


def test_mixed_resolved_and_unresolved_bindings_are_only_reviewable(target_rig):
    _, _, row, _, port, state, binding = target_rig
    charter(state, binding)
    port.settings["targets"]["unresolved"] = {"document_field": "old-links"}
    original = copy.deepcopy(port.settings["targets"])
    result = discover(port, row)
    assert result["state"] == "unresolved" and result["targets"] == []
    assert [target["id"] for target in result["reviewable_candidates"]] == ["report"]
    assert result["unresolved"] == ["unresolved"]
    assert port.settings["targets"] == original
    assert_no_write(state)


def test_multiple_verified_bindings_require_explicit_selection(target_rig):
    _, _, row, _, port, state, binding = target_rig
    charter(state, binding)
    port.settings["targets"]["another"] = copy.deepcopy(binding)
    result = discover(port, row)
    assert result["state"] == "ambiguous"
    assert {target["id"] for target in result["targets"]} == {"another", "report"}
    assert "明确选择" in render_targets(result)
    assert_no_write(state)


def test_only_matching_project_and_document_type_is_a_discovery_candidate(target_rig):
    _, _, row, _, port, state, _ = target_rig
    result = discover(port, row)  # verified test report; caller requests charter
    assert result["state"] == "not_configured" and result["targets"] == []
    assert result["diagnostics"][0]["document_type_matches"] is False
    assert_no_write(state)


def test_document_identity_rereads_and_rejects_stale_mutable_revision(target_rig):
    _, _, row, _, port, state, _ = target_rig
    target = port.resolve(row, "report")
    before = len(state["calls"])
    assert port.document_identity(row, target) == {"project_code": "IRAD-2099-001", "doc_type": "test"}
    assert ["workitem", "meta-fields"] in state["calls"][before:]
    state["revision"] = "changed"
    with pytest.raises(BoundaryError, match="TARGET_REVISION_CHANGED"):
        port.document_identity(row, target)
    assert_no_write(state)


def test_successful_append_changes_revision_but_preserves_target_binding(rig):
    g, store, row, draft, port, state, _ = bound(rig)
    before = port.resolve(row, "report")
    result = g.logic.mount(row, draft["id"])
    assert result["receipt"] is not None
    after = port.resolve(row, "report")
    assert after["revision"] != before["revision"]
    assert after["binding_fingerprint"] == before["binding_fingerprint"]
    assert after["field_metadata_fingerprint"] == before["field_metadata_fingerprint"]
    write = store.rows("SELECT * FROM logic_writes")[0]
    assert port.reconcile(row, write["idem"]) == result["receipt"]
    assert state["updates"] == state["uploads"] == 1
    assert json.loads(write["target"])["document_link_field"] == "files"


def test_metadata_contract_change_cannot_reconcile_against_old_target(rig):
    g, store, row, draft, port, state, _ = bound(rig)
    assert g.logic.mount(row, draft["id"])["receipt"] is not None
    field(state, "mode")["options"][0]["label"] = "文档（新定义）"
    write = store.rows("SELECT * FROM logic_writes")[0]
    with pytest.raises(BoundaryError, match="BUSINESS_TARGET_BINDING_CHANGED"):
        port.reconcile(row, write["idem"])
    assert state["updates"] == state["uploads"] == 1


def test_metadata_change_before_write_is_proven_not_started(target_rig):
    _, _, row, draft, port, state, binding = target_rig
    target = port.resolve(row, "report")
    binding["verified_empty_revision"] = target["revision"]
    field(state, "mode")["options"][0]["label"] = "文档（新定义）"
    with pytest.raises(BusinessNotStarted, match="TARGET_REVISION_CHANGED"):
        port.commit(row, target, draft["content"], draft["content_hash"], "synthetic-idem", lambda: True)
    assert_no_write(state)


def test_unpreservable_existing_attachment_is_proven_not_started(target_rig):
    _, _, row, draft, port, state, _ = target_rig
    state["files"] = [{"name": "existing.md", "url": "https://files.invalid/existing.md"}]
    target = port.resolve(row, "report")
    with pytest.raises(BusinessNotStarted, match="BUSINESS_EXISTING_ATTACHMENT_UNVERIFIED"):
        port.commit(row, target, draft["content"], draft["content_hash"], "synthetic-idem", lambda: True)
    assert_no_write(state)
