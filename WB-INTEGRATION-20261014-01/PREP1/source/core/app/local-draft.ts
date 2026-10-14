/** Unsubmitted input only. Never restores an approval, identity or execution token. */
export function readInputDraft<T>(key:string,fallback:T):T{
  if(typeof window==='undefined')return fallback;
  try{
    const raw=localStorage.getItem('pm-input-draft:'+key);if(!raw||raw.length>24000)return fallback;
    const value=JSON.parse(raw);if(value?.version!==1)return fallback;
    if(typeof fallback==='string')return typeof value.input==='string'?value.input as T:fallback;
    if(fallback&&typeof fallback==='object'&&!Array.isArray(fallback)&&value.input&&typeof value.input==='object'&&!Array.isArray(value.input))return Object.fromEntries(Object.entries(fallback).map(([field,initial])=>[field,typeof value.input[field]===typeof initial?value.input[field]:initial])) as T;
    return fallback;
  }catch{return fallback;}
}
export function writeInputDraft(key:string,input:unknown){
  try{const raw=JSON.stringify({version:1,input});if(raw.length<=24000)localStorage.setItem('pm-input-draft:'+key,raw);}catch{/* The input remains in the current form when storage is unavailable. */}
}
export function clearInputDraft(key:string){try{localStorage.removeItem('pm-input-draft:'+key);}catch{/* No execution state depends on this cache. */}}
