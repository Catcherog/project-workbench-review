"""Differentiable scalar-gated delta rule using short triangular blocks.

This is the same recurrence as mlx_lm.models.gated_delta.gated_delta_ops,
reassociated in FP32. No token is discarded and recurrent state crosses every
block. Only the training reference path is replaced. Inference kernels stay
unchanged. Unsupported mask/vector-gate paths use the original implementation.
"""
import json
import math
import time
from pathlib import Path
import mlx.core as mx
import mlx_lm.models.gated_delta as gd

ORIGINAL = gd.gated_delta_ops
CHUNK_SIZE = 32

def _unit_lower_inverse(A):
    """Stable recursive block solve; avoid cancellation in a Neumann series."""
    n=A.shape[-1]
    assert n & (n-1)==0
    blocks=mx.broadcast_to(mx.ones((1,1),dtype=mx.float32),(*A.shape[:-2],n,1,1))
    size=1
    while size<n:
        left=blocks[...,0::2,:,:]
        right=blocks[...,1::2,:,:]
        cross=mx.stack([A[...,start+size:start+2*size,start:start+size] for start in range(0,n,2*size)],axis=-3)
        lower=-(right @ cross) @ left
        top=mx.concatenate([left,mx.zeros_like(left)],axis=-1)
        bottom=mx.concatenate([lower,right],axis=-1)
        blocks=mx.concatenate([top,bottom],axis=-2)
        size*=2
    return blocks[...,0,:,:]

@mx.compile
def _block(q, k, v, g, beta, state):
    # Layout B,H,T,D. For delta u_t:
    # (I+A)u = beta*v - beta*exp(G)*k*S0^T,
    # A[t,i] = beta[t] * <k_t,k_i> * exp(G_t-G_i), i<t.
    n = q.shape[-2]
    log_g = mx.log(mx.maximum(g, 1e-30))
    G = mx.cumsum(log_g, axis=-1)
    strict = mx.arange(n)[:, None] > mx.arange(n)[None, :]
    causal = mx.arange(n)[:, None] >= mx.arange(n)[None, :]
    difference = G[..., :, None] - G[..., None, :]
    decay = mx.exp(mx.minimum(difference, 0)) * causal
    A = (k @ mx.swapaxes(k, -1, -2)) * decay * beta[..., :, None] * strict
    # A Neumann-series inverse is algebraically valid but numerically unstable
    # for highly correlated keys and beta/g near 1. Recursive triangular solves
    # avoid the large intermediate powers and their catastrophic cancellation.
    inverse = _unit_lower_inverse(A)
    expG = mx.exp(G)
    rhs = beta[..., :, None] * (v - expG[..., :, None] * (k @ mx.swapaxes(state, -1, -2)))
    u = inverse @ rhs
    attention = (q @ mx.swapaxes(k, -1, -2)) * decay
    y = expG[..., :, None] * (q @ mx.swapaxes(state, -1, -2)) + attention @ u
    tail = mx.exp(mx.minimum(G[..., -1:] - G, 0))
    state = mx.exp(G[..., -1, None, None]) * state + mx.swapaxes(u * tail[..., :, None], -1, -2) @ k
    return y, state

