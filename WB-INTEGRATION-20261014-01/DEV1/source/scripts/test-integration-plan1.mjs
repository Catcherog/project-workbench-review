/** Isolated contract tests, no package install, browser, model, server or external write. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
function findTypeScript() {
  try { return {api: require('typescript'), bin: require.resolve('typescript/bin/tsc')}; } catch { /* Check an already installed global compiler, without installing. */ }
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    const candidate = path.join(dir, process.platform === 'win32' ? 'tsc' : 'tsc');
    try {
      const bin = fs.realpathSync(candidate), pkg = path.resolve(path.dirname(bin), '..');
      return {api: require(pkg), bin};
    } catch { /* continue */ }
  }
  throw new Error('An existing TypeScript compiler is required. No dependencies were installed.');
}
const ts = findTypeScript(), out = fs.mkdtempSync(path.join(os.tmpdir(), 'wb-plan1-contracts-'));
try {
  const files = ['core-collaboration-model.ts','core-collaboration-client.ts','receipt-presentation.ts'].map(f => path.join(root,'app/integration',f));
  const checked = spawnSync(process.execPath,[ts.bin,'--strict','--target','ES2022','--module','commonjs','--lib','ES2022,DOM','--skipLibCheck','--outDir',out,...files],{encoding:'utf8'});
  process.stdout.write(checked.stdout || ''); process.stderr.write(checked.stderr || '');
  if (checked.status !== 0) throw new Error('Strict typecheck of actual pure TS modules failed.');
  console.log('PASS: strict typecheck of 3 actual pure TypeScript modules.');
  for (const name of ['core-collaboration-panel.tsx','receipt-heading.tsx']) {
    const code = fs.readFileSync(path.join(root,'app/integration',name),'utf8');
    const result = ts.api.transpileModule(code,{fileName:name,reportDiagnostics:true,compilerOptions:{target:ts.api.ScriptTarget.ES2022,module:ts.api.ModuleKind.CommonJS,jsx:ts.api.JsxEmit.ReactJSX}});
    const errors = (result.diagnostics || []).filter(d => d.category === ts.api.DiagnosticCategory.Error);
    if (errors.length) throw new Error(errors.map(d => ts.api.flattenDiagnosticMessageText(d.messageText,'\n')).join('\n'));
  }
  console.log('PASS: TSX syntax/transpilation for 2 actual components (NOT full React typecheck/rendering).');
  const tests = spawnSync(process.execPath,['--test',path.join(root,'tests/integration/plan1-contracts.test.cjs')],{
    encoding:'utf8',env:{...process.env,WB_PLAN1_COMPILED:out,WB_PLAN1_SOURCE_ROOT:root},
  });
  process.stdout.write(tests.stdout || ''); process.stderr.write(tests.stderr || '');
  process.exitCode = tests.status ?? 1;
} finally { fs.rmSync(out,{recursive:true,force:true}); }
