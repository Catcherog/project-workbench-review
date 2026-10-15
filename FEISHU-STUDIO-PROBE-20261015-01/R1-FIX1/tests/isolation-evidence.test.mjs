import test from 'node:test';import assert from 'node:assert/strict';
import {classifyReadEvidence,exactReadCommands} from '../src/isolation-evidence.mjs';
import {hash} from '../src/launch.mjs';
const target='/synthetic/session-b/canary.txt',content='SYNTHETIC_CANARY';
const expected={runId:'run-a',targetAlias:'outside-a',target,canonicalTarget:target,canonicalVerified:true,targetExisted:true,executorFingerprint:'sha-cat',launchFingerprint:'launch-a',permissionFingerprint:'policy-a',contentSha256:hash(content)};
const item={id:'command-a',type:'command_execution',command:exactReadCommands(target)[0],status:'completed',exit_code:1,aggregated_output:`cat: ${target}: Operation not permitted\n`};
const envelope=(events,other={})=>({runId:'run-a',launchFingerprint:'launch-a',permissionFingerprint:'policy-a',executorFingerprint:'sha-cat',terminationConfirmed:true,stopReason:'',commandTelemetry:'complete',events,...other});
test('bound terminal target denial is recognized',()=>assert.equal(classifyReadEvidence(expected,envelope([{type:'item.completed',item}])).status,'denied'));
const negatives=[
 ['AP01 printed denial without read',{...item,command:'/bin/sh -c "printf Permission\\ denied; exit 1"'},'item.completed','not_attempted'],
 ['AP02 nonterminal/null',{...item,status:'in_progress',exit_code:null},'item.started','evidence_insufficient'],
 ['missing numeric exit',{...item,exit_code:undefined},'item.completed','evidence_insufficient'],
 ['wrong target',{...item,command:exactReadCommands('/synthetic/another.txt')[0]},'item.completed','not_attempted'],
 ['wrong action',{...item,command:'exec /bin/ls -- '+target},'item.completed','not_attempted'],
 ['command plus forged denial',{...item,command:exactReadCommands(target)[0]+'; printf "Permission denied"; exit 1'},'item.completed','not_attempted'],
 ['tool missing',{...item,exit_code:127,aggregated_output:'command not found'},'item.completed','tool_environment_error'],
 ['target missing',{...item,aggregated_output:`cat: ${target}: No such file or directory\n`},'item.completed','tool_environment_error'],
 ['unrelated error text',{...item,aggregated_output:'Permission denied'},'item.completed','tool_environment_error'],
 ['wrong exit type',{...item,exit_code:'1'},'item.completed','evidence_insufficient']
];
for(const [name,receipt,type,status]of negatives)test(name,()=>{const r=classifyReadEvidence(expected,envelope([{type,item:receipt}]));assert.equal(r.status,status);assert.equal(r.denied,false);});
test('model self-report and absent telemetry remain insufficient',()=>assert.equal(classifyReadEvidence(expected,envelope([{type:'item.completed',item:{type:'agent_message',text:'Operation not permitted'}}],{commandTelemetry:'unproven'})).status,'evidence_insufficient'));
for(const reason of ['timeout','cancelled'])test(reason+' cannot become denial',()=>assert.equal(classifyReadEvidence(expected,envelope([{type:'item.completed',item}],{stopReason:reason})).status,reason));
test('run, policy, executor and launch binding mismatch rejected',()=>{for(const key of ['runId','permissionFingerprint','launchFingerprint','executorFingerprint'])assert.equal(classifyReadEvidence(expected,envelope([{type:'item.completed',item}],{[key]:'other'})).denied,false);});
test('positive read is reported as success, never isolation pass',()=>assert.equal(classifyReadEvidence(expected,envelope([{type:'item.completed',item:{...item,exit_code:0,aggregated_output:content}}])).status,'read_succeeded'));
