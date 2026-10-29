"""Original bot transport for scheduled messages and bound feedback cards."""
import json
import re
import uuid
import time
from .config import BoundaryError
from .feishu import SendRejected,SendUnknown,classify_send_failure
from .project_catalog import canonical
from .reminder_content import normalized_payload


class BusinessPort:
    def __init__(self,gateway,ledger):self.g,self.ledger=gateway,ledger;self.reminder=gateway.reminders.port

    def prepare(self,payload,occurrence_id):
        if payload['target']['kind']=='owner':return payload
        source=payload['target']['payload']
        nonce=uuid.uuid5(uuid.NAMESPACE_URL,'feedback/'+occurrence_id).hex
        people=source['people']
        mentions=' '.join('<at id="'+p['id']+'"></at>' for p in people)
        # Only the code-owned mention line uses Markdown. The user body is a
        # plain_text div and cannot synthesize an @all or another button.
        actions=[('received','已收到'),('eta','预计完成时间'),('help','需要协助'),('submitted','已提交材料'),('not_mine','非本人负责')]
        buttons=[{'tag':'button','text':{'tag':'plain_text','content':label},'value':{'flow':'am_self','feedback':occurrence_id,'nonce':nonce,'action':kind}} for kind,label in actions]
        card={'config':{'wide_screen_mode':True},'header':{'title':{'tag':'plain_text','content':'AM 跟进事项'}},'elements':[
            {'tag':'div','text':{'tag':'lark_md','content':mentions}},
            {'tag':'div','text':{'tag':'plain_text','content':payload['body']}},
            {'tag':'div','text':{'tag':'plain_text','content':'事项 '+str(payload['item_id'])+' v'+str(payload['item_version'])+'\n收到不代表完成；提交材料仍需核验。\n预计时间、协助内容或材料链接可用：/feedback '+occurrence_id+' 类型｜具体内容'}},
            {'tag':'action','actions':buttons}]}
        return dict(payload,card=card,feedback_nonce=nonce)

    def refresh(self,payload):
        target=payload['target']
        if target['kind']=='owner':
            if target['user']!=self.g.config.owner:raise BoundaryError('OWNER_TARGET_CHANGED')
            self.ledger.port.authorize_user(target['user']);return
        self.reminder.refresh(target['payload'])

    def send(self,payload,key,guard):
        from lark_oapi.api.im.v1 import CreateMessageRequest,CreateMessageRequestBody
        self.refresh(payload)
        if not guard():raise SendRejected('SCHEDULER_SEND_GUARD')
        t=payload['target'];private=t['kind']=='owner'
        target=t['user'] if private else t['payload']['group']['id']
        kind='text' if private else 'interactive'
        content={'text':payload['body']} if private else payload['card']
        req=(CreateMessageRequest.builder().receive_id_type('open_id' if private else 'chat_id').request_body(
            CreateMessageRequestBody.builder().receive_id(target).msg_type(kind).content(canonical(content)).uuid(key).build()).build())
        if not guard():raise SendRejected('SCHEDULER_SEND_GUARD')
        try:r=self.g.api.client.im.v1.message.create(req)
        except Exception:raise SendUnknown('SCHEDULED_SEND_UNKNOWN') from None
        if not r.success():classify_send_failure(r,'SCHEDULED')
        if not r.data or not r.data.message_id:raise SendUnknown('SCHEDULED_RECEIPT_MISSING')
        return {'message_id':r.data.message_id,'sent_at':time.time()}

    def verify(self,payload,m):
        if m['deleted'] or m['sender_id']!=self.g.config.bot_open_id or m['sender_type'] not in ('app','bot'):return False
        t=payload['target'];private=t['kind']=='owner'
        if not private and m['chat_id']!=t['payload']['group']['id']:return False
        if private:
            # The exact owner chat is bound when the subscription is created.
            if m['chat_id']!=t['chat']:return False
        try:content=json.loads(m['content']) if isinstance(m['content'],str) else m['content']
        except ValueError:return False
        return m['msg_type']==('text' if private else 'interactive') and content==({'text':payload['body']} if private else payload['card'])

    def reconcile(self,payload,key,started,message_id=None):
        if not message_id:
            # A bounded bot-originated lookup is permitted only for an already
            # approved group. No synthetic probe and no inference from absence.
            if payload['target']['kind']=='owner' or not self.reminder.policy()['reconcile_own_attempts']:return None
            from lark_oapi.api.im.v1 import ListMessageRequest
            group=payload['target']['payload']['group']['id']
            if not self.reminder.allowed(group):return None
            request=(ListMessageRequest.builder().container_id_type('chat').container_id(group)
                     .start_time(str(int(started)-2)).end_time(str(int(started)+125)).page_size(50).build())
            data=self.reminder._data(self.g.api.client.im.v1.message.list(request))
            if data.has_more:return None
            matches=[self.reminder._message(m) for m in data.items or []]
            matches=[m for m in matches if self.verify(payload,m)]
            if len(matches)!=1:return None
            message=matches[0]
        else:message=self.reminder.read(message_id)
        if not self.verify(payload,message):return None
        return {'verified':True,'message_id':message['message_id'],'sent_at':message['created_at']}
