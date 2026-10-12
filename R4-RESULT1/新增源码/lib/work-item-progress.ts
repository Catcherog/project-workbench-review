import type {Item} from './domain';
import type {V2State} from './v2-types';

export type TimeChoice = {state:'scheduled'|'pending'|'clear'|'unchanged';date?:string;time?:string;zone?:string;quote?:string};
export type TimeNode = TimeChoice & {precision?:'date'|'minute';effectiveAt?:string;origin?:string;at?:string;defaultTime?:string;completedAt?:string;needsReview?:boolean;reviewReason?:string};
export type EntryPlan = {intent:'record'|'discuss'|'mixed'|'clarify'|'other';progress:string;progressQuote:string;waitingFor:string;waitingResult:string;waitingQuote:string;checkCompleted:boolean;checkQuote:string;riskDecision:'none'|'confirmed'|'resolved'|'dismissed';riskQuote:string;followup:'unchanged'|'continue'|'end'|'cancel';followupQuote:string;check:TimeChoice;completion:TimeChoice;clarification:string};
export type EntryInput = {text:string;occurredAt:string;editProgressId?:string;manual?:{check?:TimeChoice;completion?:TimeChoice};resolution?:{check?:'text'|'manual';completion?:'text'|'manual';followup?:'continue'|'end'}};
export type EntryChanges={progress?:{text:string;quote:string;editId?:string};waiting?:{who:string;result:string;quote:string};checkCompleted?:string;riskDecision?:'confirmed'|'resolved'|'dismissed';riskQuote?:string;followup?:'continue'|'end'|'cancel';followupQuote?:string;check?:TimeNode;completion?:TimeNode};
export type EntryConflict={field:string;message:string;text?:TimeNode;manual?:TimeNode};
const same=(a:unknown,b:unknown)=>JSON.stringify(a??null)===JSON.stringify(b??null);
const fail=(message:string)=>{throw Object.assign(new Error(message),{status:422});};
export const shanghaiDay=(at:string|number=Date.now())=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(at));
function validDate(date:unknown){return typeof date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(date)&&Number.isFinite(Date.parse(date+'T12:00:00Z'))&&new Date(date+'T12:00:00Z').toISOString().slice(0,10)===date;}
export function normalizeTime(value:TimeChoice,origin:string,at:string):TimeNode {
  if(!value||!['scheduled','pending','clear','unchanged'].includes(value.state))fail('时间选择无效');
  if(value.state!=='scheduled')return {state:value.state,origin,quote:value.quote||'',at};
  if(!validDate(value.date)||value.time&&!/^([01]\d|2[0-3]):[0-5]\d$/.test(value.time))fail('请使用有效日期和时刻');
  const zone=value.zone||'Asia/Shanghai',offset=zone==='Asia/Shanghai'?'+08:00':zone==='UTC'?'Z':zone;
  if(!/^(Z|[+-](?:0\d|1[0-4]):[0-5]\d)$/.test(offset))fail('时间需要明确的时区');
  return {state:'scheduled',date:value.date,time:value.time||'',zone,precision:value.time?'minute':'date',origin,quote:value.quote||'',at,
    ...(value.time?{effectiveAt:new Date(value.date+'T'+value.time+':00'+offset).toISOString()}:{} )};
}
const comparable=(t:TimeNode)=>[t.state,t.date||'',t.time||'',t.zone||'Asia/Shanghai'];
export function combineEntry(plan:EntryPlan,input:EntryInput){
  const changes:EntryChanges={},conflicts:EntryConflict[]=[];
  const grounded=(quote:string)=>typeof quote==='string'&&!!quote.trim()&&input.text.includes(quote);
  if(!plan||!['record','discuss','mixed','clarify','other'].includes(plan.intent))fail('事项理解格式无效');
  if(!Number.isFinite(Date.parse(input.occurredAt)))fail('输入发生时间无效');
  if(plan.progress){if(!grounded(plan.progressQuote)||plan.progress.length>4000)fail('进展缺少本次输入的原话');changes.progress={text:plan.progress,quote:plan.progressQuote,...(input.editProgressId?{editId:input.editProgressId}:{})};}
  if(plan.waitingFor||plan.waitingResult){if(!grounded(plan.waitingQuote)||!plan.waitingFor||!plan.waitingResult)conflicts.push({field:'waiting',message:'请明确等谁或哪个来源、等什么结果。'});else changes.waiting={who:plan.waitingFor,result:plan.waitingResult,quote:plan.waitingQuote};}
  if(plan.checkCompleted){if(!grounded(plan.checkQuote))fail('检查结果缺少本次输入依据');changes.checkCompleted=plan.checkQuote;}
  if(plan.riskDecision!=='none'){if(!['confirmed','resolved','dismissed'].includes(plan.riskDecision)||!grounded(plan.riskQuote))fail('风险结论缺少本次明确表达');changes.riskDecision=plan.riskDecision;changes.riskQuote=plan.riskQuote;}
  if(plan.followup!=='unchanged'){if(!['continue','end','cancel'].includes(plan.followup)||!grounded(plan.followupQuote))fail('跟进结束条件需有本次明确表达');changes.followup=plan.followup;changes.followupQuote=plan.followupQuote;}
  for(const key of ['check','completion'] as const){
    let text:TimeNode|undefined,manual:TimeNode|undefined;
    if(plan[key]?.state&&plan[key].state!=='unchanged'){
      if(!grounded(plan[key].quote||''))fail('文字时间缺少本次输入的原话');text=normalizeTime(plan[key],'user-text',input.occurredAt);
    }
    if(input.manual?.[key]&&input.manual[key]!.state!=='unchanged')manual=normalizeTime(input.manual[key]!,'manual',input.occurredAt);
    if(text&&manual&&!same(comparable(text),comparable(manual))&&!input.resolution?.[key])conflicts.push({field:key,message:(key==='check'?'检查':'完成')+'时间有两种明确选择，请选本次采用哪一项。',text,manual});
    else if(text||manual){const node=input.resolution?.[key]==='text'?text:input.resolution?.[key]==='manual'?manual:manual||text;if(!node)fail('时间候选已变化，请重新选择');changes[key]=node;}
  }
  const future=(['check','completion'] as const).filter(key=>{const t=changes[key];return t?.state==='scheduled'&&Date.parse(t.effectiveAt||t.date+'T10:00:00+08:00')>Date.parse(input.occurredAt);});
  if(['end','cancel'].includes(changes.followup||'')&&future.length){
    if(input.resolution?.followup==='continue')changes.followup='continue';
    else if(input.resolution?.followup==='end')for(const key of future)delete changes[key];
    else conflicts.push({field:'followup',message:'本次同时要求结束并设置了未来安排：还有后续要跟进吗？'});
  }
  if(plan.intent==='clarify'||plan.clarification)conflicts.push({field:'clarification',message:plan.clarification||'请补充会影响本次结果的具体安排。'});
  if(plan.intent==='discuss'&&Object.keys(changes).some(k=>!['check','completion'].includes(k)))fail('讨论不能自动写成业务记录');
  if(plan.intent==='other'&&Object.keys(changes).length)fail('本次请求不属于明确的本地记录');
  return {changes,conflicts,stay:plan.intent==='discuss'||plan.intent==='mixed'||plan.intent==='clarify'||plan.intent==='other'};
}

