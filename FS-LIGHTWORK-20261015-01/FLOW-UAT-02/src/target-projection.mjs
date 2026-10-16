import { createHash } from 'node:crypto';

const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const localDate = ms => new Date(ms + 8 * 3600000).toISOString().slice(0, 10);
export function projectRows(outputs, scope, runId, updatedAt) {
  if (outputs.length !== 2 || new Set(outputs.map(x => x.mode)).size !== 2) throw Error('missing_period_mode');
  const rows = outputs.flatMap(out => {
    if (!['week', 'month'].includes(out.mode) || out.unit !== 'hour' || out.timeZone !== 'Asia/Shanghai' ||
        out.errors.length || out.pending.length || out.cells.length !== 1 || out.rowsRead !== 1) throw Error('source_not_ready');
    const c = out.cells[0];
    if (c.kind !== 'actual' || c.hours === null || !/^(0|[1-9]\d*)(\.\d+)?$/.test(c.hours) ||
        c.person.id !== scope.sourcePersonId || c.rows.length !== 1) throw Error('unexpected_source_cell');
    const r = c.rows[0];
    if (r.person.id !== scope.sourcePersonId || r.source.workItemId !== scope.sourceItemId ||
        r.source.type !== scope.sourceType || r.source.space !== scope.sourceProjectKey ||
        r.registrationId !== scope.sourceRegistrationId || r.ownership.projectRef !== null ||
        r.ownership.label !== '非项目' || !r.note.includes('合成')) throw Error('source_scope_mismatch');
    const hours = Number(c.hours);
    if (!Number.isFinite(hours) || hours < 0 || Math.abs(hours) > Number.MAX_SAFE_INTEGER || String(hours)!==c.hours) throw Error('unsafe_hours');
    const fingerprint = digest({source:r.source,person:r.person.id,start:r.startInclusive,end:r.endExclusive,hours:r.hours,version:r.version,registration:r.registrationId});
    return {
      '汇总键':`actual|${scope.aliasId}|${out.mode}|${c.period.key}`,
      '数据集':'sample','记录类型':'aggregate','待登记事项数':0,'来源事项数':1,
      '人员':scope.aliasName,'人员键':scope.aliasId,'口径':'actual','周期类型':out.mode,
      '周期':c.period.label,'周期开始':localDate(c.period.startInclusive),'周期结束不含':localDate(c.period.endExclusive),
      '实际小时':hours,'来源行数':c.rows.length,'非项目事项数':c.nonProjectItemCount,
      '范围说明':'已覆盖来源小计，不代表全部投入；合成测试登记，不代表员工真实劳动量',
      '覆盖缺口':out.coverageGaps.map(g => `${g.source}: ${g.status}${Number.isInteger(g.total) ? ` (${g.total}条)` : ''}`).join('；') || '仅覆盖已授权测试样本',
      '来源摘要':`T02合成测试登记；非项目；原发生期${localDate(r.startInclusive)}—${localDate(r.endInclusive)}；原小时${r.hours}；非逐日实测`,
      '来源版本':String(r.version),'来源指纹':fingerprint,'读取时间':r.readAt,
      '更新时间':updatedAt,'运行标识':runId,'刷新结果':'success_partial',
    };
  });
  if (new Set(rows.map(r=>r['来源指纹'])).size !== 1) throw Error('week_month_source_mismatch');
  return rows;
}

export function planWrites(desired, existing, ownedRecordIds = []) {
  const desiredKeys = new Set(desired.map(r=>r['汇总键']));
  if (desiredKeys.size !== desired.length) throw Error('duplicate_desired_key');
  const seen = new Map();
  for (const r of existing) {
    const key = r['汇总键'];
    if (!desiredKeys.has(key)) throw Error('unexpected_target_key');
    if (!r.record_id || seen.has(key)) throw Error('duplicate_target_key');
    if (!ownedRecordIds.includes(r.record_id)) throw Error('target_record_not_owned');
    seen.set(key,r.record_id);
  }
  return desired.map(fields=>({recordId:seen.get(fields['汇总键'])??null,fields}));
}
