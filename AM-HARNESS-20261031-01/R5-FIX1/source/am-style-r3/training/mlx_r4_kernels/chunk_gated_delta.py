"""R4 scoped training-only delta-rule helper, derived from the sealed R3 code.

Numerical validation must execute on the actual MLX build before any model load.
Importing or static-testing this module is not evidence that validation passed.
"""
from contextlib import contextmanager
import hashlib
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


@contextmanager
def patched_training_kernel():
    if gd.gated_delta_ops is not ORIGINAL:
        raise RuntimeError("Another delta-rule patch is already active")
    gd.gated_delta_ops = chunk_gated_delta_ops
    try:
        yield
    finally:
        gd.gated_delta_ops = ORIGINAL


def validate_numerics(text_config):
    """Run real forward/state/VJP checks; return evidence only after all pass."""
    fields = ("linear_num_key_heads", "linear_num_value_heads",
              "linear_key_head_dim", "linear_value_head_dim")
    if any(type(text_config.get(k)) is not int or text_config[k] < 1 for k in fields):
        raise RuntimeError("Exact scalar-gate head dimensions are required for kernel validation")
    hk, hv, dk, dv = [text_config[k] for k in fields]
    if hv % hk:
        raise RuntimeError("Unsupported key/value head ratio")
    mx.random.seed(12425)
    checks = []
    shapes = [(1, 31, 2, 6, 16, 8, mx.float32),
              (2, 32, 2, 2, 16, 8, mx.float32),
              (1, 33, 2, 6, 16, 8, mx.float32),
              (1, 33, hk, hv, dk, dv, mx.float32),
              (1, 33, hk, hv, dk, dv, mx.bfloat16)]
    for batch, tokens, key_heads, value_heads, key_dim, value_dim, dtype in shapes:
        q = (mx.random.normal((batch, tokens, key_heads, key_dim)) / key_dim).astype(dtype)
        k = mx.random.normal((batch, tokens, key_heads, key_dim))
        k = (k / mx.sqrt(mx.sum(k * k, axis=-1, keepdims=True) + 1e-6)).astype(dtype)
        v = mx.random.normal((batch, tokens, value_heads, value_dim)).astype(dtype)
        g = mx.random.uniform(low=0.15, high=0.99, shape=(batch, tokens, value_heads))
        beta = mx.sigmoid(mx.random.normal((batch, tokens, value_heads))).astype(dtype)
        state = mx.random.normal((batch, value_heads, value_dim, key_dim)) * 0.1
        args = (q, k, v, g, beta, state)
        ref, ref_state = ORIGINAL(*args)
        got, got_state = chunk_gated_delta_ops(*args)
        mx.eval(ref, ref_state, got, got_state)
        bf16 = dtype == mx.bfloat16
        output_atol, grad_atol, rtol = (0.003, 0.003, 0.02) if bf16 else (2e-5, 1e-4, 2e-4)
        def checked_difference(a, b, atol):
            if not bool(mx.all(mx.isfinite(a))) or not bool(mx.all(mx.isfinite(b))):
                raise RuntimeError("Non-finite kernel parity result")
            a, b = a.astype(mx.float32), b.astype(mx.float32)
            max_abs = float(mx.max(mx.abs(a - b)))
            if not bool(mx.allclose(a, b, atol=atol, rtol=rtol)):
                raise RuntimeError(f"Kernel parity failed: shape={(batch,tokens,key_heads,value_heads,key_dim,value_dim)}, dtype={dtype}, max_abs={max_abs}, atol={atol}, rtol={rtol}; do not widen automatically")
            return max_abs
        output_error = checked_difference(ref, got, output_atol)
        state_error = checked_difference(ref_state, got_state, output_atol)
        def objective(fn, *a):
            y, s = fn(*a)
            # Float32 objective avoids bf16 reduction/overflow concealing gradients.
            return mx.sum(y.astype(mx.float32) ** 2) * 0.13 + mx.sum(s.astype(mx.float32) ** 2) * 0.07
        reference_grads = mx.grad(lambda *a: objective(ORIGINAL, *a), argnums=list(range(6)))(*args)
        candidate_grads = mx.grad(lambda *a: objective(chunk_gated_delta_ops, *a), argnums=list(range(6)))(*args)
        mx.eval(reference_grads, candidate_grads)
        errors = [checked_difference(a, b, grad_atol) for a, b in zip(reference_grads, candidate_grads)]
        checks.append({"shape": [batch, tokens, key_heads, value_heads, key_dim, value_dim],
                       "dtype": str(dtype), "output_max_abs": output_error, "state_max_abs": state_error,
                       "gradient_max_abs_q_k_v_g_beta_state": errors,
                       "output_atol": output_atol, "gradient_atol": grad_atol, "rtol": rtol})
    # Check chunk boundaries, high-correlation triangular solve and zero decay.
    A = mx.tril(mx.ones((1, CHUNK_SIZE, CHUNK_SIZE)) * 0.99, -1)
    inverse = _unit_lower_inverse(A)
    residual = (mx.eye(CHUNK_SIZE) + A) @ inverse - mx.eye(CHUNK_SIZE)
    mx.eval(residual)
    residual_error = float(mx.max(mx.abs(residual)))
    if not residual_error < 2e-6:
        raise RuntimeError("High-correlation triangular inverse residual exceeded tolerance")
    zero_args = list(args); zero_args[3] = mx.zeros_like(args[3])
    zero_output, zero_state = chunk_gated_delta_ops(*zero_args)
    original_output, original_state = ORIGINAL(*zero_args)
    mx.eval(zero_output, zero_state, original_output, original_state)
    if not bool(mx.allclose(zero_output, original_output, atol=0.003, rtol=0.02)):
        raise RuntimeError("Zero-decay forward parity failed")
    if not bool(mx.all(mx.isfinite(zero_state))) or not bool(mx.allclose(zero_state, original_state, atol=2e-5, rtol=2e-4)):
        raise RuntimeError("Zero-decay recurrent-state parity failed")
    # Mask/vector-gate inputs intentionally take the exact upstream path.
    mask = mx.ones((args[0].shape[0], args[0].shape[1]), dtype=mx.bool_)
    fallback, fallback_state = chunk_gated_delta_ops(*args, mask=mask)
    expected, expected_state = ORIGINAL(*args, mask=mask)
    mx.eval(fallback, fallback_state, expected, expected_state)
    if not bool(mx.array_equal(fallback, expected)) or not bool(mx.array_equal(fallback_state, expected_state)):
        raise RuntimeError("Masked fallback differs from the original implementation")
    vector_args = list(args)
    vector_args[3] = mx.broadcast_to(args[3][..., None], (*args[3].shape, args[0].shape[-1]))
    vector_output, vector_state = chunk_gated_delta_ops(*vector_args)
    expected, expected_state = ORIGINAL(*vector_args)
    mx.eval(vector_output, vector_state, expected, expected_state)
    if not bool(mx.array_equal(vector_output, expected)) or not bool(mx.array_equal(vector_state, expected_state)):
        raise RuntimeError("Vector-gate fallback differs from the original implementation")
    return {"status": "passed_on_actual_mlx", "numerical_validation_executed": True,
            "patch_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "original_module_sha256": hashlib.sha256(Path(gd.__file__).read_bytes()).hexdigest(),
            "checks": checks, "high_correlation_inverse_residual": residual_error,
            "zero_decay_forward_checked": True, "zero_decay_state_checked": True, "zero_decay_jacobian_claimed": False,
            "masked_fallback_identical": True, "vector_fallback_identical": True,
            "full_model_gradient_equivalence": "not_established"}
