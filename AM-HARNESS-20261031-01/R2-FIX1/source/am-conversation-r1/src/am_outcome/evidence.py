"""One immutable evidence contract consumed by query and document paths."""
from dataclasses import dataclass
from .types import encode, fingerprint

@dataclass(frozen=True)
class EvidenceBundle:
    serialized: str
    @property
    def data(self):
        import json
        return json.loads(self.serialized)
    @classmethod
    def build(cls, project, *, scope, expires, information=None):
        ident=project.get('id',project.get('key'));fields=project.get('fields') or {k:project[k] for k in ('关键日期','待办','项目进展','人员与职责') if k in project}
        source=project.get('snapshot') or {'version':project.get('source_revision'),'observed_at':project.get('_sync_observed_at') or project.get('observed_at')}
        claims=[]
        for key,value in fields.items():
            claims.append({'id':fingerprint([ident,key,source,value])[:24], 'subject':ident,'predicate':key,'value':value,
                'modality':'recorded','business_state':'reported','source':dict(source,source_id='th2-ledger',object_id=ident,locator=key),
                'expression':'quote','observed_at':project.get('observed_at')})
        info=information if information is not None else project.get('information',{})
        for fact in info.get('facts',[]):
            if 'value' not in fact:continue
            claims.append({'id':fact['fact_id'],'subject':fact.get('subject_id',ident),'predicate':fact['field'],'value':fact['value'],
                'modality':fact.get('assertion_type','unknown'),'business_state':fact.get('business_state','unconfirmed'),
                'source':fact.get('evidence',{}),'expression':'quote'})
        content={'schema_version':'am-evidence/1','project_id':ident,'project_title':project.get('title'),
                 'claims':claims,'coverage':info.get('coverage',{}),'gaps':info.get('gaps',[])}
        return cls(encode(dict(content,bundle_id=fingerprint(content),scope=list(scope),expires=expires)))

    def document_source(self, *, uri, legacy_project_id=None):
        d=self.data
        return {'id':'shared-evidence','uri':uri,'version':d['bundle_id'],'read_status':'partial' if any(d['coverage'].get(k) for k in ('processing_pending','needs_refresh_or_review','stale')) else 'complete',
                'provenance':'current_project','project_id':d['project_id'],
                'legacy_project_id':legacy_project_id,'evidence_bundle_id':d['bundle_id'],
                'segments':[{'id':c['id'],'original':str(c['predicate'])+'：'+(c['value'] if isinstance(c['value'],str) else encode(c['value'])),
                    'source':c['source'],'modality':c['modality'],'business_state':c['business_state']} for c in d['claims']],
                'coverage':d['coverage'],'gaps':d['gaps']}
