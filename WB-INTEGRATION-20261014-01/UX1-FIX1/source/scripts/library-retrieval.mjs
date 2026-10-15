import {readFileSync,realpathSync,statSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';

const defaultRoot=fileURLToPath(new URL('..',import.meta.url));
const digest=value=>createHash('sha256').update(value).digest('hex');
const allowedKinds=new Set(['fixed-rule','template-guidance','template-catalog','template-master-snapshot','user-confirmed-rules-and-source-navigation']);
const safeUrl=value=>{try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)?u.href:'';}catch{return '';}};

/** Read-only local knowledge. No import into sources, directory crawl, network or
 * user-supplied path. Every body must match its current catalog registration. */
export class LibraryRetrieval {
  constructor({root=defaultRoot}={}){this.root=path.resolve(root);}
  read(relative){
    if(typeof relative!=='string'||path.isAbsolute(relative)||relative.split(/[\\/]/).includes('..')||! /^(docs\/(library|reference)\/|output\/)/.test(relative)||relative.includes('/history/')||! /\.(md|txt|json)$/.test(relative))throw Error('资料路径不在登记范围');
    const real=realpathSync(path.join(this.root,relative)),root=realpathSync(this.root);
    if(!real.startsWith(root+path.sep)||statSync(real).size>4*1024*1024)throw Error('资料超出范围或大小限制');
    return readFileSync(real,'utf8');
  }
  snapshot(){
    const documents=[],gaps=[];
    let catalog;
    try{catalog=JSON.parse(this.read('docs/library/catalog.json'));if(![1,2].includes(catalog.schemaVersion)||!Array.isArray(catalog.entries)||catalog.entries.length>400)throw Error();}
    catch{return {documents,gaps:['本地 Library 目录不可用；未读取未登记文件'],available:false};}
    const ids=new Set(),ambiguous=new Set();
    const add=(entry,metadata,parent=null)=>{
      if(!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,149}$/.test(metadata.id||'')||typeof metadata.title!=='string'||!metadata.title.trim()||metadata.title.length>300||!String(metadata.version??''))throw Error('资料身份或版本无效');
      if(ids.has(metadata.id)){ambiguous.add(metadata.id);throw Error('重复的资料身份');}ids.add(metadata.id);
      const text=this.read(metadata.path);
      if(!/^[a-f0-9]{64}$/.test(metadata.sha256||'')||digest(text)!==metadata.sha256)throw Error('正文与登记指纹不一致');
      const library={id:metadata.id,path:metadata.path,version:String(metadata.version||''),sha256:metadata.sha256,kind:entry.kind,
        snapshotDate:metadata.snapshotDate||'',originalAvailability:entry.originalAvailability?.status||'',catalogEntryId:entry.id};
      const fingerprint=digest(JSON.stringify([library,entry,parent]));
      const limitations=['本地已登记快照，未核验远端后续版本'];
      if(entry.originalAvailability?.status==='missing')limitations.push('原始文件缺失；本轮使用已核对的提取副本');
      documents.push({id:'library:'+metadata.id,title:metadata.title,text,version:library.version,library,fingerprint,url:safeUrl(metadata.url),limitations});
    };
    for(const entry of catalog.entries){
      if(!entry||typeof entry!=='object'){gaps.push('Library 目录有无效登记，本轮跳过');continue;}
      if(entry.lifecycle!=='current'||!allowedKinds.has(entry.kind))continue;
      try{
        if(entry.kind==='template-catalog'){
          const raw=this.read(entry.path);if(digest(raw)!==entry.sha256)throw Error('模板目录指纹变化');
          const pack=JSON.parse(raw);if(!Array.isArray(pack.templates)||pack.templates.length>200)throw Error('模板目录格式无效');
          for(const t of pack.templates){
            try{if(typeof t.markdown_path!=='string'||path.isAbsolute(t.markdown_path)||t.markdown_path.split(/[\\/]/).includes('..'))throw Error('模板路径超出范围');
              add(entry,{id:entry.id+':'+t.number,path:path.posix.join(path.posix.dirname(entry.path),t.markdown_path),title:t.name,version:t.revision,sha256:t.sha256,url:t.url,snapshotDate:pack.snapshot_date},t);
            }catch{gaps.push('Library 模板“'+String(t?.number||'未命名')+'”缺失、路径无效或指纹不符，本轮不引用');}
          }
        }else add(entry,{id:entry.id,path:entry.path,title:entry.title,version:entry.version,sha256:entry.sha256,url:entry.sourceUrl});
      }catch{gaps.push('Library 资料“'+String(entry.title||entry.id)+'”缺失、路径无效或指纹不符，本轮不引用');}
    }
    // Duplicate identities are ambiguous even when one copy appeared earlier.
    const counts=new Map();for(const e of catalog.entries)if(e&&typeof e==='object')counts.set(e.id,(counts.get(e.id)||0)+1);
    return {documents:documents.filter(d=>counts.get(d.library.catalogEntryId)===1&&!ambiguous.has(d.library.id)),gaps,available:true};
  }
  current(evidence){return this.snapshot().documents.some(d=>d.id===evidence.sourceId&&d.fingerprint===evidence.fingerprint);}
  citation(evidence){
    const doc=this.snapshot().documents.find(d=>d.id===evidence.sourceId&&d.fingerprint===evidence.fingerprint);
    if(!doc)return null;
    const {start,end}=evidence.locator||{};
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end>doc.text.length||end<=start)return null;
    return {text:doc.text.slice(start,end),title:doc.title,version:doc.version,path:doc.library.path};
  }
}
