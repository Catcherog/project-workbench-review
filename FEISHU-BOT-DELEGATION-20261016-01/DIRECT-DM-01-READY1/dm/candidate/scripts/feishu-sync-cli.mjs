/** Async, bounded Meegle transport for the local sync service. No shell or login. */
import {spawn} from 'node:child_process';
import {isDeepStrictEqual} from 'node:util';
import path from 'node:path';

const WRITABLE_KEYS = new Set(['name', 'description', 'field_5a13c8', 'field_d014b4', 'field_922242']);
const TEXT_TYPES = new Set(['_name', 'text', 'multi-text', 'multi-pure-text', 'link']);
const READ_COMMANDS = new Set(['auth status', 'user me', 'user search', 'workitem get', 'workitem meta-fields', 'workitem meta-types', 'workitem query', 'workflow get-node', 'workflow meta-node-fields', 'comment list']);
const WRITE_COMMANDS = new Set(['workitem update', 'workflow update-node', 'comment add']);
const MAX_PAGES = 500;
const own = (o, k) => Object.prototype.hasOwnProperty.call(o || {}, k);
const str = v => v == null ? '' : String(v);
const arr = v => Array.isArray(v) ? v : [];
const first = (...v) => v.find(x => x !== undefined && x !== null && x !== '');
const rootOf = v => v?.data && typeof v.data === 'object' && !Array.isArray(v.data) ? v.data : v;
const hostOf = v => str(v).trim().toLowerCase().replace(/\.(?=:|$)/, '');
const keyOf = f => str(first(f?.field_key, f?.key, f?.fieldKey));
const typeOf = o => str(first(o.workItemType, o.raw?.workItemType, o.raw?.work_item_type_key, o.raw?.work_item_attribute?.work_item_type?.key, o.raw?.summary?.work_item_type));
const nodeId = row => str(first(row.basic?.node_key, row.basic?.state_key, row.node_key, row.state_key, row.id));
const textCacheKey = object => JSON.stringify([object.spaceKey, typeOf(object), object.remoteKind, str(object.remoteId)]);

export class MeegleSyncError extends Error {
  constructor(code, message, {retryable = false, uncertain = false} = {}) {
    super(message); this.name = 'MeegleSyncError'; this.code = code; this.retryable = retryable; this.uncertain = uncertain;
  }
}
const fail = (code, message, options) => new MeegleSyncError(code, message, options);
const errorShape = error => ({code: error.code || 'CLI_ERROR', message: error.message || String(error), retryable: !!error.retryable, uncertain: !!error.uncertain});

function classify(code, message, writing = false) {
  const detail = `${code || ''} ${message || ''}`;
  if (/429|rate.?limit|too many|频率|限流/i.test(detail)) return fail('RATE_LIMITED', '飞书接口限流，请稍后重试。', {retryable: true});
  if (/401|unauthori[sz]ed|auth.*required|token.*(expir|invalid)|not.*authenticated|未登录|登录过期/i.test(detail)) return fail('AUTH_REQUIRED', '飞书登录已失效，请在前台重新登录。');
  if (/403|permission|forbidden|权限|无权/i.test(detail)) return fail('PERMISSION_DENIED', '当前飞书身份没有目标对象的访问权限。');
  if (/404|not.?found|不存在/i.test(detail)) return fail('NOT_FOUND', '飞书对象不存在或当前身份无法访问。');
  if (/ENOENT/.test(detail)) return fail('CLI_NOT_FOUND', '未找到 meegle CLI。');
  if (/timeout|timed.?out|ETIMEDOUT/i.test(detail)) return fail('TIMEOUT', '飞书 CLI 请求超时。', {retryable: !writing, uncertain: writing});
  if (/ECONN|ENET|EHOST|EAI_AGAIN|ENOTFOUND|network|socket|fetch failed|TLS|连接|网络/i.test(detail)) return fail('NETWORK_ERROR', '飞书 CLI 网络连接失败。', {retryable: !writing, uncertain: writing});
  return fail('CLI_ERROR', str(message || code || '飞书 CLI 执行失败。').slice(0, 500), {uncertain: writing});
}

/** runner contract: (executable, args, {signal,timeoutMs,maxOutputBytes,shell:false}). */
export function spawnMeegle(executable, args, {signal, maxOutputBytes = 16 * 1024 * 1024,cwd} = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(fail('ABORTED', '同步已取消。'));
    // Finder-launched apps may have no Node on PATH; use their bundled runtime
    // for CLI launchers with an /usr/bin/env node shebang as well.
    const child = spawn(executable, args, {shell: false, windowsHide: true,...(cwd?{cwd}:{}), stdio: ['ignore', 'pipe', 'pipe'], env: {...process.env, PATH: path.dirname(process.execPath)+path.delimiter+(process.env.PATH||'/usr/bin:/bin')}});
    let stdout = '', stderr = '', bytes = 0, settled = false, killer;
    const stop = () => { child.kill('SIGTERM'); killer = setTimeout(() => child.kill('SIGKILL'), 500); killer.unref(); };
    const finish = (error, result) => {
      if (settled) return; settled = true; signal?.removeEventListener('abort', abort);
      if (error) reject(error); else resolve(result);
    };
    const abort = () => { stop(); finish(fail('ABORTED', '同步已取消。')); };
    signal?.addEventListener('abort', abort, {once: true});
    const collect = (which, chunk) => {
      bytes += Buffer.byteLength(chunk);
      if (bytes > maxOutputBytes) { stop(); finish(fail('OUTPUT_LIMIT', '飞书 CLI 响应超出大小限制。')); return; }
      if (which === 'stdout') stdout += chunk.toString('utf8'); else stderr += chunk.toString('utf8');
    };
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', c => collect('stdout', c)); child.stderr.on('data', c => collect('stderr', c));
    child.on('error', e => finish(e));
    child.on('close', (status, signalName) => { if (killer) clearTimeout(killer); finish(null, {stdout, stderr, status, signal: signalName}); });
  });
}

