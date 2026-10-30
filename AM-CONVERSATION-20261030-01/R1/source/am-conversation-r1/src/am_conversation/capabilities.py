"""Load relevant tool schemas without making unavailable powers implicit."""
import re
from .tools import Tool,obj,string

AREAS={
 'followups':{'list_followups','create_followup','change_followup','close_followup','submit_followup_feedback'},
 'sending':{'list_targets','send_message','reconcile_send','list_pending_actions','revise_pending_action'},
 'reminders':{'list_targets','schedule_reminder','list_reminders','control_reminder','revise_reminder','list_pending_actions','revise_pending_action'},
 'documents':{'read_documents','edit_document','publish_document','list_pending_actions','revise_pending_action'},
 'updates':{'submit_project_update','list_project_updates','adopt_project_update'},
 'knowledge':{'search_knowledge','propose_knowledge','list_knowledge_candidates','revise_knowledge'},
 'briefings':{'read_briefing','subscribe_briefing','list_reminders','control_reminder'},
 'information':{'read_information','list_projects','read_project'},
}
PATTERNS={
 'followups':r'跟进|事项|负责人|反馈|暂停|关闭|取消|处理中',
 'sending':r'发给|发送|发群|发.*(?:消息|这条|那条)|通知|催|核对.*发送',
 'reminders':r'提醒|闹钟|定时|每天|工作日|改.*时间|暂停|取消',
 'documents':r'文稿|文档|章程|生成|撰写|整理.*报告|写.*报告|新建.*报告|预检|挂载|云端|这版',
 'updates':r'更新.*进展|同步.*进展|提交.*进展|台账|更正|提案|项目反馈',
 'knowledge':r'知识|规则|以后|习惯|原则|教你|改.*写法|学习',
 'briefings':r'简报|订阅|哪些.*变化|项目变化|汇总',
 'information':r'最新|消息|审批|新反馈|信息来源|资料来源|同步信息',
}
BASE={'list_projects','read_project','read_information','search_knowledge','list_work_notes','save_work_note','update_work_note','record_report','list_followups','discover_capabilities'}

def install(bridge):
    def discover(ctx,args,event):
        current=bridge._current(ctx);area=args['area']
        current.setdefault('expanded_tools',set()).update(AREAS[area])
        return {'area':area,'available_tools':[{'name':t.name,'purpose':t.description} for t in bridge.registry._tools.values() if t.name in AREAS[area] and (ctx.is_owner or not t.owner_only)]}
    bridge.registry.register(Tool('discover_capabilities','按需取得现有业务工具。可用类别：followups跟进、sending发送、reminders提醒、documents文稿、updates进展提案、knowledge教学、briefings简报、information信息来源；未看到对应工具时先查询，不编造能力。',obj({'area':{'type':'string','enum':list(AREAS)}},('area',)),discover))
    def choose(ctx,tools):
        try:current=bridge._current(ctx)
        except Exception:return [t for t in tools if t.name in BASE]
        names=set(BASE)|current.get('expanded_tools',set());text=current['row']['body']
        for area,pattern in PATTERNS.items():
            if re.search(pattern,text):names.update(AREAS[area])
        # If a request spans several areas, retain a bounded catalog. Discovery
        # can load another area on the next loop without changing capabilities.
        return [t for t in tools if t.name in names][:32]
    bridge.registry.selector=choose

def information(bridge,ctx,args,event):
    bridge.authorize(ctx,'read',args);host=getattr(bridge.service,'information',None)
    if host is None:return {'available':False,'message':'当前信息源模块尚未接入，可先查询台账记录。'}
    raw=host.query(bridge._current(ctx)['row'],args['project_id'])
    offset=args.get('offset',0);limit=args.get('limit',6);selected=[];size=0
    from .types import canonical
    facts=[f for f in raw['facts'] if not args.get('exclude_ledger') or f.get('field')!='ledger_record']
    if args.get('fact_id'):facts=[f for f in facts if f['fact_id']==args['fact_id']]
    for fact in facts[offset:offset+limit]:
        projected={k:fact[k] for k in ('fact_id','subject_id','field','assertion_type','business_state','status') if k in fact}
        evidence=fact.get('evidence',{})
        projected['evidence']={k:v for k,v in evidence.items() if k in ('source_id','object_id','version','url','occurred_at_ms','observed_at_ms','locator','completeness','read_status','time_basis') and len(canonical(v))<=1000}
        value=fact.get('value');section=args.get('section','summary')
        if section!='summary' and isinstance(value,dict):
            value={section:value[section]} if section in value else {'requested_section_unavailable':section,'available_sections':list(value)}
        elif fact.get('field')=='system_record' and isinstance(value,dict):
            reduced={k:value[k] for k in ('title','summary','status','instance_status','project_code','doc_type') if k in value and len(canonical(value[k]))<=1200}
            if isinstance(value.get('basic'),dict):reduced['basic']={k:v for k,v in value['basic'].items() if k in ('name','status','priority','work_item_type','work_item_name','auto_number')}
            reduced['available_sections']=list(value);reduced['selection_note']='仅为所列字段摘要，其余字段未在本次展开'
            value=reduced
        if len(canonical(value))>2600:
            projected.update(value_omitted=True,available_sections=list(value) if isinstance(value,dict) else [],note='此条正文较长，未截断为完整事实；请指定字段或查看其来源原文。')
        else:projected['value']=value
        if size+len(canonical(projected))>5500:break
        selected.append(projected);size+=len(canonical(projected))
    coverage={k:v for k,v in raw['coverage'].items() if k!='sources' and len(canonical(v))<=1000}
    sources=raw['coverage'].get('sources',[]);coverage['source_count']=len(sources);coverage['sources']=[]
    for source in sources:
        compact={k:v for k,v in source.items() if k in ('source_id','availability','last_checked_ms','stale','unprocessed_jobs','gap_kinds','completeness')}
        if len(canonical(coverage))+len(canonical(compact))>2200:break
        coverage['sources'].append(compact)
    coverage['source_details_omitted']=len(coverage['sources'])<len(sources)
    return {'available':True,'version':raw['version'],'coverage':coverage,'facts':selected,'has_more':offset+len(selected)<len(facts),
            'next_offset':offset+len(selected),'complete_response':offset==0 and len(selected)==len(facts) and not any(f.get('value_omitted') or isinstance(f.get('value'),dict) and f['value'].get('selection_note') for f in selected),
            'boundary':'来源报告、预测和已核实事实分别保留；覆盖和解析积压以coverage为准。只读取所列字段，未展开内容不等于不存在。'}
