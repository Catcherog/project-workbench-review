import {isDeepStrictEqual} from 'node:util';

const fail=(message,status)=>Object.assign(new Error(message),{status});

/** Read only a persisted preparation reference, never a caller-supplied path or title. */
export function readCoreMaterial({assistant,workspaceId,sourceId,jobId,materialId}){
  const state=assistant.store.load(workspaceId);
  let materials;
  if(jobId){
    const job=assistant.get(jobId,workspaceId);
    if(job.restored||state.workspaceType==='restored')throw fail('恢复记录中的资源库引用仅供历史核对，请重新准备资料',409);
    materials=job.coreWorkOutcome?.summaries?.find(row=>row.sourceId===sourceId)?.delivery?.materials;
  }else{
    const owner=state.sources.find(row=>row.id===sourceId&&!row.archived);
    if(!owner||state.workspaceType==='restored')throw fail('原事项已不存在或仅为恢复的历史记录',409);
    materials=owner.workItem?.core?.delivery?.materials;
  }
  const matches=(materials||[]).filter(row=>row.id===materialId);
  if(matches.length!==1)throw fail('原资料引用不存在或身份不唯一，请重新核对准备结果',404);
  const material=matches[0],reference=material.library,locator=material.locator;
  if(!material.id.startsWith('library:')||!reference||!locator)throw fail('资源库引用缺少原身份或定位信息，请重新准备资料',409);
  const library=assistant.retrieval.library;
  if(!library)throw fail('资源库读取能力当前不可用，尚未读取资料',503);
  const snapshot=library.snapshot();
  if(!snapshot.available)throw fail('资源库目录当前不可读，尚未取得正文；请核对目录与读取权限',503);
  const doc=snapshot.documents.find(row=>row.id===material.id);
  if(!doc||!isDeepStrictEqual(reference,doc.library))throw fail('资源库引用已失效、版本已变化或当前不可读；请核对原资料与读取权限',409);
  const original=library.citation({sourceId:doc.id,fingerprint:doc.fingerprint,locator});
  if(!original)throw fail('资源库原定位已失效，尚未读取资料',409);
  return {workspaceId,sourceId,jobId:jobId||'',materialId,library:doc.library,locator,
    original:{title:doc.title,version:doc.version,text:doc.text,excerpt:original.text},limitations:doc.limitations};
}