function rowsOf(value) {
  const root = rootOf(value);
  if (Array.isArray(root)) return root;
  if (!root || typeof root !== 'object') throw fail('INVALID_RESPONSE', '飞书列表响应格式无效。');
  for (const k of ['list', 'items', 'results', 'records', 'nodes', 'fields', 'comments']) if (Array.isArray(root[k])) return root[k];
  const groups = Object.keys(root).filter(k => /^\d+$/.test(k) && Array.isArray(root[k]));
  if (groups.length) return groups.sort((a, b) => Number(a) - Number(b)).flatMap(k => root[k]);
  // MQL represents an empty result as data:{} and an explicit empty group list.
  if (value?.data && (Array.isArray(value.list) || value.session_id)) return [];
  throw fail('INVALID_RESPONSE', '飞书响应缺少预期的列表。');
}
function paging(value) {
  const root = rootOf(value);
  return root?.pagination || value?.pagination || root || {};
}
function morePages(value, length, size, page) {
  const p = paging(value);
  if (own(p, 'has_more')) return p.has_more === true;
  if (own(p, 'hasMore')) return p.hasMore === true;
  if (Number.isFinite(p.total)) return page * size < p.total;
  return length >= size;
}
function rawFields(raw) {
  const result = {};
  for (const key of ['workitem_fields', 'work_item_fields', 'fields', 'field_values', 'form_items']) {
    const value = raw?.[key];
    if (Array.isArray(value)) for (const field of value) {
      const fieldKey = keyOf(field); if (!fieldKey) continue;
      for (const valueKey of ['value', 'field_value', 'fieldValue']) if (own(field, valueKey)) { result[fieldKey] = field[valueKey]; break; }
    }
    else if (value && typeof value === 'object') Object.assign(result, value);
  }
  const attr = raw.work_item_attribute || {};
  if (own(attr, 'work_item_name')) result.name = attr.work_item_name;
  if (own(attr, 'work_item_status')) result.work_item_status = attr.work_item_status;
  for (const key of ['name', 'description', 'status', 'owner', 'owners', 'schedule']) if (own(raw, key)) result[key] = raw[key];
  return result;
}
function metadataEntry(row) {
  return {...row, key: keyOf(row), name: str(first(row.field_name, row.name)), valueType: str(first(row.field_type, row.type, row.valueType))};
}
function moqlField(row, key) {
  const f = arr(row.moql_field_list).find(f => f.key === key);
  if (!f) return row[key];
  const value = f.value;
  if (value == null) return null;
  if (f.value_type && own(value, f.value_type)) return value[f.value_type];
  return first(value.long_value, value.string_value, value.key_label_value, value.key_label_value_list, null);
}

export class MeegleSyncAdapter {
  constructor({cli = 'meegle', profile, host = 'project.feishu.cn', timeoutMs = 30_000, maxOutputBytes = 16 * 1024 * 1024, runner = spawnMeegle, expectedUserKey} = {}) {
    if (!cli || typeof cli !== 'string' || cli.includes('\0')) throw fail('INVALID_CONFIG', 'CLI 路径无效。');
    this.cli = cli; this.profile = profile; this.host = hostOf(host); this.timeoutMs = Math.max(10, Math.min(120_000, timeoutMs));
    this.maxOutputBytes = maxOutputBytes; this.runner = runner; this.userKey = expectedUserKey || '';
  }

