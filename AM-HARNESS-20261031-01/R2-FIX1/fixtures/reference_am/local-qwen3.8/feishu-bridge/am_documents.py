"""Document views reuse the original question ledger, adoption and mount journal."""
import json
import uuid
from fs_agent.config import BoundaryError
from fs_agent.project_catalog import canonical,digest
from fs_agent.presentation import ResponseEnvelope
from fs_agent.card_ui import card,paragraph,button,bind_rendered_card
from fs_agent.store import scope_of

class DocumentViewsMixin:
    def document_summary(self,d):
        analysis=json.loads(d['analysis'] or '{}')
        status={'ready':'阶段稿已形成' if d['stage'] else '候选稿已形成','collecting':'正在收集资料','dirty':'已收到新资料，待重新整理','paused':'已暂停','cancelled':'已放弃'}.get(d['state'],'正在整理')
        lines=[status+'；'+('已采用当前文字，尚需核对挂载状态。' if d['accepted_hash'] and d['accepted_hash']==d['content_hash'] else '尚未采用或挂载。')]
        for q in analysis.get('questions',[])[:2]:lines.append(q['ask'])
        if not analysis.get('questions'):lines.append('可打开稿件与核对报告，确认后再选择后续操作。')
        return '\n'.join(lines)

    def document_completion(self,task,result,conn):
        if task['chat_type']!='p2p':return False
        job=conn.execute('SELECT draft_id FROM logic_jobs WHERE task_id=?',(task['id'],)).fetchone()
        if not job:return False
        d=dict(conn.execute('SELECT * FROM logic_drafts WHERE id=?',(job[0],)).fetchone())
        row=dict(task,kind='text',id=task['id'])
        nonce=digest(['document-result',task['id'],d['revision']])
        actions=[('查看稿件',{'page':'documents','draft':d['id'],'section':'content'}),('处理稿件',{'page':'documents','draft':d['id'],'section':'actions'}),('核对报告',{'page':'documents','draft':d['id'],'section':'review'})]
        summary=self.document_summary(d)
        env=ResponseEnvelope(task['id'],1,[d['id']],d['state'],summary,detail_ref={'draft':d['id'],'revision':d['revision']}).validate()
        snapshot={'actions':{str(i):a for i,(_,a) in enumerate(actions)},'fields':None,'data':{'document_revision':d['revision']},'thread':None,'app':task['app'],'tenant':task['tenant'],'envelope':env}
        controls=[button(label,{'flow':'am_self','nonce':nonce,'action':str(i)}) for i,(label,_) in enumerate(actions)]
        controls[0]['type']='primary'
        rendered=bind_rendered_card(card('文稿整理', [paragraph(summary)]+controls))
        out=self.notify(row,card=rendered,kind='document_result',object_id=d['id'],version=d['revision'],hash=digest(snapshot),conn=conn,event_key='doc/'+task['id'])
        conn.execute('INSERT OR IGNORE INTO am_cards VALUES(?,?,?,?,?,?,?,?,?,?,NULL)',(nonce,'ux',d['id'],d['revision'],task['user'],task['chat'],canonical(snapshot),digest(snapshot),task['expires'],out))
        return True

    def ux_documents(self,row,a):
        logic=self.g.logic;ident=a.get('draft');section=a.get('section')
        if a.get('kind'):
            d=logic.create(row,a['kind']);self.s.select(row,'doc')
            self.s.execute("INSERT INTO bridge_mode VALUES(?,'poc',?) ON CONFLICT(scope) DO UPDATE SET mode='poc',expires=excluded.expires",(self.scope(row),row['expires']))
            return self.ux_page(row,'文稿整理','请发送文字或附件。当前文种已选定；可一次提供已有资料。',[('查看当前稿',{'page':'documents','draft':d['id']}),('返回首页',{'page':'home'})])
        d=logic.get(row,ident) if ident else logic.current(row)
        if not d:return self.ux_page(row,'文稿整理','选择文种后发送资料。',[(label,{'page':'documents','kind':kind}) for kind,label in [('test','测试报告'),('8d','异常分析'),('charter','项目章程')]])
        base={'page':'documents','draft':d['id']};back=[('返回当前稿',base)]
        if section in ('content','review'):
            text=d['content'] or '尚无当前稿件。'
            if section=='review':
                review=json.loads(d['review'] or '{}');analysis=json.loads(d['analysis'] or '{}')
                text='核对报告\n'+analysis.get('assessment','尚未完成核对。')+'\n'+json.dumps(review,ensure_ascii=False,indent=2)
            return self.ux_page(row,'稿件全文' if section=='content' else '完整核对报告',text,back,data={'detail':True})
        if section=='actions':
            actions=[]
            if d['state']=='ready' and d['content_hash'] and d['accepted_hash']!=d['content_hash']:actions.append(('采用当前文字',dict(base,section='adopt',revision=d['revision'],hash=d['content_hash'])))
            actions += [('选择挂载目标',dict(base,section='targets'))]
            if d['accepted_hash'] and d['accepted_hash']==d['content_hash'] and d['target']:actions.append(('查看挂载预览',dict(base,section='mount_preview')))
            return self.ux_page(row,'稿件操作',self.document_summary(d),actions+back)
        if section=='adopt':
            if d['revision']!=a['revision'] or d['content_hash']!=a['hash']:raise BoundaryError('LOGIC_NO_CURRENT_DRAFT')
            logic.adopt(row,d['id']);return self.ux_documents(row,dict(base,section='actions'))
        if section=='targets':
            targets=getattr(logic.business,'settings',{}).get('targets',{})
            return self.ux_page(row,'选择挂载目标','采用文字与挂载为独立操作。',[(v.get('label',key),dict(base,section='target',target=key)) for key,v in targets.items()]+back)
        if section=='target':
            logic.select_target(row,d['id'],a['target']);return self.ux_documents(row,base)
        if section=='mount_preview':
            if not d['target'] or d['accepted_hash']!=d['content_hash']:raise BoundaryError('CONTENT_ADOPTION_REQUIRED')
            target=json.loads(d['target'])
            if logic.business.resolve(row,target['id'])!=target:raise BoundaryError('TARGET_REVISION_CHANGED')
            text='准确挂载目标：\n'+'\n'.join(str(k)+'：'+str(v) for k,v in target.items())+'\n当前稿件版本：'+str(d['revision'])+'\n稿件指纹：'+d['content_hash']+'\n仅挂载已采用稿件，不改变专业审核或节点完成状态。'
            return self.ux_page(row,'准确挂载预览',text,[('确认挂载当前稿',dict(base,section='mount',revision=d['revision'],hash=d['content_hash'],target=target)),('查看稿件',dict(base,section='content'))],data={'full_preview':True})
        if section=='mount':
            if d['revision']!=a['revision'] or d['content_hash']!=a['hash'] or json.loads(d['target'] or '{}')!=a['target']:raise BoundaryError('TARGET_REVISION_CHANGED')
            result=logic.mount(row,d['id']);text=result['message']
            if result.get('receipt'):text+='\n查看交付物：'+result['receipt']['url']
            return self.ux_page(row,'挂载结果',text,[('核对原挂载',dict(base,section='reconcile')),('返回当前稿',base)],data={'immutable':True,'business_event':digest(['mount',d['id'],d['revision'],d['content_hash']])})
        if section=='reconcile':return self.ux_page(row,'挂载核对',logic.reconcile_draft(row,d['id']),back)
        return self.ux_page(row,'当前稿件',self.document_summary(d),[('查看稿件',dict(base,section='content')),('处理稿件',dict(base,section='actions')),('核对报告',dict(base,section='review'))])
