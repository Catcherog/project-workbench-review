import {organizeCandidates} from '../core/index.mjs';

export function demoSnapshot(now=Date.now()) {
  const at=new Date(now).toISOString();
  const day=offset=>new Date(now+offset*86400000).toISOString().slice(0,10);
  const evidence=(id,quote)=>({sourceId:'demo-source',objectId:id,version:'1',quote,rawAvailable:true,
    verification:'verbatim_at_extraction',url:null,occurredAt:at,receivedAt:at,stale:false});
  const fact=(id,projectId,itemId,field,text,extra={})=>({id,projectId,itemId,field,text,value:text,
    assertionType:'reported',authority:'source_confirmed',protected:false,stale:false,status:'effective',
    sourceRefs:[evidence(id,text)],factIds:[id],critical:false,...extra});
  const snapshot={schemaVersion:1,workspaceId:'ledger-demo',viewerId:'demo-owner',revision:1,generatedAt:at,
    coverage:{status:'complete',checkedAt:at,reasons:[]},
    projects:[
      {id:'demo-sample',title:'样机验证 · 示例',kind:'project',status:'active'},
      {id:'demo-release',title:'软件发布 · 示例',kind:'project',status:'active'},
      {id:'demo-outside',title:'模板协同 · 项目外示例',kind:'outside',status:'active'},
    ],
    items:[
      {id:'demo-bench',projectId:'demo-sample',title:'确认台架档期与开测安排',version:3,semanticVersion:2,businessState:'open',priority:'P1',
        requiresViewerAction:true,actionText:'决定是否联系测试负责人核实台架档期。',dueAt:day(1),deadlineKind:'check',assignees:['demo-engineer'],view:{fields:{}}},
      {id:'demo-rollout',projectId:'demo-release',title:'核对发布结果',version:2,semanticVersion:1,businessState:'waiting',priority:'P2',
        requiresViewerAction:false,dueAt:day(4),deadlineKind:'check',assignees:['demo-release-owner'],view:{fields:{},nextCheckAt:day(4)}},
      {id:'demo-template',projectId:'demo-outside',title:'汇总模板调整意见',version:1,semanticVersion:1,businessState:'open',priority:'P2',
        requiresViewerAction:true,actionText:'核实尚未收齐的修改意见。',dueAt:day(3),deadlineKind:'check',assignees:['demo-coordinator'],view:{fields:{}}},
    ],
    facts:[
      fact('sample-plan','demo-sample','demo-bench','plan',day(3)+' 完成对比试验，结果满足要求后安排评审。'),
      fact('sample-progress','demo-sample','demo-bench','progress','样机和方案已齐，试验尚未开始。',{authority:'unconfirmed'}),
      fact('sample-blocker','demo-sample','demo-bench','blocker','台架档期未定，可能影响试验节点。'),
      fact('release-plan','demo-release','demo-rollout','plan',day(4)+' 核对发布结果。'),
      fact('release-progress','demo-release','demo-rollout','progress','验收记录已齐，按原发布窗口推进。',{authority:'unconfirmed'}),
      fact('outside-plan','demo-outside','demo-template','plan',day(3)+' 汇总模板差异清单。'),
      fact('outside-progress','demo-outside','demo-template','progress','已收到两项修改意见。',{authority:'unconfirmed'}),
      fact('outside-blocker','demo-outside','demo-template','blocker','意见尚未收齐，是否影响汇总时间待核实。'),
    ],reviews:[],reminders:[{id:'demo-notice',itemId:'demo-bench',projectId:'demo-sample',title:'台架档期需要核实',
      body:'台架时间未定，建议在检查点前核实是否影响对比试验。',priority:'P1',dueAt:day(1),
      displayState:'unread',snoozedUntil:null,businessState:'open',basis:'demo-notice-v1'}],sources:[],decisions:[],receipts:[]};
  return organizeCandidates(snapshot,[{id:'demo-unassigned',projectId:null,itemId:null,field:'progress',value:day(2)+' 提供评审资料，尚未交付。',
    text:day(2)+' 提供评审资料，尚未交付。',assertionType:'reported',authority:'unconfirmed',association:'unknown',
    sourceRefs:[evidence('unassigned','评审资料后天给你。')]}],{requestId:'demo-initial-ingest',now:at}).snapshot;
}
