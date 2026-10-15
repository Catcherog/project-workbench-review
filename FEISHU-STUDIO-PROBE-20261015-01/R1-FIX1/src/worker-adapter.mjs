import fs from 'node:fs/promises';
import {join,resolve,relative,isAbsolute} from 'node:path';
import {runCodex,validateCompletion} from './codex.mjs';

/** Executor configuration is supplied by the controller, never by message/model fields. */
export function createWorkerAdapter({binary,prefixArgs=[],executionKind='offline-fixture',jobsRoot,model='gpt-6-astra',effort='max',timeoutMs=180000,onEvidence}={}){
 const root=resolve(jobsRoot);
 return async input=>{
  if(input.signal?.aborted)throw Error('CANCELLED_BEFORE_START');
  const job=resolve(input.jobDir),rel=relative(root,job);if(!rel||rel.startsWith('..')||isAbsolute(rel))throw Error('JOB_OUTSIDE_CONTROLLER_ROOT');
  await fs.mkdir(job,{recursive:true,mode:0o700});
  const realRoot=await fs.realpath(root),realJob=await fs.realpath(job),realRel=relative(realRoot,realJob);
  if(!realRel||realRel.startsWith('..')||isAbsolute(realRel))throw Error('JOB_SYMLINK_ESCAPE');
  const fixture={marker:input.marker,label:'合成测试',samples:[{planned:8,done:5},{planned:6,done:2}],history:input.history.slice(-8)};
  await fs.writeFile(join(job,'synthetic.json'),JSON.stringify(fixture),{mode:0o600,flag:'wx'});
  const prompt='只读取 synthetic.json，计算样本计划和完成总数。返回 marker/summary/missing/question 四字段；summary 标注合成测试，missing 必须为空数组，question 必须为空。不得选定消息收件人、身份、权限或其他路径。';
  let response;
  try{response=await runCodex({binary,prefixArgs,jobDir:job,prompt,marker:input.marker,model,effort,timeoutMs,signal:input.signal,executionKind});}
  catch(e){if(e.evidence)onEvidence?.(e.evidence);throw e;}
  validateCompletion(response,input.marker);
  if(input.signal?.aborted)throw Error('CANCELLED_AFTER_COMPLETION');
  onEvidence?.(response.evidence);
  if(response.result.missing.length||response.result.question)throw Error('UNEXPECTED_CLARIFICATION_FOR_SINGLE_PROBE');
  return {marker:response.result.marker,summary:response.result.summary};
 };
}
