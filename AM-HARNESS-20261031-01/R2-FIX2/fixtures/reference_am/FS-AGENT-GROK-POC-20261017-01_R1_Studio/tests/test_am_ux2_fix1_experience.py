"""Scenario walkthrough using only rendered button labels, synthetic ports.

This is an agent cognitive walkthrough, not a human blind usability study.
"""
import json,os
from pathlib import Path
import pytest
from test_am_ux1 import ux,service,am_rig,base_rig,request,latest,text
from test_gateway import drain
from fs_agent.presentation import visible_metrics


def nodes(value):
    if isinstance(value,dict):
        yield value
        for v in value.values():yield from nodes(v)
    elif isinstance(value,list):
        for v in value:yield from nodes(v)


class Walk:
    def __init__(self,rig):self.rig=rig;self.steps=[]
    def see(self,action):
        card=json.loads(text(self.rig));items=list(nodes(card))
        self.steps.append({'action':action,'title':card['header']['title']['content'],
            'visible_text':[x['content'] for x in items if x.get('tag') in ('plain_text','markdown') and 'content' in x],
            'buttons':[x['text']['content'] for x in items if x.get('tag')=='button'],
            'metrics':visible_metrics(card)})
    def press(self,label,form=None):
        am,g,s,api,clock,_=self.rig
        buttons=[b for b in nodes(json.loads(text(self.rig))) if b.get('tag')=='button' and b['text']['content']==label]
        assert len(buttons)==1,(label,self.steps[-1]['buttons'])
        c=latest(self.rig);ident='experience-'+str(len(self.steps))
        e={'header':{'app_id':g.config.app_id,'tenant_key':g.config.tenant_key,'event_id':ident,'event_type':'card.action.trigger'},
           'event':{'operator':{'open_id':am.owner},'context':{'open_chat_id':'oc_dm','open_message_id':c['message_id']},
                    'action':{'value':buttons[0]['behaviors'][0]['value'],'form_value':form}}}
        assert am.ingest(e)==(True,True);assert am.step();drain(g)
        assert s.rows('SELECT state FROM am_inbox WHERE id=?',(ident,))[0]['state']=='done'
        self.see(label)
    def save(self,name,**result):
        folder=os.environ.get('AM_FIX1_UX_EVIDENCE')
        if folder:
            p=Path(folder);p.mkdir(parents=True,exist_ok=True)
            (p/(name+'.json')).write_text(json.dumps({'layer':'synthetic_label_driven_cognitive_walkthrough','human_blind_test':False,'steps':self.steps,**result},ensure_ascii=False,indent=2)+'\n')


def test_novice_can_ask_without_command(ux):
    request(ux,'需求75谁负责',1);walk=Walk(ux);walk.see('直接输入自然语言问题')
    assert 'AR1测试甲' in text(ux) and '实际收货' not in text(ux)
    walk.save('natural-query',completed=True,input_actions=1,limitation='首屏没有提示可直接用自然语言查询；知道能提问时一次输入可完成。')


def test_novice_search_people_and_return(ux):
    request(ux,'/menu',1);walk=Walk(ux);walk.see('常驻菜单打开我的工作')
    walk.press('搜索',{'query':'需求75'})
    target='查看'
    walk.press(target);walk.press('人员')
    assert 'AR1测试甲' in text(ux)
    walk.press('返回项目列表')
    assert json.loads(latest(ux)['snapshot'])['fields']['query']['default']=='需求75'
    walk.save('search-people-return',completed=True,clicks_to_people_from_home=3,return_context_preserved=True,
              limitation='搜索是辅助动作；从列表查看人员需两次点击。')


def test_novice_briefing_details_and_todos(ux):
    request(ux,'/menu',1);walk=Walk(ux);walk.see('常驻菜单打开我的工作')
    walk.press('更多');walk.press('变化简报');walk.press('完整变化');walk.press('返回简报');walk.press('候选待办')
    assert '跟进' in text(ux)
    walk.save('briefing-details',completed=True,clicks_to_summary_from_home=2,clicks_to_full_changes_from_home=3,
              limitation='“候选待办”需要理解它与已创建 AM 跟进事项的区别。')


def test_novice_todo_pagination(ux):
    ux[-1].values += [[f'需求{n}:合成项目{n}','','',f'跟进报告{n}','处理中','合成人员',''] for n in range(80,88)]
    request(ux,'/menu',1);walk=Walk(ux);walk.see('常驻菜单打开我的工作')
    first=text(ux);walk.press('下一页')
    assert text(ux)!=first and len([b for b in walk.steps[-1]['buttons'] if b=='查看'])<=5
    walk.press('上一页');walk.save('project-pages',completed=True,page_size=5,limitation='仅合成走查，非真人验收。')


def test_navigation_delivery_revocation_is_not_cached(ux,monkeypatch):
    reader=ux[-1].read
    def revoke():
        result=reader()
        ux[-1].authorize_user=lambda u: (_ for _ in ()).throw(RuntimeError('REVOKED'))
        return result
    monkeypatch.setattr(ux[-1],'read',revoke)
    request(ux,'需求75谁负责',1)
    assert not ux[3].sent
    assert ux[2].rows('SELECT state,error FROM outbox')[0]=={'state':'rejected','error':'DELIVERY_AUTH_OR_TTL'}
