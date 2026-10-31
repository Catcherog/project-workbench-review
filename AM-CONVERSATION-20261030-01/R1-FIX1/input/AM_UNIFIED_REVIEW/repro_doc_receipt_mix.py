import copy,json,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from _bootstrap import bootstrap
root=bootstrap()
studio=root/'FS-AGENT-GROK-POC-20261017-01_R1_Studio'
from fs_agent.store import Store
from fs_agent.document_native import NativePublisher
from fs_agent.document_mapping import blueprint
from am_doc_engine.models import fingerprint,SourceAsset
import ast
test_ast=ast.parse((studio/'tests/test_document_standards.py').read_text())
fixtures=[node for node in test_ast.body if isinstance(node,ast.FunctionDef) and node.name in ('fixture_native','profile_and_slots')]
exec(compile(ast.Module(body=fixtures,type_ignores=[]),'original_test_fixtures','exec'))
from am_conversation.documents import DocumentTools

class Cloud:
    def __init__(self,native):
        self.docs={native['token']:copy.deepcopy(native)}
        self.copies=0
        self.fail_readback=False
    def check(self): return True
    def restrict_copy(self,token): pass
    def read(self,token): return copy.deepcopy(self.docs[token])
    def call(self,method,path,*,body=None,query=None):
        if method=='POST':
            self.copies+=1
            token='copy'+str(self.copies)
            old_token=path.split('/')[-2]
            source=copy.deepcopy(self.docs[old_token])
            mapping={b['block_id']:token+'-'+str(i) for i,b in enumerate(source['blocks'])}
            def remap(v):
                if isinstance(v,dict):return {k:remap(x) for k,x in v.items()}
                if isinstance(v,list):return [remap(x) for x in v]
                return mapping.get(v,v) if isinstance(v,str) else v
            source['blocks']=remap(source['blocks'])
            source['paths']={mapping[k]:v for k,v in source['paths'].items()}
            source.update(token=token,title=body['name'])
            source['blocks'][0]['page']['elements'][0]['text_run']['content']=body['name']
            source['hash']=fingerprint(source['blocks'])
            self.docs[token]=source
            return {'file':{'token':token}}
        if method=='PATCH':
            token=path.split('/')[-3]
            native=self.docs[token]
            by={b['block_id']:b for b in native['blocks']}
            for r in body['requests']:
                by[r['block_id']]['text']['elements']=r['update_text_elements']['elements']
            if self.fail_readback:
                by[body['requests'][0]['block_id']]['text']['elements'].append({'text_run':{'content':' readback mismatch'}})
            native['revision']+=1
            native['hash']=fingerprint(native['blocks'])
            return {}
        raise AssertionError((method,path))

with tempfile.TemporaryDirectory() as td:
    s=Store(Path(td)/'test.sqlite3')
    native=fixture_native();cloud=Cloud(native)
    pub=NativePublisher(s,cloud,folder='folder',host='example.com')
    _,slots=profile_and_slots()
    document={'fields':[{'field_id':x['field_id'],'text':'value '+str(i)} for i,x in enumerate(slots)],'issues':[],'template_hash':'same-template'}
    draft={'id':'draft','revision':1,'content_hash':'hash1','accepted_hash':'hash1','state':'ready','expires':time.time()+120}
    first=pub.save(draft,document,native,slots)
    assert first['state']=='verified'
    cloud.fail_readback=True
    latest={}
    def native_action(row,d,command):
        latest.update(pub.save(d,document,native,slots,selected_fields=[slots[0]['field_id']],revalidate=lambda b,h,c,sel:c))
        assert latest['state']=='unknown' and latest['receipt'] is None
        return '云文档结果待确认，请先执行 /doc 云文档对账。'
    tools=DocumentTools.__new__(DocumentTools)
    tools.s=s
    tools.logic=SimpleNamespace(standards=SimpleNamespace(native_action=native_action))
    tools.b=SimpleNamespace(store=SimpleNamespace(get_action=lambda ctx,key:{'preview':'exact preview'}))
    tools.publish_preview=lambda ctx,args:'exact preview'
    tools.get=lambda ctx,ident:({},draft)
    result=tools.publish(None,{'draft_id':'draft','operation':'update_cloud','sections':[slots[0]['field_id']]},'action2')
    assert latest['idempotency_key']!=first['idempotency_key']
    assert result['status']=='succeeded' and result['receipt_id']==first['receipt']['url']
    print(json.dumps({'first_idem':first['idempotency_key'],'current_idem':latest['idempotency_key'],'current_publisher_state':latest['state'],'adapter_result':result,'write_states':s.rows('SELECT revision,state,token FROM amdoc_native_writes')},ensure_ascii=False,indent=2))
    s.close()
