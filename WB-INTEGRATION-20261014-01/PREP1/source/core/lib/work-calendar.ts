/** Business calendars are explicit evidence/configuration. Never infer a weekend. */
export type WorkCalendar = {
  id:string; revision:number; source:string; verifiedAt:string; from:string; through:string;
  days:Record<string,boolean>; synthetic?:boolean;
};
export const chinaDay=(at:string|number)=>new Date(new Date(at).getTime()+8*3600000).toISOString().slice(0,10);
export const chinaTime=(at:string|number)=>new Date(new Date(at).getTime()+8*3600000).toISOString().slice(11,16);
export const chinaInstant=(day:string,time='09:00')=>new Date(day+'T'+time+':00+08:00').toISOString();
export const addDays=(day:string,n:number)=>new Date(Date.parse(day+'T12:00:00Z')+n*86400000).toISOString().slice(0,10);
export function validDay(day:unknown):day is string {
  return typeof day==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(day)&&Number.isFinite(Date.parse(day))&&new Date(day).toISOString().slice(0,10)===day;
}
export function validateWorkCalendar(value:WorkCalendar) {
  if(!value?.id||!Number.isInteger(value.revision)||value.revision<1||!value.source?.trim()||!Number.isFinite(Date.parse(value.verifiedAt))||!validDay(value.from)||!validDay(value.through)||value.from>value.through||!value.days||Object.entries(value.days).some(([day,work])=>!validDay(day)||typeof work!=='boolean'||day<value.from||day>value.through))throw Object.assign(Error('工作日历需要有效范围、逐日配置和核对来源'),{status:422});
  return value;
}
export function workingDay(calendar:WorkCalendar|undefined,day:string):boolean|null {
  if(!calendar||day<calendar.from||day>calendar.through||!Object.hasOwn(calendar.days,day))return null;
  return calendar.days[day];
}
export function nextWorkMorning(calendar:WorkCalendar|undefined,at:string|number,includeToday=false):string|null {
  const day=chinaDay(at);
  for(let n=includeToday?0:1;n<370;n++){
    const date=addDays(day,n),work=workingDay(calendar,date);
    if(work===null)return null;
    if(work&&(n>0||Date.parse(chinaInstant(date))>new Date(at).getTime()))return chinaInstant(date);
  }
  return null;
}
export function lastWorkdayOfWeek(calendar:WorkCalendar|undefined,day:string):string|null {
  const weekday=new Date(day+'T12:00:00Z').getUTCDay(),monday=addDays(day,-((weekday+6)%7));
  let last='';
  for(let n=0;n<7;n++){
    const date=addDays(monday,n),work=workingDay(calendar,date);
    if(work===null)return null;
    if(work)last=date;
  }
  return last;
}
