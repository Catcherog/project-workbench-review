import {meetingError as fail} from './meeting-materials.mjs';

/**
 * Boundary for the coordinator's existing Meegle executor and mapping registry.
 * No guessed CLI node binding, no node-subtask fallback, no removal of TH2 guards.
 * Port methods return normalized read-back, never only a success boolean.
 */
export class MeetingDeliverableAdapter {
  constructor({port,simulation=false}){this.port=port;this.simulation=simulation;}
  async inspect(context){
    if(!this.port?.inspectMeetingTarget)throw fail('尚未接入 Meegle 类型、字段、模板及节点元数据核对',503);
    const target=await this.port.inspectMeetingTarget(context);
    if(!target?.verified||!target.metadataFingerprint||!target.templateId||!target.projectRemoteId||!target.mainNodeRemoteId||target.remoteKind!=='film'||target.documentField!=='field_d06ce2'||target.relation!=='node_sub_workitems')throw fail('须核对 film、交付物文档字段、创建模板及主节点子工作项关系',409);
    for(const nodeId of context.intent.referenceNodeIds)if(!target.referenceNodeRemoteIds?.[nodeId])throw fail('引用节点缺少真实ID映射：'+nodeId,409);
    // Unknown space classification is protected by default.
    return {...target,protectedSpace:target.protectedSpace!==false};
  }
  assertTarget(target){if(!this.simulation&&target.protectedSpace!==false)throw fail('TH2 写入保护仍启用，请由总控走既有受控路径',403,{definiteFailure:true});}
  async create(input){this.assertTarget(input.target);return this.call('createMeetingFilm',{...input,fieldKey:input.target.documentField,templateId:input.target.templateId,projectRemoteId:input.target.projectRemoteId},'交付物创建执行器尚未接线');}
  async update(input){this.assertTarget(input.target);return this.call('updateMeetingFilmDocument',{...input,fieldKey:input.target.documentField},'纪要文档更新执行器尚未接线');}
  get(input){return this.call('readMeetingFilm',input,'交付物保存回读尚未接线');}
  async attachMain(input){
    this.assertTarget(input.target);
    if(await this.hasMain(input))return {alreadyBound:true,remoteId:input.remoteId,nodeId:input.nodeId};
    return this.call('attachMeetingMainNode',input,`交付物 ${input.remoteId} 已创建；请在主节点“子工作项→添加现有”挂接该ID后续办。当前CLI不能证明节点绑定，不能改用“全部任务”。`);
  }
  async hasMain(input){const row=await this.call('readMeetingNode',input,'主节点子工作项回读尚未接线');return row.nodeId===input.nodeId&&row.subWorkitemIds?.includes(input.remoteId)===true;}
  async reference(input){
    this.assertTarget(input.target);
    if(await this.hasReference(input))return {alreadyReferenced:true,remoteId:input.remoteId,nodeId:input.nodeId};
    return this.call('referenceMeetingFilm',input,'其他节点的同一纪要引用需受控接线，不能重复创建交付物');
  }
  async hasReference(input){const row=await this.call('readMeetingReference',input,'引用节点回读尚未接线');return row.nodeId===input.nodeId&&row.deliverableId===input.remoteId&&row.verified===true;}
  reconcile(input){return this.call('reconcileMeetingWrite',input,'外部执行结果未知；需保留原请求ID并回读核对');}
  call(method,input,message){if(!this.port?.[method])throw fail(message,503,{definiteFailure:true});return this.port[method](input);}
}
