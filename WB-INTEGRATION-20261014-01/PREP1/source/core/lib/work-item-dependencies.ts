import type {Item} from './domain';
import type {V2State} from './v2-types';
import {coreDigest,validCoreProofs,ensureCore,type CoreProof} from './work-item-core';
export type VerifiedDependency={id:string;upstreamId:string;downstreamId:string;input:string;affectedWork:string;impact:string;proof:CoreProof[];resolved:boolean};
export type DurationEvidence={min:number;max:number;unit:'hours';remaining:boolean;includesPreparation:boolean;includesRetest:boolean;conditions:string;proof:CoreProof[]};
export type DependencyWindow={
  dependency:VerifiedDependency;readStatus:'verified'|'partial'|'failed';planConfirmed:boolean;planProof:CoreProof[];
  duration:DurationEvidence|null;sharedProof:CoreProof[];
  availableHours:number|null;windowProof:CoreProof[];calendarSource:string;
  coordination:'not-tried'|'possible'|'impossible';coordinationProof:CoreProof[];
  knownByAffected:boolean;awarenessProof:CoreProof[];arrangementDecided:boolean;
  closingWindow:boolean;closingProof:CoreProof[];
  options:{title:string;impact:string;preconditions:string;proof:CoreProof[]}[];
};
/** Sharing a duration range or sending a message does not establish awareness
 * of the actual review impact. Require an explicit acknowledged-impact claim. */
function impactAwareness(proofs:CoreProof[]){
  return proofs.some(proof=>{
    const clauses=proof.quote.split(/[。；\n]/);
    return clauses.some((clause,i)=>{
      const text=clause+'；'+(clauses[i+1]||'');
      if(/(?:尚未|未|待|应该|需要|请|希望|可能|如果).{0,10}(?:知晓|知悉|了解|确认收到)/.test(text))return false;
      return /(?:影响|缺口|阻塞).{0,100}(?:已知晓|知晓并|知悉|确认收到|明确了解)|(?:已知晓|已知悉|已明确了解|确认收到).{0,100}(?:影响|缺口|阻塞)/.test(text)||/acknowledged.{0,80}(?:impact|gap|blocker)|(?:impact|gap|blocker).{0,80}acknowledged/i.test(text);
    });
  });
}
export function evaluateDependency(s:V2State,w:DependencyWindow){
  const gaps:string[]=[],edge=w.dependency;
  const answer=(status:string,intervene:boolean,reason:string,extra:Record<string,unknown>={})=>({status,intervene,reason,gaps,dependencyId:edge?.id,...extra});
  if(!edge||!edge.id||!edge.input||!edge.affectedWork||!edge.impact||edge.upstreamId===edge.downstreamId||!s.sources.some(r=>r.id===edge.upstreamId&&r.workItem)||!s.sources.some(r=>r.id===edge.downstreamId&&r.workItem)||!validCoreProofs(s,edge.proof))return answer('unverified',false,'真实依赖尚未核实；相同项目、标题或责任人不能证明依赖');
  if(w.readStatus!=='verified')return answer('unverified',false,'本次尚未完整核实；不能认定负责人未提供或未共享');
  if(edge.resolved)return answer('unblocked',false,'共同阻塞已解除；下游按自身剩余动作继续');
  const duration=w.duration,rangeValid=!!duration&&Number.isFinite(duration.min)&&Number.isFinite(duration.max)&&duration.min>=0&&duration.max>=duration.min&&duration.unit==='hours'&&!!duration.conditions&&validCoreProofs(s,duration.proof);
  const shared=validCoreProofs(s,w.sharedProof),plan=w.planConfirmed&&validCoreProofs(s,w.planProof);
  if(!rangeValid)gaps.push('最短与最长预计时长尚未核实');
  if(!shared)gaps.push('尚无时长范围已共享的有效依据');
  if(plan&&gaps.length)return answer('needs-range',true,'关键测试计划已确认，请推动明确并共享时长范围',{rangeExists:rangeValid,shared});
  const windowValid=Number.isFinite(w.availableHours)&&w.availableHours!==null&&w.availableHours>=0&&!!w.calendarSource&&validCoreProofs(s,w.windowProof);
  if(!windowValid)gaps.push('当前有效可用时间及日历口径尚未核实');
  const windowClosing=w.closingWindow&&validCoreProofs(s,w.closingProof);
  if(!rangeValid||!windowValid||!duration!.remaining)return answer(windowClosing?'closing-window':'needs-evidence',windowClosing,windowClosing?'有依据的行动窗口正在关闭，请及时介入；缺口仍需核实':'补查当前剩余必要时长及时间口径；不机械扣减最初估计');
  if(duration!.min>w.availableHours!){
    const impossible=w.coordination==='impossible'&&validCoreProofs(s,w.coordinationProof),known=w.knownByAffected&&validCoreProofs(s,w.awarenessProof)&&impactAwareness(w.awarenessProof);
    if(w.knownByAffected&&!known)gaps.push('时长范围共享或消息已发送，不能替代风险影响已被相关人明确知晓的依据');
    const options=(w.options||[]).filter(o=>o.title&&o.impact&&o.preconditions&&validCoreProofs(s,o.proof));
    return answer(impossible?known&&!w.arrangementDecided?'leader-decision':'share-impact':'coordinate',true,impossible?known&&!w.arrangementDecided?'影响已知晓，安排尚未明确；由本人找领导推动决定':'已核实协调不能消除缺口，准备向受影响人员共享事实':'当前剩余最短必要时长超过可用时间，需要本人协调资源',{
      gapHours:duration!.min-w.availableHours!,brief:{blocker:edge.affectedWork,coordination:w.coordination==='impossible'?'已核实协调不能消除缺口':w.coordination==='possible'?'仍有可核实的协调空间':'尚未进行资源协调',impact:edge.impact,context:edge.input,window:'剩余最短必要时长 '+duration!.min+' 小时；可用 '+w.availableHours+' 小时；缺口 '+Number((duration!.min-w.availableHours!).toFixed(6))+' 小时',conditions:duration!.conditions},options,
    });
  }
  return answer(windowClosing?'closing-window':'observe',windowClosing,windowClosing?'其他有效证据显示行动窗口正在关闭，需及时介入':'仍存在按时完成可能，持续关注实际过程；尚未全部通过',{rangeExists:true,shared,availableHours:w.availableHours});
}

