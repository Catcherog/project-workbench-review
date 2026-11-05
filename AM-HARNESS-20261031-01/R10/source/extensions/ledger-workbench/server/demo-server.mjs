import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {randomBytes} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {dirname,join} from 'node:path';
import {DemoBridge} from '../demo/demo-bridge.mjs';
import {createLedgerHandler} from './ledger-handler.mjs';
import {LedgerError} from './errors.mjs';

const root=dirname(dirname(fileURLToPath(import.meta.url)));
export async function startDemo({port=0,bridge=new DemoBridge()}={}){
  const csrf=randomBytes(24).toString('hex'),cookie=randomBytes(24).toString('hex');
  const session={verified:true,id:'demo-session',userId:'demo-owner',tenantId:'demo-tenant',workspaceId:'ledger-demo',projectIds:['*'],
    scopes:['ledger:read','am:prepare','am:approve','review:resolve','reminder:manage'],expiresAtMs:Date.now()+86400000};
  let origin;
  const api=createLedgerHandler({bridge,getSession(req){
    if(!String(req.headers.cookie||'').split(';').some(v=>v.trim()==='demo_session='+cookie))throw new LedgerError('login_required','请先打开开发预览。',401);
    return session;
  },authorizeMutation(req){
    if(req.headers.origin!==origin||req.headers['x-demo-csrf']!==csrf)throw new LedgerError('csrf_rejected','请从当前预览页面确认。',403);
  }});
  const server=createServer(async(req,res)=>{
    try{
      if(req.headers.host!==new URL(origin).host){res.writeHead(403);res.end('Loopback host required');return;}
      if(await api(req,res))return;
      const path=new URL(req.url,origin).pathname;
      if(req.method!=='GET'){res.writeHead(405);res.end();return;}
      if(path==='/'){
        const html='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="demo-csrf" content="'+csrf+'"><title>单页台账开发预览</title><link rel="stylesheet" href="/ledger-demo.css"></head><body><div id="root"></div><script src="/ledger-demo.js"></script></body></html>';
        res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Set-Cookie':'demo_session='+cookie+'; HttpOnly; SameSite=Strict; Path=/',
          'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"});res.end(html);return;
      }
      if(['/ledger-demo.js','/ledger-demo.css'].includes(path)) {
        const bytes=await readFile(join(root,'dist',path.slice(1)));
        res.writeHead(200,{'Content-Type':path.endsWith('.js')?'text/javascript; charset=utf-8':'text/css; charset=utf-8','Cache-Control':'no-store'});res.end(bytes);return;
      }
      res.writeHead(404);res.end();
    }catch{res.writeHead(500,{'Content-Type':'text/plain; charset=utf-8'});res.end('开发预览未构建或暂时不可用。');}
  });
  await new Promise(resolve=>server.listen(port,'127.0.0.1',resolve));
  origin='http://127.0.0.1:'+server.address().port;
  return {server,origin,bridge,close:()=>new Promise(resolve=>server.close(resolve))};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  const port=Number(process.env.LEDGER_DEMO_PORT||5487);
  const demo=await startDemo({port});console.log('Synthetic-only development preview: '+demo.origin);
}
