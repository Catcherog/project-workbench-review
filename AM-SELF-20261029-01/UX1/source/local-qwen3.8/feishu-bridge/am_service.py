"""Owner-facing AM functions, called by the original consumer's business loop."""
from __future__ import annotations
import json
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from fs_agent.config import BoundaryError
from fs_agent.message_text import normalize_message
from fs_agent.project_catalog import canonical,digest
from group_ledger import render_project,select_projects,SOURCE,SHEET
from am_business import BusinessCommands
from am_updates import UpdateCommands
from am_ux import UxMixin,MENU_KEYS
from query_rules import deterministic_intent,identifiers,resolve_identifiers,fields_for,choice_number

DEFAULT_FLAGS={'query':False,'snapshots':False,'items':False,'scheduler':False,'progress_collection':False,'ledger_write':False,'attachments':False,'precheck':False}


class AmSelfService(UxMixin,BusinessCommands,UpdateCommands):
    def __init__(self,gateway,ledger,*,flags=None,calendar=None,metadata_reader=None,execution_policy=None):
        self.g,self.s,self.ledger=gateway,gateway.store,ledger
        if flags and (set(flags)-set(DEFAULT_FLAGS) or any(type(v) is not bool for v in flags.values())):raise BoundaryError('AM_FEATURE_FLAGS_INVALID')
        self.flags=dict(DEFAULT_FLAGS,**(flags or {}))
        self.owner=gateway.config.owner
        self.items=None;self.scheduler=None;self.updates=None
        with self.s.lock:
            self.s.conn.executescript('''
            CREATE TABLE IF NOT EXISTS am_inbox(
              id TEXT PRIMARY KEY,app TEXT NOT NULL,tenant TEXT NOT NULL,user TEXT NOT NULL,chat TEXT NOT NULL,
              chat_type TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,body TEXT NOT NULL,
              kind TEXT NOT NULL,state TEXT NOT NULL,error TEXT);
            CREATE TABLE IF NOT EXISTS am_source_meta(id TEXT PRIMARY KEY,metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS am_query_refs(message_id TEXT PRIMARY KEY,scope TEXT NOT NULL,project_ref TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS am_sessions(
              scope TEXT PRIMARY KEY,focus TEXT,pending TEXT,version INTEGER NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS am_notifications(
              outbox_id TEXT PRIMARY KEY,kind TEXT NOT NULL,object_id TEXT,version INTEGER,hash TEXT);
            CREATE TABLE IF NOT EXISTS am_cards(
              nonce TEXT PRIMARY KEY,flow TEXT NOT NULL,object_id TEXT NOT NULL,version INTEGER NOT NULL,
              actor TEXT NOT NULL,chat TEXT NOT NULL,snapshot TEXT NOT NULL,hash TEXT NOT NULL,
              expires REAL NOT NULL,outbox_id TEXT,message_id TEXT);
            ''')
        self.s.execute("UPDATE am_inbox SET state='interrupted' WHERE state='processing'")
        self.s.execute("UPDATE am_inbox SET state='delivery_unknown' WHERE state='sending'")
        self.init_business(calendar)
        self.init_updates(metadata_reader=metadata_reader,execution_policy=execution_policy)
        self.init_ux()
        gateway.am_self=self

    def scope(self,row):
        keys=[row['tenant'],row['app'],row['chat'],row['user']]
        thread=row.get('thread') or self.source_meta(row).get('thread')
        return canonical(keys+[thread] if thread else keys)

    def source_meta(self,row):
        rows=self.s.rows('SELECT metadata FROM am_source_meta WHERE id=?',(row.get('id'),))
        return json.loads(rows[0]['metadata']) if rows else {}

    def message_meta(self,message):
        # normalize_message has validated the format before this is called. The
        # fingerprint covers the original content, not the stripped route text.
        content=json.loads(message['content']) if isinstance(message['content'],str) else message['content']
        return {'thread':message.get('thread_id'),'parent':message.get('parent_id'),'root':message.get('root_id'),
                'message_type':message['message_type'],'content_fingerprint':digest(content),'fingerprint_kind':'raw-content-v1'}

    def wants(self,text):
        if text.strip() in ('/am','/menu','/help','/status'):return True
        if text.startswith(('/project','/changes','/todo','/briefing','/item','/plan','/update','/precheck','/mapping')):return True
        if text.startswith('/progress ') and text.strip()!='/progress sample':return True
        if text.startswith(('今天我需要跟进什么','我的待办','查看变化','项目变化','变化简报','订阅简报','取消订阅','新增跟进','查看跟进','更新需求')):return True
        if text.startswith('哪些项目') and re.search('待确认|未明确|缺少|资料',text):return True
        return self.flags['query'] and deterministic_intent(text)=='project'

    def ingest(self,payload):
        try:
            meta=None;collection=None
            h,e=payload['header'],payload['event'];config=self.g.config
            if h['app_id']!=config.app_id or h['tenant_key']!=config.tenant_key:return False,False
            if h['event_type']=='application.bot.menu_v6':
                user=e['operator']['operator_id']['open_id'];key=e['event_key']
                if user!=self.owner or key not in MENU_KEYS:return True,False
                created=float(e['timestamp'])
                if created>10**12:created/=1000
                row={'id':h['event_id'],'app':config.app_id,'tenant':config.tenant_key,'user':user,
                     'chat':'menu:'+user,'chat_type':'p2p','created':created,'kind':'menu','body':MENU_KEYS[key]}
                prior=self.s.rows("SELECT chat FROM am_inbox WHERE user=? AND chat_type='p2p' AND chat NOT LIKE 'menu:%' ORDER BY created DESC LIMIT 1",(user,))
                if prior:row['chat']=prior[0]['chat']
            elif h['event_type']=='card.action.trigger':
                value=e['action']['value']
                if value.get('flow')!='am_self':return False,False
                row={'id':h['event_id'],'app':config.app_id,'tenant':config.tenant_key,'user':e['operator']['open_id'],
                     'chat':e['context']['open_chat_id'],'chat_type':'p2p','created':self.s.clock(),'kind':'card',
                     'body':canonical({'value':value,'source_message':e['context']['open_message_id'],
                                       'form_value':e['action'].get('form_value'), 'action_meta':{k:e['action'].get(k) for k in ('name','tag','timezone')},
                                       'thread':e['context'].get('open_thread_id')})}
                if len(row['body'])>20000:return True,False
            elif h['event_type']=='im.message.receive_v1':
                m,sender=e['message'],e['sender']
                if sender['sender_type']!='user' or m['message_type'] not in ('text','post','file'):return False,False
                if sender.get('tenant_key',config.tenant_key)!=config.tenant_key:return True,False
                text=normalize_message(m,bot_open_id=config.bot_open_id,max_chars=6000).text.strip() if m['message_type']!='file' else ''
                meta=self.message_meta(m)
                user=sender['sender_id']['open_id']
                session={'app':config.app_id,'tenant':config.tenant_key,'user':user,'chat':m['chat_id'],'thread':meta.get('thread')}
                if m['chat_type']=='p2p' and user==self.owner:
                    if text=='/chat':self.ux_cancel_collection(session,all_chat=True)
                    elif not text.startswith('/'):
                        collection=self.ux_collection_at_receipt(session)
                        if not collection and self.ux_collection_in_chat(session):collection={'token':'scope-mismatch'}
                if m['message_type']=='file' and not collection:return False,False
                if text.startswith('/feedback '):
                    match=re.fullmatch(r'/feedback ([a-f0-9]{32}) (收到|处理中|预计|协助|提交|非本人)[｜|](.{1,2000})',text)
                    if not match or not m.get('parent_id'):return True,False
                    if m['chat_type']=='group' and not normalize_message(m,bot_open_id=config.bot_open_id,max_chars=6000).bot_mentioned:return True,False
                    occurrence=self.scheduler.occurrence(match[1]);saved=json.loads(occurrence['payload'])
                    body={'value':{'feedback':match[1],'nonce':saved.get('feedback_nonce'),'action':{'收到':'received','处理中':'processing','预计':'eta','协助':'help','提交':'submitted','非本人':'not_mine'}[match[2]]},'source_message':m['parent_id'],'detail':match[3]}
                    row={'id':m['message_id'],'app':config.app_id,'tenant':config.tenant_key,'user':user,'chat':m['chat_id'],'chat_type':m['chat_type'],'created':int(m['create_time'])/1000,'kind':'card','body':canonical(body)}
                    row['expires']=min(row['created'],self.s.clock())+86400
                    if row['expires']<=self.s.clock() or row['created']>self.s.clock()+60:return True,False
                    with self.s.tx() as c:
                        n=c.execute("INSERT OR IGNORE INTO am_inbox VALUES(?,?,?,?,?,?,?,?,?,?,'received',NULL)",tuple(row[k] for k in ('id','app','tenant','user','chat','chat_type','created','expires','body','kind'))).rowcount
                    return True,bool(n)
                if m['chat_type']=='group':
                    if not self.flags['progress_collection'] or not text.startswith(('/update','更新需求','更新项目')):return False,False
                    if not normalize_message(m,bot_open_id=config.bot_open_id,max_chars=6000).bot_mentioned:return True,False
                    row={'id':m['message_id'],'app':config.app_id,'tenant':config.tenant_key,'user':user,'chat':m['chat_id'],'chat_type':'group','created':int(m['create_time'])/1000,'kind':'update','body':text}
                    row['expires']=min(row['created'],self.s.clock())+86400
                    if row['expires']<=self.s.clock() or row['created']>self.s.clock()+60:return True,False
                    with self.s.tx() as c:
                        if c.execute("SELECT count(*) FROM am_inbox WHERE state='received'").fetchone()[0]>=32:raise BoundaryError('AM_QUEUE_FULL')
                        n=c.execute("INSERT OR IGNORE INTO am_inbox VALUES(?,?,?,?,?,?,?,?,?,?,'received',NULL)",tuple(row[k] for k in ('id','app','tenant','user','chat','chat_type','created','expires','body','kind'))).rowcount
                        if n:c.execute('INSERT INTO am_source_meta VALUES(?,?)',(row['id'],canonical(meta)))
                    return True,bool(n)
                if m['chat_type']!='p2p':return False,False
                if not collection and not self.wants(text):
                    session={'app':config.app_id,'tenant':config.tenant_key,'user':user,'chat':m['chat_id'],'thread':meta.get('thread')}
                    pending=self.s.rows('SELECT 1 FROM am_sessions WHERE scope=? AND pending IS NOT NULL AND expires>?',(self.scope(session),self.s.clock()))
                    if not pending or choice_number(text) is None:return False,False
                if user!=self.owner:return True,False
                row={'id':m['message_id'],'app':config.app_id,'tenant':config.tenant_key,'user':user,'chat':m['chat_id'],
                     'chat_type':'p2p','created':int(m['create_time'])/1000,'kind':'collection' if collection else 'text',
                     'body':canonical(json.loads(m['content']) if isinstance(m['content'],str) else m['content']) if m['message_type']=='file' else text}
            else:return False,False
            row['expires']=min(row['created'],self.s.clock())+86400
            if row['created']>self.s.clock()+60 or row['expires']<=self.s.clock():return True,False
            with self.s.tx() as c:
                if c.execute('SELECT 1 FROM am_inbox WHERE id=?',(row['id'],)).fetchone():return True,False
                if c.execute("SELECT count(*) FROM am_inbox WHERE state='received'").fetchone()[0]>=32:raise BoundaryError('AM_QUEUE_FULL')
                c.execute("INSERT INTO am_inbox VALUES(?,?,?,?,?,?,?,?,?,?,'received',NULL)",tuple(row[k] for k in ('id','app','tenant','user','chat','chat_type','created','expires','body','kind')))
                if meta:c.execute('INSERT INTO am_source_meta VALUES(?,?)',(row['id'],canonical(meta)))
                if collection:c.execute('INSERT INTO am_ux_receipts VALUES(?,?)',(row['id'],canonical(collection)))
            return True,True
        except (KeyError,TypeError,ValueError):return False,False

    def notify(self,row,text=None,*,card=None,kind='status',object_id=None,version=None,hash=None,conn=None):
        if conn is None:
            with self.s.tx() as c:return self.notify(row,text,card=card,kind=kind,object_id=object_id,version=version,hash=hash,conn=c)
        out=self.s.add_outbox(row,text=text,card=card,private=True,conn=conn)
        if kind=='status' and text and conn.execute('SELECT 1 FROM am_query_refs WHERE message_id=? AND expires>?',(row['id'],self.s.clock())).fetchone():
            kind='query';object_id=row['id']
        conn.execute('INSERT INTO am_notifications VALUES(?,?,?,?,?)',(out,kind,object_id,version,hash))
        return out

    def card(self,row,*,object_id,version,snapshot,title,body,actions,flow,expires=None):
        nonce=uuid.uuid4().hex;fingerprint=digest(snapshot);expiry=min(expires or row['expires'],row['expires'])
        buttons=[{'tag':'button','text':{'tag':'plain_text','content':label},'type':'primary' if index==0 else 'default',
                  'value':{'flow':'am_self','nonce':nonce,'action':action}} for index,(action,label) in enumerate(actions)]
        card={'config':{'wide_screen_mode':True},'header':{'title':{'tag':'plain_text','content':title}},
              'elements':[{'tag':'div','text':{'tag':'plain_text','content':body}},{'tag':'action','actions':buttons}]}
        with self.s.tx() as c:
            out=self.notify(row,card=card,kind='card',object_id=object_id,version=version,hash=fingerprint,conn=c)
            c.execute('INSERT INTO am_cards VALUES(?,?,?,?,?,?,?,?,?,?,NULL)',(nonce,flow,object_id,version,row['user'],row['chat'],canonical(snapshot),fingerprint,expiry,out))
        return nonce

    def valid_notification(self,row):
        notices=self.s.rows('SELECT * FROM am_notifications WHERE outbox_id=?',(row['id'],))
        if not notices:return None
        cards=self.s.rows('SELECT * FROM am_cards WHERE outbox_id=?',(row['id'],))
        if cards and cards[0]['expires']<=self.s.clock():return False
        return True

    def authorized_notification(self,row):
        notes=self.s.rows("SELECT object_id FROM am_notifications WHERE outbox_id=? AND kind='feedback_ack'",(row['id'],))
        if not notes:return None
        try:
            o=self.scheduler.occurrence(notes[0]['object_id']);p=json.loads(o['payload']);item=self.items.get(o['item_id'])
            if row['app']!=self.g.config.app_id or row['tenant']!=self.g.config.tenant_key or row['expires']<=self.s.clock() or row['user'] not in json.loads(item['assignees']):return False
            self.ledger.port.guard(p['target']['payload']['group']['id'],row['user'])
            return True
        except Exception:return False

    def delivered(self,c,row,message_id):
        c.execute('UPDATE am_cards SET message_id=? WHERE outbox_id=?',(message_id,row['id']))
        ref=c.execute("SELECT q.* FROM am_notifications n JOIN am_query_refs q ON q.message_id=n.object_id WHERE n.outbox_id=? AND n.kind='query' AND q.expires>?",(row['id'],self.s.clock())).fetchone()
        if ref:c.execute('INSERT OR IGNORE INTO am_query_refs VALUES(?,?,?,?)',(message_id,ref['scope'],ref['project_ref'],ref['expires']))

    def validate_card(self,row):
        body=json.loads(row['body']);value=body['value']
        cards=self.s.rows('SELECT * FROM am_cards WHERE nonce=?',(value.get('nonce'),))
        if not cards:raise BoundaryError('CARD_UNKNOWN')
        c=cards[0]
        if c['chat']=='menu:'+row['user'] and c['actor']==row['user'] and c['message_id']==body['source_message'] and c['expires']>self.s.clock():
            # Menu events have no chat ID. Bind the first callback to the actual
            # bot message after a platform read; never fabricate a message event.
            message=self.g.reminders.port.read(c['message_id'])
            if message['chat_id']!=row['chat'] or message['sender_id']!=self.g.config.bot_open_id:raise BoundaryError('CARD_IDENTITY_OR_VERSION_INVALID')
            self.s.execute('UPDATE am_cards SET chat=? WHERE nonce=?',(row['chat'],c['nonce']));c=dict(c,chat=row['chat'])
        if c['actor']!=row['user'] or c['chat']!=row['chat'] or not c['message_id'] or c['message_id']!=body['source_message'] or c['expires']<=self.s.clock():raise BoundaryError('CARD_IDENTITY_OR_VERSION_INVALID')
        if digest(json.loads(c['snapshot']))!=c['hash']:raise BoundaryError('CARD_SNAPSHOT_CHANGED')
        if c['flow']=='ux' and body.get('thread') and body['thread']!=json.loads(c['snapshot']).get('thread'):raise BoundaryError('CARD_IDENTITY_OR_VERSION_INVALID')
        return c,value.get('action')

    def projects(self,row):
        if row['user']!=self.owner:raise BoundaryError('OWNER_ONLY')
        self.ledger.port.authorize_user(row['user'])
        projects=self.ledger.port.read()
        with self.ledger.mutex:
            return self.ledger.catalog.sync(projects,complete=all(p.get('read_status','complete')=='complete' for p in projects),revision=projects[0].get('source_revision') if projects else None)

    def help(self):
        lines=['AM 自身功能（当前可用入口）：','/remind 事项：创建、修改、预览、确认、取消及查询提醒。'] if self.g.config.reminders_enabled else ['AM 自身功能：']
        if self.flags['query']:lines+=['/project 需求编号：真实台账快查；/todo：需要你推动的跟进清单。']
        if self.flags['snapshots']:lines+=['/changes：记录变化；/briefing：本人简报；订阅须明确时间。']
        if self.flags['items']:lines+=['/item 帮助：创建跟进事项、反馈、暂停、核验和关闭。']
        if self.flags['scheduler']:lines+=['/plan 帮助：一次或周期计划；显示完整规则后确认。']
        if self.flags['progress_collection']:lines+=['/update 项目编号：进展原文 → 核对 → 精确差异 → 批准。']
        if self.flags['precheck']:lines+=['/precheck 帮助：先绑定目标和要求，再预检材料。']
        lines+=['/doc logic 8d|test|charter：文档整理；/chat 返回普通对话。','/doc sample 与 /progress sample 为合成测试。']
        return '\n'.join(lines)

    def query(self,row):
        q=row['body'];projects=self.projects(row);scope=self.scope(row)
        meta=self.source_meta(row);reference=meta.get('parent') or meta.get('root')
        if reference:
            refs=self.s.rows('SELECT project_ref FROM am_query_refs WHERE message_id=? AND scope=? AND expires>?',(reference,scope,self.s.clock()))
            matches=[p for p in projects if refs and p['key']==refs[0]['project_ref'] and p.get('identity_status')=='verified']
            if len(matches)!=1:return '引用消息无法在当前身份和话题内确认有效项目，请明确项目编号或名称。'
            requested=identifiers(q)
            if requested and requested!=identifiers(matches[0]['title']):return '引用项目与本条编号不一致，请确认要查询的项目。'
            self.save_session(row,matches[0]['key'],None)
            return render_project(matches[0],fields_for(q),self.s.clock())
        session=self.s.rows('SELECT * FROM am_sessions WHERE scope=? AND expires>?',(scope,self.s.clock()))
        session=session[0] if session else None
        previous=session['focus'] if session else None
        pending=json.loads(session['pending']) if session and session['pending'] else None
        choice=choice_number(q)
        if choice and pending:
            if choice>len(pending['ids']):return '序号不在当前候选中。'
            matches=[p for p in projects if p['key']==pending['ids'][choice-1]];fields=pending['fields']
        else:
            fields=fields_for(q);requested,matches,unresolved,conflicts=resolve_identifiers(q,projects)
            if requested:
                parts=[render_project(p,fields,self.s.clock()) for p in matches]
                if unresolved:parts+=['未找到编号：'+'、'.join(unresolved)]
                if conflicts:parts+=['编号重复，身份待核对：'+'、'.join(conflicts)]
                focus=matches[0]['key'] if len(requested)==len(matches)==1 else None
                self.save_session(row,focus,None)
                return '\n\n'.join(parts)
            matches=select_projects(q,projects,previous)
        if len(matches)==1:
            self.save_session(row,matches[0]['key'],None)
            return render_project(matches[0],fields,self.s.clock())
        if not matches:return '请提供唯一项目编号或名称；当前无法可靠确定对象。'
        self.save_session(row,None,{'question':q,'ids':[p['key'] for p in matches[:5]],'fields':fields})
        return '请选择本次候选序号：\n'+'\n'.join(f'{i}. '+p['title'] for i,p in enumerate(matches[:5],1))

    def save_session(self,row,focus,pending):
        scope=self.scope(row)
        with self.s.tx() as c:
            c.execute('INSERT INTO am_sessions VALUES(?,?,?,1,?) ON CONFLICT(scope) DO UPDATE SET focus=excluded.focus,pending=excluded.pending,version=am_sessions.version+1,expires=MIN(am_sessions.expires,excluded.expires)',
                      (scope,focus,canonical(pending) if pending else None,row['expires']))
            if focus:c.execute('INSERT OR IGNORE INTO am_query_refs VALUES(?,?,?,?)',(row['id'],scope,focus,row['expires']))

    def briefing(self,row,*,changes_only=False):
        projects=self.projects(row)
        changes=self.ledger.catalog.changes()
        lines=['变化查询：记录文字变化不代表正式批准或验收改变。']
        if not changes:lines+=['暂无可比较的新变化；首次完整读取只建立基线。']
        for c in changes:
            stamp=datetime.fromtimestamp(c['read_at'],ZoneInfo('Asia/Shanghai'))
            lines += [f"{c['title']}｜{c['field']}｜{stamp.year}.{stamp.month}.{stamp.day} {stamp:%H:%M}\n原值：{c['before_value'] or '未记录'}\n现值：{c['after_value']}\n事件：{c['id'][:12]}"]
        if not changes_only:lines += [self.todos(row,projects=projects)]
        lines+=['来源：'+SOURCE+'?sheet='+SHEET,'主动查询不会改变订阅的投递记录。']
        text='\n\n'.join(lines)
        return text if len(text)<10000 else text[:9500]+'\n本次仅显示前部变化；完整记录仍保存在 AM。'

    def todos(self,row,*,projects=None,uncertain=False):
        if projects is None:projects=self.projects(row)
        lines=['需要你推动的协调、确认和验收事项；不是要求你亲自完成所有专业工作。']
        today=datetime.fromtimestamp(row.get('created',self.s.clock()),ZoneInfo('Asia/Shanghai'))
        today_terms={f'{today.year}.{today.month}.{today.day}',f'{today.year}-{today.month:02d}-{today.day:02d}'}
        dated=[];other=[]
        for p in projects:
            if uncertain:
                values=[p.get(k,'') for k in ('关键日期','人员与职责','项目进展')]
                selected=[v for v in values if re.search('待确认|未明确|待定|缺少|待核',v)]
                if not p.get('关键日期'):selected+=['日期未记录']
                if not p.get('人员与职责'):selected+=['人员职责未记录']
                if selected:lines.append(p['title']+'\n'+'\n'.join(selected))
            else:
                todo=p.get('待办','').strip()
                if todo and todo!='—':
                    entry=p['title']+'\n'+todo+('' if re.search('跟进|协调|确认|推动|组织|催办|决策',todo) else '\n推动动作与执行归属待核对。')
                    (dated if any(term in todo for term in today_terms) else other).append(entry)
        if dated:lines+=['原文明确出现今天日期的跟进项（预计、承诺或检查性质仍按原文）：']+dated
        if other:lines+=['其他重点／尚未明确今天期限：']+other
        if len(lines)==1:lines+=['台账未记录当前待跟进项；不代表项目全部完成。']
        lines+=['未写明确日期的事项不判为今天到期；预计、承诺与检查时间按原文保留。','来源：'+SOURCE]
        return '\n\n'.join(lines)

    def handle(self,row):
        if row['kind']=='menu':
            if row['body']=='home':return self.ux_home(row)
            if row['body']=='projects':return self.ux_projects(row)
            return self.ux_more_action(row,{'page':'more'})
        if row['kind']=='collection':return self.ux_collect_message(row)
        if row['kind']=='card':
            body=json.loads(row['body'])
            if body['value'].get('feedback'):return self.handle_feedback(row,body)
            c,action=self.validate_card(row)
            if c['flow']=='ux':return self.ux_handle(row,c,action)
            if hasattr(self,'handle_business_card'):return self.handle_business_card(row,c,action)
            raise BoundaryError('CARD_FEATURE_NOT_READY')
        q=row['body'].strip()
        if q in ('/am','/menu'):return self.ux_home(row)
        if q=='/help':return self.help()
        if q=='/status':
            def read_state(path):
                try:return json.loads(path.read_text())
                except (OSError,ValueError):return {}
            connection=read_state(self.ledger.root/'connection-status.json')
            reception=read_state(self.ledger.root/'event-status.json')
            model=read_state(self.g.config.root/'state/model-coordinator.json')
            baseline=self.ledger.db.execute('SELECT read_at FROM source_baselines WHERE namespace=?',(self.ledger.catalog.namespace,)).fetchone()
            fetch=datetime.fromtimestamp(baseline[0],ZoneInfo('Asia/Shanghai')).isoformat() if baseline else '尚未建立成功读取基线'
            delivery=self.s.rows('SELECT state,count(*) AS count FROM outbox GROUP BY state')
            scheduled=self.s.rows('SELECT state,count(*) AS count FROM reminder_occurrences GROUP BY state')
            writes=self.s.rows('SELECT state,count(*) AS count FROM ledger_write_attempts GROUP BY state')
            return ('连接最近记录：'+str(connection.get('state','未知'))+'\n接收最近记录：'+('已持久受理' if reception.get('accepted') else '未记录新的受理')+
                    '\n资料最近成功读取：'+fetch+'\n模型最近执行：'+str(model.get('state','尚无记录'))+'；暂停原因：'+str(self.s.meta('provider_pause') or '未记录暂停')+
                    '\n消息投递：'+canonical(delivery)+'\n计划实例：'+canonical(scheduled)+'\n台账写回：'+canonical(writes)+
                    '\n正式写回：'+('已配置，仍逐差异批准' if self.flags['ledger_write'] else '未启用；采集和提案可独立使用'))
        handled,result=self.update_command(row)
        if handled:return result
        handled,result=self.business_command(row)
        if handled:return result
        if not self.flags['query']:raise BoundaryError('QUERY_NOT_ENABLED')
        if q in ('/todo','我的待办','今天我需要跟进什么','今天我需要跟进什么？'):return self.todos(row)
        if q.startswith('哪些项目'):return self.todos(row,uncertain=True)
        if q in ('/changes','查看变化','项目变化'):
            if not self.flags['snapshots']:raise BoundaryError('SNAPSHOTS_NOT_ENABLED')
            return self.briefing(row,changes_only=True)
        if q in ('/briefing','变化简报'):return self.briefing(row)
        return self.query(row)

    def group_status(self,row,text):
        self.ledger.port.guard(row['chat'],row['user'])
        self.s.execute("UPDATE am_inbox SET state='sending' WHERE id=?",(row['id'],))
        try:self.ledger.reply(row['id'],re.sub(r'(?i)<(?=/?at\b)','＜',text))
        except Exception:
            self.s.execute("UPDATE am_inbox SET state='delivery_unknown' WHERE id=?",(row['id'],))
            raise BoundaryError('GROUP_REPLY_UNKNOWN')

    def step(self):
        self.ux_cleanup()
        self.s.execute("UPDATE am_inbox SET body='',state=CASE WHEN state='received' THEN 'expired' ELSE state END WHERE expires<=?",(self.s.clock(),))
        self.s.execute('DELETE FROM am_sessions WHERE expires<=?',(self.s.clock(),))
        self.s.execute('DELETE FROM am_query_refs WHERE expires<=?',(self.s.clock(),))
        self.s.execute('DELETE FROM am_source_meta WHERE id IN (SELECT id FROM am_inbox WHERE expires<=?)',(self.s.clock(),))
        self.s.execute("UPDATE am_cards SET snapshot='{}' WHERE expires<=?",(self.s.clock(),))
        rows=self.s.rows("SELECT * FROM am_inbox WHERE state='received' AND expires>? ORDER BY created LIMIT 1",(self.s.clock(),))
        if not rows:
            if self.scheduler:
                if self.flags['scheduler']:
                    for plan in self.s.rows("SELECT * FROM reminder_plans WHERE kind='briefing' AND state='active' AND next_at<=? AND valid_until>?",(self.s.clock(),self.s.clock())):
                        origin=self.owner_origin()
                        try:
                            if origin is None:raise BoundaryError('OWNER_ORIGIN_UNAVAILABLE')
                            self.projects(origin)
                            self.s.execute("UPDATE reminder_plans SET error=NULL WHERE id=? AND error='BRIEFING_SOURCE_UNAVAILABLE'",(plan['id'],))
                        except Exception:
                            self.s.execute("UPDATE reminder_plans SET error='BRIEFING_SOURCE_UNAVAILABLE' WHERE id=?",(plan['id'],))
                return self.scheduler.step()
            return False
        row=rows[0]
        if not self.s.execute("UPDATE am_inbox SET state='processing' WHERE id=? AND state='received'",(row['id'],)):return False
        try:
            if row['chat_type']=='group':self.ledger.port.guard(row['chat'],row['user'])
            elif row['user']==self.owner:self.ledger.port.authorize_user(row['user'])
            elif row['kind']!='card':raise BoundaryError('OWNER_ONLY')
            text=self.handle(row)
            if row['user']==self.owner:self.ledger.port.authorize_user(row['user'])
            if text:
                if row['chat_type']=='group':self.group_status(row,text)
                else:self.notify(row,text)
            self.s.execute("UPDATE am_inbox SET state='done' WHERE id=?",(row['id'],))
        except Exception as exc:
            if str(exc)=='GROUP_REPLY_UNKNOWN':return True
            code=str(exc) if isinstance(exc,(BoundaryError,ValueError)) and re.fullmatch('[A-Z_0-9]{1,80}',str(exc)) else 'AM_REQUEST_FAILED'
            self.s.execute("UPDATE am_inbox SET state='failed',error=? WHERE id=?",(code,row['id']))
            if row['chat_type']=='group':
                try:
                    self.group_status(row,'本次操作未完成：'+code+'。未据此写入台账。')
                    self.s.execute("UPDATE am_inbox SET state='failed',error=? WHERE id=?",(code,row['id']))
                except Exception:pass
            elif row['user']==self.owner:self.ux_error(row,code)
        return True
