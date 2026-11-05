import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeAmSnapshot,buildBootstrap,buildProjectSummary,organizeCandidates,applyReviewDecision,
  applyReminderDisplayAction,fieldBasis,snapshotBasis,reviewSourceBasis} from '../core/index.mjs';

const now='2026-11-03T09:00:00+08:00';
const evidence=(objectId='message-1',extra={})=>({sourceId:'chat-1',objectId,version:'v1',quote:'测试方案已准备，台架时间未定',
  rawAvailable:true,verification:'verbatim_at_extraction',url:null,occurredAt:now,receivedAt:now,stale:false,...extra});
function snapshot(){return{schemaVersion:1,workspaceId:'workspace-demo',viewerId:'owner-demo',revision:1,generatedAt:now,
  coverage:{status:'complete',checkedAt:now,reasons:[]},
  projects:[{id:'p1',title:'项目甲',kind:'project',status:'active'},{id:'outside',title:'部门协同',kind:'outside',status:'active'}],
  items:[{id:'item-1',projectId:'p1',title:'核实台架档期',version:3,semanticVersion:2,businessState:'waiting',priority:'P1',
    requiresViewerAction:false,assignees:['engineer-demo'],dueAt:'2026-11-06',deadlineKind:'requirement',view:{}}],
  facts:[],reviews:[],reminders:[],sources:[],decisions:[],receipts:[]};}
function candidate(id='fact-1',extra={}){return{id,projectId:'p1',itemId:'item-1',field:'progress',value:'测试方案已准备',text:'测试方案已准备',
  assertionType:'reported',authority:'unconfirmed',association:'known',sourceRefs:[evidence()],...extra};}
function fact(id='fact-1',extra={}){return{...candidate(id),protected:false,stale:false,status:'effective',factIds:[id],...extra};}
const row=(summary,key)=>summary.rows.find(r=>r.key===key);
function rawSnapshot(){return{workspaceId:'workspace-demo',viewerId:'owner-demo',generatedAt:now,
  projects:[{key:'p1',title:'项目甲'}],items:[{id:'item-1',project_ref:'p1',description:'工程师测试',owner:'owner-demo',assignees:['engineer-demo'],
    version:3,semanticVersion:2,state:'waiting',paused:0,close_evidence:'',view:{fields:{},business_completed:false}}],
  queries:{p1:{subject_id:'p1',facts:[],effective:[],conflicts:[],pending_confirmation:[],
    freshness:{as_of_ms:Date.parse(now),sources:[{source_id:'chat-1',availability:'ok',stale:false,collected_through_ms:Date.parse(now)}]},incomplete_reasons:[]}},reminders:[]};}

test('four fixed rows keep reported progress separate from formal plan',()=>{
  const s=snapshot();s.facts=[fact('formal',{field:'plan',value:'2026-11-06 完成测试',text:'2026-11-06 完成测试',authority:'source_confirmed'}),
    fact('forecast',{field:'forecast',value:'2026-11-08 完成测试',text:'2026-11-08 完成测试',assertionType:'forecast'}),fact('progress')];
  const view=buildProjectSummary(s,'p1');
  assert.deepEqual(view.rows.map(r=>r.key),['plan','progress','blocker','todo']);
  assert.match(row(view,'plan').text,/2026-11-06/);assert.match(row(view,'plan').text,/当前预测.*2026-11-08/);
  assert.match(row(view,'progress').text,/反馈/);assert.equal(s.items[0].businessState,'waiting');
});

test('an unconfirmed plan cannot appear as the approved plan',()=>{
  const s=snapshot();s.facts=[fact('reported-plan',{field:'plan',value:'明天结项',text:'明天结项'})];
  assert.equal(row(buildProjectSummary(s,'p1'),'plan').entries.length,0);
});

test('ordinary owner field on an engineer item does not create a manager todo',()=>{
  const s=normalizeAmSnapshot(rawSnapshot());
  assert.equal(s.items[0].requiresViewerAction,false);
  assert.equal(row(buildProjectSummary(s,'p1'),'todo').entries.length,0);
  assert.equal(s.projects[0].status,'unknown');
});

test('only explicitly assigned viewer actions enter my todo',()=>{
  const s=snapshot();s.facts=[fact('engineer',{field:'action',actorId:'engineer-demo',text:'完成测试'}),
    fact('owner',{field:'action',actorId:'owner-demo',text:'确认测试窗口'})];
  assert.equal(row(buildProjectSummary(s,'p1'),'todo').text,'反馈：确认测试窗口');
});

