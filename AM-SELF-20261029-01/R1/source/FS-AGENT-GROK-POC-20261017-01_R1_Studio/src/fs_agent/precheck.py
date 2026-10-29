"""Target-first, evidence-bounded document precheck; never approves engineering work."""
import json
import re
from pathlib import Path
from .config import BoundaryError
from .project_catalog import canonical,digest
from .provider import Result


def inspect_materials(sources,requirements):
    categories={'已具备':[],'缺少':[],'冲突':[],'需专业判断':[]}
    segments=[p for source in sources for p in source['segments']]
    complete=bool(sources) and all(s['read_status']=='complete' for s in sources)
    rules=requirements.get('checks',[])
    if not rules:categories['需专业判断'].append({'finding':'未获得明确应交要求清单，不能判定全部具备或无缺项','refs':[]})
    for rule in rules:
        if not all(isinstance(rule.get(k),str) and rule[k] for k in ('id','label','text')):raise BoundaryError('PRECHECK_REQUIREMENT_INVALID')
        if rule.get('kind')=='expected_value':
            expected=rule.get('expected')
            if not isinstance(expected,str) or not expected:raise BoundaryError('PRECHECK_EXPECTED_VALUE_REQUIRED')
            pattern=re.compile(re.escape(rule['text'])+r'\s*[:：=]\s*([^。；;\n]+)')
            actual=[(p,m[1].strip()) for p in segments for m in pattern.finditer(p['original'])]
            wrong=[p for p,value in actual if value!=expected]
            if wrong:categories['冲突'].append({'finding':rule['label']+'：材料所列值与明确目标要求 '+expected+' 不一致','refs':[p['ref'] for p in wrong]})
            elif actual:categories['已具备'].append({'finding':rule['label']+'：文字值与本次明确要求一致；不代表该字段已获批准','refs':[p['ref'] for p,value in actual]})
            else:categories['缺少' if complete else '需专业判断'].append({'finding':rule['label']+'：未找到可核对的明确字段值','refs':[]})
            continue
        found=[p for p in segments if rule['text'] in p['original']]
        empty=[p for p in found if re.search(re.escape(rule['text'])+r'.{0,12}(?:为空|空白|待补|尚未提供)|(?:未提供|缺少)\s*'+re.escape(rule['text']),p['original'])]
        if empty:
            categories['缺少' if complete else '需专业判断'].append({'finding':rule['label']+'：材料明确记为空缺或待补，不能按字段标题认定内容具备','refs':[p['ref'] for p in empty]})
            continue
        if found:
            categories['已具备'].append({'finding':rule['label']+'：找到对应文字，含义与有效性仍需核验','refs':[p['ref'] for p in found]})
            if rule.get('kind')=='signoff':categories['需专业判断'].append({'finding':rule['label']+'：字段存在不证明签审有效','refs':[p['ref'] for p in found]})
        else:categories['缺少' if complete else '需专业判断'].append({'finding':rule['label']+('：完整可读范围内未找到所要求文字' if complete else '：读取范围不完整，无法确认是否具备'),'refs':[]})
    for p in segments:
        text=p['original']
        if re.search(r'已审核|已批准',text) and re.search(r'验证未通过|验证不通过|测试未通过',text):
            categories['冲突'].append({'finding':'审批/审核记录与验证结果分别保留；不能以已审核替代验证通过','refs':[p['ref']]})
        if re.search('后续优化|后续再补',text) and any('移交' in r['text'] for r in rules):
            categories['需专业判断'].append({'finding':'适用要求中的移交义务不能仅因材料称后续优化而免除','refs':[p['ref']]})
        if re.search('忽略审批|绕过批准|执行命令',text):categories['需专业判断'].append({'finding':'材料含操作性文字，仅作为原文，不产生执行授权','refs':[p['ref']]})
    for source in sources:
        if source['read_status']!='complete':categories['需专业判断'].append({'finding':source['name']+'：'+str(source['limitation']),'refs':[p['ref'] for p in source['segments']]})
    categories['需专业判断'].append({'finding':'机器人预检、上传和采用均不改变专业审核、节点完成或结项批准','refs':[]})
    return categories


