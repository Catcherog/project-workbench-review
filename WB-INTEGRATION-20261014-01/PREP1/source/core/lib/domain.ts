export type Kind =
  | "projects"
  | "milestones"
  | "dependencies"
  | "risks"
  | "decisions"
  | "actions"
  | "sources"
  | "judgments";
export type Item = {
  id: string;
  title: string;
  projectIds: string[];
  sourceIds: string[];
  [key: string]: any;
};
export type Candidate = {
  id: string;
  category: string;
  kind: Kind;
  targetId: string;
  field: string;
  value: string;
  before: string;
  baseValue: string;
  evidence: string;
  sourceId: string;
  projectIds: string[];
  status: "pending" | "accepted" | "ignored";
  mode: string;
  acceptedAt?: string;
  appliedValue?: string;
};
export type Publication = {
  id: string;
  objectId: string;
  kind: "task" | "report";
  mode: "simulation";
  targetId: string;
  targetUrl: string;
  content: string;
  status: "failed" | "success";
  attempts: { time: string; result: string; reason: string }[];
  createdAt: string;
  sourceIds: string[];
  feedbackIds: string[];
};
export type State = {
  schemaVersion: number;
  revision: number;
  demo: boolean;
  seedDate: string;
  projects: Item[];
  milestones: Item[];
  dependencies: Item[];
  risks: Item[];
  decisions: Item[];
  actions: Item[];
  sources: Item[];
  judgments: Item[];
  candidates: Candidate[];
  publications: Publication[];
  audit: {
    id: string;
    time: string;
    operation: string;
    objectId: string;
    before: unknown;
    after: unknown;
  }[];
};
export const today = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
export const shift = (n: number) => {
  const d = new Date(today() + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
export const delta = (a: string, b: string) =>
  Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
export const uid = (p: string) => p + "-" + crypto.randomUUID();
export const collections: Kind[] = [
  "projects",
  "milestones",
  "dependencies",
  "risks",
  "decisions",
  "actions",
  "sources",
  "judgments",
];
export const labels: Record<Kind, string> = {
  projects: "项目",
  milestones: "里程碑",
  dependencies: "依赖",
  risks: "风险与问题",
  decisions: "决策事项",
  actions: "行动项",
  sources: "信息来源",
  judgments: "项目判断",
};
export const rec = (
  id: string,
  title: string,
  projectIds: string[],
  sourceIds: string[],
  rest: Record<string, any> = {},
): Item => ({ id, title, projectIds, sourceIds, ...rest });
export function lookup(s: State, id: string): Item | undefined {
  for (const k of collections) {
    const x = s[k].find((x) => x.id === id);
    if (x) return x;
  }
}
export const kindOf = (s: State, id: string) =>
  collections.find((k) => s[k].some((x) => x.id === id));
export const related = (s: State, k: Kind, p: string) =>
  s[k].filter((x) => x.projectIds.includes(p));
export function taskDraft(s: State, id: string) {
  const a = s.actions.find((x) => x.id === id);
  if (!a) throw Error("行动不存在");
  return `【模拟飞书任务】\n标题：${a.title}\n工作说明：${a.title}\n实际执行人：${a.executor || "待指定"}\n截止日期：${a.dueAt || "待指定"}\n验收要求：${a.acceptance}\n相关来源：${a.sourceIds.map((x) => `${lookup(s, x)?.title} [${x}] ${lookup(s, x)?.url || "链接待补充"}`).join("\n")}`;
}
export function reportDraft(s: State, pid: string) {
  const p = lookup(s, pid);
  if (!p) throw Error("项目不存在");
  const ms = related(s, "milestones", pid)
    .filter((m) => !m.actual)
    .sort((a, b) => a.committed.localeCompare(b.committed));
  return `【项目汇报草稿 · 演示数据】${p.title}\n\n当前进展（已确认来源）\n${related(
    s,
    "sources",
    pid,
  )
    .filter((x) => x.confirmed)
    .map((x) => `- ${x.excerpt} [${x.id}]`)
    .join("\n")}\n\n下一里程碑\n${ms
    .slice(0, 1)
    .map(
      (x) =>
        `- ${x.title}：承诺 ${x.committed}，预测 ${x.forecast} [${x.id}] ${x.sourceIds.map((id) => "[" + id + "]").join(" ")}`,
    )
    .join("\n")}\n\n已确认判断与风险\n${related(s, "judgments", pid)
    .filter((x) => x.confirmed)
    .map(
      (x) =>
        `- ${x.title} [${x.id}] ${x.sourceIds.map((id) => "[" + id + "]").join(" ")}`,
    )
    .join("\n")}\n${related(s, "risks", pid)
    .filter((x) => x.confirmed && x.status !== "已关闭")
    .map(
      (x) =>
        `- ${x.title}；应对：${x.response} [${x.id}] ${x.sourceIds.map((id) => "[" + id + "]").join(" ")}`,
    )
    .join("\n")}\n\n需要协调或决策\n${related(s, "decisions", pid)
    .filter((x) => x.status === "待决策")
    .map(
      (x) =>
        `- ${x.owner || "待指定决策人"}：${x.title}，最晚 ${x.deadline || "待确认"} [${x.id}]`,
    )
    .join("\n")}\n\n下一步计划\n- ${p.nextAction} [${p.id}]`;
}
export const stableHash = (str: string) => {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++)
    h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return (h >>> 0).toString(16);
};
export function prepareSource(
  s: State,
  input: {
    text: string;
    url?: string;
    occurredAt?: string;
    projectIds?: string[];
    type?: string;
  },
): Item {
  const text = input.text?.trim();
  if (!text || text.length > 20000) throw Error("请输入 1–20000 字的信息");
  if (input.url && !/^https?:\/\//i.test(input.url))
    throw Error("来源链接须为 http 或 https");
  if (input.occurredAt && Number.isNaN(Date.parse(input.occurredAt)))
    throw Error("信息发生时间无效");
  const pids =
    input.projectIds?.filter((id) => s.projects.some((p) => p.id === id)) || [];
  if (!pids.length)
    for (const p of s.projects)
      if (text.includes(p.title.split(" ")[0]) || text.includes(p.code))
        pids.push(p.id);
  const id =
    "in-" +
    stableHash(
      text +
        "|" +
        (input.url || "") +
        "|" +
        (input.occurredAt || "") +
        "|" +
        [...pids].sort().join(","),
    );
  return rec(id, "收件箱 · " + text.slice(0, 24), pids, [], {
    type: input.type || "粘贴记录",
    excerpt: text,
    url: input.url || "",
    occurredAt: input.occurredAt || "",
    collectedAt: new Date().toISOString(),
    confirmed: false,
    objectIds: [],
    demo: false,
  });
}
export function analyzeMock(s: State, src: Item): Candidate[] {
  const txt = src.excerpt as string,
    pids = src.projectIds,
    result: Candidate[] = [];
  const add = (
    category: string,
    kind: Kind,
    targetId: string,
    field: string,
    value: string,
    before = "",
  ) => {
    const base = String(lookup(s, targetId)?.[field] ?? "");
    result.push({
      id: "c-" + stableHash(src.id + category + targetId + field),
      category,
      kind,
      targetId,
      field,
      value,
      before: before || base,
      baseValue: base,
      evidence: txt,
      sourceId: src.id,
      projectIds: pids,
      status: "pending",
      mode: "本地规则整理",
    });
  };
  const action =
    s.actions.find((a) => txt.includes(a.title)) ||
    (/附件|测试报告/.test(txt)
      ? s.actions.find((a) => a.id === "a1" && pids.includes("p1"))
      : undefined);
  const milestone = s.milestones.find((m) => txt.includes(m.title));
  add("项目进展", "sources", src.id, "confirmed", "true");
  const date = txt.match(
    /(?:预测|预计)[^\n。；]{0,18}?(\d{4}-\d{2}-\d{2})/,
  )?.[1];
  if (date && milestone) {
    add("日期变化", "milestones", milestone.id, "forecast", date);
    if (date !== milestone.forecast)
      add(
        "与已有记录的矛盾",
        "judgments",
        "new-" + src.id + "-conflict",
        "title",
        `日期冲突：${milestone.title} 现预测 ${milestone.forecast}，新反馈 ${date}；承诺 ${milestone.committed} 保持不变。`,
        milestone.forecast,
      );
  }
  const actionSentence = action
    ? txt
        .split(/[。；\n]/)
        .find((sentence) => sentence.includes(action.title)) || ""
    : "";
  if (action && /完成|提交/.test(actionSentence)) {
    const negative =
      /(未|没有|尚未|还未|没)(能|能否)?(完成|提交)|尚未完成|未提交/.test(
        actionSentence,
      );
    add(
      "行动项更新",
      "actions",
      action.id,
      "executionStatus",
      negative ? "团队反馈未完成" : "团队反馈完成",
    );
  } else if (action && /跟进|负责|请/.test(txt)) {
    add('行动项更新','actions',action.id,'followUp',txt.split(/[。\n]/).find(x=>/跟进|负责|请/.test(x)) || txt);
  } else if (/跟进|负责|请|行动|需要/.test(txt)) {
    const existing = s.actions.find((a) => a.sourceIds.includes(src.id));
    add(
      "新增行动项",
      "actions",
      existing?.id || "new-" + src.id + "-action",
      "title",
      txt
        .split(/[。\n]/)
        .find((x) => /跟进|负责|请|行动|需要/.test(x))
        ?.slice(0, 160) || "核实待办事项",
    );
  }
  if (/风险|延期|缺少|缺失|未齐|不足|阻塞|没补|尚无|未补/.test(txt)) {
    const r =
      /附件|验收/.test(txt) && pids.includes("p1")
        ? s.risks.find((r) => r.id === "r2")
        : undefined;
    add(
      "风险与问题",
      "risks",
      r?.id || "new-" + src.id + "-risk",
      r ? "description" : "title",
      r ? txt : "待核实：" + txt.slice(0, 80),
    );
  }
  if (/决定|决策|方案|是否/.test(txt)) {
    const d = s.decisions.find(
      (d) => txt.includes("台架") && d.id === "d1" && pids.includes("p1"),
    );
    add(
      "待决策事项",
      "decisions",
      d?.id || "new-" + src.id + "-decision",
      d ? "recommendation" : "title",
      txt.split(/[。\n]/).find((x) => /决定|决策|方案|是否/.test(x)) || txt,
    );
  }
  const missing = [
    !pids.length ? "尚未匹配项目，请先补充关联项目。" : "",
    date && !milestone ? "提到日期但未明确匹配里程碑，请补充目标事项。" : "",
    !src.url ? "未提供原始链接。" : "",
    !src.occurredAt ? "未提供信息发生时间。" : "",
    /完成|提交/.test(txt) && !/https?:/.test(txt)
      ? "完成反馈缺少可验证的交付物链接，不能自动认定验收通过。"
      : "",
  ]
    .filter(Boolean)
    .join(" ");
  if (missing)
    add(
      "缺失信息",
      "judgments",
      "new-" + src.id + "-missing",
      "title",
      missing,
    );
  return result;
}
export function answerMock(s: State, q: string, pid?: string) {
  const select = (k: Kind) => (pid ? related(s, k, pid) : s[k]);
  let rows: Item[] = [],
    text = "";
  if (/两周|里程碑/.test(q)) {
    rows = select("milestones").filter(
      (x) =>
        !x.actual &&
        x.committed <= shift(14) &&
        (x.forecast > x.committed ||
          s.risks.some(
            (r) => r.milestoneIds?.includes(x.id) && r.status !== "已关闭",
          )),
    );
    text =
      rows
        .map(
          (x) =>
            `${x.title}：承诺 ${x.committed}，预测 ${x.forecast}。${s.risks
              .filter((r) => r.milestoneIds?.includes(x.id))
              .map((r) => r.title + " [" + r.id + "]")
              .join("；")} [${x.id}]`,
        )
        .join("\n\n") ||
      "当前记录未显示未来两周的风险里程碑；资料完整性仍需确认。";
  } else if (/等.*(回复|反馈)|等别人/.test(q)) {
    rows = select("actions").filter((x) => x.status === "等待他人反馈");
    text =
      rows
        .map(
          (x) =>
            `等待 ${x.executor}：${x.title}。上次沟通 ${x.lastContactAt || "待补充"}，下次检查 ${x.checkAt || "待补充"} [${x.id}]`,
        )
        .join("\n\n") || "当前没有标记为等待反馈的行动。";
  } else if (/决策/.test(q)) {
    rows = select("decisions").filter(
      (x) => x.status === "待决策" && x.projectIds.length > 1,
    );
    text =
      rows
        .map(
          (x) =>
            `${x.owner}需在 ${x.deadline} 前决定：${x.title}。${x.impact} [${x.id}]`,
        )
        .join("\n\n") || "未记录影响多个项目的待决策事项。";
  } else if (/最近|变化/.test(q)) {
    rows = select("sources").slice(-6);
    text = rows
      .map(
        (x) =>
          `${x.occurredAt || "发生时间待确认"}：${x.excerpt}（${x.confirmed ? "已确认" : "待确认"}）[${x.id}]`,
      )
      .join("\n\n");
  } else if (/今天|三件|本周/.test(q)) {
    rows = select("actions")
      .filter((x) => x.status !== "已完成")
      .sort((a, b) => a.checkAt.localeCompare(b.checkAt))
      .slice(0, 3);
    text =
      "建议优先推动以下三件事（按检查时间和现有状态排序）：\n\n" +
      rows
        .map(
          (x, i) => `${i + 1}. ${x.followUp} 检查时间 ${x.checkAt} [${x.id}]`,
        )
        .join("\n\n");
  } else
    text =
      "本地规则整理支持下方五类提问。当前信息不足以可靠回答这个问题，请选择一个场景，或先补充台账与来源。";
  return {
    text: text + "\n\n依据仅来自当前台账；缺少来源的内容仍待确认。",
    recordIds: [...new Set(rows.flatMap((x) => [x.id, ...x.sourceIds]))],
    mode: "本地规则整理",
  };
}
export const editable: Record<Kind, string[]> = {
  projects: [
    "title",
    "goal",
    "owner",
    "phase",
    "health",
    "healthReason",
    "nextAction",
    "privateNote",
  ],
  milestones: [
    "title",
    "committed",
    "forecast",
    "actual",
    "acceptance",
    "owner",
    "deliverableIds",
  ],
  dependencies: [
    "title",
    "predecessorIds",
    "affectedIds",
    "type",
    "owner",
    "neededBy",
    "status",
    "situation",
  ],
  risks: [
    "title",
    "projectIds",
    "milestoneIds",
    "type",
    "impact",
    "description",
    "trigger",
    "response",
    "owner",
    "checkAt",
    "confirmed",
    "status",
  ],
  decisions: [
    "title",
    "projectIds",
    "milestoneIds",
    "options",
    "recommendation",
    "owner",
    "deadline",
    "impact",
  ],
  actions: [
    "title",
    "projectIds",
    "executor",
    "feishuIdentity",
    "followUp",
    "priority",
    "dueAt",
    "checkAt",
    "lastContactAt",
    "status",
    "executionStatus",
    "acceptanceStatus",
    "acceptance",
  ],
  sources: ["confirmed"],
  judgments: ["title", "confirmed"],
};
function validatePatch(s: State, kind: Kind, patch: Record<string, any>) {
  for (const [key, value] of Object.entries(patch)) {
    if (!editable[kind].includes(key)) throw Error("不可编辑字段：" + key);
    if (
      [
        "projectIds",
        "milestoneIds",
        "predecessorIds",
        "affectedIds",
        "deliverableIds",
      ].includes(key)
    ) {
      if (
        !Array.isArray(value) ||
        value.some((id) => typeof id !== "string" || !lookup(s, id))
      )
        throw Error("关联记录无效");
      continue;
    }
    if (key === "confirmed") {
      if (typeof value !== "boolean") throw Error("确认状态无效");
      continue;
    }
    if (typeof value !== "string" || value.length > 20000)
      throw Error("字段格式无效：" + key);
    if (
      [
        "committed",
        "forecast",
        "actual",
        "deadline",
        "neededBy",
        "dueAt",
        "checkAt",
        "lastContactAt",
      ].includes(key) &&
      value &&
      (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(value)))
    )
      throw Error("日期格式无效");
    if (key === "title" && !value.trim()) throw Error("标题不能为空");
  }
}
function audit(
  s: State,
  operation: string,
  objectId: string,
  before: unknown,
  after: unknown,
) {
  s.audit.push({
    id: uid("audit"),
    time: new Date().toISOString(),
    operation,
    objectId,
    before: structuredClone(before),
    after: structuredClone(after),
  });
}
function createItem(s: State, c: Candidate, value: string) {
  const x = rec(
    c.targetId,
    value,
    c.projectIds,
    c.sourceId ? [c.sourceId] : [],
    { createdAt: new Date().toISOString() },
  );
  if (c.kind === "actions")
    Object.assign(x, {
      executor: "",
      feishuIdentity: "",
      followUp: "确认实际执行人和下次检查时间。",
      priority: "P2",
      dueAt: "",
      checkAt: today(),
      lastContactAt: "",
      status: "今天需要推动",
      executionStatus: "待确认",
      acceptanceStatus: "待验收",
      acceptance: "待补充",
      milestoneIds: [],
    });
  if (c.kind === "risks")
    Object.assign(x, {
      type: "风险",
      impact: "中",
      description: value,
      trigger: "待确认",
      response: "核实来源并落实应对措施。",
      owner: "",
      checkAt: today(),
      milestoneIds: [],
      confirmed: true,
      status: "待处理",
    });
  if (c.kind === "decisions")
    Object.assign(x, {
      options: "待补充",
      recommendation: "待确认",
      owner: "",
      deadline: "",
      impact: "待确认",
      milestoneIds: [],
      status: "待决策",
      conclusion: "",
      history: [],
    });
  if (c.kind === "judgments")
    Object.assign(x, {
      confirmed: true,
      author: "项目经理",
      category: c.category,
    });
  s[c.kind].push(x);
  return x;
}
export function applyCommand(state: State, command: any): State {
  const s = structuredClone(state),
    now = new Date().toISOString();
  if (command.type === "edit") {
    const kind = command.kind as Kind;
    if (!collections.includes(kind)) throw Error("记录类型无效");
    const x = s[kind].find((x) => x.id === command.id);
    if (!x) throw Error("记录不存在");
    validatePatch(s, kind, command.patch);
    const before = structuredClone(x);
    Object.assign(x, command.patch, { updatedAt: now });
    if (
      kind === "projects" &&
      ("health" in command.patch || "healthReason" in command.patch)
    ) {
      if (!x.healthReason.trim()) throw Error("请填写健康判断依据");
      s.judgments.push(
        rec(uid("j"), x.healthReason, [x.id], x.sourceIds, {
          confirmed: true,
          author: "项目经理",
          health: x.health,
          createdAt: now,
        }),
      );
    }
    audit(s, "edit", x.id, before, x);
  } else if (command.type === "createRisk") {
    validatePatch(s, "risks", command.patch);
    if (!command.patch.title?.trim()) throw Error("请填写风险标题");
    const x = createItem(
      s,
      {
        targetId: uid("r"),
        kind: "risks",
        projectIds: command.patch.projectIds || [],
        sourceId: "",
        category: "风险与问题",
      } as Candidate,
      command.patch.title,
    );
    Object.assign(x, command.patch);
    if (!x.sourceIds.length) x.confirmed = false;
    audit(s, "createRisk", x.id, null, x);
  } else if (command.type === "ingest") {
    const src = command.source as Item;
    if (!src?.id || !src.excerpt) throw Error("来源无效");
    if (!s.sources.some((x) => x.id === src.id)) s.sources.push(src);
    for (const c of command.candidates as Candidate[]) {
      const old = s.candidates.findIndex((x) => x.id === c.id);
      if (old < 0) s.candidates.push(c);
      else if (s.candidates[old].status === "pending") s.candidates[old] = c;
    }
    audit(s, "ingest", src.id, null, {
      candidateIds: command.candidates.map((c: Candidate) => c.id),
    });
  } else if (command.type === "candidate") {
    const c = s.candidates.find((x) => x.id === command.id);
    if (!c) throw Error("候选不存在");
    if (c.status !== "pending") return state;
    if (command.action === "ignore") {
      c.status = "ignored";
      audit(s, "ignore", c.id, null, c);
    } else {
      const value = String(command.value ?? c.value).trim();
      if (!value) throw Error("候选内容不能为空");
      let x = lookup(s, c.targetId);
      const before = x ? structuredClone(x) : null;
      if (x && c.kind !== "sources" && String(x[c.field] ?? "") !== c.baseValue)
        throw Error("目标记录已变化，请重新分析后确认，避免覆盖新信息");
      if (!x) x = createItem(s, c, value);
      else {
        const v = c.field === "confirmed" ? value === "true" : value;
        validatePatch(s, c.kind, { [c.field]: v });
        x[c.field] = v;
      }
      if (!x.sourceIds.includes(c.sourceId) && x.id !== c.sourceId)
        x.sourceIds.push(c.sourceId);
      const src = s.sources.find((x) => x.id === c.sourceId)!;
      src.objectIds = [...new Set([...(src.objectIds || []), x.id])];
      c.status = "accepted";
      c.appliedValue = value;
      c.acceptedAt = now;
      x.updatedAt = now;
      audit(s, "accept", c.id, before, x);
    }
  } else if (command.type === "decision") {
    const d = s.decisions.find((x) => x.id === command.id);
    if (!d) throw Error("决策不存在");
    if (!command.conclusion?.trim() || !command.basis?.trim())
      throw Error("请填写结论与依据");
    d.history.push({
      time: now,
      conclusion: command.conclusion,
      basis: command.basis,
      decider: d.owner || "待确认",
    });
    d.conclusion = command.conclusion;
    d.status = "已决策";
    audit(s, "decision", d.id, null, d.history.at(-1));
  } else if (command.type === "publish") {
    if (!["task", "report"].includes(command.kind)) throw Error("发布类型无效");
    const x = lookup(s, command.objectId);
    if (
      !x ||
      !(command.kind === "task" ? s.actions : s.projects).some(
        (a) => a.id === x.id,
      )
    )
      throw Error("发布对象无效");
    let p = s.publications.find((p) => p.id === command.publicationId);
    if (!p && command.kind === "task")
      p = s.publications.find((p) => p.kind === "task" && p.objectId === x.id);
    if (p && (p.objectId !== x.id || p.kind !== command.kind))
      throw Error("重试对象与原发布记录不一致");
    if (p?.status === "success") return state;
    if (!p) {
      if (!command.content?.trim()) throw Error("发布内容不能为空");
      p = {
        id: command.kind === "task" ? "pub-task-" + x.id : uid("pub-report"),
        objectId: x.id,
        kind: command.kind,
        mode: "simulation",
        targetId: "",
        targetUrl: "",
        content: command.content,
        status: "failed",
        attempts: [],
        createdAt: now,
        sourceIds: [...x.sourceIds],
        feedbackIds: [],
      };
      s.publications.push(p);
    }
    const fail = command.fail === true;
    p.attempts.push({
      time: now,
      result: fail ? "failed" : "success",
      reason: fail
        ? "模拟：连接超时（SIM_TIMEOUT），目标尚未创建。可重试同一发布记录。"
        : "",
    });
    p.status = fail ? "failed" : "success";
    if (!fail) {
      p.targetId =
        (p.kind === "task" ? "SIM-TASK-" : "SIM-REPORT-") +
        (p.kind === "task" ? p.objectId : p.id);
      p.targetUrl = "/simulated-feishu/" + p.targetId;
    }
    audit(s, fail ? "publishFailed" : "publishSuccess", p.id, null, {
      targetId: p.targetId,
      attempt: p.attempts.length,
    });
  } else if (command.type === "feedback") {
    const p = s.publications.find(
      (p) =>
        p.targetId === command.targetId &&
        p.status === "success" &&
        p.kind === "task",
    );
    if (!p) throw Error("未找到已发布任务映射");
    if (!command.text?.trim() || !command.eventId)
      throw Error("反馈内容或事件 ID 缺失");
    if (p.feedbackIds.includes(command.eventId)) return state;
    const a = s.actions.find((x) => x.id === p.objectId)!,
      sid = "feedback-" + command.eventId;
    s.sources.push(
      rec(sid, "模拟飞书反馈 · " + a.title, a.projectIds, [], {
        type: "模拟任务反馈",
        excerpt: command.text,
        url: p.targetUrl,
        occurredAt: now,
        collectedAt: now,
        confirmed: false,
        objectIds: [a.id],
        demo: true,
      }),
    );
    const before = structuredClone(a);
    a.executionStatus = command.completed ? "团队反馈完成" : "进行中";
    a.lastContactAt = today();
    a.sourceIds.push(sid);
    a.updatedAt = now;
    p.feedbackIds.push(command.eventId);
    audit(s, "feedback", a.id, before, a);
  } else throw Error("不支持的操作");
  s.revision = state.revision + 1;
  return s;
}
