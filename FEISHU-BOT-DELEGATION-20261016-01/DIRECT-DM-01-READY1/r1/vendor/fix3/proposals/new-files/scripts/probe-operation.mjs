export class OperationStopped extends Error{
  constructor(phase,reason){super(phase+':'+reason);this.phase=phase;this.reason=reason;}
}

/** Bounds the logical operation even if an adapter ignores AbortSignal. */
export function bounded(phase,fn,{timeoutMs,signal,onUnderlying}={}){
  if(signal?.aborted)return Promise.reject(new OperationStopped(phase,'cancelled'));
  return new Promise((resolve,reject)=>{
    const controller=new AbortController();let finished=false,timer;
    const cleanup=()=>{clearTimeout(timer);signal?.removeEventListener('abort',cancel);};
    const settle=(f,x)=>{if(finished)return;finished=true;cleanup();f(x);};
    const cancel=()=>{settle(reject,new OperationStopped(phase,'cancelled'));controller.abort();};
    signal?.addEventListener('abort',cancel,{once:true});
    if(signal?.aborted){cancel();return;}
    timer=setTimeout(()=>{settle(reject,new OperationStopped(phase,'timeout'));controller.abort();},timeoutMs);
    const work=Promise.resolve().then(()=>{if(controller.signal.aborted)throw new OperationStopped(phase,'cancelled');return fn(controller.signal);});
    onUnderlying?.(work);
    work.then(v=>settle(resolve,v),e=>settle(reject,e));
  });
}
