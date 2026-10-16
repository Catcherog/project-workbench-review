import {existsSync,readFileSync,statSync,realpathSync} from 'node:fs';
import path from 'node:path';
import {homedir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
const projectRoot=fileURLToPath(new URL('..',import.meta.url)),verified=new Map();
export function cliRuntime(kind,{root=projectRoot,env=process.env,home=homedir()}={}){
  if(!['lark','meegle'].includes(kind))throw Error('未知 CLI 类型');
  const explicit=kind==='lark'?env.PM_LARK_CLI:env.PM_MEEGLE_BIN||env.PM_MEEGLE_CLI;
  if(explicit)return {path:explicit,source:'explicit'};
  if(kind==='meegle'){const local=path.join(home,'.local/bin/meegle');return {path:existsSync(local)?local:'meegle',source:existsSync(local)?'user-install':'PATH'};}
  const manifest=path.join(root,'.sites-runtime/tools/manifest.json');
  if(existsSync(manifest)){
    const m=JSON.parse(readFileSync(manifest,'utf8')),tool=m.tools?.lark;
    if(m.schemaVersion!==1||!tool||typeof tool.path!=='string'||!/^bin\/[-\w.]+$/.test(tool.path)||! /^[a-f0-9]{64}$/.test(tool.sha256||''))throw Error('受管飞书 CLI 登记无效');
    const folder=realpathSync(path.dirname(manifest)),file=realpathSync(path.join(folder,tool.path));if(!file.startsWith(folder+path.sep))throw Error('受管 CLI 路径超出范围');
    const st=statSync(file),key=[file,st.size,st.mtimeMs,st.ctimeMs,tool.sha256].join(':');
    if(!verified.has(key)){if(createHash('sha256').update(readFileSync(file)).digest('hex')!==tool.sha256)throw Error('受管飞书 CLI 指纹已变化');verified.clear();verified.set(key,true);}
    return {path:file,source:'managed',version:tool.version,sha256:tool.sha256};
  }
  const legacy=path.join(root,'tmp/lark-cli-runtime/node_modules/@larksuite/cli/bin/lark-cli');
  return {path:existsSync(legacy)?legacy:'lark-cli',source:existsSync(legacy)?'legacy-fallback':'PATH'};
}
export const resolveLarkCli=options=>cliRuntime('lark',options).path;
export const resolveMeegleCli=options=>cliRuntime('meegle',options).path;
