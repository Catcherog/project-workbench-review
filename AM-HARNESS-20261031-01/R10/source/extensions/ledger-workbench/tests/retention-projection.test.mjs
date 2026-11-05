import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeAmSnapshot,buildProjectSummary} from '../core/index.mjs';
import {sanitizeEvidence} from '../server/evidence-retention.mjs';
import {scopeSnapshot} from '../server/projection-cache.mjs';

const captured=Date.parse('2026-11-03T01:00:00Z');
const rawText='原始关联反馈，仅在原文可用期展示';
function rawSnapshot(){
  const ref={source_id:'source-a',object_id:'message-a',version:'v1',quote:rawText,
    raw_available:true,raw_expires_at_ms:captured+1000};
  return {workspaceId:'w1',viewerId:'u1',generatedAt:new Date(captured).toISOString(),
    projects:[{id:'p1',title:'项目甲'},{id:'p2',title:'项目乙'}],items:[],reminders:[],
    queries:{p1:{facts:[
      {fact_id:'bound',field:'progress',value:rawText,authority:'unconfirmed',retentionBoundExcerpt:true,evidence:ref},
      {fact_id:'structured',field:'plan',value:'正式计划保留',authority:'source_confirmed',evidence:{...ref,object_id:'plan-a'}}],
      effective:[{fact_ids:['structured']}],freshness:{sources:[{availability:'ok',collected_through_ms:captured}]},incomplete_reasons:[]},
      p2:{facts:[],freshness:{sources:[{availability:'ok',collected_through_ms:captured}]},incomplete_reasons:[]}}};
}

test('retention-bound raw text expires in facts, visible entries and joined four-row summaries',()=>{
  const normalized=normalizeAmSnapshot(rawSnapshot());
  const summary=buildProjectSummary(normalized,'p1');
  assert.match(summary.rows.find(r=>r.key==='progress').text,/原始关联反馈/);
  const expired=sanitizeEvidence(summary,captured+1001);
  assert.ok(!JSON.stringify(expired).includes(rawText));
  assert.equal(expired.details.facts.find(f=>f.id==='bound').rawExcerptUnavailable,true);
  assert.match(expired.rows.find(r=>r.key==='plan').text,/正式计划保留/);
  assert.equal(expired.details.facts.find(f=>f.id==='structured').value,'正式计划保留');
});

test('normalization never restores an unavailable raw excerpt from fact.value',()=>{
  const raw=rawSnapshot();raw.generatedAt=new Date(captured+1001).toISOString();
  const normalized=normalizeAmSnapshot(raw);
  assert.equal(normalized.facts.find(f=>f.id==='bound').text,'原文暂不可用，待刷新');
  assert.ok(!JSON.stringify(normalized).includes(rawText));
});

test('processing gaps remain visible as coverage and expire without becoming actionable reviews',()=>{
  const raw=rawSnapshot();
  const gap={id:'gap-1',kind:'processing',projectIds:['p1'],sourceId:'source-a',objectId:'message-b',sourceVersion:'v1',
    reason:'条件语句尚未完整处理',gapCode:'conditional',text:'如果材料齐备，下周可以安排',rawAvailable:true,expiresAtMs:captured+1000};
  raw.queries.p1.coverage={processing_pending:true,processingGaps:[gap]};
  raw.queries.p1.incomplete_reasons=['资料含义尚未完整处理，当前摘要未涵盖全部资料'];
  const normalized=normalizeAmSnapshot(raw),summary=buildProjectSummary(normalized,'p1');
  assert.equal(normalized.reviews.length,0);assert.equal(summary.coverage.status,'partial');
  assert.equal(summary.details.processingGaps[0].text,gap.text);
  assert.equal(Object.hasOwn(summary.details.processingGaps[0],'choices'),false);
  const expired=sanitizeEvidence(summary,captured+1001);
  assert.ok(!JSON.stringify(expired).includes(gap.text));
  assert.match(expired.coverage.reasons.join(''),/尚未完整处理/);
  const scoped=scopeSnapshot(raw,{userId:'u1',workspaceId:'w1',projectIds:['p2']});
  assert.deepEqual(scoped.coverage.processingGaps,[]);
});
