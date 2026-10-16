import {homedir} from 'node:os';
import {resolve,join} from 'node:path';
import {buildLaunch,hash} from './launch.mjs';
export const extraDisabled=['shell_snapshot','workspace_dependencies','daemon_auto_start','code_mode_host','unbounded_connection_retries','goals'];
// The trusted CLI parent may read existing auth, but not user configuration, memory,
// skills, history or business files. Its model-generated tools retain the inner profile.
export function bootstrapPolicy(runtimeRoot){
 return ['(version 1)','(allow default)','(deny file-read* file-write* (subpath "/Users"))',
  `(allow file-read* file-write* (subpath ${JSON.stringify(resolve(runtimeRoot))}))`,
  `(allow file-read* (literal ${JSON.stringify(join(homedir(),'.codex','auth.json'))}))`].join('\n');
}
export function buildRoleLaunch(options){
 const {runtimeRoot,bootstrapFile,instructions}=options;
 const launch=buildLaunch(options);
 const overrides=['-c','developer_instructions='+JSON.stringify(instructions),'-c','allow_login_shell=false',
  '-c','sqlite_home='+JSON.stringify(join(runtimeRoot,'state')),'-c','log_dir='+JSON.stringify(join(runtimeRoot,'logs')),
  ...extraDisabled.flatMap(x=>['--disable',x])];
 const args=[...launch.args.slice(0,-1),...overrides,'-'];
 const descriptor={...launch.descriptor,args,disabled:[...launch.descriptor.disabled,...extraDisabled],personalBootstrapIsolation:'scoped_parent_seatbelt_plus_tool_profile',parentPolicySha256:hash(bootstrapPolicy(runtimeRoot)),stateScope:resolve(runtimeRoot),instructionsSha256:hash(instructions),wrapper:'/usr/bin/sandbox-exec'};
 return {binary:'/usr/bin/sandbox-exec',args:['-f',bootstrapFile,options.binary,...args],cwd:launch.cwd,env:launch.env,descriptor,fingerprint:hash(descriptor)};
}
