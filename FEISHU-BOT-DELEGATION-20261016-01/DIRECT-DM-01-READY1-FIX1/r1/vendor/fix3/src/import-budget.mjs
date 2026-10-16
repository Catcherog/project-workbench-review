import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {ExecutionBudget} from './budget.mjs';
const known=JSON.parse(await fs.readFile(new URL('../evidence/round-budget.json',import.meta.url),'utf8'));
const d=new ExecutionBudget(fileURLToPath(new URL('../runtime/model-budget.sqlite',import.meta.url)),known);
console.log({...d.status(),roundLimit:20,incrementalLimit:4,concurrency:1});d.close();
