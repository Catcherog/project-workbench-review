"""UX1 navigation and forms over the original AM services and durable queue.

Buttons carry only a nonce and a server-owned action key. Collection is bound at
receipt to the actual user's message, scope and non-renewable context revision.
"""
import json
import re
import uuid
import math
from datetime import datetime,timedelta
from fs_agent.config import BoundaryError
from fs_agent.project_catalog import canonical,digest
from fs_agent.scheduler import TZ,parse_time
from fs_agent.reminder_content import normalized_payload
from fs_agent.card_ui import card,paragraph,button,field
from group_ledger import render_project,select_projects

MENU_KEYS={'am_work':'home','am_projects':'projects','am_more':'more'}
PAGE_SIZE=6

def card_time(value):
    if not isinstance(value,str):raise BoundaryError('FORM_TIME_REQUIRED')
    try:
        dt=datetime.strptime(value,'%Y-%m-%d %H:%M %z')
        # Feishu appends the client's timezone as reference, not a timezone
        # selected by the user. Every UX1 time field explicitly says Beijing.
        return dt.replace(tzinfo=TZ).timestamp()
    except ValueError:
        # Some clients omit an offset. The form explicitly states Beijing time.
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}',value):raise BoundaryError('FORM_TIME_REQUIRED')
        return parse_time(value,0)

