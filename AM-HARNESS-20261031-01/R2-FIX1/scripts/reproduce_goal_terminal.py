"""Read-only-to-production reproduction using an isolated native conversation store."""
from pathlib import Path
import json,sys,tempfile
TASK=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TASK/'worktree/am-conversation-r1/src'))
from am_conversation.store import ConversationStore
from am_conversation.types import AccessContext
from am_outcome.goals import GoalJournal
CAT=[{'id':'p','title':'需求75','aliases':[]}]
with tempfile.TemporaryDirectory() as temp:
    path=Path(temp)/'goal.db';ctx=AccessContext('t','a','u','c',is_owner=True,content_expires_at=1000)
    store=ConversationStore(path,clock=lambda:100)
    question='明天09:30提醒我确认油脂交期';args={'target':'self','body':'确认油脂交期','frequency':'once','at':'2030-03-02T09:30:00+08:00'}
    store.claim_event(ctx,'first',question)
    goal=GoalJournal(store,ctx,'first',question,CAT)
    assert goal.before('schedule_reminder',args,'external') is None
    action=store.create_action(ctx,tool_name='schedule_reminder',arguments=args,preview='合成提醒预览')
    draft={'status':'draft','action_id':action['id'],'version':action['version'],'preview':action['preview'],'executed':False}
    goal.record('schedule_reminder',args,draft,'external')
    store.mark_presented(ctx,action['id'],expected_version=1,event_id='first')
    store.approve_action(ctx,action['id'],expected_version=1,digest=action['digest'])
    assert store.begin_execution(ctx,action['id'],expected_version=1)['claimed']
    receipt={'status':'succeeded','verified':True,'receipt_id':'synthetic-plan','message':'合成提醒计划已启用，尚无实际提醒发生记录。'}
    store.finish_execution(ctx,action['id'],status='succeeded',result=receipt)
    metadata=store.action_metadata(ctx,action['id']);authoritative=store.get_action(ctx,action['id']);store.close()
    store=ConversationStore(path,clock=lambda:101);resumed=GoalJournal(store,ctx,'next','继续',CAT)
    cached=resumed.before('schedule_reminder',args,'external')
    out={'source_commit':'e86a443367c5bfbd980103481a14039334dd6280','layer':'native_store_synthetic_action_receipt_no_platform_io','action_metadata_has_result':'result' in metadata,'authoritative_status':authoritative['status'],'authoritative_result':authoritative['result'],'resumed_completion':resumed.data['completion'],'cached_result':cached,'cached_is_authoritative_result':cached==receipt,'action_begin_claims':1,'real_business_actions':0}
    (TASK/'evidence/goal-terminal-reproduction-e86.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k not in ('authoritative_result','cached_result')},ensure_ascii=False))
    store.close()
