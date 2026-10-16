# De-identified review copy. Not configured for live execution.
# -*- coding: utf-8 -*-
import json
import cli
x=cli.nodes('verification-resources-generated',10004)
ids=next(n for n in x['list'] if n['basic']['node_key']=='state_3')['sub_workitems'][0]['workitems']
print(ids,flush=True)
assert len(ids)==2
r=cli.registry()
for i in ids:
    d=cli.get('verification-child-'+str(i)+'-before',i)
    is_test='验19' in d['work_item_attribute']['work_item_name']
    key='A-verify' if is_test else 'A-handover'
    r['children'][key]=i
    (cli.ROOT/'registry.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
    cli.update(key+'-failed-iteration',i,{
        'FIELD_11':'LF.R1.S4.'+('VERIFY' if is_test else 'HANDOVER'),
        'FIELD_12':'state_3','FIELD_07':'10004',
        'FIELD_08':'R1-synthetic-v1','FIELD_02':'reviewed','FIELD_03':'applicable',
        'FIELD_04':('合成整体验证v1：资料入口版本指向不一致，结果不通过，问题R1-ISSUE-01待修复复验。' if is_test else '合成移交记录v1：模拟交付与维护责任已记录；不代表真实部署、实际客户接收或业务批准。'),
        'FIELD_05':('R1合成验证不通过；已审核仅表示工程师对本结果负责，不能当成验证通过。' if is_test else 'R1合成移交完成；本期维护承接人仅测试操作者，后续网站迁移不在本期，未实施。')
    },[{'op':'add','role_key':'ROLE_DELIVERABLE_OWNER','user_keys':[cli.USER]}])
r['resource_ids'] += [10002,10003]
(cli.ROOT/'registry.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
print(json.dumps(r,ensure_ascii=False),flush=True)
