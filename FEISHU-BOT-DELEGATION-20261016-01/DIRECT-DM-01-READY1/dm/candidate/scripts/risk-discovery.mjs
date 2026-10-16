const fail = message => Object.assign(new Error(message), {status: 422});
const object = value => value && typeof value === 'object' && !Array.isArray(value);
const text = (value, max) => typeof value === 'string' && value.trim() && value.length <= max;

/** A triage result proposes ownership; it never assigns or creates business work. */
export function validateRiskTriage(value, state, priority) {
  if (value === undefined) return undefined;
  if (!object(value) || priority !== 'attention' || !['risk', 'intervention'].includes(value.kind)
      || !['normal', 'urgent'].includes(value.urgency) || !text(value.title, 200) || !text(value.impact, 1200)) {
    throw fail('风险识别须说明事项、影响和紧迫度');
  }
  const a = value.association;
  if (!object(a) || !['project', 'case', 'new_case', 'unknown'].includes(a.kind) || !text(a.reason, 1000)) {
    throw fail('请说明项目或专项的归属判断依据；无法确定时标记待确认');
  }
  const association = {kind: a.kind, reason: a.reason.trim()};
  if (['project', 'case'].includes(a.kind)) {
    const kind = a.kind === 'project' ? 'projects' : 'cases';
    const row = state[kind].find(row => row.id === a.id && !row.archived && !row.mergedIntoId);
    if (!row || kind === 'cases' && row.status === '已关闭') throw fail('建议关联的项目或专项已不可用，请重新核对');
    Object.assign(association, {id: row.id, title: row.title});
  } else if (a.kind === 'new_case') {
    if (!text(a.title, 200)) throw fail('独立专项建议需要名称');
    association.title = a.title.trim();
  }
  return {kind: value.kind, urgency: value.urgency, title: value.title.trim(), impact: value.impact.trim(), association};
}

export function riskDiscoveryContext(state) {
  return {
    candidates: [
      ...state.projects.filter(row => !row.archived).map(row => ({kind: 'project', id: row.id, title: row.title, owner: row.owner || '', description: (row.description || '').slice(0, 600)})),
      ...state.cases.filter(row => !row.archived && row.status !== '已关闭').map(row => ({kind: 'case', id: row.id, title: row.title, owner: row.owner || '', description: (row.situation || '').slice(0, 600)})),
    ],
    instructions: '仅根据实际读到的原文判断是否有风险或需要本人介入。新群、项目归属不明本身不等于风险。项目和独立专项同等对待；有风险先回传，不等待归属。attention 可附 triage={kind:risk|intervention,urgency:normal|urgent,title,impact,association:{kind:project|case|new_case|unknown,id?,title?,reason}}。归属是建议，确认前不创建或改动业务对象。普通进展用 routine。partial 或仅有链接时明确未读正文，不据此断言文档结论。',
  };
}
