import {randomUUID} from 'node:crypto';
import {demoSnapshot} from './fixture.mjs';
import {applyReviewDecision,applyReminderDisplayAction,organizeCandidates} from '../core/index.mjs';
import {digest} from '../server/canonical.mjs';
import {LedgerError} from '../server/errors.mjs';

/** Explicit synthetic-only adapter. It contains no network/Feishu client or scheduler. */
export class DemoBridge {
  constructor({clock=Date.now}={}){this.clock=clock;this.snapshot=demoSnapshot(clock());this.previews=new Map();this.presentations=new Map();this.receipts=new Map();this.calls=[];}
  async call(method,params,session,{requestId=randomUUID()}={}) {
    this.calls.push({method,requestId});
    if(method==='snapshot')return structuredClone(this.snapshot);
    if(method==='status')return this.receipts.get(params.requestId)||{requestId:params.requestId,state:'not_found',messageId:null};
    if(method==='review') {
      const out=applyReviewDecision(this.snapshot,{reviewId:params.reviewId,choiceId:params.choiceId,expectedBasis:params.reviewHash,
        requestId,actorId:session.userId,now:new Date(this.clock()).toISOString()});
      this.snapshot=out.snapshot;return out.receipt.result;
    }
    if(method==='reminder') {
      const out=applyReminderDisplayAction(this.snapshot,{reminderId:params.reminderId,action:params.action==='ack'?'read':'snooze',
        expectedBasis:params.basis,requestId,actorId:session.userId,until:params.untilMs?new Date(params.untilMs).toISOString():undefined,
        now:new Date(this.clock()).toISOString()});this.snapshot=out.snapshot;return out.receipt.result;
    }
    if(method==='prepare'||method==='revise') {
      const item=this.snapshot.items.find(i=>i.id===params.itemId);
      if(!item||item.version!==params.expectedItemVersion||item.semanticVersion!==params.expectedSemanticVersion)
        throw new LedgerError('item_changed','原事项已经变化，请重新核对。',409);
      if(item.id==='demo-rollout')return {kind:'wait',recommendation:'按原发布窗口等待即可。',
        reason:'已有明确安排，当前没有需要补问的新变化。',nextCheckAt:item.dueAt};
      if(method==='revise') {
        const old=this.previews.get(params.previousPreviewId);
        if(!old||old.sessionId!==session.id)throw new LedgerError('preview_not_found','原预览不可用。',409);
        old.superseded=true;
      }
      const channel=params.channel||'group';
      const outside=item.projectId==='demo-outside';
      const target=channel==='group'?{channel,id:outside?'demo-template-group':'demo-test-group',
        name:outside?'模板协同群 · 示例':'验证协作群 · 示例',
        attention:[{id:item.assignees[0],name:outside?'模板协调人 · 示例':'测试负责人 · 示例'}]}
        :{channel,id:params.recipientId||item.assignees[0],name:'责任人 · 示例',attention:[]};
      const body=params.body||(outside?'想确认一下尚未收齐的模板修改意见，是否会影响差异清单的汇总时间？请同步剩余意见及预计提供时间。'
        :'想确认一下当前台架档期和开测安排，是否会影响对比试验节点？如有变化，请同步新的安排。');
      const previewId='demo-preview-'+randomUUID();
      const preview={previewId,contentHash:digest({body,target}),displayHash:digest({body,target,previewId}),version:1,
        expiresAtMs:this.clock()+300000,itemId:item.id,projectId:item.projectId,target,body,count:1,
        sendWindow:{notBeforeMs:this.clock(),expiresAtMs:this.clock()+300000,immediate:true},
        followup:'核对回执并等待反馈',dependenciesHash:digest({id:item.id,version:item.version,semanticVersion:item.semanticVersion})};
      this.previews.set(previewId,{preview,sessionId:session.id});return preview;
    }
    if(method==='present') {
      const record=this.previews.get(params.previewId);
      if(!record||record.superseded||record.sessionId!==session.id||record.preview.displayHash!==params.displayHash)
        throw new LedgerError('preview_changed','预览已变化，请重新展示。',409);
      const presentationId='demo-presentation-'+randomUUID();
      const presentation={presentationId,expiresAtMs:record.preview.expiresAtMs};
      this.presentations.set(presentationId,{...presentation,previewId:params.previewId,sessionId:session.id});return presentation;
    }
    if(method==='approve') {
      const prior=this.receipts.get(params.requestId);if(prior)return prior;
      const record=this.previews.get(params.previewId),presentation=this.presentations.get(params.presentationId);
      if(!record||record.superseded||record.sessionId!==session.id||record.preview.displayHash!==params.displayHash||
        !presentation||presentation.sessionId!==session.id||presentation.previewId!==params.previewId||presentation.expiresAtMs<=this.clock())
        throw new LedgerError('approval_stale','当前展示已失效，请重新核对。',409);
      const item=this.snapshot.items.find(i=>i.id===record.preview.itemId);
      if(!item||record.preview.dependenciesHash!==digest({id:item.id,version:item.version,semanticVersion:item.semanticVersion}))
        throw new LedgerError('item_changed','原事项已变化，请重新核对。',409);
      if(record.approvedRequestId)return this.receipts.get(record.approvedRequestId);
      const receipt={requestId:params.requestId,intentId:'demo-intent-'+randomUUID(),occurrenceId:'demo-occurrence-'+randomUUID(),
        state:'queued',messageId:null,readbackState:'not_sent',reason:'演示确认已记录；此示例没有连接真实发送。'};
      record.approvedRequestId=params.requestId;this.receipts.set(params.requestId,receipt);return receipt;
    }
    throw new LedgerError('unsupported_method','示例未实现此操作。',422);
  }
  async peek(){throw new LedgerError('unknown_request','示例没有待处理的远端请求。',404);}
  ingest(candidates,requestId='demo-ingest-'+randomUUID()) {
    const out=organizeCandidates(this.snapshot,candidates,{requestId,now:new Date(this.clock()).toISOString()});
    this.snapshot=out.snapshot;return out;
  }
}
