/** Minimal read model for pet reminders and selection lists. Source bodies stay in the service. */
const fields=new Set(('id title workspaceId version projectIds sourceIds caseId outputIds actionIds archived status done actual actualEnd actualCompletedAt completedAt owner ownerId executor executorId acceptance acceptanceStatus acceptanceEvidenceIds evidenceIds deliverableIds committed forecast plannedStart plannedEnd dueAt checkAt deadline decidedAt lastContactAt executionStatus submissionStatus nodeStatus nextAction followUp trigger response confirmed stale staleReasons basisRefs supersedesId').split(' '));
const collections=['projects','milestones','actions','decisions','risks','judgments','flowNodes','deliverables','people','resources','dependencies','relations'];
export function petSnapshot(state,followupProjections){
  const view={schemaVersion:2,workspaceId:state.workspaceId,workspaceName:state.workspaceName,workspaceType:state.workspaceType,revision:state.revision};
  for(const kind of collections)view[kind]=(state[kind]||[]).map(row=>Object.fromEntries(Object.entries(row).filter(([key])=>fields.has(key))));
  view.sources=(state.sources||[]).map(row=>Object.fromEntries(Object.entries(row).filter(([key])=>['id','title','workspaceId','version','projectIds','sourceIds','archived','confirmed','supersedesId'].includes(key))));
  view.changeGroups=(state.changeGroups||[]).map(group=>({id:group.id,status:group.status,purpose:group.purpose,createdAt:group.createdAt}));
  for(const key of ['audit','externalObjects','externalLinks','remoteFieldValues','mappingRules','syncBaselines','syncRuns','syncReceipts','dispatchRecords','reports','candidates','publications'])view[key]=[];
  // Optional coordinator injection: no source bodies travel into the pet shell.
  if(followupProjections)view.followupProjections=followupProjections;
  view.cases=(state.cases||[]).map(row=>Object.fromEntries(Object.entries(row).filter(([key])=>fields.has(key))));
  view.receipts={};view.viewed=null;return view;
}
