import {createHash} from 'node:crypto';
import {createLedgerHandler} from '../../server/ledger-handler.mjs';
import {SignedQueueBridge} from '../../server/queue-bridge.mjs';
import {LedgerError} from '../../server/errors.mjs';
import {open} from 'node:fs/promises';
import {constants} from 'node:fs';

const ALLOWED_SCOPES=new Set(['ledger:read','am:prepare','am:approve','review:resolve','reminder:manage']);

export async function loadNativeLedgerOptions(configPath) {
  const file=await open(configPath,constants.O_RDONLY|(constants.O_NOFOLLOW||0));
  try{
    const info=await file.stat();
    if(!info.isFile()||(info.mode&0o077)||info.size>16384||(process.getuid&&info.uid!==process.getuid()))
      throw new LedgerError('unsafe_ledger_config','台账接入配置的权限不正确。',503);
    const config=JSON.parse(await file.readFile('utf8'));
    if(!config||typeof config!=='object'||Array.isArray(config))throw new LedgerError('invalid_ledger_config','台账接入配置无效。',503);
    return config;
  }finally{await file.close();}
}

/** Native pm-workbench adapter for scripts/local-http.mjs.
 * `authorize` is the ORIGINAL closure: token + Origin + uiOnly checks.
 * `binding`/getBinding is server-owned, never request JSON or query parameters.
 */
export async function createNativeLedgerMount({authorize,store,sessionNonce,isRestoring=()=>false,options={}}) {
  if(options.enabled===undefined&&process.env.PM_LEDGER_CONFIG)options=await loadNativeLedgerOptions(process.env.PM_LEDGER_CONFIG);
  if(options.enabled!==true)return async()=>false;
  if(typeof authorize!=='function'||!store?.load||!sessionNonce)throw new Error('Original WB host authorization is required');
  const bridge=options.bridge || await new SignedQueueBridge({queueDir:options.queueDir,keyFile:options.keyFile}).init();
  const getBinding=options.getBinding || (()=>options.binding);
  const clock=options.clock||Date.now;
  async function getSession(req) {
    authorize(req,true);
    const binding=await getBinding();
    if(!binding || !['userId','tenantId','workspaceId'].every(k=>typeof binding[k]==='string'&&binding[k]))
      throw new LedgerError('principal_binding_required','当前工作区尚未完成 AM 身份绑定。',503);
    const state=store.load(binding.workspaceId);
    if(!state || state.workspaceId!==binding.workspaceId)throw new LedgerError('workspace_binding_changed','当前工作区绑定已变化。',409);
    const projectIds=options.resolveProjectIds ? await options.resolveProjectIds({state,binding}) : binding.projectIds;
    if(!Array.isArray(projectIds)||projectIds.some(id=>typeof id!=='string'||!id))throw new LedgerError('project_scope_required','尚未取得项目授权范围。',503);
    const scopes=(binding.scopes||[]).filter(scope=>ALLOWED_SCOPES.has(scope));
    if(!scopes.includes('ledger:read'))throw new LedgerError('ledger_read_disabled','此工作区尚未开放台账读取。',403);
    return {verified:true,id:createHash('sha256').update(JSON.stringify([sessionNonce,binding.userId,binding.tenantId,binding.workspaceId,projectIds,scopes])).digest('hex'),
      userId:binding.userId,tenantId:binding.tenantId,workspaceId:binding.workspaceId,projectIds,scopes,
      expiresAtMs:clock()+600000};
  }
  return createLedgerHandler({bridge,getSession,clock,authorizeMutation(req){
    authorize(req,true);
    if(isRestoring())throw new LedgerError('workspace_restoring','工作区正在恢复，请稍后继续。',409);
  }});
}
