import {createHash,randomUUID} from 'node:crypto';
import {publishRuleSignals} from './management-signals.mjs';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const fail=message=>Object.assign(Error(message),{status:409});
export const confirmedRules={id:'workbench-confirmed',version:'20261008.1',title:'已确认的交付物与验收规则',effectiveFrom:'2026-09-30',
  appliesTo:{projectTypes:[],levels:[]},evidence:{path:'AGENTS.md',quote:'普通反馈、预测、正式计划、提交、专业审核、经理验收、节点完成和同步批准分别记录。'},
  rules:[{id:'owner',title:'工作责任资料是否明确',check:'deliverable_owner'},
    {id:'acceptance',title:'经理验收是否保留成果与专业审核依据',check:'acceptance_evidence'},
    {id:'node',title:'节点完成是否有对应交付物依据',check:'node_delivery_evidence'}]};
const checks=new Set(confirmedRules.rules.map(r=>r.check));
export class WorkbenchRules {
  constructor({store,domain}){Object.assign(this,{store,domain});}
  library(state){
    const versions=state.sources.filter(s=>!s.archived&&s.ruleBundle).map(s=>({...s.ruleBundle,sourceId:s.id}));
    if(!versions.some(v=>v.id===confirmedRules.id&&v.version===confirmedRules.version))versions.push({...confirmedRules,digest:hash(confirmedRules),builtin:true});
    return versions;
  }
  view(workspaceId){const state=this.store.load(workspaceId);return {versions:this.library(state),history:state.sources.filter(s=>s.ruleCheck).slice(-30).reverse().map(s=>({id:s.id,...s.ruleCheck})),uncovered:['预算、采购、物料与资源约束尚未建立有效规则和数据连接','检查只使用已保存证据；不代表远端权限、成果专业正确性或实时版本已通过']};}
  persist(workspaceId,source){return this.store.transaction(()=>{const state=this.store.load(workspaceId);state.sources.push(source);if(source.ruleCheck)publishRuleSignals(state,source);const revision=state.revision;state.revision++;const errors=this.domain.validateState(state);if(errors.length)throw fail(errors.map(e=>e.message).join('；'));this.store.save(state,revision);return source;});}
  register({workspaceId,bundle,confirmed}){
    if(confirmed!==true)throw fail('请先核对规则版本、适用范围和依据');
    if(!bundle||!/^[-\w]{1,80}$/.test(bundle.id||'')||!/^[-\w.]{1,80}$/.test(bundle.version||'')||typeof bundle.title!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(bundle.effectiveFrom||'')||!Array.isArray(bundle.rules)||!bundle.rules.length||bundle.rules.length>30||bundle.rules.some(r=>!r?.id||!r.title||!checks.has(r.check))||new Set(bundle.rules.map(r=>r.id)).size!==bundle.rules.length)throw fail('规则版本格式无效或包含未支持的检查');
    if(!bundle.appliesTo||['projectTypes','levels'].some(k=>!Array.isArray(bundle.appliesTo[k])||bundle.appliesTo[k].some(v=>typeof v!=='string')))throw fail('规则适用范围无效');
    const state=this.store.load(workspaceId),evidence=state.sources.find(s=>s.id===bundle.evidence?.sourceId&&!s.archived&&s.confirmed);
    if(!evidence||typeof bundle.evidence?.quote!=='string'||!bundle.evidence.quote.trim()||bundle.evidence.quote.length>1000||!evidence.excerpt?.includes(bundle.evidence.quote))throw fail('规则需要已核对资料中的逐字依据');
    const digest=hash(bundle),existing=this.library(state).find(v=>v.id===bundle.id&&v.version===bundle.version);
    if(existing){if(existing.digest!==digest)throw fail('同一规则版本不能改写，请建立新版本');return existing;}
    const source={id:'rule-version-'+randomUUID(),title:bundle.title+' / '+bundle.version,type:'制度规则版本',projectIds:[],sourceIds:[evidence.id],version:1,confirmed:true,excerpt:bundle.evidence.quote,ruleBundle:{...structuredClone(bundle),digest,registeredAt:new Date().toISOString()}};
    return this.persist(workspaceId,source).ruleBundle;
  }
  run({workspaceId,projectId,versions,requestId}){
    const state=this.store.load(workspaceId),project=state.projects.find(p=>p.id===projectId&&!p.archived);
    if(!project)throw fail('请选择当前工作区的项目');
    if(!Array.isArray(versions)||!versions.length||versions.length>20)throw fail('请明确选择检查所用规则版本');
    if(!/^[\w-]{1,160}$/.test(requestId||''))throw fail('检查需要稳定请求标识');
    const prior=state.sources.find(s=>s.ruleCheck?.requestId===requestId);
    if(prior){if(prior.ruleCheck.requestHash!==hash([projectId,versions]))throw fail('同一检查请求不能改写');return {id:prior.id,...prior.ruleCheck};}
    const library=this.library(state),selected=versions.map(key=>library.find(v=>v.id+'@'+v.version===key));
    if(selected.some(v=>!v)||new Set(versions).size!==versions.length)throw fail('规则版本不存在或重复');
    const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date()),findings=[],used=new Set();
    const nodes=state.flowNodes.filter(n=>!n.archived&&n.projectIds?.includes(projectId)),deliverables=state.deliverables.filter(d=>!d.archived&&d.projectIds?.includes(projectId));
    for(const bundle of selected){
      const scope=bundle.appliesTo,metadata=this.domain.ruleProjectScope(state,project),unknown=scope.projectTypes.length&&!metadata.types.length||scope.levels.length&&metadata.level==='未定级';
      if(unknown){findings.push({status:'uncovered',title:bundle.title,reason:'项目类型或级别缺少明确数据，未套用专用规则'});continue;}
      if(bundle.effectiveFrom>today||scope.projectTypes.length&&!scope.projectTypes.some(type=>metadata.types.includes(type))||scope.levels.length&&!scope.levels.includes(metadata.level)){findings.push({status:'not_applicable',title:bundle.title,reason:'不在生效日期或适用范围内'});continue;}
      for(const rule of bundle.rules){
        const base={ruleId:rule.id,ruleVersion:bundle.id+'@'+bundle.version,title:rule.title};
        if(used.has(rule.check)){findings.push({...base,status:'conflict',reason:'所选版本对同一事项重复规定，请核对版本适用关系'});continue;}used.add(rule.check);
        const rows=rule.check==='node_delivery_evidence'?nodes:deliverables;
        if(!rows.length)findings.push({...base,status:'uncovered',reason:'当前范围没有可检查的业务记录'});
        for(const row of rows){
          const finding=this.domain.evaluateCoreRule(state,rule.check,rule.check==='node_delivery_evidence'?'flowNodes':'deliverables',row.id);
          if(finding&&finding.status!=='not_applicable')findings.push({...base,...finding});
        }
      }
    }
    const at=new Date().toISOString(),report={requestId,requestHash:hash([projectId,versions]),projectId,projectTitle:project.title,basisRevision:state.revision,versions:selected.map(v=>({id:v.id,version:v.version,digest:v.digest||hash(v),evidence:v.evidence,definition:v})),checkedAt:at,findings};
    const id='rule-check-'+randomUUID();this.persist(workspaceId,{id,title:'制度检查 · '+project.title,type:'制度检查记录',projectIds:[projectId],sourceIds:[],version:1,confirmed:false,collectedAt:at,excerpt:'根据已保存资料核对；不修改正式计划、验收或节点状态。',ruleCheck:report});
    return {id,...report};
  }
}
