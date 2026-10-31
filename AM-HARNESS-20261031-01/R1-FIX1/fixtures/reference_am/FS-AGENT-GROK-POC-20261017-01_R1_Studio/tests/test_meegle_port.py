"""Synthetic Meegle contract tests; no network, credentials, or real project IDs."""
import copy,json
from pathlib import Path
import pytest
from fs_agent.doc_logic import digest
from fs_agent.config import BoundaryError
from fs_agent.meegle_port import MeeglePort
from test_doc_logic import rig, ready
from test_gateway import rig as base_rig

def port_fixture(g):
    binary=g.config.root/"bin"/"meegle"
    binary.parent.mkdir();binary.write_bytes(b"synthetic-not-executable")
    settings={"executable":str(binary),"sha256":digest(binary.read_bytes()),"profile":"fs-doc-logic-r1",
              "allowed_user":"ou_a","user_key":"project-user-A","targets":{"report":{
                  "space":"space-A","project":"100","node":"state-test","deliverable":"200","type":"deliverable",
                  "attachment_field":"files","approval_field":"review","node_field":"node","project_field":"parent",
                  "document_field":"doc","delivery_mode_field":"mode","unreviewed_value":"not_reviewed",
                  "url":"https://project.invalid/report"}}}
    port=MeeglePort(g,settings)
    state={"files":None,"revision":"r1","review":"not_reviewed","updates":0,"uploads":0,"calls":[],"identity":"project-user-A","race":False,"links":[200],"data":{}}
    def run(args, *, params=None, json_result=True):
        state["calls"].append(args[:2])
        if args[:2]==["user","me"]:return {"user_key":state["identity"]}
        if args[:2]==["workflow","get-node"]:
            return {"list":[{"basic":{"node_key":"state-test","status":"not_started"},
                            "sub_workitems":[{"workitems":state["links"]}]}],"pagination":{"has_more":False}}
        if args[:2]==["workitem","get"]:
            fields={"review":{"value":state["review"],"label":"未审核"},"node":"state-test","parent":{"id":100},
                    "doc":["existing-document"],"mode":{"value":"doc"}}
            if state["files"] is not None:fields["files"]=state["files"]
            return {"work_item_attribute":{"work_item_id":"200","work_item_type":{"key":"deliverable"},
                    "work_item_name":"same-name","owned_project":{"key":"space-A"},"update_time":state["revision"],
                    "work_item_status":{"key":"Not started","name":"未开始"}},
                    "work_item_fields":[{"key":k,"value":v} for k,v in fields.items()]}
        if args[:2]==["attachment","+upload"]:
            state["uploads"]+=1;name=Path(args[2]).name;state["data"][name]=Path(args[2]).read_bytes()
            if state["race"]:state["revision"]="external-edit"
            return {"file_token":"token-"+name,"file_url":"https://files.invalid/"+name,
                    "name":name,"size":len(state["data"][name]),"mime_type":"text/markdown"}
        if args[:2]==["workitem","update"]:
            assert [f["field_key"] for f in params["fields"]]==["files"]
            state["files"]=json.loads(params["fields"][0]["field_value"])
            for f in state["files"]:f["url"]="https://files.invalid/"+f["name"]
            state["updates"]+=1;state["revision"]="r2";return None
        if args[:2]==["attachment","+download"]:
            name=args[2].split("/")[-1];Path(args[args.index("--output")+1]).write_bytes(state["data"][name]);return None
        raise AssertionError(args)
    port._run=run
    return port,state,settings

def bound(rig):
    g,s,row,d=ready(rig);port,state,settings=port_fixture(g);g.logic.business=port
    target=port.resolve(row,"report");settings["targets"]["report"]["verified_empty_revision"]=target["revision"]
    g.logic.select_target(row,d["id"],"report");g.logic.adopt(row,d["id"])
    return g,s,row,d,port,state,settings

def test_exact_native_parent_upload_field_readback_and_idempotency(rig):
    g,s,row,d,port,state,settings=bound(rig)
    result=g.logic.mount(row,d["id"])
    assert result["receipt"] and state["updates"]==1 and state["uploads"]==1
    assert state["review"]=="not_reviewed"
    assert g.logic.mount(row,d["id"])["receipt"]==result["receipt"]
    assert state["updates"]==1

def test_new_identity_is_rejected_before_project_reads(rig):
    g,s,row,d,port,state,settings=bound(rig)
    state["calls"].clear();state["identity"]="another-user"
    with pytest.raises(BoundaryError,match="IDENTITY_CHANGED"):port.resolve(row,"report")
    assert state["calls"]==[["user","me"]]
    state["calls"].clear()
    with pytest.raises(BoundaryError,match="SCOPE_DENIED"):port.resolve({**row,"user":"ou_b"},"report")
    assert state["calls"]==[]

def test_native_node_membership_is_authoritative(rig):
    g,s,row,d,port,state,settings=bound(rig)
    state["links"]=[201]
    with pytest.raises(BoundaryError,match="PARENT_CHANGED"):port.resolve(row,"report")
    assert state["updates"]==0

def test_target_changed_during_upload_stops_field_mutation(rig):
    g,s,row,d,port,state,settings=bound(rig);state["race"]=True
    result=g.logic.mount(row,d["id"])
    assert result["receipt"] is None and state["updates"]==0 and state["uploads"]==1

def test_unobserved_empty_field_is_not_assumed_empty(rig):
    g,s,row,d,port,state,settings=bound(rig)
    settings["targets"]["report"].pop("verified_empty_revision")
    result=g.logic.mount(row,d["id"])
    assert result["receipt"] is None and state["updates"]==0 and state["uploads"]==0

def test_missing_permission_and_old_approval_never_write(rig):
    g,s,row,d,port,state,settings=bound(rig)
    state["review"]="approved"
    g.logic.select_target(row,d["id"],"report")
    with pytest.raises(BoundaryError,match="NO_CURRENT_DRAFT"):
        g.logic.adopt(row,d["id"])
    with pytest.raises(BoundaryError,match="REVIEWED_CONTENT_PROTECTED"):
        port.commit(row,port.resolve(row,"report"),d["content"],d["content_hash"],"synthetic-idem",lambda:True)
    assert state["updates"]==0 and state["uploads"]==0


def test_D13_readback_requires_known_old_attachment_to_remain(rig):
    g,s,row,d=ready(rig);port,state,settings=port_fixture(g);g.logic.business=port
    state['files']=[{'name':'original.md','type':'text/markdown','size':'8','fileToken':'original-token','url':'https://files.invalid/original.md'}]
    state['data']['original.md']=b'original'
    g.logic.select_target(row,d['id'],'report');g.logic.adopt(row,d['id'])
    result=g.logic.mount(row,d['id'])
    assert result['receipt']['previous_tokens']==['original-token']
    assert len(state['files'])==2 and state['updates']==1
    state['files']=[f for f in state['files'] if f['fileToken']!='original-token']
    with pytest.raises(BoundaryError,match='EXISTING_ATTACHMENT_LOST'):
        g.logic.mount(row,d['id'])
    assert state['updates']==1 and state['review']=='not_reviewed'