def chunk_gated_delta_ops(q, k, v, g, beta, state=None, mask=None):
    if mask is not None or g.ndim != 3:
        return ORIGINAL(q, k, v, g, beta, state, mask)
    B, T, Hk, Dk = q.shape
    Hv, Dv = v.shape[-2:]
    original_dtype = q.dtype
    if state is None:
        state = mx.zeros((B, Hv, Dv, Dk), mx.float32)
    if Hv != Hk:
        assert Hv % Hk == 0
        q, k = mx.repeat(q, Hv // Hk, -2), mx.repeat(k, Hv // Hk, -2)
    q, k, v = [x.astype(mx.float32).transpose(0, 2, 1, 3) for x in (q, k, v)]
    g, beta = [x.astype(mx.float32).transpose(0, 2, 1) for x in (g, beta)]
    output = []
    for start in range(0, T, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE, T)
        length=end-start
        qc,kc,vc=[x[:,:,start:end] for x in (q,k,v)]
        gc,bc=g[:,:,start:end],beta[:,:,start:end]
        if length<CHUNK_SIZE:
            pad=CHUNK_SIZE-length
            qc,kc,vc=[mx.pad(x,[(0,0),(0,0),(0,pad),(0,0)]) for x in (qc,kc,vc)]
            gc=mx.pad(gc,[(0,0),(0,0),(0,pad)],constant_values=1)
            bc=mx.pad(bc,[(0,0),(0,0),(0,pad)])
        y, state = _block(qc,kc,vc,gc,bc,state)
        output.append(y[:,:,:length])
    return mx.concatenate(output, axis=2).transpose(0, 2, 1, 3).astype(original_dtype), state

def install():
    gd.gated_delta_ops = chunk_gated_delta_ops

def verify():
    mx.random.seed(12425)
    records = []
    for T, Hk, Hv, D, dtype in [(7,2,4,8,mx.float32),(35,2,2,16,mx.float32),(70,2,4,16,mx.float32),(97,2,4,32,mx.bfloat16)]:
        q = mx.random.normal((1,T,Hk,D)) / D
        k = mx.random.normal((1,T,Hk,D)); k = k / mx.sqrt(mx.sum(k*k,axis=-1,keepdims=True)+1e-6)
        v = mx.random.normal((1,T,Hv,D))
        q,k,v=[x.astype(dtype) for x in (q,k,v)]
        g = mx.random.uniform(low=0.15, high=0.99, shape=(1,T,Hv))
        beta = mx.sigmoid(mx.random.normal((1,T,Hv))).astype(dtype)
        state = mx.random.normal((1,Hv,D,D)) * 0.1
        args = [q,k,v,g,beta,state]
        ref, rs = ORIGINAL(*args)
        got, gs = chunk_gated_delta_ops(*args)
        mx.eval(ref,rs,got,gs)
        diff = float(mx.max(mx.abs(ref.astype(mx.float32)-got.astype(mx.float32))))
        state_diff = float(mx.max(mx.abs(rs-gs)))
        tolerance = 0.002 if dtype==mx.bfloat16 else 2e-5
        assert diff<tolerance and state_diff<2e-5, (T,diff,state_diff)
        row = {'tokens':T,'key_heads':Hk,'value_heads':Hv,'dtype':str(dtype),'max_output_abs_error':diff,'max_state_abs_error':state_diff}
        if dtype==mx.float32:
            def objective(fn,*a):
                y,s=fn(*a)
                return mx.sum(y*y)*0.13+mx.sum(s*s)*0.07
            gr = mx.grad(lambda *a:objective(ORIGINAL,*a),argnums=list(range(6)))(*args)
            gg = mx.grad(lambda *a:objective(chunk_gated_delta_ops,*a),argnums=list(range(6)))(*args)
            mx.eval(gr,gg)
            errors=[float(mx.max(mx.abs(a-b))) for a,b in zip(gr,gg)]
            assert max(errors)<1e-4, errors
            row['gradient_abs_errors_q_k_v_g_beta_state']=errors
        records.append(row)
    # A zero decay must reset history, without NaN from log(0).
    args[3]=mx.zeros_like(args[3])
    y,s=chunk_gated_delta_ops(*args); ry,rs=ORIGINAL(*args)
    mx.eval(y,s,ry,rs)
    assert bool(mx.all(mx.isfinite(y))) and float(mx.max(mx.abs(y-ry)))<0.002
    A=mx.tril(mx.ones((1,32,32))*.99,-1)
    inverse=_unit_lower_inverse(A)
    reference_inverse=mx.linalg.tri_inv(mx.eye(32)+A,upper=False,stream=mx.cpu)
    mx.eval(inverse,reference_inverse)
    inverse_error=float(mx.max(mx.abs(inverse-reference_inverse)))
    assert inverse_error<2e-6,inverse_error
    out={'status':'pass','chunk_size':CHUNK_SIZE,'solver':'stable recursive unit-lower triangular block solve','reference':'Installed MLX-LM gated_delta_ops','checks':records,'high_correlation_inverse_max_error':inverse_error,'zero_gate_finite':True,'real_full_model_test':'pending'}
    (Path(__file__).resolve().parents[1]/'provenance/chunk_delta_validation.json').write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))

if __name__=='__main__': verify()