  async _run(command, params, {signal, writing = false} = {}) {
    if (!(writing ? WRITE_COMMANDS : READ_COMMANDS).has(command)) throw fail('COMMAND_REJECTED', '同步执行器拒绝未许可的 CLI 命令。');
    if (signal?.aborted) throw fail('ABORTED', '同步已取消。');
    const args = [...(this.profile ? ['--profile', this.profile] : []), ...command.split(' '), ...(params ? ['--params', JSON.stringify(params)] : []), '--format', 'json'];
    const controller = new AbortController(); let timer, onAbort;
    const interruption = new Promise((_, reject) => {
      onAbort = () => { reject(fail('ABORTED', '同步已取消。', {uncertain: writing})); controller.abort(); };
      signal?.addEventListener('abort', onAbort, {once: true});
      timer = setTimeout(() => { reject(fail('TIMEOUT', '飞书 CLI 请求超时。', {retryable: !writing, uncertain: writing})); controller.abort(); }, this.timeoutMs);
    });
    try {
      const output = await Promise.race([this.runner(this.cli, args, {shell: false, signal: controller.signal, timeoutMs: this.timeoutMs, maxOutputBytes: this.maxOutputBytes}), interruption]);
      if (Buffer.byteLength(output?.stdout || '') + Buffer.byteLength(output?.stderr || '') > this.maxOutputBytes) throw fail('OUTPUT_LIMIT', '飞书 CLI 响应超出大小限制。', {uncertain: writing});
      let parsed;
      try { parsed = JSON.parse(output?.stdout || '', (_key,value,context)=>typeof value==='number'&&Number.isInteger(value)&&!Number.isSafeInteger(value)?context?.source||(()=>{throw Error('远端标识超出安全整数范围');})():value); }
      catch { if (output?.error || (output?.status ?? output?.exitCode ?? 0) !== 0) throw classify(output?.error?.code, output?.stderr || output?.error?.message, writing); throw fail('NON_JSON', '飞书 CLI 未返回有效 JSON。', {uncertain: writing}); }
      if (!parsed || typeof parsed !== 'object') throw fail('INVALID_RESPONSE', '飞书 CLI JSON 响应格式无效。', {uncertain: writing});
      const response = rootOf(parsed);
      const codes = [parsed.err_code, parsed.errCode, parsed.code, response?.err_code, response?.errCode, response?.code];
      const code = codes.find(value => value !== undefined && ![0, '0', 'OK', 'SUCCESS'].includes(value));
      const error = parsed.error || response?.error;
      const unauthenticatedStatus = command === 'auth status' && own(parsed, 'authenticated') && !error;
      if (!unauthenticatedStatus && (output?.error || (output?.status ?? output?.exitCode ?? 0) !== 0 || error || code !== undefined || parsed.success === false || response?.success === false)) {
        throw classify(first(error?.code, code, output?.error?.code), first(error?.message, typeof error === 'string' ? error : undefined, parsed.err_msg, parsed.message, response?.err_msg, output?.stderr, output?.error?.message), writing);
      }
      return parsed;
    } catch (error) { if (error instanceof MeegleSyncError) throw error; throw classify(error.code, error.message, writing); }
    finally { clearTimeout(timer); signal?.removeEventListener('abort', onAbort); }
  }

  async auth({signal} = {}) {
    const status = rootOf(await this._run('auth status', null, {signal}));
    if (status.host && hostOf(status.host) !== this.host) throw fail('HOST_MISMATCH', 'CLI 登录站点与同步目标站点不一致。');
    if (status.authenticated !== true) throw fail('AUTH_REQUIRED', '请先在前台登录飞书项目，后台不会发起登录。');
    if (!status.host) throw fail('HOST_MISMATCH', '无法确认 CLI 登录站点。');
    const identity = rootOf(await this._run('user me', null, {signal}));
    const userKey = str(first(identity.user_key, identity.userKey));
    if (!userKey) throw fail('IDENTITY_UNVERIFIED', '无法确认当前飞书登录身份。');
    if (this.userKey && this.userKey !== userKey) throw fail('IDENTITY_MISMATCH', '飞书登录身份已改变，请重新确认同步配置。');
    this.userKey = userKey;
    return {...status, authenticated: true, host: this.host, profile: this.profile || '', userKey, identity};
  }

  _validateObject(object) {
    if (!object || !['project', 'deliverable', 'node'].includes(object.remoteKind)) throw fail('UNSUPPORTED_OBJECT', '当前对象类型不支持同步。');
    if (object.system && object.system !== 'meegle') throw fail('SYSTEM_MISMATCH', '目标不是飞书项目对象。');
    if (object.host && hostOf(object.host) !== this.host) throw fail('HOST_MISMATCH', '对象站点与同步站点不一致。');
    if (!object.spaceKey || !object.remoteId) throw fail('MISSING_IDENTITY', '对象缺少远端空间或对象 ID。');
    if (object.remoteKind === 'node' && !object.parentRemoteId) throw fail('MISSING_PARENT', '节点缺少所属项目 ID。');
  }

  async _metadata(object, {signal, cache} = {}) {
    const workItemType = typeOf(object);
    if (!workItemType) throw fail('MISSING_TYPE', '对象缺少已核实的飞书工作项类型。');
    const node = object.remoteKind === 'node';
    const cacheKey = JSON.stringify([object.spaceKey, workItemType, node]);
    if (cache?.has(cacheKey)) return cache.get(cacheKey);
    const collect = async () => {
      const rows = [], seen = new Set();
      for (let page = 1; page <= MAX_PAGES; page++) {
        const value = await this._run(node ? 'workflow meta-node-fields' : 'workitem meta-fields', {project_key: object.spaceKey, work_item_type: workItemType, ...(node ? {} : {page_num: page})}, {signal});
        const pageRows = rowsOf(value), signature = JSON.stringify(pageRows);
        if (seen.has(signature) && pageRows.length) throw fail('PAGINATION_STALLED', '字段元数据分页重复，已中止。');
        seen.add(signature); rows.push(...pageRows.map(metadataEntry));
        if (!morePages(value, pageRows.length, 50, page)) return rows;
        if (node) throw fail('INCOMPLETE_METADATA', '节点字段元数据返回未完成分页，当前接口无法继续。');
      }
      throw fail('PAGINATION_LIMIT', '字段元数据分页超过安全上限。');
    };
    const promise = collect(); cache?.set(cacheKey, promise); return promise;
  }

