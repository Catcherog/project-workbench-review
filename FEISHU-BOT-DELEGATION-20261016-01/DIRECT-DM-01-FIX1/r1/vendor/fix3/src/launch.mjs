import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {cleanEnv} from './process.mjs';
export const hash=x=>createHash('sha256').update(typeof x==='string'||Buffer.isBuffer(x)?x:JSON.stringify(x)).digest('hex');
export function permissionArgs(jobDir){
 const p={':root':'deny',':minimal':'read',[resolve(jobDir)]:'read'};
 return ['-c','default_permissions="probe"','-c','permissions.probe.filesystem={'+Object.entries(p).map(([k,v])=>JSON.stringify(k)+'='+JSON.stringify(v)).join(',')+'}','-c','permissions.probe.network.enabled=false'];
}
export function buildLaunch({binary,prefixArgs=[],jobDir,outputFile,schemaFile,model='gpt-6-astra',effort='max',executionKind='real-model'}){
 const disabled=['apps','plugins','remote_plugin','browser_use','browser_use_external','in_app_browser','computer_use','multi_agent','multi_agent_v2','memories','chronicle','hooks','skill_search','skill_mcp_dependency_install','image_generation','view_image','sleep_tool'];
 const overrides=[...permissionArgs(jobDir),'-c','approval_policy="never"','-c','project_doc_max_bytes=0','-c','mcp_servers={}','-c','web_search="disabled"','-c','features.skip_host_skill_discovery=true','-c','shell_environment_policy.inherit="none"','-c','shell_environment_policy.set={PATH="/usr/bin:/bin:/usr/sbin:/sbin"}','-c','model_reasoning_effort='+JSON.stringify(effort),'-m',model,...disabled.flatMap(f=>['--disable',f])];
 const args=[...prefixArgs,'exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check','--json','--color','never','-C',resolve(jobDir),...overrides,'--output-schema',schemaFile,'--output-last-message',outputFile,'-'];
 const env=cleanEnv(),environmentNames=Object.keys(env).sort(),cwd=resolve(jobDir);
 const permissionFingerprint=hash(permissionArgs(jobDir));
 const descriptor={binary,prefixArgs,args,cwd,model,effort,executionKind,environmentNames,homeSource:env.HOME?'inherited_from_operator':'unset',codexHomeSource:env.CODEX_HOME?'explicit':'Codex default under operator HOME',environmentFingerprint:hash(env),permissionFingerprint,disabled,personalBootstrapIsolation:'NOT_PROVEN',commandSandbox:'named_profile_restricted_reads_network_off',externalTools:'disabled_by_flags_not_independent_account'};
 return {binary,args,cwd,env,descriptor,fingerprint:hash(descriptor)};
}
