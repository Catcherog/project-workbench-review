# De-identified review copy. Not configured for live execution.
# -*- coding: utf-8 -*-
import concurrent.futures,datetime,hashlib,json
import cli
r=cli.registry()
jobs=[]
for alias,item in {**r['projects'],**r['children']}.items():
    jobs.append(('object-'+alias,lambda a=alias,i=item:cli.get('final-object-'+a,i)))
    jobs.append(('hours-'+alias,lambda a=alias,i=item:cli.call('final-hours-'+a,['workhour','list-records','--project-key',cli.SPACE,'--work-item-id',str(i)])))
for alias,item in r['projects'].items():
    jobs.append(('nodes-'+alias,lambda a=alias,i=item:cli.nodes('final-nodes-'+a,i)))
    jobs.append(('history-'+alias,lambda a=alias,i=item:cli.call('final-history-'+a,['workitem','list-op-records','--project-key',cli.SPACE,'--work-item-id',str(i)])))
jobs.append(('reference',lambda:cli.get('reference-test-project-after',10001)))
jobs.append(('generic',lambda:cli.call('generic-usage-after',['workitem','query','--project-key',cli.SPACE,'--mql',"SELECT `工作项id`, `名称`, `项目类型`, `流程版本`, `更新时间` FROM `测试空间`.`项目` WHERE `项目类型` = '<id:20001>'"])))
jobs.append(('verify-history',lambda:cli.call('final-verification-history',['workitem','list-op-records','--project-key',cli.SPACE,'--work-item-id',str(r['children']['A-verify'])])))
out={}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
    futures={ex.submit(fn):name for name,fn in jobs}
    for f in concurrent.futures.as_completed(futures):
        name=futures[f]
        try:out[name]={'ok':True,'data':f.result()}
        except Exception as e:out[name]={'ok':False,'error':str(e)}
def rows(x):
    return sorted([{v['key']:v['value'] for v in row['moql_FIELD_10']} for group in x.get('data',{}).values() for row in group],key=lambda x:x['work_item_id']['long_value'])
before_generic=json.loads((cli.ROOT/'evidence/generic-usage-before.json').read_text())
before_ref=json.loads((cli.ROOT/'evidence/reference-test-project-before.json').read_text())
report={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'read_count':len(jobs),'errors':[k for k,v in out.items()if not v['ok']],
 'generic_16_project_rows_unchanged':out['generic']['ok'] and rows(out['generic']['data'])==rows(before_generic),
 'reference_attributes_unchanged':out['reference']['ok'] and out['reference']['data']['work_item_attribute']==before_ref['work_item_attribute'],
 'projects':{},'children':{},'hours':{},'schedules_empty':True,'people_only_operator':True}
for alias,item in r['projects'].items():
    d=out['object-'+alias]['data'];n=out['nodes-'+alias]['data']['list'];fields={v['key']:v['value']for v in d['work_item_fields']}
    report['projects'][alias]={'id':item,'template_version':fields.get('template_version'),'state':d['work_item_attribute']['work_item_status'],'nodes':[{'name':v['basic']['name'],'id':v['basic']['node_key'],'state':v['basic']['status'],'children':[i for g in v.get('sub_workitems',[])for i in g.get('workitems',[])]}for v in n]}
    for node in n:
        if any(node['schedule'].get(k) is not None for k in ['estimate_start_time','estimate_finish_time','points','actual_work_time']):report['schedules_empty']=False
        if any(x['user_key']!=cli.USER for x in (node.get('assignees',{}).get('owners')or[])):report['people_only_operator']=False
for alias,item in r['children'].items():
    d=out['object-'+alias]['data'];fields={v['key']:v['value']for v in d['work_item_fields']};a=d['work_item_attribute'];report['children'][alias]={'id':item,'state':a['work_item_status'],'key':fields.get('FIELD_11'),'review':fields.get('FIELD_02'),'version':fields.get('FIELD_08'),'source':fields.get('_instance_linked_virtual_resource_workitem'),'parent':fields.get('FIELD_06'),'node':fields.get('FIELD_01')}
    for role in a.get('role_members',[]):
        if any(x['key']!=cli.USER for x in role.get('members',[])):report['people_only_operator']=False
for k,v in out.items():
    if k.startswith('hours-'):report['hours'][k[6:]]=v
(cli.ROOT/'evidence/final-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items()if k not in ['children','hours']},ensure_ascii=False,indent=2))
print('Hours readback:',json.dumps({k:v.get('data') for k,v in report['hours'].items()},ensure_ascii=False))
