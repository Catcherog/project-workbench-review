// Candidate read-only aggregation contract. The original matrix source is not
// available; this module deliberately does not impersonate its component API.
export const F = Object.freeze({parent:'field_f34a5f', person:'field_4ede40', period:'field_036afd', hours:'field_3a677c', registration:'field_fe8c78', note:'field_9d3b78', total:'field_896a57', ownership:'field_2c4f5a'});
const DAY=86400000, OFFSET=8*3600000;
const STATES=new Set(['ok','no_records','permission_denied','request_failed','pagination_incomplete','mapping_unverified']);
const copy=x=>structuredClone(x);
const canonical=x=>JSON.stringify(x,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
function id(x,label){if(typeof x!=='string'||!x.trim())throw new Error(`invalid_${label}`);return x;}
function field(fields,key,required=false){
  if(!Array.isArray(fields))throw new Error('invalid_fields');
  const found=fields.filter(f=>f.key===key);
  if(found.length>1)throw new Error(`duplicate_field:${key}`);
  if(required&&found.length!==1)throw new Error(`missing_field:${key}`);
  return found[0]?.value;
}
export function decimal(value){
  // Preserve source decimal hours, with no binary floating point accumulation.
  if(typeof value!=='string'||!/^\d+(?:\.\d+)?$/.test(value)||value.length>100)throw new Error('invalid_decimal_hours');
  let [a,b='']=value.split('.');a=a.replace(/^0+(?=\d)/,'');b=b.replace(/0+$/,'');
  return b?`${a}.${b}`:a;
}
export function sumHours(values){
  const ds=values.map(decimal), scale=Math.max(0,...ds.map(s=>(s.split('.')[1]||'').length));
  const units=ds.reduce((n,s)=>{const[a,b='']=s.split('.');return n+BigInt(a+b.padEnd(scale,'0'));},0n);
  const v=units.toString().padStart(scale+1,'0');
  return decimal(scale?`${v.slice(0,-scale)}.${v.slice(-scale)}`:v);
}
function instant(v){
  if(!v||!Number.isSafeInteger(v.timestamp))throw new Error('invalid_timestamp');
  const parsed=v.iso_time?Date.parse(v.iso_time):null;
  if(parsed!==null&&(!Number.isFinite(parsed)||Math.abs(parsed-v.timestamp)>999))throw new Error('timestamp_iso_mismatch');
  return v.timestamp;
}
function localDate(ms){return new Date(ms+OFFSET).toISOString().slice(0,10);}
export function periodAt(ms,mode){
  if(!Number.isSafeInteger(ms))throw new Error('invalid_timestamp');
  const shifted=new Date(ms+OFFSET), dayStart=Date.UTC(shifted.getUTCFullYear(),shifted.getUTCMonth(),shifted.getUTCDate())-OFFSET;
  let start,end;
  if(mode==='week'){start=dayStart-((shifted.getUTCDay()+6)%7)*DAY;end=start+7*DAY;}
  else if(mode==='month'){start=Date.UTC(shifted.getUTCFullYear(),shifted.getUTCMonth(),1)-OFFSET;end=Date.UTC(shifted.getUTCFullYear(),shifted.getUTCMonth()+1,1)-OFFSET;}
  else throw new Error('invalid_period_mode');
  return {key:mode==='week'?localDate(start):localDate(start).slice(0,7), startInclusive:start,endExclusive:end,label:mode==='week'?`${localDate(start)}—${localDate(end-1)}`:localDate(start).slice(0,7),timeZone:'Asia/Shanghai'};
}
function provenance(a,rowId){return {space:id(a.owned_project?.key,'space'),type:id(a.work_item_type?.key,'type'),workItemId:id(a.work_item_id,'workitem_id'),parentField:F.parent,rowId};}
function sourceKey(source){return canonical(source);}
function versionOf(response){
  const updated=field(response.work_item_fields,'updated_at');
  // Only use the server timestamp, never the local read time, to order versions.
  if(updated)return instant(updated);
  const iso=response.work_item_attribute?.update_time;
  if(!iso)return null;
  const ms=Date.parse(iso);return Number.isFinite(ms)?ms:null;
}
function ownerOf(response){
  const raw=field(response.work_item_fields,F.ownership);
  // Preserve the exact source label. Never infer a project from the title.
  return {label:typeof raw?.label==='string'?raw.label:null,value:typeof raw?.value==='string'?raw.value:null,projectRef:null,projectMapping:'unverified'};
}
export function normalize(snapshot){
  const {response,readAt}=snapshot;
  if(!Number.isFinite(Date.parse(readAt)))throw new Error('invalid_read_time');
  const a=response?.work_item_attribute;
  if(!a)throw new Error('missing_workitem_identity');
  const source=provenance(a,undefined), sourceId=sourceKey(source), version=versionOf(response), rows=[],issues=[];
  const group=field(response.work_item_fields,F.parent,true);
  if(group!==null&&!Array.isArray(group))throw new Error('invalid_compound_rows');
  const complete=snapshot.complete===true&&response.pagination?.has_more!==true;
  for(const [index,cells] of (group||[]).entries()){
    try{
      const rowId=id(field(cells,'group_uuid',true),'row_id'), person=field(cells,F.person,true), schedule=field(cells,F.period,true);
      const start=instant(schedule?.start_time), end=instant(schedule?.end_time);
      if(end<start||!Number.isSafeInteger(end+1))throw new Error('invalid_interval');
      const rowSource=provenance(a,rowId);
      const sourceHours=field(cells,F.hours,true);
      rows.push({key:sourceKey(rowSource),source:rowSource,person:{namespace:'feishu-project-user-key',id:id(person?.key,'person_id'),name:typeof person.name==='string'?person.name:null},startInclusive:start,endInclusive:end,endExclusive:end+1,sourcePeriod:copy(schedule),sourceHours,hours:decimal(sourceHours),registrationId:id(field(cells,F.registration,true),'registration_id'),note:field(cells,F.note)||null,ownership:ownerOf(response),readAt,version,kind:'actual',sourceTitle:a.work_item_name||null});
    }catch(e){issues.push({sourceId,rowIndex:index,code:e.message});}
  }
  return {sourceId,source,rows,issues,complete,readAt,version,reconciliationOnly:field(response.work_item_fields,F.total)??null,identity:a.work_item_name};
}
function semanticRow(row){const {readAt,version,...business}=row;return canonical(business);}
function semanticSnapshot(snapshot){return canonical({complete:snapshot.complete,rows:snapshot.rows.map(semanticRow).sort(),issues:snapshot.issues});}
function chooseVersion(versions,semantic){
  if(versions.length===1)return {value:versions[0]};
  const contents=new Set(versions.map(semantic));
  if(contents.size===1){
    return {value:[...versions].sort((a,b)=>(b.version??-Infinity)-(a.version??-Infinity)||Date.parse(b.readAt)-Date.parse(a.readAt))[0]};
  }
  if(versions.some(v=>v.version===null))return {conflict:'unversioned_conflict'};
  const latest=Math.max(...versions.map(v=>v.version));
  const candidates=versions.filter(v=>v.version===latest);
  if(new Set(candidates.map(semantic)).size!==1)return {conflict:'same_version_conflict'};
  return {value:candidates[0]};
}
function groupBy(values,key){const m=new Map();for(const v of values){const k=key(v);if(!m.has(k))m.set(k,[]);m.get(k).push(v);}return m;}
export function aggregate(snapshots,{mode='week',coverage=[],people=[],periods=[]}={}){
  const errors=[],normalized=[],sourceStatuses=[],rows=[];
  for(const s of snapshots){try{normalized.push(normalize(s));}catch(e){errors.push({code:e.message,source:s.sourceHint||null});}}
  // Choose a whole snapshot first. A newer complete snapshot can remove rows;
  // unioning historic rows would silently retain deleted records forever.
  for(const [sourceId,versions] of groupBy(normalized,s=>s.sourceId)){
    const chosen=chooseVersion(versions,semanticSnapshot);
    if(chosen.conflict){errors.push({code:chosen.conflict,sourceId});sourceStatuses.push({sourceId,status:'conflict'});continue;}
    const s=chosen.value;errors.push(...s.issues);
    sourceStatuses.push({sourceId,status:!s.complete?'pagination_incomplete':s.issues.length?'partial':s.rows.length?'ok':'no_records',readAt:s.readAt});
    for(const [key,duplicates] of groupBy(s.rows,r=>r.key)){
      const row=chooseVersion(duplicates,semanticRow);
      if(row.conflict)errors.push({code:row.conflict,key});else rows.push(row.value);
    }
  }
  const external=coverage.map(c=>{
    if(!STATES.has(c.status))throw new Error('invalid_coverage_state');
    return copy(c);
  });
  const cells=new Map(), pending=[],crossSourceCandidates=[];
  // Same registration at different locators is only a possible duplicate.
  // Quarantine it until an explicit relation resolves the ambiguity.
  const ambiguous=new Set();
  for(const [registration,rs] of groupBy(rows,r=>r.registrationId)){
    if(new Set(rs.map(r=>r.key)).size>1){
      crossSourceCandidates.push({registration,keys:rs.map(r=>r.key)});rs.forEach(r=>ambiguous.add(r.key));
    }
  }
  function ensure(person,period){
    const key=canonical([person.namespace,person.id,mode,period.key]);
    if(!cells.has(key))cells.set(key,{key,person:copy(person),period:copy(period),kind:'actual',unit:'hour',hours:null,rows:[],pending:[],valueState:'no_records'});
    return cells.get(key);
  }
  for(const person of people){id(person.id,'person_id');id(person.namespace,'person_namespace');for(const ms of periods)ensure(person,periodAt(ms,mode));}
  for(const row of rows){
    const period=periodAt(row.startInclusive,mode), last=periodAt(row.endInclusive,mode);
    let reason=null;
    if(ambiguous.has(row.key))reason='cross_source_duplicate_unresolved';
    else if(period.key!==last.key)reason=mode==='week'?'cross_week_unallocated':'cross_month_unallocated';
    if(reason){
      const item={reason,row};pending.push(item);
      // Keep a pending warning on every overlapping period, without allocating
      // any hours. Long spans are rejected rather than expanding unboundedly.
      let cursor=period.startInclusive, count=0;
      while(cursor<=row.endInclusive&&count++<370){const p=periodAt(cursor,mode);ensure(row.person,p).pending.push({rowKey:row.key,reason});cursor=p.endExclusive;}
      if(cursor<=row.endInclusive)errors.push({code:'interval_too_large',key:row.key});
      continue;
    }
    ensure(row.person,period).rows.push(row);
  }
  const coverageGaps=[...sourceStatuses.filter(s=>s.status!=='ok'),...external.filter(c=>c.status!=='ok'),...errors.map(e=>({status:'invalid_or_conflict',...e}))];
  for(const cell of cells.values()){
    if(cell.rows.length){cell.hours=sumHours(cell.rows.map(r=>r.hours));cell.valueState=cell.hours==='0'?'explicit_zero':'recorded';}
    if(cell.pending.length)cell.valueState=cell.rows.length?'recorded_with_pending':'pending';
    cell.coverage='covered_sources_only';
    cell.coverageGaps=copy(coverageGaps);
    cell.caption='已覆盖来源小计；不代表该人员全部实际投入';
    cell.nonProjectItemCount=new Set(cell.rows.filter(r=>r.ownership.label==='非项目').map(r=>r.source.workItemId)).size;
    cell.projectCount=null; // No verified project identity mapping in this probe.
  }
  return {contract:'candidate-actual-aggregate/v1',componentBinding:'unverified',timeZone:'Asia/Shanghai',mode,unit:'hour',cells:[...cells.values()].sort((a,b)=>a.person.id.localeCompare(b.person.id)||a.period.startInclusive-b.period.startInclusive),pending,errors,crossSourceCandidates,sourceStatuses,coverage:external,coverageGaps,rowsRead:rows.length};
}