/** Read old values without migrating or inventing user intent. */
export function itemTiming(s:V2State,source:Item,at:string|number=Date.now()){
  const item=source.workItem,p1=item.p1||{},target=item.businessTarget&&s[item.businessTarget.kind as keyof V2State];
  const business=Array.isArray(target)?target.find((r:Item)=>r.id===item.businessTarget.id) as Item|undefined:undefined;
  let check:TimeNode=p1.check||{state:'unchanged'};
  if(!p1.check&&item.handling?.nextCheckAt){const old=item.handling.nextCheckAt;check=Number.isFinite(Date.parse(old))?{state:'scheduled',effectiveAt:old,date:shanghaiDay(old),time:new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(old)),zone:'Asia/Shanghai',precision:'minute',origin:'legacy',quote:old}:{state:'unchanged',quote:String(old),needsReview:true};}
  const requirements:TimeNode[]=[];
  for(const [field,label] of [['plannedEnd','正式计划'],['dueAt','承诺交付'],['committed','责任人承诺'],['deadline','业务完成要求']] as const){const value=business?.[field];if(value)requirements.push(validDate(value)?{state:'scheduled',date:value,precision:'date',origin:label,quote:value}:{state:'unchanged',origin:label,quote:String(value),needsReview:true});}
  if(!p1.check&&check.state==='unchanged'&&business?.checkAt)check=validDate(business.checkAt)?{...normalizeTime({state:'scheduled',date:business.checkAt},'legacy',source.updatedAt||source.createdAt),defaultTime:'09:00（旧规则）',effectiveAt:new Date(business.checkAt+'T09:00:00+08:00').toISOString()}:{state:'unchanged',quote:String(business.checkAt),needsReview:true};
  const completion:TimeNode=p1.completion||{state:'unchanged'};
  const usable=(n:TimeNode)=>n.state==='scheduled'&&!n.completedAt&&!n.needsReview;
  const scheduled=usable(check)||usable(completion)||requirements.some(usable);
  const status=scheduled?'已安排':check.state==='pending'&&completion.state==='pending'?'明确待定':!['risk','action','decision'].includes(item.nature)?'无需时间安排':'时间待确认';
  const today=shanghaiDay(at);
  const nodeDay=(node:TimeNode)=>{if(!node.zone||node.zone==='Asia/Shanghai')return today;if(node.zone==='UTC')return new Date(at).toISOString().slice(0,10);const parts=/^([+-])(\d{2}):(\d{2})$/.exec(node.zone);return parts?new Date(new Date(at).getTime()+(parts[1]==='-'?-1:1)*(Number(parts[2])*60+Number(parts[3]))*60000).toISOString().slice(0,10):today;};
  const dueLabel=(node:TimeNode)=>!usable(node)?'':node.precision==='minute'?(Date.parse(node.effectiveAt||'')<=new Date(at).getTime()?'要求时间已过，完成情况待核实':''):node.date!<nodeDay(node)?'要求时间已过，完成情况待核实':node.date===nodeDay(node)?'今日到期':'';
  return {check,completion,requirements,status,completionDue:[completion,...requirements].map(node=>({node,label:dueLabel(node)})).filter(v=>v.label),checkMissing:!usable(check),checkHistorical:!!check.completedAt};
}
export function timeLabel(node:TimeNode){if(node.needsReview)return node.reviewReason||'原时间待核对：'+node.quote;if(node.completedAt)return '本次检查已完成（历史）';if(node.state==='pending')return '明确待定';if(node.state!=='scheduled')return '未提供';return node.date+(node.time?' '+node.time:node.defaultTime?' · 默认 '+node.defaultTime:'')+(node.zone&&node.zone!=='Asia/Shanghai'?' '+node.zone:'')+(node.origin&&node.origin!=='user-text'&&node.origin!=='manual'?' · '+node.origin:'');}

