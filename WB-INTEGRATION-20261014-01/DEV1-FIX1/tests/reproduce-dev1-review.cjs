/** Isolated executable review: real DEV1 TS/TSX bodies; minimal deterministic hook/JSX and HTTP substitutes.
 * NOT React, browser, original HTTP/SQLite, or a real-send test. No package installation.
 */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
function installedTypeScript(){
 try{return require('typescript');}catch{}
 for(const dir of (process.env.PATH||'').split(path.delimiter)){
  try{const bin=fs.realpathSync(path.join(dir,'tsc'));return require(path.resolve(path.dirname(bin),'..'));}catch{}
 }
 throw Error('Existing TypeScript required. No installation is performed.');
}
const ts=installedTypeScript();
const expectFixed=process.argv.includes('--expect-fixed');
const root=process.env.DEV1_SOURCE_ROOT||process.cwd();
const source=name=>fs.readFileSync(path.join(root,'app/integration',name),'utf8');
const jsx=(type,props,key)=>({type,props:props||{},key});
const compile=(name,customRequire)=>{
 const out=ts.transpileModule(source(name),{fileName:name,compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const module={exports:{}};vm.runInNewContext(out,{module,exports:module.exports,require:customRequire,console,sessionStorage:{getItem:()=>null,setItem:()=>{}},crypto:{randomUUID:()=>crypto.randomUUID()},setTimeout,clearTimeout},{filename:name});return module.exports;
};
const model=compile('core-collaboration-model.ts',()=>{throw Error('unexpected import')});
const receipt=compile('receipt-presentation.ts',()=>{throw Error('unexpected import')});
const client=compile('core-collaboration-client.ts',()=>model);
const msg=(id='m1',extra={})=>({id,workItemId:'i1',title:'合成 '+id,text:'原完整正文',fingerprint:'fp1',stage:'pending_review',executionOwner:'ai',recipient:{id:'ou_test',localId:'p1',name:'合成收件人',channel:'private'},approvalHistory:[],...extra});
const item=()=>({id:'i1',title:'合成事项',version:1,projectNames:['测试项目'],core:{admission:'candidate'}});
const initial=()=>({people:[{id:'p1',title:'合成收件人',identityVerified:true}],groups:[],items:[item()],runs:[{id:'b1',version:1,projectNames:['测试项目'],items:[msg()]}],inputs:[],notices:[]});
const children=x=>Array.isArray(x)?x:x?.props?.children===undefined?[]:[x.props.children];
const walk=function*(node){if(Array.isArray(node)){for(const n of node)yield*walk(n);return;}if(!node||typeof node!=='object')return;yield node;for(const c of children(node))yield*walk(c);};
const content=node=>Array.isArray(node)?node.map(content).join(''):typeof node==='string'||typeof node==='number'?String(node):node&&typeof node==='object'?content(node.props.children):'';
function mount(data){
 let slots=[],cursor=0,pendingEffects=[],tree,revision=1;const posts=[];const refs={data};
 const same=(a,b)=>a&&b&&a.length===b.length&&a.every((x,i)=>Object.is(x,b[i]));
 const hooks={
  useState(init){const i=cursor++;if(!slots[i])slots[i]={value:typeof init==='function'?init():init};return [slots[i].value,fn=>{slots[i].value=typeof fn==='function'?fn(slots[i].value):fn}];},
  useRef(init){const i=cursor++;return (slots[i]??={current:init});},
  useCallback(fn,deps){const i=cursor++;if(!slots[i]||!same(slots[i].deps,deps))slots[i]={fn,deps};return slots[i].fn;},
  useEffect(fn,deps){const i=cursor++;if(!slots[i]||!same(slots[i].deps,deps)){const prev=slots[i];slots[i]={deps};pendingEffects.push(()=>{prev?.cleanup?.();slots[i].cleanup=fn();});}}
 };
 const panel=compile('core-collaboration-panel.tsx',name=> name==='react'?hooks:name==='react/jsx-runtime'?{jsx,jsxs:jsx,Fragment:'fragment'}:name==='./core-collaboration-model'?model:name==='./core-collaboration-client'?client:receipt);
 const request=async(url,body)=>{if(body!==undefined){posts.push(structuredClone(body));return {};}return structuredClone(refs.data);};
 function render(){cursor=0;tree=panel.CoreCollaborationPanel({workspaceId:'w',revision,request});const effects=pendingEffects;pendingEffects=[];effects.forEach(f=>f());return tree;}
 async function flush(){for(let i=0;i<5;i++){await new Promise(r=>setImmediate(r));render();}}
 const find=(predicate,node=tree)=>[...walk(node)].find(predicate);
 const button=(text,node=tree)=>find(n=>n.type==='button'&&content(n)===text,node);
 const card=id=>find(n=>n.props['data-message-id']===id);
 const checkbox=id=>find(n=>n.type==='input'&&n.props.type==='checkbox',card(id));
 const check=async node=>{assert.ok(node);assert.ok(!node.props.disabled,'actual checkbox must be enabled');node.props.onChange({target:{checked:true}});await flush();};
 const click=async node=>{assert.ok(node);assert.ok(!node.props.disabled,'actual button must be enabled');node.props.onClick();await flush();};
 const reread=async()=>{await click(button('重新读取当前记录'));};
 render();return {flush,button,card,checkbox,check,click,reread,find,refs,posts,render,get tree(){return tree},get error(){return [...walk(tree)].filter(n=>n.props.role==='alert').map(content).join(';')}};
}
(async()=>{
 const results=[];
 {const h=mount(initial());await h.flush();await h.check(h.checkbox('m1'));h.refs.data.runs[0].items[0].fingerprint='fp2';h.refs.data.runs[0].items[0].text='其他窗口新正文';await h.reread();assert.equal(h.checkbox('m1').props.checked,false);await h.check(h.checkbox('m1'));await h.click(h.button('保存本批所选决定（不发送）'));if(expectFixed){assert.equal(h.error,'');assert.equal(h.posts.length,1);assert.equal(h.posts[0].decisions.length,1);assert.equal(h.posts[0].decisions[0].fingerprint,'fp2');}else{assert.match(h.error,/所选预览指纹已变化/);assert.equal(h.posts.length,0);}results.push({id:'B01-fingerprint',expectedFixed:expectFixed,verified:true,posts:h.posts.length,error:h.error});}
 {const h=mount(initial());await h.flush();let label=h.find(n=>n.type==='label'&&content(n).startsWith('将「'));await h.check(h.find(n=>n.type==='input',label));h.refs.data.items[0].version=2;await h.reread();label=h.find(n=>n.type==='label'&&content(n).startsWith('将「'));const box=h.find(n=>n.type==='input',label);assert.equal(box.props.checked,false);await h.check(box);await h.click(h.button('保存本批所选决定（不发送）'));if(expectFixed){assert.equal(h.error,'');assert.equal(h.posts.length,1);assert.equal(h.posts[0].admissions.length,1);assert.equal(h.posts[0].admissions[0].expectedVersion,2);}else{assert.match(h.error,/候选版本或纳入状态已变化/);assert.equal(h.posts.length,0);}results.push({id:'B01-admission',expectedFixed:expectFixed,verified:true,posts:h.posts.length,error:h.error});}
 {const data=initial();data.runs[0].items.push(msg('m2'));const h=mount(data);await h.flush();await h.check(h.checkbox('m1'));h.refs.data.runs[0].items[0].stage='approved';h.refs.data.runs[0].items[0].approvedHash='fp1';await h.reread();assert.equal(h.checkbox('m1'),undefined);await h.check(h.checkbox('m2'));await h.click(h.button('保存本批所选决定（不发送）'));if(expectFixed){assert.equal(h.error,'');assert.equal(h.posts.length,1);assert.equal(h.posts[0].decisions.length,1);assert.equal(h.posts[0].decisions[0].id,'m2');}else{assert.match(h.error,/旧批准不重复保存/);assert.equal(h.posts.length,0);}results.push({id:'B01-stage',expectedFixed:expectFixed,verified:true,posts:h.posts.length,error:h.error});}
 for(const stage of ['cancelled','readback_verified']){
  const data=initial();data.runs[0].items.push(msg('m2',{stage:'approved',approvedHash:'fp1'}));const h=mount(data);await h.flush();const textarea=h.find(n=>n.type==='textarea',h.card('m1'));textarea.props.onChange({target:{value:'未保存的本地草稿'}});await h.flush();h.refs.data.runs[0].items[0].stage=stage;await h.reread();assert.equal(h.button('放弃本地修改，使用当前预览',h.card('m1')),undefined);assert.equal(h.find(n=>n.type==='textarea',h.card('m1')),undefined);const exec=h.button('执行本批已批准消息 · 1 条');assert.ok(exec.props.disabled);assert.match(content(h.tree),/本批有未保存或过期草稿/);if(expectFixed){const discard=h.button('放弃这份本地草稿（不改变消息）',h.card('m1'));assert.ok(discard);await h.click(discard);assert.equal(h.button('执行本批已批准消息 · 1 条').props.disabled,false);assert.equal(h.refs.data.runs[0].items[0].stage,stage);assert.equal(h.posts.length,0);}else{assert.equal(h.button('放弃这份本地草稿（不改变消息）',h.card('m1')),undefined);}results.push({id:'B02-'+stage,expectedFixed:expectFixed,verified:true,executionDisabled:h.button('执行本批已批准消息 · 1 条').props.disabled,posts:h.posts.length});
 }
 const report={mode:expectFixed?'FIX-CANDIDATE local verification':'DEV1 as-is bug reproduction',scope:'Actual source TSX handlers + TS modules, deterministic hook/JSX/HTTP substitutes; no actual React/browser/server',sourceSha256:Object.fromEntries(['core-collaboration-model.ts','core-collaboration-client.ts','core-collaboration-panel.tsx','receipt-presentation.ts'].map(n=>[n,require('node:crypto').createHash('sha256').update(source(n)).digest('hex')])),results,issueGroups:2};fs.writeFileSync(path.join(process.env.DEV1_REVIEW_OUTPUT||__dirname,expectFixed?'candidate-recovery-results.json':'reproduction-results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
