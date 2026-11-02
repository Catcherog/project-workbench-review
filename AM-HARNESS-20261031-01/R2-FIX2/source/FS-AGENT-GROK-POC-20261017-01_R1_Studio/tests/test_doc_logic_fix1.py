"""R1-FIX1 counterexamples: actual state transitions with isolated model/platform doubles."""
import copy
import json
import pytest
from fs_agent.config import BoundaryError
from fs_agent.doc_logic import (read_source, program_questions, apply_program_findings,
                                mechanical_issues, validate_analysis)
from fs_agent.question_state import question_id, register, reconcile, reconcile_questions
from fs_agent.provider import Result
from test_doc_logic import rig, base_rig
from test_gateway import event

def source(text, number=1):
    return read_source("input.txt", text.encode(), source_id=f"S{number:02}", origin=None)

def question(ref, subject, gap, ask):
    return dict(key="same_model_key", refs=[ref], subject=subject, gap=gap, ask=ask, impact="影响对应记录判断")

def candidate(sources, questions=(), assessment="按当前已提供记录形成有边界的判断。"):
    p = sources[0]["segments"][0]
    return {"problem":"核对本次记录", "assessment":assessment,
            "evidence":[dict(ref=p["ref"],quote=p["original"],kind="reported",relation="支持",
                             claim="保留本次原始记录",reason="仅支持记录明确的内容")],
            "changes":["依据新增资料更新判断，原句保留"], "gaps":[], "questions":list(questions), "next":[]}

def model_run(g, s, outputs):
    outputs=iter(outputs)
    class Model:
        def complete(self, *a, **kw):
            return Result(json.dumps(next(outputs),ensure_ascii=False), "isolated-double", .01)
    g.provider=Model()
    task=s.claim(1); g.run_task(task)
    result=s.rows("SELECT state,error FROM tasks WHERE id=?",(task["id"],))[0]
    assert result["state"]=="completed", result
    with pytest.raises(StopIteration): next(outputs)
    return g.logic.current(task)

OK={"ok":True,"issues":[]}

def two_questions(rig):
    g,s,*_=rig
    g.ingest(event("/doc logic test 电机A：电流18 A；样本编号与适用判据待补。"));g.receive_one()
    row=s.rows("SELECT * FROM inbox ORDER BY seq DESC LIMIT 1")[0]
    sources=json.loads(g.logic.current(row)["sources"])
    qs=[question("S01:1","电机A / 电流 A","sample","电机A样本编号是什么？"),
        question("S01:1","电机A / 电流 A","criterion","电机A适用判据是什么？")]
    d=model_run(g,s,[candidate(sources,qs),OK])
    return g,s,row,d,qs

def update(q, status, quote, answer, remaining="", ref="S02:1"):
    return dict(id=question_id(q),status=status,answer=answer,remaining=remaining,
                citations=[dict(ref=ref,quote=quote)],reason="补充明确指向该对象的此项缺口")

def test_two_questions_only_one_answer_keeps_other_open(rig):
    g,s,row,d,qs=two_questions(rig)
    g.ingest(event("电机A样本编号是 S-A。",number=2));g.receive_one()
    # Saving the source alone must not change ANY question to answered.
    pending=g.logic.current(row)
    assert {q["status"] for q in json.loads(pending["answers"]).values()}=={"unanswered"}
    sources=json.loads(pending["sources"])
    d=model_run(g,s,[{"updates":[update(qs[0],"resolved","样本编号是 S-A","样本 S-A")]},candidate(sources),OK])
    ledger=json.loads(d["answers"])
    assert ledger[question_id(qs[0])]["status"]=="resolved"
    assert ledger[question_id(qs[1])]["status"]=="unanswered"
    assert [q["gap"] for q in json.loads(d["analysis"])["questions"]]==["criterion"]
    assert len(sources)==2 and len(ledger[question_id(qs[0])]["history"])==1

def test_two_answers_map_individually_and_clear_gaps(rig):
    g,s,row,d,qs=two_questions(rig)
    g.ingest(event("电机A样本编号是 S-A，电机A该单项判据为≥16 A。",number=2));g.receive_one()
    sources=json.loads(g.logic.current(row)["sources"])
    updates=[update(qs[0],"resolved","样本编号是 S-A","样本 S-A"),
             update(qs[1],"resolved","该单项判据为≥16 A","单项判据≥16 A")]
    d=model_run(g,s,[{"updates":updates},candidate(sources,assessment="电机A样本S-A该次电流18 A满足≥16 A单项判据。"),OK])
    a=json.loads(d["analysis"]);ledger=json.loads(d["answers"])
    assert a["questions"]==[] and a["gaps"]==[]
    assert all(q["status"]=="resolved" for q in ledger.values())
    assert ledger[question_id(qs[0])]["citations"]!=ledger[question_id(qs[1])]["citations"]