export function applyEntryChanges(source:Item,changes:EntryChanges,operationId:string,at:string){
  const item=source.workItem;item.p1||={};const p=item.p1;
  if(changes.progress){const entry={id:changes.progress.editId||operationId,text:changes.progress.text,quote:changes.progress.quote,at};if(changes.progress.editId){if(!(p.progress||[]).some((r:Item)=>r.id===entry.id))fail('原进展记录已变化，请重新核对');p.progress=p.progress.map((r:Item)=>r.id===entry.id?entry:r);}else p.progress=[...(p.progress||[]),entry];}
  if(changes.checkCompleted){p.checkHistory=[...(p.checkHistory||[]),{...(p.check||{}),completedAt:at,result:changes.checkCompleted}];p.check={...(p.check||{}),state:p.check?.state||'unchanged',completedAt:at};p.checkResult={text:changes.checkCompleted,at};}
  for(const key of ['check','completion'] as const)if(changes[key]){
    const node=structuredClone(changes[key]);
    if(key==='check'&&node.state==='scheduled'&&node.precision==='date'){node.defaultTime='10:00';const offset=node.zone==='UTC'?'Z':node.zone==='Asia/Shanghai'?'+08:00':node.zone;node.effectiveAt=new Date(node.date+'T10:00:00'+offset).toISOString();}
    p[key]=node;
  }
  if(changes.waiting){p.waiting={...changes.waiting,at};item.handling={...(item.handling||{}),state:'waiting',reason:'等待'+changes.waiting.who+'：'+changes.waiting.result,at};}
  if(changes.followup)p.lifecycle={state:['end','cancel'].includes(changes.followup||'')?'closed':'open',reason:changes.followupQuote||'',at,operationId};
  if(changes.riskDecision){p.riskDecision={decision:changes.riskDecision,reason:changes.riskQuote,at};if(!changes.followup)p.lifecycle={state:'open',reason:'风险结论已记录，后续安排尚未明确结束',at,operationId};}
  if(p.lifecycle?.state==='closed')item.handling={...(item.handling||{}),state:'handled',at};
  else if(changes.followup==='continue')item.handling={...(item.handling||{}),state:'attention',at};
  item.contentHash='';
}

