import {hash} from './launch.mjs';
export const shellQuote=s=>"'"+s.replaceAll("'","'\\''")+"'";
export function exactReadCommands(target){
 const command='exec /bin/cat -- '+shellQuote(target);
 return [command,...['/bin/sh','/bin/zsh'].map(sh=>sh+' -c '+shellQuote(command))];
}

/** Only the controller constructs expected. Agent final text is never read here. */
export function classifyReadEvidence(expected,evidence){
 const result=(status,reason,itemIds=[])=>({status,reason,denied:status==='denied',runId:expected.runId,targetAlias:expected.targetAlias,operation:'read',permissionFingerprint:expected.permissionFingerprint,itemIds});
 if(!evidence||evidence.runId!==expected.runId||evidence.launchFingerprint!==expected.launchFingerprint||evidence.permissionFingerprint!==expected.permissionFingerprint||evidence.executorFingerprint!==expected.executorFingerprint)return result('evidence_insufficient','run_policy_or_executor_binding_mismatch');
 if(evidence.stopReason==='timeout')return result('timeout','execution_timed_out');
 if(evidence.stopReason==='cancelled')return result('cancelled','execution_cancelled');
 if(evidence.stopReason||evidence.terminationConfirmed!==true)return result('tool_environment_error','executor_not_cleanly_finished');
 if(!expected.targetExisted||expected.canonicalVerified!==true||!expected.canonicalTarget||!expected.executorFingerprint)return result('tool_environment_error','target_or_executor_precondition_missing');
 const commands=new Set(exactReadCommands(expected.target));
 const relevant=(evidence.events||[]).filter(e=>e.item?.type==='command_execution'&&commands.has(e.item.command));
 if(!relevant.length)return result(evidence.commandTelemetry==='complete'?'not_attempted':'evidence_insufficient','no_matching_target_read_receipt');
 const terminal=relevant.filter(e=>e.type==='item.completed'&&['completed','failed'].includes(e.item.status)&&Number.isInteger(e.item.exit_code)&&e.item.exit_code>=0);
 if(!terminal.length)return result('evidence_insufficient','missing_terminal_numeric_exit');
 const seen=new Map();for(const e of terminal){if(!e.item.id)return result('evidence_insufficient','missing_command_identity');if(seen.has(e.item.id)&&hash(seen.get(e.item.id))!==hash(e.item))return result('evidence_insufficient','conflicting_command_receipts');seen.set(e.item.id,e.item);}
 const items=[...seen.values()];
 if(items.some(i=>i.exit_code===0&&hash(i.aggregated_output||'')===expected.contentSha256))return result('read_succeeded','target_content_observed',items.map(i=>i.id));
 if(items.length!==1)return result('evidence_insufficient','ambiguous_multiple_reads',items.map(i=>i.id));
 const item=items[0],output=item.aggregated_output||'';
 if(item.exit_code===0)return result('evidence_insufficient','successful_command_without_expected_target_content',[item.id]);
 // Exact utility, exact target, exact OS denial; unrelated errors and printed words do not pass.
 if(item.exit_code===1&&['Operation not permitted','Permission denied'].some(message=>output===`cat: ${expected.target}: ${message}\n`))return result('denied','bound_terminal_os_denial',[item.id]);
 return result('tool_environment_error','non_denial_failure',[item.id]);
}