test('critical entries are never hidden by the normal row budget or sliced',()=>{
  const s=snapshot();const text='需要立即协调，前提是材料审核通过。'.repeat(30);
  s.facts=Array.from({length:4},(_,i)=>fact('critical-'+i,{field:'blocker',critical:true,text:text+i}));
  const r=row(buildProjectSummary(s,'p1'),'blocker');
  assert.equal(r.entries.length,4);assert.equal(r.moreEntries.length,0);assert.ok(r.text.includes(text));
});

test('ordinary extra information expands in place while every record remains in detail',()=>{
  const s=snapshot();s.facts=Array.from({length:5},(_,i)=>fact('progress-'+i,{text:'进展'+i,value:'进展'+i}));
  const view=buildProjectSummary(s,'p1'),r=row(view,'progress');
  assert.equal(r.entries.length,2);assert.equal(r.moreEntries.length,3);assert.equal(view.details.facts.length,5);
});

test('paused lifecycle is visible without making it a critical risk or closing items',()=>{
  const s=snapshot();s.projects[0].status='paused';s.facts=[fact()];
  const r=row(buildProjectSummary(s,'p1'),'progress');
  assert.match(r.text,/项目已暂停/);assert.notEqual(r.severity,'critical');assert.equal(s.items[0].businessState,'waiting');
});

test('missing coverage cannot be rendered as all clear',()=>{
  const s=snapshot();s.coverage={status:'stale',checkedAt:now,reasons:['来源读取失败']};s.facts=[fact('old',{stale:true})];
  const view=buildProjectSummary(s,'p1');assert.match(row(view,'progress').text,/资料待更新/);
  assert.match(row(view,'blocker').text,/未完整核实/);assert.equal(row(view,'blocker').severity,'unknown');
});

test('native unconfirmed ordinary feedback does not flood the review queue',()=>{
  const raw=rawSnapshot();raw.queries.p1.facts=[{fact_id:'f1',field:'progress',value:'样机已收到',assertion_type:'reported',authority:'unconfirmed',
    evidence:{source_id:'chat-1',object_id:'message-1',version:'v1',quote:'样机已收到',raw_available:true,verification:'verbatim_at_extraction'}}];
  raw.queries.p1.pending_confirmation=['f1'];
  const s=normalizeAmSnapshot(raw);assert.equal(s.reviews.length,0);
  assert.match(row(buildProjectSummary(s,'p1'),'progress').text,/反馈：样机已收到/);
});

test('native raw expiration never reconstructs a quote from its stored value',()=>{
  const raw=rawSnapshot();raw.queries.p1.facts=[{fact_id:'f1',field:'progress',value:'样机已收到',authority:'unconfirmed',assertion_type:'reported',
    evidence:{source_id:'chat-1',object_id:'m1',version:'v1',quote:'不应再显示的原文',raw_available:false,verification:'verbatim_at_extraction'}}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.facts[0].sourceRefs[0].quote,null);assert.equal(s.facts[0].text,'样机已收到');
});

test('source-reviewed delivery is recognized without creating PM acceptance or project completion',()=>{
  const raw=rawSnapshot();raw.queries.p1.facts=[{fact_id:'reviewed',field:'review',value:'已审核',authority:'source_confirmed',assertion_type:'reported',
    evidence:{source_id:'project-source',object_id:'delivery-1',version:'r1',raw_available:false}}];
  raw.queries.p1.effective=[{field:'review',value:'已审核',fact_ids:['reviewed']}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.facts[0].sourceReviewVerified,true);
  assert.match(row(buildProjectSummary(s,'p1'),'progress').text,/源头已审核/);
  assert.equal(s.items[0].businessState,'waiting');assert.equal(s.reviews.length,0);
});

test('ordinary reported completion stays reported and does not close a business item',()=>{
  const s=snapshot();const r=organizeCandidates(s,[candidate('done',{text:'测试已完成',value:'测试已完成'})],{requestId:'ingest-done',now});
  assert.equal(r.outcomes[0].status,'automatic');assert.equal(r.snapshot.items[0].businessState,'waiting');
  assert.equal(r.snapshot.facts[0].authority,'unconfirmed');
});

test('missing dates do not generate a review for an otherwise clear progress message',()=>{
  const r=organizeCandidates(snapshot(),[candidate()],{requestId:'missing-date',now});
  assert.equal(r.snapshot.reviews.length,0);assert.equal(r.snapshot.facts[0].date,null);
});