type Patch={path:string[];before:unknown;after:unknown;appendId?:string};
export function entryPatches(before:Item,after:Item):Patch[]{
  const patches:Patch[]=[];
  function walk(a:unknown,b:unknown,path:string[]){
    if(same(a,b))return;
    if(path.join('.')==='p1.progress'){
      const old=(a||[]) as Item[],next=(b||[]) as Item[];for(const row of next){const previous=old.find((x:Item)=>x.id===row.id);if(!same(previous,row))patches.push({path,before:previous||null,after:row,appendId:row.id});}return;
    }
    if((b&&typeof b==='object'&&!Array.isArray(b))||(a&&typeof a==='object'&&!Array.isArray(a))){const left=(a||{}) as Record<string,unknown>,right=(b||{}) as Record<string,unknown>;for(const k of new Set([...Object.keys(left),...Object.keys(right)]))walk(left[k],right[k],[...path,k]);}
    else patches.push({path,before:a??null,after:b??null});
  }
  for(const key of ['p1','handling','reviews','decisions','disposition','nature','summary','impact','nextStep','urgency'])walk(before[key],after[key],[key]);
  return patches;
}
export function undoEntry(source:Item,patches:Patch[]){
  const item=source.workItem;
  const read=(path:string[])=>path.reduce((value,key)=>value?.[key],item);
  const conflicts=patches.filter(p=>p.appendId?!same((read(p.path)||[]).find((x:Item)=>x.id===p.appendId),p.after):!same(read(p.path),p.after));
  if(conflicts.length)throw Object.assign(new Error('本次涉及的内容已有后续修改，未撤销任何内容。请查看当前记录再修正。'),{status:409,errors:conflicts.map(p=>({path:p.path.join('.'),message:'后续修改与本次撤销冲突'}))});
  for(const p of patches){let parent=item;for(const key of p.path.slice(0,-1))parent=parent[key]??={};const key=p.path.at(-1)!;if(p.appendId)parent[key]=p.before===null?(parent[key]||[]).filter((x:Item)=>x.id!==p.appendId):(parent[key]||[]).map((x:Item)=>x.id===p.appendId?structuredClone(p.before):x);else if(p.before===null)delete parent[key];else parent[key]=structuredClone(p.before);}
  item.contentHash='';
}
export function entryReceipts(s:V2State,sourceId:string){return Object.entries(s.receipts).flatMap(([key,r])=>r.result?.p1&&r.result.sourceId===sourceId?[{...r.result,requestId:key.slice('work-item:'.length)}]:[]).sort((a,b)=>String(b.at).localeCompare(String(a.at)));}

export type P1ReceiptValue={p1?:boolean;sourceId:string;operationId:string;at:string;progress:string;closed:boolean;stay:boolean;input:EntryInput;timing:ReturnType<typeof itemTiming>;patches:Patch[];changes:string[];undoneAt?:string};
export type P1EntrySeed={focusTime?:boolean;receipt?:P1ReceiptValue};
