import {AsyncLocalStorage} from 'node:async_hooks';
const executions=new AsyncLocalStorage();
// This channel carries controller callbacks, never JSONL/model/message content.
export const withinExecution=(record,fn)=>executions.run(record,fn);
export function recordExecution(event){return executions.getStore()?.(event)??true;}
