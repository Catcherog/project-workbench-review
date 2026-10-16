import {readdirSync,readFileSync,writeFileSync} from 'node:fs';
import {resolve,relative} from 'node:path';
import {digest} from '../dm/candidate/scripts/direct-dm-authority.mjs';
const root=resolve(import.meta.dirname,'../dm/candidate');
const files=[];
function visit(dir){for(const entry of readdirSync(dir,{withFileTypes:true})){const file=resolve(dir,entry.name);if(entry.isDirectory())visit(file);else if((file.endsWith('.mjs')&&!entry.name.endsWith('.fixture.mjs')&&!entry.name.startsWith('test-'))||entry.name==='release.json')files.push({path:relative(root,file),sha256:digest(readFileSync(file,'utf8'))});}}
visit(root);files.sort((a,b)=>a.path.localeCompare(b.path));
const manifest={version:1,files};writeFileSync(resolve(root,'build-manifest.json'),JSON.stringify(manifest,null,2)+'\n');console.log(JSON.stringify({buildHash:digest(manifest),files:files.length}));