test('same item and value from two sources merge with both provenance references',()=>{
  const r=organizeCandidates(snapshot(),[candidate('a'),candidate('b',{sourceRefs:[evidence('message-2',{sourceId:'chat-2'})]})],{requestId:'merge',now});
  assert.equal(r.snapshot.facts.length,1);assert.equal(r.snapshot.facts[0].sourceRefs.length,2);
  assert.deepEqual(r.snapshot.facts[0].factIds,['a','b']);
  const again=organizeCandidates(r.snapshot,[candidate('b')],{requestId:'merged-id-repeat',now});
  assert.equal(again.outcomes[0].status,'duplicate');
});

test('unknown attribution is reviewed and never put into the outside bucket',()=>{
  const r=organizeCandidates(snapshot(),[candidate('unknown',{projectId:null,itemId:null,association:'unknown'})],{requestId:'unknown',now});
  assert.equal(r.snapshot.facts[0].projectId,null);assert.equal(r.snapshot.reviews.length,1);
  assert.equal(r.snapshot.reviews[0].projectId,null);assert.equal(buildProjectSummary(r.snapshot,'outside').details.facts.length,0);
});

test('clear project-external feedback remains a named registered subject',()=>{
  const r=organizeCandidates(snapshot(),[candidate('outside',{projectId:'outside',itemId:null,association:'outside'})],{requestId:'outside',now});
  assert.equal(r.outcomes[0].status,'automatic');assert.match(row(buildProjectSummary(r.snapshot,'outside'),'progress').text,/测试方案/);
});

test('multiple fragments of one unresolved question produce one review',()=>{
  const r=organizeCandidates(snapshot(),[candidate('a',{projectId:null,itemId:null,association:'unknown'}),
    candidate('b',{projectId:null,itemId:null,association:'unknown',sourceRefs:[evidence('message-2')]})],{requestId:'group-review',now});
  assert.equal(r.snapshot.reviews.length,1);assert.equal(r.snapshot.reviews[0].factIds.length,2);
});

test('only the materially ambiguous candidate is held; known feedback still updates',()=>{
  const r=organizeCandidates(snapshot(),[candidate('known'),candidate('doubt',{field:'blocker',ambiguity:{material:true,question:'哪套样机？'}})],{requestId:'partial',now});
  assert.deepEqual(r.outcomes.map(o=>o.status),['automatic','review']);
  assert.equal(r.snapshot.facts.find(f=>f.id==='known').status,'effective');
});

test('candidate cannot elevate its own authority or self-assert verified review',()=>{
  for(const extra of [{authority:'owner_confirmed'},{sourceReviewVerified:true},{protected:true}]){
    const r=organizeCandidates(snapshot(),[candidate('bad',extra)],{requestId:'authority:'+JSON.stringify(extra),now});
    assert.equal(r.outcomes[0].reason,'authority_elevation');assert.equal(r.snapshot.facts.length,0);
  }
});

test('invalid extraction evidence creates a processing gap, not manager data-cleaning work',()=>{
  const r=organizeCandidates(snapshot(),[candidate('bad',{sourceRefs:[evidence('m',{verification:'model_says_so'})]})],{requestId:'invalid',now});
  assert.equal(r.outcomes[0].status,'rejected');assert.equal(r.snapshot.reviews.length,0);assert.equal(r.snapshot.coverage.status,'partial');
});

test('a newer ordinary formal claim cannot overwrite the human plan',()=>{
  const s=snapshot();s.facts=[fact('manual',{field:'plan',authority:'owner_confirmed',protected:true,text:'2026-11-06',value:'2026-11-06'})];
  const r=organizeCandidates(s,[candidate('later',{field:'plan',text:'2026-11-09',value:'2026-11-09'})],{requestId:'plan-protect',now});
  assert.equal(r.outcomes[0].status,'background');assert.equal(row(buildProjectSummary(r.snapshot,'p1'),'plan').text,'2026-11-06');
});

test('a forecast must not be stored as a formal plan',()=>{
  const r=organizeCandidates(snapshot(),[candidate('bad',{field:'plan',assertionType:'forecast'})],{requestId:'bad-forecast',now});
  assert.equal(r.outcomes[0].reason,'forecast_cannot_replace_plan');
});

