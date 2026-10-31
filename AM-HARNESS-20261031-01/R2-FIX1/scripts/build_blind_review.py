"""48 fixed first-repetition entries; never substitute fallback for a missing proposal."""
from pathlib import Path
import json,hashlib,random,html
TASK=Path(__file__).resolve().parents[1];manifest=json.loads((TASK/'input/evaluation-manifest.json').read_text())
projections=json.loads((TASK/'evidence/model-input-projections.json').read_text())['entries'] if (TASK/'evidence/model-input-projections.json').exists() else []
by_label={x['label']:x for x in projections};rows=[];key=[]
private=Path.home()/'.local/share/local-qwen-feishu/validation/am-harness-r2-fix1';private.mkdir(parents=True,exist_ok=True,mode=0o700)
seed_path=private/'blind-seed.json'
if not seed_path.exists():
 import secrets
 seed_path.write_text(json.dumps({'seed':secrets.randbits(128)}));seed_path.chmod(0o600)
rng=random.Random(json.loads(seed_path.read_text())['seed'])
def read(case,mode):
 p=TASK/'evidence/full-model'/f'1-{case}-{mode}.json'
 return json.loads(p.read_text()) if p.exists() else None
def normalize(text,data):
 if not text:return text
 labels={'action':'动作','knowledge':'知识候选','followup':'跟进事项','draft':'文稿','plan':'提醒计划','old_run':'之前任务','cancel_pending_action':'待取消动作','note0':'笔记一','note1':'笔记二'}
 for name,ident in (data or {}).get('setup',{}).get('native_objects',{}).items():
  if isinstance(ident,str):text=text.replace(ident,'〔'+labels.get(name,name)+'〕')
 return text