  _readShape(object, fields, raw, metadata) {
    return {externalObjectId: object.id || object.externalObjectId || '', system: 'meegle', host: this.host, spaceKey: object.spaceKey, remoteId: str(object.remoteId), remoteKind: object.remoteKind, parentRemoteId: str(object.parentRemoteId), fields, ...(metadata ? {fieldMetadata: metadata} : {}), raw, collectedAt: new Date().toISOString(), complete: true};
  }

  async _readWorkItem(object, {signal, cache, textCache} = {}) {
    const pages = [], fields = {}, seen = new Set(); let token;
    for (let page = 1; page <= MAX_PAGES; page++) {
      const response = rootOf(await this._run('workitem get', {project_key: object.spaceKey, work_item_id: str(object.remoteId), fields: ['_all'], page_size: 200, ...(token ? {page_token: token} : {})}, {signal}));
      const attr = response.work_item_attribute || {};
      const returnedId = str(first(attr.work_item_id, response.work_item_id, response.id));
      if (returnedId !== str(object.remoteId)) throw fail('OBJECT_MISMATCH', '飞书返回的工作项 ID 与请求不一致。');
      const returnedType = str(first(attr.work_item_type?.key, response.work_item_type_key));
      if (returnedType && typeOf(object) && returnedType !== typeOf(object)) throw fail('TYPE_MISMATCH', '飞书返回的工作项类型与已登记类型不一致。');
      const returnedSpace = attr.owned_project;
      if (returnedSpace && ![returnedSpace.key, returnedSpace.simple_name].includes(object.spaceKey)) throw fail('SPACE_MISMATCH', '飞书返回的工作项所属空间与请求不一致。');
      Object.assign(fields, rawFields(response)); pages.push(response);
      const p = paging(response), next = str(first(p.next_page_token, response.next_page_token, p.nextPageToken));
      if (!next) {
        if (p.has_more === true || p.hasMore === true) throw fail('INCOMPLETE_READ', '飞书字段分页缺少下一页标识。');
        const effectiveObject = {...object, workItemType: returnedType || typeOf(object)};
        const metadata = await this._metadata(effectiveObject, {signal, cache});
        // Missing fields can mean empty OR hidden by field permissions. Preserve
        // absence; only explicit nulls may clear a previously collected value.
        const cachedText = textCache?.get(textCacheKey(effectiveObject));
        if (cachedText) for (const [key, value] of Object.entries(cachedText.fields)) if (!own(fields, key)) fields[key] = value;
        const textProof = cachedText ? cachedText.proof : await this._readOmittedText(effectiveObject, fields, metadata, {signal});
        const omittedFieldKeys = metadata.filter(field => field.key && !own(fields, field.key)).map(field => field.key);
        return this._readShape(object, fields, {workItemType: typeOf(effectiveObject), fieldPages: pages, omittedFieldKeys, textProof}, metadata);
      }
      if (seen.has(next)) throw fail('PAGINATION_STALLED', '飞书字段分页标识重复，已中止。');
      seen.add(next); token = next;
    }
    throw fail('PAGINATION_LIMIT', '飞书字段分页超过安全上限。');
  }

  async _queryRows(spaceKey, mql, {signal} = {}) {
    const rows = [], seen = new Set(); let sessionId = '', expectedTotal;
    for (let page = 1; page <= MAX_PAGES; page++) {
      const params = page === 1 ? {project_key: spaceKey, mql} : {project_key: spaceKey, session_id: sessionId, group_pagination_list: [{group_id: '1', page_num: page}]};
      const value = await this._run('workitem query', params, {signal}), pageRows = rowsOf(value);
      sessionId = str(first(value.session_id, rootOf(value)?.session_id, sessionId));
      if (page === 1) { const group = arr(value.list).find(g => arr(g.group_infos).some(i => str(i.group_id) === '1')); if (Number.isFinite(group?.count)) expectedTotal = group.count; }
      for (const row of pageRows) {
        const id = str(moqlField(row, 'work_item_id'));
        if (!id || seen.has(id)) throw fail('PAGINATION_STALLED', '文本补查分页缺少或重复工作项 ID。');
        seen.add(id); rows.push(row);
      }
      const more = expectedTotal === undefined ? morePages(value, pageRows.length, 50, page) : rows.length < expectedTotal;
      if (!more) return {rows, pages: page, sessionId};
      if (!sessionId || !pageRows.length) throw fail('INCOMPLETE_READ', '文本补查分页缺少会话或下一页内容。');
    }
    throw fail('PAGINATION_LIMIT', '文本补查分页超过安全上限。');
  }

