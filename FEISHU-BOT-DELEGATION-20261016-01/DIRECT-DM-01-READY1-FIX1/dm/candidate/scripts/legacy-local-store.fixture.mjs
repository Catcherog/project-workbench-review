import { DatabaseSync, backup as sqliteBackup } from 'node:sqlite';
import { mkdirSync, readFileSync, writeFileSync, renameSync, existsSync, readdirSync, unlinkSync, statSync, openSync, fsyncSync, closeSync } from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import path from 'node:path';
import * as domain from '../dist-local/domain.mjs';
import { AssistantSessions, validateAssistantBundle } from './assistant-sessions.mjs';
import {meetingFiles, restoreMeetingWorkflow, validateMeetingBackup} from './meeting-integration.mjs';
import {validateDesktopNotifications} from './followup-notifications.mjs';

export const kinds = ['projects','milestones','dependencies','risks','decisions','actions','sources','judgments','people','resources','relations','flowNodes','deliverables','externalLinks','cases'];
export const hash = value => createHash('sha256').update(typeof value==='string'||Buffer.isBuffer(value)?value:JSON.stringify(value)).digest('hex');
const fail = (message,status=400,errors=[]) => Object.assign(new Error(message),{status,errors});
const now = () => new Date().toISOString();
function cloneSyncForRestore(input,workspaceId) {
  const value=input?structuredClone(input):{version:1,config:{enabled:false,intervalSeconds:60},status:{phase:'idle'},runs:[],conflicts:[],inaccessible:[],discoveries:[],requests:{}};
  value.workspaceId=workspaceId;value.config.enabled=false;value.status.phase='idle';value.status.nextRunAt='';value.requests={};
  value.conflicts=Array.isArray(value.conflicts)?value.conflicts:[];value.inaccessible=Array.isArray(value.inaccessible)?value.inaccessible:[];value.discoveries=Array.isArray(value.discoveries)?value.discoveries:[];value.readWarnings=Array.isArray(value.readWarnings)?value.readWarnings:[];
  for(const run of value.runs){run.workspaceId=workspaceId;if(['approved','sending','pending_review'].includes(run.status)){run.status=run.status==='sending'?'needs_reconcile':'stale';run.error='备份恢复后原批准失效，请核对远端并重新审核';}}
  return value;
}
export function durableWrite(filename, data) {
  mkdirSync(path.dirname(filename),{recursive:true});
  const temp=filename+'.'+randomUUID()+'.tmp';
  const fd=openSync(temp,'wx',0o600);
  try { writeFileSync(fd,data); fsyncSync(fd); } finally { closeSync(fd); }
  renameSync(temp,filename);
}
export function findLegacy(root) {
  const folder=path.join(root,'.wrangler/state/v3/d1/miniflare-D1DatabaseObject');
  if(!existsSync(folder)) return null;
  const files=readdirSync(folder).filter(x=>x.endsWith('.sqlite')&&x!=='metadata.sqlite');
  if(files.length>1) throw fail('存在多个旧数据库，请明确指定 PM_LEGACY_DB，不能自动选择。');
  return files.length?path.join(folder,files[0]):null;
}
export class LocalStore {
  constructor(dataDir,options={}) {
    this.dir=path.resolve(dataDir);this.options=options;this.changeListeners=new Set();this.workspaceSummaries=new Map();this.summaryDataVersion=null;
    mkdirSync(this.dir,{recursive:true});
    this.file=path.join(this.dir,'workbench.sqlite');
    this.existed=existsSync(this.file);
    this.db=new DatabaseSync(this.file);
    this.db.exec('PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;');
    if(this.db.prepare('PRAGMA integrity_check').get().integrity_check!=='ok') throw fail('数据库校验失败；已停止启动，请从备份恢复。');
  }
  async initialize(legacy) {
    const version=this.db.prepare('PRAGMA user_version').get().user_version;
    if(version>2)throw fail('数据库版本高于此应用支持的版本，未修改原数据。');
    if(this.existed&&version<2) {
      const file=path.join(this.dir,'backups','before-migration-'+Date.now()+'.sqlite');
      mkdirSync(path.dirname(file),{recursive:true});
      await sqliteBackup(this.db,file);
    }
    this.db.exec('BEGIN IMMEDIATE');
    try {
      this.db.exec('CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS attachments (workspace_id TEXT NOT NULL,id TEXT NOT NULL,name TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,path TEXT NOT NULL,PRIMARY KEY(workspace_id,id),FOREIGN KEY(workspace_id) REFERENCES workspaces(id)); CREATE TABLE IF NOT EXISTS restore_previews (token TEXT PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL,result TEXT);');
      this.db.exec('CREATE TABLE IF NOT EXISTS assistant_jobs (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(workspace_id,request_id))');
      this.assistantSessions = new AssistantSessions(this);
      if(this.options.failMigration)throw fail('隔离测试：模拟迁移失败');
      this.db.exec('PRAGMA user_version=2; COMMIT');
    } catch(e){this.db.exec('ROLLBACK');throw e;}
    if(!this.getSetting('initialized')) {
      let oldStates=[];
      if(legacy) {
        if(!existsSync(legacy))throw fail('指定的旧数据库不存在；不会初始化为空库。');
        const original=new DatabaseSync(legacy,{readOnly:true});
        const snapshot=path.join(this.dir,'backups','legacy-before-upgrade-'+Date.now()+'.sqlite');
        mkdirSync(path.dirname(snapshot),{recursive:true});
        try {await sqliteBackup(original,snapshot);} finally {original.close();}
        const src=new DatabaseSync(snapshot,{readOnly:true});
        try {
          if(src.prepare('PRAGMA integrity_check').get().integrity_check!=='ok')throw fail('旧库备份校验失败。');
          oldStates=src.prepare('SELECT id,revision,payload FROM workspaces').all();
          if(!oldStates.length)throw fail('旧数据库没有工作区；需检查原因，未自动重播种。');
        } finally {src.close();}
        durableWrite(path.join(this.dir,'migration-baseline.json'),JSON.stringify({createdAt:now(),source:legacy,snapshot,records:oldStates.map(r=>({id:r.id,revision:r.revision,sha256:hash(r.payload),counts:Object.fromEntries(kinds.map(k=>[k,JSON.parse(r.payload)[k]?.length||0]))}))},null,2));
      }
      this.transaction(()=>{
        if(this.db.prepare('SELECT count(*) n FROM workspaces').get().n)throw fail('数据库包含未初始化的记录，已停止以保护数据。');
        for(const row of oldStates) this.insert(domain.normalizeState(JSON.parse(row.payload),row.id,'历史工作区（来源待整理）','legacy'));
        for(const s of [domain.emptyState('official','正式工作区','official'),domain.demoState('demo')]) this.insert(s);
        this.setSetting('initialized',{version:2,at:now(),legacy:legacy||null});
        this.setSetting('backupSettings',{enabled:true,intervalHours:24,retain:14,lastRun:null,lastVerified:null});
      });
      await this.createBackup(undefined,'初始化与迁移完成');
    }
  }
  close(){this.changeListeners.clear();this.workspaceSummaries.clear();this.db.close();}
  transaction(fn) {
    this.db.exec('BEGIN IMMEDIATE');
    try {const result=fn();this.db.exec('COMMIT');return result;}catch(e){this.db.exec('ROLLBACK');this.workspaceSummaries.clear();throw e;}
  }
  getSetting(key){const row=this.db.prepare('SELECT payload FROM settings WHERE key=?').get(key);return row?JSON.parse(row.payload):null;}
  setSetting(key,value){this.db.prepare('INSERT INTO settings(key,payload) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload').run(key,JSON.stringify(value));}
  load(id) {
    if(typeof id!=='string'||!id)throw fail('必须提供工作区 ID');
    const row=this.db.prepare('SELECT payload FROM workspaces WHERE id=?').get(id);
    if(!row)throw fail('工作区不存在：'+id,404);
    const s=JSON.parse(row.payload);
    if(s.workspaceId!==id)throw fail('工作区数据范围不一致；已停止读取。',500);
    return domain.hydrateStateCollections(s);
  }
  list(){
    // Only compact headers are read on repeat polls. Other connections invalidate
    // the cache via data_version; local mutations explicitly evict their row.
    const dataVersion=this.db.prepare('PRAGMA data_version').get().data_version;
    if(this.summaryDataVersion!==dataVersion){this.workspaceSummaries.clear();this.summaryDataVersion=dataVersion;}
    const headers=this.db.prepare("SELECT id,revision,updated_at FROM workspaces ORDER BY CASE id WHEN 'official' THEN 0 WHEN 'personal' THEN 1 WHEN 'demo' THEN 2 ELSE 3 END,id").all();
    for(const id of this.workspaceSummaries.keys())if(!headers.some(r=>r.id===id))this.workspaceSummaries.delete(id);
    return headers.map(header=>{
      const key=JSON.stringify([header.revision,header.updated_at]),cached=this.workspaceSummaries.get(header.id);
      if(cached?.key===key)return structuredClone(cached.value);
      const r=this.db.prepare('SELECT id,revision,payload,updated_at FROM workspaces WHERE id=?').get(header.id);
      if(!r)return null;
      const s=JSON.parse(r.payload),recordCounts=Object.fromEntries(kinds.map(k=>[k,s[k]?.length||0])),statistics=domain.workbenchStatistics(domain.hydrateStateCollections(s));
      const value={id:r.id,name:s.workspaceName,type:s.workspaceType,revision:r.revision,recordCounts,counts:{...recordCounts,risks:statistics.risks.open,workItems:statistics.items.total,rawSources:statistics.sources.originals},statistics,countSemantics:{sources:'保存的资料记录数（含派生记录）',risks:'待核实及已确认的未关闭风险',workItems:'未归档且未合并的整合事项',rawSources:'去重后的原始资料'}};
      this.workspaceSummaries.set(header.id,{key:JSON.stringify([r.revision,r.updated_at]),value});return structuredClone(value);
    }).filter(Boolean);
  }

