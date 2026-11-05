import { promises as fs, constants } from 'node:fs';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { canonical, digest, sign, verifySigned } from './canonical.mjs';
import { LedgerError } from './errors.mjs';

const ID = /^[A-Za-z0-9_-]{8,96}$/;
const METHODS = new Set(['snapshot', 'prepare', 'revise', 'present', 'approve', 'status', 'review', 'reminder']);
const AUDIENCE = 'am-ledger-workbench';
const MAX_FILE = 8 * 1024 * 1024;

function sessionKey(session) {
  return digest({ id: session.id, userId: session.userId, tenantId: session.tenantId, workspaceId: session.workspaceId,
    projectIds: [...session.projectIds].sort(), scopes: [...session.scopes].sort() });
}

export class SignedQueueBridge {
  constructor({ queueDir, keyFile, clock = Date.now, timeoutMs = 12000, pollMs = 100 }) {
    if (!queueDir || !keyFile) throw new LedgerError('am_unconfigured', 'AM 接入位置尚未配置。', 503);
    this.queueDir = resolve(queueDir); this.keyFile = resolve(keyFile);
    this.clock = clock; this.timeoutMs = timeoutMs; this.pollMs = pollMs;
  }

  async init() {
    const dir = await fs.lstat(this.queueDir);
    if (!dir.isDirectory() || dir.isSymbolicLink() || (dir.mode & 0o022) ||
        (process.getuid && dir.uid !== process.getuid()) || await fs.realpath(this.queueDir) !== this.queueDir) {
      throw new LedgerError('unsafe_am_queue', 'AM 队列目录不满足当前账号的接入条件。', 503);
    }
    this.key = await this.readPrivate(this.keyFile, 4096);
    if (this.key.length < 32) throw new LedgerError('invalid_am_key', 'AM 接入密钥未达到要求。', 503);
    return this;
  }

  async readPrivate(path, limit = MAX_FILE) {
    const handle = await fs.open(path, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
    try {
      const stat = await handle.stat();
      if (!stat.isFile() || (stat.mode & 0o077) || stat.size > limit || (process.getuid && stat.uid !== process.getuid())) {
        throw new LedgerError('unsafe_am_file', 'AM 接入文件的权限或大小不符合要求。', 503);
      }
      return await handle.readFile();
    } finally { await handle.close(); }
  }

  paths(id) {
    if (!ID.test(id)) throw new LedgerError('invalid_request_id', '请求标识无效。', 422);
    const base = join(this.queueDir, 'wb-' + id);
    return { request: base + '.request.json', result: base + '.result.json', meta: base + '.ledger-meta.json' };
  }

  async atomicCreate(path, value) {
    const temp = path + '.' + randomUUID() + '.tmp';
    const handle = await fs.open(temp, 'wx', 0o600);
    try { await handle.writeFile(canonical(value), 'utf8'); await handle.sync(); }
    finally { await handle.close(); }
    try { await fs.link(temp, path); }
    finally { await fs.unlink(temp); }
  }

  async call(method, params, session, { requestId = randomUUID(), context = {} } = {}) {
    if (!this.key) await this.init();
    if (!METHODS.has(method)) throw new LedgerError('invalid_method', '不支持此 AM 操作。', 422);
    const now = this.clock();
    if (session.expiresAtMs <= now) throw new LedgerError('session_expired', '当前身份已过期，请刷新后继续。', 401);
    const paths = this.paths(requestId);
    const binding = { method, params, sessionKey: sessionKey(session), scopes: [...session.scopes].sort(), context };
    const fingerprint = digest(binding);
    const meta = { fingerprint, sessionKey: binding.sessionKey, method, context, issuedAtMs: now, expiresAtMs: Math.min(now + 60000, session.expiresAtMs) };
    try { await this.atomicCreate(paths.meta, meta); }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const original = JSON.parse((await this.readPrivate(paths.meta)).toString('utf8'));
      if (original.fingerprint !== fingerprint) throw new LedgerError('idempotency_conflict', '同一请求标识对应的内容已变化，请先核对原结果。', 409);
      return this.waitForResult(requestId, session);
    }
    const envelope = {
      schema: 'am-workbench.rpc/v1', requestId, method,
      issuedAtMs: now, expiresAtMs: meta.expiresAtMs, audience: AUDIENCE,
      session: { id: session.id, userId: session.userId, tenantId: session.tenantId,
        expiresAtMs: session.expiresAtMs, scopes: [...session.scopes].sort(),
        workspaceId: session.workspaceId, projectIds: [...session.projectIds].sort() }, params
    };
    envelope.signature = sign(envelope, this.key);
    // Existing operator_step consumes exactly this queue. No dispatcher is started here.
    // expires_at is an integer in seconds; the signed envelope retains millisecond precision.
    try {
      await this.atomicCreate(paths.request, { operation: 'workbench', expires_at: Math.ceil(meta.expiresAtMs / 1000), envelope });
    } catch (error) {
      if (error.code !== 'EEXIST') throw new LedgerError('queue_write_unknown', '提交结果尚未明确，请查询原请求。', 503, { requestId });
    }
    return this.waitForResult(requestId, session);
  }