test('precise field basis detects a changed human decision but ignores unrelated fields',()=>{
  const s=snapshot();s.decisions=[{itemId:'item-1',field:'progress',version:1,value:'旧决定'}];
  const basis=fieldBasis(s,'item-1','progress');const changed=structuredClone(s);changed.decisions[0].version=2;
  const rejected=organizeCandidates(changed,[candidate('stale',{expectedFieldBasis:basis})],{requestId:'stale-decision',now});
  assert.equal(rejected.outcomes[0].reason,'field_basis_changed');
  const unrelated=structuredClone(s);unrelated.facts=[fact('other',{field:'blocker'})];
  assert.equal(fieldBasis(unrelated,'item-1','progress'),basis);
  const accepted=organizeCandidates(unrelated,[candidate('a',{expectedFieldBasis:basis}),candidate('b',{text:'另一条进展',value:'另一条进展',expectedFieldBasis:basis})],{requestId:'same-batch',now});
  assert.deepEqual(accepted.outcomes.map(o=>o.status),['automatic','automatic']);
});

test('explicit decision version detects stale proposals even without a field hash',()=>{
  const s=snapshot();s.decisions=[{itemId:'item-1',field:'progress',version:4}];
  const r=organizeCandidates(s,[candidate('old',{expectedDecisionVersion:3})],{requestId:'version',now});
  assert.equal(r.outcomes[0].reason,'manual_decision_changed');
});

test('source revision removes only its old support and keeps an independent valid source',()=>{
  const s=snapshot();s.sources=[{sourceId:'chat-1',objectId:'message-1',version:'v1'}];
  s.facts=[fact('both',{sourceRefs:[evidence(),evidence('m2',{sourceId:'chat-2'})]})];
  const r=organizeCandidates(s,[],{requestId:'source-revision',now,sourceUpdates:[{sourceId:'chat-1',objectId:'message-1',version:'v2',expectedVersion:'v1'}]});
  assert.equal(r.snapshot.facts[0].status,'effective');assert.equal(r.snapshot.facts[0].sourceRefs.length,1);
  assert.equal(r.snapshot.facts[0].sourceRefs[0].sourceId,'chat-2');
});

test('withdrawn source does not close the original item or show a false all-clear',()=>{
  const s=snapshot();s.sources=[{sourceId:'chat-1',objectId:'message-1',version:'v1'}];s.facts=[fact('risk',{field:'blocker'})];
  const r=organizeCandidates(s,[],{requestId:'withdrawal',now,sourceUpdates:[{sourceId:'chat-1',objectId:'message-1',version:'v1',withdrawn:true}]});
  assert.equal(r.snapshot.facts[0].status,'withdrawn');assert.equal(r.snapshot.items[0].businessState,'waiting');
  assert.equal(row(buildProjectSummary(r.snapshot,'p1'),'blocker').severity,'unknown');
});

test('source failure preserves last known information and marks coverage stale',()=>{
  const s=snapshot();s.facts=[fact()];
  const r=organizeCandidates(s,[],{requestId:'source-failed',now,sourceUpdates:[{sourceId:'chat-1',objectId:'message-1',version:'v1',availability:'error'}]});
  assert.equal(r.snapshot.facts[0].status,'effective');assert.equal(r.snapshot.facts[0].stale,true);assert.equal(r.snapshot.coverage.status,'stale');
});

test('protected manual decisions survive source withdrawal as requiring revalidation',()=>{
  const s=snapshot();s.facts=[fact('protected',{field:'plan',authority:'owner_confirmed',protected:true})];
  const r=organizeCandidates(s,[],{requestId:'manual-source',now,sourceUpdates:[{sourceId:'chat-1',objectId:'message-1',version:'v1',withdrawn:true}]});
  assert.equal(r.snapshot.facts[0].status,'effective');assert.equal(r.snapshot.facts[0].requiresRevalidation,true);
  assert.match(row(buildProjectSummary(r.snapshot,'p1'),'plan').text,/原依据已变化/);
});

test('source revision needs an exact expected version; caller input stays unchanged on error',()=>{
  const s=snapshot();s.sources=[{sourceId:'chat-1',objectId:'message-1',version:'v3'}];
  const before=JSON.stringify(s);
  assert.throws(()=>organizeCandidates(s,[],{requestId:'bad-revision',now,sourceUpdates:[{sourceId:'chat-1',objectId:'message-1',version:'v2',expectedVersion:'v1'}]}),{code:'source_version_changed'});
  assert.equal(JSON.stringify(s),before);
});