  insert(s) {
    this.directDmIsolation?.assertNoSources(s.sources);
    this.workspaceSummaries.delete(s.workspaceId);
    this.db.prepare('INSERT INTO workspaces(id,revision,payload,updated_at) VALUES (?,?,?,?)').run(s.workspaceId,s.revision,JSON.stringify(s),now());
  }
  save(s,expected) {
    this.directDmIsolation?.assertNoSources(s.sources);
    this.workspaceSummaries.delete(s.workspaceId);
    const result=this.db.prepare('UPDATE workspaces SET revision=?,payload=?,updated_at=? WHERE id=? AND revision=?').run(s.revision,JSON.stringify(s),now(),s.workspaceId,expected);
    if(result.changes!==1)throw fail('工作区版本已变化，请刷新后重试',409);
    if(this.changeListeners.size)queueMicrotask(()=>{for(const listener of this.changeListeners)try{listener(s.workspaceId);}catch{/* Services retain their own diagnostics. */}});
  }
  subscribe(listener){this.changeListeners.add(listener);return()=>this.changeListeners.delete(listener);}
  validateAttachments(s) {
    const errors=[];
    // Attachments may belong to a source, project, flow node or deliverable.
    // Validate every collection so an uploaded deliverable can safely be
    // reviewed and later synchronized without an orphaned local file.
    for(const kind of kinds)for(const record of s[kind]||[])for(const a of record.attachments||[]){
      const row=this.db.prepare('SELECT * FROM attachments WHERE workspace_id=? AND id=?').get(s.workspaceId,a.id);
      if(!row||row.sha256!==a.sha256||row.name!==a.name)errors.push({path:kind+'.'+record.id+'.attachments',message:'附件不存在、校验信息不同或属于其他工作区'});
    }
    if(errors.length)throw fail('附件引用校验失败',400,errors);
  }
  command(body) {
    return this.transaction(()=>{
      const s=this.load(body.workspaceId);let state;let extra={};
      switch(body.type){
        case 'case': {const result=domain.applyCaseCommand(s,body);const errors=domain.validateState(result.state);if(errors.length)throw fail(errors.map(e=>e.message).join('；'),422,errors);state=result.state;extra.caseId=result.caseId;extra.workId=result.workId;break;}
        case 'manual': state=domain.manualEdit(s,body);break;
        case 'weeklyReview': state=domain.applyWeeklyReviewCommand(s,body);break;
        case 'submitDraft': {const result=domain.submitDraft(s,body.draft);state=result.state;extra.group=result.group;break;}
        case 'editDraft':state=domain.editDraft(s,body.groupId,body.draftVersion,body.operations);break;
        case 'review':state=domain.reviewDraft(s,body);break;
        case 'undo':state=domain.undo(s,body);break;
        case 'viewed':state=domain.markViewed(s,body.requestId);break;
        case 'report': {
          if(!s.projects.some(x=>x.id===body.projectId&&!x.archived))throw fail('项目不存在或已归档');
          if(typeof body.requestId!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(body.requestId))throw fail('生成汇报必须提供有效的请求 ID');
          const receipt=Object.hasOwn(s.receipts,body.requestId)?s.receipts[body.requestId]:null;
          if(receipt){if(receipt.fingerprint!==hash({type:'report',projectId:body.projectId}))throw fail('幂等标识已用于不同请求',409);state=s;extra.report=receipt.result;break;}
          state=structuredClone(s);
          const report={id:'report-'+randomUUID(),createdAt:now(),revision:s.revision,projectId:body.projectId,content:domain.report(s,body.projectId)};
          state.reports.push(report);state.revision++;state.receipts[body.requestId]={fingerprint:hash({type:'report',projectId:body.projectId}),result:report};extra.report=report;break;
        }
        case 'syncPrepare': {
          const result=domain.recordSyncPreparation(s,body.input||body);
          state=result.state;extra.prepared=result.prepared;break;
        }
        case 'syncApprove': {
          const result=domain.approveSyncPreparation(s,body.input||body);
          state=result.state;extra.run=result.run;break;
        }
        case 'registryRegister': {
          const result=domain.registerRemoteSnapshot(s,body.input||body);
          state=result.state;extra.summary=result.summary;break;
        }
        case 'dispatchPrepare': {
          const result=domain.recordDispatchPreparation(s,body.input||body);
          state=result.state;extra.record=result.record;break;
        }
        default:throw fail('不支持的命令类型');
      }
      this.validateAttachments(state);
      if(state!==s) this.save(state,s.revision);
      if(body.simulateSaveFailure&&this.options.testMode)throw fail('隔离测试：模拟提交前写入失败',503);
      return {state,...extra};
    });
  }
  attach(workspaceId,{name,mime,base64}) {
    this.load(workspaceId);
    if(typeof name!=='string'||!name.trim()||name.length>240)throw fail('文件名为空或过长');
    // Repeated four-character capture groups overflow V8's regexp stack on
    // valid large attachments. Validate alphabet, padding and length separately.
    if(typeof base64!=='string'||base64.length%4!==0||!/^[A-Za-z0-9+/]*={0,2}$/.test(base64))throw fail('文件编码无效');
    const bytes=Buffer.from(base64,'base64');
    if(bytes.length>20*1024*1024)throw fail('单个附件最大 20 MB');
    const sha256=hash(bytes),id='file-'+randomUUID(),relative=path.join('attachments',hash(workspaceId).slice(0,24),id);
    const filename=path.join(this.dir,relative);
    durableWrite(filename,bytes);
    const cleanName=path.basename(name).replace(/[\r\n]/g,'_');
    const cleanMime=typeof mime==='string'&&/^[\w.+-]+\/[\w.+-]+$/.test(mime)?mime:'application/octet-stream';
    try {this.transaction(()=>this.db.prepare('INSERT INTO attachments(workspace_id,id,name,mime,size,sha256,path) VALUES (?,?,?,?,?,?,?)').run(workspaceId,id,cleanName,cleanMime,bytes.length,sha256,relative));}
    catch(e){unlinkSync(filename);throw e;}
    return {id,name:cleanName,mime:cleanMime,size:bytes.length,sha256,url:'/api/v2/attachments/'+id+'?workspaceId='+encodeURIComponent(workspaceId)};
  }
  attachment(workspaceId,id) {
    this.load(workspaceId);
    const row=this.db.prepare('SELECT * FROM attachments WHERE workspace_id=? AND id=?').get(workspaceId,id);
    if(!row)throw fail('当前工作区没有此附件',404);
    const bytes=readFileSync(path.join(this.dir,row.path));
    if(hash(bytes)!==row.sha256)throw fail('附件内容校验失败，请从备份恢复',500);
    return {...row,bytes};
  }
  bundle(workspaceId) {
    return this.transaction(()=>{
      const states=workspaceId?[this.load(workspaceId)]:this.list().map(w=>this.load(w.id));
      const rows=workspaceId?this.db.prepare('SELECT * FROM attachments WHERE workspace_id=?').all(workspaceId):this.db.prepare('SELECT * FROM attachments').all();
      const attachments=rows.map(row=>{const bytes=readFileSync(path.join(this.dir,row.path));if(hash(bytes)!==row.sha256)throw fail('附件校验失败：'+row.name);const {path:_,...meta}=row;return {...meta,base64:bytes.toString('base64')};});
      const feishuSync=Object.fromEntries(states.map(s=>[s.workspaceId,this.getSetting('feishuSync:'+s.workspaceId)]).filter(([,value])=>value));
      const assistantConversations=Object.fromEntries(states.map(s=>[s.workspaceId,this.assistantSessions.export(s.workspaceId)]));
      const desktopNotifications=Object.fromEntries(states.map(s=>[s.workspaceId,this.getSetting('followupDesktop:'+s.workspaceId)||[]]));
      const agentMonitor=Object.fromEntries(states.map(s=>[s.workspaceId,this.getSetting('agentMonitor:'+s.workspaceId)]).filter(([,value])=>value));
      const collectionSettings=Object.fromEntries(states.map(s=>[s.workspaceId,{feedback:this.getSetting('feedbackIntake:'+s.workspaceId),meetings:this.getSetting('meetingIntake:'+s.workspaceId),projectChats:this.getSetting('projectChats:'+s.workspaceId)}]));
      const aiRuntime=this.getSetting('aiRuntime');
      const body={format:'pm-workbench-backup',version:2,createdAt:now(),scope:workspaceId||'all',workspaces:states,attachments,assistantConversations,desktopNotifications,agentMonitor,collectionSettings,aiRuntime,...(Object.keys(feishuSync).length?{feishuSync}:{})};
      return {...body,sha256:hash(body)};
    });
  }
  async createBackup(workspaceId,reason='用户完整备份') {
    const bundle=this.bundle(workspaceId),id='backup-'+Date.now()+'-'+randomUUID().slice(0,8);
    const filename=path.join(this.dir,'backups',id+'.json');
    durableWrite(filename,JSON.stringify(bundle));
    this.validateBundle(JSON.parse(readFileSync(filename,'utf8')));
    const meta={id,path:filename,createdAt:bundle.createdAt,scope:bundle.scope,version:2,size:statSync(filename).size,sha256:bundle.sha256,reason,exportVerified:true,restoreVerified:false};
    durableWrite(filename+'.meta',JSON.stringify(meta));
    return meta;
  }
  backups() {
    const dir=path.join(this.dir,'backups');
    if(!existsSync(dir))return [];
    return readdirSync(dir).filter(x=>/^backup-[\w-]+\.json$/.test(x)).map(x=>{
      try {return JSON.parse(readFileSync(path.join(dir,x+'.meta'),'utf8'));}catch{return {id:x.slice(0,-5),path:path.join(dir,x),error:'备份索引缺失，需要重新校验'};}
    }).sort((a,b)=>(b.createdAt||'').localeCompare(a.createdAt||''));
  }
  backupFile(id) {
    if(!/^backup-[\w-]+$/.test(id))throw fail('备份 ID 无效');
    const filename=path.join(this.dir,'backups',id+'.json');
    if(!existsSync(filename))throw fail('备份不存在',404);
    return {filename,bytes:readFileSync(filename)};
  }
  validateBundle(input) {
    let bundle=input,warnings=[];
    if(!input||typeof input!=='object')throw fail('备份必须是 JSON 对象');
    if(input.format!=='pm-workbench-backup') {
      if(input.schemaVersion!==1||!Array.isArray(input.projects)||!Array.isArray(input.audit))throw fail('不支持的旧 JSON 格式或版本');
      const s=domain.normalizeState(input,'legacy-import','旧 JSON 导入','restored');
      bundle={format:'pm-workbench-backup',version:2,createdAt:now(),scope:'legacy-import',workspaces:[s],attachments:[]};
      warnings.push('旧 JSON 没有受管理附件内容；仅恢复台账、来源引用、候选及审计。外部链接不代表文件已经归档。');
      bundle.sha256=hash(bundle);
    } else {
      if(input.version!==2)throw fail('备份版本不兼容');
      const {sha256,...body}=input;
      if(hash(body)!==sha256)throw fail('备份整体校验值不一致，文件可能损坏');
    }
    if(!Array.isArray(bundle.workspaces)||!bundle.workspaces.length||!Array.isArray(bundle.attachments))throw fail('备份缺少工作区或附件清单');
    // Validate the original checksum above, then create an in-memory compatible
    // view. Never rewrite a backup or migrate business records while reading.
    const states=bundle.workspaces.map(s=>domain.hydrateStateCollections(s));
    if(states.some((s,i)=>s!==bundle.workspaces[i])) {
      const {sha256:_,...body}=bundle;
      const compatible={...body,workspaces:states};
      bundle={...compatible,sha256:hash(compatible)};
    }
    const ids=new Set(),fileIds=new Set();
    for(const s of bundle.workspaces) {
      if(ids.has(s.workspaceId)||!s.workspaceId)throw fail('备份中的工作区 ID 重复或缺失');
      ids.add(s.workspaceId);
      const errors=domain.validateState(s);
      if(errors.length)throw fail('备份存在非法对象或引用',400,errors);
      for(const source of s.sources)validateMeetingBackup(source);
      if(Object.keys(s.legacyEventTimes||{}).length)warnings.push(s.workspaceName+'：历史时间缺少时区，保留原始值；未推断发生时间。');
      for(const g of s.changeGroups||[])if(g.workspaceId!==s.workspaceId)throw fail('备份修改组跨工作区');
    }
    if(bundle.feishuSync!==undefined) {
      if(!bundle.feishuSync||typeof bundle.feishuSync!=='object'||Array.isArray(bundle.feishuSync))throw fail('同步记录备份格式无效');
      for(const [id,value] of Object.entries(bundle.feishuSync)) {
        if(!ids.has(id)||value?.workspaceId!==id||value?.version!==1||!Array.isArray(value.runs)||!value.config||!value.status||typeof value.config.enabled!=='boolean'||!Number.isInteger(value.config.intervalSeconds)||value.config.intervalSeconds<30||value.config.intervalSeconds>3600)throw fail('同步记录备份跨工作区或缺少必要内容');
        for(const run of value.runs)if(!run||typeof run.id!=='string'||run.workspaceId!==id||typeof run.status!=='string'||typeof run.fingerprint!=='string'||!Array.isArray(run.patches)||!Array.isArray(run.receipts)||run.patches.some(patch=>!patch||typeof patch.externalObjectId!=='string'||typeof patch.remoteFieldKey!=='string'||typeof patch.proposed!=='string'||!patch.target))throw fail('同步审核备份含有无效或跨工作区记录');
      }
    }
    if(bundle.assistantConversations!==undefined) {
      if(!bundle.assistantConversations||typeof bundle.assistantConversations!=='object'||Array.isArray(bundle.assistantConversations))throw fail('助手历史备份格式无效');
      for(const [id,value] of Object.entries(bundle.assistantConversations)) {
        if(!ids.has(id))throw fail('助手历史备份跨工作区');
        validateAssistantBundle(value,id);
      }
    }
    if(bundle.desktopNotifications!==undefined){
      if(!bundle.desktopNotifications||typeof bundle.desktopNotifications!=='object'||Array.isArray(bundle.desktopNotifications))throw fail('电脑通知备份格式无效');
      for(const [id,rows] of Object.entries(bundle.desktopNotifications)){if(!ids.has(id))throw fail('电脑通知备份跨工作区');validateDesktopNotifications(rows,id);}
    }
    if(bundle.agentMonitor!==undefined){
      if(!bundle.agentMonitor||typeof bundle.agentMonitor!=='object'||Array.isArray(bundle.agentMonitor))throw fail('持续关注备份格式无效');
      for(const [id,c]of Object.entries(bundle.agentMonitor)){
        if(!ids.has(id)||!c||!Array.isArray(c.events)||!Array.isArray(c.advice)||c.events.length>1000||c.advice.length>1000||!c.heads||typeof c.heads!=='object'||!Number.isInteger(c.revision)||!Number.isInteger(c.nextSequence)||!Number.isInteger(c.intervalSeconds)||c.intervalSeconds<30||c.intervalSeconds>3600)throw fail('持续关注历史范围无效');
        if(c.analysis&&(!Number.isSafeInteger(c.analysis.cursor)||c.analysis.cursor<0||c.analysis.cursor>=c.nextSequence||!Array.isArray(c.analysis.runs)||c.analysis.runs.length>100))throw fail('分析回执或恢复游标无效');
        if(c.workflowJobs!==undefined&&(!Array.isArray(c.workflowJobs)||c.workflowJobs.length>30||c.workflowJobs.some(j=>!j||typeof j.id!=='string'||typeof j.status!=='string'||!Array.isArray(j.seeds)||j.seeds.length>8||!Array.isArray(j.proofs)||j.proofs.length>400||!Array.isArray(j.steps))))throw fail('风险研判历史格式无效');
        for(const e of c.events)if(!e||typeof e.id!=='string'||typeof e.sourceId!=='string'||typeof e.fingerprint!=='string'||typeof e.text!=='string'||!Number.isSafeInteger(e.sequence))throw fail('持续关注增量历史格式无效');
        for(const a of c.advice)if(!a||typeof a.id!=='string'||typeof a.sourceId!=='string'||typeof a.fingerprint!=='string'||typeof a.quote!=='string'||typeof a.summary!=='string'||typeof a.nextStep!=='string')throw fail('协作建议历史格式无效');
      }
    }
    if(bundle.collectionSettings!==undefined){
      if(!bundle.collectionSettings||typeof bundle.collectionSettings!=='object'||Array.isArray(bundle.collectionSettings))throw fail('采集设置备份格式无效');
      for(const [id,c] of Object.entries(bundle.collectionSettings)){
        if(c?.projectChats&&(typeof c.projectChats.enabled!=='boolean'||!Number.isInteger(c.projectChats.revision)||c.projectChats.revision<0))throw fail('项目群采集设置备份格式无效');
        if(!ids.has(id)||!c||typeof c!=='object'||Array.isArray(c))throw fail('采集设置跨工作区或格式无效');
        if(c.feedback&&(!Array.isArray(c.feedback.projectIds)||c.feedback.projectIds.some(id=>typeof id!=='string')||typeof c.feedback.enabled!=='boolean'))throw fail('评论采集范围无效');
        if(c.meetings&&(c.meetings.intervalSeconds!=null&&(!Number.isInteger(c.meetings.intervalSeconds)||c.meetings.intervalSeconds<300||c.meetings.intervalSeconds>3600)||c.meetings.lookAheadDays!=null&&![0,7,14,30].includes(c.meetings.lookAheadDays)))throw fail('日历采集范围无效');
      }
    }
    if(bundle.aiRuntime)warnings.push('模型偏好随备份留存；恢复工作区不会覆盖本机当前模型设置。');
    const missingHistory=bundle.workspaces.filter(s=>!Object.hasOwn(bundle.assistantConversations||{},s.workspaceId));
    if(missingHistory.length)warnings.push('此备份未包含'+missingHistory.map(s=>s.workspaceName).join('、')+'的助手历史；覆盖恢复会先备份现有数据，再清除目标原会话，避免将旧会话误认为已恢复内容。');
    for(const a of bundle.attachments) {
      const key=a.workspace_id+':'+a.id;
      if(fileIds.has(key)||!ids.has(a.workspace_id))throw fail('附件 ID 重复或工作区无效');
      fileIds.add(key);
      const bytes=Buffer.from(a.base64||'','base64');
      if(hash(bytes)!==a.sha256||bytes.length!==a.size)throw fail('附件校验失败：'+a.name);
      if(!/^file-[\w-]+$/.test(a.id)||typeof a.name!=='string'||a.name.length>240||/[\r\n]/.test(a.name)||!Number.isSafeInteger(a.size)||a.size<0||typeof a.mime!=='string'||!/^[\w.+-]+\/[\w.+-]+$/.test(a.mime))throw fail('附件标识、类型或文件名无效');
    }
    for(const s of bundle.workspaces)for(const src of s.sources)for(const a of src.attachments||[]) {
      const matched=bundle.attachments.find(f=>f.workspace_id===s.workspaceId&&f.id===a.id);
      if(!matched||matched.sha256!==a.sha256)throw fail('来源附件缺失或内容校验不匹配：'+src.id);
    }
    for(const s of bundle.workspaces)for(const src of s.sources)for(const file of meetingFiles(src)){
      const matched=bundle.attachments.find(a=>a.workspace_id===s.workspaceId&&a.id===file.managedAttachmentId);
      if(!matched||matched.sha256!==file.sha256||matched.size!==file.size)throw fail('会议原件或讨论文件尚未进入完整备份：'+file.name);
    }
    return {bundle,warnings};
  }
  preview(input) {
    const {bundle,warnings}=this.validateBundle(input);
    const token='restore-'+randomUUID(),baselines=Object.fromEntries(this.list().map(w=>[w.id,w.revision]));
    const assistantBaselines=Object.fromEntries(this.list().map(w=>[w.id,this.assistantFingerprint(w.id)]));
    const summary=bundle.workspaces.map(s=>({id:s.workspaceId,name:s.workspaceName,revision:s.revision,counts:Object.fromEntries(kinds.map(k=>[k,s[k].length])),drafts:s.changeGroups.length,audit:s.audit.length,attachments:bundle.attachments.filter(a=>a.workspace_id===s.workspaceId).length,assistantIncluded:!!bundle.assistantConversations?.[s.workspaceId],assistantSessions:bundle.assistantConversations?.[s.workspaceId]?.sessions.length??null,assistantJobs:bundle.assistantConversations?.[s.workspaceId]?.jobs.length??null}));
    const differences={};
    if(bundle.workspaces.length===1)for(const w of this.list()){
      const current=this.load(w.id),next=bundle.workspaces[0];
      differences[w.id]=kinds.flatMap(k=>{
        const old=new Map(current[k].map(x=>[x.id,x])),fresh=new Map(next[k].map(x=>[x.id,x]));
        return [...new Set([...old.keys(),...fresh.keys()])].filter(id=>hash(old.get(id)||null)!==hash(fresh.get(id)||null)).map(id=>({kind:k,id,before:old.get(id)||null,after:fresh.get(id)||null}));
      });
    }
    this.db.prepare('INSERT INTO restore_previews(token,payload,created_at) VALUES (?,?,?)').run(token,JSON.stringify({bundle,baselines,assistantBaselines,differences}),now());
    return {token,workspaces:summary,summary,warnings,differences};
  }
  assistantFingerprint(workspaceId) { return hash(this.assistantSessions.export(workspaceId)); }
  checkRestore({token,mode,workspaceId,confirmed},{assistantFingerprint}={}) {
    if(confirmed!==true)throw fail('必须先查看恢复范围并明确确认');
    if(!['new','replace'].includes(mode))throw fail('恢复模式无效');
    const preview=this.db.prepare('SELECT * FROM restore_previews WHERE token=?').get(token);
    if(!preview)throw fail('恢复预览已不存在，请重新预览',409);
    const requestHash=hash({mode,workspaceId:workspaceId||null});
    if(preview.result){const saved=JSON.parse(preview.result);if(saved.requestHash!==requestHash)throw fail('此恢复预览已用于不同目标',409);return {result:saved.result};}
    const savedPreview=JSON.parse(preview.payload),{baselines,assistantBaselines}=savedPreview;
    const {bundle}=this.validateBundle(savedPreview.bundle);
    if(mode==='replace'){
      if(bundle.workspaces.length!==1)throw fail('覆盖恢复须使用单个工作区备份；完整备份可先恢复到新工作区');
      const target=this.load(workspaceId);
      if(baselines[workspaceId]!==target.revision)throw fail('预览后目标工作区已变化，请重新预览差异',409);
      const expected=assistantFingerprint??assistantBaselines?.[workspaceId];
      if(!expected||expected!==this.assistantFingerprint(workspaceId))throw fail('预览后助手对话或任务已有变化，请重新预览恢复范围',409);
    }
    return {bundle,baselines,requestHash,assistantBaseline:assistantFingerprint??assistantBaselines?.[workspaceId]};
  }
  async restore(body,internal={}) {
    const {token,mode,workspaceId}=body;
    const plan=this.checkRestore(body,internal);
    if(plan.result)return plan.result;
    const {bundle,baselines,requestHash,assistantBaseline}=plan;
    const before=await this.createBackup(undefined,'恢复前自动备份');
    const result=this.transaction(()=>{
      const latest=this.db.prepare('SELECT result FROM restore_previews WHERE token=?').get(token);
      if(latest?.result){const saved=JSON.parse(latest.result);if(saved.requestHash!==requestHash)throw fail('此恢复预览已用于不同目标',409);return saved.result;}
      const restored=[];
      for(const original of bundle.workspaces) {
        const id=mode==='replace'?workspaceId:'restored-'+randomUUID(),s=structuredClone(original);
        s.workspaceId=id;s.workspaceName=original.workspaceName+'（恢复检查）';s.workspaceType='restored';s.demo=false;
        for(const kind of kinds)for(const record of s[kind])if(record.workspaceId)record.workspaceId=id;
        for(const kind of ['externalObjects','remoteFieldValues','mappingRules','syncBaselines','syncRuns','syncReceipts','dispatchRecords'])for(const record of s[kind]||[])record.workspaceId=id;
        for(const g of s.changeGroups){g.workspaceId=id;for(const op of g.operations)for(const a of op.after?.attachments||[])a.url='/api/v2/attachments/'+a.id+'?workspaceId='+encodeURIComponent(id);}
        for(const src of s.sources)for(const a of src.attachments||[])a.url='/api/v2/attachments/'+a.id+'?workspaceId='+encodeURIComponent(id);
        for(const src of s.sources){
          if(src.ruleCheck)src.ruleCheck={...src.ruleCheck,historical:true,restoredAt:now()};
          if(src.dataPublication){src.dataPublication.originalStatus=src.dataPublication.status;src.dataPublication.status='restored';src.dataPublication.fingerprint='';src.dataPublication.restoredAt=now();}
          if(src.meetingWorkflow)restoreMeetingWorkflow(src,id,now());
          for(const key of ['taskContext','meetingContext'])if(['pending','running'].includes(src[key]?.analysis?.status))src[key].analysis={status:'failed',error:'恢复副本保留原文与历史，未重放上次分析；需要时请手动重试。'};
          if(src.commentDispatch){const run=src.commentDispatch;run.workspaceId=id;run.status='historical';run.approvalHash='';run.error='恢复的评论记录仅保留历史，不自动重新发布。';}
          if(src.reminderRun){const run=src.reminderRun;run.workspaceId=id;if(run.status!=='readback_verified'){run.status=['sending','needs_reconcile','partial'].includes(run.status)?'needs_reconcile':'stale';run.error='恢复副本中的原审核失效；已执行结果先回读，剩余内容重新审核。';}run.approvalHash='';if(run.core){run.restored=true;for(const message of run.items){message.approvedHash='';if(!['sending','unknown','sent','readback_verified'].includes(message.stage))message.stage='needs_preview';}run.messages=structuredClone(run.items);}}
          if(src.inputEnvelope){src.inputEnvelope.restored=true;src.inputEnvelope.status='historical';}
          if(src.resultReview?.status==='prepared'){src.resultReview.status='stale';src.resultReview.restoredAt=now();}
        }
        for(const source of s.sources||[]){if(source.subjectAssociation)source.subjectAssociation.historical=true;if(source.managementSignal)source.managementSignal.historical=true;if(source.riskEvidence)source.riskEvidence.historical=true;if(source.chatScope)source.chatScope.state='historical';}
        for(const row of s.cases||[])if(row.chatPolling)row.chatPolling={enabled:false,failures:0,lastError:'',nextReadAt:''};
        for(const row of s.sources||[])if(row.intakeBatch&&['queued','reading','analysing'].includes(row.intakeBatch.status)){row.intakeBatch.status='interrupted';row.intakeBatch.error='从备份恢复的未完成整理，请核对资料后重试。';}
        if(mode==='replace') {
          const current=this.load(id);
          if(current.revision!==baselines[id])throw fail('恢复前工作区已变化',409);
          if(this.assistantFingerprint(id)!==assistantBaseline)throw fail('恢复前助手对话已有变化，请重新预览',409);
          s.revision=current.revision+1;
          this.db.prepare('DELETE FROM attachments WHERE workspace_id=?').run(id);
          this.save(s,current.revision);
        } else this.insert(s);
        // A restored approval is historical evidence, never a new permission
        // to replay an external side effect. Restored polling also stays off.
        const sync=cloneSyncForRestore(bundle.feishuSync?.[original.workspaceId],id);
        this.setSetting('feishuSync:'+id,sync);
        const collections=bundle.collectionSettings?.[original.workspaceId]||{};
        this.setSetting('feedbackIntake:'+id,{projectIds:[],collectFrom:domain.feedbackCollectFrom,issues:[],...(collections.feedback||{}),enabled:false,phase:'idle',nextReadAt:'',restored:true});
        this.setSetting('meetingIntake:'+id,{...(collections.meetings||{}),enabled:false,nextReadAt:'',running:false,phase:'idle',restored:true});
        this.setSetting('projectChats:'+id,collections.projectChats?{...collections.projectChats,enabled:false,nextReadAt:'',restored:true}:null);
        const monitor=bundle.agentMonitor?.[original.workspaceId];
        this.setSetting('agentMonitor:'+id,monitor?{...structuredClone(monitor),enabled:false,analysisOnChange:false,eventPush:{enabled:false,status:'paused'},workflowJobs:(monitor.workflowJobs||[]).map(j=>({...j,status:'historical',workspaceId:id})),restored:true,revision:monitor.revision+1,nextReadAt:'',lastError:'备份中的采集已暂停，建议仅作为历史保留。',lastFeedAt:'',analysis:null,restoredAnalysis:monitor.analysis||null,advice:monitor.advice.map(a=>({...a,historical:true}))}:null);
        this.setSetting('followupDesktop:'+id,(bundle.desktopNotifications?.[original.workspaceId]||[]).map(row=>({...row,workspaceId:id,originalDelivery:row.delivery,delivery:'historical'})));
        for(const a of bundle.attachments.filter(a=>a.workspace_id===original.workspaceId)){
          const relative=path.join('attachments',hash(id).slice(0,24),a.id+'-'+a.sha256);
          durableWrite(path.join(this.dir,relative),Buffer.from(a.base64,'base64'));
          this.db.prepare('INSERT INTO attachments(workspace_id,id,name,mime,size,sha256,path) VALUES (?,?,?,?,?,?,?)').run(id,a.id,a.name,a.mime,a.size,a.sha256,relative);
        }
        if(mode==='replace') {
          this.db.prepare('DELETE FROM assistant_sessions WHERE workspace_id=?').run(id);
          this.db.prepare('DELETE FROM assistant_jobs WHERE workspace_id=?').run(id);
        }
        const history=bundle.assistantConversations?.[original.workspaceId];
        if(history)this.assistantSessions.restore(history,id);
        const actual=this.load(id);
        if(hash(actual)!==hash(s))throw fail('恢复后台账逐字段核对失败',500);
        this.validateAttachments(actual);
        for(const a of bundle.attachments.filter(a=>a.workspace_id===original.workspaceId))this.attachment(id,a.id);
        const historyReadback=this.assistantSessions.export(id);
        validateAssistantBundle(historyReadback,id);
        if(historyReadback.sessions.length!==(history?.sessions.length||0)||historyReadback.jobs.length!==(history?.jobs.length||0)||historyReadback.jobs.some(({job})=>job.status==='running'||job.groupId||job.preview))throw fail('恢复后助手历史校验失败',500);
        restored.push({id,sourceId:original.workspaceId,revision:s.revision,verified:true,assistantSessions:historyReadback.sessions.length,assistantJobs:historyReadback.jobs.length});
      }
      const result={workspaces:restored,beforeBackup:before,restoreVerified:true};
      this.db.prepare('UPDATE restore_previews SET result=? WHERE token=?').run(JSON.stringify({requestHash,result}),token);
      this.setSetting('lastRestore',{at:now(),...result});
      return result;
    });
    for(const metadata of this.backups()){
      if(metadata.sha256===bundle.sha256){metadata.restoreVerified=true;metadata.restoreVerifiedAt=now();durableWrite(metadata.path+'.meta',JSON.stringify(metadata));}
    }
    return result;
  }
  async periodic() {
    const settings=this.getSetting('backupSettings');
    if(!settings?.enabled)return;
    if(settings.lastRun&&Date.now()-Date.parse(settings.lastRun)<settings.intervalHours*3600000)return;
    try {
      const backup=await this.createBackup(undefined,'周期快照');
      this.setSetting('backupSettings',{...settings,lastRun:now(),lastVerified:backup.createdAt,error:null});
      const automatic=this.backups().filter(x=>x.reason==='周期快照');
      for(const expired of automatic.slice(settings.retain)) {unlinkSync(expired.path);if(existsSync(expired.path+'.meta'))unlinkSync(expired.path+'.meta');}
    }catch(e){this.setSetting('backupSettings',{...settings,error:e.message});}
  }
}
