// Read-only comparison. This deliberately offers no apply/install/restart mode.
import {readFileSync,existsSync,realpathSync} from 'node:fs';
import {resolve,join,relative} from 'node:path';
import {createHash} from 'node:crypto';
const hash=b=>createHash('sha256').update(b).digest('hex'),base=realpathSync(process.argv[2]),root=resolve(import.meta.dirname,'../install-candidate'),plan=JSON.parse(readFileSync(join(root,'INSTALL_PLAN.json'),'utf8'));
const results=plan.changes.map(r=>{if(r.path.startsWith('/')||r.path.split('/').includes('..'))throw Error('INVALID_PATH');const f=join(base,r.path),present=existsSync(f);if(present&&relative(base,realpathSync(f)).startsWith('..'))throw Error('SYMLINK_OUTSIDE_TARGET');return {path:r.path,baseMatches:(present?hash(readFileSync(f)):null)===r.expectedBeforeSha256,payloadMatches:hash(readFileSync(join(root,'payload',r.path)))===r.candidateSha256};});
console.log(JSON.stringify({readOnly:true,results,allMatch:results.every(r=>r.baseMatches&&r.payloadMatches)},null,2));if(results.some(r=>!r.baseMatches||!r.payloadMatches))process.exitCode=1;
