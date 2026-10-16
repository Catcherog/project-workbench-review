import {AssistantActions} from './assistant-actions.mjs';
import {CodexMonitorAgent} from './codex-monitor-agent.mjs';

/** Called after the existing task and meeting services are constructed. */
export function connectAssistantActions({assistant,reminders,meetingWorkflow,agentMonitor,riskAgent,runtimeSettings,analyseMonitor,mode='disabled'}) {
  if(assistant.actions)throw Error('助手操作服务已经接入');
  const service=new AssistantActions({assistant,reminders,meetings:meetingWorkflow,mode});
  assistant.actions=service;
  if(riskAgent){
    const status=workspaceId=>{
      const current=riskAgent.status(workspaceId),job=current.jobs[0];
      return {available:true,mode:current.analysisOnChange?'on-change':'on-demand',running:current.running,job:job?{...job,producer:'codex',analysed:job.seeds.length+(job.reused?.length||0),message:job.steps.at(-1)?.label||(job.status==='completed'?'没有需要重复分析的新资料':'正在研判新资料')}:null};
    };
    // The released risk agent owns analysis, checkpoints and event-triggered runs.
    // This compatibility endpoint delegates to it instead of starting a second worker.
    assistant.monitorAgent={running:riskAgent.jobs,status,start:input=>{riskAgent.start(input);return status(input.workspaceId);},cancel:async input=>{
      const running=riskAgent.jobs.get(input.workspaceId);
      if(running&&input.jobId!==running.id)throw Object.assign(Error('研判任务已变化，请刷新'),{status:409});
      riskAgent.cancel(input.workspaceId);await running?.promise;return status(input.workspaceId);
    },close:async()=>{}};
  }else if(agentMonitor)assistant.monitorAgent=new CodexMonitorAgent({store:assistant.store,monitor:agentMonitor,runtimeSettings:runtimeSettings||assistant.runtimeSettings,...(analyseMonitor?{analyse:analyseMonitor}:{})});
  return service;
}
