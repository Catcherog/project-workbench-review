import React from 'react';
import {createRoot} from 'react-dom/client';
import {LedgerWorkbench} from '../web/LedgerWorkbench';
import {createLedgerHostRequest} from '../web/host-adapter';
import {readLedgerResponse} from '../web/request-error';
import './host-theme.css';

const token=document.querySelector<HTMLMetaElement>('meta[name="demo-csrf"]')?.content;
async function send(path:string,body?:Record<string,unknown>){
  const response=await fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json','X-Demo-CSRF':token||''},...(body===undefined?{}:{body:JSON.stringify(body)})});
  return readLedgerResponse(response);
}
const request=createLedgerHostRequest({load:path=>send(path),post:(path,body)=>send(path,body)});
createRoot(document.getElementById('root')!).render(<React.StrictMode>
  <div className="demo-host"><header className="demo-banner">推进工作台 · 单页台账开发预览 <span>全部为演示数据 · 确认不会实际发送</span></header>
    <main><LedgerWorkbench request={request}/></main></div>
</React.StrictMode>);
