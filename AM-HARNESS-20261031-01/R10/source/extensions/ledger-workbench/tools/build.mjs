import {build} from 'esbuild';
import {mkdir} from 'node:fs/promises';
await mkdir('dist',{recursive:true});
await build({entryPoints:['demo/main.tsx'],bundle:true,outfile:'dist/ledger-demo.js',platform:'browser',target:['es2022'],format:'iife',minify:true,
  sourcemap:true,define:{'process.env.NODE_ENV':'"production"'},legalComments:'eof'});
console.log('Built React demo bundle; production mounts web/LedgerWorkbench.tsx inside the existing WB host.');
