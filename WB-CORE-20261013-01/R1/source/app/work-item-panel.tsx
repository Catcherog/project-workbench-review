"use client";
import {NotebookPen,FileText,UserRound,CalendarDays} from 'lucide-react';
import {timeLabel,entryReceipts} from '../lib/work-item-progress';
import './work-item-entry.css';
import {P1Receipt} from './work-item-entry';
import {useEffect,useRef,useState} from 'react';
import type {Item} from '../lib/domain';
import type {V2Kind,V2State} from '../lib/v2-types';
import {workItemState,workItemRecordView,workItemLabels,type WorkItemNature} from '../lib/work-items';
import {workItemBrief} from '../lib/work-item-brief';
import type {FeedbackRequest} from './comment-feedback';
import {itemTime} from './item-workspace-model';
import {readInputDraft,writeInputDraft} from './local-draft';
import {useItemWorkspaceNavigation} from './item-workspace-navigation';
import './work-item-panel.css';
import {WorkItemCoreControls} from './work-item-core-controls';
import {EvidenceReader} from './evidence-reader';

type Props={s:V2State;source:Item;request:FeedbackRequest;refresh:()=>Promise<unknown>;open:(id:string)=>void};
const labels:Record<string,string>={'delivery-recorded':'工程师交付已记录','task-linked':'已关联任务操作',confirm_ready:'核对清楚并转入待跟进',associate:'调整归属',ignore:'忽略',restore:'恢复关注',reopen:'重新打开',acknowledge:'已了解',correct:'纠正理解',review:'风险判断',take_over:'接手',wait:'等待',resume:'恢复跟进',done:'办结',split:'拆分',merge:'合并','change-decision':'核对新变化'};
export function WorkItemPanel({s,source,request,refresh,open}:Props){
  const navigation=useItemWorkspaceNavigation(),editorRef=useRef<HTMLFormElement>(null),evidenceRef=useRef<HTMLDetailsElement>(null);
  const [focusEditor,setFocusEditor]=useState(0);
  useEffect(()=>{const editor=editorRef.current;if(focusEditor&&editor){const header=editor.closest('.iw-dialog')?.querySelector('.iw-top');editor.style.scrollMarginTop=((header?.getBoundingClientRect().height||0)+20)+'px';editor.scrollIntoView({block:'start'});editor.focus({preventScroll:true});}},[focusEditor]);
  const c=workItemState(s,source),item=c.item,change=c.pendingChange,brief=workItemBrief(s,source);
  const draftKey='work-item:'+JSON.stringify([s.workspaceId,source.id]);
  const fresh={title:source.title,summary:item.summary||'',nature:item.nature as WorkItemNature,impact:item.impact||'',nextStep:item.nextStep||'',urgency:item.urgency||'normal'};
  const [draft]=useState(()=>readInputDraft(draftKey,{reason:'',nextDate:'',decision:'',association:item.association.kind+':'+(item.association.id||''),expectedVersion:source.version,expectedBasis:c.basis,expectedEvidenceBasis:c.liveEvidenceBasis,editing:false,editMode:'full',
    editTitle:fresh.title,editSummary:fresh.summary,editNature:fresh.nature,editImpact:fresh.impact,editNextStep:fresh.nextStep,editUrgency:fresh.urgency,riskDecision:item.nature==='risk'?'preserve':'pending',riskDisposition:''}));
  const [expected,setExpected]=useState(()=>draft.reason||draft.nextDate||draft.decision||draft.editing?{version:draft.expectedVersion,basis:draft.expectedBasis,evidence:draft.expectedEvidenceBasis}:{version:source.version,basis:c.basis,evidence:c.liveEvidenceBasis});
  const [reason,setReason]=useState(draft.reason),[nextDate,setNextDate]=useState(draft.nextDate),[decision,setDecision]=useState(draft.decision);
  const [association]=useState(draft.association),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [editing,setEditing]=useState(draft.editing),[editMode,setEditMode]=useState(draft.editMode),[edit,setEdit]=useState({title:draft.editTitle,summary:draft.editSummary,nature:draft.editNature,impact:draft.editImpact,nextStep:draft.editNextStep,urgency:draft.editUrgency});
  const [riskDecision,setRiskDecision]=useState(draft.riskDecision),[riskDisposition,setRiskDisposition]=useState(draft.riskDisposition),[ownProof,setOwnProof]=useState(false);
  const outdated=expected.version!==source.version||expected.basis!==c.basis||expected.evidence!==c.liveEvidenceBasis;
  useEffect(()=>{writeInputDraft(draftKey,{reason,nextDate,decision,association,expectedVersion:expected.version,expectedBasis:expected.basis,expectedEvidenceBasis:expected.evidence,editing,editMode,
    editTitle:edit.title,editSummary:edit.summary,editNature:edit.nature,editImpact:edit.impact,editNextStep:edit.nextStep,editUrgency:edit.urgency,riskDecision,riskDisposition});},[draftKey,reason,nextDate,decision,association,expected,editing,editMode,edit,riskDecision,riskDisposition]);
  async function run(action:string,extra:Record<string,unknown>={}){
    if(busy)return;setBusy(true);setError('');setNotice('');
    try{
      const result=await request('/api/v2/work-items',{workspaceId:s.workspaceId,sourceId:source.id,expectedVersion:expected.version,expectedBasis:expected.basis,expectedEvidenceBasis:expected.evidence,requestId:crypto.randomUUID(),action,reason,...extra});
      await refresh();const updated=result.state?.sources.find((row:Item)=>row.id===source.id);
      if(updated){const current=workItemState(result.state,updated);setExpected({version:updated.version,basis:current.basis,evidence:current.liveEvidenceBasis});}
      setReason('');setDecision('');setEditing(false);setOwnProof(false);
      setNotice(action==='take_over'?'已标记为正在处理；请按上方建议推进。':action==='ignore'?(cancelsPreview?'已忽略并取消未执行的挂载准备，原稿和历史保留。':'已忽略；普通补充不再提示，出现实质风险或新的办理要求时会重新提示。'):action==='correct'&&edit.nature==='risk'?'已进入风险模块，沿用本事项和原文依据。':action==='correct'&&edit.nature==='action'?'已进入待跟进，未创建飞书任务。':(labels[action]||'处理')+'已保存。');

    }catch(e){setError(e instanceof Error?e.message:'未能保存事项');}finally{setBusy(false);}
  }
  function correct(nature?:WorkItemNature){
    setNotice('');setError('');setEditMode(nature||'full');
    setEdit(value=>({...(!editing?fresh:value),...(nature?{nature}:{}),...(nature==='action'?{nextStep:''}:nature==='risk'&&!editing?{nextStep:'持续关注进展，有变化时核对风险影响'}:{})}));
    setRiskDecision(nature==='risk'&&item.nature!=='risk'?'pending':item.nature==='risk'?'preserve':'pending');
    setEditing(true);setFocusEditor(value=>value+1);
  }
  const requiresRiskReason=(edit.nature==='risk'||item.nature==='risk')&&edit.nature!==item.nature||edit.nature==='risk'&&riskDecision!=='preserve';
  const editMissing=[...(!edit.title.trim()?['事项标题']:[]),...(!edit.summary.trim()?['当前理解']:[]),...(requiresRiskReason&&!reason.trim()?['判断依据']:[]),...(editMode==='action'&&!edit.nextStep.trim()?['下一步']:[]),...(edit.nature==='risk'&&riskDecision!=='preserve'&&!edit.impact.trim()?['风险影响']:[]),...(item.nature==='risk'&&edit.nature!=='risk'&&!c.closed&&!riskDisposition?['原风险处理结论']:[])];
  function saveEdit(){
    if(editMissing.length){setError('请补充：'+editMissing.join('、')+'。');return;}
    const patch={...Object.fromEntries(Object.entries(edit).filter(([key,value])=>value!==fresh[key as keyof typeof fresh])),...(edit.nature==='risk'&&riskDecision!=='preserve'?{nature:edit.nature}:{})};
    if(!Object.keys(patch).length){setNotice('内容没有变化。');return;}
    void run('correct',{patch,riskDecision,riskDisposition});
  }
  const target=item.association.kind==='project'?s.projects.find(row=>row.id===item.association.id):item.association.kind==='case'?s.cases.find(row=>row.id===item.association.id):undefined;
  const business=item.businessTarget?s[item.businessTarget.kind as V2Kind]?.find((row:Item)=>row.id===item.businessTarget.id&&!row.archived):undefined;
  const badge=c.ignored?'已忽略':c.closed?c.review?.decision==='dismissed'?'疑点不成立':c.review?.decision==='resolved'?'风险已解除':'已办结':change?'新变化待核对':item.nature==='risk'&&c.needsVerification?'风险待核实':item.nature==='risk'&&c.review?.decision==='resolved'?'风险已解除 · 仍有后续':item.nature==='risk'&&c.review?'已确认风险':workItemLabels[item.nature as WorkItemNature];
  const disabled=busy||outdated;
  const cancelsPreview=!!source.dataPublication&&!source.dataPublication.artifact&&['prepared','stale','failed'].includes(source.dataPublication.status);
  return <section className="work-item-panel" aria-label="整合事项处理" data-work-item={source.id}>
    <div className="wi-summary"><span className="v2-badge">{badge}</span>
      {item.handling?.state==='in_progress'&&!c.closed&&!c.ignored&&<p className="wi-handling-status" role="status"><strong>{c.handlingState==='in_progress'?'已接手 · 正在处理':'已接手 · 有新变化待核对'}</strong><span>{itemTime(item.handling.at)} · 接手记录已保存</span></p>}
      <dl className="wi-brief" aria-label="事项概括">
        <div><dt>发生了什么</dt><dd>{brief.facts}</dd></div>
        <div><dt>有什么影响</dt><dd>{brief.impact}</dd></div>
        <div className="wi-brief-next"><dt>需要你做什么</dt><dd>{c.closed?'本次已处理，原建议与处理结论保留在历史。':c.ignored?'本事项已忽略，当前无需处理。':brief.nextStep}</dd></div>
        <div><dt>依据与缺口</dt><dd>{brief.gaps.length?brief.gaps.join('；'):'原文依据与处理记录可在下方展开查看。'}{brief.links.map((url,index)=><a className="wi-source-link" key={url} href={url} target="_blank" rel="noreferrer">打开待补读文档{brief.links.length>1?' '+(index+1):''}</a>)}</dd></div>
      </dl>
      {item.triage&&<details className="wi-triage"><summary>查看 AI 判断依据</summary><p>{item.triage.reason}</p></details>}
      <p>{target?.title||(item.association.kind==='personal'?'个人范围':'归属待定')}{!item.association.confirmed&&target?' · AI建议，待确认':''}</p>
      {target&&<button className="v2-text-button" onClick={()=>open(target.id)}>查看关联{item.association.kind==='case'?'专项':'项目'}</button>}
      {business&&business.id!==target?.id&&<button className="v2-button" onClick={()=>open(business.id)}>办理关联工作：{business.title}</button>}
    </div>
    {<section className="p1-current-times" aria-label="事项时间安排"><strong>{c.closed?'已结束 · 原时间保留历史':c.timing.status}</strong><p>检查：{timeLabel(c.timing.check)}</p><p>完成要求：{timeLabel(c.timing.completion)}</p>{c.timing.requirements.map((t,i)=><p key={i}>{timeLabel(t)}</p>)}{!c.closed&&c.timing.completionDue.map((v,i)=><p key={i} className="p1-overdue">{v.node.date} · {v.label}</p>)}{!c.closed&&navigation&&<button className="v2-text-button" onClick={navigation.openAssistant}><CalendarDays size={15}/>设置时间 / 记录进展</button>}</section>}
    {(item.p1?.progress||[]).slice(-3).map((p:Item)=><div className="p1-progress" key={p.id}><strong>已记录进展</strong><p>{p.text}</p><small>{itemTime(p.at)}</small></div>)}
    {c.ignored&&<p className="wi-saved">原文和历史仍在资料库。普通补充保持安静，新的实质风险或办理要求会重新提示。</p>}
    {item.reactivation&&!c.ignored&&!c.closed&&<p className="wi-saved"><strong>新变化重新提示：</strong>{item.reactivation.reason}</p>}
    {outdated&&<div className="dc-error" role="status"><p>事项或原文已有更新；填写的内容已保留，请重新核对。</p><button className="v2-button" onClick={()=>{setExpected({version:source.version,basis:c.basis,evidence:c.liveEvidenceBasis});setError('');}}>已重新核对，保留说明继续</button></div>}
    {c.stale&&<p className="dc-error" role="status">部分原依据已变化或不可用。{c.currentEvidenceReviewed?'本次处理已针对当前依据状态记录。':'旧判断保留为历史，需核对当前情况。'}</p>}
    {notice&&<p className="wi-saved" role="status">{notice}</p>}{error&&<p className="dc-error" role="alert">{error}</p>}
    <div className="wi-actions">
      {!editing&&<div className="wi-action-row" role="group" aria-label="选择处置方式">{!c.closed&&c.actionable&&navigation&&<button className="v2-button primary" onClick={navigation.openAssistant}><NotebookPen size={15}/>记录进展 / 讨论</button>}{!c.actionable&&<button className="v2-button primary" onClick={()=>{if(evidenceRef.current){evidenceRef.current.open=true;evidenceRef.current.scrollIntoView({block:'start'});}}}><FileText size={15}/>查看依据</button>}
        {c.ignored?<button className="v2-button primary" disabled={disabled} onClick={()=>void run('restore')}>恢复关注</button>:c.closed?<button className="v2-button primary" disabled={disabled||item.nature==='risk'&&!reason.trim()} onClick={()=>void run('reopen')}>{item.nature==='risk'?'重新核实风险':'重新打开'}</button>:<>
          {!change&&c.actionable&&<button className="v2-button" title="标记本人开始跟进，不发送消息或创建飞书任务" disabled={disabled||c.handlingState==='in_progress'} onClick={()=>void run('take_over')}><UserRound size={15}/>{c.handlingState==='in_progress'?'已接手处理':'接手处理'}</button>}
          {!change&&c.actionable&&c.handlingState==='waiting'&&<button className="v2-button" disabled={disabled} onClick={()=>void run('resume')}>恢复跟进</button>}
          {!change&&c.actionable&&item.nature!=='risk'&&<button className="v2-button" title="记录本地事项已处理完，不代替交付物审核或飞书任务完成" disabled={disabled||c.stale&&!c.currentEvidenceReviewed&&(!ownProof||!reason.trim())||item.nature==='decision'&&!reason.trim()} onClick={()=>void run('done',{addOwnEvidence:ownProof})}>{item.nature==='decision'?'记录决定并办结':'本事项已办结'}</button>}
          {!c.actionable&&<button className="v2-button" disabled={disabled} onClick={()=>correct('action')}>转为待办</button>}
          {item.nature!=='risk'&&<button className="v2-button" disabled={disabled} onClick={()=>correct('risk')}>上升为风险</button>}
          {!c.actionable&&!change&&<button className="v2-button" disabled={disabled} onClick={()=>void run('acknowledge')}>已了解，留存资料</button>}
          {c.canIgnore&&<button className="v2-button" disabled={disabled} onClick={()=>void run('ignore')}>{cancelsPreview?'忽略并取消挂载准备':'忽略'}</button>}
        </>}
      </div>}
      {!editing&&<div className="wi-secondary-actions"><button className="v2-text-button" disabled={busy} onClick={()=>correct()}>修改分类与理解</button>{navigation&&<button className="v2-text-button" onClick={navigation.openAssistant}>让 AI 整理归属、合并或拆分</button>}</div>}
      {!editing&&(c.actionable||change||c.closed&&item.nature==='risk')&&<label>说明与依据<textarea aria-label="事项处理说明" rows={3} maxLength={1000} value={reason} onChange={event=>{if(!reason&&!nextDate&&!decision&&!editing)setExpected({version:source.version,basis:c.basis,evidence:c.liveEvidenceBasis});setReason(event.target.value);}} placeholder="记录本次判断的原因或依据"/></label>}
      {c.actionable&&!c.closed&&!c.ignored&&!change&&item.nature!=='decision'&&workItemRecordView(s,source).category==='confirmation'&&<button className="v2-button primary" disabled={disabled||!reason.trim()||c.stale&&!c.currentEvidenceReviewed} onClick={()=>void run('confirm_ready')}>核对清楚，转入待跟进</button>}
      {item.decisions?.length>0&&<div className="wi-saved"><strong>已记录的决定</strong><p>{item.decisions.at(-1).text}</p><small>{itemTime(item.decisions.at(-1).at)}</small></div>}
      {change&&<section className="wi-proposal" aria-label="核对新的实质变化"><strong>AI建议：{workItemLabels[change.nature as WorkItemNature]}</strong><p>{change.summary}</p><p>影响：{change.impact||change.reason}</p><p>原人工判断保留，采用前不会替换。</p>
        {change.nature==='risk'&&<label>采用后的风险状态<select aria-label="新建议风险状态" value={riskDecision==='preserve'?'pending':riskDecision} onChange={event=>setRiskDecision(event.target.value)}><option value="pending">待核实</option><option value="confirmed">已确认风险</option></select></label>}
        {item.nature==='risk'&&change.nature!=='risk'&&!c.closed&&<label>原风险处理<select value={riskDisposition} onChange={event=>setRiskDisposition(event.target.value)}><option value="">请选择</option><option value="dismissed">疑点不成立</option><option value="resolved">风险已解除</option></select></label>}
        <div className="wi-action-row"><button className="v2-button primary" disabled={disabled||!reason.trim()} onClick={()=>void run('change-decision',{changeId:change.id,decision:'accept',riskDecision:riskDecision==='preserve'?'pending':riskDecision,riskDisposition})}>采用这次建议</button><button className="v2-button" disabled={disabled||!reason.trim()} onClick={()=>void run('change-decision',{changeId:change.id,decision:'reject'})}>保留我的判断</button></div>
      </section>}
      {editing&&<form ref={editorRef} tabIndex={-1} className="wi-editor" aria-label="调整事项分类与理解" onSubmit={event=>{event.preventDefault();saveEdit();}}>
        <div className="wi-editor-heading"><strong>{editMode==='risk'?'标记风险并持续关注':editMode==='action'?'转为个人待办':'修改分类与理解'}</strong><span className="v2-muted">尚未保存</span></div>
        {editMode!=='full'&&<p className="v2-muted">{editMode==='risk'?'保存后进入风险清单，沿用当前原文和处理记录。':'写明下一步，保存后进入个人待跟进清单。'}<button type="button" className="v2-text-button" onClick={()=>setEditMode('full')}>修改标题或理解</button></p>}
        {editMode==='full'&&<><label>事项类型<select aria-label="事项类型" value={edit.nature} onChange={event=>{const nature=event.target.value as WorkItemNature;setEdit(value=>({...value,nature}));if(nature==='risk'&&item.nature!=='risk')setRiskDecision('pending');}}>{Object.entries(workItemLabels).map(([value,label])=><option key={value} value={value}>{value==='risk'?'风险':label}</option>)}</select></label>
        <label>事项标题<input required aria-label="事项标题" maxLength={200} value={edit.title} onChange={event=>setEdit(value=>({...value,title:event.target.value}))}/></label>
        <label>当前理解<textarea required aria-label="当前理解" rows={3} maxLength={1600} value={edit.summary} onChange={event=>setEdit(value=>({...value,summary:event.target.value}))}/></label></>}
        {edit.nature==='risk'&&<><div className="wi-controls"><label>风险状态<select aria-label="上升风险状态" value={riskDecision} onChange={event=>setRiskDecision(event.target.value)}>{item.nature==='risk'&&<option value="preserve">保留当前核实状态</option>}<option value="pending">待核实</option><option value="confirmed">已确认风险，持续关注</option></select></label><label>紧迫度<select aria-label="事项紧迫度" value={edit.urgency} onChange={event=>setEdit(value=>({...value,urgency:event.target.value}))}><option value="normal">普通</option><option value="urgent">紧急</option></select></label></div>
        <label>风险影响{riskDecision!=='preserve'?'（必填）':''}<textarea required={riskDecision!=='preserve'} aria-label="风险影响" rows={2} maxLength={1600} value={edit.impact} placeholder="可能影响什么，例如认证进度或关键交付" onChange={event=>setEdit(value=>({...value,impact:event.target.value}))}/></label></>}
        <label>{edit.nature==='risk'?'关注安排':'下一步'}{editMode==='action'?'（必填）':''}<input required={editMode==='action'} aria-label="事项下一步" maxLength={1600} value={edit.nextStep} onChange={event=>setEdit(value=>({...value,nextStep:event.target.value}))}/></label>
        <label>{requiresRiskReason?'判断依据（必填）':'调整说明（选填）'}<textarea required={requiresRiskReason} aria-label="事项处理说明" rows={2} maxLength={1000} value={reason} onChange={event=>{if(!reason&&!nextDate&&!decision&&!editing)setExpected({version:source.version,basis:c.basis,evidence:c.liveEvidenceBasis});setReason(event.target.value);}} placeholder="说明为何这样判断，可引用原文或记录本人的补充判断"/></label>
        {item.nature==='risk'&&edit.nature!=='risk'&&!c.closed&&<label>原风险如何处理<select required aria-label="原风险处理" value={riskDisposition} onChange={event=>setRiskDisposition(event.target.value)}><option value="">请选择结论</option><option value="dismissed">疑点不成立</option><option value="resolved">风险已解除</option></select></label>}
        {edit.nature==='risk'&&<p className="v2-muted">{riskDecision==='confirmed'?'这次确认会记录为本人的风险判断，持续保留在风险清单。':'待核实表示需要继续确认，不等于风险已经成立。'}</p>}
        <div className="wi-form-footer">{outdated&&<p className="dc-error" role="status">事项或原文已有更新，草稿已保留。<button type="button" className="v2-text-button" onClick={()=>{setExpected({version:source.version,basis:c.basis,evidence:c.liveEvidenceBasis});setError('');}}>我已核对更新，继续保存</button></p>}{editMissing.length>0&&<p className="wi-required" role="status">待填写：{editMissing.join('、')}</p>}<div className="wi-action-row"><button type="submit" className="v2-button primary" disabled={disabled}>{busy?'正在保存…':editMode==='risk'?riskDecision==='confirmed'?'确认风险并持续关注':'列为待核实风险':editMode==='action'?'保存为待办':'保存调整'}</button><button type="button" className="v2-button" disabled={busy} onClick={()=>{setEditing(false);setError('');}}>取消调整</button></div></div>
      </form>}
      {item.nature==='risk'&&!change&&!editing&&<div className="wi-controls"><label>风险判断<select aria-label="事项风险判断" value={decision} onChange={event=>setDecision(event.target.value)}><option value="">选择本次结论</option><option value="confirmed">确认风险，继续跟进</option><option value="dismissed">疑点不成立</option><option value="resolved">风险已解除</option></select></label><button className="v2-button primary" disabled={disabled||!decision||!reason.trim()||c.stale&&decision!=='dismissed'&&!ownProof} onClick={()=>void run('review',{decision,addOwnEvidence:ownProof})}>保存风险判断</button></div>}
      {c.stale&&!editing&&!c.closed&&!c.ignored&&(item.nature==='risk'?decision&&decision!=='dismissed':c.actionable&&!change)&&<label className="v2-check wi-check"><input type="checkbox" checked={ownProof} onChange={event=>setOwnProof(event.target.checked)}/>我已基于上面的本人说明核实；将说明作为补充依据留存</label>}
      {c.review&&<div className="wi-saved"><strong>{{confirmed:'已确认风险，继续跟进',dismissed:'疑点不成立',resolved:'风险已解除'}[c.review.decision as 'confirmed'|'dismissed'|'resolved']}</strong><p>{c.review.reason}</p><small>{itemTime(c.review.at)}</small></div>}
      {c.actionable&&!c.closed&&!c.ignored&&!change&&navigation&&<details><summary>等待结果</summary><p>{item.p1?.waiting?'等待'+item.p1.waiting.who+'：'+item.p1.waiting.result:item.handling?.reason||'等待对象与预期结果可沿用当前上下文。'}</p><button className="v2-button" onClick={navigation.openAssistant}>记录等待 / 调整时间</button></details>}
      {c.actionable&&!c.closed&&!c.ignored&&!change&&!navigation&&<details><summary>等待回复与下次跟进</summary><div className="wi-controls"><label>下次跟进时间<input aria-label="事项下次跟进时间" type="datetime-local" value={nextDate} onChange={event=>setNextDate(event.target.value)}/></label><button className="v2-button" disabled={disabled||!nextDate||!reason.trim()} onClick={()=>void run('wait',{nextCheckAt:new Date(nextDate+':00+08:00').toISOString()})}>等待回复</button></div>{item.handling?.nextCheckAt&&c.nextCheckAt!==item.handling.nextCheckAt&&<p>下次跟进已按关联工作的较早期限提前。</p>}{item.handling?.nextCheckAt&&<p>{itemTime(c.nextCheckAt)} · {item.handling.reason}</p>}</details>}
    </div>
    {(c.actionable||item.manualAttention||c.closed)&&<WorkItemCoreControls s={s} source={source} request={request} refresh={refresh}/>}
    <details className="wi-evidence" ref={evidenceRef}><summary>原文与处理记录 · {c.evidence.length} 份原文 · {item.history.length+item.reviews.length} 条记录</summary>
      <h4>原文依据</h4>{item.assessmentEvidence&&<p className="v2-muted">当前判断依据与历史留档分别标明；历史材料保留用于追溯。</p>}{c.evidence.map((proof:Item)=><section key={proof.key}>{item.assessmentEvidence&&<p className="v2-muted">{c.currentEvidence.some((e:Item)=>e.key===proof.key)?'当前判断依据':'历史留档'}</p>}<EvidenceReader s={s} evidence={{id:proof.sourceId,title:proof.row?.title||'原文不可用',author:proof.row?.author||'',occurredAt:proof.row?.occurredAt||proof.row?.collectedAt||'',version:proof.row?.version,text:proof.row?.excerpt||'',available:proof.available}}/><button className="v2-text-button" onClick={()=>open(proof.sourceId)}>查看来源及版本</button></section>)}
      {item.limitations?.length>0&&<><h4>待核实与读取范围</h4><ul>{item.limitations.map((text:string,index:number)=><li key={index}>{text}</li>)}</ul></>}
      <h4>处理记录</h4>{entryReceipts(s,source.id).map(r=><P1Receipt key={r.operationId} receipt={r} s={s} request={request} onEdit={()=>navigation?.editEntry?.(r)} onTime={()=>navigation?.openAssistant()} onRefresh={async()=>{await refresh();}}/>)}{item.history.length+item.reviews.length===0&&<p className="v2-muted">尚无处理记录。</p>}
      {[...item.reviews.map((entry:Item)=>({...entry,operation:'review'})),...item.history].sort((a:Item,b:Item)=>b.at.localeCompare(a.at)).map((entry:Item,index:number)=><section key={index}><small>{itemTime(entry.at)} · {labels[entry.operation]||'资料更新'}</small><p>{entry.reason||entry.summary||'原处理结论已保留'}</p>{entry.reviews?.map((review:Item,i:number)=><p key={i}>{review.reason}</p>)}</section>)}
    </details>
  </section>;
}
