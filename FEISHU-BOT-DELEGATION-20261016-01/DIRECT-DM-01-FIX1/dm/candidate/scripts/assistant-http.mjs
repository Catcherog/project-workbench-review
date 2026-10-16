import {listWorkItemRequests,applyWorkItemRequest} from './work-item-assistant.mjs';
import { assistantError } from './assistant-sessions.mjs';
import { evidenceCurrent } from './source-retrieval-service.mjs';

/** Mount only AFTER the existing local token/origin + uiOnly checks.
 * No body/path field here grants permission or executes an external command. */
export async function assistantRoute({ assistant, method, pathname, workspaceId, body = {}, searchParams = new URLSearchParams() }) {
  const prefix = '/api/v2/codex/';
  if (!pathname.startsWith(prefix)) return null;
  if(pathname===prefix+'monitor-agent'){
    if(!assistant.monitorAgent)throw assistantError('Codex 资料分析 agent 尚未接线',503);
    if(method==='GET')return assistant.monitorAgent.status(workspaceId);
    if(method==='POST'&&body.action==='analyse')return assistant.monitorAgent.start({workspaceId,requestId:body.requestId});
    if(method==='POST'&&body.action==='cancel')return assistant.monitorAgent.cancel({workspaceId,jobId:body.jobId});
    throw assistantError('不支持的资料分析操作',405);
  }
  const submitted=pathname.match(/^\/api\/v2\/codex\/requests\/([A-Za-z0-9_.:-]+)$/);
  if(submitted&&method==='GET'){assistant.store.load(workspaceId);const row=assistant.store.db.prepare('SELECT payload FROM assistant_jobs WHERE workspace_id=? AND request_id=?').get(workspaceId,submitted[1]);return {job:row?assistant.decorate(JSON.parse(row.payload)):null};}
  const workItems=pathname.match(/^\/api\/v2\/codex\/jobs\/([A-Za-z0-9_.:-]+)\/work-items(?:\/(\d+)\/apply)?$/);
  if(workItems){
    if(method==='GET'&&!workItems[2])return listWorkItemRequests(assistant,workspaceId,workItems[1]);
    if(method==='POST'&&workItems[2])return applyWorkItemRequest(assistant,{workspaceId,jobId:workItems[1],index:Number(workItems[2]),draft:body.draft});
    throw assistantError('不支持的事项整理请求',405);
  }
  const people=pathname.match(/^\/api\/v2\/codex\/jobs\/([A-Za-z0-9_.:-]+)\/actions\/people$/);
  if(people&&method==='POST'){
    if(!assistant.actions)throw assistantError('人员查询接线尚未启用',503);
    return assistant.actions.resolvePerson({...body,workspaceId,jobId:people[1]});
  }
  const actions=pathname.match(/^\/api\/v2\/codex\/jobs\/([A-Za-z0-9_.:-]+)\/actions(?:\/(\d+)\/(prepare|execute|reconcile))?$/);
  if(actions){
    if(!assistant.actions)throw assistantError('任务与会议操作接线尚未启用',503);
    if(method==='GET'&&!actions[2])return assistant.actions.list({workspaceId,jobId:actions[1]});
    if(method==='POST'&&actions[2])return assistant.actions[actions[3]]({...body,workspaceId,jobId:actions[1],index:Number(actions[2])});
    throw assistantError('不支持的助手操作请求',405);
  }
  if (method === 'GET' && pathname === prefix + 'sessions') return { sessions: assistant.sessions.list(workspaceId) };
  const session = pathname.match(/^\/api\/v2\/codex\/sessions\/([A-Za-z0-9_.:-]+)$/);
  if (method === 'GET' && session) return assistant.conversation(workspaceId, session[1]);
  const evidence = pathname.match(/^\/api\/v2\/codex\/jobs\/([A-Za-z0-9_.:-]+)\/evidence$/);
  if (method === 'GET' && evidence) return assistant.get(evidence[1], workspaceId).evidencePacket || { citations: [], gaps: ['旧任务没有可回查的引用记录'] };
  const citation = pathname.match(/^\/api\/v2\/codex\/jobs\/([A-Za-z0-9_.:-]+)\/citation$/);
  if (method === 'GET' && citation) {
    const job = assistant.get(citation[1], workspaceId), proof = job.citations?.find(c => c.citationId === searchParams.get('id'));
    if (!proof) throw assistantError('没有这条引用', 404);
    if (job.restored || !evidenceCurrent(assistant.store.load(workspaceId), proof, assistant.domain, assistant.retrieval.library)) throw assistantError('引用已更正或撤回，请重新提问', 409);
    // Snapshot quote + exact locator, verified against the current content fingerprint.
    const original=proof.library?assistant.retrieval.library.citation(proof):undefined;
    if(proof.library&&!original)throw assistantError('引用已更正或撤回，请重新提问',409);
    return { citation: proof, ...(original?{original}:{}) };
  }
  const preview = pathname.match(/^\/api\/v2\/codex\/jobs\/([A-Za-z0-9_.:-]+)\/review-preview$/);
  if (method === 'POST' && preview) {
    const job = assistant.get(preview[1], body.workspaceId), state = assistant.store.load(body.workspaceId);
    const group = state.changeGroups.find(g => g.id === job.groupId);
    if (!group) throw assistantError('预览已失效或不在本次恢复范围，请重新准备', 409);
    if (['accepted', 'rejected', 'withdrawn'].includes(group.status)) return {groupId:group.id,preview:{...job.preview,availability:'historical',requiresReview:false}};
    if (!job.preview || job.preview.availability !== 'current') throw assistantError('预览已失效或不在本次恢复范围，请重新准备', 409);
    if (['pending', 'partial', 'conflict'].includes(group.status) && assistant.domain.validateDraft(state, group).length) throw assistantError('拟变更对象或依据已有变化，预览已失效，请重新准备', 409);
    return { groupId: job.groupId, preview: job.preview };
  }
  return null;
}