@pytest.mark.parametrize("reply",["我查一下", "今天下雨。"])
def test_wait_or_unrelated_reply_does_not_resolve(rig,reply):
    g,s,row,d,qs=two_questions(rig)
    g.ingest(event(reply,number=2));g.receive_one()
    sources=json.loads(g.logic.current(row)["sources"])
    outputs=([{"updates":[]}] if reply!="我查一下" else [])+[candidate(sources),OK]
    d=model_run(g,s,outputs)
    assert len(json.loads(d["analysis"])["questions"])==2
    assert all(q["status"]=="unanswered" for q in json.loads(d["answers"]).values())

def test_unavailable_preserves_boundary_and_stage_without_reasking(rig):
    g,s,row,d,qs=two_questions(rig)
    g.ingest(event("电机A的样本编号不知道。",number=2));g.receive_one()
    sources=json.loads(g.logic.current(row)["sources"])
    d=model_run(g,s,[{"updates":[update(qs[0],"unavailable","样本编号不知道","用户不知道样本编号","样本身份仍无法确认")]},candidate(sources),OK])
    a=json.loads(d["analysis"])
    assert [q["gap"] for q in a["questions"]]==["criterion"]
    assert any("无法提供" in gap for gap in a["gaps"])
    g.ingest(event("/doc 阶段稿",number=3));g.receive_one()
    d=model_run(g,s,[candidate(sources),OK])
    assert json.loads(d["analysis"])["questions"]==[]
    assert "样本身份仍无法确认" in d["content"]

def test_partial_mean_then_sample_scope_updates_without_old_gap(rig):
    g,s,*_=rig
    g.ingest(event("/doc logic test 电机A：均值判据≥16 A；处理后记录18 A以上。"));g.receive_one()
    row=s.rows("SELECT * FROM inbox ORDER BY seq DESC LIMIT 1")[0]
    sources=json.loads(g.logic.current(row)["sources"])
    q=program_questions(sources)[0]
    d=model_run(g,s,[candidate(sources),OK])
    g.ingest(event("电机A上述18 A以上是均值，样本范围待查。",number=2));g.receive_one()
    sources=json.loads(g.logic.current(row)["sources"])
    d=model_run(g,s,[{"updates":[update(q,"partial","18 A以上是均值","已明确为均值","电机A该均值对应的样本范围是什么？")]},candidate(sources),OK])
    assert json.loads(d["analysis"])["questions"][0]["ask"]=="电机A该均值对应的样本范围是什么？"
    assert "是否为均值" not in " ".join(json.loads(d["analysis"])["gaps"])
    g.ingest(event("电机A上述均值的样本范围是A1、A2、A3，与该均值判据对应。",number=3));g.receive_one()
    sources=json.loads(g.logic.current(row)["sources"])
    d=model_run(g,s,[{"updates":[update(q,"resolved","样本范围是A1、A2、A3，与该均值判据对应","均值，样本A1、A2、A3，判据对应",ref="S03:1")]},candidate(sources,assessment="电机A该样本范围的均值18 A以上满足≥16 A判据。"),OK])
    assert not json.loads(d["analysis"])["gaps"] and not json.loads(d["analysis"])["questions"]
    assert "处理后记录18 A以上" in d["content"] and "满足" in json.loads(d["analysis"])["assessment"]

def test_different_objects_units_and_single_mean_criteria_are_not_paired():
    sources=[source("电机A：均值判据≥16 A；处理后记录18 A以上。\n支架B：处理后记录20 mm以上，单件判据≥19 mm。\n电机C：单件判据≥16 A；处理后单次记录18 A。")]
    qs=program_questions(sources)
    assert len(qs)==1 and qs[0]["refs"]==["S01:2"] and "电机A" in qs[0]["subject"]
    ledger={}
    a=question("S01:2","电机A","criterion","A判据？")
    b=question("S01:3","支架B","criterion","B判据？")
    assert a["key"]==b["key"] and register(ledger,a,sources)!=register(ledger,b,sources)
    ledger[question_id(a)]["status"]="resolved"
    out=reconcile_questions(candidate(sources,[b]),ledger,sources)
    assert out["questions"][0]["subject"]=="支架B"

@pytest.mark.parametrize("correction",["应为静态电流37 mA，原物理量名称写错", "单位应为mW，原mA写错；静态功耗37 mW"])
def test_quantity_or_unit_correction_resolves_only_its_record(correction):
    sources=[source("电机A：静态功耗37 mA。\n电机B：静态功耗39 mA。"),source("更正电机A："+correction,2)]
    ledger={}
    qs=program_questions(sources)
    for q in qs: register(ledger,q,sources)
    ledger=reconcile({"updates":[update(qs[0],"resolved",correction.split("；")[0],correction)]},ledger,sources,{"S02"})
    result=apply_program_findings(candidate(sources),sources,ledger)
    assert not any("S01:1" in g for g in result["gaps"])
    assert any("S01:2" in g for g in result["gaps"])

