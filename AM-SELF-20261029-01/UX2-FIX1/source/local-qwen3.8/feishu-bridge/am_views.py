"""Small business projections and paged detail views over existing services."""
import json
import math
from datetime import datetime
from fs_agent.config import BoundaryError
from fs_agent.project_catalog import canonical,digest
from fs_agent.scheduler import TZ
from group_ledger import render_project,SOURCE,SHEET
from source_views import project_data,render_data

SIZE=5
KINDS={'received':'已收到','processing':'处理中','eta':'预计时间','help':'需要协助','submitted':'提交材料','not_mine':'非本人负责'}
STATES={'waiting':'待反馈','in_progress':'处理中','blocked':'受阻','submitted':'已提交待核验','closed':'已关闭','cancelled':'已取消'}

def stamp(t):return datetime.fromtimestamp(t,TZ).strftime('%Y-%m-%d %H:%M') if t and math.isfinite(t) else '无下一次'
def short(value,limit=140,fallback='内容较长，请打开详情查看完整范围与条件。'):
    return value if len(value)<=limit else fallback

def paging(rows,page,size=SIZE):
    page=max(0,min(int(page),max(0,(len(rows)-1)//size)))
    return rows[page*size:(page+1)*size],page,f'第 {page+1} / {max(1,math.ceil(len(rows)/size))} 页 · 共 {len(rows)} 项'

def page_actions(page,count,base,size=SIZE):
    out=[]
    if page:out.append(('上一页',dict(base,offset=page-1)))
    if (page+1)*size<count:out.append(('下一页',dict(base,offset=page+1)))
    return out

class ViewsMixin:
    def ux_home(self,row):
        if row['user']!=self.owner:raise BoundaryError('OWNER_ONLY')
        rows=self.s.rows("SELECT * FROM action_items WHERE owner=? AND state NOT IN ('closed','cancelled') ORDER BY CASE state WHEN 'blocked' THEN 0 WHEN 'submitted' THEN 1 ELSE 2 END, CASE WHEN next_check IS NULL THEN 1 ELSE 0 END,next_check,created,id",(self.owner,))
        lines=[f'当前有 {len(rows)} 项 AM 跟进事项。']
        for i,r in enumerate(rows[:3],1):lines.append(f"{i}. {short(r['description'],55,'跟进事项（打开查看全文）')} · {STATES[r['state']]}")
        if not rows:lines.append('可从项目查看台账待办，或进入更多处理资料。')
        actions=[('查看全部待办',{'page':'work'}),('项目',{'page':'projects'}),('更多',{'page':'more'})]
        collection=self.ux_collection_at_receipt(row)
        if collection and collection['state']=='active':
            lines.append('当前仍在收集资料；结束后可恢复普通聊天。')
            actions[0]=('结束收集',{'page':'cancel_collect'})
        return self.ux_page(row,'我的工作','\n'.join(lines),actions)

    def ux_projects(self,row,*,next='project',query='',page=0):
        from group_ledger import select_projects
        if not self.flags['query']:raise BoundaryError('QUERY_NOT_ENABLED')
        rows=self.projects(row)
        if query:rows=select_projects(query,rows)
        selected,page,label=paging(rows,page)
        origin={'page':'projects','next':next,'query':query,'offset':page}
        actions=[(p['title'],{'page':next,'project':p['key'],'origin':origin}) for p in selected if p.get('identity_status')=='verified']
        unverified=sum(p.get('identity_status')!='verified' for p in selected)
        if unverified:label+=f'\n本页 {unverified} 项身份待核实，暂不可绑定。'
        actions+=page_actions(page,len(rows),origin)+[('返回首页',{'page':'home'})]
        return self.ux_page(row,'项目',label+('\n未找到匹配项目，请修改关键词。' if not rows else '\n选择项目查看详情。'),actions,
            fields={'query':{'label':'名称或编号','required':False,'default':query}},submit=('搜索',{'page':'search','next':next}),data={'origin':origin})

    def ux_project_detail(self,row,key,section=None,origin=None):
        p=self.ux_project(row,key);self.save_session(row,key,None)
        origin=origin or row.get('_list_origin') or {'page':'projects'}
        row['_list_origin']=origin
        fields={'dates':['schedule'],'people':['people'],'todos':['todo'],'source':[],'full':list(('progress','schedule','people','todo'))}.get(section,['progress'])
        projection=project_data(p,fields,detail=section=='full')
        text=render_project(p,fields,self.s.clock(),detail=section=='full')
        if section=='source':text=p['title']+'\n来源：'+SOURCE+'?sheet='+SHEET+'\n读取：'+stamp(self.s.clock())+'\n记录版本已绑定本次读取；来源日期不代表完成或验收。'
        back={'page':'project','project':key,'origin':origin}
        if section:
            actions=[('其他栏目',dict(back,section='sections')),('返回概览',back),('返回项目列表',origin)]
        else:actions=[('查看栏目',dict(back,section='sections')),('项目操作',{'page':'project_actions','project':key,'origin':origin}),('返回项目列表',origin)]
        if section=='sections':
            text='选择需要查看的内容。'
            actions=[(label,dict(back,section=part)) for label,part in [('关键日期','dates'),('人员与职责','people'),('待办','todos'),('查看来源','source'),('完整原文','full')]]+[('返回概览',back)]
        return self.ux_page(row,p['title'],text,actions,data={'origin':origin,'subject_refs':[key],'facts':projection['facts'],'mandatory_qualifiers':[q for f in projection['facts'] for q in f['qualifiers']] if section not in ('sections','source') else [],'source_revision':projection['source_revision'],'detail':section=='full'})

    def ux_work(self,row,page=0):
        projects=self.projects(row)
        rows=[{'kind':'candidate','id':p['key'],'title':p['title'],'text':p.get('待办','')} for p in projects if p.get('待办','').strip() not in ('','—')]
        rows += [dict(r,kind='item',title=short(r['description'],65,'AM 跟进事项'),text=STATES[r['state']]) for r in self.s.rows('SELECT * FROM action_items WHERE owner=? ORDER BY updated DESC,id',(self.owner,))]
        selected,page,label=paging(rows,page,3);lines=[label];actions=[]
        for i,r in enumerate(selected,1):
            prefix='台账候选' if r['kind']=='candidate' else 'AM 跟进'
            from query_rules import identifiers
            title=r['title']
            if len(title)>45 and identifiers(title):title='、'.join(identifiers(title))
            lines.append(f"{i}. {prefix}｜{title}\n{short(r['text'],65)}")
            target={'page':'project','project':r['id'],'section':'todos'} if r['kind']=='candidate' else {'page':'item','item':r['id']}
            actions.append((f"{i}. 查看{prefix}",target))
        if not rows:lines.append('当前未记录待办；不代表项目全部完成。')
        actions+=page_actions(page,len(rows),{'page':'work'},3)+[('返回首页',{'page':'home'}),('更多',{'page':'more'})]
        return self.ux_page(row,'待办与跟进','\n'.join(lines),actions)

    def ux_item_text(self,item):
        latest=json.loads(item['latest_feedback']) if item['latest_feedback'] else None
        lines=[json.loads(item['source']).get('project_title','项目归属待核对'),short(item['description']),
            '状态：'+STATES[item['state']]+('（暂停）' if item['paused'] else ''),'下次检查：'+stamp(item['next_check'])]
        if latest:lines+=['最新有效反馈：'+KINDS.get(latest['kind'],latest['kind'])+'；'+short(latest['body'],100)]
        lines.append('材料提交仍需核验。' if item['state']!='closed' else '已按核验依据关闭。')
        return '\n'.join(lines)

    def ux_item(self,row,ident):
        item=self.items.get(ident)
        if item['owner']!=row['user']:raise BoundaryError('OWNER_ONLY')
        return self.ux_page(row,'事项详情',self.ux_item_text(item),[('跟进操作',{'page':'item_actions','item':ident}),('反馈记录',{'page':'history','item':ident}),('完整事项',{'page':'item_full','item':ident})])

    def ux_feedback_notice(self,row,item,summary,event):
        # Dedup uses the operation actually claimed by ActionItems, not delivery
        # event IDs. Separate recipient/kind keys preserve the two notices.
        return self.ux_page(row,'新增反馈',summary,[('查看事项',{'page':'item','item':item['id']}),('反馈记录',{'page':'history','item':item['id']})],data={'immutable':True,'business_event':event,'notice_kind':'feedback_owner'})

    def ux_proposal(self,row,p,section=None):
        r=self.updates.collection(p['collection_id']);basis=json.loads(p['basis']);patches=json.loads(p['patches'])
        if row['user']!=self.owner:raise BoundaryError('OWNER_ONLY')
        current=r['version']==p['collection_version'] and r['state']!='withdrawn'
        text=basis['title']+'\n'+('内容已核对' if r['reporter_confirmed'] else '已收集，待核对')+'；正式台账未写入。\n报告人自报，不代表专业验收。'
        actions=[]
        if section=='diff':
            text='\n\n'.join([basis['title']]+[f"字段：{k}\n修改前全文：\n{v['before']}\n修改后全文：\n{v['after']}" for k,v in patches.items()])
        elif section=='source':text='报告人原话与解释（自报待核验）：\n'+'\n'.join(f['original']+'｜'+f['status'] for f in json.loads(r['facts']))
        if current and not r['reporter_confirmed'] and r['reporter']==row['user']:
            actions.append(('确认内容',{'page':'review_content','proposal':p['id'],'version':p['version'],'collection_version':r['version']}))
        actions += [('查看精确差异',{'page':'proposal','proposal':p['id'],'section':'diff'}),('查看原话与解释',{'page':'proposal','proposal':p['id'],'section':'source'}),('继续补充',{'page':'collect','project':p['project_ref']}),('结束收集',{'page':'cancel_collect'})]
        return self.ux_page(row,'进展提案',text,actions,data={'subject_refs':[p['project_ref']],'full_preview':section=='diff'})

    def ux_status(self,row):
        counts=self.s.rows("SELECT state,count(*) n FROM reminder_occurrences WHERE state IN ('unknown','sending') GROUP BY state")
        n=sum(x['n'] for x in counts)
        return self.ux_page(row,'运行状态',f'正式台账写回：未启用。\n发送结果待核对：{n} 项。\n查询、资料收集和提案可分别使用。',[('提醒计划',{'page':'plans'}),('维护诊断',{'page':'diagnostics'}),('返回首页',{'page':'home'})])

    def ux_plan_detail(self,row,ident):
        p=self.scheduler.plan(ident)
        if p['owner']!=row['user']:raise BoundaryError('OWNER_ONLY')
        states={'draft':'待确认','active':'已启用','paused':'已暂停','cancelled':'已取消','expired':'已到期'}
        target=json.loads(p['target']);who='本人私聊' if target['kind']=='owner' else target['payload']['group']['name']
        occurrences=self.s.rows('SELECT * FROM reminder_occurrences WHERE plan_id=? ORDER BY scheduled_at DESC',(ident,))
        lines=['状态：'+states.get(p['state'],p['state']),'目标：'+who,'下一次：'+stamp(p['next_at'])]
        if occurrences:lines.append('最近结果：'+self.ux_occurrence_status(occurrences[0]))
        actions=[]
        if p['state']=='active':actions.append(('暂停计划',{'page':'plan_control','plan':ident,'version':p['version'],'control':'pause'}))
        if p['state']=='paused':actions.append(('恢复并重新预览',{'page':'plan_control','plan':ident,'version':p['version'],'control':'resume'}))
        if p['state']=='draft':actions.append(('查看完整预览',{'page':'plan_preview','plan':ident}))
        actions += [('规则与正文',{'page':'plan_rules','plan':ident}),('发送记录',{'page':'occurrences','plan':ident}),('返回计划',{'page':'plans'})]
        return self.ux_page(row,'提醒计划','\n'.join(lines),actions)

    def ux_run_precheck(self,row,ident):
        logic=self.g.logic;d=logic.get(row,ident);sources=json.loads(d['sources'])
        for source in logic.business.sources(row,json.loads(d['target'])):
            if source['id'] not in {s['id'] for s in sources}:sources.append(source)
        content,report=logic.evaluate_precheck(row,d,sources)
        complete=bool(sources) and all(s['read_status']=='complete' for s in sources)
        text=('本次材料读取完整；此结果为资料检查。' if complete else '材料未完整读取，暂不能判断是否齐备。')
        text+='\n待补 '+str(len(report['缺少']))+' 项；冲突 '+str(len(report['冲突']))+' 项；需专业判断 '+str(len(report['需专业判断']))+' 项。'
        for x in (report['缺少']+report['冲突'])[:2]:text+='\n'+short(x['finding'],95,'该项存在缺口，详见完整报告。')
        fresh=logic.get(row,ident)
        return self.ux_page(row,'资料预检结果',text,[('补充材料',{'page':'precheck_continue','draft':ident}),('完整报告',{'page':'precheck_report','draft':ident,'revision':fresh['revision']}),('结束收集',{'page':'cancel_collect'})],data={'report_snapshot':content,'report_revision':fresh['revision']})

    def ux_extra(self,row,a,values,data):
        page=a['page']
        if page=='long_content':
            saved=dict(data,_long_index=a['offset']);content=saved['_long_view']
            return self.ux_page(row,content['title'],content['text'],content['actions'],data=saved)
        if page=='briefing_detail':return self.ux_briefing(row,data['briefing_snapshot'],a.get('section'),a.get('offset',0))
        if page=='documents':return self.ux_documents(row,a)
        if page=='project_actions':
            p=self.ux_project(row,a['project']);actions=[]
            origin=a.get('origin') or row.get('_list_origin') or {'page':'projects'}
            if self.flags['scheduler']:actions.append(('创建提醒',{'page':'remind','project':p['key']}))
            if self.flags['progress_collection']:actions.append(('更新进展',{'page':'collect','project':p['key']}))
            return self.ux_page(row,'项目操作',p['title'],actions+[('返回项目',{'page':'project','project':p['key'],'origin':origin})],data={'origin':origin})
        if page in ('history','item_full','item_actions'):
            item=self.items.get(a['item'])
            if item['owner']!=row['user']:raise BoundaryError('OWNER_ONLY')
            back=[('返回事项',{'page':'item','item':item['id']}),('返回全部跟进',{'page':'work'})]
            if page=='history':
                rows=list(reversed(self.items.history(item['id'])));selected,num,label=paging(rows,a.get('offset',0))
                people={p['id']:p['name'] for p in json.loads(item['source']).get('target',{}).get('people',[])}
                lines=[label]+[people.get(h['actor'],'授权反馈人')+'｜'+KINDS[h['kind']]+'｜'+('有效反馈' if h['applied'] else '迟到留证')+'｜'+stamp(h['created'])+'\n'+(h['body'] or '无补充') for h in selected]
                return self.ux_page(row,'反馈记录','\n\n'.join(lines),page_actions(num,len(rows),a)+back,data={'detail':True})
            if page=='item_full':return self.ux_page(row,'完整事项',item['description']+'\n交付要求：'+(item['requirements'] or '待确认')+'\n核验关闭依据：'+(item['close_evidence'] or '尚未核验关闭'),back,data={'detail':True})
            actions=[]
            if item['state'] not in ('closed','cancelled'):
                choices=[('设置检查时间','check'),('恢复跟进','resume') if item['paused'] else ('暂停跟进','pause'),('核验并关闭','close')]
                actions=[(label,{'page':'item_action_form','item':item['id'],'version':item['version'],'control':control}) for label,control in choices]
                if not item['paused']:actions.append(('创建提醒',{'page':'remind','project':item['project_ref'],'item':item['id']}))
            return self.ux_page(row,'跟进操作',STATES[item['state']],actions+back)
        if page=='proposal':return self.ux_proposal(row,self.updates.proposal(a['proposal']),a.get('section'))
        if page=='review_content':
            p=self.updates.proposal(a['proposal']);r=self.updates.collection(p['collection_id'])
            if p['version']!=a['version'] or p['collection_version']!=r['version'] or r['version']!=a['collection_version'] or p['expires']<=self.s.clock():raise BoundaryError('PROPOSAL_VERSION_CHANGED')
            self.updates.confirm_reporter(row['user'],r['id'],r['version'])
            return self.ux_proposal(row,p)
        if page=='precheck_report':
            d=self.g.logic.get(row,a['draft']);content=data.get('report_snapshot')
            if content is None:raise BoundaryError('REPORT_SNAPSHOT_UNAVAILABLE')
            label='完整报告'+('（旧版本）' if d['revision']!=a['revision'] else '')
            return self.ux_page(row,label,content,[('返回当前检查',{'page':'precheck_result','draft':d['id']})],data={'detail':True})
        if page=='precheck_result':return self.ux_run_precheck(row,a['draft'])
        if page=='diagnostics':return self.ux_page(row,'维护诊断',self.handle(dict(row,kind='text',body='/diagnostics')),[('返回状态',{'page':'status'})],data={'detail':True})
        if page=='plan_preview':return self.plan_card(row,self.scheduler.plan(a['plan']))
        if page=='plan_rules':
            p=self.scheduler.plan(a['plan']);text=self.plan_preview_text(p)
            actions=[('返回计划',{'page':'plan','plan':p['id']})]
            if p['state'] not in ('cancelled','expired'):actions.append(('取消计划',{'page':'plan_control','plan':p['id'],'version':p['version'],'control':'cancel'}))
            return self.ux_page(row,'完整规则与正文',text,actions,data={'detail':True})
        if page=='occurrences':
            p=self.scheduler.plan(a['plan'])
            if p['owner']!=row['user']:raise BoundaryError('OWNER_ONLY')
            rows=self.s.rows('SELECT * FROM reminder_occurrences WHERE plan_id=? ORDER BY scheduled_at DESC',(p['id'],));selected,num,label=paging(rows,a.get('offset',0))
            actions=[(self.ux_occurrence_status(o),{'page':'reconcile','occurrence':o['id']}) for o in selected if o['state'] in ('unknown','sending','sent') and o['readback_state']!='verified']
            return self.ux_page(row,'发送记录',label+'\n'+'\n'.join(self.ux_occurrence_status(o) for o in selected),actions+page_actions(num,len(rows),a)+[('返回计划',{'page':'plan','plan':p['id']})])
        raise BoundaryError('CARD_ACTION_NOT_SUPPORTED')
