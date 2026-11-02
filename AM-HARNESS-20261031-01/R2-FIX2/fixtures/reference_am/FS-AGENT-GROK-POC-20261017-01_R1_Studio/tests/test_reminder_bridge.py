"""The actual ordinary-chat bridge must not learn reminder drafts or confirmations."""
import json
from dataclasses import replace
from fs_agent.provider import Result
from test_embedded import rig,event
from test_reminder import Port,TEXT,FIELDS
from test_gateway import drain

def test_R09_bridge_does_not_store_reminder_in_ordinary_chat_and_returns_after_cancel(rig):
    b,api,provider,calls,replies=rig;g=b.poc.gateway;s=g.store
    g.config=replace(g.config,reminders_enabled=True,document_logic=True);b.poc.config=g.config
    g.reminders.port=Port(s.clock);g.reminders.port.group_info["tenant"]="tenant"
    provider.complete=lambda prompt,**kw:Result(json.dumps(FIELDS,ensure_ascii=False),"fixture",.01)
    assert b.ingest(event(TEXT,1));g.receive_one();task=s.claim(1);g.run_task(task);drain(g)
    assert b.db.execute("SELECT count(*) FROM inbox").fetchone()[0]==0
    assert b.db.execute("SELECT count(*) FROM turns").fetchone()[0]==0
    assert b.ingest(event("/remind 取消",2));g.receive_one();drain(g)
    assert not g.reminders.focused(task)
    assert b.ingest(event("现在说一句普通问候",3));assert b.process_one()
    history=b.db.execute("SELECT usertext,answer FROM turns").fetchall()
    assert len(history)==1 and history[0][0]=="现在说一句普通问候"
    assert not g.reminders.port.sent