class UxMixin:
    def init_ux(self):
        with self.s.lock:self.s.conn.executescript('''
        CREATE TABLE IF NOT EXISTS am_ux_drafts(id TEXT PRIMARY KEY,scope TEXT NOT NULL,version INTEGER NOT NULL,state TEXT NOT NULL,data TEXT NOT NULL,expires REAL NOT NULL,result TEXT);
        CREATE TABLE IF NOT EXISTS am_ux_collection(scope TEXT PRIMARY KEY,token TEXT NOT NULL,kind TEXT NOT NULL,target TEXT NOT NULL,expires REAL NOT NULL,state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS am_ux_receipts(id TEXT PRIMARY KEY,context TEXT NOT NULL);
        ''')

    def ux_page(self,row,title,text,actions=(),*,fields=None,submit=None,data=None):
        nonce=uuid.uuid4().hex
        actions=list(actions)
        if fields is not None:actions.append((submit[0],submit[1]))
        snapshot={'actions':{str(i):a for i,(label,a) in enumerate(actions)},'data':data or {},
                  'fields':fields,'thread':row.get('thread') or self.source_meta(row).get('thread'),
                  'app':row['app'],'tenant':row['tenant']}
        elements=[paragraph(text)] if text else []
        if fields is not None:
            inputs=[]
            for name,spec in fields.items():
                inputs+=field(name,spec['label'],kind=spec.get('kind','input'),options=spec.get('options'),default=spec.get('default'),required=spec.get('required',True))
            index=str(len(actions)-1)
            inputs.append(button(submit[0],{'flow':'am_self','nonce':nonce,'action':index},name='submit',submit=True))
            elements.append({'tag':'form','name':'ux_form','elements':inputs})
            visible=actions[:-1]
        else:visible=actions
        for i,(label,action) in enumerate(visible):elements.append(button(label,{'flow':'am_self','nonce':nonce,'action':str(i)}))
        # Split long source text without silently truncating approval content.
        expanded=[]
        for el in elements:
            if el['tag']=='div' and len(el['text']['content'])>3500:
                value=el['text']['content'];expanded += [paragraph(value[i:i+3500]) for i in range(0,len(value),3500)]
            else:expanded.append(el)
        fingerprint=digest(snapshot)
        with self.s.tx() as c:
            out=self.notify(row,card=card(title,expanded),kind='card',object_id=nonce,version=1,hash=fingerprint,conn=c)
            c.execute('INSERT INTO am_cards VALUES(?,?,?,?,?,?,?,?,?,?,NULL)',(nonce,'ux',nonce,1,row['user'],row['chat'],canonical(snapshot),fingerprint,min(row['expires'],self.s.clock()+3600),out))
            if c.execute('SELECT 1 FROM am_query_refs WHERE message_id=? AND expires>?',(row['id'],self.s.clock())).fetchone():
                c.execute("UPDATE am_notifications SET kind='query',object_id=? WHERE outbox_id=?",(row['id'],out))

    def ux_home(self,row):
        if row['user']!=self.owner:raise BoundaryError('OWNER_ONLY')
        self.ux_cancel_collection(row)
        entries=[('query','项目查询',{'page':'projects'}),('items','待办与跟进',{'page':'work'}),
                 ('scheduler','创建提醒',{'page':'projects','next':'remind'}),('snapshots','变化简报',{'page':'briefing'}),
                 ('progress_collection','更新进展',{'page':'projects','next':'collect'}),('precheck','资料预检',{'page':'targets'})]
        return self.ux_page(row,'我的工作','选择要处理的工作。',[(label,a) for flag,label,a in entries if self.flags[flag]])

    def ux_cancel_collection(self,row,all_chat=False):
        scopes=[self.scope(row)]
        if all_chat:
            prefix=[row[k] for k in ('tenant','app','chat','user')]
            scopes=[r['scope'] for r in self.s.rows('SELECT scope FROM am_ux_collection') if json.loads(r['scope'])[:4]==prefix]
        for scope in scopes:self.s.execute("UPDATE am_ux_collection SET state='cancelled',target='{}' WHERE scope=?",(scope,))

    def ux_project(self,row,key):
        matches=[p for p in self.projects(row) if p['key']==key and p.get('identity_status')=='verified']
        if len(matches)!=1:raise BoundaryError('PROJECT_IDENTITY_UNVERIFIED')
        return matches[0]

    def ux_projects(self,row,*,next='project',query='',page=0):
        if not self.flags['query']:raise BoundaryError('QUERY_NOT_ENABLED')
        projects=self.projects(row)
        if query:projects=select_projects(query,projects)
        selected=projects[page*PAGE_SIZE:(page+1)*PAGE_SIZE]
        actions=[]
        for p in selected:
            if p.get('identity_status')=='verified':actions.append((p['title'],{'page':next,'project':p['key']}))
        text='选择项目，或填写名称关键词。'
        if not projects:text='未找到匹配项目，请修改关键词。'
        if any(p.get('identity_status')!='verified' for p in selected):text+='部分候选身份尚未核实，暂不可绑定。'
        if page:actions.append(('上一页',{'page':'projects','next':next,'query':query,'offset':page-1}))
        if (page+1)*PAGE_SIZE<len(projects):actions.append(('下一页',{'page':'projects','next':next,'query':query,'offset':page+1}))
        actions.append(('返回首页',{'page':'home'}))
        return self.ux_page(row,'项目',text,actions,fields={'query':{'label':'项目名称或编号','required':False,'default':query}},submit=('搜索',{'page':'search','next':next}))

    def ux_project_detail(self,row,key,section=None):
        p=self.ux_project(row,key);self.save_session(row,p['key'],None)
        fields={'dates':['关键日期'],'people':['人员与职责'],'todos':['待办'],'source':[]}.get(section,['项目进展','人员与职责','关键日期','待办'])
        text=render_project(p,fields,self.s.clock())
        actions=[('关键日期',{'page':'project','project':key,'section':'dates'}),('人员与职责',{'page':'project','project':key,'section':'people'}),('待办',{'page':'project','project':key,'section':'todos'}),('查看依据',{'page':'project','project':key,'section':'source'})]
        for flag,label,next in [('scheduler','创建提醒','remind'),('progress_collection','更新进展','collect')]:
            if self.flags[flag]:actions.append((label,{'page':next,'project':key}))
        actions.append(('返回项目',{'page':'projects'}))
        return self.ux_page(row,p['title'],text,actions)

    def ux_form_values(self,snapshot,body):
        specs=snapshot.get('fields')
        values=body.get('form_value') or {}
        if not isinstance(values,dict) or len(canonical(values))>16000:raise BoundaryError('FORM_INVALID')
        if specs is None:
            if values:raise BoundaryError('FORM_UNEXPECTED')
            return {}
        if set(values)-set(specs):raise BoundaryError('FORM_UNEXPECTED')
        out={}
        for name,spec in specs.items():
            value=values.get(name,[] if spec.get('kind')=='multi_select_static' else '')
            if spec.get('required',True) and not value:raise BoundaryError('FORM_REQUIRED')
            if spec.get('kind')=='multi_select_static':
                if not isinstance(value,list) or not all(isinstance(x,str) for x in value) or len(value)!=len(set(value)):raise BoundaryError('FORM_INVALID')
                if set(value)-{x[0] for x in spec['options']}:raise BoundaryError('FORM_OPTION_INVALID')
            else:
                if not isinstance(value,str) or len(value)>(1000 if spec.get('kind','input')=='input' else 4000):raise BoundaryError('FORM_INVALID')
                if spec.get('options') and value and value not in {x[0] for x in spec['options']}:raise BoundaryError('FORM_OPTION_INVALID')
                if spec.get('required',True) and not value.strip():raise BoundaryError('FORM_REQUIRED')
            out[name]=value
        return out

    def ux_draft(self,row,ident,version=None):
        ds=self.s.rows('SELECT * FROM am_ux_drafts WHERE id=? AND scope=? AND expires>?',(ident,self.scope(row),self.s.clock()))
        if not ds:raise BoundaryError('UX_DRAFT_EXPIRED')
        d=ds[0]
        if version is not None and version!=d['version']:raise BoundaryError('UX_DRAFT_CHANGED')
        if d['state']=='cancelled':raise BoundaryError('UX_DRAFT_EXPIRED')
        return d,json.loads(d['data'])

    def ux_remind(self,row,key,group=None,draft=None,item=None):
        if not self.flags['scheduler'] or not self.flags['items']:raise BoundaryError('SCHEDULER_NOT_ENABLED')
        p=self.ux_project(row,key);port=self.g.reminders.port;existing=None
        if item:
            existing=self.items.get(item)
            if existing['owner']!=row['user'] or existing['project_ref']!=key or existing['paused'] or existing['state'] in ('closed','cancelled'):raise BoundaryError('ITEM_OPERATION_DENIED')
            target=json.loads(existing['source']).get('target')
            if not target:raise BoundaryError('ITEM_TARGET_NOT_VERIFIED')
            group=target['group']['id']
        if not group:
            groups=[port.group(g) for g in port.policy()['outbound_group_ids']]
            return self.ux_page(row,'选择提醒群',p['title']+'\n仅列出已授权的群。',[(g['name'],{'page':'remind','project':key,'group':g['id']}) for g in groups]+[('返回项目',{'page':'project','project':key})])
        group_info=port.group(group);members=port.members(group)
        if not members:return self.ux_page(row,'暂无可选人员','当前群没有可核实的人员。',[('返回项目',{'page':'project','project':key})])
        if draft:
            d,old=self.ux_draft(row,draft)
            if d['state']=='done':return self.ux_plan_detail(row,json.loads(d['result'])['plan'])
            # Opening edit invalidates every prior preview before any new input.
            self.s.execute("UPDATE am_ux_drafts SET version=version+1,state='editing' WHERE id=?",(draft,))
            d,old=self.ux_draft(row,draft)
        else:
            ident=uuid.uuid4().hex;old={}
            if existing:old={'values':{'body':existing['description']},'people_ids':json.loads(existing['assignees']),'item':existing['id'],'item_version':existing['version']}
            self.s.execute("INSERT INTO am_ux_drafts VALUES(?,?,1,'editing','{}',?,NULL)",(ident,self.scope(row),row['expires']))
            d,_=self.ux_draft(row,ident)
        people={str(i):m for i,m in enumerate(members)}
        defaults=old.get('values',{})
        selected=[i for i,m in people.items() if m['id'] in old.get('people_ids',[])]
        specs={
          'people':{'label':'提醒谁','kind':'multi_select_static','options':[(i,m['name']) for i,m in people.items()],'default':selected},
          'body':{'label':'完整提醒正文','default':defaults.get('body','')},
          'when':{'label':'首次发送时间（北京时间）','kind':'picker_datetime','default':defaults.get('when',(datetime.fromtimestamp(self.s.clock(),TZ)+timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M'))},
          'frequency':{'label':'发送频率','kind':'select_static','options':[('once','仅一次'),('daily','每天（遵循已核实工作日历）'),('workdays','工作日（需已核实日历）'),('exact_daily','特殊每天（含休息日，按所示时刻）')],'default':defaults.get('frequency','once')},
          'until':{'label':'周期截止时间（仅周期提醒必填，北京时间）','kind':'picker_datetime','required':False,'default':defaults.get('until','')},
          'policy':{'label':'周期批准方式','kind':'select_static','options':[('preview_each','每次发送前确认'),('fixed_rule','批准完整固定规则')],'default':defaults.get('policy','preview_each')}}
        return self.ux_page(row,'填写提醒',p['title']+'\n目标群：'+group_info['name']+'\n下一步查看完整预览。',
                [('取消',{'page':'cancel_draft','draft':d['id'],'version':d['version']})],fields=specs,submit=('查看完整预览',{'page':'preview_reminder'}),
                data={'draft':d['id'],'version':d['version'],'project':key,'group':group_info,'people':people,'item':old.get('item'),'item_version':old.get('item_version')})

    def ux_preview_reminder(self,row,data,values):
        d,old=self.ux_draft(row,data['draft'],data['version'])
        if d['state']!='editing':raise BoundaryError('UX_DRAFT_CHANGED')
        p=self.ux_project(row,data['project']);people=[data['people'][i] for i in values['people']]
        port=self.g.reminders.port
        target={'bot':port.bot(),'group':data['group'],'people':people}
        port.refresh(target)
        at=card_time(values['when']);frequency=values['frequency'];once=frequency=='once'
        saved={'project':p['key'],'title':p['title'],'values':values,'people_ids':[m['id'] for m in people],'target':target,'item':data.get('item'),'item_version':data.get('item_version')}
        if saved['item']:
            item=self.items.get(saved['item'])
            if item['version']!=saved['item_version'] or set(saved['people_ids'])!=set(json.loads(item['assignees'])):raise BoundaryError('ITEM_VERSION_CHANGED')
        # Preserve the user's form even if calendar validation fails.
        self.s.execute('UPDATE am_ux_drafts SET data=? WHERE id=?',(canonical(saved),d['id']))
        if at<=self.s.clock():raise BoundaryError('FUTURE_SEND_TIME_REQUIRED')
        kind='once' if once else 'workdays' if frequency=='workdays' else 'daily'
        rule={'at':at} if once else {'time':datetime.fromtimestamp(at,TZ).strftime('%H:%M'),'timezone':'Asia/Shanghai','calendar_version':self.scheduler.calendar.data.get('version'),'quiet_policy':'exact' if frequency=='exact_daily' else 'business_hours'}
        if not once:rule['start_at']=at
        next_at=at if once else self.scheduler.next_time(kind,rule,at-1)
        until=at+61 if once else card_time(values['until'])
        if until<=next_at or until>self.s.clock()+366*86400:raise BoundaryError('PLAN_VALIDITY_REQUIRED')
        saved.update(kind=kind,rule=rule,next_at=next_at,until=until,policy='fixed_rule' if once else values['policy'],window=60)
        self.s.execute("UPDATE am_ux_drafts SET data=?,version=version+1,state='preview' WHERE id=?",(canonical(saved),d['id']))
        d,_=self.ux_draft(row,d['id'])
        text=(p['title']+'\n事项：'+values['body']+'\n目标群：'+target['group']['name']+'\n涉及人员：'+'、'.join(x['name'] for x in people)+
              '\n完整正文：\n'+values['body']+'\n首次实际发送：'+datetime.fromtimestamp(next_at,TZ).strftime('%Y-%m-%d %H:%M:%S')+
              '\n时区：Asia/Shanghai（北京时间）\n执行窗口：60 秒，超时不补发\n有效至：'+datetime.fromtimestamp(until,TZ).strftime('%Y-%m-%d %H:%M:%S')+
              '\n周期：'+{'once':'仅一次','daily':'每天，普通工作时间及已核实日历','workdays':'已核实工作日','exact_daily':'特殊每天，含休息日，按所示时刻'}[frequency]+
              '\n批准方式：'+('每次发送前仍需确认' if saved['policy']=='preview_each' else '批准此完整固定规则')+
              '\n确认后纳入 AM 跟进并启用计划；不改变正式台账。')
        actions=[('确认所示提醒',{'page':'confirm_reminder','draft':d['id'],'version':d['version']}),('返回修改',{'page':'remind','project':p['key'],'group':target['group']['id'],'draft':d['id']}),('取消',{'page':'cancel_draft','draft':d['id'],'version':d['version']})]
        return self.ux_page(row,'完整提醒预览',text,actions)

    def ux_confirm_reminder(self,row,ident,version):
        d,v=self.ux_draft(row,ident,version)
        if d['state']=='done':return self.ux_plan_detail(row,json.loads(d['result'])['plan'])
        if d['state']!='preview':raise BoundaryError('UX_DRAFT_CHANGED')
        p=self.ux_project(row,v['project'])
        if p['title']!=v['title']:raise BoundaryError('UX_DRAFT_CHANGED')
        if v['next_at']<self.s.clock():raise BoundaryError('FUTURE_SEND_TIME_REQUIRED')
        self.g.reminders.port.refresh(v['target'])
        op='ux/'+ident+'/'+str(version)
        if v.get('item'):
            item=self.items.get(v['item'])
            if item['version']!=v['item_version'] or item['paused'] or item['state'] in ('closed','cancelled'):raise BoundaryError('ITEM_VERSION_CHANGED')
        else:item=self.items.create(row['user'],op,project_ref=v['project'],description=v['values']['body'],requirements='',assignees=v['people_ids'],source={'project_title':v['title'],'target':v['target'],'preview':ident,'version':version})
        payload=normalized_payload(item['id'],v['target']['bot'],v['target']['group'],v['target']['people'],v['values']['body'])
        p=self.scheduler.create(row['user'],op,item_id=item['id'],kind=v['kind'],rule=v['rule'],target={'kind':'group','payload':payload},template=v['values']['body'],policy=v['policy'],valid_until=v['until'],window_seconds=v['window'])
        self.scheduler.approve_plan(row['user'],p['id'],p['version'],p['hash'])
        self.s.execute("UPDATE am_ux_drafts SET state='done',result=? WHERE id=?",(canonical({'plan':p['id'],'item':item['id']}),ident))
        return self.ux_plan_detail(row,p['id'])

    def ux_plan_detail(self,row,ident):
        p=self.scheduler.plan(ident)
        if row['user']!=p['owner']:raise BoundaryError('OWNER_ONLY')
        target=json.loads(p['target']);who='本人私聊' if target['kind']=='owner' else target['payload']['group']['name']
        names={'draft':'待确认','active':'已启用','paused':'已暂停','cancelled':'已取消','expired':'已到期'}
        next_text=datetime.fromtimestamp(p['next_at'],TZ).strftime('%Y-%m-%d %H:%M')+'（北京时间）' if math.isfinite(p['next_at']) else '无下一次触发'
        text='计划状态：'+names.get(p['state'],p['state'])+'\n目标：'+who+'\n正文：'+p['template']+'\n下一次检查/发送：'+next_text
        actions=[]
        for o in self.s.rows('SELECT * FROM reminder_occurrences WHERE plan_id=? ORDER BY scheduled_at DESC LIMIT 5',(ident,)):
            text+='\n'+self.ux_occurrence_status(o)
            if o['state'] in ('unknown','sent','sending') and o['readback_state']!='verified':actions.append(('核对发送结果',{'page':'reconcile','occurrence':o['id']}))
        if p['state']=='active':actions.append(('暂停计划',{'page':'plan_control','plan':ident,'version':p['version'],'control':'pause'}))
        if p['state']=='paused':actions.append(('恢复并重新预览',{'page':'plan_control','plan':ident,'version':p['version'],'control':'resume'}))
        if p['state'] not in ('cancelled','expired'):actions.append(('取消计划',{'page':'plan_control','plan':ident,'version':p['version'],'control':'cancel'}))
        actions += [('刷新状态',{'page':'plan','plan':ident}),('返回计划',{'page':'plans'})]
        return self.ux_page(row,'提醒计划',text,actions)

    def ux_occurrence_status(self,o):
        state=o['state']
        label='已发送并核对' if state=='sent' and o['readback_state']=='verified' else '结果待核对' if state in ('unknown','sending','sent') else '确定未发送' if state in ('confirmed_not_sent','cancelled') else '等待本次确认' if state=='awaiting_confirmation' else '等待发送'
        return datetime.fromtimestamp(o['scheduled_at'],TZ).strftime('%Y-%m-%d %H:%M')+'：'+label

    def ux_collect_start(self,row,key):
        if not self.flags['progress_collection']:raise BoundaryError('PROGRESS_COLLECTION_NOT_ENABLED')
        p=self.ux_project(row,key)
        self.ux_set_collection(row,'progress',{'project':p['key'],'title':p['title']})
        return self.ux_page(row,'更新进展','当前收集：'+p['title']+'\n请直接在当前聊天发送进展文字。将生成待核对提案；正式台账写回未开启。',[('更换项目',{'page':'projects','next':'collect'}),('取消收集',{'page':'cancel_collect'})])

    def ux_set_collection(self,row,kind,target):
        self.s.execute("INSERT INTO am_ux_collection VALUES(?,?,?,?,?,'active') ON CONFLICT(scope) DO UPDATE SET token=excluded.token,kind=excluded.kind,target=excluded.target,expires=excluded.expires,state='active'",(self.scope(row),uuid.uuid4().hex,kind,canonical(target),min(row['expires'],self.s.clock()+3600)))

    def ux_collection_at_receipt(self,row):
        rows=self.s.rows('SELECT * FROM am_ux_collection WHERE scope=?',(self.scope(row),))
        if not rows or rows[0]['state']=='cancelled':return None
        return rows[0]

    def ux_collection_in_chat(self,row):
        prefix=[row[k] for k in ('tenant','app','chat','user')]
        return any(json.loads(r['scope'])[:4]==prefix for r in self.s.rows("SELECT scope FROM am_ux_collection WHERE state IN ('active','expired')"))

    def ux_collect_message(self,row):
        receipts=self.s.rows('SELECT context FROM am_ux_receipts WHERE id=?',(row['id'],))
        if not receipts:raise BoundaryError('COLLECTION_CONTEXT_EXPIRED')
        receipt=json.loads(receipts[0]['context']);current=self.ux_collection_at_receipt(row)
        if not current or current['token']!=receipt['token'] or current['expires']<=self.s.clock():raise BoundaryError('COLLECTION_CONTEXT_EXPIRED')
        target=json.loads(current['target']);meta=self.source_meta(row)
        if current['kind']=='progress':
            if meta['message_type'] not in ('text','post'):raise BoundaryError('PROGRESS_TEXT_REQUIRED')
            p=self.ux_project(row,target['project'])
            from query_rules import identifiers
            mentioned=identifiers(row['body'])
            if mentioned and mentioned!=identifiers(p['title']):raise BoundaryError('COLLECTION_REFERENCE_CONFLICT')
            if meta.get('parent'):
                refs=self.s.rows('SELECT project_ref FROM am_query_refs WHERE message_id=? AND scope=? AND expires>?',(meta['parent'],self.scope(row),self.s.clock()))
                if not refs or refs[0]['project_ref']!=p['key']:raise BoundaryError('COLLECTION_REFERENCE_CONFLICT')
            r=self.updates.collect(row['user'],row['id'],p['key'],row['body'],self.collection_source(row),row['created'])
            self.update_card(row,self.updates.propose(r['id']))
            return '已生成待核对提案；正式台账写回未开启。当前仍收集：'+target['title']+'。可点取消收集结束。'
        if current['kind']=='precheck':
            if not self.flags['precheck']:raise BoundaryError('PRECHECK_NOT_ENABLED')
            logic=self.g.logic;principal=dict(row,message_id=row['id'])
            d=logic.get(principal,target['draft'])
            if logic.current(principal)['id']!=d['id'] or json.loads(d['target'])!=target['target']:raise BoundaryError('COLLECTION_CONTEXT_CHANGED')
            if meta['message_type']=='file':
                if not self.flags['attachments']:raise BoundaryError('ATTACHMENTS_NOT_ENABLED')
                info=json.loads(row['body'])
                try:data=self.g.api.read_file(principal,info['file_key'],lambda:self.g.authorized(principal),limit=8*1024*1024)
                except BoundaryError as exc:
                    logic.add_source(principal,d,info['file_name'],b'',limitation='已提供文件，读取失败：'+str(exc))
                else:logic.add_source(principal,d,info['file_name'],data)
            else:logic.add_source(principal,d,'进件.txt',row['body'].encode())
            return self.ux_run_precheck(principal,target['draft'])
        raise BoundaryError('COLLECTION_CONTEXT_CHANGED')

    def ux_targets(self,row):
        if not self.flags['precheck']:raise BoundaryError('PRECHECK_NOT_ENABLED')
        settings=getattr(self.g.logic.business,'settings',{})
        targets=settings.get('targets',{})
        actions=[(str(v.get('label') or alias),{'page':'precheck_form','target':alias}) for alias,v in targets.items()]
        return self.ux_page(row,'选择预检目标','选择已登记的项目 / 节点 / 交付物。' if actions else '尚无已授权的预检目标，请先登记准确的项目、节点和交付物。',actions+[('返回首页',{'page':'home'})])

    def ux_precheck_form(self,row,alias):
        target=self.g.logic.business.resolve(row,alias)
        fields={'kind':{'label':'文种','kind':'select_static','options':[('test','测试报告'),('8d','异常分析'),('charter','项目章程')],'default':'test'},'requirements':{'label':'本次明确应交要求（每行一项；留空使用目标已登记要求）','required':False}}
        return self.ux_page(row,'资料预检',alias+'\n项目 / 节点 / 交付物已核实。材料会绑定此目标。',[('返回目标列表',{'page':'targets'})],fields=fields,submit=('开始收集材料',{'page':'start_precheck'}),data={'target':target})

    def ux_start_precheck(self,row,data,values):
        if self.g.logic.business.resolve(row,data['target']['id'])!=data['target']:raise BoundaryError('TARGET_REVISION_CHANGED')
        logic=self.g.logic;logic.create(row,values['kind']);d=logic.start_precheck(row,data['target']['id'],values['kind'])
        if values['requirements'].strip():d=logic.set_precheck_requirements(row,values['requirements'])
        if not self.g.authorized(row):raise BoundaryError('LOGIC_SCOPE_DENIED')
        self.ux_set_collection(row,'precheck',{'draft':d['id'],'target':data['target']})
        return self.ux_page(row,'等待资料','当前收集：'+data['target']['id']+'\n直接发送原文或 DOCX、文字层 PDF、文本附件。读取不完整会保留限制，不视为验收通过。',[('更换目标',{'page':'targets'}),('取消收集',{'page':'cancel_collect'})])

    def ux_run_precheck(self,row,ident):
        logic=self.g.logic;d=logic.get(row,ident);sources=json.loads(d['sources'])
        for source in logic.business.sources(row,json.loads(d['target'])):
            if source['id'] not in {s['id'] for s in sources}:sources.append(source)
        content,report=logic.evaluate_precheck(row,d,sources)
        return self.ux_page(row,'资料预检结果',content,[('继续补充材料',{'page':'precheck_continue','draft':ident}),('更换目标',{'page':'targets'}),('取消收集',{'page':'cancel_collect'})])

    def ux_handle(self,row,c,action):
        snapshot=json.loads(c['snapshot'])
        if row['user']!=self.owner:raise BoundaryError('OWNER_ONLY')
        if snapshot.get('app')!=row['app'] or snapshot.get('tenant')!=row['tenant']:raise BoundaryError('CARD_IDENTITY_OR_VERSION_INVALID')
        if action not in snapshot['actions']:raise BoundaryError('CARD_ACTION_NOT_SUPPORTED')
        row['thread']=snapshot.get('thread')
        a=snapshot['actions'][action];body=json.loads(row['body'])
        page_flags={'preview_reminder':'scheduler','confirm_reminder':'scheduler','plan':'scheduler','plan_control':'scheduler','reconcile':'scheduler','subscribe':'scheduler','subscription_preview':'scheduler','subscription_confirm':'scheduler','start_precheck':'precheck','precheck_continue':'precheck','precheck_form':'precheck','item_change':'items','item_action_form':'items','item':'items','briefing':'snapshots'}
        if a['page'] in page_flags and not self.flags[page_flags[a['page']]]:raise BoundaryError('FEATURE_NOT_ENABLED')
        # Navigation buttons do not require the form's mandatory fields.
        submit=a['page'] in ('search','preview_reminder','start_precheck','subscription_preview','item_change')
        saved=snapshot['data']
        if submit and saved.get('draft') and isinstance(body.get('form_value'),dict):
            d,old=self.ux_draft(row,saved['draft'],saved['version'])
            if d['state']!='editing':raise BoundaryError('UX_DRAFT_CHANGED')
            specs=snapshot.get('fields') or {};incoming=body['form_value']
            kept={k:v for k,v in incoming.items() if k in specs and isinstance(v,str) and len(v)<=4000}
            previous=dict(old,values=kept)
            if 'project' in saved:previous.update(project=saved['project'],item=saved.get('item'),item_version=saved.get('item_version'))
            if 'people' in saved and isinstance(incoming.get('people'),list):previous['people_ids']=[saved['people'][i]['id'] for i in incoming['people'] if isinstance(i,str) and i in saved['people']]
            self.s.execute('UPDATE am_ux_drafts SET data=? WHERE id=?',(canonical(previous),d['id']))
        values=self.ux_form_values(snapshot,body) if submit else {}
        data=dict(snapshot['data'],nonce=c['nonce']);page=a['page']
        if page=='home':return self.ux_home(row)
        if page=='projects':return self.ux_projects(row,next=a.get('next','project'),query=a.get('query',''),page=a.get('offset',0))
        if page=='search':return self.ux_projects(row,next=a['next'],query=values['query'])
        if page=='project':return self.ux_project_detail(row,a['project'],a.get('section'))
        if page=='remind':return self.ux_remind(row,a['project'],a.get('group'),a.get('draft'),a.get('item'))
        if page=='preview_reminder':return self.ux_preview_reminder(row,data,values)
        if page=='confirm_reminder':return self.ux_confirm_reminder(row,a['draft'],a['version'])
        if page=='cancel_draft':
            d,_=self.ux_draft(row,a['draft'],a['version'])
            if d['state']=='done':raise BoundaryError('UX_DRAFT_CHANGED')
            self.s.execute("UPDATE am_ux_drafts SET state='cancelled',version=version+1 WHERE id=?",(d['id'],));return self.ux_home(row)
        if page=='collect':return self.ux_collect_start(row,a['project'])
        if page=='cancel_collect':self.ux_cancel_collection(row);return self.ux_home(row)
        if page=='retry_form':
            old=self.s.rows('SELECT * FROM am_cards WHERE nonce=?',(a['nonce'],))
            if not old or old[0]['actor']!=row['user'] or old[0]['chat']!=row['chat'] or old[0]['expires']<=self.s.clock():raise BoundaryError('UX_DRAFT_EXPIRED')
            snap=json.loads(old[0]['snapshot']);saved=snap['data']
            if saved.get('draft'):
                d,v=self.ux_draft(row,saved['draft'])
                if saved.get('subscription'):return self.ux_more_action(row,{'page':'subscribe','draft':d['id']})
                return self.ux_remind(row,saved['project'],saved['group']['id'],d['id'])
            if saved.get('target'):return self.ux_precheck_form(row,saved['target']['id'])
            return self.ux_more_action(row,{'page':'subscribe'})
        if page=='targets':return self.ux_targets(row)
        if page=='precheck_form':return self.ux_precheck_form(row,a['target'])
        if page=='start_precheck':return self.ux_start_precheck(row,data,values)
        if page=='precheck_continue':
            d=self.g.logic.get(row,a['draft']);target=json.loads(d['target']);self.ux_set_collection(row,'precheck',{'draft':d['id'],'target':target})
            return '当前收集：'+target['id']+'。请直接发送补充材料。'
        if page=='plan':return self.ux_plan_detail(row,a['plan'])
        if page=='reconcile':
            self.scheduler.reconcile(a['occurrence'],manual=True);o=self.scheduler.occurrence(a['occurrence']);return self.ux_plan_detail(row,o['plan_id'])
        if page=='plan_control':
            p=self.scheduler.control(row['user'],'ux/'+c['nonce'],a['plan'],a['version'],a['control'])
            if p['state']=='draft':return self.plan_card(row,p)
            return self.ux_plan_detail(row,p['id'])
        return self.ux_more_action(row,a,values,data)

    def ux_more_action(self,row,a,values=None,data=None):
        page=a['page'];values=values or {};data=data or {}
        if page=='more':return self.ux_page(row,'更多','选择要查看或设置的内容。',[('提醒计划',{'page':'plans'}),('简报订阅',{'page':'subscribe'}),('运行状态',{'page':'status'}),('帮助',{'page':'help'}),('返回首页',{'page':'home'})])
        if page in ('status','help','briefing'):
            if page=='status':text=self.handle(dict(row,kind='text',body='/status'))
            elif page=='help':text='从首页选择项目、提醒、进展或资料预检。文字和附件直接在当前聊天发送。发送“/chat”可返回普通聊天。'
            else:text=self.briefing(row)
            return self.ux_page(row,{'status':'运行状态','help':'使用帮助','briefing':'变化简报'}[page],text,[('返回首页',{'page':'home'}),('更多',{'page':'more'})])
        if page=='work':
            if not self.flags['items']:raise BoundaryError('ITEMS_NOT_ENABLED')
            rows=self.s.rows('SELECT * FROM action_items WHERE owner=? ORDER BY updated DESC',(self.owner,))
            return self.ux_object_list(row,'待办与跟进',self.todos(row),rows,'item',a.get('offset',0))
        if page=='plans':
            if not self.flags['scheduler']:raise BoundaryError('SCHEDULER_NOT_ENABLED')
            rows=self.s.rows('SELECT * FROM reminder_plans WHERE owner=? ORDER BY created DESC',(self.owner,))
            return self.ux_object_list(row,'提醒计划','查看已确认或待处理的计划。',rows,'plan',a.get('offset',0))
        if page=='item':
            item=self.items.get(a['item'])
            if item['owner']!=row['user']:raise BoundaryError('OWNER_ONLY')
            actions=[('返回跟进',{'page':'work'})]
            if item['state'] not in ('closed','cancelled'):
                actions=[(label,{'page':'item_action_form','item':item['id'],'version':item['version'],'control':control}) for label,control in [('设置检查时间','check'),('暂停跟进','pause'),('恢复跟进','resume'),('核验并关闭','close')]]+actions
                if self.flags['scheduler'] and not item['paused']:actions.insert(0,('为此事项创建提醒',{'page':'remind','project':item['project_ref'],'item':item['id']}))
            return self.ux_page(row,'事项详情',self.ux_item_text(item),actions)
        if page=='item_action_form':
            fields={'detail':{'label':'核验依据 / 补充说明','required':a['control']=='close'}}
            if a['control']=='check':fields={'when':{'label':'下一次检查时间（北京时间）','kind':'picker_datetime'}}
            return self.ux_page(row,'确认跟进操作',self.ux_item_text(self.items.get(a['item'])),[('返回事项',{'page':'item','item':a['item']})],fields=fields,submit=('确认本次操作',{'page':'item_change'}),data=a)
        if page=='item_change':
            self.items.change(row['user'],row['id'],data['item'],data['version'],data['control'],evidence=values.get('detail') if data['control']=='close' else None,next_check=card_time(values['when']) if data['control']=='check' else None)
            return self.ux_more_action(row,{'page':'item','item':data['item']})
        if page=='subscribe':
            if not self.flags['scheduler'] or not self.flags['snapshots']:raise BoundaryError('SCHEDULER_NOT_ENABLED')
            if a.get('draft'):
                d,old=self.ux_draft(row,a['draft'])
                if d['state']=='done':return self.ux_plan_detail(row,json.loads(d['result'])['plan'])
                self.s.execute("UPDATE am_ux_drafts SET version=version+1,state='editing' WHERE id=?",(d['id'],))
                d,old=self.ux_draft(row,d['id'])
            else:
                ident=uuid.uuid4().hex
                self.s.execute("INSERT INTO am_ux_drafts VALUES(?,?,1,'editing','{}',?,NULL)",(ident,self.scope(row),row['expires']))
                d,old=self.ux_draft(row,ident)
            defaults=old.get('values',{})
            fields={'frequency':{'label':'频率','kind':'select_static','options':[('daily','每天'),('workdays','已核实工作日')],'default':defaults.get('frequency','daily')},'time':{'label':'北京时间（HH:MM）','default':defaults.get('time','09:00')},'until':{'label':'订阅截止时间（北京时间）','kind':'picker_datetime','default':defaults.get('until','')}}
            return self.ux_page(row,'本人简报订阅','范围：当前本人可访问的项目变化及待办。仅发本人私聊。',[('返回更多',{'page':'more'})],fields=fields,submit=('查看订阅预览',{'page':'subscription_preview'}),data={'draft':d['id'],'version':d['version'],'subscription':True})
        if page=='subscription_preview':
            d,old=self.ux_draft(row,data['draft'],data['version'])
            if d['state']!='editing':raise BoundaryError('UX_DRAFT_CHANGED')
            self.s.execute('UPDATE am_ux_drafts SET data=? WHERE id=?',(canonical({'values':values,'subscription':True}),d['id']))
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',values['time']):raise BoundaryError('SCHEDULE_TIME_REQUIRED')
            rule={'time':values['time'],'timezone':'Asia/Shanghai','workdays':values['frequency']=='workdays','calendar_version':self.scheduler.calendar.data.get('version')}
            next_at=self.scheduler.next_time('briefing',rule,self.s.clock()-1);until=card_time(values['until'])
            if until<=next_at or until>self.s.clock()+366*86400:raise BoundaryError('PLAN_VALIDITY_REQUIRED')
            saved={'values':values,'subscription':True,'rule':rule,'until':until,'next_at':next_at}
            self.s.execute("UPDATE am_ux_drafts SET data=?,version=version+1,state='preview' WHERE id=?",(canonical(saved),d['id']))
            d,_=self.ux_draft(row,d['id'])
            return self.ux_page(row,'订阅完整预览','范围：本人当前可访问项目\n目标：本人私聊\n内容：项目变化、待办及来源时间\n北京时间：'+values['time']+'\n频率：'+('已核实工作日' if rule['workdays'] else '每天')+'\n下一次：'+datetime.fromtimestamp(next_at,TZ).isoformat()+'\n有效至：'+datetime.fromtimestamp(until,TZ).isoformat()+'\n执行窗口：60 秒，过期不补发。确认后按固定规则执行。',[('确认订阅',{'page':'subscription_confirm','draft':d['id'],'version':d['version']}),('返回修改',{'page':'subscribe','draft':d['id']})])
        if page=='subscription_confirm':
            d,v=self.ux_draft(row,a['draft'],a['version'])
            if d['state']=='done':return self.ux_plan_detail(row,json.loads(d['result'])['plan'])
            if d['state']!='preview':raise BoundaryError('UX_DRAFT_CHANGED')
            if v['next_at']<self.s.clock():raise BoundaryError('FUTURE_SEND_TIME_REQUIRED')
            self.projects(row)
            p=self.scheduler.create(row['user'],'ux-sub/'+d['id']+'/'+str(d['version']),item_id=None,kind='briefing',rule=v['rule'],target={'kind':'owner','user':self.owner,'chat':row['chat']},template='',policy='owner_subscription',valid_until=v['until'])
            self.s.execute("INSERT OR IGNORE INTO am_subscriptions VALUES(?,?,?,'active')",(p['id'],self.owner,p['id']))
            self.scheduler.approve_plan(row['user'],p['id'],p['version'],p['hash'])
            self.s.execute("UPDATE am_ux_drafts SET state='done',result=? WHERE id=?",(canonical({'plan':p['id']}),d['id']))
            return self.ux_plan_detail(row,p['id'])
        raise BoundaryError('CARD_ACTION_NOT_SUPPORTED')

    def ux_item_text(self,item):
        from am_business import LABELS
        source=json.loads(item['source']);people={p['id']:p['name'] for p in source.get('target',{}).get('people',[])}
        next_check=datetime.fromtimestamp(item['next_check'],TZ).strftime('%Y-%m-%d %H:%M') if item['next_check'] else '尚未设置'
        lines=[source.get('project_title','项目归属待核对'),item['description'],'状态：'+LABELS[item['state']]+('（暂停）' if item['paused'] else ''),'交付要求：'+(item['requirements'] or '待确认'),'下一次检查：'+next_check,'核验关闭依据：'+(item['close_evidence'] or '尚未核验关闭')]
        kinds={'received':'已收到','processing':'处理中','eta':'预计时间','help':'需要协助','submitted':'提交材料','not_mine':'非本人负责'}
        for h in self.items.history(item['id']):
            lines += [people.get(h['actor'],'授权反馈人')+'｜'+kinds.get(h['kind'],h['kind'])+'｜'+('有效反馈' if h['applied'] else '迟到留证')+'｜'+datetime.fromtimestamp(h['created'],TZ).strftime('%Y-%m-%d %H:%M'),h['body'] or '无补充','来源：已绑定的原事项卡']
        return '\n'.join(lines)

    def ux_object_list(self,row,title,text,rows,kind,page):
        selected=rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE]
        actions=[((r.get('description') or r.get('template') or '本人变化简报')[:80],{'page':kind,kind:r['id']}) for r in selected]
        parent='work' if kind=='item' else 'plans'
        if page:actions.append(('上一页',{'page':parent,'offset':page-1}))
        if (page+1)*PAGE_SIZE<len(rows):actions.append(('下一页',{'page':parent,'offset':page+1}))
        if not rows:text+='\n当前尚无 AM '+('跟进事项' if kind=='item' else '提醒计划')+'。'
        if kind=='plan':actions.append(('创建提醒计划',{'page':'projects','next':'remind'}))
        return self.ux_page(row,title,text,actions+[('返回首页',{'page':'home'}),('更多',{'page':'more'})])

    def ux_error(self,row,code):
        messages={'FORM_REQUIRED':'请填写必填内容。','FORM_OPTION_INVALID':'选项已失效，请重新选择。','FORM_INVALID':'表单内容无法识别，请重新填写。','FORM_TIME_REQUIRED':'请选择完整日期和时间。','FUTURE_SEND_TIME_REQUIRED':'发送时刻已经过去，请重新设置未来时间。','PLAN_VALIDITY_REQUIRED':'截止时间需要晚于下一次发送，且在一年以内。','CALENDAR_COVERAGE_MISSING':'尚无覆盖该日期的已核实工作日历。可改为明确的一次提醒，或待日历核实后设置普通周期。','UX_DRAFT_CHANGED':'内容已变化，请重新预览再确认。','UX_DRAFT_EXPIRED':'草稿已过期或取消，请重新创建。','COLLECTION_CONTEXT_EXPIRED':'收集已过期或对象已更换，请重新选择收集目标后发送。','COLLECTION_REFERENCE_CONFLICT':'引用的项目与当前收集对象不一致，请重新选择目标。','TARGET_REVISION_CHANGED':'目标内容已变化，请重新选择并预检。','CARD_IDENTITY_OR_VERSION_INVALID':'此卡片已过期或不属于当前身份与聊天，请重新打开菜单。','PROJECT_IDENTITY_UNVERIFIED':'项目身份尚未核实，请重新选择。','PROGRESS_TEXT_REQUIRED':'进展采集需要文字；附件请通过资料预检入口提交。'}
        actions=[('返回首页',{'page':'home'}),('更多',{'page':'more'})]
        if row['kind']=='card':
            body=json.loads(row['body']);nonce=body.get('value',{}).get('nonce')
            old=self.s.rows('SELECT * FROM am_cards WHERE nonce=?',(nonce,))
            if old and old[0]['actor']==row['user'] and old[0]['chat']==row['chat'] and old[0]['flow']=='ux':
                snapshot=json.loads(old[0]['snapshot'])
                if snapshot.get('fields'):actions.insert(0,('返回修改',{'page':'retry_form','nonce':nonce}))
        return self.ux_page(row,'本次未完成',messages.get(code,'当前操作未完成，请返回后重试；已有记录保留。'),actions)

    def ux_cleanup(self):
        now=self.s.clock()
        self.s.execute("UPDATE am_ux_drafts SET data='{}',result=NULL,state='cancelled' WHERE expires<=?",(now,))
        self.s.execute("UPDATE am_ux_collection SET target='{}',state='expired' WHERE expires<=? AND state='active'",(now,))
        self.s.execute('DELETE FROM am_ux_receipts WHERE id IN (SELECT id FROM am_inbox WHERE expires<=?)',(now,))
