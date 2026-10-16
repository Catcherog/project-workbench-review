import {createHash} from 'node:crypto';
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const day=ms=>new Date(ms+8*3600000).toISOString().slice(0,10);
export function projectReal(outputs,{aliases,allowedPersonIds,runId,readAt,totalItems,unregisteredItems,failedItems,missingDetailItems=0}){
  // Aliasing is not authorization. The current preview is limited to the
  // explicitly approved test actor; other people's hours must not leak into it.
  if(!Array.isArray(allowedPersonIds)||!allowedPersonIds.length)throw Error('display_scope_required');
  if(outputs.some(out=>out.cells.some(c=>!allowedPersonIds.includes(c.person.id))))throw Error('person_outside_display_scope');
  const rows=[];
  for(const out of outputs){
    for(const c of out.cells){
      const person=aliases[c.person.id];if(!person)throw Error('missing_person_alias');
      const h=c.hours==null?null:Number(c.hours);
      if(h!==null&&(!Number.isFinite(h)||h<0||h>Number.MAX_SAFE_INTEGER||String(h)!==c.hours))throw Error('unsafe_hours');
      const partial=out.coverageGaps.length>0||out.pending.length>0||failedItems>0;
      const sourceRows=c.rows.map(r=>({key:r.key,version:r.version,hours:r.hours,start:r.startInclusive,end:r.endExclusive,registrationDerived:r.registrationDerived===true}));
      const hasUnknownOwnership=c.rows.some(r=>!r.ownership.label);
      rows.push({'汇总键':`real|${person.id}|${out.mode}|${c.period.key}`,'数据集':'real','记录类型':'aggregate',
        '人员':person.name,'人员键':person.id,'口径':'actual','周期类型':out.mode,'周期':c.period.label,
        '周期开始':day(c.period.startInclusive),'周期结束不含':day(c.period.endExclusive),'实际小时':h,
        '来源行数':c.rows.length,'非项目事项数':hasUnknownOwnership?null:c.nonProjectItemCount,
        '来源事项数':totalItems,'待登记事项数':unregisteredItems,
        '范围说明':'真实需求体验副本的已覆盖来源小计；不代表全部投入；校验样本不参与本数值',
        '覆盖缺口':`待登记或核对${unregisteredItems}项（其中明细未返回${missingDetailItems}项）；读取失败${failedItems}项；待分配${out.pending.length}行；异常${out.errors.length}项`,
        '来源摘要':`来自本批真实需求体验副本的${c.rows.length}行登记；${hasUnknownOwnership?'项目归属尚未完整核实；':''}无手填登记标识时使用原生行标识对账`,
        '来源版本':hash(sourceRows.map(r=>[r.key,r.version])),'来源指纹':hash(sourceRows),
        '读取时间':readAt,'更新时间':new Date().toISOString(),'运行标识':runId,
        '刷新结果':h===null?'pending':partial?'success_partial':'success'});
    }
  }
  rows.push({'汇总键':'real|scope','数据集':'real','记录类型':'scope','人员':null,'人员键':null,'口径':'actual','周期类型':'scope','周期':null,
    '周期开始':null,'周期结束不含':null,'实际小时':null,'来源行数':outputs[0].rowsRead,
    '非项目事项数':null,'来源事项数':totalItems,'待登记事项数':unregisteredItems,
    '范围说明':'仅覆盖本批真实需求体验副本；未登记不代表零投入；校验样本单独展示',
    '覆盖缺口':`明细未返回${missingDetailItems}项；读取失败${failedItems}项；明细需核对${outputs[0].errors.length}处；周/月待确认${outputs[0].pending.length}/${outputs[1].pending.length}行。不包含本轮43条已完成原任务历史；缺少明细不能解释为零投入。`,
    '来源摘要':`当前范围${totalItems}项；${unregisteredItems}项待登记或核对。${missingDetailItems?'当前接口未返回这些事项的实际明细；未使用累计字段的0代替实际投入。':''}工程师在飞书测试事项登记一次，由执行端手动读取更新。`,
    '来源版本':null,'来源指纹':hash(outputs[0].sourceStatuses.map(x=>[x.sourceId,x.status])),
    '读取时间':readAt,'更新时间':new Date().toISOString(),'运行标识':runId,
    '刷新结果':failedItems||outputs[0].errors.length||outputs[0].pending.length?'success_partial':outputs[0].rowsRead===0?'success_no_records':'success_partial'});
  return rows;
}
