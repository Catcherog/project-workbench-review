import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [sourcePath,outputPath]=process.argv.slice(2);
if(!sourcePath||!outputPath)throw new Error('Usage: node tools/make-wb-patch.mjs CURRENT/scripts/local-http.mjs OUTPUT.patch');
const original=await readFile(sourcePath,'utf8');
if(original.includes('createNativeLedgerMount'))throw new Error('Ledger mount already exists; inspect it instead of applying twice.');
const importAnchor="import {WorkbenchRules} from './workbench-rules.mjs';";
const handleAnchor='  async function handle(req,res) {';
const routeAnchor="    if(p==='/api/v2/core'){";
for(const anchor of [importAnchor,handleAnchor,routeAnchor])if(original.split(anchor).length!==2)throw new Error('Host anchor absent or ambiguous: '+anchor);
if(!original.includes('function authorize(req,uiOnly=false)')||!original.includes("if(uiOnly&&client==='codex')"))
  throw new Error('Original UI-only authorization must be inspected before mounting.');
const candidate=original.replace(importAnchor,importAnchor+"\nimport {createNativeLedgerMount} from '../extensions/ledger-workbench/integrations/wb/native-mount.mjs';")
  .replace(handleAnchor,"  const ledgerRoute=await createNativeLedgerMount({authorize,store,sessionNonce:token,isRestoring:()=>!!restoreInFlight,options:options.ledgerWorkbench||{}});\n"+handleAnchor)
  .replace(routeAnchor,"    if(p.startsWith('/api/v2/ledger/')){if(await ledgerRoute(req,res))return;}\n"+routeAnchor);
const temp=await mkdtemp(join(tmpdir(),'wb-ledger-patch-'));
try{
  await writeFile(join(temp,'before'),original);await writeFile(join(temp,'after'),candidate);
  const diff=spawnSync('diff',['-u','--label','a/scripts/local-http.mjs','--label','b/scripts/local-http.mjs',join(temp,'before'),join(temp,'after')],{encoding:'utf8'});
  if(![0,1].includes(diff.status))throw new Error(diff.stderr||'diff failed');
  await writeFile(outputPath,diff.stdout);
  const sha=text=>createHash('sha256').update(text).digest('hex');
  console.log(JSON.stringify({source:sourcePath,output:outputPath,beforeSha256:sha(original),afterSha256:sha(candidate),sourceModified:false}));
}finally{await rm(temp,{recursive:true,force:true});}