  async peek(requestId, session) {
    if (!this.key) await this.init();
    if (session.expiresAtMs <= this.clock()) throw new LedgerError('session_expired', '当前身份已过期。', 401);
    const paths = this.paths(requestId);
    let meta;
    try { meta = JSON.parse((await this.readPrivate(paths.meta)).toString('utf8')); }
    catch (error) { if (error.code === 'ENOENT') throw new LedgerError('unknown_request', '没有找到本次请求。', 404); throw error; }
    if (meta.sessionKey !== sessionKey(session)) throw new LedgerError('request_scope_mismatch', '当前会话不能读取这次请求。', 403);
    let outer;
    try { outer = JSON.parse((await this.readPrivate(paths.result)).toString('utf8')); }
    catch (error) {
      if (error.code === 'ENOENT') return { state: 'pending', requestId, expired: this.clock() > meta.expiresAtMs, context: meta.context, method: meta.method };
      throw error;
    }
    const result = outer.workbench || outer;
    if (!verifySigned(result, this.key) || result.schema !== 'am-workbench.rpc-result/v1' ||
        result.requestId !== requestId || result.method !== meta.method || result.audience !== AUDIENCE ||
        !Number.isSafeInteger(result.serverTimeMs) || result.serverTimeMs < meta.issuedAtMs - 5000 || result.serverTimeMs > this.clock() + 5000) {
      throw new LedgerError('invalid_am_receipt', 'AM 回执未通过来源核对，请保留原请求等待核实。', 502, { requestId });
    }
    if (!result.ok) throw new LedgerError(result.error?.code || 'am_rejected', 'AM 未采用本次操作，请刷新相关信息后核对。', result.error?.status || 409, { requestId });
    if(meta.method==='snapshot' && Number.isSafeInteger(result.data?.expiresAtMs) && result.data.expiresAtMs<=this.clock())
      throw new LedgerError('snapshot_expired','这份资料已过读取时效，请重新读取当前来源。',409,{requestId});
    if(['prepare','revise'].includes(meta.method) && result.data?.previewId &&
        (!Number.isSafeInteger(result.data.expiresAtMs) || result.data.expiresAtMs<=this.clock()))
      throw new LedgerError('preview_expired','本次预览已到期，请重新核对来源并生成预览。',409,{requestId});
    return { state: 'complete', requestId, data: result.data, context: meta.context, method: meta.method };
  }

  async waitForResult(requestId, session) {
    const started = Date.now();
    while (Date.now() - started < this.timeoutMs) {
      const outcome = await this.peek(requestId, session);
      if (outcome.state === 'complete') return outcome.data;
      if (outcome.expired) throw new LedgerError('rpc_expired', 'AM 尚未确认本次请求；请查询原请求，勿重复提交执行。', 409, { requestId });
      await delay(this.pollMs);
    }
    throw new LedgerError('rpc_pending', 'AM 正在处理，本次请求已保留。', 202, { requestId, pollUrl: '/api/v2/ledger/operations/' + requestId });
  }
}
