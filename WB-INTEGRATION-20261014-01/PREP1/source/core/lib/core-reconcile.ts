import type {Item} from './domain';
import type {V2State} from './v2-types';
import {validCoreProofs,invalidateCoreDerivations} from './work-item-core';
import {evaluateDependency,saveDependencyWindow} from './work-item-dependencies';
import {prepareDeliveryCollaboration} from './work-item-collaboration';
/** Local invalidation is always active; it neither calls a model nor sends messages. */
export function reconcileCoreLocals(s:V2State,at:string){
  if(s.workspaceType==='restored')return false;
  let changed=false;
  for(const row of s.sources.filter(r=>r.workItem?.core&&!r.archived)){
    const c=row.workItem.core,before=JSON.stringify(c);
    if(c.assessment&&!validCoreProofs(s,c.assessment.proof))invalidateCoreDerivations(s,row,at,'当前引用已纠正或撤回');
    if(c.delivery?.context){
      const value=prepareDeliveryCollaboration(s,row,c.delivery.context),prior=Object.fromEntries(Object.entries(c.delivery).filter(([key])=>!['context','at'].includes(key)));
      // Library template references have their own reader; preserve them as references.
      value.materials.push(...(c.delivery.materials||[]).filter((m:Item)=>m.library));
      if(JSON.stringify(value)!==JSON.stringify(prior))c.delivery={...value,context:c.delivery.context,at};
    }
    for(const dependency of [...(c.dependencies||[])]){const result=evaluateDependency(s,dependency.window);if(JSON.stringify(result)!==JSON.stringify(dependency.result)){saveDependencyWindow(s,row,dependency.window,at);c.checks={...c.checks,needsRecheck:true,reason:'已核实依赖的依据发生变化'};}}
    if(JSON.stringify(c)!==before){row.version++;row.updatedAt=at;changed=true;}
  }
  for(const source of s.sources.filter(r=>r.reminderRun?.core&&!r.archived)){
    let updated=false;
    for(const m of source.reminderRun.items){
      if(['sending','unknown','sent','readback_verified','cancelled','stopped'].includes(m.stage))continue;
      const row=s.sources.find(r=>r.id===m.workItemId&&r.workItem&&!r.archived),c=row?.workItem.core;
      if(!row)continue; // Unread is not proof that a message is unnecessary.
      const done=c?.delivery?.targetId===m.targetId&&c.delivery.delivered&&validCoreProofs(s,c.delivery.proof)||row.workItem.p1?.lifecycle?.state==='closed'&&c?.assessment?.goalSatisfied&&validCoreProofs(s,c.assessment.proof);
      const stale=!validCoreProofs(s,m.proof);
      const stage=done?'stopped':stale||row.workItem.p1?.lifecycle?.state==='closed'?'needs_preview':m.stage;
      if(stage===m.stage)continue;
      m.stage=stage;m.events.push({at,kind:stage,reason:done?'可靠新事实已使本条协作无必要':'相关原文已变化，保留原批准并重新完整预览'});updated=true;
    }
    if(updated){source.reminderRun.messages=structuredClone(source.reminderRun.items);source.version++;source.updatedAt=at;changed=true;}
  }
  return changed;
}
