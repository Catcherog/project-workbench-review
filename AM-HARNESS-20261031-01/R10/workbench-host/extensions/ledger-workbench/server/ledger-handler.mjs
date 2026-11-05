import {randomUUID} from 'node:crypto';
import {ProjectionCache} from './projection-cache.mjs';
import {LedgerError,publicError} from './errors.mjs';
import {sanitizeEvidence} from './evidence-retention.mjs';

const PREFIX='/api/v2/ledger';
const WRITE_SCOPES={
  '/am/prepare':'am:prepare','/am/revise':'am:prepare','/am/present':'am:prepare','/am/approve':'am:approve',
  '/reviews/resolve':'review:resolve','/reminders/ack':'reminder:manage','/reminders/snooze':'reminder:manage',
};
const REQUEST_ID=/^[A-Za-z0-9_-]{8,96}$/;
const TEXT_LIMIT=4000;

function response(res,status,value) {
  res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
  res.end(JSON.stringify(sanitizeEvidence(value)));
}
async function readBody(req) {
  if(!/^application\/json(?:;|$)/i.test(req.headers['content-type']||''))throw new LedgerError('json_required','请使用 JSON 提交。',415);
  let size=0;const chunks=[];
  for await(const chunk of req){size+=chunk.length;if(size>65536)throw new LedgerError('body_too_large','本次内容过长，请缩小范围。',413);chunks.push(chunk);}
  let body;try{body=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw new LedgerError('invalid_json','提交内容格式不正确。',422);}
  if(!body || typeof body!=='object' || Array.isArray(body))throw new LedgerError('invalid_body','提交内容格式不正确。',422);
  for(const protectedKey of ['session','userId','tenantId','actorId','scopes','projectIds','signature']) {
    if(Object.hasOwn(body,protectedKey))throw new LedgerError('untrusted_identity','身份与范围由当前会话提供。',422);
  }
  return body;
}
function requiredString(value,name,limit=256) {
  if(typeof value!=='string'||!value.trim()||value.length>limit)throw new LedgerError('invalid_'+name,'请核对 '+name+'。',422);
  return value;
}
function requestId(body) {
  if(!REQUEST_ID.test(body.requestId||''))throw new LedgerError('request_id_required','本次操作缺少有效请求标识。',422);
  return body.requestId;
}
function requireSession(session,now) {
  if(!session || !session.verified || !Number.isSafeInteger(session.expiresAtMs) || session.expiresAtMs<=now)
    throw new LedgerError('authentication_required','请通过当前工作台登录后继续。',401);
  for(const field of ['id','userId','tenantId','workspaceId'])requiredString(session[field],field);
  if(!Array.isArray(session.scopes)||!Array.isArray(session.projectIds))throw new LedgerError('scope_required','当前会话缺少授权范围。',403);
  if(!session.scopes.includes('ledger:read'))throw new LedgerError('scope_required','当前会话不能读取项目台账。',403);
}
function currentProject(entry,projectId) {
  const project=entry.snapshot.projects.find(p=>p.id===projectId);
  if(!project)throw new LedgerError('project_not_available','当前范围中没有这个项目或事项。',404);
  return project;
}
function actionableItems(entry,projectId) {
  return entry.snapshot.items.filter(i=>i.projectId===projectId&&!['closed','paused','cancelled'].includes(i.businessState)
    &&Number.isSafeInteger(i.version)&&Number.isSafeInteger(i.semanticVersion));
}
function previewResponse(preview,context) {
  if(['wait','choose_route'].includes(preview?.kind))return preview;
  return {kind:'action',recommendation:context.recommendation,reason:context.reason,
    itemId:context.itemId,expectedItemVersion:context.expectedItemVersion,
    expectedSemanticVersion:context.expectedSemanticVersion,preview};
}

/** Mount inside the original WB HTTP server AFTER its authenticated session boundary.
 * Both callbacks are mandatory; no browser-supplied identity is trusted.
 */
