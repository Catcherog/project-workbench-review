import { createHash, createHmac, timingSafeEqual } from 'node:crypto';
import { LedgerError } from './errors.mjs';

// Python sort_keys sorts Unicode code points; JS default sorting uses UTF-16.
function compareKeys(a, b) {
  const x = Array.from(a, c => c.codePointAt(0)), y = Array.from(b, c => c.codePointAt(0));
  for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}
export function canonical(value) {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    return '{' + Object.keys(value).sort(compareKeys).map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  }
  throw new LedgerError('invalid_wire_value', '接口仅接受明确的 JSON 值和安全整数。', 422);
}
export const digest = value => createHash('sha256').update(canonical(value), 'utf8').digest('hex');
export const sign = (value, key) => createHmac('sha256', key).update(canonical(value), 'utf8').digest('hex');
export function verifySigned(envelope, key) {
  if (!envelope || typeof envelope.signature !== 'string' || !/^[a-f0-9]{64}$/.test(envelope.signature)) return false;
  const { signature, ...payload } = envelope;
  const expected = sign(payload, key);
  return timingSafeEqual(Buffer.from(signature, 'hex'), Buffer.from(expected, 'hex'));
}