  async _primeTextProof(objects, {signal, cache} = {}) {
    const groups = new Map(), textCache = new Map();
    for (const object of objects) {
      if (object.remoteKind === 'node' || !/^\d+$/.test(str(object.remoteId)) || !/^[\w-]+$/.test(object.spaceKey) || !/^[\w-]+$/.test(typeOf(object))) continue;
      const key = JSON.stringify([object.spaceKey, typeOf(object), object.remoteKind]);
      if (!groups.has(key)) groups.set(key, []); groups.get(key).push(object);
    }
    const batches = [...groups.values()].flatMap(group => Array.from({length: Math.ceil(group.length / 100)}, (_, index) => group.slice(index * 100, (index + 1) * 100)));
    let index = 0;
    const worker = async () => {
      while (index < batches.length) {
        const batch = batches[index++], object = batch[0];
        try {
          const metadata = await this._metadata(object, {signal, cache});
          const keys = metadata.filter(field => WRITABLE_KEYS.has(field.key) && TEXT_TYPES.has(field.valueType)).map(field => field.key);
          if (!keys.length) continue;
          const expected = new Map(batch.map(row => [str(row.remoteId), row]));
          const from = '`' + object.spaceKey + '`.`' + typeOf(object) + '`';
          const whereIds = ids => '`work_item_id` IN (' + ids.join(', ') + ')';
          const select = ['work_item_id', ...keys].map(key => '`' + key + '`').join(', ');
          const explicit = await this._queryRows(object.spaceKey, `SELECT ${select} FROM ${from} WHERE ${whereIds([...expected.keys()])}`, {signal});
          const prepared = new Map(), candidates = new Map(keys.map(key => [key, []]));
          for (const row of explicit.rows) {
            const id = str(moqlField(row, 'work_item_id')); if (!expected.has(id)) continue;
            const fields = {}, proof = [{kind: 'batch_explicit_fields', workItemType: typeOf(object), remoteId: id, row}];
            for (const key of keys) {
              const matches = arr(row.moql_field_list).filter(field => field.key === key); if (matches.length !== 1) continue;
              const field = matches[0];
              if (field.value === null) { fields[key] = null; continue; }
              if (field.value_type !== 'string_value' || !field.value || typeof field.value !== 'object') continue;
              if (own(field.value, 'string_value')) {
                if (typeof field.value.string_value === 'string' || field.value.string_value === null) fields[key] = field.value.string_value;
              } else if (!Object.keys(field.value).length) candidates.get(key).push(id);
            }
            prepared.set(id, {fields, proof});
          }
          for (const [key, ids] of candidates) {
            if (!ids.length) continue;
            const expectedNull = new Set(ids);
            const mql = `SELECT \`work_item_id\` FROM ${from} WHERE ${whereIds(ids)} AND \`${key}\` IS NULL`;
            const nullProof = await this._queryRows(object.spaceKey, mql, {signal});
            const matches = new Set(nullProof.rows.map(row => str(moqlField(row, 'work_item_id'))).filter(id => expectedNull.has(id)));
            for (const id of ids) {
              prepared.get(id).proof.push({kind: 'batch_is_null', remoteId: id, key, matched: matches.has(id), mql, pages: nullProof.pages});
              if (matches.has(id)) prepared.get(id).fields[key] = null;
            }
          }
          // Commit proof cache only after every requested page and NULL check
          // succeeds. A failed batch falls back to exact per-object queries.
          for (const [id, proof] of prepared) textCache.set(textCacheKey(expected.get(id)), proof);
        } catch (error) { if (signal?.aborted || error.code === 'ABORTED') throw error; }
      }
    };
    await Promise.all(Array.from({length: Math.min(3, batches.length)}, worker));
    return textCache;
  }

  async _readOmittedText(object, fields, metadata, {signal} = {}) {
    const keys = metadata.filter(field => WRITABLE_KEYS.has(field.key) && TEXT_TYPES.has(field.valueType) && !own(fields, field.key)).map(field => field.key);
    if (!keys.length) return [];
    // Real Meegle IDs are bigint. Do not interpolate unverified identifiers.
    if (!/^\d+$/.test(str(object.remoteId)) || !/^[\w-]+$/.test(object.spaceKey) || !/^[\w-]+$/.test(typeOf(object))) return [];
    const from = '`' + object.spaceKey + '`.`' + typeOf(object) + '`';
    const where = '`work_item_id` = ' + str(object.remoteId);
    const select = ['work_item_id', ...keys].map(key => '`' + key + '`').join(', ');
    const explicit = await this._run('workitem query', {project_key: object.spaceKey, mql: `SELECT ${select} FROM ${from} WHERE ${where}`}, {signal});
    const rows = rowsOf(explicit), proof = [{kind: 'explicit_fields', response: explicit}];
    if (rows.length !== 1 || str(moqlField(rows[0], 'work_item_id')) !== str(object.remoteId)) throw fail('OBJECT_MISMATCH', '空字段核验未返回唯一匹配的工作项。');
    const candidates = [];
    for (const key of keys) {
      const matches = arr(rows[0].moql_field_list).filter(field => field.key === key);
      if (matches.length !== 1) continue;
      const field = matches[0];
      if (field.value === null) { fields[key] = null; continue; }
      if (field.value_type !== 'string_value' || !field.value || typeof field.value !== 'object') continue;
      if (own(field.value, 'string_value')) {
        if (typeof field.value.string_value === 'string' || field.value.string_value === null) fields[key] = field.value.string_value;
      } else if (Object.keys(field.value).length === 0) candidates.push(key);
    }
    // A returned field with value:{} is not treated as null. Establish actual
    // SQL NULL semantics using IS NULL on the same known object and text keys.
    if (candidates.length) {
      const predicate = candidates.map(key => '`' + key + '` IS NULL').join(' AND ');
      const nullProof = await this._run('workitem query', {project_key: object.spaceKey, mql: `SELECT \`work_item_id\` FROM ${from} WHERE ${where} AND ${predicate}`}, {signal});
      const nullRows = rowsOf(nullProof); proof.push({kind: 'is_null', keys: candidates, response: nullProof});
      if (nullRows.length > 1 || (nullRows.length === 1 && str(moqlField(nullRows[0], 'work_item_id')) !== str(object.remoteId))) throw fail('OBJECT_MISMATCH', '空字段条件核验返回了错误工作项。');
      if (nullRows.length === 1) for (const key of candidates) fields[key] = null;
    }
    return proof;
  }

