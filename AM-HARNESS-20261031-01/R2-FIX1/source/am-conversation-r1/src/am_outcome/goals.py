"""Durable obligation journal; original tools/receipts remain execution authority."""
import json
import re
from .completion import resolve_goals, check_goals, matches_goal
from .adapters import adapt
from .types import encode, fingerprint
from am_conversation.types import ConversationError


class GoalJournal:
    def __init__(self, store, ctx, event, text, catalog):
        self.store,self.ctx,self.event=store,ctx,event
        now=store._now();self.expires=min(ctx.content_expires_at or now+86400,now+86400)
        with store._connection() as db:
            rows=db.execute("SELECT * FROM conversation_goals_v2 WHERE scope_key=? AND expires>? AND state NOT IN ('fulfilled','cancelled') ORDER BY updated DESC",(ctx.session_id,now)).fetchall()
        continuing=bool(re.match(r'^(?:继续|剩下|接着|刚才|取消剩余)',text))
        if continuing and len(rows)==1:
            self.id=rows[0]['goal_id'];self.data=json.loads(rows[0]['data_json']);self.expires=min(self.expires,rows[0]['expires'])
            if self.data.get('source_access_version') != ctx.source_access_version:
                raise ConversationError('SOURCE_ACCESS_CHANGED')
            if any(g.get('project_id') and not ctx.can_access_project(g['project_id']) for g in self.data['goals']):
                raise ConversationError('SOURCE_ACCESS_CHANGED')
            self.data['continuation_input']=text
            if text.startswith('取消剩余'):
                self.data['cancelled']=True
            # Reconcile confirmed external results through the original store.
            for key,u in list(self.data['units'].items()):
                if u.get('effect')!='external':continue
                action=u.get('result',{}).get('action_id')
                if not action or u['completion']=='fulfilled':continue
                # Full receipt access must retain the original source/scope
                # checks. Metadata deliberately omits the result payload.
                if not ctx.is_owner:raise ConversationError('OWNER_REQUIRED')
                row=store.get_action(ctx,action)
                if (row['tool_name']!=u['operation'] or row['arguments']!=u['target']
                        or row['version']!=u['result'].get('version')):
                    self.data['ambiguous']=True
                    continue
                if row['status'] in ('succeeded','unknown','executing','failed','cancelled','expired'):
                    raw=dict(row['result']) if isinstance(row.get('result'),dict) else {}
                    if row['status']!='succeeded':
                        raw.update(status=row['status'],verified=False,action_id=action,version=row['version'])
                    restored=adapt(u['operation'],u['target'],raw,u['effect'],key=key)
                    self.data['units'][key]=restored
                    # Restore both views. Reusing the old draft cache would
                    # downgrade the reconciled unit on an exact repeated call.
                    self.data['calls'][key]={'state':'unknown' if restored['status']=='unknown' else restored['completion'],
                                             'result':raw,'native_action_id':action}
        else:
            self.id=fingerprint([ctx.scope,event,'goals'])
            goals,complete=resolve_goals(text,catalog)
            self.data={'schema_version':'am-goals/1','source_access_version':ctx.source_access_version,'request':text,'goals':goals,'complete':complete,'units':{},'calls':{},'ambiguous':continuing and len(rows)>1,'cancelled':False}
        self.save()

    def save(self):
        progress,state=check_goals(self.data['goals'],self.data['complete'],list(self.data['units'].values()))
        self.data['progress']=progress
        self.data['completion']=state
        if self.data['cancelled']:state='cancelled'
        with self.store._connection(write=True) as db:
            db.execute('INSERT INTO conversation_goals_v2 VALUES(?,?,?,?,?,?) ON CONFLICT(goal_id) DO UPDATE SET data_json=excluded.data_json,state=excluded.state,updated=excluded.updated,expires=MIN(expires,excluded.expires)',
                (self.id,self.ctx.session_id,encode(self.data),state,self.expires,self.store._now()))

    def before(self,name,args,effect):
        if effect=='read':return None
        if self.data['ambiguous'] or self.data['cancelled']:raise ConversationError('GOAL_SELECTION_REQUIRED')
        key=fingerprint([name,args]);prior=self.data['calls'].get(key)
        if prior:
            if prior['state']=='fulfilled':return prior['result']
            if prior['state'] in ('executing','unknown'):raise ConversationError('GOAL_RESULT_RECONCILE_REQUIRED')
            if prior['state']=='awaiting_approval' or (prior['state']=='blocked' and prior.get('native_action_id')):
                return prior['result']
        # A changed payload must not silently replay an already committed matter.
        unit={'operation':name,'target':args}
        for goal in self.data['progress']:
            if goal['completion']=='fulfilled' and matches_goal(goal,unit,require_matter=True):
                refs=goal['receipt_refs']
                if refs:return self.data['units'][refs[0]]['result']
        self.data['calls'][key]={'state':'executing','operation':name,'arguments':args,'engine_event_id':self.event}
        self.save();return None

    def record(self,name,args,result,effect):
        key=fingerprint([name,args]);unit=adapt(name,args,result,effect,key=key)
        self.data['units'][key]=unit
        if effect!='read':
            prior=self.data['calls'].get(key,{})
            self.data['calls'][key]={'state':'unknown' if unit['status']=='unknown' else unit['completion'],'result':result}
            if prior.get('native_action_id'):self.data['calls'][key]['native_action_id']=prior['native_action_id']
        self.save()

    def context(self):
        return {'goal_id':self.id,'goals':self.data['progress'],'request':self.data['request'],
                'complete_request_coverage':self.data['complete'],'ambiguous':self.data['ambiguous'],
                'rule':'仅处理未完成目标；已提交步骤不得重放，未知结果先核对。'}

    def fulfilled(self):
        return self.data['completion']=='fulfilled'
