const obj=properties=>({type:'object',properties,required:Object.keys(properties),additionalProperties:false}),str={type:'string'},bool={type:'boolean'},strings={type:'array',items:str};
// Shared citation IDs avoid asking the model to repeat the same paragraph in
// every duration, sharing, dependency, coordination and recipient proof.
const proof={type:'array',items:str},nullable=s=>({anyOf:[s,{type:'null'}]});
export const dependencyWindowSchema=obj({
  dependency:obj({id:str,upstreamId:str,downstreamId:str,input:str,affectedWork:str,impact:str,proof,resolved:bool}),
  readStatus:{type:'string',enum:['verified','partial','failed']},planConfirmed:bool,planProof:proof,
  duration:nullable(obj({min:{type:'number'},max:{type:'number'},unit:{type:'string',enum:['hours']},remaining:bool,includesPreparation:bool,includesRetest:bool,conditions:str,proof})),sharedProof:proof,
  availableHours:nullable({type:'number'}),windowProof:proof,calendarSource:str,coordination:{type:'string',enum:['not-tried','possible','impossible']},coordinationProof:proof,knownByAffected:bool,awarenessProof:proof,arrangementDecided:bool,closingWindow:bool,closingProof:proof,
  options:{type:'array',items:obj({title:str,impact:str,preconditions:str,proof})},
});
export const deliveryContextSchema=obj({targetId:str,nodeId:str,ownerId:str,providerId:str,fileOwnerId:str,teamOwnerId:str,verified:bool,proof,requirement:str,requirementConflict:bool,exceptionProof:proof,templates:{type:'array',items:obj({sourceId:str,title:str,applicable:bool,reason:str})},templateUncertain:bool,materialSourceIds:strings,missing:strings,accessDenied:bool,linked:bool,submitted:bool,reviewValue:str,ownerCannotIdentifyProvider:bool,providerLookupProof:proof,responsibilityDisputed:bool});
export const coreWorkSchema=obj({dependencies:{type:'array',maxItems:4,items:dependencyWindowSchema},deliveries:{type:'array',maxItems:4,items:obj({workItemId:str,context:deliveryContextSchema})},messages:{type:'array',maxItems:8,items:obj({workItemId:str,targetId:str,nodeId:str,recipientId:str,channel:{type:'string',enum:['private','group']},purpose:str,text:str,proof})}});
export const coreWorkInstructions=`\n只有本轮确实涉及真实依赖、时间挤压、交付资料或协作消息准备时才填写coreWork，其他情况数组均为空。messages只准备有当前实际必要性的完整正文、真实接收范围及来源；不同报告分别一条。普通资料优先private；确需群体知晓才group，群ID必须来自已核实范围，未知留空并说明。只准备不发送。不得为凑齐字段猜测。dependencies只关联context.coreInput.items内不同目标的稳定ID；实际输入、被阻塞工作和评审影响须逐项有原文证据，不按同名/同负责人/项目推导依赖。时长和剩余可用时间直接取本轮可靠出处，不机械减去已过时间；范围存在与sharedProof分别给出，未读到共享依据留空。knownByAffected专指风险影响和协调失败已被实际受影响人明确知晓；时长范围已共享、消息已发送、已读或待发送，均不能代替。awarenessProof只引用明确已知晓风险影响的原话，没有就knownByAffected=false。单位统一小时，有效时间计算口径calendarSource必须来自证据。引用源已失败/部分时readStatus如实填写，不判负责人未提供。已确认无法协调就不再提重复调人方案；候选方案列影响和前提，用户选择，不主观排序。\n交付资料准备只选context.coreInput.deliverables和nodes的真实ID。报告由ownerId本人编写、关联并推动审核；资料提供人明确则直接准备请求，不明确先询问报告责任人。只有报告责任人明确反馈仍不知道提供方并有providerLookupProof时，ownerCannotIdentifyProvider=true，再按已知teamOwnerId继续简单核实；真实职责争议responsibilityDisputed=true，交本人协调，不自行裁决。冲突无可靠例外交用户；权限受限只准备向所有者申请。绝不代关联、代审核或修改共享。linked和reviewValue最终由平台按实际对象字段核验，模型推测不生效。templates可用实际已读取的模板来源及library引用ID，保留适用理由；缺模板如实列missing，不能生成正式报告替代责任人。材料和消息只是准备，第三方完整预览后才执行。所有proof或以Proof结尾的数组只填本轮已经列入citations的citationId，复用同一引文，不在这里重复抄写原文。原始citations仍逐字引用并由平台校验；不能引用AI历史回答。\n`;
export function attachProofFingerprints(value,state,domain,citations=[],field=''){
  if(Array.isArray(value)){
    if(/proof$/i.test(field)&&value.some(v=>typeof v==='string'))return value.map(id=>{
      const c=citations.find(c=>c.citationId===id),source=c&&state.sources.find(r=>r.id===c.sourceId&&!r.workItem);
      if(!c||!source)throw Object.assign(Error('风险或协作引用未在本轮原件中核验'),{status:422});
      return {sourceId:source.id,fingerprint:domain.coreProofFingerprint(source),quote:c.locator.kind==='image'?c.interpretation:c.quote,kind:c.locator.kind==='image'?'image':'text',attachmentId:c.locator.attachmentId||'',locator:c.locator};
    });
    return value.map(v=>attachProofFingerprints(v,state,domain,citations,field));
  }
  if(!value||typeof value!=='object')return value;
  const result=Object.fromEntries(Object.entries(value).map(([k,v])=>[k,attachProofFingerprints(v,state,domain,citations,k)]));
  if(typeof value.sourceId==='string'&&typeof value.quote==='string'){const source=state.sources.find(r=>r.id===value.sourceId);result.fingerprint=source?domain.coreProofFingerprint(source):'';}
  return result;
}