  async _nodes(object, {signal} = {}) {
    const nodes = new Map(), seenPages = new Set();
    for (let page = 1; page <= MAX_PAGES; page++) {
      const value = await this._run('workflow get-node', {project_key: object.spaceKey, work_item_id: str(object.parentRemoteId), node_id_list: ['_all'], field_key_list: ['_all'], need_sub_task: true, page_num: page}, {signal});
      const rows = rowsOf(value), signature = JSON.stringify(rows.map(nodeId));
      if (rows.length && seenPages.has(signature)) throw fail('PAGINATION_STALLED', '飞书节点分页重复，已中止。');
      seenPages.add(signature);
      for (const row of rows) {
        const id = nodeId(row); if (!id) throw fail('INVALID_RESPONSE', '飞书节点缺少节点 ID。');
        const parent = first(row.work_item_id, row.parent_work_item_id);
        if (parent != null && str(parent) !== str(object.parentRemoteId)) throw fail('PARENT_MISMATCH', '飞书节点所属项目与请求不一致。');
        if (nodes.has(id)) throw fail('PAGINATION_STALLED', '飞书节点跨页重复，不能确认完整性。');
        nodes.set(id, row);
      }
      if (!morePages(value, rows.length, 20, page)) return nodes;
    }
    throw fail('PAGINATION_LIMIT', '飞书节点分页超过安全上限。');
  }

  _normalizeNode(object, nodes) {
    const row = nodes.get(str(object.remoteId));
    if (!row) throw fail('NOT_FOUND', '所属项目中未找到已登记的飞书节点。');
    const basic = row.basic || row, fields = rawFields(row);
    if (own(basic, 'name')) fields.name = basic.name;
    if (own(basic, 'status')) fields.status = basic.status;
    if (own(row.assignees, 'owners')) fields.owners = row.assignees.owners;
    if (own(row, 'schedule')) fields.schedule = row.schedule;
    // Existing registry baselines use these canonical raw paths. Refresh both
    // the normalized view and those values, retaining missing-vs-null semantics.
    for (const key of ['basic', 'schedule', 'assignees']) if (own(row, key)) fields[`raw.${key}`] = row[key];
    return this._readShape(object, fields, {...row, workItemType: typeOf(object)});
  }

  async readObject(object, {signal} = {}) {
    this._validateObject(object); await this.auth({signal});
    return object.remoteKind === 'node' ? this._normalizeNode(object, await this._nodes(object, {signal})) : this._readWorkItem(object, {signal});
  }

