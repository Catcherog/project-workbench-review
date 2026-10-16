import {resolveMeegleCli} from './cli-runtime.mjs';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {MeegleSyncAdapter} from './feishu-sync-cli.mjs';
import {analyseFeedbackWithCodex} from './feedback-ai.mjs';
import {FeishuTaskClient} from './feishu-task-client.mjs';

const root=fileURLToPath(new URL('..',import.meta.url));
const fail=(message,status=422)=>Object.assign(new Error(message),{status});
const now=()=>new Date().toISOString();
export class FeedbackIntake {
  constructor({store,domain,materialIntake,adapter,taskClient=new FeishuTaskClient(),analyse=analyseFeedbackWithCodex,intervalMs=300000,clock=now,scopeFile=path.join(root,'output/workbench-reconstruction-20260928/confirmed-intake-scope.json')}={}){
    Object.assign(this,{store,domain,materialIntake,adapter,taskClient,analyse,intervalMs,clock});this.jobs=new Map();this.analysisRuns=new Map();this.closed=false;
    const scope=JSON.parse(readFileSync(scopeFile,'utf8'));
    if(scope.scopeStatus!=='confirmed_by_user'||scope.historyBackfill!==false||scope.collectFrom!==domain.feedbackCollectFrom)throw Error('评论采集范围与已确认记录不一致');
    this.collectFrom=scope.collectFrom;
  }
  key(id){return 'feedbackIntake:'+id;}
  control(id){this.store.load(id);return this.store.getSetting(this.key(id))||{enabled:false,projectIds:[],collectFrom:this.collectFrom,phase:'idle',processed:0,total:0,lastCompletedAt:'',lastError:'',issues:[],newSources:0,historical:0,unchanged:0,nextReadAt:''};}
  save(id,c){this.store.setSetting(this.key(id),c);return c;}
  status(id){const s=this.store.load(id),c=this.control(id),sources=s.sources.filter(this.domain.isCommentFeedback),objects=this.objects(s,c.projectIds);return {...c,running:this.jobs.has(id),analysing:this.analysisRuns.has(id),counts:{sources:sources.length,pending:sources.filter(s=>s.feedback.analysis.status==='pending').length,failed:sources.filter(s=>s.feedback.analysis.status==='failed').length,ready:sources.filter(s=>s.feedback.analysis.status==='ready').length},scopeCount:objects.length,taskCount:objects.filter(o=>o.system==='feishu_tasks').length,deliverableCount:objects.filter(o=>o.system==='meegle').length};}
  configure(id,{enabled,projectIds}){
    const s=this.store.load(id);if(typeof enabled!=='boolean'||!Array.isArray(projectIds)||!projectIds.length||projectIds.length>100||new Set(projectIds).size!==projectIds.length||projectIds.some(pid=>!s.projects.some(p=>p.id===pid&&!p.archived)))throw fail('请选择当前工作区内的有效项目，可多选');
    if(enabled&&s.workspaceType==='restored')throw fail('恢复工作区的采集保持暂停，请在正式工作区配置');
    const c=this.control(id),changed=JSON.stringify([...c.projectIds].sort())!==JSON.stringify([...new Set(projectIds)].sort());
    if(this.jobs.has(id)&&changed)throw fail('正在读取，请等待本次完成后调整项目范围',409);
    this.save(id,{...c,enabled,projectIds:[...new Set(projectIds)],collectFrom:this.collectFrom,nextReadAt:enabled?this.clock():'',...(enabled?{consecutiveFailures:0,lastError:''}:{})});
    if(!enabled)this.jobs.get(id)?.controller.abort();
    if(enabled)void this.poll(id).catch(()=>{});return this.status(id);
  }
  objects(s,projectIds){return [...s.externalObjects.filter(r=>r.workspaceId===s.workspaceId&&r.system==='meegle'&&r.host==='project.feishu.cn'&&r.remoteKind==='deliverable'&&r.verificationStatus==='verified'&&!['quarantined','unmapped','conflict'].includes(r.mappingStatus)&&s.deliverables.some(d=>d.id===r.localObjectId&&!d.archived&&d.projectIds.some(pid=>projectIds.includes(pid)))),...this.domain.taskFeedbackLinks(s,projectIds)];}
  client(){if(!this.adapter){this.adapter=new MeegleSyncAdapter({cli:resolveMeegleCli(),profile:process.env.PM_MEEGLE_PROFILE,host:'project.feishu.cn'});}return this.adapter;}
  persistState(before,next){if(next===before)return;this.materialIntake?.captureCollected(before,next);const errors=this.domain.validateState(next);if(errors.length)throw fail('反馈未通过保存校验：'+errors.slice(0,2).map(e=>e.message).join('；'));this.store.save(next,before.revision);}
  async poll(id,{wait=false}={}){
    if(this.closed)throw fail('服务已停止',503);if(this.jobs.has(id)){if(wait)await this.jobs.get(id).promise;return this.status(id);}
    const c=this.control(id),s=this.store.load(id);if(!c.projectIds.length)throw fail('请先选择评论采集项目');
    const objects=this.objects(s,c.projectIds);if(!objects.length)throw fail('当前项目没有已核对的飞书交付物或任务关联');
    const controller=new AbortController(),reads=[],issues=[],started=this.clock();
    this.save(id,{...c,phase:'reading',processed:0,total:objects.length,lastError:'',issues:[]});
    const job={controller,promise:null};this.jobs.set(id,job);
    job.promise=(async()=>{
      let index=0,processed=0;
      const worker=async()=>{while(index<objects.length&&!controller.signal.aborted){const remote=objects[index++];try{
        if(remote.system==='feishu_tasks'){
          const response=await this.taskClient.feedback(remote,{signal:controller.signal});reads.push(...response.reads);issues.push(...response.issues.map(message=>(s.actions.find(a=>a.id===remote.localObjectId)?.title||'任务')+'：'+message));
        }else{
        const response=await this.client().readComments(remote,{signal:controller.signal,since:Date.parse(this.collectFrom),until:Date.parse(started)});
        if(response.complete!==true)throw Error('评论分页未完成');
        reads.push({externalObjectId:remote.id,remoteId:remote.remoteId,spaceKey:remote.spaceKey,comments:response.comments,collectedAt:response.collectedAt||this.clock(),complete:true,rangeVerified:true});
        }
      }catch(error){if(!controller.signal.aborted)issues.push((s.deliverables.find(d=>d.id===remote.localObjectId)?.title||s.actions.find(d=>d.id===remote.localObjectId)?.title||'反馈对象')+'：'+(error.message||'读取失败').slice(0,180));}
      processed++;this.save(id,{...this.control(id),processed});}};
      try{
        await Promise.all(Array.from({length:Math.min(3,objects.length)},worker));
        if(controller.signal.aborted)throw Error('本次读取已停止，已有资料保留。');
        let result;
        this.store.transaction(()=>{const current=this.store.load(id);result=this.domain.ingestCommentFeedback(current,reads,{projectIds:c.projectIds,collectFrom:this.collectFrom});this.persistState(current,result.state);});
        const all=[...issues,...result.issues],current=this.control(id),failures=reads.length?0:(current.consecutiveFailures||0)+1,paused=failures>=3;
        this.save(id,{...current,enabled:paused?false:current.enabled,consecutiveFailures:failures,phase:all.length?'partial':'idle',lastCompletedAt:this.clock(),lastError:paused?'连续读取失败，已暂停自动采集；请核对读取情况后重新开始。':all.length?'部分反馈读取或解析未完成':'',issues:all,newSources:result.changed.length,historical:result.historical,unchanged:result.unchanged,nextReadAt:paused?'':new Date(Date.parse(this.clock())+this.intervalMs).toISOString()});
        void this.processPending(id);
      }catch(error){const current=this.control(id),failures=controller.signal.aborted?(current.consecutiveFailures||0):(current.consecutiveFailures||0)+1,paused=failures>=3;this.save(id,{...current,enabled:paused?false:current.enabled,consecutiveFailures:failures,phase:controller.signal.aborted?'idle':'error',lastError:controller.signal.aborted?'':(error.message||'读取失败')+(paused?'；连续失败已暂停自动采集。':''),issues,nextReadAt:paused?'':controller.signal.aborted?(current.enabled?this.clock():''):new Date(Date.parse(this.clock())+this.intervalMs).toISOString()});}
      finally{this.jobs.delete(id);}
    })();
    if(wait)await job.promise;return this.status(id);
  }
  updateAnalysis(id,sourceId,version,patch){
    this.store.transaction(()=>{const state=this.store.load(id),source=state.sources.find(s=>s.id===sourceId&&this.domain.isCommentFeedback(s));if(!source||source.feedback.contentVersion!==version)return;
      Object.assign(source.feedback.analysis,patch);source.version=(source.version||1)+1;source.updatedAt=this.clock();state.revision++;this.store.save(state,state.revision-1);
    });
  }
  processPending(id){
    if(this.analysisRuns.has(id)||this.closed)return this.analysisRuns.get(id)?.promise||Promise.resolve();
    if(this.analysisRuns.size>=1||!this.control(id).projectIds.length)return Promise.resolve();
    const controller=new AbortController(),run={controller,promise:null};this.analysisRuns.set(id,run);
    run.promise=(async()=>{
      try{
        for(let index=0;index<50&&!this.closed&&!controller.signal.aborted;index++){
          const s=this.store.load(id),scope=this.control(id).projectIds,source=s.sources.find(s=>!s.archived&&!s.collectedIntake&&this.domain.isCommentFeedback(s)&&s.feedback.analysis.status==='pending'&&s.projectIds.some(pid=>scope.includes(pid)));if(!source)break;
          const version=source.feedback.contentVersion,candidates=this.domain.feedbackCandidates(s,source),target=this.domain.feedbackTarget(s,source);
          this.updateAnalysis(id,source.id,version,{status:'running',error:''});
          try{
            if(!target||target.archived)throw Error('原反馈对象已不可用，请核对关联。');
            const context={comment:{content:source.excerpt,author:source.author,createdAt:source.feedback.originalTime,updatedAt:source.feedback.updatedTime,timeUncertain:source.feedback.timeUncertain},viewer:source.feedback.viewer,deliverable:{id:target.id,title:target.title},projects:s.projects.filter(p=>source.projectIds.includes(p.id)).map(p=>({id:p.id,title:p.title})),candidates};
            const result=await this.analyse(context,{signal:controller.signal});if(controller.signal.aborted)throw Error('摘要已停止，原始反馈已保留。');
            this.store.transaction(()=>{const current=this.store.load(id),next=this.domain.applyFeedbackAnalysis(current,source.id,version,result,candidates,this.clock());this.persistState(current,next);});
          }catch(error){this.updateAnalysis(id,source.id,version,{status:controller.signal.aborted?'pending':'failed',error:(error.message||'摘要未完成，原文已保留').slice(0,250)});}
        }
      }finally{this.analysisRuns.delete(id);}
    })();return run.promise;
  }
  retry(id,sourceId){if(this.materialIntake&&this.store.load(id).sources.find(src=>src.id===sourceId)?.collectedIntake){this.materialIntake.retryCollected({workspaceId:id,sourceId});return this.status(id);}const s=this.store.load(id),source=s.sources.find(s=>s.id===sourceId&&!s.archived&&this.domain.isCommentFeedback(s));if(!source)throw fail('反馈不存在',404);if(source.feedback.analysis.status==='running')return this.status(id);this.updateAnalysis(id,sourceId,source.feedback.contentVersion,{status:'pending',error:''});void this.processPending(id);return this.status(id);}
  review(id,sourceId,version){try{return this.store.transaction(()=>{const before=this.store.load(id);const next=this.domain.reviewCommentFeedback(before,sourceId,version,this.clock());this.persistState(before,next);return {state:next};});}catch(error){throw fail(error.message||'反馈核对未完成',409);}}
  start(){
    // Interrupted summaries resume from saved originals, never from half a model response.
    for(const w of this.store.list().filter(w=>w.type!=='restored')){
      if(!this.control(w.id).projectIds.length)continue;
      const s=this.store.load(w.id),interrupted=s.sources.filter(source=>this.domain.isCommentFeedback(source)&&source.feedback.analysis.status==='running');
      for(const source of interrupted)this.updateAnalysis(w.id,source.id,source.feedback.contentVersion,{status:'pending',error:''});
      if(s.sources.some(source=>this.domain.isCommentFeedback(source)&&['pending','running'].includes(source.feedback.analysis.status)))void this.processPending(w.id);
    }
    this.timer=setInterval(()=>{for(const w of this.store.list().filter(w=>w.type!=='restored')){const c=this.control(w.id);if(c.enabled&&!this.jobs.has(w.id)&&(!c.nextReadAt||Date.parse(c.nextReadAt)<=Date.parse(this.clock())))void this.poll(w.id).catch(()=>{});if(!this.analysisRuns.has(w.id))void this.processPending(w.id);}},10000);this.timer.unref();
  }
  async close(){this.closed=true;clearInterval(this.timer);for(const job of this.jobs.values())job.controller.abort();for(const run of this.analysisRuns.values())run.controller.abort();await Promise.allSettled([...this.jobs.values(),...this.analysisRuns.values()].map(v=>v.promise));}
}
