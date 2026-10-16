import {mkdtemp,writeFile,readFile,rm,realpath} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {homedir,tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {spawnMeegle} from './feishu-sync-cli.mjs';
import {extractChatFile} from './case-evidence-reader.mjs';
const root=fileURLToPath(new URL('..',import.meta.url));
const bundled=path.join(homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3');
export async function readIntakeFile(attachment,{signal,runner=spawnMeegle,python=process.env.PM_INTAKE_PYTHON||bundled}={}){
  const folder=await mkdtemp(path.join(tmpdir(),'pm-intake-file-'));
  try{
    const ext=path.extname(attachment.name).toLowerCase(),input=path.join(folder,'original'+ext);await writeFile(input,attachment.bytes,{mode:0o600});
    let result={text:'',images:[],limitations:[],complete:true};
    if(['.txt','.md','.csv','.tsv','.json','.log','.html','.htm'].includes(ext)){
      if(['.html','.htm'].includes(ext)){try{result.text=extractChatFile(attachment.bytes,attachment.name).content;}catch(error){if(!error.message.includes('未提取到可读正文'))throw error;}}
      else {try{result.text=new TextDecoder('utf-8',{fatal:true}).decode(attachment.bytes);}catch{throw Error('文件不是可识别的UTF-8文本，原件已保留');}}
      if(Buffer.byteLength(result.text)>2*1024*1024)throw Error('正文超过2MB，原件已保留');
    }
    if(!['.txt','.md','.csv','.tsv','.json','.log'].includes(ext)){
      if(!existsSync(python))throw Error('文档读取组件不可用，原件已保留；请核对本机Python组件路径');
      const out=await runner(python,[path.join(root,'scripts/intake-file-reader.py'),input,attachment.name,folder],{signal,maxOutputBytes:2*1024*1024,shell:false});
      let parsed;try{parsed=JSON.parse(out.stdout);}catch{throw Error('文档读取未返回有效结果，原件已保留');}
      if(parsed.error||(out.status??out.exitCode??0)!==0)throw Error(parsed.error||'文档读取失败，原件已保留');
      result={...parsed,text:result.text||parsed.text};
      const canonicalFolder=await realpath(folder);
      result.images=await Promise.all(parsed.images.map(async image=>{if(path.dirname(await realpath(image.path))!==canonicalFolder)throw Error('图像路径不属于本次读取范围');return {label:image.label,bytes:await readFile(image.path),mime:'image/png'};}));
    }
    if(!result.text.trim()&&!result.images.length)throw Error('文件没有可读正文或图像');
    return result;
  }finally{await rm(folder,{recursive:true,force:true});}
}