/** Links are evidence-backed and stored on the same target item. */
export function saveDependencyWindow(s:V2State,row:Item,w:DependencyWindow,at:string){
  if(w.dependency.downstreamId!==row.id)throw Object.assign(Error('依赖目标与事项不一致'),{status:422});
  const result=evaluateDependency(s,w),c=ensureCore(row);
  c.dependencies||=[];const prior=c.dependencies.findIndex((x:Item)=>x.window.dependency.id===w.dependency.id);
  const value={id:w.dependency.id,window:structuredClone(w),result,at,fingerprint:coreDigest(w)};
  if(prior<0)c.dependencies.push(value);else c.dependencies[prior]=value;
  if(result.intervene){
    const key='dependency:'+w.dependency.id+':'+result.status;
    if(c.need.key!==key){c.history.push({at,kind:'dependency-need',previous:structuredClone(c.cycle),reason:result.reason});c.cycle={id:coreDigest([row.id,key,w]),needKey:key,count:0,epoch:c.cycle.epoch+1,escalated:false,temp:null,notices:[]};}
    c.need={key,actor:'self',description:result.reason,arranged:false,remainingActions:[result.reason],at};
    c.dependencyUrgent=result.status==='closing-window';
  }else if(['unblocked','observe'].includes(result.status)&&c.need.key.startsWith('dependency:'+w.dependency.id+':')){
    c.need={...c.need,arranged:true,actor:'none',description:result.reason};c.cycle.temp=null;c.dependencyUrgent=false;
  }
  c.history.push({at,kind:'dependency-evaluated',dependencyId:w.dependency.id,status:result.status});
  return result;
}
export function recheckKnownDependencies(s:V2State,changedIds:string[],at:string){
  const affected:string[]=[];
  for(const row of s.sources.filter(r=>r.workItem&&!r.archived)){
    const c=row.workItem.core;if(!c?.dependencies)continue;
    for(const d of c.dependencies){
      const edge=d.window.dependency;
      const serialized=JSON.stringify(d.window);
      if(!changedIds.some(id=>edge.upstreamId===id||edge.downstreamId===id||serialized.includes(JSON.stringify(id))))continue;
      // A closed upstream item is not itself proof that every dependency resolved.
      const result=evaluateDependency(s,d.window);
      d.result=result;d.at=at;c.checks={...c.checks,needsRecheck:true,reason:'相关依赖依据发生变化'};
      c.history.push({at,kind:'dependency-recheck',dependencyId:edge.id,status:result.status});
      if(!affected.includes(row.id))affected.push(row.id);
    }
  }
  return affected;
}
