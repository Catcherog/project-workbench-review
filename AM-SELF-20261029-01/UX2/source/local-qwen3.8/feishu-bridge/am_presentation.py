"""N7–N10: deterministic rendering, versioned private navigation and recovery.

Business state stays in its owning services. Every view has an origin and an
outbox journal; an unknown PATCH never falls back to an unrelated CREATE.
"""
import json
import uuid
from fs_agent.project_catalog import canonical,digest
from fs_agent.config import BoundaryError
from fs_agent.card_ui import card,paragraph,button,field,bind_rendered_card
from fs_agent.presentation import ResponseEnvelope,visible_metrics

class PresentationMixin:
    def init_presentation(self):
        with self.s.lock:self.s.conn.executescript('''
        CREATE TABLE IF NOT EXISTS am_interactions(id TEXT PRIMARY KEY,scope TEXT NOT NULL,origin_event TEXT NOT NULL,kind TEXT NOT NULL,view_version INTEGER NOT NULL,message_id TEXT,current_view TEXT NOT NULL,subject_refs TEXT NOT NULL,pending_outbox TEXT,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS am_navigation(scope TEXT PRIMARY KEY,interaction_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS am_view_outputs(outbox_id TEXT PRIMARY KEY,interaction_id TEXT NOT NULL,version INTEGER NOT NULL,target_message TEXT,payload_hash TEXT NOT NULL,metrics TEXT NOT NULL,UNIQUE(interaction_id,version));
        CREATE TABLE IF NOT EXISTS am_collection_views(token TEXT PRIMARY KEY,interaction_id TEXT NOT NULL);
        ''')

    def bind_view(self,row,data):
        immutable=bool(data.get('immutable') or data.get('full_preview') or row.get('_immutable_output'))
        if immutable:
            ident=digest([data.get('business_event') or row['id'],row['user'],data.get('notice_kind'),data.get('output_kind','snapshot')])
            kind='immutable'
        else:
            ident=row.get('_interaction');kind=row.get('_view_kind','navigation')
            if not ident and row['kind']=='collection':
                receipt=self.s.rows('SELECT context FROM am_ux_receipts WHERE id=?',(row['id'],))
                token=json.loads(receipt[0]['context']).get('token') if receipt else None
                saved=self.s.rows('SELECT interaction_id FROM am_collection_views WHERE token=?',(token,))
                if saved:ident=saved[0]['interaction_id']
            if not ident and (row['kind']=='menu' or row.get('body') in ('/menu','/am')):
                head=self.s.rows('SELECT v.id FROM am_navigation n JOIN am_interactions v ON v.id=n.interaction_id WHERE n.scope=? AND v.expires>?',(self.scope(row),self.s.clock()))
                if head:ident=head[0]['id']
            if not ident:
                ident=digest([row['app'],row['tenant'],row['user'],row['id']]);kind=row.get('_view_kind') or ('query' if row['kind']=='text' and row.get('body') not in ('/menu','/am') else 'navigation')
        existing=self.s.rows('SELECT * FROM am_interactions WHERE id=?',(ident,))
        if existing:
            view=existing[0]
            if view['expires']<=self.s.clock():raise BoundaryError('VIEW_EXPIRED')
            if view['scope']!=self.scope(row):raise BoundaryError('VIEW_SCOPE_CHANGED')
            expected=row.get('_view_version')
            if expected is not None and not immutable and expected!=view['view_version']:raise BoundaryError('VIEW_CHANGED')
            if view['pending_outbox']:
                pending=self.s.rows('SELECT state FROM outbox WHERE id=?',(view['pending_outbox'],))
                if pending and pending[0]['state']=='unknown' and self.reconcile_view(ident):
                    view=self.s.rows('SELECT * FROM am_interactions WHERE id=?',(ident,))[0]
                elif pending and pending[0]['state'] in ('sending','unknown'):raise BoundaryError('VIEW_DELIVERY_UNKNOWN')
            if kind=='immutable':return view,True
        else:
            self.s.execute('INSERT INTO am_interactions VALUES(?,?,?,?,0,NULL,\'{}\',\'[]\',NULL,?)',(ident,self.scope(row),row['id'],kind,row['expires']))
            view=self.s.rows('SELECT * FROM am_interactions WHERE id=?',(ident,))[0]
        if not immutable:row['_interaction']=ident;row['_view_version']=view['view_version']
        return view,False

    def ux_page(self,row,title,text,actions=(),*,fields=None,submit=None,data=None):
        data=dict(data or {})
        if row.get('_business_event'):data['business_event']=row['_business_event']
        if '预览' in title:data['full_preview']=True
        long_view=data.get('_long_view')
        if long_view is None and len(text.encode('utf-8'))>9000:
            long_view={'text':text,'actions':list(actions),'title':title}
            data['_long_view']=long_view
            data['detail']=True
        if long_view:
            raw=long_view['text'];pages=[]
            while raw:
                end=min(2300,len(raw))
                if end<len(raw):
                    boundary=raw.rfind('\n',0,end)
                    if boundary>500:end=boundary+1
                pages.append(raw[:end]);raw=raw[end:]
            index=max(0,min(data.get('_long_index',0),len(pages)-1))
            text=f'完整内容 · 第 {index+1}/{len(pages)} 页\n'+pages[index]
            actions=[]
            if index:actions.append(('上一页',{'page':'long_content','offset':index-1}))
            if index+1<len(pages):actions.append(('继续阅读',{'page':'long_content','offset':index+1}))
            else:actions+=long_view['actions']
        view,replayed=self.bind_view(row,data)
        if replayed:return None
        row=dict(row,expires=min(row['expires'],view['expires']))
        version=view['view_version']+1;nonce=digest([view['id'],version]);actions=list(actions)
        if fields is not None:actions.append((submit[0],submit[1]))
        snapshot={'actions':{str(i):a for i,(label,a) in enumerate(actions)},'data':data,'fields':fields,
                  'thread':row.get('thread') or self.source_meta(row).get('thread'),'app':row['app'],'tenant':row['tenant'],
                  'interaction_id':view['id'],'view_version':version,'navigation_parent':row.get('_interaction') if view['kind']=='immutable' else None}
        envelope=ResponseEnvelope(view['id'],version,data.get('subject_refs',[]),data.get('task_state','details'),text,
            facts=data.get('facts',[]),mandatory_qualifiers=data.get('mandatory_qualifiers',[]),primary_action=actions[0][1] if actions else None,
            secondary_actions=[a for _,a in actions[1:]],detail_ref=data.get('detail_ref'),source_revision=data.get('source_revision'),
            exception='full_preview' if data.get('full_preview') else 'detail' if data.get('detail') else None)
        snapshot['envelope']=envelope.validate()
        from group_ledger import SOURCE,SHEET
        source_link=f'[查看来源原文]({SOURCE}?sheet={SHEET})'
        shown=text
        has_source=shown.endswith(source_link)
        if has_source:shown=shown[:-len(source_link)].rstrip('｜\n ')
        if shown.startswith(title+'\n'):shown=shown[len(title)+1:]
        elements=[paragraph(shown)] if shown else []
        if has_source:elements.append({'tag':'markdown','content':source_link})
        if fields is not None:
            inputs=[]
            for name,spec in fields.items():inputs+=field(name,spec['label'],kind=spec.get('kind','input'),options=spec.get('options'),default=spec.get('default'),required=spec.get('required',True))
            submit_button=button(submit[0],{'flow':'am_self','nonce':nonce,'action':str(len(actions)-1)},name='submit',submit=True);submit_button['type']='primary'
            inputs.append(submit_button);elements.append({'tag':'form','name':'ux_form','elements':inputs});visible=actions[:-1]
        else:visible=actions
        for i,(label,action) in enumerate(visible):
            control=button(label,{'flow':'am_self','nonce':nonce,'action':str(i)})
            if fields is None and i==0:control['type']='primary'
            elements.append(control)
        # Split only for transport, retaining every character. This is reserved
        # for explicitly opened detail and exact previews, never a summary cut.
        expanded=[]
        for el in elements:
            if el['tag']=='div' and len(el['text']['content'])>3500:
                value=el['text']['content'];expanded.extend(paragraph(value[i:i+3500]) for i in range(0,len(value),3500))
            else:expanded.append(el)
        rendered=bind_rendered_card(card(title,expanded));metrics=visible_metrics(rendered);metrics.update(exception=envelope.exception,origin_event=row['id'],created=self.s.clock())
        fingerprint=digest(snapshot)
        with self.s.tx() as c:
            current=c.execute('SELECT * FROM am_interactions WHERE id=?',(view['id'],)).fetchone()
            if current['view_version']!=view['view_version']:raise BoundaryError('VIEW_CHANGED')
            if current['pending_outbox']:
                pending=c.execute('SELECT state FROM outbox WHERE id=?',(current['pending_outbox'],)).fetchone()
                if pending and pending['state'] in ('sending','unknown'):raise BoundaryError('VIEW_DELIVERY_UNKNOWN')
                if pending and pending['state']=='pending':c.execute("UPDATE outbox SET state='rejected',error='VIEW_SUPERSEDED' WHERE id=?",(current['pending_outbox'],))
            out=self.notify(row,card=rendered,kind=data.get('notice_kind','card'),object_id=nonce,version=version,hash=fingerprint,conn=c,event_key=data.get('business_event'))
            target=current['message_id'] if current['kind']!='immutable' and not data.get('immutable') else None
            c.execute('INSERT INTO am_view_outputs VALUES(?,?,?,?,?,?)',(out,view['id'],version,target,digest(rendered),canonical(metrics)))
            c.execute('INSERT INTO am_cards VALUES(?,?,?,?,?,?,?,?,?,?,NULL)',(nonce,'ux',nonce,version,row['user'],row['chat'],canonical(snapshot),fingerprint,min(row['expires'],self.s.clock()+3600),out))
            c.execute('UPDATE am_interactions SET view_version=?,current_view=?,subject_refs=?,pending_outbox=? WHERE id=?',(version,canonical(snapshot),canonical(envelope.subject_refs),out,view['id']))
            if current['kind']=='navigation':c.execute('INSERT INTO am_navigation VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET interaction_id=excluded.interaction_id',(self.scope(row),view['id']))
            context=c.execute("SELECT token FROM am_ux_collection WHERE scope=? AND state='active'",(self.scope(row),)).fetchone()
            if context and current['kind']!='immutable':c.execute('INSERT OR IGNORE INTO am_collection_views VALUES(?,?)',(context['token'],view['id']))
            if c.execute('SELECT 1 FROM am_query_refs WHERE message_id=? AND expires>?',(row['id'],self.s.clock())).fetchone():c.execute("UPDATE am_notifications SET kind='query',object_id=? WHERE outbox_id=?",(row['id'],out))
        row['_view_version']=version
        return None

    def view_delivery(self,row):
        rows=self.s.rows('SELECT * FROM am_view_outputs WHERE outbox_id=?',(row['id'],))
        if not rows:return None
        output=rows[0];view=self.s.rows('SELECT * FROM am_interactions WHERE id=?',(output['interaction_id'],))[0]
        if output['version']!=view['view_version']:return False
        return output

    def reconcile_view(self,ident):
        view=self.s.rows('SELECT * FROM am_interactions WHERE id=?',(ident,))[0]
        if not view['pending_outbox']:return True
        rows=self.s.rows('SELECT * FROM outbox WHERE id=?',(view['pending_outbox'],));out=rows[0]
        if out['state']!='unknown':return out['state']=='sent'
        delivery=self.view_delivery(out)
        # CREATE without a received message ID remains unknown; do not infer
        # absence and resend. PATCH can be read at its already bound identity.
        if not delivery or not delivery['target_message']:return False
        if not self.g.api.verify_card(delivery['target_message'],out):return False
        with self.s.tx() as c:
            c.execute("UPDATE outbox SET state='sent',message_id=?,error=NULL WHERE id=?",(delivery['target_message'],out['id']))
            self.delivered(c,out,delivery['target_message'])
        return True