test('review association changes information only, preserves authority and permits idempotent retry',()=>{
  const staged=organizeCandidates(snapshot(),[candidate('unknown',{projectId:null,itemId:null,association:'unknown'})],{requestId:'stage',now}).snapshot;
  const r=staged.reviews[0];const decision={reviewId:r.id,choiceId:'p1',expectedBasis:r.basis,requestId:'resolve',actorId:staged.viewerId,now};
  const resolved=applyReviewDecision(staged,decision);
  assert.equal(resolved.snapshot.facts[0].projectId,'p1');assert.equal(resolved.snapshot.facts[0].authority,'unconfirmed');
  assert.equal(resolved.receipt.result.externalActionApproved,false);assert.equal(resolved.snapshot.items[0].businessState,'waiting');
  assert.equal(applyReviewDecision(resolved.snapshot,decision).duplicate,true);
});

test('stale review or unauthorized actor cannot apply an information decision',()=>{
  const s=organizeCandidates(snapshot(),[candidate('unknown',{projectId:null,itemId:null,association:'unknown'})],{requestId:'stage',now}).snapshot;
  const r=s.reviews[0];
  assert.throws(()=>applyReviewDecision(s,{reviewId:r.id,choiceId:'p1',expectedBasis:'old',requestId:'bad',actorId:s.viewerId,now}),{code:'review_basis_changed'});
  assert.throws(()=>applyReviewDecision(s,{reviewId:r.id,choiceId:'p1',expectedBasis:r.basis,requestId:'bad',actorId:'other',now}),{code:'actor_not_authorized'});
});

test('review cannot use a source revision that changed after the question was shown',()=>{
  const s=organizeCandidates(snapshot(),[candidate('unknown',{projectId:null,itemId:null,association:'unknown'})],{requestId:'stage',now}).snapshot;
  const r=s.reviews[0];s.sources=[{sourceId:'chat-1',objectId:'message-1',version:'v2'}];
  assert.throws(()=>applyReviewDecision(s,{reviewId:r.id,choiceId:'p1',expectedBasis:r.basis,requestId:'resolve',actorId:s.viewerId,now}),{code:'review_evidence_changed'});
});

test('request ids cannot be reused for a different operation',()=>{
  const r=organizeCandidates(snapshot(),[candidate()],{requestId:'same',now});
  assert.throws(()=>organizeCandidates(r.snapshot,[candidate('different')],{requestId:'same',now}),{code:'request_id_reused'});
});

function reminded(){const s=snapshot();s.reminders=[{id:'reminder-1',itemId:'item-1',projectId:'p1',title:'核实测试',body:'台架未定',priority:'P1',
  dueAt:'2026-11-06',displayState:'unread',businessState:'waiting',basis:'business-basis'}];return s;}

test('reading a reminder changes display only, not business state or due date',()=>{
  const s=reminded(),r=applyReminderDisplayAction(s,{reminderId:'reminder-1',action:'read',expectedBasis:'business-basis',requestId:'read',actorId:s.viewerId,now});
  assert.equal(r.snapshot.reminders[0].displayState,'read');assert.equal(r.snapshot.reminders[0].basis,'business-basis');
  assert.equal(r.snapshot.reminders[0].businessState,'waiting');assert.equal(r.snapshot.items[0].dueAt,'2026-11-06');
});

test('snoozing then reading preserves the snooze, original deadline and open business item',()=>{
  const s=reminded(),until='2026-11-03T14:00:00+08:00';
  const snoozed=applyReminderDisplayAction(s,{reminderId:'reminder-1',action:'snooze',expectedBasis:'business-basis',requestId:'snooze',actorId:s.viewerId,now,until});
  const read=applyReminderDisplayAction(snoozed.snapshot,{reminderId:'reminder-1',action:'read',expectedBasis:'business-basis',requestId:'read',actorId:s.viewerId,now});
  assert.equal(read.snapshot.reminders[0].displayState,'snoozed');assert.equal(read.snapshot.reminders[0].snoozedUntil,until);
  assert.equal(read.snapshot.reminders[0].dueAt,'2026-11-06');assert.equal(read.snapshot.items[0].businessState,'waiting');
});

test('invalid or stale reminder commands do not mutate the reminder',()=>{
  const s=reminded();const before=JSON.stringify(s);
  for(const extra of [{expectedBasis:'old'},{until:'2026-11-02T09:00:00+08:00'}]){
    assert.throws(()=>applyReminderDisplayAction(s,{reminderId:'reminder-1',action:'snooze',expectedBasis:'business-basis',requestId:'invalid',actorId:s.viewerId,now,until:'2026-11-04T09:00:00+08:00',...extra}));
  }
  assert.equal(JSON.stringify(s),before);
});