export function createLedgerHandler({bridge,getSession,authorizeMutation,clock=Date.now,cacheTtlMs=10000}) {
  if(!bridge || typeof getSession!=='function' || typeof authorizeMutation!=='function')
    throw new Error('bridge, verified host getSession and authorizeMutation callbacks are required');
  const cache=new ProjectionCache(bridge,{clock,ttlMs:cacheTtlMs});

  async function completePending(outcome,session) {
    const context=outcome.context||{};
    if(context.route==='bootstrap'||context.route==='project') {
      const entry=cache.accept(outcome.data,session,context);
      if(context.route==='bootstrap')return entry.bootstrap;
      currentProject(entry,context.projectId);return entry.summaryCache.get(context.projectId).summary;
    }
    if(context.route==='am-preview')return previewResponse(outcome.data,context);
    if(context.route==='internal-read'){cache.accept(outcome.data,session,context);return {state:'source_ready'};}
    if(context.mutates)cache.invalidate(session);
    return outcome.data;
  }

  const handler=async(req,res)=>{
    let url;
    try{url=new URL(req.url,'http://ledger.internal');}catch{return false;}
    if(url.pathname!==PREFIX&&!url.pathname.startsWith(PREFIX+'/'))return false;
    try{
      const session=await getSession(req);requireSession(session,clock());
      const path=url.pathname.slice(PREFIX.length);
      if(req.method==='GET') {
        if(path==='/bootstrap') {
          const entry=await cache.get(session,{context:{route:'bootstrap'}});response(res,200,entry.bootstrap);return true;
        }
        if(path.startsWith('/projects/')) {
          const projectId=decodeURIComponent(path.slice('/projects/'.length));
          const entry=await cache.get(session,{context:{route:'project',projectId}});
          currentProject(entry,projectId);response(res,200,entry.summaryCache.get(projectId).summary);return true;
        }
        if(path.startsWith('/operations/')) {
          const id=path.slice('/operations/'.length),outcome=await bridge.peek(id,session);
          if(outcome.state!=='complete') {response(res,202,{state:'pending',requestId:id,expired:outcome.expired,pollUrl:PREFIX+path});return true;}
          response(res,200,await completePending(outcome,session));return true;
        }
        if(path.startsWith('/am/receipts/')) {
          const id=path.slice('/am/receipts/'.length);
          if(!REQUEST_ID.test(id))throw new LedgerError('invalid_request_id','请求标识无效。',422);
          const receipt=await bridge.call('status',{requestId:id},session,{context:{route:'passthrough'}});
          response(res,200,receipt);return true;
        }
        throw new LedgerError('not_found','没有找到这个接口。',404);
      }
      if(req.method!=='POST')throw new LedgerError('method_not_allowed','此接口不支持该请求方式。',405);
      const needed=WRITE_SCOPES[path];
      if(!needed)throw new LedgerError('not_found','没有找到这个接口。',404);
      if(!session.scopes.includes(needed))throw new LedgerError('scope_required','当前会话不能执行该操作。',403);
      await authorizeMutation(req,session);
      const body=await readBody(req),id=requestId(body);
      if(body.workspaceId && body.workspaceId!==session.workspaceId)throw new LedgerError('workspace_mismatch','工作区已经变化，请刷新。',409);

      if(path==='/am/prepare'||path==='/am/revise') {
        const projectId=requiredString(body.projectId,'projectId');
        const entry=await cache.get(session,{fresh:true,allowStale:false,context:{route:'internal-read'}});
        const project=currentProject(entry,projectId),items=actionableItems(entry,projectId);
        if(['paused','closed'].includes(project.status)||!items.length) {
          response(res,200,{kind:'wait',recommendation:project.status==='paused'?'项目已暂停，按恢复安排再跟进。':'当前没有可直接执行的跟进动作。',
            reason:!items.length?'台账信息已保留；尚无具备原事项身份和有效版本的跟进对象。':'保留现有计划与检查安排。'});return true;
        }
        if(!body.itemId && items.length>1) {
          response(res,200,{kind:'choose',recommendation:'请选择本次需要跟进的事项。',reason:'这些事项有各自的跟进对象与依据。',items:items.map(i=>({id:i.id,title:i.title}))});return true;
        }
        const item=items.find(i=>i.id===(body.itemId||items[0].id));
        if(!item)throw new LedgerError('item_not_actionable','原事项当前不能发起这项跟进，请刷新核对。',409);
        if(body.expectedItemVersion!==undefined && body.expectedItemVersion!==item.version ||
           body.expectedSemanticVersion!==undefined && body.expectedSemanticVersion!==item.semanticVersion)
          throw new LedgerError('item_changed','项目事项已有变化，请重新生成建议。',409);
        if(body.body!==undefined)requiredString(body.body,'body',TEXT_LIMIT);
        const params={itemId:item.id,expectedItemVersion:item.version,expectedSemanticVersion:item.semanticVersion,purpose:'request_progress'};
        for(const key of ['channel','recipientId','body','previousPreviewId'])if(body[key]!==undefined)params[key]=body[key];
        if(params.channel&&!['group','recipient_p2p'].includes(params.channel))throw new LedgerError('invalid_channel','请选择已核实的跟进渠道。',422);
        if(path==='/am/revise')requiredString(params.previousPreviewId,'previousPreviewId');
        const context={route:'am-preview',itemId:item.id,projectId,expectedItemVersion:item.version,expectedSemanticVersion:item.semanticVersion,
          recommendation:'建议核实「'+item.title+'」的当前进度和下一步安排。',reason:'以当前事项和已有来源为依据；确认下方具体对象与正文后执行。'};
        const preview=await bridge.call(path.endsWith('revise')?'revise':'prepare',params,session,{requestId:id,context});
        response(res,200,previewResponse(preview,context));return true;
      }
      if(path==='/am/present'||path==='/am/approve') {
        const params={previewId:requiredString(body.previewId,'previewId'),displayHash:requiredString(body.displayHash,'displayHash')};
        if(path.endsWith('approve')){params.presentationId=requiredString(body.presentationId,'presentationId');params.requestId=id;}
        const result=await bridge.call(path.endsWith('approve')?'approve':'present',params,session,{requestId:id,
          context:{route:'passthrough',mutates:path.endsWith('approve')}});
        if(path.endsWith('approve'))cache.invalidate(session);
        response(res,200,result);return true;
      }
      if(path==='/reviews/resolve') {
        const entry=await cache.get(session,{fresh:true,allowStale:false,context:{route:'internal-read'}});
        const review=entry.snapshot.reviews.find(r=>r.id===body.reviewId&&r.status==='pending');
        if(!review)throw new LedgerError('review_not_available','该疑点已经变化或处理，请刷新。',409);
        if(review.basis!==body.expectedBasis)throw new LedgerError('review_changed','该疑点的来源已变化，请查看新内容。',409);
        const choice=review.choices.find(c=>c.id===body.choiceId);
        if(!choice)throw new LedgerError('invalid_review_choice','请选择当前列出的判断。',422);
        const result=await bridge.call('review',{reviewId:review.id,reviewHash:review.basis,choiceId:choice.id,choice:choice.value,
          evidence:review.evidence,factIds:review.factIds||[],projectId:review.projectId,requestId:id},session,
          {requestId:id,context:{route:'passthrough',mutates:true}});
        cache.invalidate(session);response(res,200,result);return true;
      }
      if(path==='/reminders/ack'||path==='/reminders/snooze') {
        const entry=await cache.get(session,{fresh:true,allowStale:false,context:{route:'internal-read'}});
        const reminder=entry.snapshot.reminders.find(r=>r.id===body.reminderId);
        if(!reminder)throw new LedgerError('reminder_not_available','当前没有这条提醒，请刷新。',409);
        const basis=body.expectedBasis??body.basis;
        if(basis!==reminder.basis)throw new LedgerError('reminder_changed','事项已有新变化，请先查看更新。',409);
        const params={reminderId:reminder.id,basis:reminder.basis,action:path.endsWith('ack')?'ack':'snooze',requestId:id};
        if(params.action==='snooze') {
          const until=typeof body.until==='string'?Date.parse(body.until):body.untilMs;
          if(!Number.isSafeInteger(until)||until<=clock()||until>clock()+7*86400000)throw new LedgerError('invalid_snooze','请选择未来七天内的提醒时间。',422);
          params.untilMs=until;
        }
        const result=await bridge.call('reminder',params,session,{requestId:id,context:{route:'passthrough',mutates:true}});
        cache.invalidate(session);response(res,200,result);return true;
      }
    }catch(error){
      if(error.code==='rpc_pending')response(res,202,{state:'pending',...error.details});
      else response(res,error.status||500,{error:publicError(error)});
      return true;
    }
    return true;
  };
  handler.invalidate=session=>cache.invalidate(session);
  return handler;
}
