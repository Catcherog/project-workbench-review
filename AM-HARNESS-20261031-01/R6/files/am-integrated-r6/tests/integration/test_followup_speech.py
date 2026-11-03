"""Synthetic speech contracts; these are not human labels or held-out cases."""
import copy
import pytest

from am_style.contracts import ContractError, StylePolicy
from am_style.followup import FollowupSpeech, project_followup, render_followup
from am_style.verify import CompositeVerifier


def value(state="unknown"):
    return {"schema_version":"am-followup-speech/1",
        "binding":{"turn_id":"turn","scope":["tenant","app","chat","owner"],
            "source_revision":"1","item_version":3,"semantic_version":2,"cancel_epoch":1,
            "owner_id":"owner","requester_id":"owner"},
        "expires_at":1000,"question":"这个跟进怎么样了？",
        "item":{"id":"item","label":"核对开测","state":"waiting","paused":False,
            "verifier":"owner","closed_by":None,"close_evidence_sha256":None},
        "delivery":{"state":state,"occurrence_id":"occ","intent_id":"intent","request_uuid":"req",
            "message_id":"message","body_sha256":"a"*64,"target_sha256":"b"*64,"receipt":None},
        "feedback":[],"readback_job":None}


def verified():
    v=value("verified")
    v["delivery"]["receipt"]={k:v["delivery"][k] for k in ("occurrence_id","intent_id","request_uuid","message_id","body_sha256","target_sha256")}
    return v


def job(v):
    j={k:v["delivery"][k] for k in ("occurrence_id","request_uuid","body_sha256","target_sha256","message_id")}
    j.update(job_id="job",kind="original_scheduler_readback",state="queued",not_before=900,expires_at=1000)
    v["readback_job"]=j
    return v


def test_unknown_without_job_never_promises_check_or_resend():
    text=render_followup(FollowupSpeech.freeze(value()))
    assert "还没核实" in text and "暂时不会重发" in text
    assert "我确定一下" not in text and "正在核对" not in text


def test_exact_native_job_allows_acknowledged_style_phrase():
    text=render_followup(FollowupSpeech.freeze(job(value())))
    assert "我确定一下" in text and "暂时不会重发" in text


@pytest.mark.parametrize("key",["occurrence_id","request_uuid","message_id","body_sha256","target_sha256"])
def test_job_cannot_be_borrowed_for_different_send(key):
    v=job(value());v["readback_job"][key]="wrong"
    with pytest.raises(ContractError):FollowupSpeech.freeze(v)


@pytest.mark.parametrize("key",["occurrence_id","intent_id","request_uuid","message_id","body_sha256","target_sha256"])
def test_receipt_must_match_entire_send(key):
    v=verified();v["delivery"]["receipt"][key]="wrong"
    with pytest.raises(ContractError):FollowupSpeech.freeze(v)


def test_owner_reply_does_not_invent_second_person_or_business_completion():
    v=verified();v["feedback"]=[dict(message_id="reply",occurrence_id="occ",actor="owner",kind="reported_update")]
    text=render_followup(FollowupSpeech.freeze(v))
    assert "你的自报进展" in text and "尚未核验完成" in text
    assert "负责人" not in text and "已经完成" not in text


def test_acknowledgement_not_delivery_acceptance():
    v=verified();v["feedback"]=[dict(message_id="reply",occurrence_id="occ",actor="engineer",kind="acknowledged")]
    text=render_followup(FollowupSpeech.freeze(v))
    assert "负责人已回应" in text and "尚未核验完成" in text


def test_close_requires_verifier_and_actual_evidence_digest():
    v=verified();v["item"].update(state="closed",closed_by="engineer",close_evidence_sha256="c"*64)
    with pytest.raises(ContractError):FollowupSpeech.freeze(v)
    v["item"]["closed_by"]="owner"
    assert "核验依据关闭" in render_followup(FollowupSpeech.freeze(v))


def test_semantic_version_and_reply_changes_change_fingerprint():
    a=value();b=copy.deepcopy(a);b["binding"]["semantic_version"]+=1
    assert FollowupSpeech.freeze(a).fingerprint!=FollowupSpeech.freeze(b).fingerprint
    b=copy.deepcopy(a);b["feedback"]=[dict(message_id="r",occurrence_id="occ",actor="owner",kind="acknowledged")]
    assert FollowupSpeech.freeze(a).fingerprint!=FollowupSpeech.freeze(b).fingerprint


def test_model_cannot_omit_business_qualification():
    snap=FollowupSpeech.freeze(verified());frame=project_followup(snap)
    text=render_followup(snap)
    verifier=CompositeVerifier()
    assert verifier.verify(frame,text,StylePolicy()).decision=="pass"
    candidate=text.replace("事项仍在跟进中，尚未核验完成。","")
    assert verifier.verify(frame,candidate,StylePolicy()).decision!="pass"


def test_model_cannot_promote_unknown_to_sent():
    frame=project_followup(FollowupSpeech.freeze(value()))
    assert CompositeVerifier().verify(frame,"已经发送成功。",StylePolicy()).decision!="pass"


def test_snapshot_is_immutable_and_revalidated():
    v=value();snapshot=FollowupSpeech.freeze(v);v["item"]["label"]="changed"
    assert snapshot.data["item"]["label"]=="核对开测"
    malformed=FollowupSpeech('{"schema_version":"untrusted"}')
    with pytest.raises(ContractError):project_followup(malformed)


def test_scope_is_owner_bound():
    v=value();v["binding"]["requester_id"]="someone_else"
    with pytest.raises(ContractError):FollowupSpeech.freeze(v)