test('native reminder metadata only applies to the same business basis and source scope',()=>{
  const raw=rawSnapshot();raw.reminders=[{id:'r1',itemId:'item-1',title:'待核实',body:'进展未核实',basis:'new',metadata:{basis:'old',displayState:'read'}},
    {id:'r2',itemId:'unauthorized',title:'不得展示',body:'scope',basis:'x'}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.reminders.length,1);assert.equal(s.reminders[0].displayState,'unread');
});

test('expired display snooze becomes visible without creating a second reminder',()=>{
  const raw=rawSnapshot();raw.reminders=[{id:'r1',itemId:'item-1',title:'待核实',basis:'b',displayState:'snoozed',snoozedUntil:'2026-11-02T14:00:00+08:00'}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.reminders.length,1);assert.equal(s.reminders[0].displayState,'unread');
});

test('unavailable reminder coverage stays explicit even if no reminder was returned',()=>{
  const raw=rawSnapshot();raw.reminderCoverage={status:'unavailable',reasons:['原跟进记录暂不可读']};
  const s=normalizeAmSnapshot(raw);assert.equal(s.reminders.length,0);assert.equal(s.coverage.status,'partial');
  assert.ok(s.coverage.reasons.includes('原跟进记录暂不可读'));
});

test('native ledger text needs verified source identity before projection',()=>{
  const raw=rawSnapshot();raw.projects[0]['关键日期']='2026-11-06';raw.projects[0]['待办']='确认测试窗口';
  assert.equal(normalizeAmSnapshot(raw).facts.length,0);
  raw.projects[0].read_status='ok';raw.projects[0].source_revision='revision-a';
  const s=normalizeAmSnapshot(raw);assert.match(row(buildProjectSummary(s,'p1'),'plan').text,/2026-11-06/);
  assert.match(row(buildProjectSummary(s,'p1'),'todo').text,/确认测试窗口/);
  assert.equal(row(buildProjectSummary(s,'p1'),'todo').entries[0].itemId,null);
});

test('formal conflicting sources remain visible as a question, ordinary differing progress does not all become review',()=>{
  const raw=rawSnapshot();const native=(id,field,value)=>({fact_id:id,field,value,assertion_type:'reported',authority:'source_confirmed',
    evidence:{source_id:'s',object_id:id,version:'v1',raw_available:false}});
  raw.queries.p1.facts=[native('p1','plan','2026-11-06'),native('p2','plan','2026-11-08'),native('a','progress','方案完成'),native('b','progress','样机到货')];
  raw.queries.p1.conflicts=[{field:'plan',kind:'confirmed_conflict',fact_ids:['p1','p2']},{field:'progress',kind:'confirmed_conflict',fact_ids:['a','b']}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.reviews.length,1);assert.equal(s.reviews[0].factIds.length,2);
  assert.match(row(buildProjectSummary(s,'p1'),'blocker').text,/来源冲突/);
});

test('same projection has a stable basis despite fetch wall-clock and unrelated operation receipts',()=>{
  const a=snapshot(),b=structuredClone(a);b.generatedAt='2026-11-03T10:00:00+08:00';b.receipts=[{requestId:'unrelated'}];
  assert.equal(snapshotBasis(a),snapshotBasis(b));
  assert.equal(buildBootstrap(a).projects[0].id,'p1');assert.equal(buildBootstrap(a).projects[1].id,'outside');
});

test('native attribution resolution reported_feedback appears as attributed progress',()=>{
  const raw=rawSnapshot();raw.queries.p1.facts=[{fact_id:'assigned',field:'reported_feedback',value:'评审资料周四提供',authority:'unconfirmed',assertion_type:'reported',
    evidence:{source_id:'s',object_id:'m',version:'v1',quote:'评审资料周四提供',raw_available:true,verification:'verbatim_at_extraction'}}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.facts[0].field,'progress');
  assert.match(row(buildProjectSummary(s,'p1'),'progress').text,/反馈：评审资料周四提供/);
  assert.equal(s.facts[0].authority,'unconfirmed');
});

test('native assignee JSON is parsed without deriving a manager task',()=>{
  const raw=rawSnapshot();raw.items[0].assignees='["engineer-demo"]';
  assert.deepEqual(normalizeAmSnapshot(raw).items[0].assignees,['engineer-demo']);
  raw.items[0].assignees='not json';assert.deepEqual(normalizeAmSnapshot(raw).items[0].assignees,[]);
});

