import type {Item} from '../lib/domain';

type HistoryInput={
  text?:string;
  coreInputSourceId?:string;
  p1Input?:{manual?:Partial<Record<'check'|'completion',{state?:string}>>};
};

/** Display only: related evidence is not the attachment list of this input. */
export function workItemInputLabel(job:HistoryInput,sources:Item[]):string{
  if(typeof job.text==='string'&&job.text.trim())return job.text;
  const input=sources.find(source=>source.id===job.coreInputSourceId);
  const attachments=Array.isArray(input?.attachments)?input.attachments:[];
  const attachmentLabel=attachments.length?(attachments.some((file:Item)=>typeof file.mime==='string'&&file.mime.startsWith('image/'))?'图片输入':'附件输入'):'';
  const manualTime=(['check','completion'] as const).some(key=>['scheduled','pending','clear'].includes(job.p1Input?.manual?.[key]?.state||''));
  if(attachmentLabel)return manualTime?attachmentLabel+'与手动时间安排':attachmentLabel;
  return manualTime?'手动时间安排':'本次输入';
}