  async readObjects(objects, {signal, onProgress, includeComments = false} = {}) {
    await this.auth({signal});
    const reads = [], errors = [], discoveries = [], cache = new Map(), nodeGroups = new Map(), jobs = [], validObjects = [];
    for (const object of objects) {
      try { this._validateObject(object); }
      catch (error) { errors.push({externalObjectId: object?.id || object?.externalObjectId || '', error: errorShape(error)}); continue; }
      validObjects.push(object);
      if (object.remoteKind === 'node') {
        const key = JSON.stringify([object.spaceKey, object.parentRemoteId]);
        if (!nodeGroups.has(key)) nodeGroups.set(key, []); nodeGroups.get(key).push(object);
      } else jobs.push({objects: [object], run: async () => {
        const read = await this._readWorkItem(object, {signal, cache, textCache});
        if (includeComments) {
          try { read.comments = (await this._readComments(object, {signal})).comments; }
          catch (error) { if (error.code === 'ABORTED') throw error; errors.push({externalObjectId: object.id || object.externalObjectId, scope: 'comments', error: errorShape(error)}); }
        }
        return [read];
      }});
    }
    for (const group of nodeGroups.values()) jobs.push({objects: group, run: async () => {
      const nodes = await this._nodes(group[0], {signal});
      const registered = new Set(group.map(object => str(object.remoteId)));
      for (const [id, row] of nodes) if (!registered.has(id)) discoveries.push({system: 'meegle', host: this.host, spaceKey: group[0].spaceKey, remoteKind: 'node', remoteId: id, parentRemoteId: str(group[0].parentRemoteId), title: str(row.basic?.name || row.name), raw: {...row, workItemType: typeOf(group[0])}});
      return group.map(object => { try { return this._normalizeNode(object, nodes); } catch (error) { return {failed: true, object, error}; } });
    }});
    const textCache = await this._primeTextProof(validObjects, {signal, cache});
    let index = 0;
    const worker = async () => {
      while (index < jobs.length) {
        if (signal?.aborted) throw fail('ABORTED', '同步已取消。');
        const job = jobs[index++];
        try {
          for (const read of await job.run()) {
            if (read.failed) errors.push({externalObjectId: read.object.id || read.object.externalObjectId, error: errorShape(read.error)});
            else reads.push(read);
          }
        } catch (error) {
          if (error.code === 'ABORTED') throw error;
          for (const object of job.objects) errors.push({externalObjectId: object.id || object.externalObjectId, error: errorShape(error)});
        }
        onProgress?.({completed: reads.length + errors.filter(error => error.scope !== 'comments').length, total: objects.length, reads: reads.length, errors: errors.length});
      }
    };
    await Promise.all(Array.from({length: Math.min(3, jobs.length)}, worker));
    return {reads, errors, discoveries};
  }

  async writeFields(object, patches, {signal, beforeWrite} = {}) {
    this._validateObject(object);
    if (!Array.isArray(patches) || !patches.length) throw fail('EMPTY_PATCH', '没有可写入的字段。');
    const seen = new Set();
    for (const patch of patches) {
      if (!WRITABLE_KEYS.has(patch.remoteFieldKey) || seen.has(patch.remoteFieldKey)) throw fail('FIELD_NOT_WRITABLE', '该字段不在已许可的文本写回范围内。');
      if (!own(patch, 'before') || typeof patch.proposed !== 'string') throw fail('INVALID_PATCH', '文本写回必须包含审核前原值及字符串新值。');
      if (patch.proposed.length > 100_000) throw fail('INVALID_PATCH', '单个写回字段超过长度限制。');
      seen.add(patch.remoteFieldKey);
    }
    await this.auth({signal});
    const metadata = await this._metadata(object, {signal});
    for (const patch of patches) {
      const field = metadata.find(f => f.key === patch.remoteFieldKey);
      if (!field || !TEXT_TYPES.has(field.valueType) || field.read_only === true || field.is_read_only === true || field.disabled === true) throw fail('FIELD_NOT_WRITABLE', '实时飞书字段配置不支持此文本写回。');
      if (object.remoteKind === 'node' && patch.remoteFieldKey === 'name') throw fail('FIELD_NOT_WRITABLE', '节点名称不是可写自定义字段。');
    }
    const fresh = object.remoteKind === 'node' ? this._normalizeNode(object, await this._nodes(object, {signal})) : await this._readWorkItem(object, {signal});
    for (const patch of patches) if (!isDeepStrictEqual(fresh.fields[patch.remoteFieldKey], patch.before)) throw fail('REMOTE_CONFLICT', '飞书原值在审核后已变化，请重新审核。');
    const params = {project_key: object.spaceKey, work_item_id: str(object.remoteKind === 'node' ? object.parentRemoteId : object.remoteId), ...(object.remoteKind === 'node' ? {node_id: str(object.remoteId)} : {}), fields: patches.map(patch => ({field_key: patch.remoteFieldKey, field_value: patch.proposed}))};
    // No await between this final local approval check and spawning the update.
    // This lets the service reject edits/remapping during the remote preflight.
    if (beforeWrite) {
      if (typeof beforeWrite !== 'function') throw fail('INVALID_GUARD', '写回前校验必须为同步函数。');
      const guardResult = beforeWrite();
      if (guardResult && typeof guardResult.then === 'function') {
        Promise.resolve(guardResult).catch(() => {});
        throw fail('INVALID_GUARD', '写回前校验不能异步执行。');
      }
    }
    const result = await this._run(object.remoteKind === 'node' ? 'workflow update-node' : 'workitem update', params, {signal, writing: true});
    // Acknowledgement only. The service must independently read back the value.
    return {acknowledged: true, verified: false, result};
  }

  async readComments(object, {signal, since, until} = {}) {
    this._validateObject(object); await this.auth({signal});
    return this._readComments(object, {signal, since, until});
  }

  async lookupUsers(object,userKeys,{signal}={}) {
    this._validateObject(object);await this.auth({signal});
    if(!Array.isArray(userKeys)||!userKeys.length||userKeys.length>20||userKeys.some(key=>typeof key!=='string'||!key.trim()))throw fail('INVALID_USER','缺少明确的负责人身份');
    const value=await this._run('user search',{project_key:object.spaceKey,user_keys:userKeys},{signal});
    return rowsOf(value);
  }