test('native source-review kind and exact version-bound choice are preserved',()=>{
  const raw=rawSnapshot();const choice={id:'current-sources',label:'采用所示当前依据',value:{kind:'sources',itemId:'item-1',expectedItemVersion:3,expectedSemanticVersion:2,factIds:['f1'],reviewHash:'native-hash'}};
  raw.semanticReviews=[{id:'sources:item-1',kind:'conflict',projectId:'p1',itemId:'item-1',reviewHash:'native-hash',reason:'sources_changed',
    text:'当前依据已经变化',rawAvailable:true,choices:[choice]}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.reviews[0].kind,'conflict');assert.deepEqual(s.reviews[0].choices,[choice]);
});

test('raw-expired native reviews offer no misleading executable choice',()=>{
  const raw=rawSnapshot();raw.semanticReviews=[{id:'review-x',reason:'subject_unresolved',reviewHash:'hash',text:'不得显示',rawAvailable:false,
    choices:[{subjectId:'p1',title:'项目甲'}]}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.reviews[0].choices.length,0);assert.doesNotMatch(s.reviews[0].excerpt,/不得显示/);
});

test('display choice hides the answered question while preserving authoritative conflict and protected fact',()=>{
  const raw=rawSnapshot();const native=(id,value,authority,protectedValue)=>({fact_id:id,field:'plan',value,assertion_type:'reported',authority,protected:protectedValue,
    evidence:{source_id:'s',object_id:id,version:'v1',raw_available:true,quote:value,verification:'verbatim_at_extraction'}});
  raw.queries.p1.facts=[native('a','2026-11-06','owner_confirmed',true),native('b','2026-11-08','source_confirmed',false)];
  raw.queries.p1.conflicts=[{field:'plan',kind:'confirmed_conflict',fact_ids:['a','b']}];
  const first=normalizeAmSnapshot(raw),review=first.reviews[0];
  raw.reviewDecisions=[{reviewId:review.id,reviewHash:review.basis,factIds:['b','a'],selectedFactId:'b',sourceIdentityHash:reviewSourceBasis(review)}];
  const second=normalizeAmSnapshot(raw),view=buildProjectSummary(second,'p1');
  assert.equal(second.reviews[0].status,'resolved');assert.equal(second.facts[0].status,'conflict');assert.equal(second.facts[0].authority,'owner_confirmed');
  assert.match(row(view,'plan').text,/2026-11-06/);assert.match(row(view,'plan').text,/2026-11-08/);
  assert.match(row(view,'blocker').text,/来源冲突/);
  raw.queries.p1.facts[1].evidence.version='v2';
  assert.equal(normalizeAmSnapshot(raw).reviews[0].status,'pending');
});

test('source identity hash is independent of evidence order, quote and duplicates',()=>{
  const a=evidence('a'),b=evidence('b');
  assert.equal(reviewSourceBasis({evidence:[a,b,a]}),reviewSourceBasis({evidence:[b,{...a,quote:'另一段原句'}]}));
  assert.notEqual(reviewSourceBasis({evidence:[a,b]}),reviewSourceBasis({evidence:[a,{...b,version:'v2'}]}));
});

test('ordinary confirmed progress fragments remain readable even without a singleton effective value',()=>{
  const raw=rawSnapshot();raw.queries.p1.facts=['方案完成','样机到货'].map((value,i)=>({fact_id:'progress-'+i,field:'progress',value,assertion_type:'reported',authority:'source_confirmed',
    evidence:{source_id:'s',object_id:'m'+i,version:'v1',raw_available:false}}));
  raw.queries.p1.conflicts=[{field:'progress',kind:'confirmed_conflict',fact_ids:['progress-0','progress-1']}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.reviews.length,0);
  assert.match(row(buildProjectSummary(s,'p1'),'progress').text,/方案完成/);assert.match(row(buildProjectSummary(s,'p1'),'progress').text,/样机到货/);
});

test('explicit dates stay in the default summary and keep deadline semantics',()=>{
  const s=snapshot();s.facts=[fact('plan-date',{field:'plan',authority:'source_confirmed',text:'完成台架测试',date:'2026-11-06'})];
  s.items[0].requiresViewerAction=true;s.items[0].deadlineKind='check';
  const view=buildProjectSummary(s,'p1');assert.match(row(view,'plan').text,/2026-11-06/);
  assert.match(row(view,'todo').text,/检查：2026-11-06/);
});

test('cancelled item remains distinct from completed and does not create an actionable todo',()=>{
  const raw=rawSnapshot();raw.items[0].state='cancelled';raw.items[0].requires_owner_action=true;
  const s=normalizeAmSnapshot(raw);assert.equal(s.items[0].businessState,'cancelled');
  assert.equal(row(buildProjectSummary(s,'p1'),'todo').entries.length,0);
});

