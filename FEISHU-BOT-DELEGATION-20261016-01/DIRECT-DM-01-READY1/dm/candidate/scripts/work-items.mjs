import {repairRiskRouting} from './risk-routing-repair.mjs';
/** Uses the existing source store and audit/backup path. All mutations are local. */
export class WorkItems {
  constructor({store,domain,clock=()=>new Date().toISOString()}){Object.assign(this,{store,domain,clock});this.pending=new Set();this.closed=false;}
  status(id){const state=this.store.load(id);const statistics=this.domain.workbenchStatistics(state);return {items:statistics.items.total,statistics,...(this.store.getSetting('workItemError:'+id)||{error:''})};}
  reconcile(workspaceId,historical=false){
    if(this.closed)return;
    this.store.transaction(()=>{
      const before=this.store.load(workspaceId);if(before.workspaceType==='restored')return;
      const next=structuredClone(before);
      const policyChanged=this.domain.adoptRiskPolicy(next,this.clock());
      const legacyChanged=this.domain.connectLegacyWorkItems(next,this.clock(),{historical});
      const followupChanged=this.domain.reconcileBusinessFollowups(next,this.clock());
      const coreChanged=this.domain.reconcileCoreLocals(next,this.clock());
      const routingChanged=repairRiskRouting(next,this.store.getSetting('agentMonitor:'+workspaceId)?.advice,this.domain,this.clock());
      const identity=this.store.getSetting('agentMonitor:'+workspaceId)?.identity;let identityChanged=false;
      if(identity?.scope&&identity.userId)for(const source of next.sources)if(source.riskEvent&&!source.riskEvent.scope&&['business-followup','verification-proposal','feishu-fact-change'].includes(source.riskEvent.kind)){source.riskEvent={...source.riskEvent,scope:identity.scope,accountId:identity.userId};identityChanged=true;}
      if(!legacyChanged&&!policyChanged&&!followupChanged&&!coreChanged&&!identityChanged&&!routingChanged){this.store.setSetting('workItemError:'+workspaceId,{error:''});return;}
      next.revision++;const errors=this.domain.validateState(next);if(errors.length)throw Error(errors.map(e=>e.message).join('；'));
      this.store.save(next,before.revision);
      this.store.setSetting('workItemError:'+workspaceId,{error:''});
    });
  }
  start(){
    for(const workspace of this.store.list())try{this.reconcile(workspace.id,true);}catch(error){this.store.setSetting('workItemError:'+workspace.id,{at:this.clock(),error:error.message});}
    this.unsubscribe=this.store.subscribe(id=>{if(this.pending.has(id)||this.closed)return;this.pending.add(id);queueMicrotask(()=>{this.pending.delete(id);if(this.closed)return;try{this.reconcile(id);}catch(error){this.store.setSetting('workItemError:'+id,{at:this.clock(),error:error.message});}});});
  }
  operate(input){return this.store.transaction(()=>{
    const before=this.store.load(input.workspaceId),next=this.domain.applyWorkItemOperation(before,input,this.clock());
    const errors=this.domain.validateState(next);if(errors.length)throw Object.assign(Error(errors.map(e=>e.message).join('；')),{status:422});
    if(next!==before)this.store.save(next,before.revision);return {state:this.store.load(input.workspaceId),...(next.receipts['work-item:'+input.requestId]?.result||{})};
  });}
  close(){this.closed=true;this.unsubscribe?.();}
}