  async addComment(object,content,{signal}={}) {
    this._validateObject(object);
    if(object.remoteKind!=='deliverable'||typeof content!=='string'||!content.trim()||content.length>12000)throw fail('INVALID_COMMENT','评论必须对应明确的交付物与正文');
    await this.auth({signal});
    return this._run('comment add',{project_key:object.spaceKey,work_item_id:str(object.remoteId),content,action:'create'},{signal,writing:true});
  }

  async _readComments(object, {signal, since, until} = {}) {
    for(const value of [since,until])if(value!==undefined&&(!Number.isSafeInteger(value)||value<0))throw fail('INVALID_TIME','评论读取范围必须是毫秒时间戳');
    const comments = [], seen = new Set();
    for (let page = 1; page <= MAX_PAGES; page++) {
      const value = await this._run('comment list', {project_key: object.spaceKey, work_item_id: str(object.remoteKind === 'node' ? object.parentRemoteId : object.remoteId), page_num: page,...(since===undefined?{}:{start_time:since}),...(until===undefined?{}:{end_time:until})}, {signal});
      const rows = rowsOf(value), signature = JSON.stringify(rows);
      if (rows.length && seen.has(signature)) throw fail('PAGINATION_STALLED', '飞书评论分页重复，已中止。');
      seen.add(signature); comments.push(...rows);
      if (!morePages(value, rows.length, 20, page)) return {comments, complete: true, collectedAt: new Date().toISOString()};
    }
    throw fail('PAGINATION_LIMIT', '飞书评论分页超过安全上限。');
  }

  async discover({spaceKey, workItemTypes = [], includeUpdated = false}, {signal} = {}) {
    if (!spaceKey || !/^[\w-]+$/.test(spaceKey)) throw fail('INVALID_SCOPE', '发现范围必须是已确认的空间 key。');
    if (!workItemTypes.length) return {objects: [], complete: true};
    await this.auth({signal});
    const available = rowsOf(await this._run('workitem meta-types', {project_key: spaceKey}, {signal}));
    const objects = [];
    for (const type of workItemTypes) {
      const key = typeof type === 'string' ? type : type.key || type.workItemType;
      const remoteKind = typeof type === 'string' ? '' : type.remoteKind;
      if (!/^[\w-]+$/.test(key || '') || !['project', 'deliverable'].includes(remoteKind)) throw fail('INVALID_SCOPE', '发现范围缺少已确认的工作项类型或对象类别。');
      if (!available.some(t => str(first(t.type_key, t.work_item_type_key, t.key)) === key)) throw fail('TYPE_MISMATCH', '配置的发现类型不在当前空间类型列表中。');
      const metadata=includeUpdated?await this._metadata({spaceKey,remoteKind,raw:{workItemType:key}},{signal}):[];
      const extra=includeUpdated?['updated_at',...(remoteKind==='deliverable'?['field_f7b70e','field_69751f']:[])].filter(k=>metadata.some(f=>f.key===k)):[];
      let sessionId = '', expectedTotal = null; const seen = new Set();
      for (let page = 1; page <= MAX_PAGES; page++) {
        const params = page === 1 ? {project_key: spaceKey, mql: 'SELECT `work_item_id`, `name`'+extra.map(k=>', `'+k+'`').join('')+' FROM `' + spaceKey + '`.`' + key + '`'} : {project_key: spaceKey, session_id: sessionId, group_pagination_list: [{group_id: '1', page_num: page}]};
        const value = await this._run('workitem query', params, {signal}), rows = rowsOf(value);
        sessionId = str(first(value.session_id, rootOf(value)?.session_id, sessionId));
        if (page === 1) { const count = arr(value.list).find(g => arr(g.group_infos).some(i => str(i.group_id) === '1'))?.count; if (Number.isFinite(count)) expectedTotal = count; }
        for (const row of rows) {
          const id = str(moqlField(row, 'work_item_id'));
          if (!id || seen.has(id)) throw fail('PAGINATION_STALLED', '工作项发现分页包含缺失或重复 ID。');
          const stamp=moqlField(row,'updated_at'),updatedAt=stamp&&typeof stamp==='object'?stamp.iso_time??stamp.timestamp??'':stamp??'';
          const projectRemoteIds=[...new Set(['field_f7b70e','field_69751f'].map(k=>moqlField(row,k)).map(v=>v&&typeof v==='object'?String(v.key??v.id??v.value??''):String(v??'')).filter(Boolean))];
          seen.add(id); objects.push({system: 'meegle', host: this.host, spaceKey, remoteKind, remoteId: id, parentRemoteId: '', raw: {workItemType: key, summary: row}, title: str(moqlField(row, 'name')),updatedAt,projectRemoteIds});
        }
        const more = expectedTotal == null ? morePages(value, rows.length, 50, page) : seen.size < expectedTotal;
        if (!more) break;
        if (!rows.length || !sessionId) throw fail('INCOMPLETE_READ', '工作项发现分页尚未完整返回。');
        if (page === MAX_PAGES) throw fail('PAGINATION_LIMIT', '工作项发现分页超过安全上限。');
      }
    }
    return {objects, complete: true};
  }
}