for index,case in enumerate(manifest['cases'],1):
 ident=case['case_id'];old=read(ident,'legacy');new=read(ident,'enforce');candidate=None;reason='no_candidate';candidate_hash=None
 if new:
  presentations=new.get('presentations',[])
  selected=presentations[-1] if presentations else {}
  plan=selected.get('candidate_plan')
  if plan is not None:
   candidate_hash=hashlib.sha256(json.dumps(plan,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
   for call in reversed(new.get('model_calls',[])):
    p=by_label.get(call.get('label'))
    if p and p.get('raw_plan')==plan:
     candidate=p.get('candidate_text');reason='candidate_available' if candidate else p.get('validation_error','not_renderable');break
 if candidate is not None and selected.get('selected_source') in ('candidate','source_projection','protected_projection'):
  candidate=new.get('selected_text');reason='actual_host_rendered_candidate'
 baseline=(old or {}).get('selected_text')
 left_is_candidate=bool(rng.getrandbits(1))
 texts=[normalize(candidate,new),normalize(baseline,old)] if left_is_candidate else [normalize(baseline,old),normalize(candidate,new)]
 row={'number':index,'case_id':ident,'family':case['family'],'question':normalize((new or old or {}).get('question',case['intent']),new or old),
      'original_intent':case['intent'],'known_conditions':{'设计样本描述（不是实际完成凭据）':case['evidence_or_receipt'],'实际前置差异':{k:v for k,v in (new or old or {}).get('setup',{}).items() if k not in ('native_objects','project_id','original_seed_intent')},'仍未证实的前置':({'SYN-OUT-04':'未完整证明同一已保存产物及已批准挂载关系','SYN-DOC-01':'本次主循环没有驱动异步生成到完成','SYN-DOC-02':'本次主循环没有驱动异步生成到完成','SYN-PAR-02':'分页失败以资料缺口表示，未完整注入原分页适配器第二页故障'}.get(ident))},'criteria':case['expected_behavior'],
      'a':texts[0] or '本轮没有可呈现的答复。','b':texts[1] or '本轮没有可呈现的答复。',
      'pair_available':candidate is not None and baseline is not None,'reason_if_unavailable':None if candidate is not None and baseline is not None else '固定样本保留：至少一侧未产生可呈现回复。'}
 rows.append(row);key.append({'number':index,'case_id':ident,'A':'candidate' if left_is_candidate else 'legacy','B':'legacy' if left_is_candidate else 'candidate','candidate_hash':candidate_hash,'candidate_reason':reason})
(private/'blind-key.json').write_text(json.dumps(key,ensure_ascii=False,indent=2)+'\n');(private/'blind-key.json').chmod(0o600)
folder=TASK/'blind-private';folder.mkdir(exist_ok=True);folder.chmod(0o700);(folder/'pairs.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
payload=json.dumps(rows,ensure_ascii=False).replace('<','\\u003c')
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>R2-FIX1 盲评</title><style>body{font:16px/1.65 system-ui,sans-serif;margin:0;background:#f5f7fa;color:#182333}main{max-width:1100px;margin:auto;padding:30px}h1{font-size:26px}nav{position:sticky;top:0;background:#f5f7fa;padding:12px 0;display:flex;gap:12px;align-items:center}button,select{font:inherit;padding:8px 14px;border:1px solid #b5c1d0;border-radius:7px;background:white;cursor:pointer}.answers{display:grid;grid-template-columns:1fr 1fr;gap:18px}.box{background:white;border:1px solid #dbe2eb;border-radius:10px;padding:20px;white-space:pre-wrap;overflow-wrap:anywhere}.muted{color:#526275;font-size:14px}pre{white-space:pre-wrap;font:14px/1.6 system-ui}textarea{width:100%;height:90px;box-sizing:border-box;font:inherit;padding:10px}label{margin-right:14px}@media(max-width:700px){.answers{grid-template-columns:1fr}}</style><main><h1>AM R2-FIX1 · 48 项盲评</h1><p>全部为合成场景，文字来自实际运行。候选可能未被系统采用；能展开引用时保留实际提案供判断，已选候选使用宿主实际呈现文字。请比较是否回应问题、保留事实与限定、表达清楚自然。对象编号按角色统一显示；候选缺失照实保留，未用回退答案补位。</p><p class="muted">这份材料不代表人工、手机、独立人员或正式业务已经验收。评分仅保存在此浏览器；点击导出才生成本地评分文件。</p><nav><button id="prev">上一项</button><select id="pick"></select><button id="next">下一项</button><button id="export">导出评分</button></nav><h2 id="title"></h2><p id="question"></p><details><summary>查看合成前置条件与核对要点</summary><pre id="conditions"></pre><ul id="criteria"></ul></details><p id="missing" class="muted"></p><div class="answers"><section><h3>A</h3><div id="a" class="box"></div></section><section><h3>B</h3><div id="b" class="box"></div></section></div><h3>你的判断</h3><div id="ratings"></div><p><label><input type="checkbox" id="errorA">A 有严重事实错误</label><label><input type="checkbox" id="errorB">B 有严重事实错误</label></p><textarea id="comment" placeholder="可选：需要保留或改进的地方"></textarea><p id="progress" class="muted"></p></main><script>const rows=__DATA__;const storage='am-r2-fix1-blind-__DATA_HASH__';let saved=JSON.parse(localStorage.getItem(storage)||'{}'),i=0;const $=x=>document.getElementById(x);rows.forEach((r,j)=>{let o=document.createElement('option');o.value=j;o.textContent=r.number+' / '+r.case_id;$('pick').append(o)});const choices=['A 更好','B 更好','相当','两者都不合格','无法评'];choices.forEach(v=>{let l=document.createElement('label'),r=document.createElement('input');r.type='radio';r.name='rating';r.value=v;r.onchange=save;l.append(r,document.createTextNode(v));$('ratings').append(l)});function save(){saved[rows[i].case_id]={rating:document.querySelector('[name=rating]:checked')?.value||null,severe_error_a:$('errorA').checked,severe_error_b:$('errorB').checked,comment:$('comment').value};localStorage.setItem(storage,JSON.stringify(saved));progress()}function progress(){$('progress').textContent='已选择 '+Object.values(saved).filter(x=>x.rating).length+' / 48 项。'}function show(){let r=rows[i],s=saved[r.case_id]||{};$('pick').value=i;$('title').textContent=r.number+' · '+r.case_id;$('question').textContent=r.question;$('conditions').textContent=JSON.stringify(r.known_conditions,null,2);$('criteria').replaceChildren(...r.criteria.map(x=>{let li=document.createElement('li');li.textContent=x;return li}));$('a').textContent=r.a;$('b').textContent=r.b;$('missing').textContent=r.reason_if_unavailable||'';document.querySelectorAll('[name=rating]').forEach(x=>x.checked=x.value===s.rating);$('errorA').checked=!!s.severe_error_a;$('errorB').checked=!!s.severe_error_b;$('comment').value=s.comment||'';progress()}$('prev').onclick=()=>{save();i=Math.max(0,i-1);show()};$('next').onclick=()=>{save();i=Math.min(47,i+1);show()};$('pick').onchange=()=>{save();i=+$('pick').value;show()};['errorA','errorB','comment'].forEach(x=>$(x).onchange=save);$('export').onclick=()=>{save();let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify({version:'r2-fix1-blind/1',dataset_sha256:'__DATA_HASH__',ratings:saved},null,2)],{type:'application/json'}));a.download='R2-FIX1-盲评评分.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};show();</script></html>'''.replace('__DATA__',payload).replace('__DATA_HASH__',hashlib.sha256(payload.encode()).hexdigest())
(folder/'48项盲评.html').write_text(page)
for artifact in folder.iterdir():
 if artifact.is_file():artifact.chmod(0o600)
metadata={'dataset_sha256':hashlib.sha256(payload.encode()).hexdigest(),'private_html_sha256':hashlib.sha256(page.encode()).hexdigest(),'entries':48,'first_repetition_only':True}
(private/'blind-key-metadata.json').write_text(json.dumps(metadata,indent=2)+'\n');(private/'blind-key-metadata.json').chmod(0o600)
public=TASK/'blind-public';public.mkdir(exist_ok=True)
(public/'README.md').write_text('# 48 项盲评材料\n\n固定采用正式第一轮输出，随机 A/B；未产生候选的条目保留，没有用 canonical/fallback 补位。原文评分材料在本人本机保存，未上传真实称呼与揭盲键；本审核包中的模型证据已脱敏，不能替代原文自然度评分。\n\n材料已准备不代表已评分。人评、手机、独立人员与正式业务验收分别记录。\n')
(public/'pair-index.json').write_text(json.dumps({'entries':48,'available_pairs':sum(r['pair_available'] for r in rows),'case_ids':[r['case_id'] for r in rows],'first_repetition_only':True,'dataset_sha256':hashlib.sha256(payload.encode()).hexdigest(),'naturalness':'not_evaluated','private_html_sha256':hashlib.sha256((folder/'48项盲评.html').read_bytes()).hexdigest(),'first_run_source_files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((TASK/'evidence/full-model').glob('1-*.json'))}},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'entries':48,'available_pairs':sum(r['pair_available'] for r in rows),'private_html':str(folder/'48项盲评.html'),'key_exported':False}))