def test_resolved_state_requires_current_exact_source_citation():
    sources=[source("电机A记录"),source("我查一下",2)]
    q=question("S01:1","电机A","criterion","判据？");ledger={};register(ledger,q,sources)
    u=update(q,"resolved","我查一下","假想判据")
    assert reconcile({"updates":[u]},ledger,sources,{"S02"})[question_id(q)]["status"]=="unanswered"
    u["citations"][0]["quote"]="不存在"
    with pytest.raises(BoundaryError,match="CITATION"): reconcile({"updates":[u]},ledger,sources,{"S02"})

@pytest.mark.parametrize("text,bad,good",[
    ("扭矩：跑合再清洗后≥2.8 N·m。","跑合后扭矩≥2.8 N·m。","跑合再清洗后扭矩≥2.8 N·m。"),
    ("工程师提交重校后恢复记录。","这些是非实测数据。","记录显示重校后恢复，本轮未独立复核。")])
def test_C02_C04_semantic_distortions_are_rejected(text,bad,good):
    sources=[source(text)]
    assert mechanical_issues(candidate(sources,assessment=bad),sources)
    assert not mechanical_issues(candidate(sources,assessment=good),sources)

def test_C05_negative_claim_evidence_direction():
    sources=[source("此输入只有图题信息，没有图片像素。")]
    v=candidate(sources);v["evidence"][0].update(claim="本轮无法独立视觉验证",relation="不足",reason="没有像素可供视觉核验")
    assert mechanical_issues(v,sources)
    v["evidence"][0]["relation"]="支持"
    assert not mechanical_issues(v,sources)


def test_rephrased_question_with_supplement_ref_keeps_original_identity():
    sources=[source("电机A：处理后记录18 A以上。"),source("电机A上述记录是均值。",2)]
    q=question("S01:1","电机A","statistic_scope","统计口径和样本范围？")
    ledger={};ident=register(ledger,q,sources)
    ledger=reconcile({"updates":[update(q,"partial","上述记录是均值","均值","样本范围？")]},ledger,sources,{"S02"})
    follow={**q,"key":"another_key","refs":["S01:1","S02:1"],"ask":"样本范围？"}
    assert register(ledger,follow,sources)==ident and len(ledger)==1


def test_condition_mismatch_is_not_automatically_paired():
    sources=[source("电机A：室温均值判据≥16 A；低温处理后记录18 A以上。")]
    assert program_questions(sources)==[]


def test_correction_quoting_old_unit_error_does_not_open_duplicate_issue():
    sources=[source("电机A：静态功耗37 mA。"),source("更正电机A原记录静态功耗37 mA，应为静态电流37 mA。",2)]
    assert len(program_questions(sources))==1


def test_normalized_reporting_limits_keep_quotes_and_log_changes():
    from fs_agent.doc_logic import normalize_limits
    sources=[source("此输入没有图片像素。")]
    v=candidate(sources,assessment="提交记录为非实测数据。")
    v["evidence"][0].update(claim="本轮无法视觉核验",relation="不足")
    original=copy.deepcopy(v["evidence"][0]["quote"])
    v,repairs=normalize_limits(v,sources)
    assert "非实测" not in v["assessment"] and "本轮未独立复核" in v["assessment"]
    assert v["evidence"][0]["quote"]==original and v["evidence"][0]["relation"]=="支持"
    assert {r["rule"] for r in repairs}=={"L04","L14"}
    # The same absence is insufficient for the positive factual claim.
    v["evidence"][0].update(claim="图A确实正常",relation="不足")
    assert not mechanical_issues(v,sources)


def test_explicit_no_gap_is_not_a_stage_gate_and_real_missing_record_survives():
    from fs_agent.doc_logic import normalize_limits
    sources=[source("已补齐记录。")]
    v=candidate(sources);v["gaps"]=["无。样本与判据已明确，无其他影响判断的缺口。", "无历史记录，仍无法判断历史原因。"]
    fixed,_=normalize_limits(v,sources)
    assert fixed["gaps"]==["无历史记录，仍无法判断历史原因。"]


def test_negating_a_false_nonmeasured_inference_is_not_that_inference():
    sources=[source("工程师提交重校后恢复记录。")]
    v=candidate(sources,assessment="记录来自提交，本轮未独立复核，不推断为非实测。")
    assert not mechanical_issues(v,sources)


def test_independent_sections_are_not_required_to_cross_compare():
    sources=[source("三个独立小节：一次重校后恢复；外部导线跨接后通信恢复；构造报警后恢复。")]
    v=candidate(sources);v["next"]=["补充对照试验以区分S01:1和S01:2的操作贡献。"]
    assert mechanical_issues(v,sources)


def test_cross_section_requirement_is_narrowed_to_the_actual_history_boundary():
    from fs_agent.doc_logic import normalize_limits
    sources=[source("三个独立小节：重校恢复；跨接恢复；构造报警后恢复。均无历史形成记录。")]
    v=candidate(sources);v["gaps"]=["S01:1和S01:2缺乏区分单一操作贡献的对照记录。"]
    v["next"]=["做对照试验，区分两者之间的贡献。"]
    v,repairs=normalize_limits(v,sources)
    assert "历史" in v["gaps"][0] and "对照" not in v["gaps"][0]
    assert any(r["rule"]=="L02" for r in repairs)
