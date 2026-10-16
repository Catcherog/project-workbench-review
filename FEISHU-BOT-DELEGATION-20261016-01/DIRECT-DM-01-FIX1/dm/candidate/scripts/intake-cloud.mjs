import {createHash} from 'node:crypto';
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
export async function readIntakeCloud({client,domain,state,url,signal}){
  const resource=domain.safeFeishuResource(url);if(!resource||!['docx','wiki'].includes(resource.type))throw Error('此链接不是已支持的飞书云文档入口');
  const identity=await client.identity({signal});
  const response=await client.run(['docs','+fetch','--doc',resource.url,'--doc-format','markdown','--scope','full','--as','user'],{signal}),doc=response?.document;
  if(!doc?.document_id||typeof doc.content!=='string'||resource.type==='docx'&&doc.document_id!==resource.token)throw Error('云文档正文或身份未通过核对');
  if(Buffer.byteLength(doc.content)>2*1024*1024)throw Error('云文档正文超过2MB，本次保留链接供核对');
  const after=await client.identity({signal});if(identity.scope!==after.scope||identity.userId!==after.userId)throw Error('读取期间飞书账号已变化，未采用这次结果');
  const bindings=[];
  for(const target of state.deliverables){const carriers=domain.getDeliverableDocuments(state,target).carriers;for(const kind of ['templates','results'])for(const item of carriers[kind].items)if(item.token===resource.token&&item.documentType===resource.type||item.documentType==='docx'&&item.token===doc.document_id)bindings.push({targetId:target.id,kind});}
  const template=bindings.some(b=>b.kind==='templates'),knownCarrier=template?'template':bindings.length?'result':'';
  const images=/!\[|<image\b|<img\b|\[图片/.test(doc.content),cloudDocument={url:resource.url,documentId:doc.document_id,revision:doc.revision_id??null,scope:identity.scope,accountId:identity.userId,bindings};
  return {name:String(doc.title||'飞书云文档').slice(0,200),inputHash:hash([identity.scope,identity.userId,doc.document_id,doc.title||'',doc.revision_id??null,bindings,doc.content]),knownCarrier,cloudDocument,parsed:{text:doc.content,images:[],complete:!images,limitations:['本批读取云文档正文快照，未读取评论或还原原版式',...(images?['正文含图像引用，云文档内图片尚未在本入口展开']:[])]}};
}