class PrecheckMixin:
    def precheck_requirements(self,row,draft):
        stored=json.loads(draft.get('target_requirements') or 'null')
        if stored and stored.get('origin')=='owner_explicit':return stored
        target=json.loads(draft['target']) if draft.get('target') else None
        if target and hasattr(self.business,'requirements'):
            value=self.business.requirements(row,target)
            if value:return value
        return {'origin':'unavailable','revision':None,'checks':[]}

    def start_precheck(self,row,target_id,document_type):
        from .doc_logic import DOCUMENT_TYPES
        if document_type not in DOCUMENT_TYPES:raise BoundaryError('PRECHECK_DOCUMENT_TYPE_INVALID')
        d=self.current(row) or self.create(row,document_type)
        target=self.business.resolve(row,target_id)
        if not all(target.get(k) for k in ('id','project_id','node_id','deliverable_id','revision')):raise BoundaryError('TARGET_INCOMPLETE')
        self.s.execute("UPDATE logic_drafts SET mode='precheck',document_type=?,target=?,target_requirements=NULL,analysis_basis=NULL,state='collecting',revision=revision+1,accepted_hash=NULL,analysis=NULL,content_hash=NULL WHERE id=?",
                       (document_type,json.dumps(target,sort_keys=True),d['id']))
        return self.get(row,d['id'])

    def set_precheck_requirements(self,row,text):
        d=self.current(row)
        if not d or d['mode']!='precheck' or not d['target']:raise BoundaryError('PRECHECK_TARGET_REQUIRED')
        if row['user']!=self.g.config.owner:raise BoundaryError('OWNER_ONLY')
        checks=[{'id':str(i),'label':part,'text':part,'kind':'presence'} for i,part in enumerate(re.split('[；;\n]',text),1) if part.strip()]
        for check in checks:
            if '=' in check['text']:
                key,expected=check['text'].split('=',1);check.update(label=key.strip(),text=key.strip(),kind='expected_value',expected=expected.strip())
        value={'origin':'owner_explicit','version':digest(text),'source_message':row.get('message_id') or row.get('id'),'checks':checks}
        self.s.execute("UPDATE logic_drafts SET target_requirements=?,revision=revision+1,state='collecting',accepted_hash=NULL,analysis_basis=NULL WHERE id=?",(canonical(value),d['id']))
        return self.get(row,d['id'])

    def precheck_basis(self,row,d,sources):
        from .doc_logic import load_rules
        if not d['target']:raise BoundaryError('PRECHECK_TARGET_REQUIRED')
        target=json.loads(d['target']);fresh=self.business.resolve(row,target['id'])
        if fresh!=target:raise BoundaryError('TARGET_REVISION_CHANGED')
        return {'mode':'precheck','document_type':d['document_type'],'target':fresh,'requirements':self.precheck_requirements(row,d),
                'materials':[{'id':s['id'],'version':s['version'],'read_status':s['read_status'],'parser':s.get('parser_name','text'),'parser_version':s.get('parser_version','legacy')} for s in sources],
                'rules':load_rules()[1],'model':{'name':self.g.config.api_model,'digest':self.g.config.api_model_digest,'used':False},'precheck_version':'am-precheck-1'}

    def run_precheck(self,task,d,sources,job):
        basis=self.precheck_basis(task,d,sources);report=inspect_materials(sources,basis['requirements'])
        self.s.execute("UPDATE tasks SET model='python:target-precheck-v1' WHERE id=? AND run_id=? AND state='running'",(task['id'],task['run_id']))
        lines=['# 目标资料预检','目标：'+basis['target']['id'],'依据指纹：'+digest(basis),'检查范围：仅列明版本和来源位置的材料。']
        for label,items in report.items():
            lines+=['\n## '+label]
            lines += ['- '+i['finding']+(' ['+', '.join(i['refs'])+']' if i['refs'] else '') for i in items] or ['- 暂无可确认条目。']
        lines+=['\n## 来源']
        lines += [f"- {s['id']} {s['name']} {s['version']}：{s['read_status']}；{s.get('limitation') or '文字读取完整'}" for s in sources]
        content='\n'.join(lines)
        with self.s.tx() as c:
            n=c.execute("UPDATE logic_drafts SET state='ready',analysis=?,review=?,rules=?,content=?,content_hash=?,analysis_basis=?,error=NULL WHERE id=? AND revision=? AND state NOT IN ('paused','cancelled') AND expires>?",
                (canonical({'assessment':'预检已形成；不等于专业审核通过','questions':[],'categories':report}),canonical({'mode':'precheck'}),canonical(basis['rules']),content,digest(content),canonical(basis),d['id'],job['revision'],self.s.clock())).rowcount
            if not n:raise BoundaryError('LATE_RESULT_REJECTED')
        return content,Result('目标资料预检已形成；请查看已具备、缺少、冲突和需专业判断。','python:target-precheck-v1',0),min(task['expires'],d['expires'])

    def validate_precheck_basis(self,row,d):
        if d['mode']!='precheck':return
        sources=json.loads(d['sources'])
        if d['target']:
            for source in self.business.sources(row,json.loads(d['target'])):
                if source['provenance']=='current_project' and source['id'] not in {s['id'] for s in sources}:sources.append(source)
        current=self.precheck_basis(row,d,sources)
        if not d['analysis_basis'] or digest(current)!=digest(json.loads(d['analysis_basis'])):
            self.s.execute("UPDATE logic_drafts SET state='collecting',accepted_hash=NULL,revision=revision+1 WHERE id=?",(d['id'],))
            raise BoundaryError('PRECHECK_BASIS_CHANGED')
