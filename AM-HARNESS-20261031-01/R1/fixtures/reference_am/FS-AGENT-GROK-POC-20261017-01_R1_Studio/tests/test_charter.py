"""Charter routing, source fidelity, and unsupported-link behavior."""
import copy
import json
import pytest
from test_doc_logic import rig, base_rig, ready
from test_gateway import event
from test_doc_logic_fix1 import candidate, model_run, OK
from fs_agent.doc_logic import read_source, data_payload, build_prompt, semantic_prompt, validate_analysis
from fs_agent.config import BoundaryError


def test_charter_file_runs_existing_pipeline_and_preserves_sources(rig):
    g, s, api, _, _ = rig
    assert g.ingest(event("/doc logic charter"))
    g.receive_one()
    row = s.rows("SELECT * FROM inbox ORDER BY seq DESC LIMIT 1")[0]
    assert g.logic.current(row)["document_type"] == "charter"
    assert not s.rows("SELECT * FROM tasks")
    text = "章程草稿。计划测试结束日期2026.11.10，官网上线另行确认。验收授权待确认。"
    api.read_file = lambda *a, **k: text.encode()
    payload = event(number=2)
    payload["event"]["message"].update(message_type="file", content=json.dumps(
        {"file_key": "file_charter", "file_name": "charter.txt"}))
    assert g.ingest(payload)
    g.receive_one()
    sources = json.loads(g.logic.current(row)["sources"])
    d = model_run(g, s, [candidate(sources), OK])
    assert d["content"].startswith("# 项目章程")
    assert "8D／异常分析" not in d["content"]
    assert "2026.11.10" in d["content"]
    assert "授权" in d["content"] and "尚未采用／挂载" in d["content"]
    assert json.loads(d["sources"]) == sources
    assert sources[0]["segments"][0]["location"]


@pytest.mark.parametrize("message", [
    "https://example.invalid/wiki/document",
    "/doc logic charter https://example.invalid/wiki/document",
])
def test_link_neither_invents_document_nor_invalidates_existing_draft(rig, message):
    g, s, row, before = ready(rig)
    before_tasks = len(s.rows("SELECT * FROM tasks"))
    assert g.ingest(event(message, number=2))
    g.receive_one()
    after = g.logic.current(row)
    for key in ("id", "revision", "state", "content_hash", "sources", "answers", "expires"):
        assert after[key] == before[key]
    assert len(s.rows("SELECT * FROM tasks")) == before_tasks
    assert any("不能直接读取" in (o["body"] or "") for o in s.rows("SELECT body FROM outbox"))


def test_long_charter_projection_keeps_every_quote_and_ref_within_prompt_budget():
    text = "\n".join(
        f"事项{i}：本项保持为计划。交付输入由既定角色提供；验收授权尚待明确。"
        for i in range(90)
    )
    source = read_source("charter.txt", text.encode(), source_id="S01", origin="private")
    saved = copy.deepcopy(source)
    projected = data_payload([source], "charter", False, {})["sources"][0]
    assert projected["segments"] == [
        {"ref": p["ref"], "original": p["original"]} for p in source["segments"]]
    assert source == saved
    assert "origin" not in projected
    prompt, _ = build_prompt([source], "charter")
    assert len(prompt) <= 30000
    assert "测试结束日期不能等同官网上线" in prompt
    assert "测试结束日期不能等同官网上线" in semantic_prompt(
        [source], candidate([source]), document_type="charter")


def test_charter_short_date_is_not_a_new_number_but_new_dates_are_rejected():
    sources = [read_source("charter.txt", "计划起点2026.10.19。".encode(),
                           source_id="S01", origin=None)]
    value = candidate(sources, assessment="10.19为计划起点，保留待核。")
    validate_analysis(value, sources, document_type="charter")
    value["assessment"] = "10.20为计划起点。"
    with pytest.raises(BoundaryError, match="LOGIC_NEW_NUMBER"):
        validate_analysis(value, sources, document_type="charter")
    # No new general permission to add decimal measurements to test reports.
    value["assessment"] = "电流为10.19 A。"
    with pytest.raises(BoundaryError, match="LOGIC_NEW_NUMBER"):
        validate_analysis(value, sources, document_type="test")