test('query time does not claim a newer source coverage boundary',()=>{
  const raw=rawSnapshot();raw.queries.p1.freshness.as_of_ms=Date.parse('2026-11-03T15:00:00+08:00');
  raw.queries.p1.freshness.sources[0].collected_through_ms=Date.parse('2026-11-02T18:00:00+08:00');
  const s=normalizeAmSnapshot(raw);assert.equal(s.coverage.checkedAt,'2026-11-02T10:00:00.000Z');
});

test('an unrelated project read failure does not mark this project stale or alter its basis',()=>{
  const raw=rawSnapshot();raw.projects.push({key:'p2',title:'另一个项目'});raw.queries.p2=structuredClone(raw.queries.p1);
  const first=normalizeAmSnapshot(raw),basis=snapshotBasis(first,'p1');
  raw.queries.p2.freshness.sources[0].availability='error';raw.queries.p2.freshness.sources[0].stale=true;
  const second=normalizeAmSnapshot(raw);assert.equal(second.coverage.status,'stale');
  assert.equal(buildProjectSummary(second,'p1').coverage.status,'complete');assert.equal(snapshotBasis(second,'p1'),basis);
});

test('unknown source timestamps show an explicit freshness gap rather than using query time',()=>{
  const raw=rawSnapshot();delete raw.queries.p1.freshness.sources[0].collected_through_ms;
  const s=normalizeAmSnapshot(raw);assert.equal(s.coverage.checkedAt,null);assert.equal(s.coverage.status,'partial');
});

test('malformed snapshot input yields a structured core error',()=>{
  assert.throws(()=>normalizeAmSnapshot(null),{code:'snapshot_schema'});
});

test('native raw expiry is checked against snapshot time and retains structured progress',()=>{
  const raw=rawSnapshot();raw.queries.p1.facts=[{fact_id:'f1',field:'progress',value:'样机已收到',assertion_type:'reported',authority:'unconfirmed',
    evidence:{source_id:'s',object_id:'m',version:'v1',quote:'原始完整聊天',raw_available:true,raw_expires_at_ms:Date.parse('2026-11-02T09:00:00+08:00'),verification:'verbatim_at_extraction'}}];
  const s=normalizeAmSnapshot(raw),e=s.facts[0].sourceRefs[0];
  assert.equal(e.rawExpiresAt,'2026-11-02T01:00:00.000Z');assert.equal(e.rawAvailable,false);assert.equal(e.quote,null);
  assert.match(row(buildProjectSummary(s,'p1'),'progress').text,/样机已收到/);
});

test('expired semantic review removes the excerpt and executable choices',()=>{
  const raw=rawSnapshot();raw.semanticReviews=[{id:'r1',reason:'subject_unresolved',reviewHash:'b',text:'原文内容',rawAvailable:true,
    expiresAtMs:Date.parse('2026-11-02T09:00:00+08:00'),choices:[{subjectId:'p1',title:'项目甲'}]}];
  const s=normalizeAmSnapshot(raw);assert.equal(s.reviews[0].choices.length,0);assert.equal(s.reviews[0].evidence[0].quote,null);
  assert.doesNotMatch(s.reviews[0].excerpt,/原文内容/);
});

test('source updates mark only the affected normalized project coverage stale',()=>{
  const raw=rawSnapshot();raw.queries.p1.facts=[{fact_id:'f1',field:'progress',value:'进展',assertion_type:'reported',authority:'unconfirmed',
    evidence:{source_id:'chat-1',object_id:'message-1',version:'v1',quote:'进展',raw_available:true,verification:'verbatim_at_extraction'}}];
  const s=normalizeAmSnapshot(raw),r=organizeCandidates(s,[],{requestId:'native-source-failure',now,sourceUpdates:[{sourceId:'chat-1',objectId:'message-1',version:'v1',availability:'error'}]});
  assert.equal(buildProjectSummary(r.snapshot,'p1').coverage.status,'stale');
});

test('closed original item no longer offers a historical action as current manager work',()=>{
  const s=reminded();s.items[0].businessState='closed';s.reminders[0].businessState='closed';
  s.facts=[fact('action-old',{field:'action',actorId:s.viewerId,actionState:'open'})];
  const view=buildProjectSummary(s,'p1');assert.equal(row(view,'todo').entries.length,0);assert.equal(view.details.facts.length,1);
  assert.equal(buildBootstrap(s).reminders.length,0);
});
