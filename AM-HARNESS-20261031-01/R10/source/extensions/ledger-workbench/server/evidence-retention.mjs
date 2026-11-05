/** Remove expired raw quotations at the final presentation boundary.
 * Structured facts and business history retain their own native retention rules.
 */
export function sanitizeEvidence(value,now=Date.now()) {
  if(Array.isArray(value))return value.map(v=>sanitizeEvidence(v,now));
  if(!value||typeof value!=='object')return value;
  const out=Object.fromEntries(Object.entries(value).map(([k,v])=>[k,sanitizeEvidence(v,now)]));
  const expiry=typeof out.rawExpiresAt==='string'?Date.parse(out.rawExpiresAt):out.raw_expires_at_ms;
  if(Number.isFinite(expiry)&&expiry<=now){
    if(Object.hasOwn(out,'quote'))out.quote=null;
    if(Object.hasOwn(out,'rawAvailable'))out.rawAvailable=false;
    if(Object.hasOwn(out,'raw_available'))out.raw_available=false;
  }
  const evidenceUnavailable=Array.isArray(out.evidence)&&out.evidence.some(ref=>ref?.rawAvailable===false ||
    (typeof ref?.rawExpiresAt==='string'&&Date.parse(ref.rawExpiresAt)<=now));
  if(out.status==='pending' && typeof out.excerpt==='string' &&
      ((Number.isFinite(out.expiresAtMs)&&out.expiresAtMs<=now)||evidenceUnavailable)){
    out.excerpt='原文暂不可用，请刷新来源后再处理';out.choices=[];
  }
  if(out.retentionBoundExcerpt===true&&(!Array.isArray(out.sourceRefs)||!out.sourceRefs.some(ref=>
      ref?.rawAvailable===true&&typeof ref.quote==='string'))){
    if(Object.hasOwn(out,'text'))out.text='原文暂不可用，待刷新';
    if(Object.hasOwn(out,'value'))out.value='原文暂不可用，待刷新';
    out.rawExcerptUnavailable=true;
  }
  // A summary row also contains a joined copy of its entries' text.
  if(Array.isArray(out.entries)&&out.entries.some(entry=>entry?.rawExcerptUnavailable===true)){
    out.text=out.entries.map(entry=>entry.text).join('；');
  }
  return out;
}
