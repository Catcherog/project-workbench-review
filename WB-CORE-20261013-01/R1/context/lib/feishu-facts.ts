import {stableHash,type Item} from './domain';
import type {V2State} from './v2-types';
import type {ExternalObject,SyncBaseline} from './mapping-registry';
import type {FeishuRead,FeishuSyncConflict} from './feishu-sync';

const own=(o:object,key:string)=>Object.prototype.hasOwnProperty.call(o,key);
const same=(a:unknown,b:unknown)=>JSON.stringify(a??null)===JSON.stringify(b??null);
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
function label(value:unknown,metadata:Item|undefined) {
  const options=metadata?.option||metadata?.options;
  const id=object(value)?value.value??value.key??value.id:value;
  if(Array.isArray(options)&&options.length){
    const found=options.find((o:Item)=>String(o.option_id??o.id??o.key)===String(id));
    if(found)return String(found.option_name??found.name??found.label??'');
    if(object(value))return '';
  }
  return typeof value==='string'?value:object(value)?String(value.label??value.name??''):'';
}
export function observedDeliveryReview(row:Item):string {
  const fact=row.feishuFacts?.deliveryReview;
  return fact?fact.state==='mapped'?fact.value:'待映射':row.deliveryReview||row.reviewStatus||'未审核';
}
export function deliveryRecorded(row:Item):boolean{return row.submissionStatus!=='免交付'&&observedDeliveryReview(row)==='已审核';}

/** Adopt read-only remote facts. This never approves a risk, writes remotely, or
 * turns a field value into a separate manager acceptance decision. */
export function adoptFeishuFacts(s:V2State,local:Item,remote:ExternalObject,read:FeishuRead,baseline:SyncBaseline):FeishuSyncConflict[]{
  if(['quarantined','unmapped'].includes(remote.mappingStatus))return [];
  const pairs=remote.remoteKind==='deliverable'?[['field_b462b3','deliveryReview'],['work_item_status','status']]:remote.remoteKind==='node'?[['status','nodeStatus']]:[];
  const conflicts:FeishuSyncConflict[]=[],changes:{field:string;before:unknown;after:string}[]=[];
  for(const [key,field] of pairs){
    if(!own(read.fields,key)){
      const declared=Array.isArray(read.fieldMetadata)&&read.fieldMetadata.some(r=>object(r)&&(r.key||r.field_key)===key);
      if(declared&&!local.feishuFacts?.[field])local.feishuFacts={...(local.feishuFacts||{}),[field]:{state:'unread',value:'',raw:null,externalObjectId:remote.id,fieldKey:key,readAt:read.collectedAt,reason:'本次未返回该字段，不推断其默认值'}};
      continue;
    }
    const existing=s.mappingRules.find(r=>r.system==='meegle'&&r.remoteKind===remote.remoteKind&&r.remoteFieldKey===key);
    if(existing&&(existing.status!=='active'||existing.localField&&existing.localField!==field))continue;
    if(!existing)s.mappingRules.push({id:'mapping-fact-'+stableHash(remote.remoteKind+':'+key),workspaceId:s.workspaceId,system:'meegle',remoteKind:remote.remoteKind,remoteFieldKey:key,remoteFieldName:field==='nodeStatus'?'节点状态':field,remoteValueType:'option',localKind:remote.remoteKind==='node'?'flowNodes':'deliverables',localField:field,conversionRule:'option_label',writable:false,requiresReview:false,bidirectional:false,status:'active'});
    const raw=read.fields[key];
    const metadata=Array.isArray(read.fieldMetadata)?read.fieldMetadata.find(r=>object(r)&&(r.key||r.field_key)===key):read.fieldMetadata?.[key];
    const display=label(raw,metadata as Item|undefined);
    const value=field==='deliveryReview'?(['已审核','未审核'].includes(display)?display:'')
      :field==='status'?(['未开始','进行中','已结束'].includes(display)?display:'')
      :({finished:'已完成',completed:'已完成',done:'已完成',started:'进行中',doing:'进行中',in_progress:'进行中',pending:'待开始',waiting:'待开始',not_started:'待开始','已完成':'已完成','进行中':'进行中','未开始':'待开始','待开始':'待开始'} as Record<string,string>)[display]||'';
    const prior=local.feishuFacts?.[field];
    const pending=s.changeGroups.some(g=>['pending','partial','conflict'].includes(g.status)&&g.operations.some(op=>op.targetId===local.id&&(!op.status||op.status==='pending')&&own(op.after,field)));
    const baselineLocal=baseline.localValues[field],edited=own(baseline.localValues,field)&&!same(local[field],baselineLocal);
    const imported=local.importedFrom?.readonly===true||local.importedFrom?.system==='feishu';
    const conflict=!!value&&(pending||edited||!own(baseline.localValues,field)&&!!local[field]&&!imported);
    const state=!value?'unmapped':conflict?'conflict':'mapped';
    const fact={state,value:value||'',raw,externalObjectId:remote.id,fieldKey:key,readAt:read.collectedAt};
    if(!prior||!same([prior.state,prior.value,prior.raw],[state,fact.value,raw])){
      local.feishuFacts={...(local.feishuFacts||{}),[field]:fact};
      if(prior&&!same([prior.state,prior.value],[state,fact.value]))changes.push({field,before:prior.value,after:fact.value||'当前选项待映射'});
    }
    if(conflict){conflicts.push({id:'feishu-fact-conflict-'+remote.id+'-'+key,externalObjectId:remote.id,localObjectId:local.id,remoteFieldKey:key,localField:field,reason:pending?'该事实字段有本地待审修改，保留差异':'该事实字段存在本地独立修改，保留差异',baselineLocal,baselineRemote:baseline.remoteValues[key],localValue:local[field],remoteValue:raw});continue;}
    if(!value)continue;
    local[field]=value;
    if(field==='deliveryReview')local.reviewStatus=value;
    baseline.localValues[field]=value;baseline.remoteValues[key]=raw;
  }
  if(changes.length&&s.workspaceType!=='restored'){
    const id='feishu-fact-event-'+stableHash(remote.id),old=s.sources.find(src=>src.id===id);
    const excerpt=JSON.stringify({title:local.title,kind:remote.remoteKind,changes,rule:'这是飞书读取事实。已审核为工程师交付标记，不需要经理内容验收。只有当前确需本人行动时列待办。'});
    const event={id,title:'飞书事实变化 · '+local.title,projectIds:[...local.projectIds],objectIds:[local.id],sourceIds:[remote.sourceId].filter(Boolean),type:'业务动态',excerpt,version:(old?.version||0)+1,createdAt:old?.createdAt||read.collectedAt,updatedAt:read.collectedAt,collectedAt:read.collectedAt,occurredAt:read.collectedAt,confirmed:false,riskEvent:{kind:'feishu-fact-change',externalObjectId:remote.id},history:old?[...(old.history||[]),{at:old.updatedAt,excerpt:old.excerpt}].slice(-30):[]};
    if(old)Object.assign(old,event);else s.sources.push(event);
  }
  return conflicts;
}
