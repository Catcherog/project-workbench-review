import { build } from 'esbuild';
import { mkdirSync, writeFileSync, copyFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('..', import.meta.url));
const out = path.join(root, 'dist-local');
mkdirSync(path.join(out, 'client'), {recursive:true});
await build({absWorkingDir:root,entryPoints:['lib/local-runtime.ts'],bundle:true,platform:'node',format:'esm',target:'node24',outfile:path.join(out,'domain.mjs'),sourcemap:true});
await build({absWorkingDir:root,entryPoints:['app/local-entry.tsx'],bundle:true,platform:'browser',format:'esm',target:['safari16','chrome110'],jsx:'automatic',outfile:path.join(out,'client/app.js'),minify:true,sourcemap:true,define:{'process.env.NODE_ENV':'"production"'},loader:{'.svg':'dataurl'}});
writeFileSync(path.join(out,'client/index.html'),'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>推进 · 本地项目工作台</title><link rel="icon" href="/favicon.svg"><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script type="module" src="/app.js"></script></body></html>');
for (const asset of ['favicon.svg', 'app-icon.svg']) {
  if (existsSync(path.join(root, 'public', asset))) copyFileSync(path.join(root, 'public', asset), path.join(out, 'client', asset));
}
console.log('本地应用已构建：'+out+'（React / TypeScript / SQLite，无网络运行依赖）');
