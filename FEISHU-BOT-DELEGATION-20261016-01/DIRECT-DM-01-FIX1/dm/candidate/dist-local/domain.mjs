// lib/domain.ts
var today = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit"
}).format(/* @__PURE__ */ new Date());
var shift = (n) => {
  const d = /* @__PURE__ */ new Date(today() + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
var uid = (p) => p + "-" + crypto.randomUUID();
var collections = [
  "projects",
  "milestones",
  "dependencies",
  "risks",
  "decisions",
  "actions",
  "sources",
  "judgments"
];
var rec = (id2, title, projectIds2, sourceIds, rest = {}) => ({ id: id2, title, projectIds: projectIds2, sourceIds, ...rest });
function lookup(s, id2) {
  for (const k of collections) {
    const x = s[k].find((x2) => x2.id === id2);
    if (x) return x;
  }
}
var related = (s, k, p) => s[k].filter((x) => x.projectIds.includes(p));
function taskDraft(s, id2) {
  const a = s.actions.find((x) => x.id === id2);
  if (!a) throw Error("\u884C\u52A8\u4E0D\u5B58\u5728");
  return `\u3010\u6A21\u62DF\u98DE\u4E66\u4EFB\u52A1\u3011
\u6807\u9898\uFF1A${a.title}
\u5DE5\u4F5C\u8BF4\u660E\uFF1A${a.title}
\u5B9E\u9645\u6267\u884C\u4EBA\uFF1A${a.executor || "\u5F85\u6307\u5B9A"}
\u622A\u6B62\u65E5\u671F\uFF1A${a.dueAt || "\u5F85\u6307\u5B9A"}
\u9A8C\u6536\u8981\u6C42\uFF1A${a.acceptance}
\u76F8\u5173\u6765\u6E90\uFF1A${a.sourceIds.map((x) => `${lookup(s, x)?.title} [${x}] ${lookup(s, x)?.url || "\u94FE\u63A5\u5F85\u8865\u5145"}`).join("\n")}`;
}
var stableHash = (str) => {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++)
    h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return (h >>> 0).toString(16);
};
function prepareSource(s, input) {
  const text15 = input.text?.trim();
  if (!text15 || text15.length > 2e4) throw Error("\u8BF7\u8F93\u5165 1\u201320000 \u5B57\u7684\u4FE1\u606F");
  if (input.url && !/^https?:\/\//i.test(input.url))
    throw Error("\u6765\u6E90\u94FE\u63A5\u987B\u4E3A http \u6216 https");
  if (input.occurredAt && Number.isNaN(Date.parse(input.occurredAt)))
    throw Error("\u4FE1\u606F\u53D1\u751F\u65F6\u95F4\u65E0\u6548");
  const pids = input.projectIds?.filter((id3) => s.projects.some((p) => p.id === id3)) || [];
  if (!pids.length) {
    for (const p of s.projects)
      if (text15.includes(p.title.split(" ")[0]) || text15.includes(p.code))
        pids.push(p.id);
  }
  const id2 = "in-" + stableHash(
    text15 + "|" + (input.url || "") + "|" + (input.occurredAt || "") + "|" + [...pids].sort().join(",")
  );
  return rec(id2, "\u6536\u4EF6\u7BB1 \xB7 " + text15.slice(0, 24), pids, [], {
    type: input.type || "\u7C98\u8D34\u8BB0\u5F55",
    excerpt: text15,
    url: input.url || "",
    occurredAt: input.occurredAt || "",
    collectedAt: (/* @__PURE__ */ new Date()).toISOString(),
    confirmed: false,
    objectIds: [],
    demo: false
  });
}
function analyzeMock(s, src) {
  const txt = src.excerpt, pids = src.projectIds, result = [];
  const add = (category, kind, targetId, field, value, before = "") => {
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
      mode: "\u672C\u5730\u89C4\u5219\u6574\u7406"
    });
  };
  const action = s.actions.find((a) => txt.includes(a.title)) || (/附件|测试报告/.test(txt) ? s.actions.find((a) => a.id === "a1" && pids.includes("p1")) : void 0);
  const milestone = s.milestones.find((m) => txt.includes(m.title));
  add("\u9879\u76EE\u8FDB\u5C55", "sources", src.id, "confirmed", "true");
  const date4 = txt.match(
    /(?:预测|预计)[^\n。；]{0,18}?(\d{4}-\d{2}-\d{2})/
  )?.[1];
  if (date4 && milestone) {
    add("\u65E5\u671F\u53D8\u5316", "milestones", milestone.id, "forecast", date4);
    if (date4 !== milestone.forecast)
      add(
        "\u4E0E\u5DF2\u6709\u8BB0\u5F55\u7684\u77DB\u76FE",
        "judgments",
        "new-" + src.id + "-conflict",
        "title",
        `\u65E5\u671F\u51B2\u7A81\uFF1A${milestone.title} \u73B0\u9884\u6D4B ${milestone.forecast}\uFF0C\u65B0\u53CD\u9988 ${date4}\uFF1B\u627F\u8BFA ${milestone.committed} \u4FDD\u6301\u4E0D\u53D8\u3002`,
        milestone.forecast
      );
  }
  const actionSentence = action ? txt.split(/[。；\n]/).find((sentence) => sentence.includes(action.title)) || "" : "";
  if (action && /完成|提交/.test(actionSentence)) {
    const negative = /(未|没有|尚未|还未|没)(能|能否)?(完成|提交)|尚未完成|未提交/.test(
      actionSentence
    );
    add(
      "\u884C\u52A8\u9879\u66F4\u65B0",
      "actions",
      action.id,
      "executionStatus",
      negative ? "\u56E2\u961F\u53CD\u9988\u672A\u5B8C\u6210" : "\u56E2\u961F\u53CD\u9988\u5B8C\u6210"
    );
  } else if (action && /跟进|负责|请/.test(txt)) {
    add("\u884C\u52A8\u9879\u66F4\u65B0", "actions", action.id, "followUp", txt.split(/[。\n]/).find((x) => /跟进|负责|请/.test(x)) || txt);
  } else if (/跟进|负责|请|行动|需要/.test(txt)) {
    const existing = s.actions.find((a) => a.sourceIds.includes(src.id));
    add(
      "\u65B0\u589E\u884C\u52A8\u9879",
      "actions",
      existing?.id || "new-" + src.id + "-action",
      "title",
      txt.split(/[。\n]/).find((x) => /跟进|负责|请|行动|需要/.test(x))?.slice(0, 160) || "\u6838\u5B9E\u5F85\u529E\u4E8B\u9879"
    );
  }
  if (/风险|延期|缺少|缺失|未齐|不足|阻塞|没补|尚无|未补/.test(txt)) {
    const r = /附件|验收/.test(txt) && pids.includes("p1") ? s.risks.find((r2) => r2.id === "r2") : void 0;
    add(
      "\u98CE\u9669\u4E0E\u95EE\u9898",
      "risks",
      r?.id || "new-" + src.id + "-risk",
      r ? "description" : "title",
      r ? txt : "\u5F85\u6838\u5B9E\uFF1A" + txt.slice(0, 80)
    );
  }
  if (/决定|决策|方案|是否/.test(txt)) {
    const d = s.decisions.find(
      (d2) => txt.includes("\u53F0\u67B6") && d2.id === "d1" && pids.includes("p1")
    );
    add(
      "\u5F85\u51B3\u7B56\u4E8B\u9879",
      "decisions",
      d?.id || "new-" + src.id + "-decision",
      d ? "recommendation" : "title",
      txt.split(/[。\n]/).find((x) => /决定|决策|方案|是否/.test(x)) || txt
    );
  }
  const missing = [
    !pids.length ? "\u5C1A\u672A\u5339\u914D\u9879\u76EE\uFF0C\u8BF7\u5148\u8865\u5145\u5173\u8054\u9879\u76EE\u3002" : "",
    date4 && !milestone ? "\u63D0\u5230\u65E5\u671F\u4F46\u672A\u660E\u786E\u5339\u914D\u91CC\u7A0B\u7891\uFF0C\u8BF7\u8865\u5145\u76EE\u6807\u4E8B\u9879\u3002" : "",
    !src.url ? "\u672A\u63D0\u4F9B\u539F\u59CB\u94FE\u63A5\u3002" : "",
    !src.occurredAt ? "\u672A\u63D0\u4F9B\u4FE1\u606F\u53D1\u751F\u65F6\u95F4\u3002" : "",
    /完成|提交/.test(txt) && !/https?:/.test(txt) ? "\u5B8C\u6210\u53CD\u9988\u7F3A\u5C11\u53EF\u9A8C\u8BC1\u7684\u4EA4\u4ED8\u7269\u94FE\u63A5\uFF0C\u4E0D\u80FD\u81EA\u52A8\u8BA4\u5B9A\u9A8C\u6536\u901A\u8FC7\u3002" : ""
  ].filter(Boolean).join(" ");
  if (missing)
    add(
      "\u7F3A\u5931\u4FE1\u606F",
      "judgments",
      "new-" + src.id + "-missing",
      "title",
      missing
    );
  return result;
}
function answerMock(s, q, pid) {
  const select = (k) => pid ? related(s, k, pid) : s[k];
  let rows2 = [], text15 = "";
  if (/两周|里程碑/.test(q)) {
    rows2 = select("milestones").filter(
      (x) => !x.actual && x.committed <= shift(14) && (x.forecast > x.committed || s.risks.some(
        (r) => r.milestoneIds?.includes(x.id) && r.status !== "\u5DF2\u5173\u95ED"
      ))
    );
    text15 = rows2.map(
      (x) => `${x.title}\uFF1A\u627F\u8BFA ${x.committed}\uFF0C\u9884\u6D4B ${x.forecast}\u3002${s.risks.filter((r) => r.milestoneIds?.includes(x.id)).map((r) => r.title + " [" + r.id + "]").join("\uFF1B")} [${x.id}]`
    ).join("\n\n") || "\u5F53\u524D\u8BB0\u5F55\u672A\u663E\u793A\u672A\u6765\u4E24\u5468\u7684\u98CE\u9669\u91CC\u7A0B\u7891\uFF1B\u8D44\u6599\u5B8C\u6574\u6027\u4ECD\u9700\u786E\u8BA4\u3002";
  } else if (/等.*(回复|反馈)|等别人/.test(q)) {
    rows2 = select("actions").filter((x) => x.status === "\u7B49\u5F85\u4ED6\u4EBA\u53CD\u9988");
    text15 = rows2.map(
      (x) => `\u7B49\u5F85 ${x.executor}\uFF1A${x.title}\u3002\u4E0A\u6B21\u6C9F\u901A ${x.lastContactAt || "\u5F85\u8865\u5145"}\uFF0C\u4E0B\u6B21\u68C0\u67E5 ${x.checkAt || "\u5F85\u8865\u5145"} [${x.id}]`
    ).join("\n\n") || "\u5F53\u524D\u6CA1\u6709\u6807\u8BB0\u4E3A\u7B49\u5F85\u53CD\u9988\u7684\u884C\u52A8\u3002";
  } else if (/决策/.test(q)) {
    rows2 = select("decisions").filter(
      (x) => x.status === "\u5F85\u51B3\u7B56" && x.projectIds.length > 1
    );
    text15 = rows2.map(
      (x) => `${x.owner}\u9700\u5728 ${x.deadline} \u524D\u51B3\u5B9A\uFF1A${x.title}\u3002${x.impact} [${x.id}]`
    ).join("\n\n") || "\u672A\u8BB0\u5F55\u5F71\u54CD\u591A\u4E2A\u9879\u76EE\u7684\u5F85\u51B3\u7B56\u4E8B\u9879\u3002";
  } else if (/最近|变化/.test(q)) {
    rows2 = select("sources").slice(-6);
    text15 = rows2.map(
      (x) => `${x.occurredAt || "\u53D1\u751F\u65F6\u95F4\u5F85\u786E\u8BA4"}\uFF1A${x.excerpt}\uFF08${x.confirmed ? "\u5DF2\u786E\u8BA4" : "\u5F85\u786E\u8BA4"}\uFF09[${x.id}]`
    ).join("\n\n");
  } else if (/今天|三件|本周/.test(q)) {
    rows2 = select("actions").filter((x) => x.status !== "\u5DF2\u5B8C\u6210").sort((a, b) => a.checkAt.localeCompare(b.checkAt)).slice(0, 3);
    text15 = "\u5EFA\u8BAE\u4F18\u5148\u63A8\u52A8\u4EE5\u4E0B\u4E09\u4EF6\u4E8B\uFF08\u6309\u68C0\u67E5\u65F6\u95F4\u548C\u73B0\u6709\u72B6\u6001\u6392\u5E8F\uFF09\uFF1A\n\n" + rows2.map(
      (x, i) => `${i + 1}. ${x.followUp} \u68C0\u67E5\u65F6\u95F4 ${x.checkAt} [${x.id}]`
    ).join("\n\n");
  } else
    text15 = "\u672C\u5730\u89C4\u5219\u6574\u7406\u652F\u6301\u4E0B\u65B9\u4E94\u7C7B\u63D0\u95EE\u3002\u5F53\u524D\u4FE1\u606F\u4E0D\u8DB3\u4EE5\u53EF\u9760\u56DE\u7B54\u8FD9\u4E2A\u95EE\u9898\uFF0C\u8BF7\u9009\u62E9\u4E00\u4E2A\u573A\u666F\uFF0C\u6216\u5148\u8865\u5145\u53F0\u8D26\u4E0E\u6765\u6E90\u3002";
  return {
    text: text15 + "\n\n\u4F9D\u636E\u4EC5\u6765\u81EA\u5F53\u524D\u53F0\u8D26\uFF1B\u7F3A\u5C11\u6765\u6E90\u7684\u5185\u5BB9\u4ECD\u5F85\u786E\u8BA4\u3002",
    recordIds: [...new Set(rows2.flatMap((x) => [x.id, ...x.sourceIds]))],
    mode: "\u672C\u5730\u89C4\u5219\u6574\u7406"
  };
}

// lib/feishu-facts.ts
var own = (o, key2) => Object.prototype.hasOwnProperty.call(o, key2);
var same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
var object = (v) => !!v && typeof v === "object" && !Array.isArray(v);
function label(value, metadata) {
  const options = metadata?.option || metadata?.options;
  const id2 = object(value) ? value.value ?? value.key ?? value.id : value;
  if (Array.isArray(options) && options.length) {
    const found = options.find((o) => String(o.option_id ?? o.id ?? o.key) === String(id2));
    if (found) return String(found.option_name ?? found.name ?? found.label ?? "");
    if (object(value)) return "";
  }
  return typeof value === "string" ? value : object(value) ? String(value.label ?? value.name ?? "") : "";
}
function observedDeliveryReview(row) {
  const fact = row.feishuFacts?.deliveryReview;
  return fact ? fact.state === "mapped" ? fact.value : "\u5F85\u6620\u5C04" : row.deliveryReview || row.reviewStatus || "\u672A\u5BA1\u6838";
}
function deliveryRecorded(row) {
  return row.submissionStatus !== "\u514D\u4EA4\u4ED8" && observedDeliveryReview(row) === "\u5DF2\u5BA1\u6838";
}
function adoptFeishuFacts(s, local, remote, read, baseline) {
  if (["quarantined", "unmapped"].includes(remote.mappingStatus)) return [];
  const pairs = remote.remoteKind === "deliverable" ? [["field_b462b3", "deliveryReview"], ["work_item_status", "status"]] : remote.remoteKind === "node" ? [["status", "nodeStatus"]] : [];
  const conflicts = [], changes = [];
  for (const [key2, field] of pairs) {
    if (!own(read.fields, key2)) {
      const declared = Array.isArray(read.fieldMetadata) && read.fieldMetadata.some((r) => object(r) && (r.key || r.field_key) === key2);
      if (declared && !local.feishuFacts?.[field]) local.feishuFacts = { ...local.feishuFacts || {}, [field]: { state: "unread", value: "", raw: null, externalObjectId: remote.id, fieldKey: key2, readAt: read.collectedAt, reason: "\u672C\u6B21\u672A\u8FD4\u56DE\u8BE5\u5B57\u6BB5\uFF0C\u4E0D\u63A8\u65AD\u5176\u9ED8\u8BA4\u503C" } };
      continue;
    }
    const existing = s.mappingRules.find((r) => r.system === "meegle" && r.remoteKind === remote.remoteKind && r.remoteFieldKey === key2);
    if (existing && (existing.status !== "active" || existing.localField && existing.localField !== field)) continue;
    if (!existing) s.mappingRules.push({ id: "mapping-fact-" + stableHash(remote.remoteKind + ":" + key2), workspaceId: s.workspaceId, system: "meegle", remoteKind: remote.remoteKind, remoteFieldKey: key2, remoteFieldName: field === "nodeStatus" ? "\u8282\u70B9\u72B6\u6001" : field, remoteValueType: "option", localKind: remote.remoteKind === "node" ? "flowNodes" : "deliverables", localField: field, conversionRule: "option_label", writable: false, requiresReview: false, bidirectional: false, status: "active" });
    const raw = read.fields[key2];
    const metadata = Array.isArray(read.fieldMetadata) ? read.fieldMetadata.find((r) => object(r) && (r.key || r.field_key) === key2) : read.fieldMetadata?.[key2];
    const display3 = label(raw, metadata);
    const value = field === "deliveryReview" ? ["\u5DF2\u5BA1\u6838", "\u672A\u5BA1\u6838"].includes(display3) ? display3 : "" : field === "status" ? ["\u672A\u5F00\u59CB", "\u8FDB\u884C\u4E2D", "\u5DF2\u7ED3\u675F"].includes(display3) ? display3 : "" : { finished: "\u5DF2\u5B8C\u6210", completed: "\u5DF2\u5B8C\u6210", done: "\u5DF2\u5B8C\u6210", started: "\u8FDB\u884C\u4E2D", doing: "\u8FDB\u884C\u4E2D", in_progress: "\u8FDB\u884C\u4E2D", pending: "\u5F85\u5F00\u59CB", waiting: "\u5F85\u5F00\u59CB", not_started: "\u5F85\u5F00\u59CB", "\u5DF2\u5B8C\u6210": "\u5DF2\u5B8C\u6210", "\u8FDB\u884C\u4E2D": "\u8FDB\u884C\u4E2D", "\u672A\u5F00\u59CB": "\u5F85\u5F00\u59CB", "\u5F85\u5F00\u59CB": "\u5F85\u5F00\u59CB" }[display3] || "";
    const prior = local.feishuFacts?.[field];
    const pending3 = s.changeGroups.some((g) => ["pending", "partial", "conflict"].includes(g.status) && g.operations.some((op) => op.targetId === local.id && (!op.status || op.status === "pending") && own(op.after, field)));
    const baselineLocal = baseline.localValues[field], edited = own(baseline.localValues, field) && !same(local[field], baselineLocal);
    const imported = local.importedFrom?.readonly === true || local.importedFrom?.system === "feishu";
    const conflict = !!value && (pending3 || edited || !own(baseline.localValues, field) && !!local[field] && !imported);
    const state = !value ? "unmapped" : conflict ? "conflict" : "mapped";
    const fact = { state, value: value || "", raw, externalObjectId: remote.id, fieldKey: key2, readAt: read.collectedAt };
    if (!prior || !same([prior.state, prior.value, prior.raw], [state, fact.value, raw])) {
      local.feishuFacts = { ...local.feishuFacts || {}, [field]: fact };
      if (prior && !same([prior.state, prior.value], [state, fact.value])) changes.push({ field, before: prior.value, after: fact.value || "\u5F53\u524D\u9009\u9879\u5F85\u6620\u5C04" });
    }
    if (conflict) {
      conflicts.push({ id: "feishu-fact-conflict-" + remote.id + "-" + key2, externalObjectId: remote.id, localObjectId: local.id, remoteFieldKey: key2, localField: field, reason: pending3 ? "\u8BE5\u4E8B\u5B9E\u5B57\u6BB5\u6709\u672C\u5730\u5F85\u5BA1\u4FEE\u6539\uFF0C\u4FDD\u7559\u5DEE\u5F02" : "\u8BE5\u4E8B\u5B9E\u5B57\u6BB5\u5B58\u5728\u672C\u5730\u72EC\u7ACB\u4FEE\u6539\uFF0C\u4FDD\u7559\u5DEE\u5F02", baselineLocal, baselineRemote: baseline.remoteValues[key2], localValue: local[field], remoteValue: raw });
      continue;
    }
    if (!value) continue;
    local[field] = value;
    if (field === "deliveryReview") local.reviewStatus = value;
    baseline.localValues[field] = value;
    baseline.remoteValues[key2] = raw;
  }
  if (changes.length && s.workspaceType !== "restored") {
    const id2 = "feishu-fact-event-" + stableHash(remote.id), old = s.sources.find((src) => src.id === id2);
    const excerpt = JSON.stringify({ title: local.title, kind: remote.remoteKind, changes, rule: "\u8FD9\u662F\u98DE\u4E66\u8BFB\u53D6\u4E8B\u5B9E\u3002\u5DF2\u5BA1\u6838\u4E3A\u5DE5\u7A0B\u5E08\u4EA4\u4ED8\u6807\u8BB0\uFF0C\u4E0D\u9700\u8981\u7ECF\u7406\u5185\u5BB9\u9A8C\u6536\u3002\u53EA\u6709\u5F53\u524D\u786E\u9700\u672C\u4EBA\u884C\u52A8\u65F6\u5217\u5F85\u529E\u3002" });
    const event = { id: id2, title: "\u98DE\u4E66\u4E8B\u5B9E\u53D8\u5316 \xB7 " + local.title, projectIds: [...local.projectIds], objectIds: [local.id], sourceIds: [remote.sourceId].filter(Boolean), type: "\u4E1A\u52A1\u52A8\u6001", excerpt, version: (old?.version || 0) + 1, createdAt: old?.createdAt || read.collectedAt, updatedAt: read.collectedAt, collectedAt: read.collectedAt, occurredAt: read.collectedAt, confirmed: false, riskEvent: { kind: "feishu-fact-change", externalObjectId: remote.id }, history: old ? [...old.history || [], { at: old.updatedAt, excerpt: old.excerpt }].slice(-30) : [] };
    if (old) Object.assign(old, event);
    else s.sources.push(event);
  }
  return conflicts;
}

// lib/project-flow-map.ts
var ipdMilestoneTitles = /* @__PURE__ */ new Set(["CDCP", "\u6982\u5FF5\u51B3\u7B56\u8BC4\u5BA1", "\u6982\u5FF5\u51B3\u7B56\u8BC4\u5BA1\uFF08CDCP\uFF09", "PDCP", "\u8BA1\u5212\u51B3\u7B56\u8BC4\u5BA1", "\u8BA1\u5212\u51B3\u7B56\u8BC4\u5BA1\uFF08PDCP\uFF09", "DVT\u8BC4\u5BA1", "DVT \u8BC4\u5BA1", "ADCP", "ADCP\u8BC4\u5BA1", "ADCP \u8BC4\u5BA1", "GA", "GA\u786E\u8BA4", "GA \u786E\u8BA4", "LDCP", "LDCP\u8BC4\u5BA1", "LDCP \u8BC4\u5BA1"]);
function flowNodeTypeLabel(node, { isIpd = false } = {}) {
  if (["\u666E\u901A\u8282\u70B9", "\u91CC\u7A0B\u7891\u8282\u70B9"].includes(node.nodeType)) return node.nodeType;
  if (node.nodeType === "\u5F85\u786E\u8BA4") return "\u7C7B\u578B\u5F85\u786E\u8BA4";
  if (!isIpd) return "\u7C7B\u578B\u5F85\u786E\u8BA4";
  return ipdMilestoneTitles.has(String(node.title || "").trim()) ? "\u91CC\u7A0B\u7891\u8282\u70B9" : "\u666E\u901A\u8282\u70B9";
}
var ipdReferenceStages = [
  {
    id: "concept",
    title: "\u6982\u5FF5",
    rows: [
      [["\u9879\u76EE\u7ACB\u9879"]],
      [["\u9879\u76EE\u5F00\u5DE5\u4F1A"]],
      [["\u5B9A\u4E49\u4EA7\u54C1\u5305\u9700\u6C42", "\u5B9A\u4E49\u4EA7\u54C1\u9700\u6C42\u5305"], ["\u5236\u5B9A\u4EA7\u54C1\u8D28\u91CF\u76EE\u6807"], ["\u5236\u5B9A\u6280\u672F\u65B9\u6848"]],
      [["CDCP", "\u6982\u5FF5\u51B3\u7B56\u8BC4\u5BA1", "\u6982\u5FF5\u51B3\u7B56\u8BC4\u5BA1\uFF08CDCP\uFF09"]]
    ]
  },
  {
    id: "plan",
    title: "\u8BA1\u5212",
    rows: [
      [["\u5236\u5B9A\u8BBE\u8BA1\u5F00\u53D1\u8BA1\u5212"]],
      [["\u5236\u5B9A\u6D4B\u8BD5\u7B56\u7565"]],
      [["\u7814\u53D1\u6982\u8981\u8BBE\u8BA1", "\u7814\u53D1\u6982\u8981\u8BBE\u8BA1 / DFMEA", "\u7814\u53D1\u8BBE\u8BA1\u6982\u8981/DFMEA"]],
      [["PDCP", "\u8BA1\u5212\u51B3\u7B56\u8BC4\u5BA1", "\u8BA1\u5212\u51B3\u7B56\u8BC4\u5BA1\uFF08PDCP\uFF09"]]
    ]
  },
  {
    id: "development",
    title: "\u5F00\u53D1",
    rows: [
      [["\u8BBE\u8BA1\u5F00\u53D1"], ["\u6D4B\u8BD5\u5F00\u53D1"]],
      [["\u539F\u578B\u6837\u673A\u6D4B\u8BD5"]],
      [["\u8BA2\u8D2D\u521D\u59CB\u7269\u6599", "\u7269\u6599\u8BA2\u8D2D"], ["IQC \u7B56\u7565", "IQC\u7B56\u7565"]],
      [["\u5C0F\u6279\u91CF\u8BD5\u4EA7\u6765\u6599\u68C0\u6D4B", "\u5C0F\u6279\u91CF\u6765\u6599\u68C0\u9A8C"]],
      [["\u5C0F\u6279\u91CF\u8BD5\u4EA7\u6837\u673A\u6D4B\u8BD5", "\u5C0F\u6279\u91CF\u8BD5\u4EA7\u6837\u673A\u6D4B\u8BD5 / DVT\u6D4B\u8BD5\u62A5\u544A", "DVT"]],
      [["DVT \u8BC4\u5BA1", "DVT\u8BC4\u5BA1"]]
    ]
  },
  {
    id: "verification",
    title: "\u9A8C\u8BC1",
    rows: [
      [["\u8F6C\u4EA7\u542F\u52A8\u4F1A\u8BAE", "\u8F6C\u4EA7\u542F\u52A8"]],
      [["\u91CF\u4EA7\u7269\u6599\u8BA1\u5212", "\u7269\u6599\u8BA1\u5212"], ["\u5DE5\u88C5\u5939\u5177\u8BBE\u8BA1", "\u5DE5\u88C5\u5939\u5177"], ["SOP \u7F16\u5236", "SOP\u7F16\u5236"], ["BOM \u51BB\u7ED3", "BOM\u51BB\u7ED3"]],
      [["NPI \u51C6\u5907", "NPI\u51C6\u5907 / DFM\u5206\u6790", "NPI\u51C6\u5907/DFM\u5206\u6790"]],
      [["\u8D22\u52A1\u5206\u6790"]],
      [["NPI \u5BFC\u5165", "NPI\u51C6\u5165\u68C0\u67E5"]],
      // The source places IQC / PVT in one box; do not invent IQC → PVT.
      [["\u91CF\u4EA7\u8BD5\u4EA7\u6765\u6599\u8D28\u91CF\u63A7\u5236", "IQC"], ["\u91CF\u4EA7\u8BD5\u4EA7\u6D4B\u8BD5", "PVT"]],
      [["ADCP", "ADCP \u8BC4\u5BA1", "ADCP\u8BC4\u5BA1"]]
    ]
  },
  {
    id: "launch",
    title: "\u53D1\u5E03",
    rows: [
      [["\u4EA7\u54C1\u5B9A\u4E49\u4E0E\u8BBE\u8BA1\u9700\u6C42\u786E\u8BA4", "\u4EA7\u54C1\u5B9A\u4E49\u4E0E\u8BBE\u8BA1\u9700\u6C42"]],
      [["\u4EA7\u54C1\u5E02\u573A\u51C6\u5907", "\u5E02\u573A\u51C6\u5907"], ["\u4EA7\u54C1\u5B9A\u4EF7\u786E\u8BA4", "\u5B9A\u4EF7\u786E\u8BA4"]],
      [["GA", "GA \u786E\u8BA4", "GA\u786E\u8BA4"]]
    ]
  },
  {
    id: "lifecycle",
    title: "\u751F\u547D\u5468\u671F",
    rows: [
      [["\u7EC4\u5EFA LPDT \u56E2\u961F", "\u7EC4\u5EFALPDT\u56E2\u961F"]],
      [["\u5DE5\u7A0B\u53D8\u66F4\u7BA1\u7406"]],
      [["LDCP", "LDCP \u8BC4\u5BA1", "LDCP\u8BC4\u5BA1"]]
    ]
  }
];
function buildProjectFlowMap(nodes, { isIpd }) {
  if (!isIpd) return { stages: [], unmatched: [...nodes] };
  const byTitle = /* @__PURE__ */ new Map();
  const idCounts = /* @__PURE__ */ new Map();
  for (const node of nodes) {
    const title = String(node.title || "").trim();
    byTitle.set(title, [...byTitle.get(title) || [], node]);
    idCounts.set(node.id, (idCounts.get(node.id) || 0) + 1);
  }
  const matched = /* @__PURE__ */ new Set();
  const stages = [];
  for (const template of ipdReferenceStages) {
    const mappedRows = template.rows.map((slots) => {
      const items = [];
      for (const aliases of slots) {
        const candidates = aliases.flatMap((alias) => byTitle.get(alias) || []);
        if (candidates.length !== 1 || idCounts.get(candidates[0].id) !== 1) continue;
        const node = candidates[0];
        if (matched.has(node)) continue;
        matched.add(node);
        items.push(node);
      }
      return { items, complete: items.length === slots.length };
    });
    const edges = [];
    for (let index = 1; index < mappedRows.length; index++) {
      const previous = mappedRows[index - 1];
      const next = mappedRows[index];
      if (!previous.complete || !next.complete) continue;
      for (const from of previous.items) {
        for (const to of next.items) edges.push({ from: from.id, to: to.id });
      }
    }
    const rows2 = mappedRows.map((row) => row.items).filter((row) => row.length > 0);
    if (rows2.length > 0) stages.push({ id: template.id, title: template.title, rows: rows2, edges, reference: edges.length > 0 });
  }
  return { stages, unmatched: nodes.filter((node) => !matched.has(node)) };
}

// lib/project-metadata.ts
var text = (value) => typeof value === "string" ? value.trim() : "";
var ids = (value) => Array.isArray(value) ? value.filter((id2) => typeof id2 === "string") : [];
var object2 = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
var visibleProjectRecord = (row) => !row.archived && !row.mergedIntoId && !row.private && row.visibility !== "private" && !row.stale && row.confirmed !== false && !["suggestion", "hypothesis"].includes(row.classification) && !["suggestion", "hypothesis"].includes(row.draftClassification);
var visible = visibleProjectRecord;
function display(value) {
  if (Array.isArray(value)) return value.map(display).filter(Boolean).join("\u3001");
  const row = object2(value);
  return text(value) || text(row.label) || text(row.name) || text(row.value);
}
function projectMetadata(s, project) {
  const registration = s.externalObjects.filter((entry) => entry.localObjectId === project.id && entry.verificationStatus === "verified").sort((a, b) => b.collectedAt.localeCompare(a.collectedAt))[0];
  const envelopes = [];
  if (registration?.raw) envelopes.push(object2(registration.raw));
  for (const source of s.sources.filter((source2) => visible(source2) && ids(project.sourceIds).includes(source2.id)).sort((a, b) => text(b.collectedAt).localeCompare(text(a.collectedAt)))) {
    try {
      envelopes.push(object2(JSON.parse(source.excerpt || "{}")));
    } catch {
    }
  }
  let category = display(project.projectCategory || project.category), progress = text(project.projectProgress || project.progressNote);
  let isIpd = /IPD/i.test(category) || project.planTemplate === "ipd";
  for (const envelope of envelopes) {
    const raw = { ...object2(envelope.raw), ...envelope };
    const fields = { ...object2(object2(envelope.raw).fields), ...object2(raw.fields) };
    const pages = Array.isArray(raw.fieldPages) ? raw.fieldPages : Array.isArray(object2(envelope.raw).fieldPages) ? object2(envelope.raw).fieldPages : [];
    for (const value of pages) {
      const page = object2(value), attribute = object2(page.work_item_attribute);
      if (object2(attribute.template).name === "IPD") isIpd = true;
      for (const value2 of Array.isArray(page.work_item_fields) ? page.work_item_fields : []) {
        const field = object2(value2);
        if (text(field.key)) fields[text(field.key)] = field.value;
        if (text(field.name)) fields[text(field.name)] = field.value;
      }
    }
    if (!category) category = display(fields["\u9879\u76EE\u5206\u7C7B"] || fields.projectCategory);
    if (!progress) progress = display(fields.field_5a13c8 || fields["\u9879\u76EE\u8FDB\u5EA6"]);
    if (/IPD/i.test(category)) isIpd = true;
  }
  return { isIpd, progress, category };
}

// lib/project-gates.ts
var text2 = (v) => typeof v === "string" ? v.trim() : "";
var ids2 = (v) => Array.isArray(v) ? v.filter((id2) => typeof id2 === "string") : [];
var approved = (v) => ["\u5DF2\u9A8C\u6536", "\u9A8C\u6536\u901A\u8FC7", "\u5DF2\u901A\u8FC7", "\u901A\u8FC7"].includes(text2(v));
var completed = (v) => ["\u5DF2\u5B8C\u6210", "finished"].includes(text2(v));
function gateDate(value) {
  const v = text2(value), n = Date.parse(v + "T12:00:00Z");
  return /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(n) && new Date(n).toISOString().slice(0, 10) === v ? v : "";
}
function getProjectGates(s, project) {
  const related2 = (rows2) => [...new Map(rows2.filter((row) => visibleProjectRecord(row) && ids2(row.projectIds).includes(project.id)).map((row) => [row.id, row])).values()];
  const nodes = related2(s.flowNodes), legacy = related2(s.milestones), { isIpd } = projectMetadata(s, project);
  const mapped = buildProjectFlowMap(nodes, { isIpd });
  const stageByNode = new Map(mapped.stages.flatMap((stage, index) => stage.rows.flat().map((row) => [row.id, { title: stage.title + "\u9636\u6BB5", index }])));
  const phaseOf = (row) => text2(row.sourceStage) || stageByNode.get(row.id)?.title || "";
  const gates = nodes.length ? nodes.filter((row) => flowNodeTypeLabel(row, { isIpd }) === "\u91CC\u7A0B\u7891\u8282\u70B9").map((row) => {
    const linked = legacy.filter((gate) => ids2(row.milestoneIds).includes(gate.id));
    const supplement = linked.length === 1 && nodes.filter((other) => ids2(other.milestoneIds).includes(linked[0].id)).length === 1 ? linked[0] : void 0;
    return { id: row.id, kind: "flowNodes", title: row.title, date: gateDate(row.plannedEnd) || gateDate(supplement?.committed || supplement?.plannedEnd), accepted: completed(row.nodeStatus) || approved(text2(row.acceptanceStatus) || supplement?.acceptanceStatus), completed: completed(row.nodeStatus), phase: phaseOf(row) };
  }) : legacy.map((row) => ({ id: row.id, kind: "milestones", title: row.title, date: gateDate(row.committed || row.plannedEnd), accepted: approved(row.acceptanceStatus), completed: completed(row.status), phase: text2(row.sourceStage) }));
  gates.sort((a, b) => (a.date || "9999").localeCompare(b.date || "9999") || (stageByNode.get(a.id)?.index ?? 99) - (stageByNode.get(b.id)?.index ?? 99) || a.id.localeCompare(b.id));
  const pending3 = gates.filter((gate) => !gate.accepted), preference = text2(project.nextGateId);
  const manual = pending3.find((gate) => gate.id === preference), automatic = pending3.find((gate) => gate.date);
  const next = manual || automatic || null, mode = manual ? "manual" : preference ? "fallback" : "automatic";
  const unavailable = gates.find((gate) => gate.id === preference);
  const notice = mode === "fallback" ? unavailable?.accepted ? "\u539F\u9009\u5173\u53E3\u5DF2\u9A8C\u6536\uFF0C\u5F53\u524D\u6309\u8BA1\u5212\u65E5\u671F\u9009\u53D6\u3002" : "\u539F\u9009\u5173\u53E3\u5DF2\u4E0D\u53EF\u7528\uFF0C\u5F53\u524D\u6309\u8BA1\u5212\u65E5\u671F\u9009\u53D6\u3002" : manual && !manual.date ? "\u5DF2\u624B\u52A8\u6307\u5B9A\uFF1B\u8BA1\u5212\u65E5\u671F\u5F85\u8865\u5145\u3002" : "";
  const active5 = mapped.stages.find((stage) => stage.rows.flat().some((row) => ["\u8FDB\u884C\u4E2D", "doing", "started"].includes(text2(row.nodeStatus))));
  return { gates, next, mode, notice, isIpd, usesFlowNodes: nodes.length > 0, phase: next?.phase || text2(project.phase) || (active5 ? active5.title + "\u9636\u6BB5" : "\u9636\u6BB5\u5F85\u6838\u5BF9") };
}

// lib/weekly-record-fields.ts
var object3 = (v) => v && typeof v === "object" && !Array.isArray(v) ? v : {};
var text3 = (v) => typeof v === "string" ? v.trim() : "";
var active = (p) => !p.archived && !p.private && p.visibility !== "private" && !p.stale && p.confirmed !== false;
function weeklyRecordFields(s, row) {
  const registration = s.externalObjects.filter((x) => x.localObjectId === row.id && x.verificationStatus === "verified" && !s.sources.some((source) => source.id === x.sourceId && (!active(source) || ["suggestion", "hypothesis"].includes(source.classification)))).sort((a, b) => b.collectedAt.localeCompare(a.collectedAt))[0];
  const raw = object3(registration?.raw);
  const pages = Array.isArray(raw.fieldPages) ? raw.fieldPages : [];
  const fields = pages.flatMap((p) => {
    const page = object3(p);
    return (Array.isArray(page.work_item_fields) ? page.work_item_fields : []).map((f) => {
      const field2 = object3(f);
      return { name: text3(field2.name), value: field2.value };
    });
  });
  const field = (names) => fields.find((f) => names.includes(f.name) && f.value !== null && f.value !== void 0);
  const clear = (name) => s.audit.some((a) => a.objectId === row.id && /^(manual\.|draft\.accept)/.test(a.operation) && !!text3(object3(a.before)[name]) && Object.hasOwn(object3(a.after), name) && object3(a.after)[name] === "");
  function calendar(value) {
    const direct = gateDate(value);
    if (direct) return direct;
    const record2 = object3(value), iso = text3(record2.iso_time);
    if (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(iso) || !Number.isFinite(Date.parse(iso))) return "";
    if (!gateDate(iso.slice(0, 10))) return "";
    return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(iso));
  }
  const endField = field(["\u8BA1\u5212\u5B8C\u6210\u65E5\u671F", "\u8BA1\u5212\u7ED3\u675F\u65E5\u671F", "\u8BA1\u5212\u7ED3\u675F\u65F6\u95F4"]);
  const startField = field(["\u8BA1\u5212\u5F00\u59CB\u65E5\u671F", "\u8BA1\u5212\u5F00\u59CB\u65F6\u95F4"]);
  const forecastField = field(["\u9884\u8BA1\u5B8C\u6210\u65E5\u671F", "\u9884\u8BA1\u5B8C\u6210\u65F6\u95F4"]);
  const responsibility = field(["\u8D23\u4EFB\u4EBA", "\u4EA4\u4ED8\u7269\u8D1F\u8D23\u4EBA", "\u8D1F\u8D23\u4EBA"]);
  const scope = registration ? [registration.system, registration.host, registration.spaceKey].join(":") : "local:" + s.workspaceId;
  function refs(value, external = false) {
    if (Array.isArray(value)) return value.flatMap((v) => refs(v, external));
    const obj = object3(value), token2 = text3(value) || text3(obj.id || obj.key || obj.user_key || obj.open_id), label2 = text3(obj.name || obj.displayName || obj.display_name);
    if (/^[\[{]/.test(token2)) {
      try {
        return refs(JSON.parse(token2), external);
      } catch {
        return [];
      }
    }
    const candidates = s.people.filter((p) => active(p) && (!!token2 && [p.id, p.meegleUserKey, p.feishuUserId].includes(token2) || !!(label2 || token2) && p.title === (label2 || token2)));
    if (candidates.length === 1) return [{ id: candidates[0].id, title: candidates[0].title }];
    if (external && token2 && label2) return [{ id: "remote-owner:" + scope + ":" + token2, title: label2 }];
    return [];
  }
  const local = refs(row.ownerId || row.owner);
  const remote = refs(responsibility?.value, true);
  const normalize2 = (value) => value.split(/[、,，;]/).map((v) => v.trim()).filter(Boolean).sort().join("|");
  let owners = local;
  if (!owners.length && !clear("owner") && !row.ownerId && remote.length && (!text3(row.owner) || normalize2(text3(row.owner)) === normalize2(remote.map((r) => r.title).join("\u3001")))) owners = remote;
  owners = [...new Map(owners.map((r) => [r.id, r])).values()];
  const fallback = (name, value) => !text3(row[name]) && !clear(name) ? calendar(value) : "";
  const plannedEnd = gateDate(row.plannedEnd) || fallback("plannedEnd", endField?.value);
  const plannedStart = gateDate(row.plannedStart) || fallback("plannedStart", startField?.value);
  const forecast = gateDate(row.forecast) || gateDate(row.expectedAt) || fallback("forecast", forecastField?.value);
  return {
    ownerRefs: owners,
    ownerName: owners.map((r) => r.title).join("\u3001"),
    plannedEnd,
    plannedStart,
    forecast,
    savedFieldAt: registration?.collectedAt || "",
    usesSavedOwner: !local.length && owners.length > 0,
    usesSavedDate: !gateDate(row.plannedEnd) && !!plannedEnd
  };
}

// lib/portfolio.ts
var text4 = (value) => typeof value === "string" ? value.trim() : "";
var completed2 = /* @__PURE__ */ new Set(["\u5DF2\u5B8C\u6210", "\u5B8C\u6210", "\u56E2\u961F\u53CD\u9988\u5B8C\u6210", "\u6267\u884C\u5B8C\u6210", "\u5DF2\u4EA4\u4ED8"]);
var accepted = /* @__PURE__ */ new Set(["\u9A8C\u6536\u901A\u8FC7", "\u5DF2\u9A8C\u6536", "\u5DF2\u901A\u8FC7", "\u901A\u8FC7"]);
var knownProgress = /* @__PURE__ */ new Set(["\u672A\u5F00\u59CB", "\u5F85\u542F\u52A8", "\u5F85\u5F00\u59CB", "\u8FDB\u884C\u4E2D", "\u6267\u884C\u4E2D", "\u5904\u7406\u4E2D", "\u963B\u585E", "\u53D7\u963B", "\u5DF2\u963B\u585E", "\u5EF6\u671F", "\u5F85\u9A8C\u6536", ...completed2]);
var isAccepted = (item) => accepted.has(text4(item.acceptanceStatus));
var executionComplete = (item) => text4(item.executionStatus) ? completed2.has(text4(item.executionStatus)) : completed2.has(text4(item.status)) || !!text4(item.actual);
function isBlocked(item) {
  if (item.archived) return false;
  const blocker = text4(item.blocker);
  return !!blocker && !["\u65E0", "\u6682\u65E0", "\u65E0\u5361\u70B9", "\u65E0\u963B\u585E", "\u5DF2\u89E3\u9664"].includes(blocker) || [item.status, item.executionStatus].some((value) => ["\u963B\u585E", "\u53D7\u963B", "\u5DF2\u963B\u585E", "\u9700\u8981\u5347\u7EA7\u534F\u8C03"].includes(text4(value)));
}
function needsFollowUp(item, date4 = today()) {
  if (item.archived || isAccepted(item)) return false;
  const checkAt = text4(item.checkAt);
  const dueAt = text4(item.dueAt || item.committed);
  return isBlocked(item) || checkAt !== "" && checkAt <= date4 || ["\u4ECA\u5929\u9700\u8981\u63A8\u52A8", "\u9700\u8981\u5347\u7EA7\u534F\u8C03"].includes(text4(item.status)) || !executionComplete(item) && dueAt !== "" && dueAt < date4;
}

// lib/project-level.ts
var projectLevels = ["L3", "L2", "L1", "\u672A\u5B9A\u7EA7"];
var text5 = (value) => {
  if (typeof value === "string") return value.trim();
  if (value && typeof value === "object" && "label" in value) return text5(value.label);
  return "";
};
var normalize = (value) => {
  const result = text5(value);
  return ["L1", "L2", "L3"].includes(result) ? result : "\u672A\u5B9A\u7EA7";
};
function projectLevel(s, project) {
  if (Object.hasOwn(project, "projectLevel")) return normalize(project.projectLevel);
  const registered = (s.externalObjects || []).filter((row) => row.localObjectId === project.id && row.verificationStatus === "verified").sort((a, b) => b.collectedAt.localeCompare(a.collectedAt))[0];
  const fields = registered?.raw?.fields;
  if (fields && typeof fields === "object" && "field_c107ba" in fields) return normalize(fields.field_c107ba);
  for (const source of s.sources.filter((row) => project.sourceIds?.includes(row.id) && !row.archived).sort((a, b) => String(b.collectedAt || "").localeCompare(String(a.collectedAt || "")))) {
    try {
      const row = JSON.parse(source.excerpt || "{}");
      const raw = row.raw || {};
      if (Object.hasOwn(row.fields || {}, "projectLevel")) return normalize(row.fields.projectLevel);
      if (Object.hasOwn(raw.fields || {}, "field_c107ba")) return normalize(raw.fields.field_c107ba);
      if (Object.hasOwn(raw, "\u7EA7\u522B")) return normalize(raw["\u7EA7\u522B"]);
    } catch {
    }
  }
  return "\u672A\u5B9A\u7EA7";
}
function ranked(s) {
  return s.projects.map((item, index) => ({ item, index, level: projectLevel(s, item), rank: typeof item.sortOrder === "number" && Number.isFinite(item.sortOrder) && item.sortOrder >= 0 ? item.sortOrder : index + 1 })).filter((row) => !row.item.archived).sort((a, b) => projectLevels.indexOf(a.level) - projectLevels.indexOf(b.level) || a.rank - b.rank || a.index - b.index);
}
function sortProjectsByLevel(s) {
  return ranked(s).map((row) => row.item);
}

// lib/weekly-meeting.ts
var text6 = (value) => typeof value === "string" ? value.trim() : "";
var ids3 = (value) => Array.isArray(value) ? value.filter((id2) => typeof id2 === "string") : [];
var object4 = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};
var visible2 = (row) => !row.archived && !row.mergedIntoId && !row.private && row.visibility !== "private" && !row.stale && row.confirmed !== false && !["suggestion", "hypothesis"].includes(row.classification) && !["suggestion", "hypothesis"].includes(row.draftClassification);
var unique = (rows2) => [...new Map(rows2.filter(visible2).map((row) => [row.id, row])).values()];
var approved2 = (value) => ["\u5DF2\u9A8C\u6536", "\u9A8C\u6536\u901A\u8FC7", "\u5DF2\u901A\u8FC7", "\u901A\u8FC7"].includes(text6(value));
var date = (value) => {
  const candidate = text6(value);
  const parsed = Date.parse(candidate + "T12:00:00Z");
  return /^\d{4}-\d{2}-\d{2}$/.test(candidate) && Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0, 10) === candidate ? candidate : "";
};
function status(value) {
  const label2 = text6(value);
  return { finished: "\u5DF2\u5B8C\u6210", started: "\u8FDB\u884C\u4E2D", doing: "\u8FDB\u884C\u4E2D", unstarted: "\u5F85\u5F00\u59CB", not_started: "\u5F85\u5F00\u59CB", "\u672A\u5F00\u59CB": "\u5F85\u5F00\u59CB" }[label2] || label2 || "\u5F85\u786E\u8BA4";
}
function owner(value, people) {
  if (Array.isArray(value)) return [...new Set(value.map((item) => owner(item, people)).filter(Boolean))].join("\u3001");
  const row = object4(value), label2 = text6(row.name || row.display_name || row.displayName);
  if (label2) return label2;
  const token2 = text6(value) || text6(row.id || row.key || row.user_key || row.open_id);
  if (/^[\[{]/.test(token2)) {
    try {
      return owner(JSON.parse(token2), people);
    } catch {
      return "";
    }
  }
  const person = people.find((person2) => [person2.id, person2.meegleUserKey, person2.feishuUserId].includes(token2) && visible2(person2));
  if (person) return person.title;
  return /^\d{7,}$|^(ou_|on_|user_|person-)/.test(token2) ? "" : token2;
}
function buildWeeklyMeetingSnapshot(s, generatedAt = (/* @__PURE__ */ new Date()).toISOString()) {
  const projectRows = unique(s.projects);
  const projects = projectRows.map((project) => {
    const related2 = (rows2) => unique(rows2).filter((row) => ids3(row.projectIds).includes(project.id));
    const metadata = projectMetadata(s, project), projectFields = weeklyRecordFields(s, project);
    const rawNodes = related2(s.flowNodes), legacy = related2(s.milestones);
    const person = (row, field = "owner") => owner(row[field + "Id"], s.people) || owner(row[field], s.people);
    const nodes = rawNodes.map((row) => {
      const linked = legacy.filter((gate) => ids3(row.milestoneIds).includes(gate.id));
      const uniqueLegacy = linked.length === 1 && rawNodes.filter((node) => ids3(node.milestoneIds).includes(linked[0].id)).length === 1 ? linked[0] : void 0;
      const explicitAcceptance = text6(row.acceptanceStatus) || text6(uniqueLegacy?.acceptanceStatus);
      const fields = weeklyRecordFields(s, row);
      return {
        id: row.id,
        title: text6(row.title),
        projectIds: [project.id],
        sourceIds: [],
        nodeStatus: status(row.nodeStatus),
        blocked: isBlocked(row),
        nodeType: text6(row.nodeType),
        owner: person(row) || fields.ownerName,
        plannedStart: date(row.plannedStart),
        plannedEnd: date(row.plannedEnd) || date(uniqueLegacy?.committed || uniqueLegacy?.plannedEnd),
        forecast: fields.forecast,
        sourceStage: text6(row.sourceStage),
        planStageId: text6(row.planStageId),
        acceptanceStatus: approved2(explicitAcceptance) ? "\u5DF2\u9A8C\u6536" : explicitAcceptance,
        progressNote: text6(row.progressNote)
      };
    });
    const nodeIds = new Set(nodes.map((node) => node.id));
    const deliverables = related2(s.deliverables).map((row) => {
      const fields = weeklyRecordFields(s, row);
      return {
        id: row.id,
        title: text6(row.title),
        projectIds: [project.id],
        sourceIds: [],
        flowNodeIds: ids3(row.flowNodeIds).filter((id2) => nodeIds.has(id2)),
        owner: person(row) || fields.ownerName,
        ownerRefs: fields.ownerRefs,
        plannedEnd: fields.plannedEnd,
        savedFieldAt: fields.savedFieldAt,
        usesSavedOwner: fields.usesSavedOwner,
        usesSavedDate: fields.usesSavedDate,
        status: text6(row.status),
        submissionStatus: text6(row.submissionStatus),
        deliveryReview: observedDeliveryReview(row),
        acceptanceStatus: approved2(row.acceptanceStatus) ? "\u5DF2\u9A8C\u6536" : text6(row.acceptanceStatus),
        progressNote: text6(row.deliverableProgress || row.progressNote)
      };
    });
    const gateView = getProjectGates(s, project);
    const phase = gateView.phase;
    const work = related2(s.actions);
    const blockerRows = unique([...rawNodes, ...related2(s.deliverables), ...work]).filter((row) => isBlocked(row) && !approved2(row.acceptanceStatus));
    const issues = blockerRows.map((row) => ({
      id: row.id,
      kind: "\u5361\u70B9",
      title: text6(row.blocker) || text6(row.title),
      detail: text6(row.blockerImpact) || text6(row.title),
      owner: owner(row.blockerOwner, s.people) || person(row) || person(row, "executor"),
      next: text6(row.followUp),
      date: date(row.checkAt)
    }));
    for (const row of related2(s.risks).filter((row2) => row2.confirmed === true && row2.status !== "\u5DF2\u5173\u95ED")) issues.push({
      id: row.id,
      kind: "\u98CE\u9669",
      title: text6(row.title),
      detail: text6(row.impact),
      owner: person(row),
      next: text6(row.response),
      date: date(row.checkAt)
    });
    for (const row of related2(s.decisions).filter((row2) => ["\u5F85\u51B3\u7B56", "\u6682\u7F13"].includes(row2.status))) issues.push({
      id: row.id,
      kind: "\u5F85\u534F\u8C03",
      title: text6(row.title),
      detail: text6(row.impact),
      owner: person(row),
      next: text6(row.recommendation),
      date: date(row.deadline)
    });
    const issueIds = new Set(issues.map((issue) => issue.id));
    const nextSteps = work.filter((row) => !approved2(row.acceptanceStatus) && !issueIds.has(row.id)).map((row) => ({
      id: row.id,
      title: text6(row.followUp) || text6(row.title),
      owner: person(row, "executor") || person(row),
      date: date(row.checkAt) || date(row.dueAt)
    }));
    if (text6(project.nextAction) && !nextSteps.some((row) => row.title === text6(project.nextAction))) nextSteps.unshift({ id: project.id + "-next", title: text6(project.nextAction), owner: person(project), date: "" });
    nextSteps.sort((a, b) => (a.date || "9999").localeCompare(b.date || "9999"));
    return {
      id: project.id,
      title: text6(project.title),
      code: text6(project.code),
      phase,
      owner: person(project),
      level: projectLevel(s, project),
      progress: metadata.progress,
      updatedAt: text6(project.updatedAt),
      isIpd: metadata.isIpd,
      nodes,
      deliverables,
      nextGate: gateView.next,
      gateMode: gateView.mode,
      gateNotice: gateView.notice,
      gates: gateView.gates.map((gate) => ({ ...gate })),
      plannedStart: projectFields.plannedStart,
      plannedEnd: projectFields.plannedEnd,
      planTemplate: text6(project.planTemplate),
      nextGateForecast: date((gateView.next?.kind === "flowNodes" ? nodes : legacy).find((n) => n.id === gateView.next?.id)?.forecast) || date((gateView.next?.kind === "flowNodes" ? rawNodes : legacy).find((n) => n.id === gateView.next?.id)?.expectedAt),
      acceptedGates: gateView.gates.filter((gate) => gate.accepted).map((gate) => gate.title),
      completedWithoutAcceptance: gateView.gates.filter((gate) => gate.completed && !gate.accepted).length,
      unlinkedDeliverables: deliverables.filter((row) => !row.flowNodeIds.length).length,
      issues,
      nextSteps
    };
  });
  projects.sort((a, b) => Number(b.issues.some((issue) => issue.kind === "\u5361\u70B9")) - Number(a.issues.some((issue) => issue.kind === "\u5361\u70B9")) || projectLevels.indexOf(a.level) - projectLevels.indexOf(b.level) || (a.nextGate?.date || "9999").localeCompare(b.nextGate?.date || "9999"));
  return { workspaceId: s.workspaceId, workspaceName: s.workspaceName, revision: s.revision, generatedAt, demo: s.workspaceType === "demo", projects };
}

// lib/project-plan.ts
var planTemplates = [
  { id: "general", title: "\u901A\u7528\u56DB\u9636\u6BB5", description: "\u6309\u9879\u76EE\u7BA1\u7406\u89C4\u8303\u7EC4\u7EC7\u5B8C\u6574\u8BA1\u5212\uFF0C\u5177\u4F53\u8282\u70B9\u548C\u5DE5\u4F5C\u9010\u6B65\u8865\u5145\u3002", stages: [
    { id: "general:initiation", title: "\u6982\u5FF5\u4E0E\u542F\u52A8", description: "\u76EE\u6807\u3001\u8303\u56F4\u3001\u9879\u76EE\u7AE0\u7A0B\u4E0E\u542F\u52A8\u4F9D\u636E" },
    { id: "general:planning", title: "\u89C4\u5212\u4E0E\u8BBE\u8BA1", description: "\u5DE5\u4F5C\u5206\u89E3\u3001\u8BA1\u5212\u3001\u8D23\u4EFB\u3001\u8D44\u6E90\u4E0E\u9A8C\u6536\u8981\u6C42" },
    { id: "general:execution", title: "\u6267\u884C\u4E0E\u76D1\u63A7", description: "\u6267\u884C\u53CD\u9988\u3001\u4EA4\u4ED8\u6210\u679C\u3001\u98CE\u9669\u548C\u53D8\u66F4" },
    { id: "general:closure", title: "\u6536\u5C3E\u4E0E\u4EA4\u4ED8", description: "\u6B63\u5F0F\u9A8C\u6536\u3001\u5F52\u6863\u3001\u590D\u76D8\u4E0E\u8D23\u4EFB\u627F\u63A5" }
  ] },
  { id: "ipd", title: "IPD \u516D\u9636\u6BB5", description: "\u5BF9\u5E94\u4EA7\u54C1\u5F00\u53D1\u6846\u67B6\uFF1B\u9636\u6BB5\u4E2D\u7684\u5173\u5361\u548C\u4EA4\u4ED8\u8981\u6C42\u6309\u5B9E\u9645\u9879\u76EE\u8865\u5145\u3002", stages: [
    { id: "ipd:concept", title: "\u6982\u5FF5\u9636\u6BB5", description: "\u9700\u6C42\u3001\u8D28\u91CF\u76EE\u6807\u3001\u6280\u672F\u65B9\u5411\u4E0E CDCP" },
    { id: "ipd:planning", title: "\u8BA1\u5212\u9636\u6BB5", description: "\u5F00\u53D1\u8BA1\u5212\u3001\u6D4B\u8BD5\u7B56\u7565\u3001\u6982\u8981\u8BBE\u8BA1\u4E0E PDCP" },
    { id: "ipd:development", title: "\u5F00\u53D1\u9636\u6BB5", description: "\u8BBE\u8BA1\u5F00\u53D1\u3001\u6837\u673A\u3001\u6D4B\u8BD5\u4E0E DVT \u8BC4\u5BA1" },
    { id: "ipd:verification", title: "\u9A8C\u8BC1\u9636\u6BB5", description: "\u8F6C\u4EA7\u3001BOM\u3001NPI\u3001PVT \u4E0E ADCP" },
    { id: "ipd:release", title: "\u53D1\u5E03\u9636\u6BB5", description: "\u53D1\u5E03\u51C6\u5907\u3001GA \u786E\u8BA4\u4E0E\u4EA4\u4ED8\u627F\u63A5" },
    { id: "ipd:lifecycle", title: "\u751F\u547D\u5468\u671F", description: "\u4EA7\u54C1\u7EF4\u62A4\u3001\u5DE5\u7A0B\u53D8\u66F4\u4E0E\u9000\u5E02" }
  ] },
  { id: "irad", title: "IRAD \u56DB\u9636\u6BB5", description: "\u5BF9\u5E94\u5185\u90E8\u7814\u53D1\u4F18\u5316\u6846\u67B6\uFF0C\u4E0D\u81EA\u52A8\u5957\u7528\u65B0\u54C1\u4E0A\u5E02\u6D41\u7A0B\u3002", stages: [
    { id: "irad:concept", title: "\u6982\u5FF5\u9636\u6BB5", description: "\u95EE\u9898\u3001\u8303\u56F4\u3001\u9002\u7528\u6027\u4E0E\u6280\u672F\u65B9\u6848\u65B9\u5411" },
    { id: "irad:planning", title: "\u8BA1\u5212\u9636\u6BB5", description: "\u5F00\u53D1\u8BA1\u5212\u3001\u6D4B\u8BD5\u7B56\u7565\u3001\u8D44\u6E90\u4E0E\u98CE\u9669" },
    { id: "irad:development", title: "\u5F00\u53D1\u9636\u6BB5", description: "\u5F00\u53D1\u5B9E\u65BD\u3001\u521D\u6B65\u9A8C\u8BC1\u4E0E\u5FC5\u8981\u7684\u8BD5\u5236" },
    { id: "irad:closure", title: "\u9A8C\u8BC1\u4E0E\u7ED3\u9898", description: "\u9A8C\u8BC1\u7ED3\u679C\u3001\u53D8\u66F4\u5BFC\u5165\u3001\u5F52\u6863\u4E0E\u7ED3\u9898" }
  ] }
];
var planStageIds = new Set(planTemplates.flatMap((template) => template.stages.map((stage) => stage.id)));
var planStageOptions = planTemplates.flatMap((template) => template.stages.map((stage) => ({ value: stage.id, label: `${template.title} \xB7 ${stage.title}` })));

// lib/weekly-charts.ts
var meetingDay = (time) => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit"
}).format(new Date(time));

// lib/weekly-review.ts
var record = (v) => !!v && typeof v === "object" && !Array.isArray(v);
var text7 = (v) => typeof v === "string" ? v.trim() : "";
var unique2 = (rows2) => [...new Map(rows2.map((row) => [row.id, row])).values()];
var same2 = (a, b) => JSON.stringify(a) === JSON.stringify(b);
var reject = (message, status2 = 422) => {
  throw Object.assign(new Error(message), { status: status2 });
};
var validWeight = (v) => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1e4;
var validId = (v) => typeof v === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(v);
var key = (value) => JSON.stringify(value);
var emptyStore = () => ({ schemaVersion: 1, version: 0, profiles: {}, history: [] });
function weeklyStore(s) {
  return s.weeklyReview || emptyStore();
}
function weeklyScopeKey(project) {
  return key({
    projectId: project.id,
    template: project.planTemplate,
    isIpd: project.isIpd,
    nodes: project.nodes.map((n) => [n.id, n.title, n.planStageId, n.sourceStage]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
    outputs: project.deliverables.map((d) => [d.id, d.title, [...d.flowNodeIds].sort(), d.submissionStatus === "\u514D\u4EA4\u4ED8"]).sort((a, b) => String(a[0]).localeCompare(String(b[0])))
  });
}
function suggestedWeights(project) {
  const template = planTemplates.find((t) => t.id === (project.isIpd ? "ipd" : project.planTemplate)) || planTemplates[0];
  const stageValues = project.isIpd ? [10, 15, 30, 25, 15, 5] : template.id === "irad" ? [15, 20, 40, 25] : [15, 20, 45, 20];
  const stages = template.stages.map((stage, i) => ({ id: stage.id, title: stage.title, weight: stageValues[i] }));
  const mapped = buildProjectFlowMap(project.nodes, { isIpd: project.isIpd });
  const aliases = { concept: "ipd:concept", plan: "ipd:planning", development: "ipd:development", verification: "ipd:verification", launch: "ipd:release", lifecycle: "ipd:lifecycle" };
  const nodeStages = /* @__PURE__ */ new Map();
  for (const stage of mapped.stages) for (const node of stage.rows.flat()) if (aliases[stage.id]) nodeStages.set(node.id, aliases[stage.id]);
  for (const node of project.nodes) {
    const explicit = stages.find((stage) => stage.id === node.planStageId || stage.title === node.sourceStage || stage.title.replace(/阶段$/, "") === node.sourceStage);
    if (explicit) nodeStages.set(node.id, explicit.id);
  }
  const outputs = project.deliverables.map((output) => {
    const linked = [...new Set(output.flowNodeIds.map((id2) => nodeStages.get(id2)).filter(Boolean))];
    const milestone = output.flowNodeIds.some((id2) => project.gates?.some((g) => g.id === id2));
    return { id: output.id, stageId: linked.length === 1 ? linked[0] : "", weight: output.submissionStatus === "\u514D\u4EA4\u4ED8" ? 0 : milestone ? 3 : 1 };
  });
  return { stages, outputs, scopeKey: weeklyScopeKey(project), confirmedAt: "" };
}
function profileShapeErrors(value) {
  if (!record(value) || !Array.isArray(value.stages) || !Array.isArray(value.outputs) || typeof value.scopeKey !== "string" || typeof value.confirmedAt !== "string") return ["\u6743\u91CD\u914D\u7F6E\u683C\u5F0F\u65E0\u6548"];
  const stages = value.stages, outputs = value.outputs;
  if (!stages.length || stages.length > 60 || outputs.length > 2e4) return ["\u9636\u6BB5\u6216\u4EA4\u4ED8\u7269\u6570\u91CF\u65E0\u6548"];
  if (stages.some((s) => !record(s) || !validId(s.id) || !text7(s.title) || text7(s.title).length > 100 || !validWeight(s.weight))) return ["\u9636\u6BB5\u540D\u79F0\u6216\u6743\u91CD\u65E0\u6548"];
  if (outputs.some((d) => !record(d) || !validId(d.id) || !validId(d.stageId) || !validWeight(d.weight))) return ["\u8BF7\u4E3A\u6BCF\u4E2A\u4EA4\u4ED8\u7269\u9009\u62E9\u9636\u6BB5\u5E76\u586B\u5199\u975E\u8D1F\u6743\u91CD"];
  const ss = stages, dd = outputs;
  if (new Set(ss.map((s) => s.id)).size !== ss.length || new Set(dd.map((d) => d.id)).size !== dd.length) return ["\u9636\u6BB5\u6216\u4EA4\u4ED8\u7269\u4E0D\u53EF\u91CD\u590D\u8BA1\u5206"];
  if (Math.abs(ss.reduce((sum, s) => sum + s.weight, 0) - 100) > 1e-5) return ["\u9636\u6BB5\u6743\u91CD\u5408\u8BA1\u987B\u4E3A 100%"];
  if (dd.some((d) => !ss.some((s) => s.id === d.stageId))) return ["\u4EA4\u4ED8\u7269\u5173\u8054\u4E86\u4E0D\u5B58\u5728\u7684\u9636\u6BB5"];
  if (ss.some((s) => s.weight > 0 && !dd.some((d) => d.stageId === s.id && d.weight > 0))) return ["\u6709\u6743\u91CD\u7684\u9636\u6BB5\u987B\u81F3\u5C11\u5305\u542B\u4E00\u9879\u6709\u6743\u91CD\u7684\u4EA4\u4ED8\u7269\uFF1B\u4E0D\u9002\u7528\u7684\u9636\u6BB5\u8BF7\u660E\u786E\u8BBE\u4E3A 0"];
  return [];
}
function weightedProgress(project, profile) {
  const scopeKey = weeklyScopeKey(project), outputs = unique2(project.deliverables), accepted5 = outputs.filter(deliveryRecorded).length;
  const base = { accepted: accepted5, total: outputs.length, stages: [], profileKey: "", scopeKey };
  if (!outputs.length) return { ...base, percent: null, reason: "\u4EA4\u4ED8\u7269\u5F85\u8865\u5145" };
  if (!profile?.confirmedAt) return { ...base, percent: null, reason: "\u6743\u91CD\u5F85\u786E\u8BA4" };
  const errors = profileShapeErrors(profile);
  if (errors.length) return { ...base, percent: null, reason: "\u6743\u91CD\u914D\u7F6E\u5F85\u6838\u5BF9" };
  const expected = outputs.map((d) => d.id).sort(), actual = profile.outputs.map((d) => d.id).sort();
  if (profile.scopeKey !== scopeKey || !same2(expected, actual)) return { ...base, percent: null, reason: "\u4EA4\u4ED8\u8303\u56F4\u5DF2\u53D8\u5316\uFF0C\u9700\u91CD\u65B0\u6838\u5BF9\u6743\u91CD" };
  const byId = new Map(outputs.map((d) => [d.id, d]));
  const stages = profile.stages.map((stage) => {
    const parts = profile.outputs.filter((d) => d.stageId === stage.id), denominator = parts.reduce((sum, d) => sum + d.weight, 0);
    const approved3 = parts.filter((d) => !!byId.get(d.id) && deliveryRecorded(byId.get(d.id)));
    return { ...stage, earned: denominator ? stage.weight * approved3.reduce((sum, d) => sum + d.weight, 0) / denominator : 0, accepted: approved3.length, total: parts.length };
  });
  const percent = Math.round(stages.reduce((sum, s) => sum + s.earned, 0) * 10) / 10;
  return { ...base, stages, percent, reason: "", profileKey: key({ stages: profile.stages, outputs: profile.outputs }) };
}
function buildWeeklyReviewView(s, generatedAt = (/* @__PURE__ */ new Date()).toISOString()) {
  const snapshot = buildWeeklyMeetingSnapshot(s, generatedAt), store = weeklyStore(s);
  return {
    snapshot,
    version: store.version,
    profiles: structuredClone(store.profiles),
    progress: Object.fromEntries(snapshot.projects.map((p) => [p.id, weightedProgress(p, store.profiles[p.id])])),
    history: structuredClone(store.history)
  };
}
function weeklyStateErrors(s) {
  const value = s.weeklyReview;
  if (value === void 0) return [];
  const fail8 = (message) => [{ path: "weeklyReview", message }];
  if (!record(value) || value.schemaVersion !== 1 || !Number.isInteger(value.version) || value.version < 0 || !record(value.profiles) || !Array.isArray(value.history)) return fail8("\u5468\u4F8B\u4F1A\u914D\u7F6E\u6216\u5386\u53F2\u683C\u5F0F\u65E0\u6548");
  for (const [id2, profile] of Object.entries(value.profiles)) if (!validId(id2) || profileShapeErrors(profile).length || !Number.isFinite(Date.parse(profile.confirmedAt))) return fail8("\u5468\u4F8B\u4F1A\u6743\u91CD\u8BB0\u5F55\u65E0\u6548");
  if (value.history.length > 5e3 || value.history.some((row) => !record(row)) || new Set(value.history.map((row) => row.id)).size !== value.history.length) return fail8("\u5468\u4F8B\u4F1A\u5386\u53F2\u8BB0\u5F55\u6570\u91CF\u6216\u8EAB\u4EFD\u65E0\u6548");
  for (const row of value.history) {
    if (!record(row) || !validId(row.id) || typeof row.createdAt !== "string" || !Number.isFinite(Date.parse(row.createdAt)) || !text7(row.title) || row.title.length > 120 || !Number.isInteger(row.revision) || !Array.isArray(row.points) || row.points.some((p) => !record(p)) || new Set(row.points.map((p) => p.projectId)).size !== row.points.length) return fail8("\u5468\u4F8B\u4F1A\u5386\u53F2\u8BB0\u5F55\u65E0\u6548");
    if (row.points.some((p) => !validId(p.projectId) || p.percent !== null && (!Number.isFinite(p.percent) || p.percent < 0 || p.percent > 100) || typeof p.profileKey !== "string" || typeof p.scopeKey !== "string")) return fail8("\u5468\u4F8B\u4F1A\u5386\u53F2\u8FDB\u5EA6\u65E0\u6548");
  }
  return [];
}
function applyWeeklyReviewCommand(s, input, at = (/* @__PURE__ */ new Date()).toISOString()) {
  if (!record(input) || input.workspaceId !== s.workspaceId || !validId(input.requestId)) reject("\u5468\u4F8B\u4F1A\u8BF7\u6C42\u8EAB\u4EFD\u6216\u5DE5\u4F5C\u533A\u65E0\u6548");
  const fingerprint = key(input), receipt2 = Object.hasOwn(s.receipts, input.requestId) ? s.receipts[input.requestId] : null;
  if (receipt2) {
    if (receipt2.fingerprint !== fingerprint) reject("\u8BF7\u6C42\u6807\u8BC6\u5DF2\u7528\u4E8E\u4E0D\u540C\u5185\u5BB9", 409);
    return s;
  }
  const before = weeklyStore(s);
  if (input.expectedVersion !== before.version) reject("\u4F8B\u4F1A\u6743\u91CD\u6216\u5386\u53F2\u5DF2\u53D8\u5316\uFF0C\u8BF7\u66F4\u65B0\u5C55\u793A\u540E\u91CD\u8BD5", 409);
  const state = structuredClone(s), store = structuredClone(before);
  let objectId = "", after;
  if (input.action === "weights") {
    const project = buildWeeklyMeetingSnapshot(s, at).projects.find((p) => p.id === input.projectId);
    if (!project) return reject("\u5F53\u524D\u5DE5\u4F5C\u533A\u6CA1\u6709\u53EF\u914D\u7F6E\u7684\u9879\u76EE", 404);
    if (input.scopeKey !== weeklyScopeKey(project)) reject("\u9879\u76EE\u6216\u4EA4\u4ED8\u8303\u56F4\u5DF2\u53D8\u5316\uFF0C\u8BF7\u66F4\u65B0\u5C55\u793A\u540E\u6838\u5BF9", 409);
    const profile = { stages: structuredClone(input.stages || []), outputs: structuredClone(input.outputs || []), scopeKey: input.scopeKey, confirmedAt: at };
    const errors2 = profileShapeErrors(profile);
    if (errors2.length) reject(errors2[0]);
    if (!same2(profile.outputs.map((d) => d.id).sort(), project.deliverables.map((d) => d.id).sort())) reject("\u6743\u91CD\u5FC5\u987B\u5B8C\u6574\u8986\u76D6\u5F53\u524D\u53EF\u5C55\u793A\u4EA4\u4ED8\u7269\uFF0C\u4E0D\u80FD\u5173\u8054\u5176\u4ED6\u9879\u76EE");
    store.profiles[project.id] = profile;
    objectId = project.id;
    after = profile;
  } else if (input.action === "capture") {
    if (input.baseRevision !== s.revision) reject("\u53F0\u8D26\u5DF2\u6709\u65B0\u8D44\u6599\uFF0C\u8BF7\u5148\u66F4\u65B0\u5C55\u793A\u518D\u4FDD\u5B58\u672C\u6B21\u4F8B\u4F1A", 409);
    if (store.history.length >= 5e3) reject("\u4F8B\u4F1A\u5386\u53F2\u5DF2\u8FBE\u4FDD\u7559\u4E0A\u9650\uFF0C\u8BF7\u5148\u5F52\u6863\uFF0C\u539F\u8BB0\u5F55\u5747\u5DF2\u4FDD\u7559");
    const view = buildWeeklyReviewView(s, at);
    const row = { id: "weekly-" + input.requestId, createdAt: at, revision: s.revision, title: text7(input.title) || meetingDay(at) + " \u5468\u4F8B\u4F1A", points: view.snapshot.projects.map((p) => {
      const value = view.progress[p.id];
      return { projectId: p.id, percent: value.percent, profileKey: value.profileKey, scopeKey: value.scopeKey };
    }) };
    if (row.title.length > 120 || !validId(row.id)) reject("\u4F8B\u4F1A\u540D\u79F0\u6216\u8BF7\u6C42\u6807\u8BC6\u8FC7\u957F");
    store.history.push(row);
    objectId = row.id;
    after = { id: row.id, title: row.title, projects: row.points.length };
  } else reject("\u5468\u4F8B\u4F1A\u64CD\u4F5C\u65E0\u6548");
  store.version++;
  state.weeklyReview = store;
  state.revision++;
  state.audit.push({ id: "audit-" + input.requestId, time: at, operation: "weekly." + input.action, objectId, before: { version: before.version }, after, actor: "\u672C\u4EBA", revision: state.revision, sourceIds: [] });
  state.receipts[input.requestId] = { fingerprint, result: { weeklyVersion: store.version, objectId } };
  const errors = weeklyStateErrors(state);
  if (errors.length) reject(errors[0].message);
  return state;
}
function comparisonPoint(view, projectId, historyId = "") {
  const history = historyId ? view.history.find((h) => h.id === historyId) : view.history.filter((h) => meetingDay(h.createdAt) < meetingDay(view.snapshot.generatedAt)).at(-1);
  const previous = history?.points.find((p) => p.projectId === projectId), current = view.progress[projectId];
  if (!history || !previous) return { delta: null, reason: "\u6682\u65E0\u53EF\u6BD4\u4F8B\u4F1A", history };
  if (current.percent === null || previous.percent === null) return { delta: null, reason: "\u8FDB\u5EA6\u53E3\u5F84\u5F85\u6838\u5BF9", history };
  if (current.profileKey !== previous.profileKey || current.scopeKey !== previous.scopeKey) return { delta: null, reason: "\u6743\u91CD\u6216\u8303\u56F4\u5DF2\u53D8\u5316", history };
  return { delta: Math.round((current.percent - previous.percent) * 10) / 10, reason: "", history };
}
var daysBetween = (a, b) => (Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 864e5;
function projectTime(project, at) {
  const start = gateDate(project.plannedStart), end = gateDate(project.plannedEnd), today2 = meetingDay(at);
  if (!start || !end || end <= start) return { percent: null, start, end, reason: "\u9879\u76EE\u8D77\u6B62\u8BA1\u5212\u5F85\u8865\u5145" };
  return { percent: Math.max(0, Math.round(daysBetween(start, today2) / daysBetween(start, end) * 100)), start, end, reason: "" };
}
function forecastVariance(project) {
  const planned = project.nextGate?.date, forecast = project.nextGateForecast;
  return planned && forecast ? daysBetween(planned, forecast) : null;
}
function ownerAssignments(snapshot) {
  const map = /* @__PURE__ */ new Map();
  for (const project of snapshot.projects) for (const row of project.deliverables) {
    if (deliveryRecorded(row) || row.submissionStatus === "\u514D\u4EA4\u4ED8") continue;
    const existing = map.get(row.id);
    if (existing) {
      if (!existing.projectIds.includes(project.id)) existing.projectIds.push(project.id);
      continue;
    }
    const owners = Array.isArray(row.ownerRefs) && row.ownerRefs.length ? row.ownerRefs : [{ id: "unknown", title: "\u8D1F\u8D23\u4EBA\u5F85\u6838\u5BF9" }];
    map.set(row.id, { key: row.id, outputId: row.id, title: row.title, projectIds: [project.id], owners, date: gateDate(row.plannedEnd), savedFieldAt: row.savedFieldAt, usesSavedFields: !!(row.usesSavedOwner || row.usesSavedDate), status: row.acceptanceStatus === "\u672A\u901A\u8FC7" || row.submissionStatus === "\u9700\u8865\u5145" ? "\u9700\u4FEE\u6539" : row.submissionStatus === "\u5DF2\u63D0\u4EA4" || row.deliveryReview === "\u5DF2\u5BA1\u6838" ? "\u4EA4\u4ED8\u6807\u8BB0\u5F85\u6838\u5BF9" : "\u5F85\u63D0\u4EA4" });
  }
  return [...map.values()];
}
function ownerChart(snapshot) {
  const today2 = meetingDay(snapshot.generatedAt), assignments = ownerAssignments(snapshot);
  const ownerMap = /* @__PURE__ */ new Map();
  for (const item of assignments) for (const owner2 of item.owners) {
    const entry = ownerMap.get(owner2.id) || { ...owner2, items: [], weeks: [0, 0], overdue: 0, undated: 0, later: 0 };
    entry.items.push(item);
    if (!item.date) entry.undated++;
    else {
      const days = daysBetween(today2, item.date);
      if (days < 0) entry.overdue++;
      else if (days < 7) entry.weeks[0]++;
      else if (days < 14) entry.weeks[1]++;
      else entry.later++;
    }
    ownerMap.set(owner2.id, entry);
  }
  return { today: today2, assignments, owners: [...ownerMap.values()].sort((a, b) => Number(a.id === "unknown") - Number(b.id === "unknown") || b.weeks[0] + b.weeks[1] - a.weeks[0] - a.weeks[1] || a.title.localeCompare(b.title)), shared: assignments.some((a) => a.owners.length > 1 || a.projectIds.length > 1) };
}
function weeklyDelivery(snapshot) {
  const today2 = meetingDay(snapshot.generatedAt), weekday = (/* @__PURE__ */ new Date(today2 + "T00:00:00Z")).getUTCDay() || 7;
  const start = new Date(Date.parse(today2 + "T00:00:00Z") - (weekday - 1) * 864e5).toISOString().slice(0, 10);
  const end = new Date(Date.parse(start + "T00:00:00Z") + 6 * 864e5).toISOString().slice(0, 10);
  const all = unique2(snapshot.projects.flatMap((p) => p.deliverables));
  const items = all.filter((d) => gateDate(d.plannedEnd) && d.plannedEnd >= start && d.plannedEnd <= end);
  const states = [{ id: "accepted", label: "\u5DF2\u4EA4\u4ED8" }, { id: "review", label: "\u4EA4\u4ED8\u6807\u8BB0\u5F85\u6838\u5BF9" }, { id: "rework", label: "\u9700\u4FEE\u6539" }, { id: "pending", label: "\u5F85\u63D0\u4EA4" }, { id: "exempt", label: "\u514D\u4EA4\u4ED8" }];
  return { start, end, total: items.length, undated: all.filter((d) => !gateDate(d.plannedEnd)).length, states: states.map((state) => ({ ...state, items: items.filter((d) => (deliveryRecorded(d) ? "accepted" : d.submissionStatus === "\u514D\u4EA4\u4ED8" ? "exempt" : d.acceptanceStatus === "\u672A\u901A\u8FC7" || d.submissionStatus === "\u9700\u8865\u5145" ? "rework" : d.submissionStatus === "\u5DF2\u63D0\u4EA4" || d.deliveryReview === "\u5DF2\u5BA1\u6838" ? "review" : "pending") === state.id) })) };
}

// lib/material-intake.ts
var intakeTargetKinds = ["projects", "deliverables", "actions", "flowNodes", "cases"];
var intakeActive = (status2) => ["queued", "reading", "analysing"].includes(status2);
var intakeProgressField = (kind) => kind === "projects" ? "projectProgress" : kind === "deliverables" ? "deliverableProgress" : "progressNote";
function intakeCanonicalTarget(s, id2) {
  const action = s.actions.find((a) => a.id === id2 && !a.archived), outputs = action ? s.deliverables.filter((d) => !d.archived && (action.outputIds || []).includes(d.id) && d.projectIds.some((p) => action.projectIds.includes(p))) : [];
  return outputs.length === 1 ? outputs[0].id : id2;
}
function materialSourceContentKey(src) {
  return JSON.stringify([src.excerpt || "", src.author || "", src.occurredAt || "", (src.attachments || []).map((a) => [a.name, a.sha256]), src.caseChat?.rawHash || "", src.feedback?.contentVersion || 0, src.taskContext?.rawHash || "", (src.resultReview?.documents || []).map((doc) => [doc.documentKey, doc.revision, doc.sha256 || doc.content])]);
}
function materialSourceIdentityKey(s, src) {
  return JSON.stringify([materialSourceContentKey(src), src.feedback?.eventAt || "", src.feedback?.deleted || false, src.caseFile?.parentHash ? src.caseFile.parentHash + (src.readStatus ? ":" + src.readStatus : "") : "", src.meetingContext?.contentHash || "", [...src.projectIds].sort(), [...src.objectIds || []].sort(), [...src.caseIds || []].sort(), src.feedback?.targetId || "", src.feedback?.observationOnly || false, src.feedback?.targetId ? intakeCanonicalTarget(s, src.feedback.targetId) : "", src.taskContext?.association || null, src.meetingContext?.kind || "", src.meetingContext?.association?.projectIds || [], (src.caseIds || []).map((id2) => {
    const c = s.cases.find((c2) => c2.id === id2);
    return [id2, c?.archived || false, c?.status === "\u5DF2\u5173\u95ED", c?.chatBinding?.chatId || "", c?.chatBinding?.scope || "", c?.chatBinding?.accountId || ""];
  })]);
}
function intakeTargets(s, projectId = "") {
  return intakeTargetKinds.flatMap((kind) => s[kind].filter((row) => !row.archived && (kind !== "actions" || intakeCanonicalTarget(s, row.id) === row.id) && (!projectId || row.id === projectId || row.projectIds.includes(projectId))).map((row) => ({ id: row.id, kind, title: row.title, projectIds: kind === "projects" ? [row.id] : row.projectIds, version: row.version || 1, progress: row[intakeProgressField(kind)] || "", forecast: row.forecast || "", plannedEnd: row.plannedEnd || "", owner: row.owner || row.executor || "", nextAction: row.nextAction || row.followUp || "", status: row.status || "", nodeStatus: row.nodeStatus || "", acceptanceStatus: row.acceptanceStatus || "", submissionStatus: row.submissionStatus || "", reviewStatus: row.reviewStatus || row.deliveryReview || "" })));
}
var validDate = (v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
function groundedForecast(date4, quote, occurredDate) {
  if (!validDate(date4) || !quote) return false;
  const [y, m, d] = date4.split("-").map(Number);
  if (new RegExp(`${y}[-/.\u5E74]0?${m}[-/.\u6708]0?${d}(?:\u65E5|\u53F7)?(?!\\d)`).test(quote)) return true;
  if (!validDate(occurredDate)) return false;
  if (y === Number(occurredDate.slice(0, 4)) && new RegExp(`(?:^|[^\\d])0?${m}\u67080?${d}[\u65E5\u53F7]?(?!\\d)`).test(quote)) return true;
  const weekday = quote.match(/(下周|本周|这周|周|星期)([一二三四五六日天])/);
  if (weekday) {
    const origin = /* @__PURE__ */ new Date(occurredDate + "T12:00:00Z"), day = origin.getUTCDay() || 7, target = "\u4E00\u4E8C\u4E09\u56DB\u4E94\u516D\u65E5".indexOf(weekday[2] === "\u5929" ? "\u65E5" : weekday[2]) + 1;
    origin.setUTCDate(origin.getUTCDate() + target - day + (weekday[1] === "\u4E0B\u5468" ? 7 : 0));
    return origin.toISOString().slice(0, 10) === date4 && date4 >= occurredDate;
  }
  const relative = quote.includes("\u540E\u5929") ? 2 : quote.includes("\u660E\u5929") ? 1 : quote.includes("\u4ECA\u5929") ? 0 : null;
  if (relative !== null) {
    const origin = /* @__PURE__ */ new Date(occurredDate + "T12:00:00Z");
    origin.setUTCDate(origin.getUTCDate() + relative);
    return origin.toISOString().slice(0, 10) === date4;
  }
  return false;
}
var compact = (text15) => text15.replace(/[\s（）()·—_-]/g, "").toLowerCase();
function isPartialForecast(source, quote, title) {
  if (!quote) return false;
  const start = source.indexOf(quote);
  if (start < 0) return true;
  const dateToken = quote.match(/\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}|\d{1,2}月\d{1,2}|下周|本周|这周|星期|周[一二三四五六日天]|明天|后天/);
  const index = start + (dateToken?.index || 0);
  const left = source.slice(0, index).split(/[，。；\n]/).at(-1) || "", right = source.slice(index).split(/[，。；\n]/)[0], clause = left + right;
  return ["\u81EA\u6D4B", "\u521D\u7A3F", "\u521D\u6B65\u9A8C\u8BC1", "\u5185\u90E8\u9A8C\u8BC1", "\u8BD5\u8FD0\u884C"].some((step) => clause.includes(step) && !title.includes(step));
}
function fail(message) {
  throw Object.assign(new Error(message), { status: 422 });
}
var bounded = (v, n) => typeof v === "string" && v.length <= n;
function applyIntakeAnalysis(input, batchId, result, basis, at) {
  const s = structuredClone(input), batch = s.sources.find((src) => src.id === batchId), job = batch?.intakeBatch;
  if (!batch || !job || job.status !== "analysing") fail("\u672C\u6279\u8D44\u6599\u5DF2\u505C\u6B62\u6216\u53D8\u5316");
  const docs = job.documents.map((id2) => s.sources.find((src) => src.id === id2 && !src.archived)).filter(Boolean);
  if (!bounded(result?.summary, 600) || !Array.isArray(result.documents) || result.documents.length !== docs.length || new Set(result.documents.map((d) => d.sourceId)).size !== docs.length || !Array.isArray(result.signals) || result.signals.length > 12) fail("AI\u6574\u7406\u7ED3\u679C\u672A\u901A\u8FC7\u8303\u56F4\u6821\u9A8C");
  const docMap = new Map(docs.map((src) => [src.id, src])), targets = intakeTargets(s, job.projectId), targetMap = new Map(targets.map((t) => [t.id, t]));
  const grounded = (source, quote) => typeof quote === "string" && quote.trim().length >= 2 && (job.analysisEvidence?.find((proof) => proof.sourceId === source.id)?.text ?? source.excerpt ?? "").includes(quote);
  for (const d of result.documents) {
    const src = docMap.get(d.sourceId);
    if (!src || !["progress", "report", "template", "rule", "unknown"].includes(d.nature) || !bounded(d.summary, 500) || !Array.isArray(d.updates) || d.updates.length > 8) fail("AI\u8D44\u6599\u5206\u7C7B\u6216\u5BF9\u8C61\u8303\u56F4\u65E0\u6548");
    for (const u of d.updates) if (!targetMap.has(u.targetId) || !bounded(u.progress, 600) || !bounded(u.progressQuote, 600) || !bounded(u.matchQuote, 400) || !bounded(u.forecastQuote, 300) || !bounded(u.reason, 500) || typeof u.clearResponse !== "boolean" || typeof u.conflict !== "boolean" || u.progress && !grounded(src, u.progressQuote) || u.matchQuote && !grounded(src, u.matchQuote) || u.forecast && !grounded(src, u.forecastQuote) || u.forecast && !validDate(u.forecast)) fail("AI\u66F4\u65B0\u7F3A\u5C11\u6709\u6548\u539F\u6587\u6216\u5BF9\u8C61\u4F9D\u636E");
  }
  for (const signal of result.signals) {
    const src = docMap.get(signal.sourceId);
    if (!src || signal.targetId && !targetMap.has(signal.targetId) || !["followup", "risk", "clarify"].includes(signal.kind) || !["normal", "urgent"].includes(signal.urgency) || !bounded(signal.title, 150) || !bounded(signal.reason, 500) || !bounded(signal.question, 500) || !bounded(signal.quote, 600) || !bounded(signal.imageLabel, 200) || !grounded(src, signal.quote) && !job.analysisCoverage?.find((c) => c.sourceId === src.id)?.images?.some((im) => im.label === signal.imageLabel)) fail("AI\u8DDF\u8FDB\u5EFA\u8BAE\u7F3A\u5C11\u53EF\u6838\u5BF9\u7684\u6587\u5B57\u6216\u56FE\u50CF\u4F9D\u636E");
  }
  for (const signal of result.signals) if (signal.viewerAction !== void 0) {
    const viewer = docMap.get(signal.sourceId)?.intakeDocument.viewer, names = [viewer?.id, viewer?.name, viewer?.name?.replace(/^AR\d+\s*/i, "")].filter(Boolean);
    if (typeof signal.viewerAction !== "boolean" || signal.viewerAction && !names.some((name) => signal.quote.includes(name))) fail("\u8BF7\u6C42\u672C\u4EBA\u5904\u7406\u7684\u5EFA\u8BAE\u7F3A\u5C11\u660E\u786E\u5BF9\u8C61\u548C\u539F\u6587\u4F9D\u636E");
  }
  for (const doc of result.documents) if (docMap.get(doc.sourceId)?.intakeDocument.knownCarrier === "template") doc.nature = "template";
  const updates = [], pending3 = [], evidenceRefresh = [], used = /* @__PURE__ */ new Set();
  for (const d of result.documents) {
    const src = docMap.get(d.sourceId), referenceOnly = job.relatedDocumentIds?.includes(src.id);
    if (!referenceOnly) {
      src.intakeDocument.nature = d.nature;
      src.intakeDocument.summary = d.summary;
      src.processingStatus = "\u5DF2\u6574\u7406";
      src.version++;
    }
    for (const u of d.updates) {
      const target = targetMap.get(u.targetId), row = s[target.kind].find((r) => r.id === target.id), prior = basis.find((t) => t.id === target.id), reasons = [];
      if (s.sources.some((other) => other.id !== batchId && other.intakeBatch && !other.intakeBatch.revertedAt && other.intakeBatch.autoUpdates?.some((old) => old.targetId === target.id && (old.sourceId === src.id || old.supportingSources?.some((ref) => ref.sourceId === src.id))))) continue;
      const sameTitle = targets.filter((t) => compact(t.title) === compact(target.title));
      const explicit = job.targetId === target.id || src.intakeDocument.targetHints?.includes(target.id) || sameTitle.length === 1 && u.matchQuote && compact(u.matchQuote).includes(compact(target.title));
      const group = result.documents.flatMap((doc) => doc.updates.filter((v) => v.targetId === target.id).map((update) => ({ doc, update })));
      const consistent = group.every(({ doc, update }) => !update.conflict && update.progress === u.progress && update.forecast === u.forecast && ["progress", "report"].includes(doc.nature) && docMap.get(doc.sourceId)?.intakeDocument.complete !== false && job.analysisCoverage?.find((c) => c.sourceId === doc.sourceId)?.complete !== false && (job.targetId === target.id || docMap.get(doc.sourceId)?.intakeDocument.targetHints?.includes(target.id) || sameTitle.length === 1 && update.matchQuote && compact(update.matchQuote).includes(compact(target.title))));
      if (!explicit) reasons.push("\u5F52\u5C5E\u5C1A\u672A\u8FBE\u5230\u552F\u4E00\u660E\u786E\u5339\u914D");
      if (referenceOnly || src.intakeDocument.knownCarrier === "context") reasons.push("\u5DF2\u5B58\u80CC\u666F\u8D44\u6599\u4EC5\u4F5C\u53C2\u8003\uFF0C\u4E0D\u4F5C\u4E3A\u672C\u6B21\u65B0\u53CD\u9988\u91CD\u590D\u66F4\u65B0");
      if (!["progress", "report"].includes(d.nature)) reasons.push("\u6A21\u677F\u3001\u5236\u5EA6\u6216\u672A\u5206\u7C7B\u8D44\u6599\u4E0D\u80FD\u66F4\u65B0\u6267\u884C\u8FDB\u5C55");
      if (src.intakeDocument.timeUncertain) reasons.push("\u6765\u6E90\u53D1\u751F\u65F6\u95F4\u5C1A\u672A\u660E\u786E\uFF0C\u5148\u4FDD\u7559\u6458\u8981\u4F9B\u6838\u5BF9");
      if (src.intakeDocument.complete === false) reasons.push("\u672C\u4EFD\u8D44\u6599\u5B58\u5728\u672A\u8BFB\u53D6\u8303\u56F4");
      if (job.analysisCoverage?.find((c) => c.sourceId === src.id)?.complete === false) reasons.push("\u672C\u6B21AI\u8BFB\u53D6\u8303\u56F4\u4E0D\u5B8C\u6574");
      if (!prior || target.version !== prior.version) reasons.push("\u5206\u6790\u671F\u95F4\u8BB0\u5F55\u5DF2\u6709\u53D8\u5316");
      if (u.conflict) reasons.push(u.reason || "\u8D44\u6599\u4E0E\u5DF2\u6709\u8BB0\u5F55\u5B58\u5728\u51B2\u7A81");
      if (["\u5DF2\u9A8C\u6536", "\u901A\u8FC7"].includes(row.acceptanceStatus) || ["\u5DF2\u5173\u95ED", "\u5DF2\u7ED3\u675F"].includes(row.status)) reasons.push("\u5BF9\u8C61\u5DF2\u6709\u6B63\u5F0F\u5B8C\u6210\u7ED3\u8BBA\uFF0C\u987B\u5148\u6838\u5BF9\u65B0\u589E\u53CD\u9988");
      if (src.occurredAt && row.intakeFeedback?.occurredAt && Date.parse(src.occurredAt) < Date.parse(row.intakeFeedback.occurredAt)) reasons.push("\u8FD9\u4EFD\u53CD\u9988\u65E9\u4E8E\u5DF2\u4FDD\u5B58\u7684\u53CD\u9988\u65F6\u95F4");
      if ((src.intakeDocument.occurredDate || job.occurredDate) && row.intakeFeedback?.occurredDate && (src.intakeDocument.occurredDate || job.occurredDate) < row.intakeFeedback.occurredDate) reasons.push("\u8FD9\u4EFD\u53CD\u9988\u65E9\u4E8E\u5DF2\u4FDD\u5B58\u7684\u53CD\u9988");
      if (group.length > 1 && !consistent) reasons.push("\u540C\u6279\u591A\u4EFD\u8D44\u6599\u5BF9\u540C\u4E00\u4E8B\u9879\u7684\u62DF\u66F4\u65B0\u4E0D\u4E00\u81F4\uFF0C\u9700\u8981\u5408\u5E76\u6838\u5BF9");
      const after = {}, before = {}, field = intakeProgressField(target.kind);
      if (u.progress && row[field] !== u.progress) after[field] = u.progress;
      const partialForecast = !!u.forecast && isPartialForecast(src.excerpt, u.forecastQuote, target.title), forecastOk = !u.forecast || groundedForecast(u.forecast, u.forecastQuote, src.intakeDocument.occurredDate || job.occurredDate || "") && !partialForecast;
      if (u.forecast && !forecastOk) pending3.push({ sourceId: src.id, targetId: target.id, title: target.title, reason: partialForecast ? "\u539F\u6587\u9884\u6D4B\u9488\u5BF9\u4E2D\u95F4\u6B65\u9AA4\uFF0C\u4E0D\u80FD\u5F53\u4F5C\u6574\u9879\u5DE5\u4F5C\u5B8C\u6210\u65E5\u671F\uFF1B\u5DF2\u4FDD\u7559\u539F\u8BDD\u4F9B\u6838\u5BF9" : "\u9884\u8BA1\u65E5\u671F\u7F3A\u5C11\u53EF\u9760\u7684\u65E5\u671F\u539F\u6587\u6216\u53D1\u751F\u65E5\u671F", proposedForecast: u.forecast, quote: u.forecastQuote });
      if (u.forecast && forecastOk && row.forecast !== u.forecast) after.forecast = u.forecast;
      if (reasons.length) {
        pending3.push({ sourceId: src.id, targetId: target.id, title: target.title, reason: reasons.join("\uFF1B"), proposed: after, quote: u.progressQuote || u.forecastQuote });
        continue;
      }
      src.projectIds = [.../* @__PURE__ */ new Set([...src.projectIds, ...target.projectIds])];
      src.objectIds = [.../* @__PURE__ */ new Set([...src.objectIds || [], target.id])];
      if (used.has(target.id)) {
        row.sourceIds = [.../* @__PURE__ */ new Set([...row.sourceIds, src.id])];
        const applied = updates.find((v) => v.targetId === target.id);
        if (applied) applied.supportingSources = [...applied.supportingSources || [], { sourceId: src.id, quote: u.progressQuote || u.forecastQuote }];
        continue;
      }
      used.add(target.id);
      for (const key2 of Object.keys(after)) before[key2] = row[key2] ?? null;
      if (Object.keys(after).length) {
        Object.assign(row, after);
        row.version++;
        row.updatedAt = at;
        row.sourceIds = [.../* @__PURE__ */ new Set([...row.sourceIds || [], src.id])];
        row.intakeFeedback = { batchId, sourceId: src.id, quote: u.progressQuote || u.forecastQuote, at, occurredAt: src.occurredAt || "", occurredDate: src.intakeDocument.occurredDate || job.occurredDate || "", state: "\u6765\u6E90\u53CD\u9988\uFF08\u81EA\u52A8\u6574\u7406\uFF09" };
        updates.push({ targetId: row.id, kind: target.kind, title: row.title, sourceId: src.id, before, after, quote: u.progressQuote || u.forecastQuote, version: row.version });
        s.audit.push({ id: "intake-update-" + stableHash(batchId + row.id + job.attempt), time: at, operation: "intake.feedback", kind: target.kind, objectId: row.id, actor: "AI\u6574\u7406\uFF08\u5DF2\u786E\u8BA4\u81EA\u52A8\u66F4\u65B0\u8303\u56F4\uFF09", before, after: { ...after, sourceId: src.id, quote: u.progressQuote || u.forecastQuote }, revision: s.revision + 1 });
      } else if (!row.sourceIds?.includes(src.id)) {
        const beforeSources = [...row.sourceIds || []];
        row.sourceIds = [.../* @__PURE__ */ new Set([...beforeSources, src.id])];
        row.intakeFeedback = { batchId, sourceId: src.id, quote: u.progressQuote || u.forecastQuote, at, occurredAt: src.occurredAt || "", occurredDate: src.intakeDocument.occurredDate || job.occurredDate || "", state: "\u6765\u6E90\u53CD\u9988\uFF08\u81EA\u52A8\u6574\u7406\uFF09" };
        row.version++;
        row.updatedAt = at;
        evidenceRefresh.push({ targetId: row.id, sourceId: src.id, title: row.title });
        s.audit.push({ id: "intake-evidence-" + stableHash(batchId + row.id + job.attempt), time: at, operation: "intake.evidence", kind: target.kind, objectId: row.id, actor: "\u8D44\u6599\u6574\u7406", before: { sourceIds: beforeSources }, after: { sourceIds: row.sourceIds, quote: u.progressQuote || u.forecastQuote }, revision: s.revision + 1 });
      }
    }
  }
  batch.projectIds = [.../* @__PURE__ */ new Set([...batch.projectIds, ...docs.filter((src) => !job.relatedDocumentIds?.includes(src.id)).flatMap((src) => src.projectIds)])];
  job.summary = result.summary;
  job.signals = result.signals.filter((signal) => docMap.get(signal.sourceId)?.intakeDocument.knownCarrier !== "template" && !(docMap.get(signal.sourceId)?.intakeDocument.observationOnly && signal.kind === "followup" && !signal.viewerAction)).map((signal, i) => ({ ...signal, id: batchId + "-signal-" + i, status: "\u5F85\u6838\u5BF9" }));
  job.pending = pending3;
  job.autoUpdates = updates;
  job.evidenceRefresh = evidenceRefresh;
  job.finishedAt = at;
  job.status = job.items.some((item) => ["failed", "partial"].includes(item.status)) || job.analysisCoverage?.some((c) => !c.complete) ? "partial" : "ready";
  batch.version++;
  batch.excerpt = result.summary;
  s.revision++;
  return s;
}

// lib/case-evidence.ts
function chatFiles(raw) {
  const files = [];
  const add = (key2, name) => {
    if (typeof key2 === "string" && /^file_[\w-]{1,200}$/.test(key2) && typeof name === "string" && name.length > 0 && name.length <= 240 && !files.some((f) => f.key === key2)) files.push({ key: key2, name, readable: /\.(html?|md|txt|csv|json|log)$/i.test(name) });
  };
  if (raw?.deleted) return files;
  let value = raw?.body?.content ?? raw?.content;
  if (typeof value === "string") {
    try {
      const data = JSON.parse(value);
      add(data.file_key, data.file_name);
      value = data;
    } catch {
      for (const match of value.matchAll(/<file\b([^>]{0,2000})\/?\s*>/gi)) {
        const attrs = Object.fromEntries([...match[1].matchAll(/\b(key|name)="([^"]*)"/g)].map((m) => [m[1], m[2].replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&")]));
        add(attrs.key, attrs.name);
      }
    }
  }
  if (value && typeof value === "object") add(value.file_key, value.file_name);
  return files;
}
function caseEvidenceAvailable(s, source, seen = []) {
  if (source.inputEnvelope?.effectWithdrawn) return false;
  if (source.archived || source.caseChat?.raw.deleted || source.feedback?.deleted || source.meetingContext?.raw.status === "cancelled") return false;
  if (seen.includes(source.id) || seen.length > 12) return false;
  if (source.riskEvidence) return !source.riskEvidence.historical && Array.isArray(source.riskEvidence.bases) && source.riskEvidence.bases.every((ref) => {
    const parent = s.sources.find((s2) => s2.id === ref.sourceId);
    return !!parent && caseEvidenceAvailable(s, parent, [...seen, source.id]) && materialSourceIdentityKey(s, parent) === ref.basis;
  });
  if (source.intakeDocument?.originalSourceId) {
    const parent = s.sources.find((src) => src.id === source.intakeDocument.originalSourceId);
    return !!parent && caseEvidenceAvailable(s, parent, [...seen, source.id]) && (!source.intakeDocument.originalIdentityKey || materialSourceIdentityKey(s, parent) === source.intakeDocument.originalIdentityKey) && (source.intakeDocument.originalContentKey ? materialSourceContentKey(parent) === source.intakeDocument.originalContentKey : parent.version === source.intakeDocument.originalSourceVersion);
  }
  if (source.caseFile) {
    const parent = s.sources.find((p) => p.id === source.caseFile.parentSourceId && !p.archived);
    return !!parent && !parent.caseChat?.raw.deleted && parent.caseChat?.rawHash === source.caseFile.parentHash && chatFiles(parent.caseChat.raw).some((f) => f.key === source.caseFile.fileKey);
  }
  return true;
}
var approvalStatusLabel = (status2) => ({ PENDING: "\u5BA1\u6279\u4E2D", APPROVED: "\u5DF2\u901A\u8FC7", REJECTED: "\u5DF2\u9000\u56DE", CANCELED: "\u5DF2\u64A4\u9500", DELETED: "\u5DF2\u5220\u9664" })[status2] || "\u72B6\u6001\u5F85\u6838\u5BF9";

// lib/cases.ts
var caseRoles = ["\u5173\u6CE8", "\u534F\u52A9\u8DDF\u8E2A", "\u7275\u5934\u8D1F\u8D23"];
var caseStatuses = ["\u5F85\u660E\u786E", "\u5904\u7406\u4E2D", "\u5F85\u6838\u9A8C", "\u5DF2\u5173\u95ED"];
var caseDateKinds = ["\u53CD\u9988\u65F6\u95F4", "\u671F\u671B\u4EA4\u4ED8", "\u627F\u8BFA\u5B8C\u6210"];
var caseProtectedFields = ["myRole", "roleHistory", "status", "reportApproval", "verification", "checkpointHistory", "closure", "closureHistory", "chatBinding", "chatBindingHistory", "chatRead", "chatPolling", "caseAnalysis"];
function fail2(message, status2 = 422) {
  throw Object.assign(new Error(message), { status: status2 });
}
var text8 = (v, max = 2e3) => typeof v === "string" && v.trim().length <= max ? v.trim() : fail2("\u5185\u5BB9\u683C\u5F0F\u65E0\u6548\u6216\u8FC7\u957F");
var ids4 = (v) => Array.isArray(v) && v.every((x) => typeof x === "string") ? [...new Set(v)] : fail2("\u5173\u8054\u8BB0\u5F55\u683C\u5F0F\u65E0\u6548");
var date2 = (v) => {
  const value = text8(v || "", 10);
  if (value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value)) fail2("\u8BF7\u586B\u5199\u6709\u6548\u65E5\u671F");
  return value;
};
var caseWorkDone = (row) => ["\u5DF2\u5B8C\u6210", "\u56E2\u961F\u53CD\u9988\u5B8C\u6210", "\u6267\u884C\u5B8C\u6210", "\u4E0D\u9002\u7528"].includes(row.executionStatus);
function caseWorks(s, id2) {
  return s.actions.filter((a) => !a.archived && a.caseId === id2);
}
function caseSources(s, id2) {
  const direct = (src) => src.caseIds?.includes(id2) || src.objectIds?.includes(id2) || s.cases.find((c) => c.id === id2)?.sourceIds.includes(src.id);
  return s.sources.filter((src) => !src.archived && (direct(src) || src.caseFile && s.sources.some((parent) => parent.id === src.caseFile.parentSourceId && !parent.archived && direct(parent))));
}
var sourceHash = (src) => stableHash(JSON.stringify([src.excerpt || "", src.url || "", src.author || "", src.attachments || [], ...src.approvalEvidence ? [src.approvalEvidence.rawHash] : []]));
function caseEvidenceChanged(s, row, checkpoint = "verification") {
  return (row[checkpoint]?.evidenceSnapshots || []).some((proof) => {
    const current = s.sources.find((src) => src.id === proof.id && !src.archived);
    return !current || !caseEvidenceAvailable(s, current) || sourceHash(current) !== proof.contentHash;
  });
}
function snapshots(s, ids8) {
  return ids8.map((id2) => {
    const src = s.sources.find((row) => row.id === id2);
    return { id: id2, title: src.title, version: src.version || 1, excerpt: src.excerpt || "", url: src.url || "", author: src.author || "", attachments: structuredClone(src.attachments || []), contentHash: sourceHash(src) };
  });
}
function caseStateErrors(s) {
  const errors = [];
  for (const row of s.cases || []) {
    const at = "cases." + row.id;
    if (!caseRoles.includes(row.myRole) || !caseStatuses.includes(row.status)) errors.push({ path: at, message: "\u4E13\u9879\u804C\u8D23\u6216\u72B6\u6001\u65E0\u6548" });
    if (!Array.isArray(row.roleHistory) || !Array.isArray(row.closureHistory)) errors.push({ path: at, message: "\u4E13\u9879\u7F3A\u5C11\u804C\u8D23\u4E0E\u5173\u95ED\u5386\u53F2" });
    if (row.status === "\u5DF2\u5173\u95ED") {
      if (row.verification?.status !== "\u901A\u8FC7" || !row.closure?.confirmedBy || !row.closure?.conclusion || !row.closure?.evidenceSourceIds?.length) errors.push({ path: at, message: "\u4E13\u9879\u5173\u95ED\u987B\u6709\u6574\u6539\u9A8C\u8BC1\u3001\u786E\u8BA4\u4EBA\u548C\u5173\u95ED\u4F9D\u636E" });
      if (caseWorks(s, row.id).some((work) => !caseWorkDone(work))) errors.push({ path: at, message: "\u4E13\u9879\u4ECD\u6709\u672A\u5B8C\u6210\u5DE5\u4F5C\uFF0C\u8BF7\u5148\u6838\u5BF9\u6216\u91CD\u65B0\u6253\u5F00\u4E13\u9879" });
      for (const id2 of [...row.verification?.evidenceSourceIds || [], ...row.closure?.evidenceSourceIds || []]) if (!s.sources.some((src) => src.id === id2 && !src.archived)) errors.push({ path: at, message: "\u4E13\u9879\u5173\u95ED\u4F9D\u636E\u5DF2\u4E0D\u53EF\u7528\uFF0C\u8BF7\u5148\u91CD\u65B0\u6253\u5F00\u4E13\u9879\u6838\u5BF9" });
    }
  }
  return errors;
}
function applyCaseCommand(input, body) {
  if (typeof body.requestId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,100}$/.test(body.requestId)) fail2("\u7F3A\u5C11\u6709\u6548\u8BF7\u6C42\u6807\u8BC6");
  const fingerprint = stableHash(JSON.stringify(body)), receipt2 = input.receipts[body.requestId];
  if (receipt2) {
    if (receipt2.fingerprint !== fingerprint) fail2("\u8BF7\u6C42\u6807\u8BC6\u5DF2\u7528\u4E8E\u5176\u4ED6\u64CD\u4F5C", 409);
    return { state: input, ...receipt2.result };
  }
  const s = structuredClone(input), at = (/* @__PURE__ */ new Date()).toISOString();
  let row = s.cases.find((c) => c.id === body.caseId && !c.archived), workId = "";
  if (body.action === "create") {
    const title = text8(body.title, 300);
    if (!title) fail2("\u8BF7\u586B\u5199\u4E13\u9879\u540D\u79F0");
    const id2 = "case-" + body.requestId;
    if (s.cases.some((c) => c.id === id2)) fail2("\u4E13\u9879\u5DF2\u5B58\u5728", 409);
    const projectIds2 = ids4(body.projectIds || []);
    if (projectIds2.some((id3) => !s.projects.some((p) => p.id === id3 && !p.archived))) fail2("\u5173\u8054\u9879\u76EE\u4E0D\u53EF\u7528");
    row = { id: id2, title, projectIds: projectIds2, sourceIds: [], version: 1, createdAt: at, updatedAt: at, caseType: text8(body.caseType || "\u4E34\u65F6\u4E13\u9879", 50), status: "\u5F85\u660E\u786E", myRole: "\u534F\u52A9\u8DDF\u8E2A", roleHistory: [], closureHistory: [], owner: "", reviewer: "", closureOwner: "", nextAction: "", situation: "", priorityReason: "", expectedAt: "", expectedTimeText: "", reportApproval: { status: "\u5F85\u6838\u5BF9" }, verification: { status: "\u5F85\u9A8C\u8BC1" }, closure: null };
    s.cases.push(row);
  } else {
    if (!row) fail2("\u4E13\u9879\u4E0D\u5B58\u5728\u6216\u5DF2\u5F52\u6863", 404);
    if (row.version !== body.expectedVersion) fail2("\u4E13\u9879\u5DF2\u66F4\u65B0\uFF0C\u8BF7\u8F7D\u5165\u6700\u65B0\u5185\u5BB9\u518D\u4FDD\u5B58", 409);
    if (row.status === "\u5DF2\u5173\u95ED" && !["reopen", "role"].includes(body.action)) fail2("\u4E13\u9879\u5DF2\u5173\u95ED\uFF1B\u8865\u5145\u6267\u884C\u5DE5\u4F5C\u524D\u8BF7\u91CD\u65B0\u6253\u5F00", 409);
    const evidence = () => {
      const values = ids4(body.evidenceSourceIds || []), available = caseSources(s, row.id).filter((src) => caseEvidenceAvailable(s, src));
      if (!values.length || values.some((id2) => !available.some((src) => src.id === id2))) fail2("\u8BF7\u9009\u62E9\u672C\u4E13\u9879\u53EF\u7528\u7684\u539F\u6587\u6216\u6210\u679C\u4F9D\u636E\uFF1B\u5DF2\u64A4\u56DE\u6D88\u606F\u548C\u6765\u6E90\u5DF2\u53D8\u5316\u7684\u6587\u4EF6\u4E0D\u80FD\u4F5C\u4E3A\u65B0\u7684\u6838\u5BF9\u4F9D\u636E");
      return values;
    };
    if (body.action === "update") {
      for (const key2 of ["title", "owner", "reviewer", "closureOwner", "nextAction", "situation", "priorityReason", "expectedTimeText"]) if (key2 in body) row[key2] = text8(body[key2], key2 === "title" ? 300 : 2e3);
      if (!row.title) fail2("\u4E13\u9879\u540D\u79F0\u4E0D\u80FD\u4E3A\u7A7A");
      if ("expectedAt" in body) row.expectedAt = date2(body.expectedAt);
      if ("projectIds" in body) {
        const values = ids4(body.projectIds);
        if (values.some((id2) => !s.projects.some((p) => p.id === id2 && !p.archived))) fail2("\u5173\u8054\u9879\u76EE\u4E0D\u53EF\u7528");
        row.projectIds = values;
      }
      if (["\u5F85\u660E\u786E", "\u5904\u7406\u4E2D", "\u5F85\u6838\u9A8C"].includes(body.status)) row.status = body.status;
    } else if (body.action === "role") {
      if (!caseRoles.includes(body.myRole)) fail2("\u8BF7\u9009\u62E9\u6709\u6548\u804C\u8D23");
      const reason = text8(body.reason);
      if (!reason) fail2("\u8BF7\u8BF4\u660E\u804C\u8D23\u8C03\u6574\u4F9D\u636E");
      if (row.myRole !== body.myRole) {
        row.roleHistory.push({ from: row.myRole, to: body.myRole, reason, at, recordedBy: "\u672C\u4EBA" });
        row.myRole = body.myRole;
      }
    } else if (body.action === "add-work") {
      const title = text8(body.title, 300);
      if (!title || !caseDateKinds.includes(body.dateKind)) fail2("\u8BF7\u586B\u5199\u5DE5\u4F5C\u540D\u79F0\u4E0E\u65E5\u671F\u7528\u9014");
      workId = "case-work-" + body.requestId;
      const sources = ids4(body.sourceIds || []);
      s.actions.push({ id: workId, title, projectIds: [...row.projectIds], sourceIds: sources, caseId: row.id, executor: text8(body.executor || "", 150), followUp: text8(body.followUp || ""), executionStatus: "\u5F85\u5F00\u59CB", acceptanceStatus: "\u5F85\u9A8C\u6536", status: "\u8FD1\u671F\u8DDF\u8FDB", dateKind: body.dateKind, dateText: text8(body.dateText || "", 300), checkAt: body.dateKind === "\u53CD\u9988\u65F6\u95F4" ? date2(body.dateValue) : "", expectedAt: body.dateKind === "\u671F\u671B\u4EA4\u4ED8" ? date2(body.dateValue) : "", dueAt: body.dateKind === "\u627F\u8BFA\u5B8C\u6210" ? date2(body.dateValue) : "", version: 1, createdAt: at, updatedAt: at });
    } else if (body.action === "checkpoint") {
      if (!["reportApproval", "verification"].includes(body.checkpoint)) fail2("\u6838\u5BF9\u7C7B\u578B\u65E0\u6548");
      const allowed = body.checkpoint === "reportApproval" ? ["\u5F85\u6838\u5BF9", "\u5BA1\u6279\u4E2D", "\u5DF2\u901A\u8FC7", "\u5DF2\u9000\u56DE"] : ["\u5F85\u9A8C\u8BC1", "\u901A\u8FC7", "\u672A\u901A\u8FC7"];
      if (!allowed.includes(body.status)) fail2("\u6838\u5BF9\u72B6\u6001\u65E0\u6548");
      const confirmedBy = text8(body.confirmedBy || "", 150), conclusion = text8(body.conclusion || "");
      if (!confirmedBy || !conclusion) fail2("\u8BF7\u8BB0\u5F55\u5B9E\u9645\u786E\u8BA4\u4EBA\u548C\u7ED3\u8BBA");
      const prior = row[body.checkpoint]?.at ? row[body.checkpoint] : row[body.checkpoint]?.previous;
      if (prior?.at) row.checkpointHistory = [...row.checkpointHistory || [], { checkpoint: body.checkpoint, value: prior }];
      const evidenceSourceIds = evidence();
      row[body.checkpoint] = { status: body.status, confirmedBy, conclusion, evidenceSourceIds, evidenceSnapshots: snapshots(s, evidenceSourceIds), at, recordedBy: "\u672C\u4EBA" };
    } else if (body.action === "close") {
      if (row.verification.status !== "\u901A\u8FC7") fail2("\u62A5\u544A\u5BA1\u6279\u901A\u8FC7\u4E0D\u80FD\u4EE3\u66FF\u6574\u6539\u9A8C\u8BC1\uFF1B\u8BF7\u5148\u8BB0\u5F55\u9A8C\u8BC1\u4F9D\u636E");
      if (!row.verification.evidenceSnapshots?.length || caseEvidenceChanged(s, row)) fail2("\u9A8C\u8BC1\u4F9D\u636E\u5DF2\u66F4\u65B0\u6216\u672A\u7559\u5B58\u7248\u672C\uFF0C\u8BF7\u91CD\u65B0\u6838\u5BF9\u9A8C\u8BC1\u7ED3\u8BBA");
      if (caseWorks(s, row.id).some((work) => !caseWorkDone(work))) fail2("\u8FD8\u6709\u5DE5\u4F5C\u672A\u53CD\u9988\u5B8C\u6210\uFF0C\u8BF7\u5148\u9010\u9879\u6838\u5BF9");
      const confirmedBy = text8(body.confirmedBy || "", 150), conclusion = text8(body.conclusion || "");
      if (!confirmedBy || !conclusion) fail2("\u8BF7\u586B\u5199\u5B9E\u9645\u5173\u95ED\u786E\u8BA4\u4EBA\u53CA\u4F9D\u636E\u8BF4\u660E");
      const evidenceSourceIds = evidence();
      row.closure = { confirmedBy, conclusion, evidenceSourceIds, evidenceSnapshots: snapshots(s, evidenceSourceIds), at, recordedBy: "\u672C\u4EBA" };
      row.status = "\u5DF2\u5173\u95ED";
      if (row.chatPolling) row.chatPolling = { ...row.chatPolling, enabled: false, nextReadAt: "" };
    } else if (body.action === "reopen") {
      if (row.status !== "\u5DF2\u5173\u95ED") fail2("\u5F53\u524D\u4E13\u9879\u5C1A\u672A\u5173\u95ED");
      const reason = text8(body.reason);
      if (!reason) fail2("\u8BF7\u8BF4\u660E\u91CD\u65B0\u6253\u5F00\u7684\u539F\u56E0");
      row.closureHistory.push({ ...row.closure, reopenedAt: at, reopenedReason: reason });
      if (row.verification?.at) row.checkpointHistory = [...row.checkpointHistory || [], { checkpoint: "verification", value: row.verification }];
      row.closure = null;
      row.status = "\u5904\u7406\u4E2D";
      row.verification = { status: "\u5F85\u9A8C\u8BC1" };
    } else fail2("\u4E0D\u652F\u6301\u7684\u4E13\u9879\u64CD\u4F5C");
    row.version = (row.version || 1) + 1;
    row.updatedAt = at;
  }
  s.revision++;
  s.audit.push({ id: "case-audit-" + body.requestId, time: at, operation: "case." + body.action, kind: "cases", objectId: row.id, actor: "\u672C\u4EBA", before: input.cases.find((c) => c.id === row.id) || null, after: structuredClone(row), revision: s.revision });
  const result = { caseId: row.id, workId };
  s.receipts[body.requestId] = { fingerprint, result };
  return { state: s, ...result };
}

// lib/seed.ts
function makeSeed() {
  const t = (/* @__PURE__ */ new Date()).toISOString();
  const projects = [
    rec("p1", "\u661F\u821F H2 \xB7 \u786C\u4EF6\u5347\u7EA7", ["p1"], ["s1", "s2"], {
      code: "HW-026",
      goal: "\u964D\u4F4E\u529F\u8017 20%\uFF0C\u5B8C\u6210 H2 \u5DE5\u7A0B\u6837\u673A\u4E0E\u5C0F\u6279\u8BD5\u4EA7\u9A8C\u8BC1\u3002",
      owner: "\u6797\u6668",
      phase: "\u5DE5\u7A0B\u9A8C\u8BC1",
      health: "\u98CE\u9669",
      healthReason: "\u6837\u673A\u9884\u6D4B\u665A\u4E8E\u627F\u8BFA 3 \u5929\uFF0C\u5171\u4EAB\u5C04\u9891\u53F0\u67B6\u5360\u7528\uFF1B\u9A8C\u6536\u9644\u4EF6\u7F3A\u5931\u3002",
      nextAction: "\u8BF7\u5468\u8861\u786E\u8BA4\u5C04\u9891\u53F0\u67B6\u91CA\u653E\u65F6\u95F4\uFF0C\u5E76\u63A8\u52A8\u6D4B\u8BD5\u8865\u9F50\u9A8C\u6536\u9644\u4EF6\u3002",
      privateNote: "\u4E2A\u4EBA\u5907\u6CE8\uFF1A\u5FC5\u8981\u65F6\u8003\u8651\u91CD\u65B0\u5206\u914D\u56E2\u961F\u8D44\u6E90\uFF0C\u5C1A\u672A\u8BA8\u8BBA\u3002",
      updatedAt: t,
      color: "#5578ed"
    }),
    rec("p2", "\u68F1\u955C \xB7 \u81EA\u52A8\u5316\u6D4B\u8BD5\u5E73\u53F0", ["p2"], ["s3", "s4"], {
      code: "SW-014",
      goal: "\u5EFA\u7ACB\u7EDF\u4E00\u56DE\u5F52\u5E73\u53F0\uFF0C\u8986\u76D6\u8F6F\u786C\u4EF6\u5173\u952E\u7528\u4F8B\u5E76\u81EA\u52A8\u8F93\u51FA\u62A5\u544A\u3002",
      owner: "\u9648\u96E8",
      phase: "\u7CFB\u7EDF\u8054\u8C03",
      health: "\u5173\u6CE8",
      healthReason: "\u63A5\u53E3\u8054\u8C03\u6B63\u5E38\uFF0C\u4F46\u786C\u4EF6\u6D4B\u8BD5\u4F9D\u8D56\u540C\u4E00\u53F0\u67B6\uFF0C\u53EF\u80FD\u5F71\u54CD\u8BD5\u8FD0\u884C\u3002",
      nextAction: "\u8DDF\u8FDB\u9648\u96E8\u7684\u63A5\u53E3\u786E\u8BA4\uFF0C\u534F\u8C03\u4E24\u4E2A\u9879\u76EE\u9519\u5CF0\u4F7F\u7528\u53F0\u67B6\u3002",
      privateNote: "\u4E2A\u4EBA\u5907\u6CE8\uFF1A\u5916\u5305\u65B9\u6848\u4EC5\u4E3A\u5907\u9009\u63A8\u6F14\uFF0C\u4E0D\u53EF\u53D1\u5E03\u3002",
      updatedAt: t,
      color: "#11a89c"
    }),
    rec("p3", "\u8FDC\u822A \xB7 \u4EA7\u54C1\u8BA4\u8BC1", ["p3"], ["s5", "s6"], {
      code: "QA-008",
      goal: "\u5B8C\u6210 EMC \u4E0E\u5B89\u5168\u8BA4\u8BC1\uFF0C\u53D6\u5F97\u53EF\u4EA4\u4ED8\u7684\u8BA4\u8BC1\u62A5\u544A\u3002",
      owner: "\u8BB8\u5B81",
      phase: "\u8BA4\u8BC1\u51C6\u5907",
      health: "\u6B63\u5E38",
      healthReason: "\u8D44\u6599\u6E05\u5355\u5DF2\u786E\u8BA4\uFF0C\u5B9E\u9A8C\u5BA4\u7A97\u53E3\u5DF2\u9884\u7559\uFF1B\u6301\u7EED\u8DDF\u8E2A\u65B0\u56FA\u4EF6\u57FA\u7EBF\u3002",
      nextAction: "\u5468\u56DB\u68C0\u67E5\u9001\u68C0\u6750\u6599\u548C\u56FA\u4EF6\u57FA\u7EBF\u7248\u672C\u3002",
      privateNote: "\u4E2A\u4EBA\u5907\u6CE8\uFF1A\u8BA4\u8BC1\u5907\u9009\u5B9E\u9A8C\u5BA4\u62A5\u4EF7\u5C1A\u672A\u8BC4\u4F30\u3002",
      updatedAt: t,
      color: "#9367d4"
    })
  ];
  const ms = [
    ["m1", "p1", "\u8BBE\u8BA1\u51BB\u7ED3", -12, -12, -12],
    ["m2", "p1", "H2 \u5DE5\u7A0B\u6837\u673A\u9A8C\u6536", 4, 7, null],
    ["m3", "p1", "\u5C0F\u6279\u8BD5\u4EA7\u8BC4\u5BA1", 22, 22, null],
    ["m4", "p2", "\u63A5\u53E3\u534F\u8BAE\u51BB\u7ED3", -5, -5, -5],
    ["m5", "p2", "\u81EA\u52A8\u5316\u56DE\u5F52\u8BD5\u8FD0\u884C", 8, 10, null],
    ["m6", "p2", "\u5E73\u53F0\u6B63\u5F0F\u79FB\u4EA4", 27, 27, null],
    ["m7", "p3", "\u8BA4\u8BC1\u8D44\u6599\u9F50\u5957", 3, 3, null],
    ["m8", "p3", "EMC \u9884\u68C0\u5B8C\u6210", 13, 13, null],
    ["m9", "p3", "\u53D6\u5F97\u8BA4\u8BC1\u62A5\u544A", 35, 35, null]
  ];
  const milestones = ms.map(
    ([id2, p, title, c, f, a]) => rec(id2, title, [p], [p === "p1" ? "s1" : p === "p2" ? "s3" : "s5"], {
      committed: shift(c),
      forecast: shift(f),
      actual: a === null ? "" : shift(a),
      acceptance: "\u8BC4\u5BA1\u901A\u8FC7\uFF0C\u4EA4\u4ED8\u7269\u5DF2\u5F52\u6863\uFF0C\u5E76\u7531\u8D1F\u8D23\u4EBA\u7B7E\u5B57\u786E\u8BA4\u3002",
      deliverableIds: [p === "p1" ? "s2" : p === "p2" ? "s4" : "s6"],
      owner: projects.find((x) => x.id === p).owner
    })
  );
  const sourceData = [
    [
      "s1",
      "\u786C\u4EF6\u5468\u4F1A\u7EAA\u8981",
      "\u4F1A\u8BAE\u8BB0\u5F55",
      "H2 \u5DE5\u7A0B\u6837\u673A\u9A8C\u6536\u627F\u8BFA\u65E5\u671F\u4E0D\u53D8\u3002\u5C04\u9891\u53F0\u67B6\u8D44\u6E90\u7D27\u5F20\uFF0C\u6700\u65B0\u9884\u6D4B\u6BD4\u627F\u8BFA\u665A 3 \u5929\u3002",
      ["p1"],
      "m2"
    ],
    [
      "s2",
      "\u6D4B\u8BD5\u62A5\u544A\u63D0\u4EA4\u53CD\u9988",
      "\u804A\u5929\u6458\u5F55",
      "\u5468\u8861\uFF1A\u6D4B\u8BD5\u62A5\u544A\u5DF2\u63D0\u4EA4\uFF0C\u9644\u4EF6\u4E2D\u7684\u7B7E\u5B57\u9875\u548C\u9A8C\u6536\u622A\u56FE\u8FD8\u6CA1\u8865\u9F50\u3002",
      ["p1"],
      "a1"
    ],
    [
      "s3",
      "\u5E73\u53F0\u8054\u8C03\u65E5\u62A5",
      "\u65E5\u62A5",
      "\u63A5\u53E3\u8054\u8C03\u901A\u8FC7\u3002\u81EA\u52A8\u5316\u56DE\u5F52\u9700\u4F7F\u7528\u5171\u4EAB\u5C04\u9891\u53F0\u67B6\uFF0C\u53EF\u80FD\u4E0E\u786C\u4EF6\u9A8C\u6536\u51B2\u7A81\u3002",
      ["p2"],
      "m5"
    ],
    [
      "s4",
      "\u63A5\u53E3\u534F\u8BAE V1.2",
      "\u4EA4\u4ED8\u7269",
      "\u63A5\u53E3\u534F\u8BAE\u5DF2\u51BB\u7ED3\uFF0C\u56DE\u5F52\u811A\u672C\u6E05\u5355\u5DF2\u8BC4\u5BA1\u3002",
      ["p2"],
      "m4"
    ],
    [
      "s5",
      "\u8BA4\u8BC1\u51C6\u5907\u4F1A",
      "\u4F1A\u8BAE\u8BB0\u5F55",
      "\u9001\u68C0\u8D44\u6599\u4ECD\u7F3A\u6700\u7EC8\u56FA\u4EF6\u57FA\u7EBF\u7B7E\u5B57\uFF1B\u5B9E\u9A8C\u5BA4\u7A97\u53E3\u5DF2\u9884\u7559\u3002",
      ["p3"],
      "m7"
    ],
    [
      "s6",
      "\u5B9E\u9A8C\u5BA4\u7A97\u53E3\u786E\u8BA4\u90AE\u4EF6",
      "\u90AE\u4EF6",
      "\u5B9E\u9A8C\u5BA4\u786E\u8BA4 EMC \u9884\u68C0\u7A97\u53E3\uFF0C\u9001\u68C0\u524D\u987B\u63D0\u4F9B\u5B8C\u6574\u8D44\u6599\u3002",
      ["p3"],
      "m8"
    ],
    [
      "s7",
      "\u5171\u4EAB\u53F0\u67B6\u6392\u671F\u8868",
      "\u6392\u671F\u8BB0\u5F55",
      "\u5171\u4EAB\u5C04\u9891\u53F0\u67B6\u53EA\u6709\u4E00\u5957\uFF1B\u786C\u4EF6\u9A8C\u6536\u4E0E\u6D4B\u8BD5\u5E73\u53F0\u8BD5\u8FD0\u884C\u6392\u671F\u91CD\u53E0\uFF0C\u9700\u51B3\u5B9A\u4F18\u5148\u7EA7\u3002",
      ["p1", "p2"],
      "dep1"
    ],
    [
      "s8",
      "\u9884\u7B97\u4E0E\u8D44\u6E90\u8BC4\u5BA1",
      "\u4F1A\u8BAE\u8BB0\u5F55",
      "\u501F\u7528\u5907\u7528\u53F0\u67B6\u9700\u8981\u8D1F\u8D23\u4EBA\u51B3\u5B9A\uFF1B\u8BA4\u8BC1\u56FA\u4EF6\u57FA\u7EBF\u5F85\u786C\u4EF6\u548C\u8F6F\u4EF6\u5171\u540C\u786E\u8BA4\u3002",
      ["p1", "p2", "p3"],
      "d1"
    ]
  ];
  const sources = sourceData.map(
    ([id2, title, type, excerpt, pids, obj]) => rec(id2, title, pids, [], {
      type,
      excerpt,
      url: "https://example.com/demo/" + id2,
      occurredAt: shift(-1) + "T09:30:00+08:00",
      collectedAt: t,
      confirmed: true,
      objectIds: [obj],
      demo: true
    })
  );
  const dependencies = [
    rec("dep1", "\u5171\u4EAB\u5C04\u9891\u53F0\u67B6 \xB7 \u4E24\u4E2A\u9879\u76EE\u4E89\u7528", ["p1", "p2"], ["s7"], {
      predecessorIds: ["m2"],
      affectedIds: ["m5"],
      type: "\u8D44\u6E90\u4F9D\u8D56",
      owner: "\u5468\u8861",
      neededBy: shift(2),
      status: "\u963B\u585E",
      situation: "\u786C\u4EF6\u9A8C\u6536\u5C1A\u672A\u91CA\u653E\u53F0\u67B6\uFF0C\u81EA\u52A8\u5316\u56DE\u5F52\u65E0\u6CD5\u6309\u539F\u8BA1\u5212\u5F00\u59CB\u3002"
    }),
    rec("dep2", "\u8BA4\u8BC1\u9001\u68C0\u4F9D\u8D56\u56FA\u4EF6\u57FA\u7EBF", ["p1", "p3"], ["s8"], {
      predecessorIds: ["m2"],
      affectedIds: ["m7", "m8"],
      type: "\u4EA4\u4ED8\u4F9D\u8D56",
      owner: "\u6797\u6668",
      neededBy: shift(3),
      status: "\u5173\u6CE8",
      situation: "\u5148\u786E\u8BA4\u53EF\u9001\u68C0\u7684\u56FA\u4EF6\u57FA\u7EBF\uFF0C\u907F\u514D\u91CD\u590D\u6D4B\u8BD5\u3002"
    })
  ];
  const risks = [
    rec("r1", "\u5171\u4EAB\u53F0\u67B6\u5360\u7528\u53EF\u80FD\u63A8\u8FDF\u4E24\u9879\u9A8C\u8BC1", ["p1", "p2"], ["s7"], {
      type: "\u98CE\u9669",
      impact: "\u9AD8",
      description: "\u786C\u4EF6\u9A8C\u6536\u4E0E\u5E73\u53F0\u56DE\u5F52\u6392\u671F\u91CD\u53E0\u3002",
      trigger: "\u53F0\u67B6\u672A\u5728\u6240\u9700\u65E5\u671F\u524D\u91CA\u653E",
      response: "\u534F\u8C03\u9519\u5CF0\u4F7F\u7528\uFF0C\u8BC4\u4F30\u501F\u7528\u5907\u7528\u53F0\u67B6\u3002",
      owner: "\u5468\u8861",
      checkAt: shift(-1),
      milestoneIds: ["m2", "m5"],
      confirmed: true,
      status: "\u5904\u7406\u4E2D"
    }),
    rec("r2", "\u62A5\u544A\u5DF2\u63D0\u4EA4\uFF0C\u9A8C\u6536\u8BC1\u636E\u4ECD\u4E0D\u9F50", ["p1"], ["s2"], {
      type: "\u95EE\u9898",
      impact: "\u9AD8",
      description: "\u56E2\u961F\u53CD\u9988\u5DF2\u5B8C\u6210\uFF0C\u4F46\u7B7E\u5B57\u9875\u53CA\u9A8C\u6536\u622A\u56FE\u7F3A\u5931\u3002",
      trigger: "\u5DF2\u6536\u5230\u62A5\u544A\uFF0C\u5C1A\u65E0\u5B8C\u6574\u9A8C\u6536\u9644\u4EF6",
      response: "\u8865\u9F50\u7B7E\u5B57\u9875\u548C\u9A8C\u6536\u622A\u56FE\u540E\u518D\u786E\u8BA4\u9A8C\u6536\u3002",
      owner: "\u5468\u8861",
      checkAt: shift(0),
      milestoneIds: ["m2"],
      confirmed: true,
      status: "\u5904\u7406\u4E2D"
    }),
    rec("r3", "\u56DE\u5F52\u7528\u4F8B\u8986\u76D6\u53EF\u80FD\u4E0D\u8DB3", ["p2"], ["s3"], {
      type: "\u98CE\u9669",
      impact: "\u4E2D",
      description: "\u6781\u7AEF\u6E29\u5EA6\u7528\u4F8B\u5C1A\u672A\u6267\u884C\u3002",
      trigger: "\u8BD5\u8FD0\u884C\u524D\u672A\u5B8C\u6210\u7528\u4F8B\u590D\u6838",
      response: "\u8865\u5145\u5F02\u5E38\u548C\u8FB9\u754C\u7528\u4F8B\u3002",
      owner: "\u9648\u96E8",
      checkAt: shift(2),
      milestoneIds: ["m5"],
      confirmed: true,
      status: "\u5F85\u5904\u7406"
    }),
    rec("r4", "\u9001\u68C0\u57FA\u7EBF\u7B7E\u5B57\u7F3A\u5931", ["p3"], ["s5"], {
      type: "\u95EE\u9898",
      impact: "\u9AD8",
      description: "\u8BA4\u8BC1\u8D44\u6599\u5305\u7F3A\u5C11\u56FA\u4EF6\u57FA\u7EBF\u7B7E\u5B57\u3002",
      trigger: "\u8D44\u6599\u68C0\u67E5\u5DF2\u53D1\u73B0\u7F3A\u9879",
      response: "\u843D\u5B9E\u7B7E\u5B57\u8D23\u4EFB\u4EBA\u3002",
      owner: "",
      checkAt: shift(-2),
      milestoneIds: ["m7"],
      confirmed: true,
      status: "\u5F85\u5904\u7406"
    }),
    rec("r5", "\u5907\u7528\u5668\u4EF6\u4EA4\u671F\u53EF\u80FD\u5EF6\u957F", ["p1"], [], {
      type: "\u98CE\u9669",
      impact: "\u4E2D",
      description: "\u6682\u65E0\u4F9B\u5E94\u5546\u6B63\u5F0F\u786E\u8BA4\uFF0C\u5F85\u6838\u5B9E\u3002",
      trigger: "\u4F9B\u5E94\u5546\u672A\u6309\u671F\u56DE\u51FD",
      response: "\u7D22\u53D6\u4E66\u9762\u4EA4\u671F\u3002",
      owner: "\u6797\u6668",
      checkAt: shift(3),
      milestoneIds: ["m3"],
      confirmed: false,
      status: "\u5F85\u786E\u8BA4"
    }),
    rec("r6", "\u6D4B\u8BD5\u73AF\u5883\u914D\u7F6E\u6F02\u79FB", ["p2"], ["s4"], {
      type: "\u95EE\u9898",
      impact: "\u4E2D",
      description: "\u4E24\u53F0\u6267\u884C\u8282\u70B9\u914D\u7F6E\u7248\u672C\u4E0D\u540C\u3002",
      trigger: "\u8054\u8C03\u53D1\u73B0\u7248\u672C\u5DEE\u5F02",
      response: "\u7EDF\u4E00\u955C\u50CF\u7248\u672C\u5E76\u590D\u6D4B\u3002",
      owner: "\u9648\u96E8",
      checkAt: shift(1),
      milestoneIds: ["m5"],
      confirmed: true,
      status: "\u5904\u7406\u4E2D"
    })
  ];
  const decisions = [
    rec("d1", "\u662F\u5426\u501F\u7528\u5907\u7528\u5C04\u9891\u53F0\u67B6\uFF1F", ["p1", "p2"], ["s7", "s8"], {
      options: "A. \u9519\u5CF0\u4F7F\u7528\u73B0\u6709\u53F0\u67B6\nB. \u501F\u7528\u5907\u7528\u53F0\u67B6\nC. \u8C03\u6574\u8BD5\u8FD0\u884C\u8303\u56F4",
      recommendation: "\u5EFA\u8BAE B\uFF0C\u9700\u786E\u8BA4\u501F\u7528\u6210\u672C\u4E0E\u6807\u5B9A\u72B6\u6001\u3002",
      owner: "\u8D75\u603B",
      deadline: shift(1),
      impact: "\u5EF6\u8FDF\u5C06\u540C\u65F6\u5F71\u54CD H2 \u6837\u673A\u9A8C\u6536\u548C\u5E73\u53F0\u8BD5\u8FD0\u884C\u3002",
      milestoneIds: ["m2", "m5"],
      status: "\u5F85\u51B3\u7B56",
      conclusion: "",
      history: []
    }),
    rec("d2", "\u9A8C\u6536\u662F\u5426\u63A5\u53D7\u5206\u6279\u8865\u9F50\u8BC1\u636E\uFF1F", ["p1"], ["s2"], {
      options: "A. \u8D44\u6599\u9F50\u5957\u540E\u9A8C\u6536\nB. \u5206\u9636\u6BB5\u9A8C\u6536\u5E76\u5217\u51FA\u4FDD\u7559\u9879",
      recommendation: "\u5EFA\u8BAE A\uFF0C\u5148\u8865\u9F50\u5FC5\u8981\u8BC1\u636E\u3002",
      owner: "\u6797\u6668",
      deadline: shift(0),
      impact: "\u53EF\u80FD\u5F71\u54CD\u6837\u673A\u9A8C\u6536\u7ED3\u8BBA\u4E0E\u8BD5\u4EA7\u6392\u671F\u3002",
      milestoneIds: ["m2", "m3"],
      status: "\u5F85\u51B3\u7B56",
      conclusion: "",
      history: []
    }),
    rec("d3", "\u8BA4\u8BC1\u91C7\u7528\u54EA\u4E2A\u56FA\u4EF6\u57FA\u7EBF\uFF1F", ["p1", "p3"], ["s8"], {
      options: "A. \u51BB\u7ED3\u5F53\u524D\u7A33\u5B9A\u7248\nB. \u7B49\u5F85\u65B0\u529F\u80FD\u5206\u652F",
      recommendation: "\u5EFA\u8BAE A\uFF0C\u51CF\u5C11\u91CD\u590D\u8BA4\u8BC1\u98CE\u9669\u3002",
      owner: "\u8BB8\u5B81",
      deadline: shift(2),
      impact: "\u5F71\u54CD\u9001\u68C0\u8D44\u6599\u4E0E EMC \u9884\u68C0\u65F6\u95F4\u3002",
      milestoneIds: ["m7", "m8"],
      status: "\u5F85\u51B3\u7B56",
      conclusion: "",
      history: []
    }),
    rec("d4", "\u5E73\u53F0\u79FB\u4EA4\u662F\u5426\u5305\u542B\u5386\u53F2\u6570\u636E\u8FC1\u79FB\uFF1F", ["p2"], ["s3"], {
      options: "A. \u672C\u671F\u4E00\u5E76\u8FC1\u79FB\nB. \u4F5C\u4E3A\u540E\u7EED\u9636\u6BB5",
      recommendation: "\u5EFA\u8BAE B\uFF0C\u4F18\u5148\u4FDD\u8BC1\u56DE\u5F52\u80FD\u529B\u3002",
      owner: "\u9648\u96E8",
      deadline: shift(9),
      impact: "\u5F71\u54CD\u79FB\u4EA4\u8303\u56F4\u548C\u4EBA\u529B\u5B89\u6392\u3002",
      milestoneIds: ["m6"],
      status: "\u5F85\u51B3\u7B56",
      conclusion: "",
      history: []
    })
  ];
  const names = [
    "\u8865\u9F50 H2 \u9A8C\u6536\u9644\u4EF6",
    "\u786E\u8BA4\u5171\u4EAB\u53F0\u67B6\u91CA\u653E\u65F6\u95F4",
    "\u590D\u6838\u6837\u673A\u529F\u8017\u6D4B\u8BD5\u7ED3\u679C",
    "\u8DDF\u8FDB\u5907\u7528\u5668\u4EF6\u4E66\u9762\u4EA4\u671F",
    "\u51C6\u5907\u5C0F\u6279\u8BD5\u4EA7\u8BC4\u5BA1",
    "\u786E\u8BA4\u63A5\u53E3\u8054\u8C03\u7ED3\u8BBA",
    "\u6392\u5B9A\u81EA\u52A8\u5316\u56DE\u5F52\u7A97\u53E3",
    "\u8865\u5145\u8FB9\u754C\u6D4B\u8BD5\u7528\u4F8B",
    "\u7EDF\u4E00\u6D4B\u8BD5\u8282\u70B9\u955C\u50CF",
    "\u51C6\u5907\u5E73\u53F0\u79FB\u4EA4\u6E05\u5355",
    "\u8865\u9F50\u9001\u68C0\u57FA\u7EBF\u7B7E\u5B57",
    "\u786E\u8BA4\u5B9E\u9A8C\u5BA4\u9884\u68C0\u7A97\u53E3",
    "\u590D\u6838\u8BA4\u8BC1\u8D44\u6599\u76EE\u5F55",
    "\u843D\u5B9E\u8BA4\u8BC1\u6837\u673A\u7269\u6D41",
    "\u5F52\u6863\u5DF2\u786E\u8BA4\u8BA4\u8BC1\u9700\u6C42"
  ];
  const actions = names.map((title, i) => {
    const p = i < 5 ? "p1" : i < 10 ? "p2" : "p3", executor = i < 5 ? "\u5468\u8861" : i < 10 ? "\u9648\u96E8" : "\u8BB8\u5B81";
    return rec(
      "a" + (i + 1),
      title,
      [p],
      [
        i === 0 ? "s2" : i === 1 ? "s7" : p === "p1" ? "s1" : p === "p2" ? "s3" : "s5"
      ],
      {
        executor,
        feishuIdentity: "",
        followUp: i === 0 ? "\u8BF7\u5468\u8861\u8865\u9F50\u7B7E\u5B57\u9875\u4E0E\u622A\u56FE\uFF0C\u6838\u5BF9\u540E\u518D\u786E\u8BA4\u9A8C\u6536\u3002" : `\u8DDF\u8FDB${executor}\uFF0C\u786E\u8BA4\u5F53\u524D\u7ED3\u679C\u4E0E\u4E0B\u4E00\u6B21\u53CD\u9988\u65F6\u95F4\u3002`,
        priority: i % 5 < 2 ? "P1" : "P2",
        dueAt: shift([0, -1, 0, 5, -2][i % 5]),
        checkAt: shift([0, -1, 0, 3, 7][i % 5]),
        lastContactAt: shift(-2),
        status: [
          "\u4ECA\u5929\u9700\u8981\u63A8\u52A8",
          "\u7B49\u5F85\u4ED6\u4EBA\u53CD\u9988",
          "\u9700\u8981\u5347\u7EA7\u534F\u8C03",
          "\u8FD1\u671F\u8DDF\u8FDB",
          "\u5DF2\u5B8C\u6210"
        ][i % 5],
        executionStatus: i === 0 ? "\u56E2\u961F\u53CD\u9988\u5B8C\u6210" : i % 5 === 4 ? "\u5DF2\u5B8C\u6210" : "\u8FDB\u884C\u4E2D",
        acceptanceStatus: i === 0 ? "\u8BC1\u636E\u4E0D\u8DB3" : "\u5F85\u9A8C\u6536",
        acceptance: "\u4EA4\u4ED8\u5B8C\u6574\u8D44\u6599\u6216\u7ED3\u679C\u94FE\u63A5\uFF0C\u5E76\u5B8C\u6210\u8D1F\u8D23\u4EBA\u6838\u9A8C\u3002",
        milestoneIds: [p === "p1" ? "m2" : p === "p2" ? "m5" : "m7"]
      }
    );
  });
  const judgments = projects.map(
    (p) => rec("j-" + p.id, p.healthReason, [p.id], p.sourceIds, {
      confirmed: true,
      author: "\u9879\u76EE\u7ECF\u7406",
      createdAt: t,
      health: p.health
    })
  );
  const s = {
    schemaVersion: 1,
    revision: 0,
    demo: true,
    seedDate: today(),
    projects,
    milestones,
    dependencies,
    risks,
    decisions,
    actions,
    sources,
    judgments,
    candidates: [],
    publications: [],
    audit: []
  };
  s.publications.push({
    id: "pub-demo",
    objectId: "a12",
    kind: "task",
    mode: "simulation",
    targetId: "SIM-TASK-a12",
    targetUrl: "/simulated-feishu/SIM-TASK-a12",
    content: taskDraft(s, "a12"),
    status: "success",
    attempts: [
      {
        time: shift(-1) + "T08:00:00Z",
        result: "failed",
        reason: "\u6A21\u62DF\uFF1A\u8FDE\u63A5\u8D85\u65F6\uFF0C\u76EE\u6807\u5C1A\u672A\u521B\u5EFA"
      },
      { time: shift(-1) + "T08:01:00Z", result: "success", reason: "" }
    ],
    createdAt: shift(-1) + "T08:00:00Z",
    sourceIds: ["s5"],
    feedbackIds: []
  });
  return s;
}

// lib/v2-types.ts
var v2Kinds = ["projects", "milestones", "dependencies", "risks", "decisions", "actions", "sources", "judgments", "people", "resources", "relations", "flowNodes", "deliverables", "externalLinks", "cases"];
var registryKinds = ["externalObjects", "remoteFieldValues", "mappingRules", "syncBaselines", "syncRuns", "syncReceipts", "dispatchRecords"];
var v2Labels = {
  projects: "\u9879\u76EE",
  milestones: "\u91CC\u7A0B\u7891",
  dependencies: "\u4F9D\u8D56",
  risks: "\u98CE\u9669 / \u95EE\u9898",
  decisions: "\u51B3\u7B56",
  actions: "\u884C\u52A8\u9879",
  sources: "\u4FE1\u606F\u6765\u6E90",
  judgments: "\u7BA1\u7406\u5224\u65AD",
  people: "\u4EBA\u5458",
  resources: "\u5171\u4EAB\u8D44\u6E90",
  relations: "\u5173\u7CFB",
  flowNodes: "\u6D41\u7A0B\u8282\u70B9",
  deliverables: "\u4EA4\u4ED8\u7269",
  externalLinks: "\u5916\u90E8\u5173\u8054",
  cases: "\u4E13\u9879\u4E8B\u9879"
};

// lib/work-item-progress.ts
var same3 = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
var fail3 = (message) => {
  throw Object.assign(new Error(message), { status: 422 });
};
var shanghaiDay = (at = Date.now()) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(at));
function validDate2(date4) {
  return typeof date4 === "string" && /^\d{4}-\d{2}-\d{2}$/.test(date4) && Number.isFinite(Date.parse(date4 + "T12:00:00Z")) && (/* @__PURE__ */ new Date(date4 + "T12:00:00Z")).toISOString().slice(0, 10) === date4;
}
function normalizeTime(value, origin, at) {
  if (!value || !["scheduled", "pending", "clear", "unchanged"].includes(value.state)) fail3("\u65F6\u95F4\u9009\u62E9\u65E0\u6548");
  if (value.state !== "scheduled") return { state: value.state, origin, quote: value.quote || "", at };
  if (!validDate2(value.date) || value.time && !/^([01]\d|2[0-3]):[0-5]\d$/.test(value.time)) fail3("\u8BF7\u4F7F\u7528\u6709\u6548\u65E5\u671F\u548C\u65F6\u523B");
  const zone = value.zone || "Asia/Shanghai", offset = zone === "Asia/Shanghai" ? "+08:00" : zone === "UTC" ? "Z" : zone;
  if (!/^(Z|[+-](?:0\d|1[0-4]):[0-5]\d)$/.test(offset)) fail3("\u65F6\u95F4\u9700\u8981\u660E\u786E\u7684\u65F6\u533A");
  return {
    state: "scheduled",
    date: value.date,
    time: value.time || "",
    zone,
    precision: value.time ? "minute" : "date",
    origin,
    quote: value.quote || "",
    at,
    ...value.time ? { effectiveAt: (/* @__PURE__ */ new Date(value.date + "T" + value.time + ":00" + offset)).toISOString() } : {}
  };
}
var comparable = (t) => [t.state, t.date || "", t.time || "", t.zone || "Asia/Shanghai"];
var candidateFingerprint = (input, field, values) => JSON.stringify([field, input.text, ...values]);
var selected = (selection, fingerprint) => selection?.fingerprint === fingerprint ? selection.choice : void 0;
var zoneOffset = (zone) => !zone || zone === "Asia/Shanghai" ? "+08:00" : zone === "UTC" ? "Z" : zone;
function arrangementBoundary(node, key2) {
  if (node.time || node.precision === "minute") return Date.parse(node.effectiveAt || node.date + "T" + node.time + ":00" + zoneOffset(node.zone));
  if (key2 === "check") return Date.parse(node.date + "T10:00:00" + zoneOffset(node.zone));
  const nextDay = new Date(Date.parse(node.date + "T00:00:00Z") + 864e5).toISOString().slice(0, 10);
  return Date.parse(nextDay + "T00:00:00" + zoneOffset(node.zone));
}
var hasTimeOverride = (node) => !!node && (node.state === "scheduled" || node.state === "pending" || node.state === "clear" || !!node.completedAt || !!node.needsReview);
function combineEntry(plan, input) {
  const changes = {}, conflicts = [];
  const grounded = (quote) => typeof quote === "string" && !!quote.trim() && input.text.includes(quote);
  if (!plan || !["record", "discuss", "mixed", "clarify", "other"].includes(plan.intent)) fail3("\u4E8B\u9879\u7406\u89E3\u683C\u5F0F\u65E0\u6548");
  if (!Number.isFinite(Date.parse(input.occurredAt))) fail3("\u8F93\u5165\u53D1\u751F\u65F6\u95F4\u65E0\u6548");
  if (plan.progress) {
    if (!grounded(plan.progressQuote) || plan.progress.length > 4e3) fail3("\u8FDB\u5C55\u7F3A\u5C11\u672C\u6B21\u8F93\u5165\u7684\u539F\u8BDD");
    changes.progress = { text: plan.progress, quote: plan.progressQuote, ...input.editProgressId ? { editId: input.editProgressId } : {} };
  }
  if (plan.waitingFor || plan.waitingResult) {
    if (!grounded(plan.waitingQuote) || !plan.waitingFor || !plan.waitingResult) conflicts.push({ field: "waiting", message: "\u8BF7\u660E\u786E\u7B49\u8C01\u6216\u54EA\u4E2A\u6765\u6E90\u3001\u7B49\u4EC0\u4E48\u7ED3\u679C\u3002" });
    else changes.waiting = { who: plan.waitingFor, result: plan.waitingResult, quote: plan.waitingQuote };
  }
  if (plan.checkCompleted) {
    if (!grounded(plan.checkQuote)) fail3("\u68C0\u67E5\u7ED3\u679C\u7F3A\u5C11\u672C\u6B21\u8F93\u5165\u4F9D\u636E");
    changes.checkCompleted = plan.checkQuote;
  }
  if (plan.riskDecision !== "none") {
    if (!["confirmed", "resolved", "dismissed"].includes(plan.riskDecision) || !grounded(plan.riskQuote)) fail3("\u98CE\u9669\u7ED3\u8BBA\u7F3A\u5C11\u672C\u6B21\u660E\u786E\u8868\u8FBE");
    changes.riskDecision = plan.riskDecision;
    changes.riskQuote = plan.riskQuote;
  }
  if (plan.followup !== "unchanged") {
    if (!["continue", "end", "cancel"].includes(plan.followup) || !grounded(plan.followupQuote)) fail3("\u8DDF\u8FDB\u7ED3\u675F\u6761\u4EF6\u9700\u6709\u672C\u6B21\u660E\u786E\u8868\u8FBE");
    changes.followup = plan.followup;
    changes.followupQuote = plan.followupQuote;
  }
  for (const key2 of ["check", "completion"]) {
    let text15, manual;
    if (plan[key2]?.state && plan[key2].state !== "unchanged") {
      if (!grounded(plan[key2].quote || "")) fail3("\u6587\u5B57\u65F6\u95F4\u7F3A\u5C11\u672C\u6B21\u8F93\u5165\u7684\u539F\u8BDD");
      text15 = normalizeTime(plan[key2], "user-text", input.occurredAt);
    }
    if (input.manual?.[key2] && input.manual[key2].state !== "unchanged") manual = normalizeTime(input.manual[key2], "manual", input.occurredAt);
    if (text15 && manual && !same3(comparable(text15), comparable(manual))) {
      const fingerprint = candidateFingerprint(input, key2, [comparable(text15), comparable(manual)]), choice = selected(input.resolution?.[key2], fingerprint);
      if (choice === "text" || choice === "manual") changes[key2] = choice === "text" ? text15 : manual;
      else conflicts.push({ field: key2, message: (key2 === "check" ? "\u68C0\u67E5" : "\u5B8C\u6210") + "\u65F6\u95F4\u6709\u4E24\u79CD\u660E\u786E\u9009\u62E9\uFF0C\u8BF7\u9009\u672C\u6B21\u91C7\u7528\u54EA\u4E00\u9879\u3002", text: text15, manual, fingerprint });
    } else if (text15 || manual) changes[key2] = manual || text15;
  }
  const future = ["check", "completion"].filter((key2) => {
    const t = changes[key2];
    return t?.state === "scheduled" && arrangementBoundary(t, key2) > Date.parse(input.occurredAt);
  });
  if (["end", "cancel"].includes(changes.followup || "") && future.length) {
    const fingerprint = candidateFingerprint(input, "followup", [changes.followup, changes.followupQuote, future.map((key2) => [key2, comparable(changes[key2])])]), choice = selected(input.resolution?.followup, fingerprint);
    if (choice === "continue") changes.followup = "continue";
    else if (choice === "end") for (const key2 of future) delete changes[key2];
    else conflicts.push({ field: "followup", message: "\u672C\u6B21\u540C\u65F6\u8981\u6C42\u7ED3\u675F\u5E76\u8BBE\u7F6E\u4E86\u672A\u6765\u5B89\u6392\uFF1A\u8FD8\u6709\u540E\u7EED\u8981\u8DDF\u8FDB\u5417\uFF1F", fingerprint });
  }
  if (plan.intent === "clarify" || plan.clarification) conflicts.push({ field: "clarification", message: plan.clarification || "\u8BF7\u8865\u5145\u4F1A\u5F71\u54CD\u672C\u6B21\u7ED3\u679C\u7684\u5177\u4F53\u5B89\u6392\u3002" });
  if (plan.intent === "discuss" && Object.keys(changes).some((k) => !["check", "completion"].includes(k))) fail3("\u8BA8\u8BBA\u4E0D\u80FD\u81EA\u52A8\u5199\u6210\u4E1A\u52A1\u8BB0\u5F55");
  if (plan.intent === "other" && Object.keys(changes).length) fail3("\u672C\u6B21\u8BF7\u6C42\u4E0D\u5C5E\u4E8E\u660E\u786E\u7684\u672C\u5730\u8BB0\u5F55");
  return { changes, conflicts, stay: plan.intent === "discuss" || plan.intent === "mixed" || plan.intent === "clarify" || plan.intent === "other" };
}
function itemTiming(s, source, at = Date.now()) {
  const item = source.workItem, p1 = item.p1 || {}, target = item.businessTarget && s[item.businessTarget.kind];
  const business = Array.isArray(target) ? target.find((r) => r.id === item.businessTarget.id) : void 0;
  const checkOverride = hasTimeOverride(p1.check);
  let check = checkOverride ? p1.check : { state: "unchanged" };
  if (!checkOverride && item.handling?.nextCheckAt) {
    const old = item.handling.nextCheckAt;
    check = Number.isFinite(Date.parse(old)) ? { state: "scheduled", effectiveAt: old, date: shanghaiDay(old), time: new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(old)), zone: "Asia/Shanghai", precision: "minute", origin: "legacy", quote: old } : { state: "unchanged", quote: String(old), needsReview: true };
  }
  const requirements = [];
  for (const [field, label2] of [["plannedEnd", "\u6B63\u5F0F\u8BA1\u5212"], ["dueAt", "\u627F\u8BFA\u4EA4\u4ED8"], ["committed", "\u8D23\u4EFB\u4EBA\u627F\u8BFA"], ["deadline", "\u4E1A\u52A1\u5B8C\u6210\u8981\u6C42"]]) {
    const value = business?.[field];
    if (value) requirements.push(validDate2(value) ? { state: "scheduled", date: value, precision: "date", origin: label2, quote: value } : { state: "unchanged", origin: label2, quote: String(value), needsReview: true });
  }
  if (!checkOverride && check.state === "unchanged" && business?.checkAt) check = validDate2(business.checkAt) ? { ...normalizeTime({ state: "scheduled", date: business.checkAt }, "legacy", source.updatedAt || source.createdAt), defaultTime: "09:00\uFF08\u65E7\u89C4\u5219\uFF09", effectiveAt: (/* @__PURE__ */ new Date(business.checkAt + "T09:00:00+08:00")).toISOString() } : { state: "unchanged", quote: String(business.checkAt), needsReview: true };
  const completion = hasTimeOverride(p1.completion) ? p1.completion : { state: "unchanged" };
  const usable = (n) => n.state === "scheduled" && !n.completedAt && !n.needsReview;
  const scheduled = usable(check) || usable(completion) || requirements.some(usable);
  const needsFollowup = ["risk", "action", "decision"].includes(item.nature) || !!item.pendingChange || p1.lifecycle?.state === "open" || p1.lifecycle?.state !== "closed" && ["waiting", "in_progress"].includes(item.handling?.state);
  const status2 = scheduled ? "\u5DF2\u5B89\u6392" : check.state === "pending" && completion.state === "pending" ? "\u660E\u786E\u5F85\u5B9A" : needsFollowup ? "\u65F6\u95F4\u5F85\u786E\u8BA4" : "\u65E0\u9700\u65F6\u95F4\u5B89\u6392";
  const today2 = shanghaiDay(at);
  const nodeDay = (node) => {
    if (!node.zone || node.zone === "Asia/Shanghai") return today2;
    if (node.zone === "UTC") return new Date(at).toISOString().slice(0, 10);
    const parts = /^([+-])(\d{2}):(\d{2})$/.exec(node.zone);
    return parts ? new Date(new Date(at).getTime() + (parts[1] === "-" ? -1 : 1) * (Number(parts[2]) * 60 + Number(parts[3])) * 6e4).toISOString().slice(0, 10) : today2;
  };
  const dueLabel = (node) => !usable(node) ? "" : node.precision === "minute" ? Date.parse(node.effectiveAt || "") <= new Date(at).getTime() ? "\u8981\u6C42\u65F6\u95F4\u5DF2\u8FC7\uFF0C\u5B8C\u6210\u60C5\u51B5\u5F85\u6838\u5B9E" : "" : node.date < nodeDay(node) ? "\u8981\u6C42\u65F6\u95F4\u5DF2\u8FC7\uFF0C\u5B8C\u6210\u60C5\u51B5\u5F85\u6838\u5B9E" : node.date === nodeDay(node) ? "\u4ECA\u65E5\u5230\u671F" : "";
  return { check, completion, requirements, status: status2, completionDue: [completion, ...requirements].map((node) => ({ node, label: dueLabel(node) })).filter((v) => v.label), checkMissing: !usable(check), checkHistorical: !!check.completedAt };
}
function timeLabel(node) {
  if (node.needsReview) return node.reviewReason || "\u539F\u65F6\u95F4\u5F85\u6838\u5BF9\uFF1A" + node.quote;
  if (node.completedAt) return "\u672C\u6B21\u68C0\u67E5\u5DF2\u5B8C\u6210\uFF08\u5386\u53F2\uFF09";
  if (node.state === "pending") return "\u660E\u786E\u5F85\u5B9A";
  if (node.state !== "scheduled") return "\u672A\u63D0\u4F9B";
  return node.date + (node.time ? " " + node.time : node.defaultTime ? " \xB7 \u9ED8\u8BA4 " + node.defaultTime : "") + (node.zone && node.zone !== "Asia/Shanghai" ? " " + node.zone : "") + (node.origin && node.origin !== "user-text" && node.origin !== "manual" ? " \xB7 " + node.origin : "");
}
function applyEntryChanges(source, changes, operationId, at) {
  const item = source.workItem;
  item.p1 ||= {};
  const p = item.p1;
  if (changes.progress) {
    const entry = { id: changes.progress.editId || operationId, text: changes.progress.text, quote: changes.progress.quote, at };
    if (changes.progress.editId) {
      if (!(p.progress || []).some((r) => r.id === entry.id)) fail3("\u539F\u8FDB\u5C55\u8BB0\u5F55\u5DF2\u53D8\u5316\uFF0C\u8BF7\u91CD\u65B0\u6838\u5BF9");
      p.progress = p.progress.map((r) => r.id === entry.id ? entry : r);
    } else p.progress = [...p.progress || [], entry];
  }
  if (changes.checkCompleted) {
    p.checkHistory = [...p.checkHistory || [], { ...p.check || {}, completedAt: at, result: changes.checkCompleted }];
    p.check = { ...p.check || {}, state: p.check?.state || "unchanged", completedAt: at };
    p.checkResult = { text: changes.checkCompleted, at };
  }
  for (const key2 of ["check", "completion"]) if (changes[key2]) {
    const node = structuredClone(changes[key2]);
    if (key2 === "check" && node.state === "scheduled" && node.precision === "date") {
      node.defaultTime = "10:00";
      const offset = node.zone === "UTC" ? "Z" : node.zone === "Asia/Shanghai" ? "+08:00" : node.zone;
      node.effectiveAt = (/* @__PURE__ */ new Date(node.date + "T10:00:00" + offset)).toISOString();
    }
    p[key2] = node;
  }
  if (changes.waiting) {
    p.waiting = { ...changes.waiting, at };
    item.handling = { ...item.handling || {}, state: "waiting", reason: "\u7B49\u5F85" + changes.waiting.who + "\uFF1A" + changes.waiting.result, at };
  }
  if (changes.followup) p.lifecycle = { state: ["end", "cancel"].includes(changes.followup || "") ? "closed" : "open", owner: "manual", reason: changes.followupQuote || "", at, operationId };
  if (changes.riskDecision) {
    p.riskDecision = { decision: changes.riskDecision, reason: changes.riskQuote, at };
    if (!changes.followup) p.lifecycle = { state: "open", reason: "\u98CE\u9669\u7ED3\u8BBA\u5DF2\u8BB0\u5F55\uFF0C\u540E\u7EED\u5B89\u6392\u5C1A\u672A\u660E\u786E\u7ED3\u675F", at, operationId };
  }
  if (p.lifecycle?.state === "closed") item.handling = { ...item.handling || {}, state: "handled", at };
  else if (changes.followup === "continue") item.handling = { ...item.handling || {}, state: "attention", at };
  item.contentHash = "";
}
function entryPatches(before, after) {
  const patches = [];
  function walk(a, b, path, beforeExists, afterExists) {
    if (same3(a, b) && beforeExists === afterExists) return;
    if (path.join(".") === "p1.progress") {
      if (!Array.isArray(a)) patches.push({ path, before: a ?? null, after: [], beforeExists, afterExists, container: true });
      const old = a || [], next = b || [];
      for (const row of next) {
        const previous = old.find((x) => x.id === row.id);
        if (!same3(previous, row)) patches.push({ path, before: previous || null, after: row, appendId: row.id });
      }
      return;
    }
    if (b && typeof b === "object" && !Array.isArray(b) || a && typeof a === "object" && !Array.isArray(a)) {
      if (!a && b) patches.push({ path, before: a ?? null, after: {}, beforeExists, afterExists, container: true });
      const left = a || {}, right = b || {};
      for (const k of /* @__PURE__ */ new Set([...Object.keys(left), ...Object.keys(right)])) walk(left[k], right[k], [...path, k], Object.hasOwn(left, k), Object.hasOwn(right, k));
    } else patches.push({ path, before: a ?? null, after: b ?? null, beforeExists, afterExists });
  }
  for (const key2 of ["p1", "handling", "reviews", "decisions", "disposition", "nature", "summary", "impact", "nextStep", "urgency"]) walk(before[key2], after[key2], [key2], Object.hasOwn(before, key2), Object.hasOwn(after, key2));
  for (const key2 of ["admission", "priority", "pause", "fullFocus", "weekly"]) walk(before.core?.[key2], after.core?.[key2], ["core", key2], Object.hasOwn(before.core || {}, key2), Object.hasOwn(after.core || {}, key2));
  return patches;
}
function undoEntry(source, patches) {
  const item = source.workItem;
  const read = (path) => path.reduce((value, key2) => value?.[key2], item);
  const exists = (path) => Object.hasOwn(read(path.slice(0, -1)) || {}, path.at(-1));
  const conflicts = patches.filter((p) => !p.container && (p.appendId ? !same3((read(p.path) || []).find((x) => x.id === p.appendId), p.after) : !same3(read(p.path), p.after) || p.afterExists !== void 0 && exists(p.path) !== p.afterExists));
  if (conflicts.length) throw Object.assign(new Error("\u672C\u6B21\u6D89\u53CA\u7684\u5185\u5BB9\u5DF2\u6709\u540E\u7EED\u4FEE\u6539\uFF0C\u672A\u64A4\u9500\u4EFB\u4F55\u5185\u5BB9\u3002\u8BF7\u67E5\u770B\u5F53\u524D\u8BB0\u5F55\u518D\u4FEE\u6B63\u3002"), { status: 409, errors: conflicts.map((p) => ({ path: p.path.join("."), message: "\u540E\u7EED\u4FEE\u6539\u4E0E\u672C\u6B21\u64A4\u9500\u51B2\u7A81" })) });
  for (const p of patches.filter((p2) => !p2.container)) {
    let parent = item;
    for (const key3 of p.path.slice(0, -1)) parent = parent[key3] ??= {};
    const key2 = p.path.at(-1);
    if (p.appendId) parent[key2] = p.before === null ? (parent[key2] || []).filter((x) => x.id !== p.appendId) : (parent[key2] || []).map((x) => x.id === p.appendId ? structuredClone(p.before) : x);
    else if (p.beforeExists === false || p.beforeExists === void 0 && p.before === null) delete parent[key2];
    else parent[key2] = structuredClone(p.before);
  }
  for (const p of patches.filter((p2) => p2.container).sort((a, b) => b.path.length - a.path.length)) {
    const value = read(p.path), parent = read(p.path.slice(0, -1));
    if (parent && value && typeof value === "object" && Object.keys(value).length === 0) {
      if (p.beforeExists) parent[p.path.at(-1)] = structuredClone(p.before);
      else delete parent[p.path.at(-1)];
    }
  }
  item.contentHash = "";
}
function entryReceipts(s, sourceId) {
  return Object.entries(s.receipts).flatMap(([key2, r]) => r.result?.p1 && r.result.sourceId === sourceId && key2 === "work-item:" + r.result.operationId ? [{ ...r.result, workspaceId: s.workspaceId, requestId: key2.slice("work-item:".length) }] : []).sort((a, b) => String(b.at).localeCompare(String(a.at)));
}
function receiptProgressId(receipt2) {
  return receipt2.progress ? receipt2.progressId || receipt2.input?.editProgressId || receipt2.patches?.find((p) => p.path.join(".") === "p1.progress" && p.appendId)?.appendId || receipt2.operationId || "" : "";
}

// lib/subject-association.ts
function sourceSubjectIdentity(source) {
  const message = source.personalMessage || source.caseChat;
  if (message?.scope && message.accountId && message.chatId && !message.channels?.includes("private")) {
    const chat = { scope: message.scope, accountId: message.accountId, chatId: message.chatId };
    return { key: "chat:" + JSON.stringify([chat.scope, chat.accountId, chat.chatId]), chat };
  }
  return { key: "source:" + source.id };
}
function subjectAssociationTarget(s, source) {
  const { key: key2 } = sourceSubjectIdentity(source);
  const bindings = s.sources.filter((row) => !row.archived && !row.subjectAssociation?.historical && row.subjectAssociation?.key === key2);
  const targets = bindings.map((row) => row.subjectAssociation.target).filter((target) => ["projects", "cases"].includes(target?.kind) && s[target.kind].some((row) => row.id === target.id && !row.archived && !row.mergedIntoId));
  const unique7 = [...new Map(targets.map((target) => [target.kind + ":" + target.id, target])).values()];
  return unique7.length === 1 ? unique7[0] : null;
}
function applySourceSubjectAssociation(s, source, target = subjectAssociationTarget(s, source)) {
  if (!target) return false;
  const record2 = s[target.kind].find((row) => row.id === target.id && !row.archived && !row.mergedIntoId);
  if (!record2) return false;
  const projects = target.kind === "projects" ? [record2.id] : record2.projectIds || [];
  if ((source.projectIds || []).some((id2) => !projects.includes(id2)) || (source.caseIds || []).some((id2) => target.kind !== "cases" || id2 !== target.id)) return false;
  const old = JSON.stringify([source.projectIds, source.objectIds, source.caseIds]);
  source.projectIds = [.../* @__PURE__ */ new Set([...source.projectIds || [], ...projects])];
  source.objectIds = [.../* @__PURE__ */ new Set([...source.objectIds || [], target.id])];
  if (target.kind === "cases") source.caseIds = [target.id];
  return old !== JSON.stringify([source.projectIds, source.objectIds, source.caseIds]);
}

// lib/management-signals.ts
var digest = (value) => stableHash(JSON.stringify(value));
var businessKinds = ["projects", "flowNodes", "deliverables", "actions", "milestones", "risks", "decisions", "cases", "dependencies"];
var human = (value) => typeof value === "string" && value.trim() && !/待确认|待指定|未知|^(?:ou_|on_|user_|person-)|^\d{7,}$/.test(value.trim()) ? value.trim() : "";
function ruleOwner(s, row) {
  const resolve = (value) => {
    if (Array.isArray(value)) return value.map(resolve).filter(Boolean).join("\u3001");
    if (value && typeof value === "object") {
      const x = value;
      return human(x.name || x.display_name || x.displayName) || resolve(x.id || x.key || x.open_id);
    }
    const person = s.people.find((p) => !p.archived && p.confirmed !== false && [p.id, p.meegleUserKey, p.feishuUserId].includes(String(value || "")));
    return person ? human(person.title) : human(value);
  };
  if (row.ownerId) {
    const person = s.people.find((p) => p.id === row.ownerId && !p.archived && p.confirmed !== false);
    if (person) return human(person.title);
  }
  return resolve(row.owner);
}
function ruleProjectScope(s, project) {
  const metadata = projectMetadata(s, project);
  const types2 = [project.projectType, metadata.category, ...metadata.isIpd ? ["IPD"] : [], .../IRAD/i.test(metadata.category) ? ["IRAD"] : []].filter((x) => typeof x === "string" && !!x.trim());
  return { types: [...new Set(types2)], level: projectLevel(s, project) };
}
function evaluateCoreRule(s, check, kind, targetId) {
  const row = s[kind]?.find((r) => r.id === targetId && !r.archived);
  if (!row) return null;
  let status2 = "pass", reason = "\u5DF2\u4FDD\u5B58\u4F9D\u636E\u6EE1\u8DB3\u672C\u9879\u8D44\u6599\u68C0\u67E5";
  const evidenceIds = [];
  let facts;
  if (check === "deliverable_owner") {
    const owner2 = ruleOwner(s, row);
    facts = [row.ownerId || "", owner2, row.owner || ""];
    if (!owner2) {
      status2 = "uncovered";
      reason = "\u8D23\u4EFB\u4EBA\u8D44\u6599\u7F3A\u5931\u6216\u5C1A\u672A\u6838\u5BF9";
    }
  } else if (check === "acceptance_evidence") {
    facts = [observedDeliveryReview(row), row.feishuFacts?.deliveryReview];
    status2 = "not_applicable";
    reason = deliveryRecorded(row) ? "\u5DE5\u7A0B\u5E08\u5DF2\u6807\u8BB0\u5DF2\u5BA1\u6838\uFF0C\u5DF2\u8BB0\u5F55\u4EA4\u4ED8" : "\u4EA4\u4ED8\u7531\u5DE5\u7A0B\u5E08\u63D0\u4EA4\u5E76\u9009\u62E9\u5DF2\u5BA1\u6838\uFF0C\u4E0D\u589E\u52A0\u7ECF\u7406\u5185\u5BB9\u9A8C\u6536";
  } else if (check === "node_delivery_evidence") {
    const linked = s.deliverables.filter((d) => !d.archived && d.flowNodeIds?.includes(row.id));
    facts = [row.nodeStatus, linked.map((d) => [d.id, observedDeliveryReview(d)])];
    if (!["\u5DF2\u5B8C\u6210", "\u5DF2\u901A\u8FC7", "finished"].includes(row.nodeStatus)) {
      status2 = "not_applicable";
      reason = "\u8282\u70B9\u5C1A\u672A\u53CD\u9988\u5B8C\u6210";
    } else if (!linked.length) {
      status2 = "uncovered";
      reason = "\u8282\u70B9\u5DF2\u5B8C\u6210\uFF0C\u672A\u8BFB\u5230\u5176\u4EA4\u4ED8\u7269\u4F9D\u636E\uFF0C\u4E0D\u80FD\u636E\u6B64\u63A8\u5B9A\u5DE5\u7A0B\u5E08\u672A\u4EA4\u4ED8";
    } else if (linked.some((d) => !deliveryRecorded(d))) {
      status2 = row.currentImpactConfirmed ? "attention" : "uncovered";
      reason = "\u8282\u70B9\u5DF2\u5B8C\u6210\uFF0C\u90E8\u5206\u4EA4\u4ED8\u6807\u8BB0\u5F85\u6838\u5BF9\uFF1B\u8D44\u6599\u7F3A\u53E3\u4E0D\u81EA\u52A8\u6210\u4E3A\u98CE\u9669";
    }
    evidenceIds.push(...linked.flatMap((d) => d.evidenceIds || []).filter((id2) => s.sources.some((src) => src.id === id2)));
  } else return null;
  return { status: status2, reason, evidenceIds, targetId, targetKind: kind, targetTitle: row.title, basis: digest([check, kind, targetId, facts]) };
}
function managementTargets(s) {
  return businessKinds.flatMap((kind) => s[kind].filter((row) => !row.archived && !row.mergedIntoId).map((row) => ({ kind, id: row.id, title: row.title, projectIds: row.projectIds })));
}
function inferredManagementTarget(s, source) {
  const association = subjectAssociationTarget(s, source);
  if (association) return association;
  const ids8 = [...new Set((source.objectIds || []).map((id2) => intakeCanonicalTarget(s, id2)))];
  const targets = managementTargets(s).filter((t) => ids8.includes(t.id));
  if (targets.length === 1) return { kind: targets[0].kind, id: targets[0].id };
  const projects = s.projects.filter((p) => !p.archived && source.projectIds?.includes(p.id));
  if (!targets.length && projects.length === 1) return { kind: "projects", id: projects[0].id };
  const message = source.personalMessage || source.caseChat;
  if (!targets.length && !projects.length && message?.chatId) {
    const cases = s.cases.filter((row) => !row.archived && row.chatBinding?.chatId === message.chatId && row.chatBinding?.scope === message.scope && row.chatBinding?.accountId === message.accountId);
    if (cases.length === 1) return { kind: "cases", id: cases[0].id };
    const scopes = s.sources.filter((row) => !row.archived && row.chatScope?.state === "active" && row.chatScope.chatId === message.chatId && row.chatScope.scope === message.scope && row.chatScope.accountId === message.accountId);
    const ids9 = [...new Set(scopes.map((row) => row.chatScope.projectId).filter((id2) => s.projects.some((p) => p.id === id2 && !p.archived)))];
    if (ids9.length === 1) return { kind: "projects", id: ids9[0] };
  }
  return null;
}
function managementSignalState(s, source) {
  const signal = source.managementSignal;
  let target = signal.target;
  if (target?.kind === "actions") {
    const id2 = intakeCanonicalTarget(s, target.id);
    if (id2 !== target.id) target = { kind: "deliverables", id: id2 };
  }
  const record2 = target ? s[target.kind]?.find((row) => row.id === target.id && !row.archived) : void 0;
  let available = true, stale = false, ruleSatisfied = false, currentSummary = signal.summary, evidenceBasis;
  if (signal.origin === "agent" || signal.origin === "dot") {
    const original = s.sources.find((row) => row.id === signal.sourceId);
    available = !!original && caseEvidenceAvailable(s, original);
    const current = original ? materialSourceIdentityKey(s, original) : "";
    stale = !available || current !== signal.sourceBasis;
    evidenceBasis = [current, signal.summary, signal.quote, signal.nextStep, ...signal.triage ? [signal.triage] : []];
    if (signal.evidence?.length) {
      const proofs = signal.evidence.map((proof) => {
        const source2 = s.sources.find((row) => row.id === proof.sourceId);
        return { source: source2, proof, current: source2 ? materialSourceIdentityKey(s, source2) : "", available: !!source2 && caseEvidenceAvailable(s, source2) };
      });
      available = available && proofs.every((p) => p.available);
      stale = stale || proofs.some((p) => !p.available || p.current !== p.proof.basis);
      evidenceBasis = [evidenceBasis, proofs.map((p) => [p.current, p.available, p.proof])];
    }
    if (stale) currentSummary = "\u5EFA\u8BAE\u6240\u636E\u539F\u6587\u5DF2\u6709\u53D8\u5316\u6216\u4E0D\u53EF\u7528\uFF0C\u8BF7\u91CD\u65B0\u6838\u5BF9\u5F53\u524D\u8D44\u6599\u3002";
  } else {
    const project = s.projects.find((p) => p.id === signal.rule?.projectId && !p.archived);
    const scope = signal.rule?.bundle.appliesTo, metadata = project ? ruleProjectScope(s, project) : null;
    const applicable = !!metadata && (!scope?.projectTypes?.length || scope.projectTypes.some((t) => metadata.types.includes(t))) && (!scope?.levels?.length || scope.levels.includes(metadata.level));
    const finding = signal.rule && target ? evaluateCoreRule(s, signal.rule.check, target.kind, target.id) : null;
    available = !!record2 && !!finding;
    stale = !available || !applicable;
    ruleSatisfied = !stale && !!finding && ["pass", "not_applicable"].includes(finding.status);
    evidenceBasis = [finding?.basis || "", metadata, signal.rule?.bundle.id, signal.rule?.bundle.version];
    currentSummary = stale ? "\u89C4\u5219\u9002\u7528\u8303\u56F4\u6216\u4E1A\u52A1\u5BF9\u8C61\u5DF2\u6709\u53D8\u5316\uFF0C\u8BF7\u91CD\u65B0\u6838\u5BF9\u3002" : finding?.status === "attention" ? finding.reason : "\u5F53\u524D\u8D44\u6599\u68C0\u67E5\u6761\u4EF6\u5DF2\u6709\u53D8\u5316\uFF0C\u8BF7\u6838\u5BF9\u672C\u6B21\u95EE\u9898\u662F\u5426\u5DF2\u5904\u7406\u3002";
  }
  const basis = digest([signal.origin, signal.originId, target, evidenceBasis, available, stale]);
  const previous = signal.reviews?.at(-1);
  const review = previous && (previous.basis === basis || signal.associationReviewBasis?.previous === previous.basis && signal.associationReviewBasis.current === basis) ? previous : void 0;
  const priorConfirmed = previous?.decision === "confirmed";
  const open = !signal.historical && (signal.priority === "attention" || priorConfirmed) && (!ruleSatisfied || priorConfirmed) && (!review || review.decision === "confirmed");
  return { signal, target, record: record2, basis, available, stale, ruleSatisfied, currentSummary, previous, review, open };
}
function itemManagementSignals(s, kind, id2) {
  return s.sources.filter((source) => !source.archived && source.managementSignal && !source.managementSignal.workItemId).flatMap((source) => {
    const current = managementSignalState(s, source);
    return kind === "sources" && source.id === id2 || current.target?.kind === kind && current.target.id === id2 ? [{ source, ...current }] : [];
  });
}
function validateManagementTarget(s, value) {
  if (value == null) return null;
  const ref = value;
  if (!v2Kinds.includes(ref.kind) || !businessKinds.includes(ref.kind) || !s[ref.kind]?.some((row) => row.id === ref.id && !row.archived)) throw Error("\u8BF7\u9009\u62E9\u672C\u5DE5\u4F5C\u533A\u5185\u4ECD\u6709\u6548\u7684\u4E1A\u52A1\u4E8B\u9879");
  return { kind: ref.kind, id: ref.id };
}

// lib/risk-signals.ts
var isRiskSignal = (signal) => signal.kind === "risk" || signal.urgency === "urgent";
function riskSignalState(s, batch, signal, index) {
  const key2 = signal.id || batch.id + ":signal:" + index;
  const source = s.sources.find((row) => row.id === signal.sourceId);
  const available = !!source && caseEvidenceAvailable(s, source) && !batch.archived;
  const basis = stableHash(JSON.stringify({ batchId: batch.id, key: key2, signal, source: source ? materialSourceIdentityKey(s, source) : null, available, revertedAt: batch.intakeBatch.revertedAt || "" }));
  const history = batch.intakeBatch.signalReviews || [];
  const previous = history.filter((review2) => review2.signalKey === key2).at(-1);
  const review = previous?.basis === basis && ["confirmed", "dismissed", "resolved"].includes(previous.decision) && previous.reason?.trim() ? previous : void 0;
  return { key: key2, basis, available, review, previous, open: !review || review.decision === "confirmed", needsVerification: !review };
}
function intakeSignalMatches(s, signal, kind, targetIds) {
  const targetId = intakeCanonicalTarget(s, signal.targetId);
  if (!targetIds.includes(targetId)) return false;
  const targets = intakeTargets(s).filter((target) => target.id === targetId);
  return targets.length === 1 && (targets[0].kind === kind || targets[0].kind === "actions" && targetIds.length > 1);
}
function itemRiskSignals(s, kind, targetId) {
  return s.sources.filter((batch) => batch.intakeBatch && !batch.archived).flatMap((batch) => (batch.intakeBatch.signals || []).flatMap((signal, index) => !signal.workItemId && isRiskSignal(signal) && (kind === "sources" ? batch.id === targetId : intakeSignalMatches(s, signal, kind, [targetId])) ? [{ batch, signal, index, ...riskSignalState(s, batch, signal, index) }] : []));
}

// lib/followup-lifecycle.ts
var text9 = (v) => typeof v === "string" ? v.trim() : "";
var ids5 = (v) => Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
var canonical = (v) => JSON.stringify(v, (_k, x) => x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, x[k]])) : x);
function followupFingerprint(value) {
  const input = canonical(value);
  let a = 2166136261, b = 5381;
  for (let i = 0; i < input.length; i++) {
    a = Math.imul(a ^ input.charCodeAt(i), 16777619);
    b = Math.imul(b, 33) ^ input.charCodeAt(i);
  }
  return (a >>> 0).toString(36) + "-" + (b >>> 0).toString(36);
}
var followupItemKey = (workspaceId, ref) => [workspaceId, ref.kind, ref.targetId].map(encodeURIComponent).join(":");
var followupDay = (now2 = Date.now()) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(now2));
var dayTime = (day) => gateDate(day) ? Date.parse(day + "T09:00:00+08:00") : NaN;
function fail4(message, status2 = 409) {
  throw Object.assign(new Error(message), { status: status2 });
}
var accepted2 = (r) => deliveryRecorded(r) || ["\u5DF2\u9A8C\u6536", "\u901A\u8FC7", "\u9A8C\u6536\u901A\u8FC7", "\u5DF2\u901A\u8FC7"].includes(r.acceptanceStatus);
function closed(r, kind) {
  return r.archived || r.mergedIntoId || ["\u5DF2\u5173\u95ED", "\u5DF2\u89E3\u9664", "\u5DF2\u53D6\u6D88"].includes(r.status) || ["deliverables", "actions", "milestones"].includes(kind) && accepted2(r);
}
function canonicalFollowupRef(s, ref) {
  const clean = { kind: ref.kind, targetId: ref.targetId };
  if (ref.kind !== "actions") return clean;
  const a = s.actions.find((r) => r.id === ref.targetId && !r.archived);
  const matches = a ? s.deliverables.filter((d) => !d.archived && (ids5(a.outputIds).includes(d.id) || ids5(d.actionIds).includes(a.id)) && (d.projectIds.some((id2) => a.projectIds.includes(id2)) || !!d.caseId && d.caseId === a.caseId)) : [];
  return matches.length === 1 ? { kind: "deliverables", targetId: matches[0].id } : clean;
}
var relatedActions = (s, ref) => ref.kind === "deliverables" ? s.actions.filter((a) => !a.archived && canonicalFollowupRef(s, { kind: "actions", targetId: a.id }).targetId === ref.targetId) : [];
function sourceRef(s, sourceId) {
  const src = s.sources.find((r) => r.id === sourceId);
  const available = !!src && caseEvidenceAvailable(s, src) && !s.sources.some((r) => !r.archived && r.confirmed && r.supersedesId === sourceId);
  return {
    id: sourceId,
    version: src?.version || 0,
    title: src?.title || "\u6765\u6E90\u4E0D\u53EF\u7528",
    available,
    fingerprint: src ? followupFingerprint([materialSourceIdentityKey(s, src), available]) : "missing",
    eventAt: feedbackTime(src?.feedback?.eventAt || src?.occurredAt)
  };
}
function buildFollowup(s, input, now2 = Date.now()) {
  if (!Number.isFinite(now2)) fail4("\u5F53\u524D\u65F6\u949F\u65E0\u6548", 422);
  const ref = canonicalFollowupRef(s, input), row = s[ref.kind]?.find((r) => r.id === ref.targetId);
  if (!row) fail4("\u5F85\u5904\u7406\u5BF9\u8C61\u4E0D\u5B58\u5728", 404);
  if (row.workItem) return workItemFollowup(s, row, now2);
  const related2 = relatedActions(s, ref), targetIds = [row.id, ...related2.map((r) => r.id)], itemKey = followupItemKey(s.workspaceId, ref);
  const meta = row.followupHandling?.workspaceId === s.workspaceId ? row.followupHandling : {};
  const today2 = followupDay(now2), projectIds2 = ref.kind === "projects" ? [row.id] : row.projectIds;
  const gates = projectIds2.map((id2) => s.projects.find((p) => p.id === id2 && !p.archived)).filter((p) => !!p).map((p) => ({ projectId: p.id, ...getProjectGates(s, p).next }));
  const gateBasis = followupFingerprint(gates), gateDates = gates.map((g) => g.date).filter((d) => !!d).sort();
  const relevant = (value) => !value.workItemId && (["risk", "followup", "clarify"].includes(value.kind) ? intakeSignalMatches(s, value, ref.kind, targetIds) : targetIds.includes(value.targetId) && (!value.kind || value.kind === ref.kind || value.kind === "actions" && related2.some((a) => a.id === value.targetId)));
  const comments = ["actions", "deliverables"].includes(ref.kind) ? s.sources.filter((src) => isCommentFeedback(src) && !workItemOwnsFeedback(s, src.id) && (feedbackRelated(s, src, row) || related2.some((a) => feedbackRelated(s, src, a))) && !src.feedback.observationOnly) : [];
  const batches = s.sources.filter((src) => src.intakeBatch && [...src.intakeBatch.autoUpdates || [], ...src.intakeBatch.evidenceRefresh || [], ...src.intakeBatch.pending || [], ...src.intakeBatch.signals || []].some(relevant));
  const provenance = row.intakeFeedback, batch = s.sources.find((src) => src.id === provenance?.batchId), job = batch?.intakeBatch;
  const batchRefs = batches.flatMap((src) => [...src.intakeBatch.autoUpdates || [], ...src.intakeBatch.evidenceRefresh || [], ...src.intakeBatch.pending || [], ...src.intakeBatch.signals || []].filter(relevant).flatMap((v) => [v.sourceId, ...(v.supportingSources || []).map((r) => r.sourceId)])).filter(Boolean);
  const refs = [.../* @__PURE__ */ new Set([...ids5(row.sourceIds), ...comments.map((src) => src.id), ...batchRefs, ...provenance?.sourceId ? [provenance.sourceId] : []])].sort().map((id2) => sourceRef(s, id2));
  const sourceKeys = refs.map((r) => [r.id, r.fingerprint, r.available]);
  const feedbackBasis = followupFingerprint([sourceKeys, batches.map((b) => [b.id, !!b.archived, !!b.intakeBatch.revertedAt, (b.intakeBatch.pending || []).filter(relevant), (b.intakeBatch.signals || []).filter(relevant)]), provenance]);
  const signals = batches.filter((b) => !b.archived && !b.intakeBatch.revertedAt).flatMap((b) => (b.intakeBatch.signals || []).filter((v, index) => relevant(v) && (!isRiskSignal(v) || riskSignalState(s, b, v, index).open)).filter((v) => !v.sourceId || refs.some((r) => r.id === v.sourceId && r.available)));
  const pending3 = batches.filter((b) => !b.archived && !b.intakeBatch.revertedAt).flatMap((b) => (b.intakeBatch.pending || []).filter(relevant).filter((v) => !v.sourceId || refs.some((r) => r.id === v.sourceId && r.available)));
  const urgentSignals = signals.filter((v) => v.urgency === "urgent");
  const unverifiedUrgent = batches.some((batch2) => (batch2.intakeBatch.signals || []).some((signal, index) => urgentSignals.includes(signal) && riskSignalState(s, batch2, signal, index).needsVerification));
  const parentCase = row.caseId ? s.cases.find((c) => c.id === row.caseId) : void 0;
  const certain = (r) => r.confirmed !== false && !r.stale && !["suggestion", "hypothesis"].includes(r.classification || r.draftClassification);
  const urgent = certain(row) && (row.status === "\u9700\u8981\u5347\u7EA7\u534F\u8C03" || ref.kind === "risks" && row.confirmed === true && row.impact === "\u9AD8" || ref.kind === "decisions" && row.confirmed === true && !!gateDate(row.deadline) && row.deadline <= today2 || related2.some((a) => certain(a) && a.status === "\u9700\u8981\u5347\u7EA7\u534F\u8C03")) || urgentSignals.length > 0;
  const matchesItem = (i) => {
    const kind = i.kind || (s.deliverables.some((d) => d.id === i.targetId) ? "deliverables" : "actions");
    return kind === ref.kind && i.targetId === row.id || kind === "actions" && related2.some((a) => a.id === i.targetId);
  };
  const runs = s.sources.filter((src) => !src.reminderRun?.core && src.reminderRun?.workspaceId === s.workspaceId && src.reminderRun.items.some(matchesItem));
  const unknown = runs.filter((src) => src.reminderRun.items.some((i) => matchesItem(i) && i.createTask && ["sending", "sent"].includes(i.taskStage)) || src.reminderRun.messages.some((m) => ["sending", "sent"].includes(m.stage)) || ["partial", "needs_reconcile", "sending"].includes(src.reminderRun.status) && (src.reminderRun.items.some((i) => i.createTask && i.taskStage === "readback_verified") || src.reminderRun.messages.some((m) => m.stage === "readback_verified")));
  const sent = runs.flatMap((src) => src.reminderRun.items.filter(matchesItem).flatMap((i) => {
    const messages = src.reminderRun.messages.filter((m) => i.recipientIds.includes(m.recipientId));
    if (!messages.length || !messages.every((m) => m.stage === "readback_verified")) return [];
    const at = feedbackTime(messages.map((m) => m.sentAt || m.sendAttemptedAt || src.reminderRun.approvedAt || m.readAt).filter(Boolean).sort().at(-1) || src.reminderRun.finishedAt);
    return at ? [{ sourceId: src.id, at, context: i.followupContext }] : [];
  })).sort((a, b) => Date.parse(b.at) - Date.parse(a.at))[0];
  const sourceChanged = !!sent?.context && canonical(sent.context.sources) !== canonical(sourceKeys);
  const gateChanged = !!sent?.context && sent.context.gateBasis !== gateBasis;
  const latestComment = comments.filter((src) => !src.archived && !src.feedback.deleted).slice().sort((a, b) => Date.parse(b.feedback.eventAt || 0) - Date.parse(a.feedback.eventAt || 0))[0];
  const awaitingReply = !!sent || !!meta.schedule || !!meta.pickedUpAt || !!row.followUp || !!row.checkAt || row.status === "\u7B49\u5F85\u4ED6\u4EBA\u53CD\u9988";
  const responseAfterSend = comments.some((src) => !src.archived && !src.feedback.deleted && (sent ? !!feedbackTime(src.feedback.eventAt) && Date.parse(src.feedback.eventAt) > Date.parse(sent.at) : awaitingReply || src.feedback.analysis?.viewerAction === true || src.feedback.analysis?.kind === "needs_confirmation"));
  const feedbackReviewed = meta.reviewedFeedbackBasis === feedbackBasis || (comments.length > 0 || !!job) && (!provenance || !!job?.reviewedAt) && comments.every((src) => src.feedback.reviewedVersion === src.feedback.contentVersion);
  const pendingReply = !feedbackReviewed && (sourceChanged || responseAfterSend || awaitingReply && !!provenance && (!sent || !!feedbackTime(provenance.occurredAt) && Date.parse(provenance.occurredAt) > Date.parse(sent.at)));
  const replaced = (id2) => {
    const old2 = s.sources.find((src) => src.id === id2), origin2 = old2?.intakeDocument?.originalSourceId;
    return !!origin2 && refs.some((r) => r.id !== id2 && r.available && s.sources.find((src) => src.id === r.id)?.intakeDocument?.originalSourceId === origin2);
  };
  const unavailable = refs.some((r) => !r.available && !replaced(r.id)), reverted = !!provenance && (!job || batch?.archived || job.revertedAt || provenance.state === "\u8BE5\u6279\u66F4\u65B0\u5DF2\u64A4\u56DE");
  const conflict = pending3.length > 0 || signals.some((v) => v.kind === "clarify") || latestComment?.feedback.analysis?.uncertainties?.length > 0;
  const source = refs.find((r) => r.id === provenance?.sourceId), occurred = feedbackTime(provenance?.occurredAt || source?.eventAt), origin = s.sources.find((src) => src.id === source?.id);
  const progress = text9(row[intakeProgressField(ref.kind)]), forecast = gateDate(row.forecast);
  const trusted = !!source?.available && !!job && !reverted && ["ready", "partial"].includes(job.status) && [...job.autoUpdates || [], ...job.evidenceRefresh || []].some((u) => u.targetId === row.id && u.sourceId === source.id) && origin?.intakeDocument?.complete !== false && !!text9(provenance?.quote) && text9(origin?.excerpt).includes(provenance.quote);
  const predatesRequest = !!sent && !!occurred && Date.parse(occurred) <= Date.parse(sent.at);
  const old = predatesRequest && (sourceChanged || !!feedbackTime(provenance?.at) && Date.parse(provenance.at) > Date.parse(sent.at));
  const stale = unavailable || reverted || old || !!occurred && Date.parse(occurred) > now2;
  const gateConcern = signals.some((v) => v.kind === "risk") || [row, ...related2].some((r) => text9(r.blocker) && !["\u65E0", "\u6682\u65E0", "\u5DF2\u89E3\u9664"].includes(text9(r.blocker)));
  const clear = trusted && !stale && !predatesRequest && !conflict && !gateConcern && !!occurred && !!progress && !/^(正在|在)?(处理|跟进|推进|进行中)[。！! ]*$/.test(progress) && !!forecast && forecast > today2 && gateDates.length === gates.length && gates.length > 0 && forecast < gateDates[0] && (!latestComment || Date.parse(latestComment.feedback.eventAt) <= Date.parse(occurred));
  const historicalOnly = !!sent && !sourceChanged && !responseAfterSend && (!provenance || predatesRequest);
  const feedbackState = stale ? "stale" : conflict ? "conflict" : clear ? "clear" : historicalOnly ? "none" : comments.length || provenance ? "vague" : "none";
  const gaps = [...new Set(pending3.map((p) => p.reason).concat(signals.filter((v) => v.kind === "clarify" || v.kind === "followup").map((v) => v.question)).filter(Boolean))];
  const clarification = feedbackState === "vague" || feedbackState === "conflict" ? gaps.join("\uFF1B") || `\u8BF7\u8865\u5145\u300C${row.title}\u300D\u7684\u5177\u4F53\u8FDB\u5C55\u3001\u6574\u9879\u9884\u8BA1\u5B8C\u6210\u65F6\u95F4\u3001\u5F53\u524D\u963B\u788D\u53CA\u6210\u679C\u5165\u53E3\u3002` : "";
  const result = s.sources.filter((src) => !src.archived && src.resultReview?.deliverableId === row.id).slice().sort((a, b) => text9(b.collectedAt).localeCompare(text9(a.collectedAt)))[0];
  const needsAcceptance = false;
  const formalDates = [row.checkAt, row.dueAt, row.plannedEnd, row.committed, row.deadline, ...gateDates].filter((v) => gateDate(v)).sort();
  const evidenceBasis = followupFingerprint([ref, row.title, row.owner, row.ownerId, projectIds2, row.caseId, row.status, row.blocker, row.followUp, row.nextAction, row.forecast, progress, row.submissionStatus, row.acceptanceStatus, row.deliveryReview, formalDates, sourceKeys, gateBasis, feedbackBasis, signals, related2.map((a) => [a.id, a.status, a.blocker]), parentCase && [parentCase.status, parentCase.myRole], result?.resultReview?.status]);
  let nextCheckAt = "";
  if (clear) nextCheckAt = new Date(Math.min(dayTime(forecast), dayTime(gateDates[0]))).toISOString();
  else if (sent) {
    const futureDates = formalDates.map(dayTime).filter((n) => n > Date.parse(sent.at));
    nextCheckAt = new Date(Math.min(Date.parse(sent.at) + 864e5, ...futureDates)).toISOString();
  }
  let scheduleCapped = false;
  if (meta.schedule?.evidenceBasis === evidenceBasis) {
    const anchor = Date.parse(sent?.at || meta.schedule.createdAt || meta.schedule.at), limits = [row.dueAt, row.plannedEnd, row.committed, row.deadline, ...gateDates].map(dayTime).filter((n) => n > anchor);
    const effective = Math.min(Date.parse(meta.schedule.at), ...limits);
    nextCheckAt = new Date(effective).toISOString();
    scheduleCapped = effective < Date.parse(meta.schedule.at);
  }
  const due = !!nextCheckAt && Date.parse(nextCheckAt) <= now2;
  const formalChanged = !!sent?.context && sent.context.formalDates !== followupFingerprint(formalDates);
  const reasons = [];
  if (unknown.length) reasons.push("\u5916\u90E8\u6267\u884C\u7ED3\u679C\u5F85\u6838\u5BF9\uFF1B\u5148\u56DE\u8BFB\u539F\u6279\u6B21");
  if (urgent) reasons.push(urgentSignals.length ? unverifiedUrgent ? "\u6709\u4F9D\u636E\u7684\u91CD\u5927\u7591\u70B9\u5F85\u6838\u5B9E\uFF0C\u53EF\u80FD\u5F71\u54CD\u5173\u53E3" : "\u5DF2\u6838\u5B9E\u98CE\u9669\u5C1A\u672A\u89E3\u9664\uFF0C\u4ECD\u9700\u8DDF\u8FDB" : "\u7D27\u6025\u95EE\u9898\u5C1A\u672A\u89E3\u9664");
  if (pendingReply) reasons.push("\u5DF2\u6709\u76F8\u5173\u53CD\u9988\u6216\u6765\u6E90\u53D8\u5316\uFF0C\u5F85\u4F60\u6838\u5BF9");
  if (stale) reasons.push(unavailable || reverted ? "\u6240\u636E\u53CD\u9988\u5DF2\u66F4\u6B63\u3001\u64A4\u56DE\u6216\u4E0D\u53EF\u7528" : "\u53CD\u9988\u65F6\u95F4\u8FC7\u65E9\u3001\u8FC7\u671F\u6216\u4E0D\u53EF\u9760\uFF0C\u4E0D\u80FD\u8986\u76D6\u5F53\u524D\u8DDF\u8FDB");
  if (conflict) reasons.push("\u53CD\u9988\u5B58\u5728\u51B2\u7A81\u6216\u4FE1\u606F\u7F3A\u53E3\uFF0C\u9700\u6838\u5BF9");
  if (gateConcern && !urgent) reasons.push("\u4ECD\u6709\u98CE\u9669\u6216\u963B\u788D\u4F9D\u636E\uFF0C\u5173\u53E3\u5F71\u54CD\u5F85\u6838\u5BF9");
  const clarificationNeeded = feedbackState === "vague" && (responseAfterSend || sourceChanged || !sent && comments.length > 0);
  if (clarificationNeeded) reasons.push("\u53CD\u9988\u4FE1\u606F\u5C1A\u4E0D\u5B8C\u6574\uFF0C\u8865\u95EE\u8349\u7A3F\u5F85\u5BA1\u6838");
  if (gateChanged || formalChanged) reasons.push("\u5173\u53E3\u6216\u6B63\u5F0F\u65E5\u671F\u5DF2\u53D8\u5316\uFF0C\u9700\u91CD\u65B0\u6838\u5BF9\u8DDF\u8FDB\u5B89\u6392");
  if (due) reasons.push("\u5DF2\u5230\u4E0B\u6B21\u8DDF\u8FDB\u65F6\u95F4");
  if (scheduleCapped) reasons.push("\u4EBA\u5DE5\u8DDF\u8FDB\u65F6\u95F4\u665A\u4E8E\u6B63\u5F0F\u671F\u9650\uFF0C\u4ECD\u6309\u8F83\u65E9\u671F\u9650\u8FD4\u56DE\u590D\u6838");
  if (needsAcceptance) reasons.push("\u6210\u679C\u5DF2\u63D0\u4EA4\uFF0C\u5F85\u4EBA\u5DE5\u6838\u5BF9\u9A8C\u6536");
  const done = closed(row, ref.kind) && !needsAcceptance;
  let handlingState = done ? "handled" : urgent && meta.pickedUpAt ? "in_progress" : "attention";
  const safeWait = !urgent && !unknown.length && !pendingReply && !stale && !conflict && !gateConcern && (!clarificationNeeded || meta.schedule?.evidenceBasis === evidenceBasis) && !gateChanged && !formalChanged && !needsAcceptance && !due;
  if (!done && safeWait && !!nextCheckAt && (!!sent || clear || !!meta.schedule)) handlingState = "waiting";
  const waitingReason = clear ? "\u5DF2\u6709\u660E\u786E\u53CD\u9988\uFF0C\u6682\u7F13\u91CD\u590D\u50AC\u529E" : sent ? "\u5DF2\u50AC\u529E\uFF0C\u7B49\u5F85\u5916\u90E8\u53CD\u9988" : meta.schedule ? "\u6309\u4EBA\u5DE5\u8C03\u6574\u65F6\u95F4\u8DDF\u8FDB" : "";
  if (handlingState === "waiting") reasons.unshift(waitingReason);
  const reminderEligible = !done && !unknown.length && !needsAcceptance && !stale && !conflict && handlingState !== "waiting" && (!clear || due || gateChanged || formalChanged || urgent);
  const notificationBasis = followupFingerprint([row.status, row.impact, row.blocker, related2.filter((a) => a.status === "\u9700\u8981\u5347\u7EA7\u534F\u8C03").map((a) => [a.id, a.status, a.blocker]), urgentSignals.map((v) => [v.sourceId, refs.find((r) => r.id === v.sourceId)?.fingerprint, v.kind, v.title, v.reason]), gateBasis]);
  const eligible = reminderEligible && (!clear || due || gateChanged || formalChanged || urgent) && !(urgent && !!sent && sent.context?.notificationBasis === notificationBasis);
  const active5 = !done && !row.taskObservationOnly && (!parentCase || !parentCase.archived && parentCase.status !== "\u5DF2\u5173\u95ED" && parentCase.myRole !== "\u5173\u6CE8");
  return {
    ...ref,
    itemKey,
    title: row.title,
    projectIds: projectIds2,
    caseId: ref.kind === "cases" ? row.id : row.caseId,
    handlingState,
    urgent: active5 && urgent,
    reason: reasons[0] || "\u6838\u5BF9\u5F53\u524D\u8FDB\u5C55\u4E0E\u4E0B\u4E00\u6B65",
    reasons,
    waitingReason,
    nextCheckAt,
    primaryAction: unknown.length ? "reconcile" : needsAcceptance ? "review_result" : pendingReply || stale || conflict ? "review_feedback" : clarification ? "clarify" : "prepare_reminder",
    feedbackState,
    clarification,
    reminderEligible: active5 && eligible,
    notificationBasis,
    basis: followupFingerprint([evidenceBasis, meta, sent, unknown.map((x) => [x.id, x.reminderRun.status]), handlingState, nextCheckAt, due]),
    evidenceBasis,
    feedbackBasis,
    gateBasis,
    sources: refs,
    pendingReply,
    executionSourceIds: unknown.map((x) => x.id),
    active: active5,
    businessStates: { feedback: progress || text9(row.executionStatus), submission: text9(row.submissionStatus), professionalReview: text9(row.deliveryReview || row.reviewStatus), acceptance: text9(row.acceptanceStatus), node: text9(row.nodeStatus), syncApproval: "\u72EC\u7ACB\u5BA1\u6838\uFF0C\u5904\u7406\u72B6\u6001\u4E0D\u6388\u4E88\u540C\u6B65\u6279\u51C6" }
  };
}
function followupContext(p, s) {
  const row = s[p.kind].find((r) => r.id === p.targetId);
  const gates = p.projectIds.map((id2) => s.projects.find((r) => r.id === id2)).filter((p2) => !!p2).map((p2) => getProjectGates(s, p2).next?.date).filter(Boolean);
  return { sources: p.sources.map((r) => [r.id, r.fingerprint, r.available]), gateBasis: p.gateBasis, notificationBasis: p.notificationBasis, formalDates: followupFingerprint([row.checkAt, row.dueAt, row.plannedEnd, row.committed, row.deadline, ...gates].filter((v) => gateDate(v)).sort()) };
}
function applyFollowupOperation(input, op, now2 = Date.now()) {
  if (op.workspaceId !== input.workspaceId) fail4("\u5DE5\u4F5C\u533A\u4E0D\u5339\u914D");
  if (!op.requestId || op.requestId.length > 160 || !["take_over", "review_feedback", "reschedule"].includes(op.action)) fail4("\u5904\u7406\u64CD\u4F5C\u6216\u8BF7\u6C42\u6807\u8BC6\u65E0\u6548", 422);
  const key2 = "followup:" + input.workspaceId + ":" + op.requestId, fingerprint = canonical(op), receipt2 = input.receipts[key2];
  if (receipt2) {
    if (receipt2.fingerprint !== fingerprint) fail4("\u540C\u4E00\u8BF7\u6C42\u6807\u8BC6\u4E0D\u80FD\u6539\u53D8\u64CD\u4F5C\u5185\u5BB9");
    return input;
  }
  const p = buildFollowup(input, op, now2);
  if (p.basis !== op.expectedBasis) fail4("\u4E8B\u9879\u3001\u4F9D\u636E\u6216\u8DDF\u8FDB\u5B89\u6392\u5DF2\u53D8\u5316\uFF0C\u8BF7\u5237\u65B0\u540E\u518D\u64CD\u4F5C");
  if (!p.active) fail4("\u6B64\u4E8B\u9879\u5DF2\u4E0D\u5728\u5F53\u524D\u5904\u7406\u8303\u56F4");
  const topic = input.sources.find((row2) => row2.id === p.targetId && row2.workItem);
  if (p.kind === "sources" && topic) {
    const next2 = applyWorkItemOperation(input, { workspaceId: input.workspaceId, sourceId: topic.id, expectedVersion: topic.version, expectedBasis: workItemState(input, topic, now2).basis, requestId: "followup-" + followupFingerprint(op), action: op.action === "reschedule" ? "wait" : op.action === "review_feedback" ? "resume" : "take_over", reason: op.reason || "", nextCheckAt: op.nextCheckAt || "" }, new Date(now2).toISOString());
    next2.receipts[key2] = { fingerprint, result: { itemKey: p.itemKey, action: op.action } };
    return next2;
  }
  const next = structuredClone(input), row = next[p.kind].find((r) => r.id === p.targetId);
  const before = row.followupHandling || null, meta = before?.workspaceId === next.workspaceId ? { ...before } : { schemaVersion: 1, workspaceId: next.workspaceId };
  if (op.action === "take_over") meta.pickedUpAt = new Date(now2).toISOString();
  if (op.action === "review_feedback") {
    meta.reviewedFeedbackBasis = p.feedbackBasis;
    for (const proof of p.sources) {
      const source = next.sources.find((src) => src.id === proof.id);
      if (!source || !isCommentFeedback(source)) continue;
      const origin = canonicalFollowupRef(next, { kind: source.feedback.channel === "meegle-deliverable-comment" ? "deliverables" : "actions", targetId: source.feedback.targetId });
      if (origin.kind !== p.kind || origin.targetId !== p.targetId) continue;
      source.feedback.reviewedVersion = source.feedback.contentVersion;
      source.feedback.reviewedAt = new Date(now2).toISOString();
      source.version = (source.version || 1) + 1;
    }
  }
  if (op.action === "reschedule") {
    const at = feedbackTime(op.nextCheckAt);
    if (!at || !gateDate(op.nextCheckAt?.slice(0, 10)) || Date.parse(at) <= now2 || !text9(op.reason) || text9(op.reason).length > 600) fail4("\u8BF7\u586B\u5199\u542B\u65F6\u533A\u7684\u672A\u6765\u8DDF\u8FDB\u65F6\u95F4\u548C\u8C03\u6574\u7406\u7531", 422);
    meta.schedule = { at, reason: text9(op.reason), evidenceBasis: p.evidenceBasis, createdAt: new Date(now2).toISOString() };
  }
  meta.version = (meta.version || 0) + 1;
  row.followupHandling = meta;
  row.version = (row.version || 1) + 1;
  next.revision++;
  next.receipts[key2] = { fingerprint, result: { itemKey: p.itemKey, action: op.action } };
  next.audit.push({ id: key2, time: new Date(now2).toISOString(), operation: "followup." + op.action, objectId: row.id, actor: "\u672C\u4EBA", before, after: meta, revision: next.revision });
  return next;
}

// lib/work-item-brief.ts
var briefLabels = ["\u53D1\u751F\u4E86\u4EC0\u4E48", "\u6709\u4EC0\u4E48\u5F71\u54CD", "\u9700\u8981\u4F60\u505A\u4EC0\u4E48", "\u4F9D\u636E\u4E0E\u7F3A\u53E3"];
function parseSummaryBrief(value) {
  const matches = [...value.matchAll(/^(发生了什么|有什么影响|需要你做什么|依据与缺口)[：:]\s*/gm)];
  if (matches.length !== 4 || matches[0].index !== 0 || matches.some((match, i) => match[1] !== briefLabels[i])) return null;
  const parts = matches.map((match, i) => value.slice(match.index + match[0].length, matches[i + 1]?.index ?? value.length).trim());
  return parts.every(Boolean) ? { facts: parts[0], impact: parts[1], nextStep: parts[2], gap: parts[3] } : null;
}
var genericNext = (value) => !value.trim() || /^(由本人选择处置方式|请自行判断|请核实|待核实|持续关注)[。！!\s]*$/.test(value.trim());
var automaticTitle = (value) => /^采集整理\s*·/.test(value);
var documentLink = (value) => /^https:\/\/[^\s/]+\/(?:docx|wiki)\/[a-zA-Z0-9]+(?:[?#][^\s]*)?$/.test(value.trim());
function eventTime(value) {
  if (!value || !Number.isFinite(Date.parse(value))) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(value));
}
function workItemBrief(s, source) {
  const item = source.workItem, summary = String(item?.summary || source.intakeBatch?.summary || source.excerpt || "\u539F\u4EF6\u5DF2\u4FDD\u5B58\uFF0C\u5C1A\u672A\u5F62\u6210\u5185\u5BB9\u6458\u8981\u3002");
  const parsed = parseSummaryBrief(summary), locks = item?.human?.fields || [];
  const ids8 = item?.assessmentEvidence?.map((e) => e.sourceId) || item?.evidence?.map((e) => e.sourceId) || source.intakeBatch?.documents || [];
  const evidence = item || source.intakeBatch ? ids8.map((id2) => s.sources.find((row) => row.id === id2)) : [source];
  const rows2 = evidence.filter((row) => !!row && !row.archived && !row.intakeBatch && !row.workItem);
  const linkOnly = rows2.length > 0 && evidence.every((row) => !!row && !row.archived) && rows2.every((row) => documentLink(String(row.excerpt || "")) && !row.intakeDocument?.cloudDocument && !row.attachments?.length);
  const links = linkOnly ? [...new Set(rows2.map((row) => String(row.excerpt).trim()).filter((url) => {
    try {
      const host = new URL(url).hostname;
      return host.endsWith(".feishu.cn") || host.endsWith(".larksuite.com");
    } catch {
      return false;
    }
  }))] : [];
  let facts = parsed?.facts || summary, impact = String(item?.impact || parsed?.impact || "\u73B0\u6709\u6458\u8981\u672A\u8BF4\u660E\u5177\u4F53\u5F71\u54CD\uFF0C\u9700\u7ED3\u5408\u539F\u6587\u5224\u65AD\u3002");
  let nextStep = String(item?.nextStep || parsed?.nextStep || "");
  const gaps = [.../* @__PURE__ */ new Set([...parsed ? [parsed.gap] : [], ...item?.limitations || [], ...item?.triage?.gaps || []])];
  let title = source.title;
  if (linkOnly && (!item || item.nature === "reference") && !item?.pendingChange && !locks.length) {
    if (rows2.length === 1) {
      const row = rows2[0], who = row.author || "\u53D1\u9001\u4EBA\u672A\u8BB0\u5F55", when = eventTime(row.occurredAt || "");
      const place = String(row.title || "").replace(/\s*·\s*\d{4}-\d{2}-\d{2}T.*$/, "").trim();
      facts = `${when ? when + "\uFF0C" : ""}${who}\u5206\u4EAB\u4E86\u4E00\u6761\u6587\u6863\u94FE\u63A5${place ? "\uFF08\u6765\u6E90\uFF1A" + place + "\uFF09" : ""}\uFF0C\u6D88\u606F\u6CA1\u6709\u9644\u5185\u5BB9\u8BF4\u660E\u3002`;
      if (automaticTitle(title)) title = `${row.author ? row.author + "\u5206\u4EAB\u7684" : "\u6536\u5230\u7684"}\u6587\u6863\uFF1A\u6B63\u6587\u5F85\u8865\u8BFB`;
    } else {
      facts = `\u6536\u5230 ${links.length || rows2.length} \u6761\u6587\u6863\u94FE\u63A5\uFF0C\u6D88\u606F\u6CA1\u6709\u9644\u5185\u5BB9\u8BF4\u660E\uFF0C\u94FE\u63A5\u6B63\u6587\u5C1A\u672A\u8BFB\u5230\u3002`;
      if (automaticTitle(title)) title = "\u6536\u5230\u6587\u6863\u94FE\u63A5\uFF0C\u6B63\u6587\u5F85\u8865\u8BFB";
    }
    if (!item?.impact && !parsed?.impact) impact = "\u76EE\u524D\u65E0\u6CD5\u5224\u65AD\u6587\u6863\u662F\u5426\u6539\u53D8\u9879\u76EE\u8FDB\u5C55\u3001\u671F\u9650\u6216\u5DF2\u6709\u98CE\u9669\u3002";
  }
  if (linkOnly) gaps.push("\u5DF2\u8BFB\u5230\u94FE\u63A5\u6D88\u606F\uFF1B\u6587\u6863\u6807\u9898\u3001\u6B63\u6587\u53CA\u5177\u4F53\u529E\u7406\u8981\u6C42\u5C1A\u672A\u786E\u8BA4\u3002");
  if (genericNext(nextStep) && !locks.includes("nextStep")) nextStep = linkOnly ? "\u5EFA\u8BAE\u5148\u6253\u5F00\u539F\u6587\uFF0C\u786E\u8BA4\u662F\u5426\u65B0\u589E\u7ED3\u8BBA\u3001\u671F\u9650\u6216\u9700\u8981\u4F60\u529E\u7406\u7684\u8981\u6C42\uFF1B\u8BFB\u6E05\u524D\u6682\u4E0D\u8F6C\u4E3A\u5F85\u529E\u6216\u98CE\u9669\u3002" : item?.triage?.necessary === false ? "\u5F53\u524D\u65E0\u9700\u4F60\u529E\u7406\uFF0C\u7559\u5B58\u8D44\u6599\uFF1B\u51FA\u73B0\u65B0\u7684\u660E\u786E\u529E\u7406\u8981\u6C42\u65F6\u518D\u5904\u7406\u3002" : "\u5148\u6838\u5BF9\u4E0B\u65B9\u539F\u6587\u4E2D\u7684\u5177\u4F53\u529E\u7406\u8981\u6C42\uFF1B\u73B0\u6709\u6458\u8981\u5C1A\u4E0D\u8DB3\u4EE5\u7ED9\u51FA\u5904\u7406\u5EFA\u8BAE\u3002";
  if (automaticTitle(title) && parsed) title = parsed.facts.split(/[。\n]/)[0].slice(0, 70);
  return { title, facts, impact, nextStep, gaps: [...new Set(gaps)], links, linkOnly };
}

// lib/work-calendar.ts
var chinaDay = (at) => new Date(new Date(at).getTime() + 8 * 36e5).toISOString().slice(0, 10);
var chinaTime = (at) => new Date(new Date(at).getTime() + 8 * 36e5).toISOString().slice(11, 16);
var chinaInstant = (day, time = "09:00") => (/* @__PURE__ */ new Date(day + "T" + time + ":00+08:00")).toISOString();
var addDays = (day, n) => new Date(Date.parse(day + "T12:00:00Z") + n * 864e5).toISOString().slice(0, 10);
function validDay(day) {
  return typeof day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(day) && Number.isFinite(Date.parse(day)) && new Date(day).toISOString().slice(0, 10) === day;
}
function validateWorkCalendar(value) {
  if (!value?.id || !Number.isInteger(value.revision) || value.revision < 1 || !value.source?.trim() || !Number.isFinite(Date.parse(value.verifiedAt)) || !validDay(value.from) || !validDay(value.through) || value.from > value.through || !value.days || Object.entries(value.days).some(([day, work]) => !validDay(day) || typeof work !== "boolean" || day < value.from || day > value.through)) throw Object.assign(Error("\u5DE5\u4F5C\u65E5\u5386\u9700\u8981\u6709\u6548\u8303\u56F4\u3001\u9010\u65E5\u914D\u7F6E\u548C\u6838\u5BF9\u6765\u6E90"), { status: 422 });
  return value;
}
function workingDay(calendar, day) {
  if (!calendar || day < calendar.from || day > calendar.through || !Object.hasOwn(calendar.days, day)) return null;
  return calendar.days[day];
}
function nextWorkMorning(calendar, at, includeToday = false) {
  const day = chinaDay(at);
  for (let n = includeToday ? 0 : 1; n < 370; n++) {
    const date4 = addDays(day, n), work = workingDay(calendar, date4);
    if (work === null) return null;
    if (work && (n > 0 || Date.parse(chinaInstant(date4)) > new Date(at).getTime())) return chinaInstant(date4);
  }
  return null;
}
function lastWorkdayOfWeek(calendar, day) {
  const weekday = (/* @__PURE__ */ new Date(day + "T12:00:00Z")).getUTCDay(), monday = addDays(day, -((weekday + 6) % 7));
  let last = "";
  for (let n = 0; n < 7; n++) {
    const date4 = addDays(monday, n), work = workingDay(calendar, date4);
    if (work === null) return null;
    if (work) last = date4;
  }
  return last;
}

// lib/work-item-core.ts
var fail5 = (message, status2 = 422) => {
  throw Object.assign(Error(message), { status: status2 });
};
var coreDigest = (value) => stableHash(JSON.stringify(value)) + stableHash("core:" + JSON.stringify(value));
var coreProofFingerprint = (row) => coreDigest([row.excerpt || "", [...row.attachments || [], ...row.intakeDocument?.images || []].map((a) => [a.id, a.sha256]), !!row.archived, !!row.personalMessage?.deleted, !!row.caseChat?.raw?.deleted, !!row.inputEnvelope?.effectWithdrawn]);
var closed2 = (row) => {
  const item = row.workItem, life = item.p1?.lifecycle?.state;
  if (life) return life === "closed";
  return item.core?.admission === "withdrawn" || !item.pendingChange && (item.handling?.state === "handled" || item.nature === "risk" && ["resolved", "dismissed"].includes(item.reviews?.at(-1)?.decision));
};
function coreState(row) {
  const defaults2 = {
    schemaVersion: 1,
    admission: "managed",
    priority: { base: row.workItem.urgency === "urgent" ? "P1" : "P2", owner: "legacy", epoch: 0, reason: "\u6CBF\u7528\u5DF2\u6709\u4E8B\u9879\uFF0C\u7B49\u5F85\u6709\u6765\u6E90\u7684\u7B49\u7EA7\u5224\u65AD" },
    cycle: { id: coreDigest([row.id, "initial"]), needKey: row.id, count: 0, epoch: 0, escalated: false, temp: null, notices: [] },
    need: { key: row.id, actor: "self", description: row.workItem.nextStep || row.workItem.summary, arranged: false },
    processedEvidence: [],
    history: [],
    checks: {},
    pause: null,
    assessment: null
  }, current = row.workItem.core;
  return current ? { ...defaults2, ...current, priority: { ...defaults2.priority, ...current.priority }, cycle: { ...defaults2.cycle, ...current.cycle }, need: { ...defaults2.need, ...current.need }, checks: { ...current.checks }, history: current.history || [], processedEvidence: current.processedEvidence || [] } : defaults2;
}
function ensureCore(row) {
  const value = coreState(row);
  if (row.workItem.core) Object.assign(row.workItem.core, value);
  else row.workItem.core = structuredClone(value);
  return row.workItem.core;
}
function effectivePriority(row) {
  const c = coreState(row);
  return c.cycle.temp && c.cycle.temp.priorityEpoch === c.priority.epoch ? c.cycle.temp.level : c.priority.base;
}
function validCoreProofs(s, proof) {
  return Array.isArray(proof) && proof.length > 0 && proof.every((p) => {
    const row = s.sources.find((r) => r.id === p.sourceId && !r.workItem && !r.archived);
    return !!row && !row.inputEnvelope?.effectWithdrawn && !row.personalMessage?.deleted && !row.caseChat?.raw?.deleted && coreProofFingerprint(row) === p.fingerprint && !!p.quote?.trim() && (p.kind === "image" ? !!p.attachmentId && [...row.attachments || [], ...row.intakeDocument?.images || []].some((a) => a.id === p.attachmentId) : String(row.excerpt || "").includes(p.quote));
  });
}
function coreReopenProposal(s, row) {
  const c = coreState(row), proposal = c.reopenProposal;
  if (!proposal?.id || !Number.isFinite(Date.parse(proposal.at)) || !closed2(row) || !validCoreProofs(s, proposal.proof)) return null;
  const decidedAt = Math.max(Date.parse(row.workItem.p1?.lifecycle?.at || "") || 0, Date.parse(c.instructionAt?.lifecycle || "") || 0);
  return decidedAt > Date.parse(proposal.at) ? null : proposal;
}
function reconcileCoreReopenProposal(s, row, at, { decided = false } = {}) {
  if (!row.workItem.core?.reopenProposal) return;
  const c = ensureCore(row);
  if (c.reopenProposal && (decided || !coreReopenProposal(s, row))) {
    c.history.push({ at, kind: "reopen-proposal-retired", proposal: structuredClone(c.reopenProposal), reason: decided ? "\u672C\u6B21\u51B3\u5B9A\u5DF2\u5904\u7406" : "\u5F53\u524D\u72B6\u6001\u6216\u6765\u6E90\u4E0D\u518D\u652F\u6301\u5F85\u5BA1" });
    c.reopenProposal = null;
    if (c.deferredNotification?.kind === "review") c.deferredNotification = null;
  }
}
function treatmentEvidenceKey(s, proof) {
  return coreDigest(proof.map((p) => {
    let source = s.sources.find((r) => r.id === p.sourceId);
    const seen = /* @__PURE__ */ new Set();
    while (source?.intakeDocument?.originalSourceId && !seen.has(source.id)) {
      seen.add(source.id);
      const original = s.sources.find((r) => r.id === source.intakeDocument.originalSourceId);
      if (!original) break;
      source = original;
    }
    const message = source?.personalMessage || source?.caseChat || source?.riskEvidence?.message;
    const identity = message?.messageId ? [message.scope, message.accountId, message.messageId] : source?.id || p.sourceId;
    const image = p.kind === "image" ? source?.attachments?.find((a) => a.id === p.attachmentId)?.sha256 || source?.intakeDocument?.inputHash || p.attachmentId : null;
    return image ? ["image", image] : [identity, null, p.quote];
  }).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))));
}
var cycleReset = (c) => {
  c.cycle.count = 0;
  c.cycle.epoch++;
};
function applyNeedAssessment(s, row, a, at) {
  if (!a?.id || !a.needKey?.trim() || !a.description?.trim() || !Number.isFinite(Date.parse(a.occurredAt)) || !validCoreProofs(s, a.proof) || !["self", "colleague", "none"].includes(a.actor) || !["P1", "P2", "P3"].includes(a.priority) || !a.priorityReason?.trim() || !Array.isArray(a.remainingActions) || !Array.isArray(a.steps)) fail5("\u63A8\u8FDB\u5224\u65AD\u7F3A\u5C11\u6709\u6548\u6765\u6E90\u3001\u5F53\u524D\u9700\u8981\u6216\u8D23\u4EFB");
  for (const key2 of ["actualAction", "substantiveProgress", "executableArrangement", "currentHandled", "noIntervention", "goalSatisfied", "urgent", "suggestP0"]) if (typeof a[key2] !== "boolean") fail5("\u63A8\u8FDB\u5224\u65AD\u683C\u5F0F\u65E0\u6548");
  if (new Set(a.steps.map((step) => step.id)).size !== a.steps.length || a.steps.some((step) => !step.id || !step.title || !["needed", "waiting", "done"].includes(step.state) || step.ownerId && !s.people.some((p) => p.id === step.ownerId && !p.archived) || !step.sourceIds.length || step.sourceIds.some((id2) => !a.proof.some((p) => p.sourceId === id2)))) fail5("\u6B65\u9AA4\u7F3A\u5C11\u6709\u6548\u8D23\u4EFB\u6216\u4F9D\u636E");
  const c = ensureCore(row), evidenceKey = treatmentEvidenceKey(s, a.proof);
  if (c.assessment?.id === a.id) return false;
  if (c.assessment && !a.temporal && a.occurredAt < (c.assessment.sourceOccurredAt || c.assessment.occurredAt)) {
    c.history.push({ at, kind: "late-assessment", id: a.id, proof: a.proof });
    c.checks = { ...c.checks, needsRecheck: true, reason: "\u8FDF\u5230\u8D44\u6599\u5DF2\u4FDD\u7559\uFF0C\u9700\u7ED3\u5408\u8F83\u65B0\u4E8B\u5B9E\u91CD\u65B0\u6838\u5BF9" };
    return true;
  }
  const fresh = !c.processedEvidence.includes(evidenceKey), temporalNew = !!a.temporal?.key && !(c.temporalKeys || []).includes(a.temporal.key), reassessmentNew = !!a.reassessmentKey && a.reassessmentKey !== c.reassessedKey;
  if (!fresh && !temporalNew && !reassessmentNew) {
    if (c.assessment?.evidenceKey === evidenceKey) c.assessment.proof = structuredClone(a.proof);
    c.checks = { ...c.checks, lastSuccess: at, error: "" };
    return true;
  }
  const newProof = a.proof.filter((p) => !(c.assessment?.proof || []).some((old) => old.sourceId === p.sourceId && old.quote === p.quote));
  const acknowledgementOnly = newProof.length > 0 && newProof.every((p) => p.kind !== "image" && /^(?:收到|好的|好|了解|知道了|在处理|正在处理|继续待定|晚点处理|条件还不具备|暂时没有新进展|没有新进展)+$/.test(p.quote.replace(/[，。！!,.、\s]/g, "")));
  if (acknowledgementOnly && !temporalNew && !reassessmentNew) {
    if (fresh) c.processedEvidence.push(evidenceKey);
    c.history.push({ at, kind: "reply-recorded", reason: "\u5DF2\u56DE\u590D\uFF1B\u672A\u636E\u6B64\u6E05\u96F6\u3001\u505C\u50AC\u3001\u6539\u7EA7\u6216\u7ED3\u675F", proof: a.proof });
    c.checks = { ...c.checks, lastSuccess: at, error: "" };
    return true;
  }
  const wasArranged = c.need.arranged, changedNeed = c.need.key !== a.needKey;
  if (changedNeed) {
    c.history.push({ at, kind: "need-cycle", previous: structuredClone(c.cycle), reason: a.description, proof: a.proof });
    c.cycle = { id: coreDigest([row.id, a.needKey, evidenceKey]), needKey: a.needKey, count: 0, epoch: c.cycle.epoch + 1, escalated: false, temp: null, notices: [] };
  } else if (wasArranged && !a.currentHandled && !a.noIntervention) {
    c.cycle = { id: coreDigest([row.id, a.needKey, evidenceKey]), needKey: a.needKey, count: 0, epoch: c.cycle.epoch + 1, escalated: false, temp: null, notices: [] };
  }
  const timing = itemTiming(s, row, at), hasTime = [timing.check, timing.completion, ...timing.requirements].some((n) => n.state === "scheduled" && !n.completedAt && !n.needsReview && (n.effectiveAt ? Date.parse(n.effectiveAt) > Date.parse(at) : !!n.date && n.date >= chinaDay(at)));
  const effective = fresh && (a.actualAction || a.substantiveProgress || a.executableArrangement);
  if (effective) cycleReset(c);
  const arranged = a.noIntervention || a.currentHandled && hasTime;
  if (arranged) c.cycle.temp = null;
  c.need = { key: a.needKey, actor: a.actor, description: a.description, arranged, remainingActions: a.remainingActions, at };
  if (c.priority.owner !== "manual" && c.priority.base !== a.priority) {
    c.priority = { base: a.priority, owner: "auto", reason: a.priorityReason, at, epoch: c.priority.epoch + 1 };
    c.cycle.temp = null;
  }
  c.steps = structuredClone(a.steps);
  c.assessment = { ...structuredClone(a), evidenceKey, at };
  if (fresh) c.processedEvidence.push(evidenceKey);
  if (temporalNew) c.temporalKeys = [...c.temporalKeys || [], a.temporal.key];
  if (reassessmentNew) c.reassessedKey = a.reassessmentKey;
  if (c.priority.base === "P0" && c.fullFocus && !a.noIntervention && (a.substantiveProgress || changedNeed || a.urgent)) c.p0Event = { key: evidenceKey, at, reason: a.description };
  c.checks = { ...c.checks, lastSuccess: at, error: "", coverage: "\u5DF2\u6838\u5BF9\u672C\u6B21\u5B9E\u9645\u53EF\u8BFB\u6765\u6E90" };
  c.history.push({ at, kind: "assessment", id: a.id, effective, arranged, proof: a.proof });
  const target = row.workItem.businessTarget?.kind === "deliverables" ? s.deliverables.find((d) => d.id === row.workItem.businessTarget.id && !d.archived) : null;
  const deliverySatisfied = !row.workItem.nativeFollowup || !!target && observedDeliveryReview(target) === "\u5DF2\u5BA1\u6838" && target.flowNodeIds?.some((id2) => s.flowNodes.some((n) => n.id === id2 && !n.archived));
  const autoEnd = a.goalSatisfied && a.remainingActions.length === 0 && a.steps.every((step) => step.state === "done") && !row.workItem.pendingChange && deliverySatisfied;
  if (autoEnd && !closed2(row)) {
    c.admission = c.admission === "candidate" ? "withdrawn" : c.admission;
    c.cycle.temp = null;
    row.workItem.p1 ||= {};
    row.workItem.p1.lifecycle = { state: "closed", owner: "auto", reason: c.admission === "withdrawn" ? "\u5DF2\u89E3\u51B3\uFF0C\u65E0\u9700\u7EB3\u5165" : "\u76EE\u6807\u5DF2\u6EE1\u8DB3\uFF0C\u65E0\u5269\u4F59\u52A8\u4F5C", at, evidenceKey };
    c.resultNotice = { id: coreDigest([row.id, evidenceKey, "closed"]), text: row.workItem.p1.lifecycle.reason, at };
  } else if (!autoEnd && closed2(row) && row.workItem.p1?.lifecycle?.owner === "auto" && fresh) {
    row.workItem.p1.lifecycle = { state: "open", owner: "auto", reason: "\u65B0\u7684\u6709\u6548\u8BC1\u636E\u8868\u660E\u4ECD\u6709\u540E\u7EED", at, evidenceKey };
    if (c.admission === "withdrawn") c.admission = "candidate";
    if (row.workItem.p1.check?.effectiveAt && Date.parse(row.workItem.p1.check.effectiveAt) <= Date.parse(at)) row.workItem.p1.check.needsReview = true;
  } else if (!autoEnd && closed2(row) && fresh) {
    c.reopenProposal = { id: coreDigest([row.id, evidenceKey, "reopen"]), reason: a.description, proof: a.proof, at };
  }
  reconcileCoreReopenProposal(s, row, at, { decided: autoEnd });
  return true;
}
function applyCoreDecision(s, row, op, at, calendar, eventAt = at) {
  const c = ensureCore(row);
  if (op.action === "core-admit") {
    if (c.admission !== "candidate") fail5("\u5F53\u524D\u4E0D\u662F\u5F85\u7EB3\u5165\u5019\u9009", 409);
    c.admission = "managed";
    c.admittedAt = at;
  } else if (op.action === "core-priority") {
    if (!["P0", "P1", "P2", "P3"].includes(op.priority)) fail5("\u8BF7\u9009\u62E9\u6709\u6548\u4F18\u5148\u7EA7");
    c.priority = { base: op.priority, owner: "manual", at, reason: op.reason || "\u672C\u4EBA\u6307\u5B9A", epoch: c.priority.epoch + 1 };
    c.cycle.temp = null;
    c.fullFocus = op.priority === "P0" && op.fullFocus === true;
  } else if (op.action === "core-pause") {
    if (op.until && (!Number.isFinite(Date.parse(op.until)) || Date.parse(op.until) <= Date.parse(at))) fail5("\u6062\u590D\u65F6\u95F4\u9700\u8981\u5728\u5F53\u524D\u65F6\u95F4\u4E4B\u540E");
    const until = op.manualResume ? "" : op.until || nextWorkMorning(calendar, at);
    c.pause = { at, until: until || "", manual: op.manualResume === true, needsCalendar: !op.manualResume && !until, reason: op.reason || "\u672C\u4EBA\u6682\u505C" };
    cycleReset(c);
  } else if (op.action === "core-resume") {
    c.pause = null;
    cycleReset(c);
    c.resumedAt = at;
  } else if (op.action === "core-weekly") {
    if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(op.time || "") || op.weekday !== void 0 && (!Number.isInteger(op.weekday) || op.weekday < 1 || op.weekday > 7)) fail5("\u5468\u5EA6\u68C0\u67E5\u9700\u8981\u6709\u6548\u65F6\u95F4\u548C\u661F\u671F");
    c.weekly = { time: op.time, weekday: op.weekday ?? null, at };
  } else fail5("\u4E0D\u652F\u6301\u7684\u63A8\u8FDB\u64CD\u4F5C");
  const decisionKey = { "core-admit": "admission", "core-priority": "priority", "core-pause": "pause", "core-resume": "pause", "core-weekly": "weekly" }[op.action];
  c.instructionAt = { ...c.instructionAt || {}, [decisionKey]: eventAt };
  c.lastInstructionAt = Object.values(c.instructionAt).sort().at(-1);
  c.history.push({ at, kind: op.action, reason: op.reason || "", priority: c.priority.base, pause: c.pause });
}
function resumeDuePause(row, calendar, at) {
  const c = ensureCore(row);
  if (!c.pause || c.pause.manual) return false;
  if (c.pause.needsCalendar) {
    const until = nextWorkMorning(calendar, c.pause.at);
    if (!until) return false;
    c.pause.until = until;
    c.pause.needsCalendar = false;
  }
  if (Date.parse(c.pause.until) > Date.parse(at)) return false;
  c.history.push({ at, kind: "pause-resumed", pause: c.pause });
  c.pause = null;
  cycleReset(c);
  c.resumedAt = at;
  return true;
}
function coreTemporalTrigger(s, row, at) {
  if (closed2(row) || row.archived || row.workItem.disposition?.state === "ignored") return null;
  const c = coreState(row), timing = itemTiming(s, row, at), check = timing.check, checkKey = coreDigest(check);
  if (check.state === "scheduled" && !check.completedAt && !check.needsReview && check.effectiveAt && Date.parse(check.effectiveAt) <= Date.parse(at) && !c.checkedArrangements?.includes(checkKey)) return { kind: "check", key: "check:" + checkKey, at };
  if (timing.completionDue.length) return { kind: "deadline", key: "deadline:" + coreDigest(timing.completionDue.map((v) => [v.node.date, v.node.time, v.node.origin, v.label])), at };
  return null;
}
function coreNotice(s, row, calendar, at, { recovery = false } = {}) {
  const c = coreState(row), day = chinaDay(at), time = chinaTime(at), priority = effectivePriority(row), working = workingDay(calendar, day), timing = itemTiming(s, row, at);
  const quiet = (reason, extra = {}) => ({ eligible: false, reason, ...extra });
  if (s.workspaceType === "restored" || row.archived || row.workItem.mergedIntoId || row.workItem.disposition?.state === "ignored") return quiet("\u5F53\u524D\u5DE5\u4F5C\u533A\u6216\u4E8B\u9879\u4E0D\u53C2\u4E0E\u81EA\u52A8\u6267\u884C");
  const check = timing.check, explicit = !closed2(row) && check.state === "scheduled" && !check.completedAt && !check.needsReview && !!check.effectiveAt && Date.parse(check.effectiveAt) <= Date.parse(at) && !c.checkedArrangements?.includes(coreDigest(check));
  const urgent = (!!c.assessment?.urgent || c.dependencyUrgent === true) && !closed2(row), suggestP0 = !closed2(row) && !!c.assessment?.suggestP0 && !c.fullFocus;
  const firstP0 = suggestP0 && !c.p0NotifiedEvidence?.includes(c.assessment.evidenceKey);
  const focusChange = !closed2(row) && priority === "P0" && c.fullFocus && c.p0Event && !c.p0ChangeNotified?.includes(c.p0Event.key);
  const result = closed2(row) && c.resultNotice && !c.resultNotice.deliveredAt;
  const reopenReview = coreReopenProposal(s, row), reviewQueue = c.admission === "candidate" || row.workItem.pendingChange || reopenReview;
  if (!["action", "risk", "decision"].includes(row.workItem.nature) && !row.workItem.manualAttention && !explicit && !reviewQueue && !result) return quiet("\u80CC\u666F\u8D44\u6599\u4FDD\u7559\uFF0C\u4E0D\u751F\u6210\u5E38\u89C4\u50AC\u529E");
  if (closed2(row) && !result && !reopenReview) return quiet("\u672C\u5730\u4E8B\u9879\u5DF2\u7ED3\u675F");
  if (c.pause && !urgent && !result) return quiet(c.pause.needsCalendar ? "\u6682\u505C\u4E2D\uFF1B\u6062\u590D\u65F6\u95F4\u6240\u9700\u5DE5\u4F5C\u65E5\u5386\u5C1A\u672A\u6838\u5B9E" : "\u5DF2\u6682\u505C\u5E38\u89C4\u63D0\u9192");
  if (!result && !explicit && !urgent && !suggestP0 && !reviewQueue && (c.need.arranged || c.need.actor !== "self")) return quiet("\u5F53\u524D\u65E0\u9700\u672C\u4EBA\u4ECB\u5165\uFF1B\u7EE7\u7EED\u8BB0\u5F55\u5BF9\u5E94\u8D23\u4EFB\u6B65\u9AA4");
  if (!result && !explicit && !urgent && !suggestP0 && !focusChange && !reopenReview && priority === "P0" && c.fullFocus) return quiet("\u5DF2\u660E\u786E\u5168\u529B\u5904\u7406\uFF0C\u6709\u5B9E\u8D28\u53D8\u5316\u6216\u660E\u786E\u68C0\u67E5\u518D\u901A\u77E5");
  const deferred = c.deferredNotification, usableDeferred = deferred && deferred.cycleId === c.cycle.id && deferred.cycleEpoch === c.cycle.epoch && deferred.priorityEpoch === c.priority.epoch;
  let slot = "", kind = "regular";
  if (result) {
    slot = "result:" + c.resultNotice.id;
    kind = "result";
  } else if (reopenReview) {
    slot = day + ":09:00";
    kind = "review";
  } else if (explicit) {
    slot = "check:" + coreDigest(check);
    kind = "explicit";
  } else if ((urgent || firstP0) && !c.urgentNotifiedEvidence?.includes(c.assessment?.evidenceKey || c.cycle.id)) {
    slot = "urgent:" + (c.assessment?.evidenceKey || c.cycle.id);
    kind = "urgent";
  } else if (focusChange) {
    slot = "change:" + c.p0Event.key;
    kind = "material";
  } else if (usableDeferred) {
    const until = deferred.until || nextWorkMorning(calendar, deferred.createdAt, chinaTime(deferred.createdAt) < "09:00");
    if (!until) return quiet("\u5EF6\u671F\u901A\u77E5\u6240\u9700\u5DE5\u4F5C\u65E5\u5386\u5C1A\u672A\u6838\u5B9E", { calendarGap: true });
    if (Date.parse(until) > Date.parse(at)) return quiet("\u666E\u901A\u901A\u77E5\u7B49\u5F85\u4E0B\u4E00\u5B9E\u9645\u5DE5\u4F5C\u65F6\u6BB5", { deferredUntil: until });
    slot = deferred.slot;
    kind = deferred.kind;
  } else if (recovery && priority === "P1") {
    slot = day + ":" + (time >= "14:00" ? "14:00" : "09:00");
    kind = "recovery";
  } else if (reviewQueue) {
    slot = day + ":" + (suggestP0 && time >= "14:00" ? "14:00" : "09:00");
    kind = "review";
  } else if (priority === "P3") {
    const weekday = ((/* @__PURE__ */ new Date(day + "T12:00:00Z")).getUTCDay() + 6) % 7 + 1, last = lastWorkdayOfWeek(calendar, day), scheduled = c.weekly?.weekday ? weekday === c.weekly.weekday : last === day;
    if (last === null && !c.weekly?.weekday) return quiet("\u672C\u5468\u5B8C\u6574\u5DE5\u4F5C\u65E5\u5386\u5C1A\u672A\u6838\u5B9E", { calendarGap: true });
    if (!scheduled || time < (c.weekly?.time || "14:00")) return quiet("\u5C1A\u672A\u5230\u672C\u5468\u590D\u67E5\u65F6\u95F4");
    slot = day + ":" + (c.weekly?.time || "14:00");
  } else if (time >= "09:00") slot = day + ":" + ((priority === "P1" || suggestP0 || priority === "P0") && time >= "14:00" ? "14:00" : "09:00");
  if (!slot) return quiet("\u5C1A\u672A\u5230\u5408\u6CD5\u63D0\u9192\u65F6\u95F4");
  const id2 = coreDigest([row.id, c.cycle.id, c.cycle.epoch, slot, ...kind === "review" && reopenReview ? [reopenReview.id] : []]);
  if ((c.deliveredSlots || []).includes(c.cycle.id + ":" + slot) || (c.deliveredSlots || []).includes(slot) || (c.cycle.notices || []).includes(id2)) return quiet("\u672C\u8F6E\u5DF2\u53D6\u5F97\u901A\u77E5\u56DE\u6267");
  const counts = !result && c.admission === "managed" && c.need.actor === "self" && !c.need.arranged && !closed2(row) && !["review", "material"].includes(kind);
  if (!explicit && !urgent && !firstP0) {
    if (working === null) return quiet("\u5DE5\u4F5C\u65E5\u5386\u5C1A\u672A\u6838\u5B9E", { calendarGap: true });
    if (!working || time < "09:00" || time >= "18:00") {
      const until = nextWorkMorning(calendar, at, time < "09:00");
      return quiet("\u666E\u901A\u901A\u77E5\u5EF6\u81F3\u4E0B\u4E00\u5B9E\u9645\u5DE5\u4F5C\u65E5 9:00", { deferredUntil: until, deferredNotification: { slot, kind, until, cycleId: c.cycle.id, cycleEpoch: c.cycle.epoch, priorityEpoch: c.priority.epoch, createdAt: deferred?.createdAt || at } });
    }
  }
  return { eligible: true, id: id2, slot, kind, counts, cycleId: c.cycle.id, cycleEpoch: c.cycle.epoch, priorityEpoch: c.priority.epoch, priority, assessmentKey: c.assessment?.evidenceKey || c.cycle.id, checkKey: explicit ? coreDigest(check) : "", reopenProposalId: kind === "review" ? reopenReview?.id || "" : "", reason: result ? c.resultNotice.text : reopenReview ? "\u91CD\u65B0\u6253\u5F00\u5F85\u5BA1\u6838\uFF1A" + reopenReview.reason : c.need.description, title: row.title, at };
}
function countCoreNotice(row, notice, at) {
  const c = ensureCore(row);
  c.deliveryHistory ||= [];
  if (c.deliveryHistory.some((x) => x.id === notice.id)) return false;
  const current = !closed2(row) && !c.pause && notice.cycleId === c.cycle.id && notice.cycleEpoch === c.cycle.epoch && notice.priorityEpoch === c.priority.epoch;
  const counted = current && notice.counts && c.admission === "managed" && c.need.actor === "self" && !c.need.arranged;
  c.deliveryHistory.push({ id: notice.id, slot: notice.slot, at, counted, qualified: notice.counts, cycleId: notice.cycleId, cycleEpoch: notice.cycleEpoch, priorityEpoch: notice.priorityEpoch, reason: counted ? "\u6709\u6548\u63D0\u9192" : "\u7ED3\u679C\u901A\u77E5\u3001\u65E0\u9700\u4ECB\u5165\u6216\u671F\u95F4\u51B3\u5B9A\u5DF2\u53D8\u5316" });
  c.deliveredSlots = [...c.deliveredSlots || [], notice.cycleId + ":" + notice.slot];
  c.cycle.notices.push(notice.id);
  if (["explicit", "urgent"].includes(notice.kind)) c.deliveredSlots.push(notice.cycleId + ":" + chinaDay(at) + ":" + (["P0", "P1"].includes(effectivePriority(row)) && chinaTime(at) >= "14:00" ? "14:00" : "09:00"));
  if (c.deferredNotification?.slot === notice.slot) c.deferredNotification = null;
  if (notice.kind === "result" && c.resultNotice?.id === notice.slot.slice(7)) c.resultNotice.deliveredAt = at;
  if (notice.checkKey) c.checkedArrangements = [...c.checkedArrangements || [], notice.checkKey];
  if (notice.kind === "urgent") {
    c.urgentNotifiedEvidence = [...c.urgentNotifiedEvidence || [], notice.assessmentKey];
    c.p0NotifiedEvidence = [...c.p0NotifiedEvidence || [], notice.assessmentKey];
  }
  if (notice.kind === "material") c.p0ChangeNotified = [...c.p0ChangeNotified || [], notice.slot.slice("change:".length)];
  if (counted) {
    c.cycle.count++;
    if (c.cycle.count >= 3 && !c.cycle.escalated) {
      c.cycle.escalated = true;
      c.cycle.escalationEpoch = c.priority.epoch;
      const p = effectivePriority(row);
      if (p === "P3" || p === "P2") c.cycle.temp = { level: p === "P3" ? "P2" : "P1", priorityEpoch: c.priority.epoch, at, reason: "\u540C\u4E00\u9700\u8981\u7B2C\u4E09\u6B21\u6709\u6548\u63D0\u9192" };
    }
  }
  return true;
}
function invalidateCoreDerivations(s, row, at, reason) {
  const c = ensureCore(row);
  c.checks = { ...c.checks, needsRecheck: true, reason, recheckKey: coreDigest([row.id, reason, at]) };
  if (c.assessment && !validCoreProofs(s, c.assessment.proof)) {
    c.history.push({ at, kind: "assessment-invalidated", assessment: structuredClone(c.assessment), reason });
    const escalationEpoch = c.cycle.escalationEpoch ?? c.cycle.temp?.priorityEpoch;
    c.assessment = null;
    c.need.arranged = false;
    c.cycle.temp = null;
    const lastValid = c.history.filter((e) => e.kind === "assessment" && e.effective && validCoreProofs(s, e.proof) || ["core-pause", "core-resume", "pause-resumed"].includes(e.kind)).map((e) => e.at).sort().at(-1) || "";
    const count = (c.deliveryHistory || []).filter((n) => n.counted && n.cycleId === c.cycle.id && n.at > lastValid).length;
    c.cycle.count = count;
    c.cycle.epoch++;
    if (count >= 3 && c.cycle.escalated && escalationEpoch === c.priority.epoch && ["P2", "P3"].includes(c.priority.base)) c.cycle.temp = { level: c.priority.base === "P3" ? "P2" : "P1", priorityEpoch: c.priority.epoch, at, reason: "\u6309\u4ECD\u6709\u6548\u7684\u53D1\u9001\u4E8B\u5B9E\u590D\u6838\u4E34\u65F6\u50AC\u529E\u7B49\u7EA7" };
  }
  for (const source of s.sources) if (source.reminderRun?.core && source.reminderRun.items.some((i) => i.workItemId === row.id)) {
    for (const item of source.reminderRun.items.filter((i) => i.workItemId === row.id)) item.needsRecheck = true;
  }
  c.history.push({ at, kind: "correction-recheck", reason });
  reconcileCoreReopenProposal(s, row, at);
}

// lib/work-items.ts
var workItemNatures = ["progress", "action", "risk", "decision", "result", "reference", "noise"];
var workItemLabels = { progress: "\u8FDB\u5C55\u53CD\u9988", action: "\u5F85\u529E", risk: "\u98CE\u9669\u5F85\u6838\u5B9E", decision: "\u5F85\u51B3\u7B56", result: "\u6210\u679C\u8D44\u6599", reference: "\u80CC\u666F\u8D44\u6599", noise: "\u65E0\u9700\u5904\u7406" };
var digest2 = (value) => {
  const text15 = JSON.stringify(value);
  return stableHash(text15) + stableHash("work-items:" + text15) + stableHash(text15 + ":evidence");
};
function fail6(message, status2 = 422) {
  throw Object.assign(new Error(message), { status: status2 });
}
var unique3 = (values) => [...new Set(values)];
var active2 = (source) => !source.archived && !source.workItem?.mergedIntoId;
var bounded2 = (value, limit) => typeof value === "string" && value.length <= limit;
function workSourceOriginal(s, source, index) {
  const seen = /* @__PURE__ */ new Set();
  let current = source;
  while (current.intakeDocument?.originalSourceId && !seen.has(current.id)) {
    seen.add(current.id);
    const original = index ? index.get(current.intakeDocument.originalSourceId) : s.sources.find((row) => row.id === current.intakeDocument.originalSourceId);
    if (!original) break;
    current = original;
  }
  return current;
}
function workSourceKey(s, source, index) {
  const original = workSourceOriginal(s, source, index), message = original.personalMessage || original.caseChat;
  return message?.scope && message.accountId && message.messageId ? "message:" + JSON.stringify([message.scope, message.accountId, message.messageId]) : "source:" + original.id;
}
function workSourceFingerprint(s, source) {
  const original = workSourceOriginal(s, source);
  return digest2([
    source.excerpt || "",
    !!original.archived,
    !!original.personalMessage?.deleted,
    !!original.caseChat?.raw?.deleted,
    (source.attachments || []).map((a) => [a.id, a.sha256]),
    source.riskEvidence?.complete === false || source.intakeDocument?.complete === false
  ]);
}
function workEvidenceSources(s, sourceIds) {
  const groups = /* @__PURE__ */ new Map();
  for (const id2 of sourceIds) {
    const source = s.sources.find((row) => row.id === id2);
    if (!source) continue;
    const key2 = workSourceKey(s, source);
    groups.set(key2, [...groups.get(key2) || [], source]);
  }
  return [...groups.values()].map((rows2) => rows2.sort((a, b) => String(b.updatedAt || b.collectedAt || "").localeCompare(String(a.updatedAt || a.collectedAt || "")) || Number(!!b.intakeDocument) - Number(!!a.intakeDocument) || a.id.localeCompare(b.id))[0]);
}
function sourceWorkItems(s, sourceId) {
  const original = s.sources.find((row) => row.id === sourceId), key2 = original ? workSourceKey(s, original) : "";
  return s.sources.filter((row) => active2(row) && row.workItem && row.workItem.evidence.some((e) => e.sourceId === sourceId || key2 && e.key === key2));
}
function workItemOwnsFeedback(s, sourceId) {
  return sourceWorkItems(s, sourceId).some((row) => ["risk", "action", "decision"].includes(row.workItem.nature));
}
var businessNature = (nature) => ["risk", "action", "decision"].includes(nature);
var evidenceStamp = (evidence) => digest2(evidence.map((e) => [e.key, e.current, e.available]).sort((a, b) => String(a[0]).localeCompare(String(b[0]))));
function workBusinessContext(s, source, now2) {
  const target = source.workItem?.businessTarget;
  const row = target && target.kind !== "sources" ? s[target.kind]?.find((r) => r.id === target.id && !r.archived) : void 0;
  const followup = row ? buildFollowup(s, { kind: target.kind, targetId: target.id }, now2) : void 0;
  const dates = [...row ? [row.plannedEnd, row.dueAt, row.deadline, row.checkAt, row.committed] : [], ...source.projectIds.map((id2) => s.projects.find((p) => p.id === id2)).filter((p) => !!p).map((p) => getProjectGates(s, p).next?.date)].filter((v) => /^\d{4}-\d{2}-\d{2}$/.test(v || "")).sort();
  return { followup, deadline: dates[0] ? dates[0] + "T09:00:00+08:00" : "", basis: followup?.evidenceBasis || digest2(dates) };
}
function workItemState(s, source, now2 = Date.now()) {
  const item = source.workItem;
  const index = new Map(s.sources.map((row) => [row.id, row])), keys = new Set((item.evidence || []).map((proof) => proof.key));
  const relevant = s.sources.filter((row) => !row.workItem && keys.has(workSourceKey(s, row, index)));
  const canonical6 = new Map(workEvidenceSources(s, relevant.map((row) => row.id)).map((row) => [workSourceKey(s, row, index), row]));
  const evidence = (item.evidence || []).map((entry) => {
    const row = canonical6.get(entry.key) || s.sources.find((src) => src.id === entry.sourceId), available = !!row && caseEvidenceAvailable(s, row);
    return { ...entry, sourceId: row?.id || entry.sourceId, row, available, current: row ? workSourceFingerprint(s, row) : "" };
  });
  const assessmentKeys = item.assessmentEvidence?.map((e) => e.key), currentEvidence = assessmentKeys ? evidence.filter((e) => assessmentKeys.includes(e.key)) : evidence;
  const invalid = currentEvidence.filter((entry) => !entry.available || entry.current !== entry.fingerprint), stale = invalid.length > 0, liveEvidenceBasis = evidenceStamp(currentEvidence), staleEvidenceBasis = evidenceStamp(invalid);
  const basis = digest2([item.semanticRevision || 1, item.nature, item.urgency]), handling = item.handling || {};
  const review = (item.reviews || []).findLast((row) => row.basis === basis);
  const currentEvidenceReviewed = !!review && (review.evidenceBasis === liveEvidenceBasis || !!review.staleEvidenceBasis && review.staleEvidenceBasis === staleEvidenceBasis) || handling.state === "handled" && handling.basis === basis && (handling.evidenceBasis === liveEvidenceBasis || !!handling.staleEvidenceBasis && handling.staleEvidenceBasis === staleEvidenceBasis);
  const pendingChange = item.pendingChange || null, nature = item.nature === "risk" ? "risk" : pendingChange && businessNature(pendingChange.nature) ? pendingChange.nature : item.nature;
  const actionable = businessNature(nature);
  const business = workBusinessContext(s, source, now2), timing = itemTiming(s, source, now2), legacyNext = Number.isFinite(Date.parse(handling.nextCheckAt || "")) ? business.deadline ? new Date(Math.min(Date.parse(handling.nextCheckAt), Date.parse(business.deadline))).toISOString() : handling.nextCheckAt : "", nextCheckAt = hasTimeOverride(item.p1?.check) ? timing.check.state === "scheduled" && !timing.check.completedAt && !timing.check.needsReview ? timing.check.effectiveAt || "" : "" : legacyNext;
  const due = !!nextCheckAt && Date.parse(nextCheckAt) <= now2;
  const businessChanged = handling.state === "waiting" && !!handling.businessBasis && handling.businessBasis !== business.basis;
  const reviewedClosed = !!review && ["dismissed", "resolved"].includes(review.decision);
  const explicitLife = item.p1?.lifecycle?.state;
  const closed4 = !pendingChange && (explicitLife ? explicitLife === "closed" : (!stale || currentEvidenceReviewed) && (item.nature === "risk" ? reviewedClosed : handling.state === "handled" && handling.basis === basis));
  const knownConfirmedRisk = item.nature === "risk" && !closed4 && (review?.decision === "confirmed" || item.reviews?.at(-1)?.decision === "confirmed");
  const ignored = item.disposition?.state === "ignored" && !knownConfirmedRisk && !pendingChange;
  const changed = handling.basis && handling.basis !== basis, urgency = item.nature === "risk" && item.urgency === "urgent" && !reviewedClosed ? "urgent" : pendingChange?.urgency || item.urgency;
  const urgent = !closed4 && !ignored && (!stale || currentEvidenceReviewed) && urgency === "urgent" && actionable;
  const handlingState = closed4 || ignored ? "handled" : pendingChange || stale && !currentEvidenceReviewed || changed || due || businessChanged || business.followup?.pendingReply ? "attention" : handling.state === "waiting" ? "waiting" : handling.state === "in_progress" ? "in_progress" : "attention";
  const canIgnore = !closed4 && !ignored && !knownConfirmedRisk && !urgent && !["publishing", "unknown", "partial"].includes(source.dataPublication?.status) && !(source.dataPublication?.artifact && source.dataPublication.status !== "verified");
  const hasNewData = !actionable && !closed4 && !ignored && (!!pendingChange || ["progress", "result"].includes(item.nature) && item.acknowledgedBasis !== basis || item.manualAttention === true);
  const notificationBasis = pendingChange ? digest2([basis, pendingChange.id]) : basis;
  return {
    item,
    timing,
    evidence,
    currentEvidence,
    stale,
    basis,
    liveEvidenceBasis,
    staleEvidenceBasis,
    review,
    currentEvidenceReviewed,
    actionable,
    closed: closed4,
    ignored,
    canIgnore,
    knownConfirmedRisk,
    pendingChange,
    nature,
    hasNewData,
    notificationBasis,
    urgent,
    handlingState,
    due,
    business,
    businessChanged,
    nextCheckAt,
    needsVerification: !!pendingChange || nature === "risk" && (!review || stale && !currentEvidenceReviewed),
    associationPending: item.association.kind === "unknown" || !item.association.confirmed && item.association.kind !== "personal"
  };
}
function workItemCandidates(s) {
  return s.sources.filter((row) => active2(row) && row.workItem).slice().sort((a, b) => String(b.workItem.lastChangedAt).localeCompare(String(a.workItem.lastChangedAt))).map((row) => ({ id: row.id, version: row.version, title: row.title, nature: row.workItem.nature, summary: row.workItem.summary, association: row.workItem.association, sourceIds: row.sourceIds, lastChangedAt: row.workItem.lastChangedAt, limitations: row.workItem.limitations || [], human: row.workItem.human?.fields?.length ? row.workItem.human : null, ignored: workItemState(s, row).ignored, pendingChange: row.workItem.pendingChange || null, lastDecision: row.workItem.decisions?.at(-1) || null, closed: workItemState(s, row).closed }));
}
function projectIds(s, a) {
  return a.kind === "project" ? [a.id] : a.kind === "case" ? s.cases.find((row) => row.id === a.id)?.projectIds || [] : [];
}
function validateFinding(s, f) {
  if (f.triage && (typeof f.triage.necessary !== "boolean" || typeof f.triage.ready !== "boolean" || !bounded2(f.triage.reason, 1e3) || !f.triage.reason.trim() || !Array.isArray(f.triage.gaps) || f.triage.gaps.some((g) => !bounded2(g, 600)))) fail6("AI\u5206\u6D41\u7F3A\u5C11\u5FC5\u8981\u6027\u3001\u4F9D\u636E\u6216\u4FE1\u606F\u7F3A\u53E3");
  if (!workItemNatures.includes(f.nature) || !bounded2(f.title, 200) || !f.title.trim() || !bounded2(f.summary, 1600) || !f.summary.trim() || !bounded2(f.nextStep, 1600) || !bounded2(f.impact || "", 1600) || !["normal", "urgent"].includes(f.urgency)) fail6("\u6574\u5408\u4E8B\u9879\u7684\u5185\u5BB9\u6216\u5206\u7C7B\u65E0\u6548");
  if (!Array.isArray(f.sourceIds) || !f.sourceIds.length || f.sourceIds.length > 128 || f.sourceIds.some((id2) => !s.sources.some((row) => row.id === id2 && !row.workItem && caseEvidenceAvailable(s, row)))) fail6("\u6574\u5408\u4E8B\u9879\u7F3A\u5C11\u5F53\u524D\u53EF\u7528\u539F\u6587");
  if (f.limitations !== void 0 && (!Array.isArray(f.limitations) || f.limitations.length > 64 || f.limitations.some((value) => !bounded2(value, 1e3)))) fail6("\u4E8B\u9879\u8BFB\u53D6\u8303\u56F4\u8BF4\u660E\u65E0\u6548");
  if (f.assessmentSourceIds !== void 0 && (!Array.isArray(f.assessmentSourceIds) || !f.assessmentSourceIds.length || f.assessmentSourceIds.some((id2) => !f.sourceIds.includes(id2)))) fail6("\u5F53\u524D\u5224\u65AD\u4F9D\u636E\u987B\u6765\u81EA\u672C\u6B21\u5DF2\u6838\u5BF9\u6765\u6E90");
  const a = f.association;
  if (!a || !["project", "case", "personal", "unknown"].includes(a.kind) || !bounded2(a.reason, 1e3)) fail6("\u4E8B\u9879\u5F52\u5C5E\u683C\u5F0F\u65E0\u6548");
  if (f.businessTarget && (!["projects", "cases", "deliverables", "actions", "flowNodes", "milestones", "risks", "decisions"].includes(f.businessTarget.kind) || !s[f.businessTarget.kind]?.some((row) => row.id === f.businessTarget.id && !row.archived))) fail6("\u5173\u8054\u4E1A\u52A1\u5DE5\u4F5C\u4E0D\u5728\u672C\u5DE5\u4F5C\u533A");
  if (["project", "case"].includes(a.kind) && !s[a.kind === "project" ? "projects" : "cases"].some((row) => row.id === a.id && !row.archived && !row.mergedIntoId)) fail6("\u4E8B\u9879\u5EFA\u8BAE\u5F52\u5C5E\u5DF2\u4E0D\u53EF\u7528");
  if (f.existingItemId) {
    const row = s.sources.find((row2) => row2.id === f.existingItemId && row2.workItem && active2(row2));
    if (!row || row.version !== f.expectedVersion) throw Object.assign(new Error("\u5DF2\u6709\u4E8B\u9879\u5DF2\u53D8\u5316\uFF0C\u8BF7\u91CD\u65B0\u6838\u5BF9\u5F53\u524D\u4EBA\u5DE5\u5224\u65AD"), { status: 409, code: "WORK_ITEM_CHANGED" });
    if (!f.matchReason?.trim()) fail6("\u7F3A\u5C11\u540C\u4E00\u4E8B\u9879\u7684\u5339\u914D\u4F9D\u636E");
  }
}
function applyWorkItemFindings(s, findings, at) {
  findings.forEach((f) => validateFinding(s, f));
  const result = [];
  for (const input of findings) {
    const f = structuredClone(input), incoming = structuredClone(input);
    const id2 = f.existingItemId || f.id || "work-item-" + digest2([s.workspaceId, unique3(f.sourceIds.map((sourceId) => workSourceKey(s, s.sources.find((row) => row.id === sourceId)))).sort(), f.nature, f.title]);
    let source = s.sources.find((row) => row.id === id2);
    if (source && !source.workItem) fail6("\u4E8B\u9879\u8EAB\u4EFD\u4E0E\u5DF2\u6709\u8D44\u6599\u51B2\u7A81", 409);
    const old = source?.workItem, priorState = old ? workItemState(s, source) : null;
    const inputs = workEvidenceSources(s, f.sourceIds).map((row) => ({ sourceId: row.id, key: workSourceKey(s, row), fingerprint: workSourceFingerprint(s, row) }));
    const evidence = [...new Map([...old?.evidence || [], ...inputs].map((row) => [row.key, row])).values()];
    const freshEvidence = !old || inputs.some((proof) => !old.evidence.some((oldProof) => oldProof.key === proof.key && oldProof.fingerprint === proof.fingerprint));
    const newBusiness = businessNature(incoming.nature) && incoming.triage?.necessary !== false && incoming.materialChange !== false && freshEvidence;
    const human2 = old?.human || { fields: [] }, locks = unique3([...human2.fields || [], ...old?.nature === "risk" && old.reviews?.length || old?.handling?.manuallyReady || old?.handling?.state === "in_progress" || old?.decisions?.length ? ["nature"] : []]);
    let pendingChange = old?.pendingChange || null, disposition = old?.disposition || { state: "active" }, reactivation = old?.reactivation || null;
    const changedLocked = locks.some((field) => field !== "title" && incoming[field] !== void 0 && incoming[field] !== old?.[field]);
    const proposalKey = digest2([incoming.nature, incoming.summary, incoming.impact, incoming.nextStep, inputs]);
    if (old && locks.length && changedLocked && incoming.materialChange !== false && freshEvidence && !(old.rejectedChanges || []).includes(proposalKey)) {
      pendingChange = {
        id: proposalKey,
        title: incoming.title,
        summary: incoming.summary,
        nature: incoming.nature,
        impact: incoming.impact || "",
        nextStep: incoming.nextStep,
        urgency: incoming.urgency,
        sourceIds: f.sourceIds,
        at,
        previousDisposition: structuredClone(old.disposition || { state: "active" }),
        reason: incoming.impact || incoming.summary
      };
    }
    if (old?.p1?.lifecycle?.state === "closed" && old.p1.lifecycle.owner !== "auto" && newBusiness) pendingChange = { id: proposalKey, title: incoming.title, summary: incoming.summary, nature: incoming.nature, impact: incoming.impact || "", nextStep: incoming.nextStep, urgency: incoming.urgency, sourceIds: f.sourceIds, at, previousDisposition: structuredClone(old.disposition || { state: "active" }), reason: incoming.impact || incoming.summary };
    const mayBackground = old?.nature === "action" && !locks.length && !priorState?.closed && !priorState?.ignored && f.triage?.necessary === false && ["reference", "noise"].includes(f.nature);
    if (old) {
      for (const field of locks) {
        if (field === "title") f.title = source.title;
        else if (["nature", "summary", "impact", "nextStep", "urgency"].includes(field)) f[field] = old[field];
      }
      if (businessNature(old.nature) && !mayBackground && !old.provisional && !priorState.closed && (old.nature === "risk" && f.nature !== "risk" || !businessNature(f.nature))) {
        f.nature = old.nature;
        f.urgency = old.urgency;
        f.impact = old.impact;
        f.nextStep = old.nextStep;
      }
      if ((priorState.closed || priorState.ignored) && !newBusiness && old.nature === "risk") {
        f.nature = old.nature;
        f.urgency = old.urgency;
        f.impact = old.impact;
        f.nextStep = old.nextStep;
      }
      if (priorState.ignored && newBusiness) {
        disposition = { state: "active", at, reason: "\u65B0\u8D44\u6599\u51FA\u73B0\u5B9E\u8D28\u98CE\u9669\u6216\u65B0\u7684\u529E\u7406\u8981\u6C42" };
        reactivation = { at, reason: incoming.impact || incoming.summary, sourceIds: f.sourceIds };
      }
      if ((priorState.ignored || priorState.closed) && !newBusiness) pendingChange = old.pendingChange || null;
      if (pendingChange) {
        f.title = source.title;
        for (const field of ["nature", "summary", "impact", "nextStep", "urgency"]) f[field] = old[field];
      }
    }
    const association = old?.association?.confirmed ? old.association : { ...f.association, confirmed: f.association.confirmed === true };
    const limitations = f.limitations || old?.limitations || [];
    if (f.triage?.necessary === false && (!old || old.provisional)) f.nature = "reference";
    const messageTriage = old?.nature === "risk" && f.triage?.necessary === false ? f.triage : null;
    const triage = locks.length && old?.triage ? old.triage : messageTriage ? old?.triage?.necessary === true ? old.triage : { necessary: true, ready: false, reason: "\u672C\u6B21\u6D88\u606F\u6CA1\u6709\u65B0\u589E\u52A8\u4F5C\uFF1B\u539F\u98CE\u9669\u7EE7\u7EED\u4FDD\u7559\uFF0C\u9700\u6309\u5B8C\u6574\u5F53\u524D\u4F9D\u636E\u6838\u5BF9\u4E0B\u4E00\u6B65\u3002", gaps: ["\u6838\u5BF9\u539F\u98CE\u9669\u5F53\u524D\u9700\u8981\u63A8\u8FDB\u7684\u5DE5\u4F5C"] } : f.triage || old?.triage || null;
    const assessmentEvidence = f.assessmentSourceIds && !locks.length ? inputs.filter((e) => f.assessmentSourceIds.some((id3) => workSourceKey(s, s.sources.find((row) => row.id === id3)) === e.key)) : old?.assessmentEvidence || null;
    const content = [f.title, f.summary, f.impact || "", f.nextStep, f.nature, f.urgency, association, evidence, limitations, pendingChange, disposition, triage, assessmentEvidence, messageTriage];
    if (old?.contentHash === digest2(content)) {
      result.push(id2);
      continue;
    }
    let material = !old || f.materialChange !== false && freshEvidence || old.nature !== f.nature || old.urgency !== f.urgency;
    if (old && (pendingChange || priorState.ignored || priorState.closed) && !newBusiness) material = false;
    if (pendingChange) material = false;
    const item = {
      ...old || {},
      schemaVersion: 1,
      nature: f.nature,
      summary: f.summary,
      impact: f.impact || "",
      nextStep: f.nextStep,
      urgency: f.urgency,
      association,
      evidence,
      limitations,
      human: human2,
      pendingChange,
      disposition,
      reactivation,
      triage,
      messageTriage,
      assessmentEvidence,
      needsTriage: !!messageTriage && !old?.triage?.necessary,
      provisional: old?.provisional === true && !f.triage,
      contentHash: digest2(content),
      semanticRevision: (old?.semanticRevision || 0) + (material ? 1 : 0),
      lastChangedAt: material || pendingChange?.id !== old?.pendingChange?.id ? at : old.lastChangedAt,
      lastReadAt: at,
      legacyRefs: unique3([...old?.legacyRefs || [], ...f.legacyRefs || []]),
      businessTarget: old?.businessTarget || f.businessTarget || null,
      reviews: old?.reviews || [],
      handling: old?.handling || {},
      notificationBaseline: old?.notificationBaseline || "",
      history: old ? [...old.history || [], { at: source.updatedAt, title: source.title, summary: old.summary, nature: old.nature, impact: old.impact, association: old.association, evidence: old.evidence, assessmentEvidence: old.assessmentEvidence || null, triage: old.triage || null, nextStep: old.nextStep, semanticRevision: old.semanticRevision, disposition: old.disposition, pendingChange: old.pendingChange }] : []
    };
    const value = { ...source || {}, id: id2, title: f.title, type: "\u6574\u5408\u4E8B\u9879", projectIds: projectIds(s, association), sourceIds: unique3(evidence.map((row) => row.sourceId)), objectIds: [], confirmed: false, processingStatus: "\u5DF2\u6574\u7406", excerpt: f.summary, version: (source?.version || 0) + 1, createdAt: source?.createdAt || at, collectedAt: source?.collectedAt || at, updatedAt: at, workItem: item };
    if (source) Object.assign(source, value);
    else {
      s.sources.push(value);
      source = value;
      ensureCore(source).admission = businessNature(item.nature) ? "candidate" : "background";
    }
    if (old && freshEvidence) {
      const core = ensureCore(source);
      core.checks = { ...core.checks, needsRecheck: true, reason: "\u65B0\u6765\u6E90\u5DF2\u4FDD\u5B58\uFF0C\u91CD\u65B0\u5224\u65AD\u5F53\u524D\u9700\u8981" };
    }
    result.push(id2);
  }
  return result;
}
function workItemRecordView(s, source, now2 = Date.now()) {
  const c = workItemState(s, source, now2), item = c.item, followup = workItemFollowup(s, source, now2), brief = workItemBrief(s, source);
  const ready = item.core?.admission !== "candidate" && !c.pendingChange && (!c.stale || c.currentEvidenceReviewed) && item.association.kind !== "unknown" && (item.triage?.necessary === true && item.triage?.ready === true && !!item.triage.reason || c.review?.decision === "confirmed" || item.handling?.manuallyReady === true && item.handling.basis === c.basis);
  return {
    id: "sources:" + source.id,
    targetId: source.id,
    kind: "sources",
    title: brief.title,
    projectIds: source.projectIds,
    caseId: item.association.kind === "case" ? item.association.id : void 0,
    category: c.closed ? "followup" : !ready || c.nature === "decision" ? "confirmation" : "followup",
    urgent: c.urgent,
    reason: followup.reason,
    reasons: [followup.reason],
    summary: c.pendingChange?.summary || brief.facts,
    next: c.pendingChange?.nextStep || brief.nextStep,
    owner: c.actionable ? "\u672C\u4EBA" : "",
    date: item.handling?.nextCheckAt || "",
    sourceIds: source.sourceIds,
    relatedIds: [],
    requiresVerification: c.needsVerification,
    handlingState: followup.handlingState,
    waitingReason: followup.waitingReason,
    nextCheckAt: followup.nextCheckAt,
    followup
  };
}
function workItemAttention(s, now2 = Date.now()) {
  return s.sources.filter((row) => active2(row) && row.workItem).flatMap((source) => {
    const c = workItemState(s, source, now2);
    return c.actionable && !c.ignored && s.workspaceType !== "restored" ? [workItemRecordView(s, source, now2)] : [];
  });
}
function workItemFollowup(s, source, now2 = Date.now()) {
  const c = workItemState(s, source, now2), item = c.item;
  const reason = c.pendingChange ? "\u6709\u65B0\u7684\u5B9E\u8D28\u53D8\u5316\u5F85\u6838\u5BF9\uFF1A" + c.pendingChange.summary : c.ignored ? "\u5DF2\u5FFD\u7565\uFF0C\u666E\u901A\u8865\u5145\u4E0D\u518D\u63D0\u793A" : c.stale && !c.currentEvidenceReviewed ? "\u539F\u4F9D\u636E\u5DF2\u53D8\u5316\u6216\u4E0D\u53EF\u7528\uFF0C\u7B49\u5F85\u91CD\u65B0\u7406\u89E3" : c.closed ? "\u672C\u4E8B\u9879\u5DF2\u5904\u7406" : c.due ? "\u5DF2\u5230\u8DDF\u8FDB\u65F6\u95F4" : item.impact || item.nextStep || item.summary;
  return {
    kind: "sources",
    targetId: source.id,
    itemKey: [s.workspaceId, "sources", source.id].map(encodeURIComponent).join(":"),
    title: source.title,
    projectIds: source.projectIds,
    caseId: item.association.kind === "case" ? item.association.id : void 0,
    handlingState: c.handlingState,
    urgent: c.urgent,
    reason: c.business.followup?.pendingReply ? "\u5173\u8054\u5DE5\u4F5C\u5DF2\u6709\u65B0\u53CD\u9988\uFF0C\u5F85\u6838\u5BF9" : c.businessChanged ? "\u5173\u8054\u5DE5\u4F5C\u7684\u671F\u9650\u6216\u4F9D\u636E\u5DF2\u6709\u53D8\u5316" : reason,
    reasons: [reason],
    waitingReason: item.handling?.reason || "",
    nextCheckAt: c.nextCheckAt,
    primaryAction: "inspect",
    feedbackState: c.stale ? "stale" : c.business.followup?.feedbackState || "none",
    clarification: c.business.followup?.clarification || "",
    reminderEligible: !!c.business.followup?.reminderEligible,
    notificationBasis: c.notificationBasis,
    suppressNotification: item.notificationBaseline === c.notificationBasis || c.ignored,
    basis: digest2([c.basis, c.liveEvidenceBasis, source.version, c.stale, item.handling, item.disposition, c.pendingChange?.id]),
    evidenceBasis: digest2(item.evidence),
    feedbackBasis: c.basis,
    gateBasis: c.business.followup?.gateBasis || c.business.basis,
    sources: c.evidence.map((e) => ({ id: e.sourceId, version: e.row?.version || 0, title: e.row?.title || "\u539F\u6587\u4E0D\u53EF\u7528", available: e.available, fingerprint: e.current, eventAt: e.row?.occurredAt || "" })),
    pendingReply: !!c.business.followup?.pendingReply,
    executionSourceIds: c.business.followup?.executionSourceIds || [],
    active: c.actionable && !c.closed && !c.ignored && !source.archived,
    businessStates: c.business.followup?.businessStates || { feedback: item.summary, submission: "", professionalReview: "", acceptance: "", node: "", syncApproval: "" }
  };
}
function ownEvidence(s, source, reason, requestId, at) {
  const id2 = "work-item-note-" + digest2([s.workspaceId, requestId]);
  const note = { id: id2, title: ("\u672C\u4EBA\u6838\u5B9E\u8BF4\u660E \xB7 " + source.title).slice(0, 200), excerpt: reason, author: "\u672C\u4EBA", type: "\u672C\u4EBA\u8BF4\u660E", projectIds: [...source.projectIds], sourceIds: [], objectIds: [source.id], version: 1, confirmed: true, collectedAt: at, occurredAt: at };
  if (!s.sources.some((row) => row.id === id2)) s.sources.push(note);
  source.workItem.evidence.push({ sourceId: id2, key: workSourceKey(s, note), fingerprint: workSourceFingerprint(s, note) });
  source.sourceIds = unique3([...source.sourceIds, id2]);
}
function reviewItem(s, source, decision, reason, at, extra = {}) {
  const c = workItemState(s, source);
  source.workItem.reviews.push({ basis: c.basis, evidenceBasis: c.liveEvidenceBasis, staleEvidenceBasis: c.staleEvidenceBasis, decision, reason, actor: "\u672C\u4EBA", at, ...extra });
}
function correctItem(s, source, patch, op, at) {
  const item = source.workItem, c = workItemState(s, source), keys = Object.keys(patch), allowed = ["title", "summary", "nature", "impact", "nextStep", "urgency"];
  if (!keys.length || keys.some((key2) => !allowed.includes(key2))) fail6("\u8BF7\u9009\u62E9\u9700\u8981\u8C03\u6574\u7684\u5206\u7C7B\u6216\u7406\u89E3\u5185\u5BB9");
  const nature = patch.nature === void 0 ? item.nature : patch.nature;
  if (!workItemNatures.includes(nature)) fail6("\u4E8B\u9879\u5206\u7C7B\u65E0\u6548");
  for (const key2 of ["title", "summary", "impact", "nextStep"]) if (patch[key2] !== void 0 && (!bounded2(patch[key2], key2 === "title" ? 200 : 1600) || ["title", "summary"].includes(key2) && !patch[key2].trim())) fail6("\u4E8B\u9879\u6807\u9898\u6216\u5185\u5BB9\u65E0\u6548");
  if (patch.urgency !== void 0 && !["normal", "urgent"].includes(patch.urgency)) fail6("\u7D27\u8FEB\u5EA6\u65E0\u6548");
  const changedNature = nature !== item.nature;
  if (changedNature && (nature === "risk" || item.nature === "risk") && !op.reason?.trim()) fail6("\u8C03\u6574\u98CE\u9669\u5206\u7C7B\u9700\u8981\u586B\u5199\u7B80\u77ED\u7406\u7531\u6216\u4F9D\u636E");
  if (item.nature === "risk" && nature !== "risk" && !c.closed) {
    if (!["dismissed", "resolved"].includes(op.riskDisposition) || !op.reason?.trim()) fail6("\u8BF7\u5148\u8BF4\u660E\u539F\u98CE\u9669\u662F\u4E0D\u6210\u7ACB\u8FD8\u662F\u5DF2\u89E3\u9664");
    reviewItem(s, source, op.riskDisposition, op.reason, at, { classificationCorrection: true });
  }
  if (nature === "risk" && (changedNature || op.riskDecision && op.riskDecision !== "preserve")) {
    if (!["pending", "confirmed"].includes(op.riskDecision) || !op.reason?.trim() || !(patch.impact ?? item.impact)?.trim()) fail6("\u5217\u4E3A\u98CE\u9669\u65F6\u8BF7\u9009\u62E9\u5F85\u6838\u5B9E\u6216\u5DF2\u786E\u8BA4\uFF0C\u5E76\u586B\u5199\u5F71\u54CD\u4E0E\u4F9D\u636E");
  }
  const currentReview = c.review, resetRisk = nature === "risk" && op.riskDecision === "pending";
  if (changedNature || resetRisk || patch.urgency && patch.urgency !== item.urgency) item.semanticRevision++;
  if (patch.title !== void 0) source.title = patch.title.trim();
  for (const key2 of ["summary", "nature", "impact", "nextStep", "urgency"]) if (patch[key2] !== void 0) item[key2] = patch[key2];
  source.excerpt = item.summary;
  item.human = { fields: unique3([...item.human?.fields || [], ...keys]), at, reason: op.reason || "\u672C\u4EBA\u66F4\u6B63\u7406\u89E3" };
  item.disposition = { state: "active", at };
  item.pendingChange = null;
  item.manualAttention = false;
  item.contentHash = "";
  if (changedNature || resetRisk) item.handling = { state: "attention", basis: workItemState(s, source).basis, at };
  if (nature === "risk" && op.riskDecision === "confirmed") {
    ownEvidence(s, source, op.reason, op.requestId, at);
    reviewItem(s, source, "confirmed", op.reason, at);
  } else if (nature === "risk" && !resetRisk && !changedNature && currentReview && currentReview.basis !== workItemState(s, source).basis) {
    reviewItem(s, source, currentReview.decision, currentReview.reason, at, { preservedByCorrection: true });
  }
  if (!businessNature(nature)) item.acknowledgedBasis = workItemState(s, source).basis;
  item.notificationBaseline = workItemState(s, source).notificationBasis;
}
function applyWorkItemOperation(input, op, at) {
  if (input.workspaceType === "restored") fail6("\u6062\u590D\u5DE5\u4F5C\u533A\u53EA\u4FDD\u7559\u4E8B\u9879\u5386\u53F2\uFF0C\u8BF7\u5728\u6B63\u5F0F\u5DE5\u4F5C\u533A\u91CD\u65B0\u6838\u5BF9", 409);
  if (op.reason !== void 0 && !bounded2(op.reason, 1e3)) fail6("\u5904\u7406\u8BF4\u660E\u4E0D\u80FD\u8D85\u8FC71000\u5B57");
  const receiptKey = "work-item:" + op.requestId;
  if (!/^[\w-]{1,160}$/.test(op.requestId || "") || op.workspaceId !== input.workspaceId) fail6("\u4E8B\u9879\u8BF7\u6C42\u8EAB\u4EFD\u65E0\u6548");
  const hash3 = digest2(op), receipt2 = input.receipts[receiptKey];
  if (receipt2) {
    if (receipt2.fingerprint !== hash3) fail6("\u540C\u4E00\u8BF7\u6C42\u4E0D\u80FD\u6539\u52A8\u64CD\u4F5C\u5185\u5BB9", 409);
    return input;
  }
  const s = structuredClone(input);
  if (op.action === "adopt") {
    const original = s.sources.find((row) => row.id === op.sourceId && !row.archived);
    if (!original || original.version !== op.expectedVersion) fail6("\u8D44\u6599\u5DF2\u53D8\u5316\uFF0C\u8BF7\u5237\u65B0\u540E\u5904\u7406", 409);
    const existing = sourceWorkItems(s, original.id);
    if (existing.length > 1) fail6("\u8FD9\u4EFD\u539F\u6587\u5DF2\u5173\u8054\u591A\u4E2A\u4E8B\u9879\uFF0C\u8BF7\u9009\u62E9\u5177\u4F53\u4E8B\u9879", 409);
    let id2 = original.workItem ? original.id : existing[0]?.id;
    if (!id2) {
      id2 = "work-item-manual-" + digest2([s.workspaceId, original.id]);
      const ids8 = unique3([original.id, ...original.intakeBatch?.documents || []]).filter((id3) => s.sources.some((row) => row.id === id3 && caseEvidenceAvailable(s, row)));
      if (!ids8.length) fail6("\u539F\u6587\u5DF2\u4E0D\u53EF\u7528\uFF0C\u8BF7\u5148\u8865\u5145\u53EF\u8FFD\u6EAF\u7684\u8D44\u6599");
      const project = original.projectIds.length === 1 ? original.projectIds[0] : "";
      const brief = workItemBrief(s, original);
      applyWorkItemFindings(s, [{ id: id2, title: brief.title, summary: brief.facts, impact: brief.impact, nextStep: brief.nextStep, nature: "reference", urgency: "normal", sourceIds: ids8, association: { kind: project ? "project" : "unknown", id: project, reason: "\u6CBF\u7528\u539F\u8D44\u6599\u5173\u8054", confirmed: !!project }, limitations: [...brief.gaps, ...original.intakeBatch?.status === "partial" ? ["\u672C\u8D44\u6599\u53EA\u8BFB\u5230\u90E8\u5206\u5185\u5BB9"] : []] }], at);
      s.sources.find((row) => row.id === id2).workItem.manualAttention = true;
    }
    s.revision++;
    s.receipts[receiptKey] = { fingerprint: hash3, result: { sourceId: id2 } };
    s.audit.push({ id: "work-item-" + digest2([receiptKey, hash3]), time: at, operation: "work-item.adopt", kind: "sources", objectId: id2, actor: "\u672C\u4EBA", before: null, after: { originalSourceId: original.id }, revision: s.revision });
    return s;
  }
  const source = s.sources.find((row) => row.id === op.sourceId && row.workItem && active2(row));
  if (!source || op.action !== "p1-undo" && source.version !== op.expectedVersion) fail6("\u4E8B\u9879\u5DF2\u53D8\u5316\uFF0C\u8BF7\u5237\u65B0\u540E\u6838\u5BF9", 409);
  const c = workItemState(s, source), item = source.workItem;
  if (op.action !== "p1-undo" && (op.expectedBasis !== c.basis || op.expectedEvidenceBasis !== void 0 && op.expectedEvidenceBasis !== c.liveEvidenceBasis)) fail6("\u4E8B\u9879\u4F9D\u636E\u5DF2\u53D8\u5316\uFF0C\u8BF7\u91CD\u65B0\u6838\u5BF9", 409);
  const before = structuredClone(item), previousTitle = source.title;
  let p1Result;
  const sourceEffects = [];
  item.provisional = false;
  if (op.action?.startsWith("core-")) {
    const calendar = s.sources.find((row) => row.workCalendar && !row.archived)?.workCalendar;
    applyCoreDecision(s, source, op, at, calendar);
  } else if (op.action === "p1-submit") {
    const prepared = combineEntry(op.entry, op.input);
    if (prepared.conflicts.length) throw Object.assign(new Error("\u672C\u6B21\u8F93\u5165\u6709\u5F85\u6F84\u6E05\u7684\u5177\u4F53\u5DEE\u5F02\uFF0C\u672A\u4FDD\u5B58\u3002"), { status: 422, conflicts: prepared.conflicts });
    if (!Object.keys(prepared.changes).length) return input;
    const change = prepared.changes, core = ensureCore(source), inputSource = s.sources.find((r) => r.id === op.inputSourceId), eventAt = inputSource?.inputEnvelope?.origin === "feishu" ? op.input.occurredAt : at, pendingChanges = [];
    if (inputSource?.inputEnvelope?.origin === "feishu") {
      const names = { check: "\u68C0\u67E5\u5B89\u6392", completion: "\u5B8C\u6210\u8981\u6C42", waiting: "\u7B49\u5F85\u5B89\u6392", followup: "\u8DDF\u8FDB\u72B6\u6001", riskDecision: "\u98CE\u9669\u7ED3\u8BBA" };
      for (const key2 of ["check", "completion", "waiting", "followup", "riskDecision"]) {
        const field = key2 === "followup" ? "lifecycle" : key2, oldAt = core.instructionAt?.[field] || item.p1?.[field]?.at || "";
        const closedAt = item.p1?.lifecycle?.owner === "manual" && item.p1.lifecycle.state === "closed" ? core.instructionAt?.lifecycle || item.p1.lifecycle.at : "";
        if (change[key2] && eventAt < (oldAt > closedAt ? oldAt : closedAt)) {
          delete change[key2];
          if (key2 === "riskDecision") delete change.riskQuote;
          if (key2 === "followup") delete change.followupQuote;
          pendingChanges.push({ id: key2, title: names[key2], projectIds: [], sourceIds: [], message: names[key2] + "\u5DF2\u6709\u8F83\u65B0\u4EBA\u5DE5\u51B3\u5B9A\uFF0C\u65E7\u6D88\u606F\u53EA\u7559\u5B58\uFF0C\u4E0D\u8986\u76D6\u3002" });
        }
      }
    }
    if (change.riskDecision && item.nature !== "risk") fail6("\u5F53\u524D\u4E8B\u9879\u4E0D\u662F\u98CE\u9669\uFF0C\u4E0D\u80FD\u4FEE\u6539\u98CE\u9669\u7ED3\u8BBA");
    if (change.followup === "end" && item.nature === "risk" && !["resolved", "dismissed"].includes(change.riskDecision || c.review?.decision)) fail6("\u98CE\u9669\u5C1A\u672A\u89E3\u9664\uFF1B\u672C\u6B21\u53EA\u80FD\u8BB0\u5F55\u8FDB\u5C55\u6216\u660E\u786E\u505C\u6B62\u8DDF\u8FDB\u539F\u56E0");
    if (c.closed && !change.followup && !change.progress && !change.checkCompleted) fail6("\u4E8B\u9879\u5DF2\u7ED3\u675F\uFF0C\u8BF7\u91CD\u65B0\u6253\u5F00\u540E\u518D\u5B89\u6392\u65F6\u95F4");
    if (change.checkCompleted && !hasTimeOverride(item.p1?.check)) {
      item.p1 ||= {};
      item.p1.check = structuredClone(c.timing.check);
    }
    applyEntryChanges(source, change, op.requestId, at);
    for (const key2 of ["check", "completion", "waiting", "followup", "riskDecision"]) if (change[key2]) {
      core.instructionAt ||= {};
      core.instructionAt[key2 === "followup" ? "lifecycle" : key2] = eventAt;
    }
    if (op.inputSourceId && change.progress) {
      const progress = item.p1.progress.find((r) => r.id === (change.progress.editId || op.requestId));
      progress.inputSourceId = op.inputSourceId;
      progress.sourceIds = [op.inputSourceId];
    }
    if (change.riskDecision) reviewItem(s, source, change.riskDecision, change.riskQuote || "", at);
    if (change.followup === "continue") item.notificationBaseline = c.notificationBasis;
    if (op.input?.editProgressId) {
      const previous = before.p1?.progress?.find((r) => r.id === op.input.editProgressId);
      const note = s.sources.find((r) => r.id === previous?.inputSourceId);
      if (note?.inputEnvelope) {
        const prior = { effectWithdrawn: note.inputEnvelope.effectWithdrawn === true, correctedBy: note.inputEnvelope.correctedBy || "" };
        note.inputEnvelope.effectWithdrawn = true;
        note.inputEnvelope.correctedBy = op.inputSourceId;
        sourceEffects.push({ id: note.id, title: "\u672C\u6B21\u7EA0\u6B63\u5F71\u54CD\u7684\u539F\u8F93\u5165\u6548\u529B", projectIds: [], sourceIds: [], before: prior, after: { effectWithdrawn: true, correctedBy: op.inputSourceId || "" } });
        note.version++;
        item.evidence = item.evidence.filter((e) => e.sourceId !== note.id);
        if (item.assessmentEvidence) item.assessmentEvidence = item.assessmentEvidence.filter((e) => e.sourceId !== note.id);
      }
    }
    const patches = entryPatches(before, item);
    p1Result = { p1: true, version: source.version + 1, basis: workItemState(s, source).basis, evidence: workItemState(s, source).liveEvidenceBasis, operationId: op.requestId, progressId: change.progress ? change.progress.editId || op.requestId : "", at, sourceId: source.id, sourceEffects, pendingChanges, patches, progress: change.progress?.text || "", changes: Object.keys(change), closed: item.p1?.lifecycle?.state === "closed", stay: prepared.stay || pendingChanges.length > 0, timing: itemTiming(s, source, at), input: op.input };
  } else if (op.action === "p1-undo") {
    const original = s.receipts["work-item:" + op.operationId]?.result;
    if (!original?.p1 || original.sourceId !== source.id) fail6("\u6CA1\u6709\u53EF\u64A4\u9500\u7684\u672C\u6B21\u64CD\u4F5C");
    if (original.undoneAt) return input;
    for (const effect of original.sourceEffects || []) {
      const note2 = s.sources.find((r) => r.id === effect.id);
      if (!note2?.inputEnvelope || JSON.stringify({ effectWithdrawn: note2.inputEnvelope.effectWithdrawn === true, correctedBy: note2.inputEnvelope.correctedBy || "" }) !== JSON.stringify(effect.after)) fail6("\u76F8\u5173\u6765\u6E90\u6548\u529B\u5DF2\u6709\u540E\u7EED\u4FEE\u6539\uFF0C\u672A\u64A4\u9500\u4EFB\u4F55\u5185\u5BB9", 409);
      Object.assign(note2.inputEnvelope, effect.before);
      note2.version++;
      if (!item.evidence.some((e) => e.sourceId === note2.id)) item.evidence.push({ sourceId: note2.id, key: workSourceKey(s, note2), fingerprint: workSourceFingerprint(s, note2) });
    }
    for (const target of original.relatedPatches || [{ id: source.id, patches: original.patches }]) {
      const related2 = s.sources.find((r) => r.id === target.id && r.workItem);
      if (!related2) fail6("\u540C\u6B21\u64CD\u4F5C\u7684\u76F8\u5173\u4E8B\u9879\u5DF2\u4E0D\u53EF\u7528\uFF0C\u672A\u64A4\u9500\u4EFB\u4F55\u5185\u5BB9", 409);
      undoEntry(target.created ? structuredClone(related2) : related2, target.patches);
      related2.workItem.evidence = related2.workItem.evidence.filter((e) => e.sourceId !== original.inputSourceId);
      if (related2.workItem.assessmentEvidence) related2.workItem.assessmentEvidence = related2.workItem.assessmentEvidence.filter((e) => e.sourceId !== original.inputSourceId);
      if (target.created) {
        related2.workItem.disposition = { state: "ignored", at, reason: "\u64A4\u9500\u672C\u6B21\u65B0\u5EFA\uFF1B\u539F\u4EF6\u4E0E\u5386\u53F2\u4FDD\u7559" };
        ensureCore(related2).admission = "withdrawn";
        related2.workItem.p1 ||= {};
        related2.workItem.p1.lifecycle = { state: "closed", owner: "manual", at, reason: "\u64A4\u9500\u672C\u6B21\u65B0\u5EFA\uFF1B\u4FDD\u7559\u5386\u53F2\u8EAB\u4EFD" };
      }
      if (related2 !== source) {
        related2.version++;
        invalidateCoreDerivations(s, related2, at, "\u540C\u6B21\u64CD\u4F5C\u64A4\u9500");
      }
    }
    const note = s.sources.find((r) => r.id === original.inputSourceId);
    if (note?.inputEnvelope) {
      note.inputEnvelope.effectWithdrawn = true;
      note.version++;
    }
    original.undoneAt = at;
    original.undoneBy = op.requestId;
    const core = ensureCore(source);
    for (const patch of original.patches || []) {
      if (patch.path[0] === "p1" && ["check", "completion", "waiting", "lifecycle", "riskDecision"].includes(patch.path[1])) {
        core.instructionAt ||= {};
        core.instructionAt[patch.path[1]] = at;
      }
    }
  } else if (op.action === "associate") {
    const a = op.association;
    if (!a || !["project", "case", "personal", "unknown"].includes(a.kind)) fail6("\u8BF7\u9009\u62E9\u4E8B\u9879\u5F52\u5C5E");
    if (["project", "case"].includes(a.kind) && !s[a.kind === "project" ? "projects" : "cases"].some((row) => row.id === a.id && !row.archived)) fail6("\u4E8B\u9879\u5F52\u5C5E\u5DF2\u4E0D\u53EF\u7528");
    item.association = { kind: a.kind, id: ["project", "case"].includes(a.kind) ? a.id : "", reason: "\u672C\u4EBA\u786E\u8BA4", confirmed: true };
    source.projectIds = projectIds(s, item.association);
  } else if (op.action === "ignore") {
    if (!c.canIgnore) fail6(c.knownConfirmedRisk || c.urgent ? "\u5DF2\u786E\u8BA4\u6216\u7D27\u6025\u98CE\u9669\u8BF7\u8BB0\u5F55\u4E0D\u6210\u7ACB\u3001\u89E3\u9664\u6216\u7B49\u5F85\uFF0C\u4E0D\u7528\u5FFD\u7565\u4EE3\u66FF\u98CE\u9669\u5904\u7406" : "\u8BF7\u5148\u6838\u5BF9\u5DF2\u6709\u6267\u884C\u7ED3\u679C\uFF0C\u6216\u6062\u590D\u540E\u518D\u64CD\u4F5C");
    if (source.dataPublication && !source.dataPublication.artifact && ["prepared", "stale", "failed"].includes(source.dataPublication.status)) {
      const publicationBefore = { status: source.dataPublication.status, targetId: source.dataPublication.targetId, destination: source.dataPublication.destination };
      source.dataPublication.status = "cancelled";
      source.dataPublication.cancelledAt = at;
      source.dataPublication.approvedAt = "";
      source.dataPublication.error = "";
      s.audit.push({ id: "cancel-on-ignore-" + digest2(receiptKey), time: at, operation: "data.publication.cancel", kind: "sources", objectId: source.id, actor: "\u672C\u4EBA", before: publicationBefore, after: { status: "cancelled", reason: "\u672C\u4EBA\u9009\u62E9\u5FFD\u7565\u5E76\u53D6\u6D88\u672A\u6267\u884C\u7684\u6302\u8F7D\u51C6\u5907" }, revision: s.revision + 1 });
    }
    item.disposition = { state: "ignored", basis: c.basis, at, reason: op.reason || "\u672C\u4EBA\u9009\u62E9\u5FFD\u7565" };
    item.pendingChange = null;
    item.manualAttention = false;
  } else if (op.action === "restore" || op.action === "reopen") {
    if (c.closed && item.nature === "risk") {
      if (!op.reason?.trim()) fail6("\u91CD\u65B0\u6838\u5B9E\u98CE\u9669\u9700\u586B\u5199\u7B80\u77ED\u539F\u56E0");
      item.semanticRevision++;
    }
    if (item.p1) {
      item.p1.lifecycle = { state: "open", reason: op.reason || "\u672C\u4EBA\u91CD\u65B0\u6253\u5F00", at };
      if (item.p1.check?.state === "scheduled" && Date.parse(item.p1.check.effectiveAt || "") <= Date.parse(at)) item.p1.check = { ...item.p1.check, needsReview: true, reviewReason: "\u539F\u68C0\u67E5\u65F6\u95F4\u5DF2\u8FC7\uFF0C\u91CD\u65B0\u5B89\u6392\u524D\u4FDD\u6301\u5F85\u6838\u5BF9" };
    }
    item.disposition = { state: "active", at, reason: op.reason || "\u672C\u4EBA\u6062\u590D\u5173\u6CE8" };
    item.handling = { state: "attention", basis: workItemState(s, source).basis, at };
    item.manualAttention = !businessNature(item.nature);
    item.acknowledgedBasis = "";
    item.notificationBaseline = workItemState(s, source).notificationBasis;
  } else if (op.action === "acknowledge") {
    if (c.actionable || c.pendingChange) fail6("\u8BF7\u5728\u539F\u4E8B\u9879\u5B8C\u6210\u4E1A\u52A1\u5904\u7406\u6216\u6838\u5BF9\u65B0\u53D8\u5316");
    item.acknowledgedBasis = c.basis;
    item.manualAttention = false;
  } else if (op.action === "correct") {
    correctItem(s, source, op.patch || {}, op, at);
    if (businessNature(item.nature) && ensureCore(source).admission === "background") item.core.admission = "managed";
  } else if (op.action === "change-decision") {
    const change = item.pendingChange;
    if (!change || change.id !== op.changeId || !["accept", "reject"].includes(op.decision)) fail6("\u65B0\u53D8\u5316\u5DF2\u66F4\u65B0\uFF0C\u8BF7\u91CD\u65B0\u6838\u5BF9", 409);
    if (op.decision === "reject") {
      if (!op.reason?.trim()) fail6("\u4FDD\u7559\u539F\u5224\u65AD\u65F6\u8BF7\u8BF4\u660E\u7B80\u77ED\u7406\u7531");
      item.rejectedChanges = unique3([...item.rejectedChanges || [], change.id]);
      item.disposition = change.previousDisposition || { state: "active" };
      item.pendingChange = null;
    } else {
      if (item.p1?.lifecycle?.state === "closed") item.p1.lifecycle = { state: "open", reason: op.reason || "\u672C\u4EBA\u91C7\u7528\u65B0\u7684\u5B9E\u8D28\u53D8\u5316", at };
      correctItem(s, source, Object.fromEntries(["title", "summary", "nature", "impact", "nextStep", "urgency"].map((key2) => [key2, change[key2]])), { ...op, riskDecision: op.riskDecision || "pending", reason: op.reason || "\u672C\u4EBA\u91C7\u7EB3\u672C\u6B21\u53D8\u5316" }, at);
    }
    item.notificationBaseline = workItemState(s, source).notificationBasis;
  } else if (op.action === "review") {
    if (item.pendingChange) fail6("\u8BF7\u5148\u6838\u5BF9\u65B0\u7684\u5206\u7C7B\u6216\u5185\u5BB9\u5EFA\u8BAE\uFF0C\u518D\u8BB0\u5F55\u98CE\u9669\u7ED3\u8BBA");
    if (item.nature !== "risk" || !["confirmed", "dismissed", "resolved"].includes(op.decision) || !op.reason?.trim() || !bounded2(op.reason, 1e3)) fail6("\u8BF7\u9009\u62E9\u98CE\u9669\u7ED3\u8BBA\u5E76\u8BF4\u660E\u4F9D\u636E");
    if (c.stale && op.decision !== "dismissed") {
      if (op.addOwnEvidence !== true) fail6("\u539F\u4F9D\u636E\u5DF2\u53D8\u5316\uFF0C\u8BF7\u8865\u5145\u672C\u4EBA\u6838\u5B9E\u4F9D\u636E\u540E\u518D\u8BB0\u5F55", 409);
      ownEvidence(s, source, op.reason, op.requestId, at);
    }
    reviewItem(s, source, op.decision, op.reason.trim(), at);
    item.human = { fields: unique3([...item.human?.fields || [], "nature"]), at, reason: op.reason };
    item.disposition = { state: "active", at };
    item.notificationBaseline = workItemState(s, source).notificationBasis;
  } else if (op.action === "confirm_ready") {
    if (!op.reason?.trim() || c.stale && !c.currentEvidenceReviewed || c.pendingChange) fail6("\u8BF7\u5148\u6838\u5BF9\u5F53\u524D\u4F9D\u636E\u548C\u65B0\u53D8\u5316\uFF0C\u5E76\u8BF4\u660E\u4E0B\u4E00\u6B65");
    item.handling = { state: "attention", basis: c.basis, manuallyReady: true, reason: op.reason, at };
    ensureCore(source).admission = "managed";
  } else if (["take_over", "wait", "resume", "done"].includes(op.action)) {
    if (c.ignored) fail6("\u8BF7\u5148\u6062\u590D\u5173\u6CE8");
    if (item.pendingChange) fail6("\u8BF7\u5148\u6838\u5BF9\u65B0\u53D8\u5316");
    if (op.action === "done" && c.stale && !c.currentEvidenceReviewed) {
      if (item.nature === "risk" || op.addOwnEvidence !== true || !op.reason?.trim()) fail6("\u539F\u4F9D\u636E\u5DF2\u53D8\u5316\uFF0C\u8BF7\u8865\u5145\u672C\u4EBA\u6838\u5B9E\u8BF4\u660E\u540E\u518D\u529E\u7ED3", 409);
      ownEvidence(s, source, op.reason, op.requestId, at);
    }
    if (op.action === "done" && item.nature === "decision" && !op.reason?.trim()) fail6("\u8BF7\u8BB0\u5F55\u672C\u6B21\u51B3\u5B9A\u548C\u7B80\u77ED\u4F9D\u636E");
    if (op.action === "done" && item.nature === "decision") item.decisions = [...item.decisions || [], { basis: c.basis, text: op.reason, at, actor: "\u672C\u4EBA" }];
    if (op.action === "done" && item.nature === "risk" && !c.closed) fail6("\u8BF7\u5148\u5728\u672C\u4E8B\u9879\u8BB0\u5F55\u98CE\u9669\u89E3\u9664\u6216\u7591\u70B9\u4E0D\u6210\u7ACB");
    if (op.action === "wait" && (!op.reason?.trim() || !Number.isFinite(Date.parse(op.nextCheckAt)) || Date.parse(op.nextCheckAt) <= Date.parse(at))) fail6("\u7B49\u5F85\u9700\u586B\u5199\u539F\u56E0\u548C\u672A\u6765\u7684\u8DDF\u8FDB\u65F6\u95F4");
    if (op.action === "done") {
      item.p1 ||= {};
      item.p1.lifecycle = { state: "closed", owner: "manual", reason: op.reason || "\u672C\u4EBA\u786E\u8BA4\u672C\u4E8B\u9879\u5DF2\u529E\u7ED3", at };
    }
    if (op.action === "wait" && item.p1) item.p1.check = { state: "scheduled", effectiveAt: op.nextCheckAt, date: op.nextCheckAt.slice(0, 10), precision: "minute", origin: "legacy-input", at };
    const current = workItemState(s, source);
    item.handling = { manuallyReady: item.handling?.manuallyReady === true, businessBasis: current.business.basis, ...op.action === "done" ? { evidenceBasis: current.liveEvidenceBasis, staleEvidenceBasis: current.staleEvidenceBasis } : {}, state: op.action === "wait" ? "waiting" : op.action === "done" ? "handled" : op.action === "take_over" ? "in_progress" : "attention", reason: String(op.reason || "").slice(0, 1e3), nextCheckAt: op.action === "wait" ? op.nextCheckAt : item.handling?.nextCheckAt || "", basis: c.basis, at };
  } else if (op.action === "split") {
    if (!op.title?.trim() || !op.summary?.trim() || !op.remainingSummary?.trim() || !op.reason?.trim() || !Array.isArray(op.sourceIds) || !op.sourceIds.length || op.sourceIds.some((id2) => !source.sourceIds.includes(id2))) fail6("\u62C6\u5206\u9700\u586B\u5199\u4E24\u8FB9\u5185\u5BB9\u3001\u62C6\u5206\u7406\u7531\uFF0C\u5E76\u9009\u62E9\u539F\u4E8B\u9879\u5185\u7684\u4F9D\u636E");
    if (!bounded2(op.title, 200) || !bounded2(op.summary, 1600) || !bounded2(op.remainingSummary, 1600) || !bounded2(op.impact || "", 1600) || !bounded2(op.nextStep || "", 1600) || !workItemNatures.includes(op.nature)) fail6("\u62C6\u5206\u5185\u5BB9\u6216\u7C7B\u578B\u65E0\u6548");
    const splitIds = op.sourceIds;
    const childId = "work-item-split-" + digest2([s.workspaceId, op.requestId]);
    const child = structuredClone(source);
    child.id = childId;
    child.title = op.title.trim();
    child.excerpt = op.summary.trim();
    child.version = 1;
    child.createdAt = at;
    child.updatedAt = at;
    delete child.dataPublication;
    child.sourceIds = unique3(splitIds);
    child.workItem = {
      ...structuredClone(item),
      triage: null,
      provisional: false,
      nativeFollowup: false,
      nature: op.nature,
      urgency: "normal",
      summary: op.summary.trim(),
      nextStep: op.nextStep || "\u8DDF\u8FDB\u62C6\u5206\u51FA\u7684\u4E8B\u9879",
      impact: op.impact || "",
      semanticRevision: 1,
      reviews: [],
      decisions: [],
      handling: {},
      disposition: { state: "active" },
      pendingChange: null,
      rejectedChanges: [],
      manualAttention: false,
      acknowledgedBasis: "",
      legacyRefs: [],
      businessTarget: null,
      reactivation: null,
      contentHash: "",
      evidence: item.evidence.filter((proof) => splitIds.includes(proof.sourceId)),
      human: { fields: ["nature", "title", "summary"], at, reason: op.reason },
      history: [{ at, operation: "split-from", splitFrom: source.id, reason: op.reason }],
      lastChangedAt: at,
      lastReadAt: at
    };
    if (!child.workItem.evidence.length) fail6("\u672A\u9009\u5230\u53EF\u8FFD\u6EAF\u7684\u62C6\u5206\u4F9D\u636E");
    if (op.nature === "risk" && (!child.workItem.impact.trim() || !["pending", "confirmed"].includes(op.riskDecision))) fail6("\u62C6\u5206\u4E3A\u98CE\u9669\u65F6\u9700\u8BF4\u660E\u5F71\u54CD\u5E76\u9009\u62E9\u6838\u5B9E\u72B6\u6001");
    s.sources.push(child);
    child.workItem.handling = { state: "attention", manuallyReady: op.nature === "action", basis: workItemState(s, child).basis, at };
    if (op.nature === "risk" && op.riskDecision === "confirmed") {
      ownEvidence(s, child, op.reason, op.requestId, at);
      reviewItem(s, child, "confirmed", op.reason, at);
    }
    child.workItem.notificationBaseline = workItemState(s, child).notificationBasis;
    if (!businessNature(op.nature)) child.workItem.acknowledgedBasis = workItemState(s, child).basis;
    item.summary = op.remainingSummary.trim();
    source.excerpt = item.summary;
    item.human = { fields: unique3([...item.human?.fields || [], "summary"]), at, reason: op.reason };
    item.contentHash = "";
    item.manualAttention = false;
    if (!businessNature(item.nature)) item.acknowledgedBasis = workItemState(s, source).basis;
    item.history.push({ at, operation: "split-to", splitTo: childId, reason: op.reason });
    op = { ...op, splitSourceId: childId };
  } else if (op.action === "merge") {
    const target = s.sources.find((row) => row.id === op.targetId && row.workItem && active2(row));
    if (!target || target.id === source.id || target.version !== op.targetVersion || !op.reason?.trim()) fail6("\u5408\u5E76\u76EE\u6807\u5DF2\u53D8\u5316\u6216\u7F3A\u5C11\u7406\u7531", 409);
    if ([source, target].some((row) => ["publishing", "unknown", "partial"].includes(row.dataPublication?.status) || row.dataPublication?.artifact && row.dataPublication.status !== "verified")) fail6("\u8BF7\u5148\u6838\u5BF9\u5DF2\u6709\u6302\u8F7D\u6267\u884C\u7ED3\u679C\uFF0C\u518D\u5408\u5E76\u4E8B\u9879", 409);
    if (item.pendingChange && target.workItem.pendingChange && item.pendingChange.id !== target.workItem.pendingChange.id) fail6("\u4E24\u4E2A\u4E8B\u9879\u90FD\u6709\u65B0\u53D8\u5316\uFF0C\u8BF7\u5148\u6838\u5BF9\u5404\u81EA\u5EFA\u8BAE\u540E\u518D\u5408\u5E76");
    if (item.association.confirmed && target.workItem.association.confirmed && JSON.stringify([item.association.kind, item.association.id]) !== JSON.stringify([target.workItem.association.kind, target.workItem.association.id])) fail6("\u4E24\u4E2A\u4E8B\u9879\u7684\u5DF2\u786E\u8BA4\u5F52\u5C5E\u4E0D\u540C\uFF0C\u8BF7\u5148\u6838\u5BF9\u5F52\u5C5E");
    target.workItem.evidence = [...new Map([...target.workItem.evidence, ...item.evidence].map((e) => [e.key, e])).values()];
    target.sourceIds = unique3(target.workItem.evidence.map((e) => e.sourceId));
    target.workItem.legacyRefs = unique3([...target.workItem.legacyRefs, ...item.legacyRefs]);
    target.workItem.history.push({ at, operation: "merge", mergedFrom: source.id, title: source.title, summary: item.summary, reviews: item.reviews, decisions: item.decisions || [], handling: item.handling, disposition: item.disposition, pendingChange: item.pendingChange, reason: op.reason });
    if (c.nature === "risk") target.workItem.nature = "risk";
    if (c.urgent) target.workItem.urgency = "urgent";
    if (item.pendingChange && !target.workItem.pendingChange) target.workItem.pendingChange = { ...structuredClone(item.pendingChange), previousDisposition: structuredClone(target.workItem.disposition || { state: "active" }) };
    if (c.knownConfirmedRisk) {
      const prior = item.reviews.findLast((review) => review.decision === "confirmed");
      if (prior) target.workItem.reviews.push({ ...structuredClone(prior), basis: "merged-" + digest2([source.id, prior.basis, op.requestId]), originalBasis: prior.basis, mergedFromSourceId: source.id });
    }
    target.workItem.disposition = { state: "active", at };
    target.workItem.human = { fields: unique3([...target.workItem.human?.fields || [], "nature"]), at, reason: op.reason };
    target.workItem.semanticRevision++;
    target.workItem.lastChangedAt = at;
    target.version++;
    target.updatedAt = at;
    item.mergedIntoId = target.id;
    target.workItem.notificationBaseline = workItemState(s, target).notificationBasis;
    for (const row of s.sources) {
      if (row.managementSignal?.workItemId === source.id) row.managementSignal.workItemId = target.id;
      for (const signal of row.intakeBatch?.signals || []) if (signal.workItemId === source.id) signal.workItemId = target.id;
    }
  } else fail6("\u4E0D\u652F\u6301\u7684\u4E8B\u9879\u64CD\u4F5C");
  if (["correct", "p1-undo", "p1-submit", "reopen", "restore", "change-decision"].includes(op.action)) invalidateCoreDerivations(s, source, at, op.action);
  if (item.p1?.lifecycle?.state === "closed" && item.p1.lifecycle.at === at) item.p1.lifecycle.owner = "manual";
  if (["done", "reopen", "restore", "ignore", "change-decision"].includes(op.action)) {
    const core = ensureCore(source);
    core.instructionAt = { ...core.instructionAt || {}, lifecycle: at };
  }
  if (op.action === "review") {
    const core = ensureCore(source);
    core.instructionAt = { ...core.instructionAt || {}, riskDecision: at, ...workItemState(s, source).closed ? { lifecycle: at } : {} };
  }
  reconcileCoreReopenProposal(s, source, at, { decided: ["done", "reopen", "restore", "ignore", "change-decision"].includes(op.action) });
  item.history.push({ at, operation: op.action, reason: op.reason || "", title: previousTitle, summary: before.summary, nature: before.nature, disposition: before.disposition, handling: before.handling, pendingChange: before.pendingChange });
  item.lastChangedAt = at;
  source.version++;
  source.updatedAt = at;
  s.revision++;
  s.receipts[receiptKey] = { fingerprint: hash3, result: { sourceId: source.id, ...p1Result || {}, ...op.splitSourceId ? { splitSourceId: op.splitSourceId } : {} } };
  s.audit.push({ id: "work-item-" + digest2([receiptKey, hash3]), time: at, operation: "work-item." + op.action, kind: "sources", objectId: source.id, actor: "\u672C\u4EBA", before, after: structuredClone(item), revision: s.revision });
  return s;
}
function connectLegacyWorkItems(s, at, { historical = false } = {}) {
  let changed = false;
  for (const source of [...s.sources]) {
    if (source.archived) continue;
    if (source.managementSignal?.workItemId) {
      const m = source.managementSignal, current = managementSignalState(s, source), item = s.sources.find((row) => row.id === m.workItemId && row.workItem && active2(row));
      if (!item || m.workItemBasis === current.basis) continue;
      if (!m.workItemBasis) {
        m.workItemBasis = current.basis;
        changed = true;
        continue;
      }
      if (current.available && !current.stale) {
        const sourceIds = unique3([m.sourceId, ...source.sourceIds]).filter((id2) => s.sources.some((row) => row.id === id2 && caseEvidenceAvailable(s, row)));
        if (sourceIds.length) applyWorkItemFindings(s, [{ existingItemId: item.id, expectedVersion: item.version, matchReason: "\u540C\u4E00\u7CFB\u7EDF\u63D0\u793A\u7684\u540E\u7EED\u4F9D\u636E\u53D8\u5316", materialChange: !current.ruleSatisfied || !workItemState(s, item).closed, title: m.triage?.title || item.title, summary: current.currentSummary, nextStep: current.ruleSatisfied ? "\u6838\u5BF9\u5F53\u524D\u4F9D\u636E\uFF0C\u786E\u8BA4\u662F\u5426\u53EF\u4EE5\u89E3\u9664\u672C\u4E8B\u9879" : m.nextStep, impact: current.ruleSatisfied ? current.currentSummary : m.triage?.impact || item.workItem.impact, nature: item.workItem.nature, urgency: current.ruleSatisfied ? "normal" : m.triage?.urgency || item.workItem.urgency, sourceIds, association: item.workItem.association, legacyRefs: [source.id] }], at);
      }
      m.workItemBasis = current.basis;
      changed = true;
    }
    if (source.managementSignal && !source.managementSignal.workItemId) {
      const m = source.managementSignal, original = s.sources.find((row) => row.id === m.sourceId);
      if (!original || !caseEvidenceAvailable(s, original) || m.priority !== "attention" || m.historical) continue;
      const current = managementSignalState(s, source);
      if (!current.open && !current.previous) continue;
      const linked = sourceWorkItems(s, original.id).filter((row) => row.workItem.legacyRefs.includes(source.id));
      const target = m.target, record2 = target ? s[target.kind]?.find((row) => row.id === target.id) : null, project = target?.kind === "projects" ? target.id : record2?.projectIds?.length === 1 ? record2.projectIds[0] : original.projectIds?.length === 1 ? original.projectIds[0] : "";
      const association = { kind: target?.kind === "cases" ? "case" : project ? "project" : "unknown", id: target?.kind === "cases" ? target.id : project, confirmed: !!target || !!project, reason: "\u6CBF\u7528\u5DF2\u6709\u4E8B\u9879\u5173\u8054" };
      const id2 = linked[0]?.id || "work-item-" + digest2(source.id);
      if (!linked.length) {
        applyWorkItemFindings(s, [{ id: id2, title: source.title, summary: m.summary, nextStep: m.nextStep, impact: m.triage?.impact || "", nature: m.origin === "rule" || m.triage?.kind === "risk" ? "risk" : "action", urgency: m.triage?.urgency || "normal", sourceIds: unique3([original.id, ...source.sourceIds]).filter((id3) => s.sources.some((row) => row.id === id3 && caseEvidenceAvailable(s, row))), association, legacyRefs: [source.id], ...target ? { businessTarget: target } : {} }], at);
        const item = s.sources.find((row) => row.id === id2), basis = workItemState(s, item).basis;
        item.workItem.history.push({ at, legacySourceId: source.id, reviews: structuredClone(m.reviews || []) });
        const last = managementSignalState(s, source).review;
        if (last) item.workItem.reviews.push({ ...last, basis, legacySourceId: source.id });
        if (historical) item.workItem.notificationBaseline = basis;
      }
      m.workItemId = id2;
      m.workItemBasis = current.basis;
      changed = true;
    }
    for (const signal of source.intakeBatch?.signals || []) {
      if (signal.workItemId || source.intakeBatch.revertedAt || !["risk", "followup"].includes(signal.kind) && signal.urgency !== "urgent") continue;
      const original = s.sources.find((row) => row.id === signal.sourceId);
      if (!original || !caseEvidenceAvailable(s, original)) continue;
      const target = s.projects.find((row) => row.id === signal.targetId), id2 = signal.existingItemId || "work-item-" + digest2([source.id, signal.id]);
      const targetKind = ["deliverables", "actions", "flowNodes", "cases"].find((kind) => s[kind].some((row) => row.id === signal.targetId));
      const parent = targetKind ? s[targetKind].find((row) => row.id === signal.targetId) : null, project = target?.id || (parent?.projectIds.length === 1 ? parent.projectIds[0] : "");
      applyWorkItemFindings(s, [{ id: id2, existingItemId: signal.existingItemId || "", expectedVersion: signal.workItemVersion, matchReason: signal.matchReason, materialChange: signal.materialChange, triage: signal.triage, title: signal.title, summary: signal.reason || signal.title, nextStep: signal.question || "\u6838\u5BF9\u4F9D\u636E\u5E76\u5B89\u6392\u4E0B\u4E00\u6B65", impact: signal.reason || "", nature: signal.kind === "risk" || signal.urgency === "urgent" ? "risk" : "action", urgency: signal.urgency || "normal", sourceIds: [signal.sourceId], association: { kind: project ? "project" : "unknown", id: project, reason: "\u6CBF\u7528\u8D44\u6599\u6574\u7406\u7ED3\u679C", confirmed: !!project }, legacyRefs: [source.id + ":" + signal.id], ...targetKind ? { businessTarget: { kind: targetKind, id: signal.targetId } } : {} }], at);
      const item = s.sources.find((row) => row.id === id2);
      item.workItem.history.push({ at, legacyBatchId: source.id, reviews: structuredClone(source.intakeBatch.signalReviews || []) });
      const last = riskSignalState(s, source, signal, source.intakeBatch.signals.indexOf(signal)).review;
      if (last) item.workItem.reviews.push({ ...last, basis: workItemState(s, item).basis, legacyBatchId: source.id });
      if (historical && !signal.existingItemId) item.workItem.notificationBaseline = workItemState(s, item).basis;
      signal.workItemId = id2;
      changed = true;
    }
  }
  return changed;
}

// lib/comment-feedback.ts
var feedbackCollectFrom = "2026-09-28T13:47:33+08:00";
var text10 = (v) => typeof v === "string" ? v.trim() : "";
var object5 = (v) => v && typeof v === "object" && !Array.isArray(v) ? v : {};
var ids6 = (v) => Array.isArray(v) ? v.filter((id2) => typeof id2 === "string") : [];
var accepted3 = (r) => ["\u5DF2\u9A8C\u6536", "\u9A8C\u6536\u901A\u8FC7", "\u5DF2\u901A\u8FC7", "\u901A\u8FC7"].includes(r.acceptanceStatus) || ["\u5DF2\u5173\u95ED", "\u5DF2\u89E3\u9664", "\u5DF2\u53D6\u6D88"].includes(r.status);
var canonical2 = (v) => JSON.stringify(v, (_k, x) => x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, x[k]])) : x);
var pending = (version) => ({ status: "pending", summary: "", kind: "progress", responseTo: [], evidence: [], uncertainties: [], contentVersion: version, analysedAt: "", error: "", provider: "", contexts: {} });
function isCommentFeedback(source) {
  return source.feedback?.schemaVersion === 1 && ["meegle-deliverable-comment", "feishu-task-comment", "feishu-task-update", "feishu-task-attachment"].includes(source.feedback.channel);
}
function feedbackTarget(s, source) {
  return (source.feedback?.channel === "meegle-deliverable-comment" ? s.deliverables : s.actions).find((row) => row.id === source.feedback?.targetId && !row.archived);
}
function taskFeedbackLinks(s, projectIds2, caseIds = []) {
  return s.externalLinks.filter((link) => !link.archived && link.system === "feishu_tasks" && link.remoteKind === "task" && link.host === "applink.feishu.cn" && link.verified === true && /^[A-Za-z0-9_-]+\/[A-Za-z0-9_-]+$/.test(link.spaceKey) && s.actions.some((a) => a.id === link.localObjectId && !a.archived && (a.projectIds.some((id2) => projectIds2.includes(id2)) || a.caseId && caseIds.includes(a.caseId))));
}
function feedbackRelated(s, source, target) {
  if (!isCommentFeedback(source)) return false;
  const origin = feedbackTarget(s, source);
  if (!origin) return false;
  if (!source.projectIds.some((id2) => target.projectIds.includes(id2)) && !(origin.caseId && origin.caseId === target.caseId)) return false;
  return origin.id === target.id || ids6(origin.outputIds).includes(target.id) || ids6(origin.actionIds).includes(target.id) || ids6(target.outputIds).includes(origin.id) || ids6(target.actionIds).includes(origin.id);
}
function feedbackTime(value) {
  if (typeof value === "number" || typeof value === "string" && /^\d{10,13}$/.test(value)) {
    const n = Number(value), d = new Date(n < 1e12 ? n * 1e3 : n);
    return Number.isFinite(d.getTime()) ? d.toISOString() : "";
  }
  const v = text10(value);
  return /^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v)) ? new Date(v).toISOString() : "";
}
function authorOf(raw, people) {
  const value = raw.creator ?? raw.author ?? raw.created_by, person = object5(value), id2 = String(person.id ?? person.key ?? person.user_key ?? (typeof value === "string" ? value : ""));
  return { id: id2, name: text10(person.name || person.display_name || raw.creator_name) || (id2 ? people.find((p) => !p.archived && [p.id, p.meegleUserKey, p.feishuUserId].includes(id2))?.title : "") || "\u4F5C\u8005\u5F85\u6838\u5BF9" };
}
function ingestCommentFeedback(input, reads, scope) {
  const state = structuredClone(input), issues = [], changed = [];
  let historical = 0, unchanged = 0;
  const boundary = Date.parse(scope.collectFrom);
  if (!Number.isFinite(boundary) || boundary < Date.parse(feedbackCollectFrom)) throw Error("\u91C7\u96C6\u8D77\u70B9\u65E9\u4E8E\u5DF2\u786E\u8BA4\u8303\u56F4");
  for (const read of reads) {
    const channel = read.channel || "meegle-deliverable-comment", taskChannel = channel.startsWith("feishu-task-");
    if (!["meegle-deliverable-comment", "feishu-task-comment", "feishu-task-update", "feishu-task-attachment"].includes(channel)) {
      issues.push("\u4E0D\u652F\u6301\u7684\u53CD\u9988\u6765\u6E90");
      continue;
    }
    const remote = taskChannel ? taskFeedbackLinks(state, scope.projectIds).find((r) => r.id === read.externalObjectId && r.remoteId === read.remoteId && r.spaceKey === read.spaceKey) : state.externalObjects.find((r) => r.id === read.externalObjectId && r.workspaceId === state.workspaceId && r.system === "meegle" && r.host === "project.feishu.cn" && r.remoteKind === "deliverable" && r.remoteId === read.remoteId && r.spaceKey === read.spaceKey && r.verificationStatus === "verified" && !["unmapped", "quarantined", "conflict"].includes(r.mappingStatus));
    const target = remote && (taskChannel ? state.actions : state.deliverables).find((d) => d.id === remote.localObjectId && !d.archived);
    if (!remote || !target || !target.projectIds.some((id2) => scope.projectIds.includes(id2))) {
      issues.push("\u8BC4\u8BBA\u5BF9\u8C61\u4E0D\u5728\u5DF2\u6838\u5BF9\u7684\u91C7\u96C6\u8303\u56F4");
      continue;
    }
    if (taskChannel && read.viewer && remote.accountId && read.viewer.id !== remote.accountId) {
      issues.push("\u4EFB\u52A1\u53CD\u9988\u7684\u8BFB\u53D6\u8D26\u53F7\u4E0D\u5339\u914D");
      continue;
    }
    if (!read.complete || read.error || !Array.isArray(read.comments) || !Number.isFinite(Date.parse(read.collectedAt))) {
      issues.push(target.title + "\uFF1A\u8BC4\u8BBA\u8BFB\u53D6\u672A\u5B8C\u6210");
      continue;
    }
    for (const value of read.comments) {
      const raw = object5(value), rawId = raw.comment_id ?? raw.id, commentId = typeof rawId === "number" && !Number.isSafeInteger(rawId) ? "" : String(rawId ?? "");
      if (![...taskChannel ? read.spaceKey.split("/") : [read.spaceKey], read.remoteId, commentId].every((id2) => /^[A-Za-z0-9_-]{1,65}$/.test(id2))) {
        issues.push(target.title + "\uFF1A\u8BC4\u8BBA\u7F3A\u5C11\u7A33\u5B9A\u8EAB\u4EFD");
        continue;
      }
      if (raw.work_item_id !== void 0 && String(raw.work_item_id) !== read.remoteId) {
        issues.push(target.title + "\uFF1A\u8BC4\u8BBA\u5BF9\u8C61\u8EAB\u4EFD\u4E0D\u5339\u914D");
        continue;
      }
      if (taskChannel && (raw.task_guid && raw.task_guid !== read.remoteId || raw.resource && (raw.resource.id !== read.remoteId || raw.resource.type !== "task"))) {
        issues.push(target.title + "\uFF1A\u53CD\u9988\u6240\u5C5E\u4EFB\u52A1\u4E0D\u5339\u914D");
        continue;
      }
      const sourceId = taskChannel ? `feedback:${channel.slice(7)}:${read.spaceKey.replace("/", ":")}:${read.remoteId}:${commentId}` : `feedback:${read.spaceKey}:${read.remoteId}:${commentId}`;
      if (sourceId.length > 160) {
        issues.push(target.title + "\uFF1A\u8BC4\u8BBA\u8EAB\u4EFD\u8FC7\u957F");
        continue;
      }
      const created = feedbackTime(raw.created_at ?? raw.create_time ?? raw.createdAt), updated = feedbackTime(raw.updated_at ?? raw.update_time ?? raw.updatedAt);
      const eventAt = updated && (!created || updated > created) ? updated : created;
      if (eventAt && Date.parse(eventAt) < boundary) {
        historical++;
        continue;
      }
      if (eventAt && Date.parse(eventAt) > Date.parse(read.collectedAt)) {
        issues.push(target.title + "\uFF1A\u53CD\u9988\u65F6\u95F4\u665A\u4E8E\u91C7\u96C6\u65F6\u95F4\uFF0C\u5F85\u6838\u5BF9");
        continue;
      }
      if (!eventAt && !read.rangeVerified) {
        issues.push(target.title + "\uFF1A\u6765\u6E90\u65F6\u95F4\u672A\u660E\u786E\uFF0C\u6682\u4E0D\u81EA\u52A8\u7EB3\u5165");
        continue;
      }
      const content = text10(raw.content ?? raw.text ?? raw.body), deleted = raw.deleted === true || raw.is_deleted === true;
      if (content.length > 1e5 || canonical2(raw).length > 18e4) {
        issues.push(target.title + "\uFF1A\u8BC4\u8BBA\u5185\u5BB9\u8FC7\u957F\uFF0C\u4FDD\u7559\u8FDC\u7AEF\u539F\u6587\u5F85\u6838\u5BF9");
        continue;
      }
      const previous = state.sources.find((s) => s.id === sourceId);
      if (previous && !isCommentFeedback(previous)) {
        issues.push(target.title + "\uFF1A\u6765\u6E90\u8EAB\u4EFD\u51B2\u7A81");
        continue;
      }
      if (previous && canonical2(previous.feedback.raw) === canonical2(raw) && previous.feedback.targetId === target.id && canonical2(previous.projectIds) === canonical2(target.projectIds.filter((id2) => scope.projectIds.includes(id2)))) {
        unchanged++;
        continue;
      }
      if (previous?.feedback.eventAt && eventAt && previous.feedback.eventAt > eventAt) {
        unchanged++;
        continue;
      }
      const author = authorOf(raw, state.people), version = (previous?.feedback.contentVersion || 0) + 1;
      const outgoing = state.sources.some((source2) => source2.commentDispatch?.commentId === commentId && source2.commentDispatch.target?.spaceKey === remote.spaceKey && String(source2.commentDispatch.target.remoteId) === String(remote.remoteId) && source2.commentDispatch.actor?.userKey === author.id);
      if (channel === "feishu-task-update") author.name += "\uFF08\u4EFB\u52A1\u521B\u5EFA\u4EBA\uFF1B\u66F4\u65B0\u4EBA\u672A\u63D0\u4F9B\uFF09";
      const feedback = {
        schemaVersion: 1,
        channel,
        viewer: read.viewer,
        observationOnly: taskChannel && remote.handling === "progress",
        externalObjectId: remote.id,
        spaceKey: remote.spaceKey,
        remoteId: remote.remoteId,
        commentId,
        targetId: target.id,
        authorId: author.id,
        author: author.name,
        originalTime: String(raw.created_at ?? raw.create_time ?? raw.createdAt ?? ""),
        updatedTime: String(raw.updated_at ?? raw.update_time ?? raw.updatedAt ?? ""),
        eventAt,
        timeUncertain: !eventAt,
        contentVersion: version,
        raw: structuredClone(raw),
        history: previous ? [...previous.feedback.history || [], { version: previous.feedback.contentVersion, raw: previous.feedback.raw, collectedAt: previous.collectedAt }] : [],
        deleted,
        analysis: pending(version),
        reviewedVersion: 0,
        reviewedAt: ""
      };
      if (!content || deleted) feedback.analysis = { ...pending(version), status: "ready", kind: "needs_confirmation", summary: deleted ? "\u6E90\u8BC4\u8BBA\u5DF2\u5220\u9664\uFF0C\u4FDD\u7559\u8BFB\u53D6\u8BB0\u5F55\u4F9B\u6838\u5BF9\u3002" : "\u53CD\u9988\u6B63\u6587\u4E3A\u7A7A\u6216\u53EA\u6709\u9644\u4EF6\uFF0C\u8BF7\u6253\u5F00\u6765\u6E90\u6838\u5BF9\u3002", provider: "\u6765\u6E90\u63D0\u793A", analysedAt: read.collectedAt };
      if (outgoing) {
        feedback.outgoing = true;
        feedback.observationOnly = true;
        feedback.analysis = { ...pending(version), status: "ready", kind: deleted ? "needs_confirmation" : "progress", summary: deleted ? "\u672C\u4EBA\u53D1\u51FA\u7684\u8BC4\u8BBA\u5DF2\u64A4\u56DE\uFF0C\u8BF7\u6838\u5BF9\u539F\u8981\u6C42\u3002" : "\u672C\u4EBA\u5DF2\u53D1\u51FA\u7684\u4EA4\u4ED8\u7269\u8BC4\u8BBA\uFF0C\u4FDD\u7559\u6C9F\u901A\u8BB0\u5F55\u3002", provider: "\u5DF2\u56DE\u8BFB\u7684\u672C\u4EBA\u8BC4\u8BBA", analysedAt: read.collectedAt, viewerAction: deleted };
      }
      if (channel === "feishu-task-attachment") feedback.analysis = { ...pending(version), status: "ready", kind: "needs_confirmation", summary: "\u65B0\u589E\u4EFB\u52A1\u9644\u4EF6\uFF0C\u8BF7\u6838\u5BF9\u6587\u4EF6\u5185\u5BB9\uFF1B\u4E0A\u4F20\u9644\u4EF6\u4E0D\u4EE3\u8868\u6210\u679C\u5DF2\u9A8C\u6536\u3002", provider: "\u6765\u6E90\u63D0\u793A", analysedAt: read.collectedAt };
      const source = { ...previous || {}, id: sourceId, title: (taskChannel ? "\u4EFB\u52A1\u53CD\u9988 \xB7 " : "\u4EA4\u4ED8\u7269\u53CD\u9988 \xB7 ") + target.title, projectIds: target.projectIds.filter((id2) => scope.projectIds.includes(id2)), sourceIds: [], objectIds: [target.id], type: taskChannel ? { "feishu-task-comment": "\u98DE\u4E66\u4EFB\u52A1\u8BC4\u8BBA", "feishu-task-update": "\u98DE\u4E66\u4EFB\u52A1\u6B63\u6587", "feishu-task-attachment": "\u98DE\u4E66\u4EFB\u52A1\u9644\u4EF6" }[channel] : "\u98DE\u4E66\u4EA4\u4ED8\u7269\u8BC4\u8BBA", excerpt: content, author: author.name, occurredAt: created, collectedAt: read.collectedAt, confirmed: false, processingStatus: outgoing ? "\u5DF2\u6574\u7406" : "\u5F85\u6574\u7406", feedback, version: (previous?.version || 0) + 1, updatedAt: read.collectedAt };
      if (previous) Object.assign(previous, source);
      else state.sources.push(source);
      changed.push(sourceId);
    }
  }
  if (changed.length) {
    state.revision = input.revision + 1;
    state.audit.push({ id: "feedback-ingest-" + state.revision, time: reads.at(-1)?.collectedAt || (/* @__PURE__ */ new Date()).toISOString(), operation: "feedback.ingest", objectId: "feedback", actor: "\u98DE\u4E66\u53EA\u8BFB\u53CD\u9988", before: { revision: input.revision }, after: { sourceIds: [...new Set(changed)] }, revision: state.revision });
  }
  return { state: changed.length ? state : input, changed: [...new Set(changed)], issues, historical, unchanged };
}
function followupSignature(row, kind) {
  return canonical2({ id: row.id, kind, title: row.title, followUp: row.followUp || "", blocker: row.blocker || "", status: row.status || "", executionStatus: row.executionStatus || "", acceptanceStatus: row.acceptanceStatus || "", checkAt: row.checkAt || "", dueAt: row.dueAt || "", lastContactAt: row.lastContactAt || "", projectIds: row.projectIds });
}
function feedbackCandidates(s, source) {
  if (!isCommentFeedback(source) || source.feedback.observationOnly) return [];
  const f = source.feedback, target = feedbackTarget(s, source);
  if (!target) return [];
  const rows2 = [...s.actions.filter((a) => !a.archived && feedbackRelated(s, source, a)).map((row) => ({ row, kind: "actions" })), ...s.deliverables.filter((d) => !d.archived && feedbackRelated(s, source, d) && (isBlocked(d) || needsFollowUp(d))).map((row) => ({ row, kind: "deliverables" }))];
  return rows2.filter(({ row }) => !accepted3(row) && (!f.eventAt || !feedbackTime(row.updatedAt) || f.eventAt >= feedbackTime(row.updatedAt)) && (isBlocked(row) || needsFollowUp(row) || !!text10(row.followUp) || row.status === "\u7B49\u5F85\u4ED6\u4EBA\u53CD\u9988")).map(({ row, kind }) => ({ id: row.id, kind, title: row.title, followUp: text10(row.followUp), blocker: text10(row.blocker), status: text10(row.status), dueAt: text10(row.dueAt), checkAt: text10(row.checkAt), signature: followupSignature(row, kind) }));
}
function applyFeedbackAnalysis(input, sourceId, version, result, context, at = (/* @__PURE__ */ new Date()).toISOString()) {
  const state = structuredClone(input), source = state.sources.find((s) => s.id === sourceId), data = object5(result);
  if (!source || !isCommentFeedback(source) || source.feedback.contentVersion !== version || source.archived) throw Error("\u53CD\u9988\u5185\u5BB9\u5DF2\u53D8\u5316\uFF0C\u5DF2\u4E22\u5F03\u65E7\u6458\u8981");
  if (!["progress", "response", "needs_confirmation"].includes(data.kind) || !text10(data.summary) || data.summary.length > 240 || !Array.isArray(data.responseTo) || !Array.isArray(data.evidence) || !Array.isArray(data.uncertainties)) throw Error("AI \u6458\u8981\u683C\u5F0F\u65E0\u6548");
  if (data.evidence.length < 1 || data.evidence.length > 3 || data.evidence.some((q) => typeof q !== "string" || !q.trim() || q.length > 400 || !source.excerpt.includes(q))) throw Error("AI \u6458\u8981\u4F9D\u636E\u672A\u5BF9\u5E94\u6765\u6E90\u539F\u6587");
  const current = new Map(feedbackCandidates(state, source).map((c) => [c.id, c]));
  if (data.responseTo.length > 10 || new Set(data.responseTo).size !== data.responseTo.length || data.responseTo.some((id2) => typeof id2 !== "string" || !context.some((c) => c.id === id2) || current.get(id2)?.signature !== context.find((c) => c.id === id2)?.signature)) throw Error("\u76F8\u5173\u8DDF\u8FDB\u4E8B\u9879\u5DF2\u53D8\u5316\u6216\u8D85\u51FA\u5173\u8054\u8303\u56F4");
  if (data.kind === "response" && !data.responseTo.length || data.kind !== "response" && data.responseTo.length) throw Error("\u53CD\u9988\u5F52\u7C7B\u4E0E\u5173\u8054\u4E8B\u9879\u4E0D\u4E00\u81F4");
  if (data.uncertainties.length > 3 || data.uncertainties.some((v) => typeof v !== "string" || v.length > 240)) throw Error("\u5F85\u6838\u5BF9\u8BF4\u660E\u65E0\u6548");
  const viewer = source.feedback.viewer, names = [viewer?.id, viewer?.name, viewer?.name?.replace(/^AR\d+\s*/i, "")].filter(Boolean);
  if (data.viewerAction !== void 0 && typeof data.viewerAction !== "boolean" || data.viewerAction === true && (data.kind !== "needs_confirmation" || !data.evidence.some((quote) => names.some((name) => quote.includes(name))))) throw Error("\u5F85\u672C\u4EBA\u5904\u7406\u7684\u8BF7\u6C42\u7F3A\u5C11\u660E\u786E\u5BF9\u8C61\u548C\u539F\u6587\u4F9D\u636E");
  source.feedback.analysis = { status: "ready", summary: data.summary, kind: data.kind, responseTo: data.responseTo, evidence: data.evidence, uncertainties: data.uncertainties, viewerAction: data.viewerAction === true, contentVersion: version, analysedAt: at, error: "", provider: "Codex AI", contexts: Object.fromEntries(context.map((c) => [c.id, c.signature])) };
  if (source.feedback.timeUncertain) source.feedback.analysis.uncertainties = [...data.uncertainties.slice(0, 2), "\u6765\u6E90\u65F6\u95F4\u672A\u660E\u786E\u65F6\u533A\uFF0C\u56DE\u590D\u5148\u540E\u4ECD\u9700\u6838\u5BF9\u3002"];
  source.version = (source.version || 1) + 1;
  source.updatedAt = at;
  state.revision++;
  state.audit.push({ id: "feedback-summary-" + state.revision, time: at, operation: "feedback.summary", objectId: sourceId, actor: "AI \u6458\u8981", before: null, after: { contentVersion: version, kind: data.kind }, revision: state.revision });
  return state;
}
function reviewCommentFeedback(input, sourceId, version, at = (/* @__PURE__ */ new Date()).toISOString()) {
  const state = structuredClone(input), source = state.sources.find((s) => s.id === sourceId && !s.archived);
  if (!source || !isCommentFeedback(source) || source.feedback.contentVersion !== version) throw Error("\u53CD\u9988\u5DF2\u66F4\u65B0\uFF0C\u8BF7\u91CD\u65B0\u67E5\u770B\u540E\u6838\u5BF9");
  if (source.feedback.reviewedVersion === version) return input;
  source.feedback.reviewedVersion = version;
  source.feedback.reviewedAt = at;
  source.version = (source.version || 1) + 1;
  source.updatedAt = at;
  state.revision++;
  state.audit.push({ id: "feedback-review-" + state.revision, time: at, operation: "feedback.review", objectId: sourceId, actor: "\u672C\u4EBA", before: null, after: { contentVersion: version, meaning: "\u5DF2\u6838\u5BF9\u53CD\u9988\uFF0C\u4FDD\u7559\u539F\u5DE5\u4F5C\u72B6\u6001" }, revision: state.revision });
  return state;
}
function pendingResponseSources(s, targetId) {
  const target = s.actions.find((a) => a.id === targetId) || s.deliverables.find((a) => a.id === targetId);
  if (!target || target.archived || accepted3(target)) return [];
  const kind = s.actions.some((a) => a.id === targetId) ? "actions" : "deliverables";
  return s.sources.filter((source) => {
    if (source.archived || !isCommentFeedback(source) || workItemOwnsFeedback(s, source.id)) return false;
    const f = source.feedback, a = f.analysis;
    const linked = feedbackRelated(s, source, target);
    return linked && !f.deleted && a.status === "ready" && a.kind === "response" && a.contentVersion === f.contentVersion && f.reviewedVersion !== f.contentVersion && a.responseTo.includes(targetId) && a.contexts?.[targetId] === followupSignature(target, kind);
  });
}

// lib/feishu-collaboration.ts
var collaborationKinds = ["flowNodes", "deliverables", "externalLinks"];
var th2FeishuFieldKeys = Object.freeze({
  projectDescription: "description",
  projectProgress: "field_5a13c8",
  deliverableDescription: "description",
  deliverableProgress: "field_d014b4",
  deliverableReview: "field_b462b3"
});
var feishuFieldMap = {
  projectDescription: "description",
  projectProgress: "field_5a13c8",
  deliverableDescription: "description",
  deliverableProgress: "field_d014b4",
  deliverableReview: "field_b462b3",
  deliverableStatus: "status"
};
var deliverableStatuses = ["\u672A\u5F00\u59CB", "\u8FDB\u884C\u4E2D", "\u5DF2\u7ED3\u675F"];
var deliverableReviews = ["\u672A\u5BA1\u6838", "\u5DF2\u5BA1\u6838"];
var optionText = (value) => {
  if (typeof value === "string") return value.trim();
  if (value && typeof value === "object") {
    const row = value;
    for (const key2 of ["name", "label", "value", "display_name", "displayName", "text"]) if (typeof row[key2] === "string" && row[key2].trim()) return row[key2].trim();
  }
  return "";
};
function normalizeDeliverableMigration(input) {
  const value = optionText(input[feishuFieldMap.deliverableStatus]);
  const review = optionText(input.deliveryReview ?? input.reviewStatus ?? input[feishuFieldMap.deliverableReview]);
  const status2 = deliverableStatuses.includes(value) ? value : "\u672A\u5F00\u59CB";
  const normalizedReview = review === "\u5DF2\u5BA1\u6838" ? "\u5DF2\u5BA1\u6838" : "\u672A\u5BA1\u6838";
  const progress = input.deliverableProgress ?? input.progressNote ?? input[feishuFieldMap.deliverableProgress] ?? "";
  return {
    ...input,
    description: input.description ?? input[feishuFieldMap.deliverableDescription] ?? "",
    deliverableProgress: typeof progress === "string" ? progress : "",
    deliveryReview: normalizedReview,
    // reviewStatus remains as a compatibility alias for older local snapshots.
    reviewStatus: normalizedReview,
    status: status2
  };
}
function normalizeProjectMigration(input) {
  const progress = input.projectProgress ?? input.progressNote ?? input[feishuFieldMap.projectProgress] ?? "";
  return {
    ...input,
    description: input.description ?? input[feishuFieldMap.projectDescription] ?? "",
    projectProgress: typeof progress === "string" ? progress : ""
  };
}
var text11 = (value) => typeof value === "string" ? value.trim() : "";
var active3 = (row) => !row.archived && row.active !== false && !["\u79BB\u804C", "\u505C\u7528"].includes(row.status);
var token = (value) => typeof value === "string" && !!value.trim() && value.trim().length <= 500 && !/[\s/?#\\]/.test(value.trim());
function hydrateStateCollections(input) {
  if (!input || typeof input !== "object" || input.schemaVersion !== 2) return input;
  const missing = [...collaborationKinds, ...registryKinds, "cases"].filter((kind) => !Object.prototype.hasOwnProperty.call(input, kind));
  return missing.length ? { ...input, ...Object.fromEntries(missing.map((kind) => [kind, []])) } : input;
}
function normalizeRemoteHost(value) {
  const raw = text11(value);
  if (!raw || /[\s\\]/.test(raw)) return "";
  try {
    const url = new URL(raw.includes("://") ? raw : `https://${raw}`);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== "/") return "";
    return url.host.toLowerCase().replace(/\.$/, "");
  } catch {
    return "";
  }
}
function safeRemoteUrl(value) {
  if (!text11(value)) return true;
  try {
    const url = new URL(text11(value));
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password;
  } catch {
    return false;
  }
}
function externalIdentity(row) {
  const nested = ["node", "subtask"].includes(row.remoteKind);
  const scope = row.system === "feishu_tasks" ? text11(row.spaceKey).split("/").map(text11).join("/") : text11(row.spaceKey);
  return JSON.stringify([row.system, normalizeRemoteHost(row.host), scope, row.remoteKind, nested ? text11(row.parentRemoteId) : "", text11(row.remoteId)]);
}
function externalLinkErrors(row, path, localKind) {
  const errors = [];
  const add = (field, message) => errors.push({ path: `${path}.${field}`, message });
  const kinds = { project: "projects", node: "flowNodes", subtask: "actions", execution_task: "actions", deliverable: "deliverables", task: "actions" };
  if (!["meegle", "feishu_tasks"].includes(row.system)) add("system", "\u5916\u90E8\u7CFB\u7EDF\u987B\u4E3A meegle \u6216 feishu_tasks");
  if (!Object.hasOwn(kinds, row.remoteKind) || (row.system === "feishu_tasks" ? row.remoteKind !== "task" : row.remoteKind === "task")) add("remoteKind", "\u98DE\u4E66\u4EFB\u52A1\u53EA\u5141\u8BB8 task\uFF1BMeegle \u987B\u4F7F\u7528\u9879\u76EE\u3001\u8282\u70B9\u3001\u5B50\u4EFB\u52A1\u3001\u6267\u884C\u4EFB\u52A1\u6216\u4EA4\u4ED8\u7269\u7C7B\u578B");
  if (localKind && kinds[row.remoteKind] !== localKind) add("localObjectId", "\u672C\u5730\u5BF9\u8C61\u7C7B\u578B\u4E0E\u5916\u90E8\u5BF9\u8C61\u7C7B\u578B\u4E0D\u5339\u914D");
  if (!row.localObjectId) add("localObjectId", "\u8BF7\u9009\u62E9\u5173\u8054\u7684\u672C\u5730\u5BF9\u8C61");
  const host = normalizeRemoteHost(row.host);
  if (!host) add("host", "\u8BF7\u586B\u5199\u5408\u6CD5\u7684\u5916\u90E8\u670D\u52A1\u4E3B\u673A\uFF0C\u4E0D\u542B\u8DEF\u5F84\u3001\u51ED\u636E\u6216\u67E5\u8BE2\u53C2\u6570");
  if (!token(row.remoteId)) add("remoteId", "\u8FDC\u7AEF\u5BF9\u8C61\u987B\u4F7F\u7528\u660E\u786E\u3001\u975E\u7A7A\u4E14\u4E0D\u542B\u8DEF\u5F84\u7684\u7A33\u5B9A ID");
  if (row.system === "feishu_tasks") {
    const scope = text11(row.spaceKey).split("/");
    if (scope.length !== 2 || !scope.every(token)) add("spaceKey", "\u98DE\u4E66\u4EFB\u52A1\u8303\u56F4\u987B\u4E3A \u79DF\u6237\u6807\u8BC6/\u5E94\u7528\u6807\u8BC6\uFF0C\u4E0D\u53EF\u4F7F\u7528\u4EFB\u52A1\u6E05\u5355 ID");
  } else if (!token(row.spaceKey)) add("spaceKey", "Meegle \u5173\u8054\u987B\u6307\u5B9A\u660E\u786E\u7684\u7A7A\u95F4\u6807\u8BC6");
  if (["node", "subtask"].includes(row.remoteKind)) {
    if (!token(row.parentRemoteId)) add("parentRemoteId", "\u8282\u70B9\u6216\u5B50\u4EFB\u52A1\u987B\u6307\u5B9A\u6240\u5C5E\u8FDC\u7AEF\u5DE5\u4F5C\u9879 ID");
  } else if (text11(row.parentRemoteId)) add("parentRemoteId", "\u6B64\u7C7B\u8FDC\u7AEF\u5BF9\u8C61\u4E0D\u4F7F\u7528\u7236 ID\uFF0C\u8BF7\u6E05\u7A7A\u6B64\u5B57\u6BB5");
  if (typeof row.verified !== "boolean") add("verified", "\u5173\u8054\u6838\u5B9E\u72B6\u6001\u987B\u4E3A true \u6216 false");
  if (!safeRemoteUrl(row.url)) add("url", "\u8FDC\u7AEF\u94FE\u63A5\u987B\u4E3A\u4E0D\u542B\u51ED\u636E\u7684 http \u6216 https \u94FE\u63A5");
  else if (text11(row.url) && host && normalizeRemoteHost(new URL(text11(row.url)).origin) !== host) add("url", "\u8FDC\u7AEF\u94FE\u63A5\u7684\u4E3B\u673A\u5FC5\u987B\u4E0E\u5173\u8054\u4E3B\u673A\u4E00\u81F4");
  return errors;
}
function personIdentityErrors(row, path) {
  if (row.identityVerified !== true) return [];
  const complete = ["feishuUserId", "feishuAppId", "feishuTenantKey"].every((field) => token(row[field])) && ["open_id", "user_id", "union_id"].includes(row.feishuIdType);
  return complete ? [] : [{ path: `${path}.identityVerified`, message: "\u6838\u5B9E\u4EBA\u5458\u8EAB\u4EFD\u524D\u987B\u586B\u5199\u98DE\u4E66\u7528\u6237\u6807\u8BC6\u3001\u6807\u8BC6\u7C7B\u578B\u3001\u5E94\u7528\u6807\u8BC6\u548C\u79DF\u6237\u6807\u8BC6\uFF1BMeegle \u7528\u6237\u6807\u8BC6\u4E0D\u80FD\u4EE3\u66FF\u5B83\u4EEC" }];
}
function getLegacyLink(row) {
  const source = row.importedFrom;
  if (!source || typeof source !== "object" || !["feishu", "meegle", "feishu_tasks"].includes(source.system)) return null;
  const rawUrl = text11(source.url);
  let url;
  if (rawUrl && safeRemoteUrl(rawUrl)) {
    try {
      url = new URL(rawUrl);
    } catch {
    }
  }
  const parts = url?.pathname.split("/").filter(Boolean) || [];
  const detail = parts.indexOf("detail");
  const urlId = detail > 0 && token(parts[detail + 1]) ? parts[detail + 1] : "";
  const remoteKind = source.system === "feishu_tasks" ? "task" : source.kind === "projects" ? "project" : source.remoteKind || "";
  const explicitId = token(source.remoteId) ? text11(source.remoteId) : "";
  const stableProjectId = remoteKind === "project" && /^\d+$/.test(text11(source.sourceId)) ? text11(source.sourceId) : "";
  return { localObjectId: row.id, system: source.system === "feishu" ? "meegle" : source.system, remoteKind, host: url?.host || "", spaceKey: text11(source.spaceKey) || (urlId ? parts[0] : ""), remoteId: explicitId || (remoteKind === "project" ? urlId || stableProjectId : ""), parentRemoteId: text11(source.parentRemoteId), url: url?.href || "", verified: false, legacy: true, sourceId: text11(source.sourceId) };
}
function calendarDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date4 = /* @__PURE__ */ new Date(value + "T12:00:00Z");
  return Number.isFinite(date4.getTime()) && date4.toISOString().slice(0, 10) === value;
}
function buildDispatchPreview(input, actionId) {
  const s = hydrateStateCollections(input), action = s.actions.find((row) => row.id === actionId && active3(row));
  const empty = { actionId, summary: "", description: "", dueDate: "", dateBasis: "", recipient: null, issues: [], ready: false, externalWrites: false };
  if (!action) return { ...empty, issues: ["\u884C\u52A8\u9879\u4E0D\u5B58\u5728\u6216\u5DF2\u5F52\u6863"] };
  const issues = [], person = s.people.find((row) => row.id === action.executorId && active3(row));
  const recipient = person ? { id: person.id, name: person.title, userId: text11(person.feishuUserId), idType: text11(person.feishuIdType), appId: text11(person.feishuAppId), tenantKey: text11(person.feishuTenantKey), verified: person.identityVerified === true } : null;
  if (!person) issues.push("\u8BF7\u5173\u8054\u4E00\u4F4D\u6709\u6548\u7684\u6267\u884C\u4EBA\u5458\uFF0C\u4E0D\u80FD\u4EC5\u51ED\u59D3\u540D\u6D3E\u53D1");
  else if (person.identityVerified !== true || personIdentityErrors({ ...person, identityVerified: true }, "person").length) issues.push("\u6267\u884C\u4EBA\u5458\u7684\u98DE\u4E66\u8EAB\u4EFD\u3001\u6807\u8BC6\u7C7B\u578B\u3001\u5E94\u7528\u548C\u79DF\u6237\u8303\u56F4\u5C1A\u672A\u5B8C\u6574\u6838\u5B9E");
  if (action.executionChannel !== "feishu_task") issues.push("\u6267\u884C\u5165\u53E3\u987B\u660E\u786E\u9009\u62E9\u98DE\u4E66\u4EFB\u52A1");
  const summary = text11(action.dispatchTitle) || text11(action.title);
  if (!summary) issues.push("\u8BF7\u586B\u5199\u5BF9\u5916\u4EFB\u52A1\u6807\u9898");
  const outward = text11(action.dispatchDescription), acceptance = text11(action.acceptance);
  if (!outward && !acceptance) issues.push("\u8BF7\u586B\u5199\u5BF9\u5916\u8BF4\u660E\u6216\u9A8C\u6536\u8981\u6C42");
  const dateBasis = text11(action.dispatchDateBasis), dueDate = text11(action.dispatchDueDate);
  if (!["planned", "committed", "custom"].includes(dateBasis)) issues.push("\u8BF7\u660E\u786E\u6D3E\u53D1\u65E5\u671F\u53E3\u5F84\uFF1A\u8BA1\u5212\u3001\u627F\u8BFA\u6216\u5355\u72EC\u7EA6\u5B9A");
  if (!calendarDate(dueDate)) issues.push("\u8BF7\u663E\u5F0F\u586B\u5199\u6709\u6548\u7684\u6D3E\u53D1\u622A\u6B62\u65E5\u671F");
  const selectedDate = dateBasis === "planned" ? text11(action.plannedEnd) : dateBasis === "committed" ? text11(action.dueAt) : "";
  if (["planned", "committed"].includes(dateBasis) && !calendarDate(selectedDate)) issues.push("\u6240\u9009\u65E5\u671F\u53E3\u5F84\u7F3A\u5C11\u5DF2\u4FDD\u5B58\u7684\u8BA1\u5212\u6216\u627F\u8BFA\u65E5\u671F\uFF0C\u8BF7\u5148\u8865\u5168\u6216\u6539\u4E3A\u5355\u72EC\u7EA6\u5B9A");
  if (selectedDate && selectedDate !== dueDate) issues.push("\u6D3E\u53D1\u65E5\u671F\u4E0E\u6240\u9009\u8BA1\u5212\u6216\u627F\u8BFA\u65E5\u671F\u4E0D\u4E00\u81F4\uFF0C\u8BF7\u91CD\u65B0\u6838\u5BF9\u6216\u6539\u4E3A\u5355\u72EC\u7EA6\u5B9A");
  const projects = s.projects.filter((project) => !project.archived && action.projectIds.includes(project.id));
  const basisLabel = { planned: "\u8BA1\u5212\u65E5\u671F", committed: "\u627F\u8BFA\u65E5\u671F", custom: "\u5355\u72EC\u7EA6\u5B9A\u65E5\u671F" };
  const description = [projects.length ? `\u6240\u5C5E\u9879\u76EE\uFF1A${projects.map((project) => [text11(project.code), project.title].filter(Boolean).join(" ")).join("\uFF1B")}` : "", outward ? `\u5DE5\u4F5C\u8BF4\u660E\uFF1A${outward}` : "", acceptance ? `\u9A8C\u6536\u8981\u6C42\uFF1A${acceptance}` : "", dueDate && basisLabel[dateBasis] ? `\u622A\u6B62\u65E5\u671F\uFF1A${dueDate}\uFF08${basisLabel[dateBasis]}\uFF09` : ""].filter(Boolean).join("\n\n");
  return { actionId, summary, description, dueDate, dateBasis, recipient, issues, ready: issues.length === 0, externalWrites: false };
}
function collaborationSummary(input, projectId) {
  const s = hydrateStateCollections(input);
  const related2 = (row) => !row.archived && (!projectId || row.id === projectId || row.projectIds.includes(projectId));
  const flowNodes = s.flowNodes.filter(related2), deliverables = s.deliverables.filter(related2), actions = s.actions.filter(related2);
  const visibleIds = new Set(v2Kinds.flatMap((kind) => s[kind].filter(related2).map((row) => row.id)));
  const externalLinks = s.externalLinks.filter((row) => !row.archived && visibleIds.has(row.localObjectId));
  const legacyLinks = v2Kinds.filter((kind) => !["externalLinks", "sources"].includes(kind)).flatMap((kind) => s[kind].filter(related2).flatMap((row) => {
    const link = getLegacyLink(row);
    return link ? [{ ...link, title: row.title }] : [];
  }));
  const prepared = actions.filter((row) => row.executionChannel === "feishu_task").map((row) => buildDispatchPreview(s, row.id));
  return { flowNodes, deliverables, externalLinks, legacyLinks, actions, counts: { flowNodes: flowNodes.length, deliverables: deliverables.length, externalLinks: externalLinks.length, verifiedLinks: externalLinks.filter((row) => row.verified).length, legacyLinks: legacyLinks.length, dispatchReady: prepared.filter((row) => row.ready).length }, issues: prepared.flatMap((row) => row.issues.map((message) => ({ objectId: row.actionId, message }))), externalWrites: false };
}

// lib/mapping-registry.ts
var registryCollections = ["externalObjects", "remoteFieldValues", "mappingRules", "syncBaselines", "syncRuns", "syncReceipts", "dispatchRecords"];
var object6 = (value) => !!value && typeof value === "object" && !Array.isArray(value);
var own2 = (value, key2) => Object.prototype.hasOwnProperty.call(value, key2);
var clone = (value) => structuredClone(value);
var canonical3 = (value) => value === void 0 ? "null" : JSON.stringify(value, (_key, item) => object6(item) ? Object.fromEntries(Object.keys(item).sort().map((key2) => [key2, item[key2]])) : item);
var same4 = (a, b) => canonical3(a) === canonical3(b);
var text12 = (value, max = 2e4) => typeof value === "string" && value.length <= max;
var id = (value) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value);
var hash = (value) => {
  let h = 2166136261;
  for (const char of canonical3(value)) {
    h ^= char.charCodeAt(0);
    h = Math.imul(h, 16777619);
  }
  return `fnv1a-${(h >>> 0).toString(16).padStart(8, "0")}`;
};
function externalObjectIdentity(input) {
  return JSON.stringify([String(input.system || ""), String(input.host || "").toLowerCase(), String(input.tenantKey || ""), String(input.spaceKey || ""), String(input.remoteKind || ""), String(input.parentRemoteId || ""), String(input.remoteId || "")]);
}
function error(path, message, before, current, proposed) {
  return { path, message, ...before === void 0 ? {} : { before }, ...current === void 0 ? {} : { current }, ...proposed === void 0 ? {} : { proposed } };
}
function mapById(rows2) {
  const result = /* @__PURE__ */ new Map();
  if (Array.isArray(rows2)) {
    for (const row of rows2) if (object6(row) && typeof row.id === "string") result.set(row.id, row);
  }
  return result;
}
function validateMappingRegistry(input) {
  const errors = [];
  const workspaceId = input?.workspaceId;
  const localIds = /* @__PURE__ */ new Set();
  for (const kind of ["projects", "milestones", "dependencies", "risks", "decisions", "actions", "sources", "judgments", "people", "resources", "relations", "flowNodes", "deliverables", "externalLinks"]) for (const row of input?.[kind] || []) if (object6(row) && typeof row.id === "string") localIds.add(row.id);
  const externalRows = Array.isArray(input?.externalObjects) ? input.externalObjects : null;
  if (!externalRows) {
    errors.push(error("externalObjects", "\u5916\u90E8\u5BF9\u8C61\u6CE8\u518C\u8868\u5FC5\u987B\u4E3A\u6570\u7EC4"));
    return errors;
  }
  const externals = mapById(externalRows), externalIdentities = /* @__PURE__ */ new Map();
  externalRows.forEach((row, index) => {
    const path = `externalObjects.${index}`;
    if (!object6(row)) {
      errors.push(error(path, "\u5916\u90E8\u5BF9\u8C61\u5FC5\u987B\u4E3A\u5BF9\u8C61"));
      return;
    }
    for (const field of ["id", "workspaceId", "system", "host", "tenantKey", "spaceKey", "remoteKind", "remoteId", "parentRemoteId", "parentNodeRemoteId", "parentDeliverableRemoteId", "localObjectId", "sourceId", "collectedAt", "sourceHash"]) if (!text12(row[field], 1e3)) errors.push(error(`${path}.${field}`, "\u5916\u90E8\u5BF9\u8C61\u5B57\u6BB5\u5FC5\u987B\u4E3A\u6587\u5B57"));
    if (!id(row.id)) errors.push(error(`${path}.id`, "\u5916\u90E8\u5BF9\u8C61 ID \u65E0\u6548"));
    if (row.workspaceId !== workspaceId) errors.push(error(`${path}.workspaceId`, "\u5916\u90E8\u5BF9\u8C61\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A"));
    if (!["unverified", "verified", "stale", "inaccessible"].includes(row.verificationStatus)) errors.push(error(`${path}.verificationStatus`, "\u5916\u90E8\u6838\u5B9E\u72B6\u6001\u65E0\u6548"));
    if (!["unmapped", "mapped", "quarantined", "conflict"].includes(row.mappingStatus)) errors.push(error(`${path}.mappingStatus`, "\u5916\u90E8\u6620\u5C04\u72B6\u6001\u65E0\u6548"));
    if (row.localObjectId && !localIds.has(row.localObjectId)) errors.push(error(`${path}.localObjectId`, "\u5916\u90E8\u5BF9\u8C61\u7684\u672C\u5730\u5BF9\u8C61\u4E0D\u5B58\u5728"));
    if (row.sourceId && !localIds.has(row.sourceId)) errors.push(error(`${path}.sourceId`, "\u5916\u90E8\u5BF9\u8C61\u6765\u6E90\u4E0D\u5B58\u5728"));
    if (row.mappingStatus === "mapped" && !row.localObjectId) errors.push(error(`${path}.mappingStatus`, "\u5DF2\u6620\u5C04\u5916\u90E8\u5BF9\u8C61\u5FC5\u987B\u6709\u672C\u5730\u5BF9\u8C61 ID"));
    const identity = externalObjectIdentity(row), previous = externalIdentities.get(identity);
    if (previous && previous !== row.id) errors.push(error(`${path}.remoteId`, "\u540C\u4E00\u8FDC\u7AEF\u8EAB\u4EFD\u4E0D\u80FD\u91CD\u590D\u6CE8\u518C\u5230\u4E0D\u540C\u5916\u90E8\u5BF9\u8C61", previous, row.id));
    else externalIdentities.set(identity, row.id);
    for (const [field, parent] of [["parentRemoteId", row.parentRemoteId], ["parentNodeRemoteId", row.parentNodeRemoteId], ["parentDeliverableRemoteId", row.parentDeliverableRemoteId]]) if (parent) {
      const parentRow = externalRows.find((candidate) => candidate && candidate.remoteId === parent && candidate.system === row.system && candidate.host === row.host && candidate.tenantKey === row.tenantKey && candidate.spaceKey === row.spaceKey);
      if (!parentRow) errors.push(error(`${path}.${field}`, "\u7236\u7EA7\u8FDC\u7AEF\u8EAB\u4EFD\u672A\u5728\u6CE8\u518C\u8868\u4E2D\u627E\u5230"));
      if (parent === row.remoteId) errors.push(error(`${path}.${field}`, "\u8FDC\u7AEF\u5BF9\u8C61\u4E0D\u80FD\u5C06\u81EA\u5DF1\u4F5C\u4E3A\u7236\u7EA7"));
    }
  });
  const fieldRows = Array.isArray(input?.remoteFieldValues) ? input.remoteFieldValues : null;
  if (!fieldRows) errors.push(error("remoteFieldValues", "\u8FDC\u7AEF\u5B57\u6BB5\u503C\u6CE8\u518C\u8868\u5FC5\u987B\u4E3A\u6570\u7EC4"));
  else {
    const fieldKeys2 = /* @__PURE__ */ new Set();
    fieldRows.forEach((row, index) => {
      const path = `remoteFieldValues.${index}`;
      if (!object6(row)) {
        errors.push(error(path, "\u8FDC\u7AEF\u5B57\u6BB5\u503C\u5FC5\u987B\u4E3A\u5BF9\u8C61"));
        return;
      }
      for (const field of ["id", "workspaceId", "externalObjectId", "remoteFieldKey", "remoteFieldName", "optionId", "displayName", "localField", "mappingRuleId", "collectedAt", "sourceHash"]) if (!text12(row[field], 2e4)) errors.push(error(`${path}.${field}`, "\u8FDC\u7AEF\u5B57\u6BB5\u8EAB\u4EFD\u5B57\u6BB5\u5FC5\u987B\u4E3A\u6587\u5B57"));
      if (!id(row.id)) errors.push(error(`${path}.id`, "\u8FDC\u7AEF\u5B57\u6BB5\u503C ID \u65E0\u6548"));
      if (row.workspaceId !== workspaceId) errors.push(error(`${path}.workspaceId`, "\u8FDC\u7AEF\u5B57\u6BB5\u503C\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A"));
      if (!externals.has(row.externalObjectId)) errors.push(error(`${path}.externalObjectId`, "\u8FDC\u7AEF\u5B57\u6BB5\u503C\u5F15\u7528\u7684\u5916\u90E8\u5BF9\u8C61\u4E0D\u5B58\u5728"));
      if (!["text", "number", "boolean", "date", "datetime", "option", "multi_option", "person", "json", "unknown"].includes(row.valueType)) errors.push(error(`${path}.valueType`, "\u8FDC\u7AEF\u503C\u7C7B\u578B\u65E0\u6548"));
      const key2 = `${row.externalObjectId}/${row.remoteFieldKey}`;
      if (fieldKeys2.has(key2)) errors.push(error(`${path}.remoteFieldKey`, "\u540C\u4E00\u5916\u90E8\u5BF9\u8C61\u7684\u8FDC\u7AEF\u5B57\u6BB5\u4E0D\u80FD\u91CD\u590D"));
      else fieldKeys2.add(key2);
    });
  }
  const ruleRows = Array.isArray(input?.mappingRules) ? input.mappingRules : null;
  const rules = /* @__PURE__ */ new Map();
  if (!ruleRows) errors.push(error("mappingRules", "\u5B57\u6BB5\u6620\u5C04\u89C4\u5219\u5FC5\u987B\u4E3A\u6570\u7EC4"));
  else ruleRows.forEach((row, index) => {
    const path = `mappingRules.${index}`;
    if (!object6(row)) {
      errors.push(error(path, "\u5B57\u6BB5\u6620\u5C04\u89C4\u5219\u5FC5\u987B\u4E3A\u5BF9\u8C61"));
      return;
    }
    for (const field of ["id", "workspaceId", "system", "remoteKind", "remoteFieldKey", "remoteFieldName", "localField", "conversionRule"]) if (!text12(row[field], 2e4)) errors.push(error(`${path}.${field}`, "\u5B57\u6BB5\u6620\u5C04\u89C4\u5219\u5B57\u6BB5\u5FC5\u987B\u4E3A\u6587\u5B57"));
    if (!id(row.id)) errors.push(error(`${path}.id`, "\u6620\u5C04\u89C4\u5219 ID \u65E0\u6548"));
    if (row.workspaceId !== workspaceId) errors.push(error(`${path}.workspaceId`, "\u6620\u5C04\u89C4\u5219\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A"));
    if (row.localKind && !["projects", "milestones", "dependencies", "risks", "decisions", "actions", "sources", "judgments", "people", "resources", "relations", "flowNodes", "deliverables", "externalLinks"].includes(row.localKind)) errors.push(error(`${path}.localKind`, "\u672C\u5730\u5BF9\u8C61\u7C7B\u578B\u65E0\u6548"));
    if (!["text", "number", "boolean", "date", "datetime", "option", "multi_option", "person", "json", "unknown"].includes(row.remoteValueType)) errors.push(error(`${path}.remoteValueType`, "\u8FDC\u7AEF\u503C\u7C7B\u578B\u65E0\u6548"));
    if (!["active", "deprecated"].includes(row.status)) errors.push(error(`${path}.status`, "\u6620\u5C04\u89C4\u5219\u72B6\u6001\u65E0\u6548"));
    if (typeof row.writable !== "boolean" || typeof row.requiresReview !== "boolean" || typeof row.bidirectional !== "boolean") errors.push(error(path, "\u53EF\u5199\u3001\u4EBA\u5DE5\u5BA1\u6838\u548C\u53CC\u5411\u6807\u8BB0\u5FC5\u987B\u4E3A\u5E03\u5C14\u503C"));
    const key2 = `${row.system}/${row.remoteKind}/${row.remoteFieldKey}`;
    if (rules.has(key2) && rules.get(key2).id !== row.id) errors.push(error(`${path}.remoteFieldKey`, "\u76F8\u540C\u8FDC\u7AEF\u5B57\u6BB5\u5DF2\u6709\u6620\u5C04\u89C4\u5219"));
    else rules.set(key2, row);
  });
  const baselineRows = Array.isArray(input?.syncBaselines) ? input.syncBaselines : null;
  const baselines = mapById(baselineRows || []);
  if (!baselineRows) errors.push(error("syncBaselines", "\u540C\u6B65\u57FA\u7EBF\u5FC5\u987B\u4E3A\u6570\u7EC4"));
  else baselineRows.forEach((row, index) => {
    const path = `syncBaselines.${index}`;
    if (!object6(row)) {
      errors.push(error(path, "\u540C\u6B65\u57FA\u7EBF\u5FC5\u987B\u4E3A\u5BF9\u8C61"));
      return;
    }
    for (const field of ["id", "workspaceId", "externalObjectId", "capturedAt", "sourceHash", "sourceId"]) if (!text12(row[field], 2e4)) errors.push(error(`${path}.${field}`, "\u540C\u6B65\u57FA\u7EBF\u5B57\u6BB5\u5FC5\u987B\u4E3A\u6587\u5B57"));
    if (!id(row.id)) errors.push(error(`${path}.id`, "\u540C\u6B65\u57FA\u7EBF ID \u65E0\u6548"));
    if (row.workspaceId !== workspaceId) errors.push(error(`${path}.workspaceId`, "\u540C\u6B65\u57FA\u7EBF\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A"));
    if (!externals.has(row.externalObjectId)) errors.push(error(`${path}.externalObjectId`, "\u540C\u6B65\u57FA\u7EBF\u5F15\u7528\u7684\u5916\u90E8\u5BF9\u8C61\u4E0D\u5B58\u5728"));
    if (!object6(row.remoteValues) || !object6(row.localValues) || !Number.isSafeInteger(row.localRevision) || row.localRevision < 0) errors.push(error(path, "\u540C\u6B65\u57FA\u7EBF\u5FEB\u7167\u6216\u672C\u5730\u7248\u672C\u65E0\u6548"));
    if (row.sourceId && !localIds.has(row.sourceId)) errors.push(error(`${path}.sourceId`, "\u540C\u6B65\u57FA\u7EBF\u6765\u6E90\u4E0D\u5B58\u5728"));
  });
  const runRows = Array.isArray(input?.syncRuns) ? input.syncRuns : null;
  const runs = mapById(runRows || []);
  if (!runRows) errors.push(error("syncRuns", "\u540C\u6B65\u8FD0\u884C\u8BB0\u5F55\u5FC5\u987B\u4E3A\u6570\u7EC4"));
  else runRows.forEach((row, index) => {
    const path = `syncRuns.${index}`;
    if (!object6(row)) {
      errors.push(error(path, "\u540C\u6B65\u8FD0\u884C\u8BB0\u5F55\u5FC5\u987B\u4E3A\u5BF9\u8C61"));
      return;
    }
    for (const field of ["id", "workspaceId", "idempotencyKey", "targetSystem", "spaceKey", "createdAt", "startedAt", "finishedAt", "reason"]) if (!text12(row[field], 2e4)) errors.push(error(`${path}.${field}`, "\u540C\u6B65\u8FD0\u884C\u5B57\u6BB5\u5FC5\u987B\u4E3A\u6587\u5B57"));
    if (!id(row.id) || !id(row.idempotencyKey)) errors.push(error(path, "\u540C\u6B65\u8FD0\u884C ID \u6216\u5E42\u7B49\u952E\u65E0\u6548"));
    if (row.workspaceId !== workspaceId) errors.push(error(`${path}.workspaceId`, "\u540C\u6B65\u8FD0\u884C\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A"));
    if (!["read", "prepare_writeback", "write", "dispatch"].includes(row.mode)) errors.push(error(`${path}.mode`, "\u540C\u6B65\u6A21\u5F0F\u65E0\u6548"));
    if (!["prepared", "pending_review", "approved", "sending", "sent", "readback_verified", "failed", "partial", "needs_reconcile", "conflict"].includes(row.status)) errors.push(error(`${path}.status`, "\u540C\u6B65\u8FD0\u884C\u72B6\u6001\u65E0\u6548"));
    if (row.approvedBy != null && !text12(row.approvedBy, 500)) errors.push(error(`${path}.approvedBy`, "\u5BA1\u6838\u4EBA\u5FC5\u987B\u4E3A\u6587\u5B57"));
    if (row.approvedAt != null && !text12(row.approvedAt, 100)) errors.push(error(`${path}.approvedAt`, "\u5BA1\u6838\u65F6\u95F4\u5FC5\u987B\u4E3A\u6587\u5B57"));
    if (row.approvalComment != null && !text12(row.approvalComment, 2e4)) errors.push(error(`${path}.approvalComment`, "\u5BA1\u6838\u610F\u89C1\u5FC5\u987B\u4E3A\u6587\u5B57"));
    if (row.status === "approved" && (!text12(row.approvedBy, 500) || !text12(row.approvedAt, 100))) errors.push(error(`${path}.status`, "approved \u540C\u6B65\u8FD0\u884C\u5FC5\u987B\u4FDD\u7559\u5BA1\u6838\u4EBA\u548C\u5BA1\u6838\u65F6\u95F4"));
    if (!Array.isArray(row.objectIds) || row.objectIds.some((value) => !id(value) || !externals.has(value))) errors.push(error(`${path}.objectIds`, "\u540C\u6B65\u8FD0\u884C\u5BF9\u8C61\u5FC5\u987B\u5F15\u7528\u5916\u90E8\u5BF9\u8C61"));
    if (!Array.isArray(row.differenceIds) || row.differenceIds.some((value) => !id(value))) errors.push(error(`${path}.differenceIds`, "\u540C\u6B65\u5DEE\u5F02 ID \u65E0\u6548"));
    if (!Array.isArray(row.conflictIds) || row.conflictIds.some((value) => !id(value))) errors.push(error(`${path}.conflictIds`, "\u540C\u6B65\u51B2\u7A81 ID \u65E0\u6548"));
    if (row.externalWriteExecuted !== false) errors.push(error(`${path}.externalWriteExecuted`, "\u672C\u5730\u6CE8\u518C\u8868\u4E0D\u80FD\u628A\u5916\u90E8\u5199\u56DE\u6807\u4E3A\u5DF2\u6267\u884C"));
  });
  const receiptRows = Array.isArray(input?.syncReceipts) ? input.syncReceipts : null;
  const receiptIds = /* @__PURE__ */ new Set();
  if (!receiptRows) errors.push(error("syncReceipts", "\u540C\u6B65\u56DE\u6267\u5FC5\u987B\u4E3A\u6570\u7EC4"));
  else receiptRows.forEach((row, index) => {
    const path = `syncReceipts.${index}`;
    if (!object6(row)) {
      errors.push(error(path, "\u540C\u6B65\u56DE\u6267\u5FC5\u987B\u4E3A\u5BF9\u8C61"));
      return;
    }
    for (const field of ["id", "workspaceId", "syncRunId", "externalObjectId", "idempotencyKey", "recordedAt", "verifiedAt"]) if (!text12(row[field], 2e4)) errors.push(error(`${path}.${field}`, "\u540C\u6B65\u56DE\u6267\u5B57\u6BB5\u5FC5\u987B\u4E3A\u6587\u5B57"));
    if (!id(row.id) || !id(row.idempotencyKey)) errors.push(error(path, "\u540C\u6B65\u56DE\u6267 ID \u6216\u5E42\u7B49\u952E\u65E0\u6548"));
    if (receiptIds.has(row.id)) errors.push(error(`${path}.id`, "\u540C\u6B65\u56DE\u6267 ID \u91CD\u590D"));
    receiptIds.add(row.id);
    if (row.workspaceId !== workspaceId) errors.push(error(`${path}.workspaceId`, "\u540C\u6B65\u56DE\u6267\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A"));
    if (!runs.has(row.syncRunId)) errors.push(error(`${path}.syncRunId`, "\u540C\u6B65\u56DE\u6267\u5F15\u7528\u7684\u8FD0\u884C\u8BB0\u5F55\u4E0D\u5B58\u5728"));
    if (!externals.has(row.externalObjectId)) errors.push(error(`${path}.externalObjectId`, "\u540C\u6B65\u56DE\u6267\u5F15\u7528\u7684\u5916\u90E8\u5BF9\u8C61\u4E0D\u5B58\u5728"));
    if (!["prepared", "pending_review", "approved", "sending", "sent", "readback_verified", "failed", "partial", "needs_reconcile", "conflict"].includes(row.status)) errors.push(error(`${path}.status`, "\u540C\u6B65\u56DE\u6267\u72B6\u6001\u65E0\u6548"));
    if (!Array.isArray(row.evidenceIds) || row.evidenceIds.some((value) => !id(value) || !localIds.has(value))) errors.push(error(`${path}.evidenceIds`, "\u540C\u6B65\u56DE\u6267\u8BC1\u636E\u5F15\u7528\u65E0\u6548"));
    if (row.externalWriteExecuted !== false) errors.push(error(`${path}.externalWriteExecuted`, "\u672C\u5730\u540C\u6B65\u56DE\u6267\u4E0D\u80FD\u628A\u5916\u90E8\u5199\u56DE\u6807\u4E3A\u5DF2\u6267\u884C"));
  });
  const dispatchRows = Array.isArray(input?.dispatchRecords) ? input.dispatchRecords : null;
  if (!dispatchRows) errors.push(error("dispatchRecords", "\u6D3E\u53D1\u8BB0\u5F55\u5FC5\u987B\u4E3A\u6570\u7EC4"));
  else dispatchRows.forEach((row, index) => {
    const path = `dispatchRecords.${index}`;
    if (!object6(row)) {
      errors.push(error(path, "\u6D3E\u53D1\u8BB0\u5F55\u5FC5\u987B\u4E3A\u5BF9\u8C61"));
      return;
    }
    for (const field of ["id", "workspaceId", "localObjectId", "actionId", "targetSystem", "spaceKey", "idempotencyKey", "remoteId", "createdAt", "updatedAt", "error"]) if (!text12(row[field], 2e4)) errors.push(error(`${path}.${field}`, "\u6D3E\u53D1\u8BB0\u5F55\u5B57\u6BB5\u5FC5\u987B\u4E3A\u6587\u5B57"));
    if (!id(row.id) || !id(row.idempotencyKey)) errors.push(error(path, "\u6D3E\u53D1\u8BB0\u5F55 ID \u6216\u5E42\u7B49\u952E\u65E0\u6548"));
    if (row.workspaceId !== workspaceId) errors.push(error(`${path}.workspaceId`, "\u6D3E\u53D1\u8BB0\u5F55\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A"));
    if (!localIds.has(row.localObjectId) || !localIds.has(row.actionId)) errors.push(error(`${path}.localObjectId`, "\u6D3E\u53D1\u8BB0\u5F55\u672C\u5730\u5BF9\u8C61\u4E0D\u5B58\u5728"));
    if (!["prepared", "pending_review", "approved", "sending", "sent", "readback_verified", "failed", "partial", "needs_reconcile"].includes(row.status)) errors.push(error(`${path}.status`, "\u6D3E\u53D1\u72B6\u6001\u65E0\u6548"));
    if (!Number.isSafeInteger(row.attempts) || row.attempts < 0 || typeof row.readbackVerified !== "boolean" || row.externalWriteExecuted !== false) errors.push(error(path, "\u6D3E\u53D1\u6B21\u6570\u3001\u56DE\u8BFB\u72B6\u6001\u6216\u5916\u90E8\u5199\u56DE\u6807\u5FD7\u65E0\u6548"));
  });
  return errors;
}
function normalizeValues(values) {
  return object6(values) ? values : {};
}
function compareThreeWay(input) {
  const baseline = normalizeValues(input.baseline?.remoteValues || input.baseline?.values || {});
  const currentRemote = normalizeValues(input.currentRemote);
  const local = normalizeValues(input.localValues);
  const rules = input.rules || [];
  const rulesByKey = new Map(rules.map((rule) => [`${rule.remoteFieldKey}`, rule]));
  const keys = /* @__PURE__ */ new Set([...Object.keys(baseline), ...Object.keys(currentRemote), ...rules.map((rule) => rule.remoteFieldKey)]);
  const result = [];
  for (const remoteFieldKey of keys) {
    const rule = rulesByKey.get(remoteFieldKey);
    const localField = rule?.localField || remoteFieldKey;
    const before = baseline[remoteFieldKey];
    const current = currentRemote[remoteFieldKey];
    const localValue = own2(local, localField) ? local[localField] : local[remoteFieldKey];
    const remoteChanged = !same4(before, current);
    const localChanged = !same4(before, localValue);
    if (!remoteChanged && !localChanged) continue;
    const conflict = remoteChanged && localChanged && !same4(current, localValue);
    let reason = conflict ? "\u8FDC\u7AEF\u5F53\u524D\u503C\u4E0E\u672C\u5730\u503C\u90FD\u76F8\u5BF9\u4E0A\u6B21\u57FA\u7EBF\u53D1\u751F\u53D8\u5316\uFF0C\u505C\u6B62\u5199\u56DE" : "";
    if (!rule) reason ||= "\u7F3A\u5C11\u5B57\u6BB5\u6620\u5C04\u89C4\u5219\uFF0C\u9ED8\u8BA4\u53EA\u8BFB\u4FDD\u7559";
    else if (rule.status !== "active") reason ||= "\u5B57\u6BB5\u6620\u5C04\u89C4\u5219\u5DF2\u505C\u7528";
    else if (!rule.writable || !rule.bidirectional) reason ||= "\u5B57\u6BB5\u7B56\u7565\u7981\u6B62\u81EA\u52A8\u53CC\u5411\u5199\u56DE";
    else if (rule.requiresReview) reason ||= "\u5B57\u6BB5\u7B56\u7565\u8981\u6C42\u4EBA\u5DE5\u5BA1\u6838\u540E\u5199\u56DE";
    result.push({ id: `diff-${hash([input.externalObjectId, remoteFieldKey, before, current, localValue])}`, externalObjectId: input.externalObjectId, remoteFieldKey, remoteFieldName: rule?.remoteFieldName || remoteFieldKey, localField, before: clone(before), baseline: clone(before), currentRemote: clone(current), localValue: clone(localValue), local: clone(localValue), remoteChanged, localChanged, conflict, writable: rule?.writable === true, requiresReview: rule?.requiresReview !== false, bidirectional: rule?.bidirectional === true, reason });
  }
  return result;
}
var buildThreeWayDiff = compareThreeWay;
var threeWayDiff = compareThreeWay;
function hasSyncConflicts(differences) {
  return differences.some((diff) => diff.conflict || diff.localChanged && (!diff.writable || !diff.bidirectional));
}
function prepareWriteback(input) {
  if (!id(input.workspaceId) || !id(input.idempotencyKey) || !id(input.externalObjectId)) throw new Error("\u540C\u6B65\u51C6\u5907\u5FC5\u987B\u63D0\u4F9B\u6709\u6548\u5DE5\u4F5C\u533A\u3001\u5E42\u7B49\u952E\u548C\u5916\u90E8\u5BF9\u8C61 ID");
  const now2 = input.now || (/* @__PURE__ */ new Date()).toISOString();
  const differences = compareThreeWay(input);
  const blocked = hasSyncConflicts(differences);
  const runId = `sync-${input.idempotencyKey}`;
  const conflictIds = differences.filter((diff) => diff.conflict || diff.localChanged && (!diff.writable || !diff.bidirectional)).map((diff) => diff.id);
  const run = { id: runId, workspaceId: input.workspaceId, idempotencyKey: input.idempotencyKey, mode: "prepare_writeback", status: blocked ? "conflict" : "pending_review", targetSystem: input.targetSystem || "", spaceKey: input.spaceKey || "", objectIds: [...input.objectIds || [input.externalObjectId]], differenceIds: differences.map((diff) => diff.id), conflictIds, createdAt: now2, startedAt: now2, finishedAt: "", externalWriteExecuted: false, reason: blocked ? "\u5B58\u5728\u8FDC\u7AEF\u3001\u672C\u5730\u6216\u5B57\u6BB5\u7B56\u7565\u51B2\u7A81\uFF0C\u672A\u751F\u6210\u53EF\u6267\u884C\u5199\u56DE" : "\u5DF2\u751F\u6210\u5F85\u4EBA\u5DE5\u5BA1\u6838\u5199\u56DE\u8349\u7A3F" };
  const receipts = differences.length ? differences.map((diff) => ({ id: `receipt-${input.idempotencyKey}-${diff.remoteFieldKey}`, workspaceId: input.workspaceId, syncRunId: runId, externalObjectId: input.externalObjectId, idempotencyKey: input.idempotencyKey, status: blocked ? "conflict" : "pending_review", before: clone(diff.before), currentRemote: clone(diff.currentRemote), proposed: clone(diff.localValue), evidenceIds: input.sourceId ? [input.sourceId] : [], remoteResponse: null, readback: null, externalWriteExecuted: false, recordedAt: now2, verifiedAt: "" })) : [];
  return { run, differences, receipts, externalWriteExecuted: false, canWriteBack: !blocked && differences.some((diff) => diff.localChanged && diff.writable && diff.bidirectional) };
}
var prepareSyncRun = prepareWriteback;
var compareRemoteLocal = compareThreeWay;
var canWriteBack = (differences) => !hasSyncConflicts(differences) && differences.some((diff) => diff.localChanged && diff.writable && diff.bidirectional);
function ensureReviewedWriteback(input) {
  if (!input || input.run.externalWriteExecuted || input.externalWriteExecuted) throw new Error("\u672C\u5730\u540C\u6B65\u8BB0\u5F55\u4E0D\u80FD\u58F0\u660E\u5916\u90E8\u5199\u56DE\u5DF2\u6267\u884C");
  if (input.run.status === "conflict" || input.differences.some((diff) => diff.conflict)) throw new Error("\u5B58\u5728\u4E09\u65B9\u51B2\u7A81\uFF0C\u5FC5\u987B\u91CD\u8BFB\u8FDC\u7AEF\u5E76\u91CD\u65B0\u5BA1\u6838\u540E\u624D\u80FD\u5199\u56DE");
  if (input.run.status !== "approved") throw new Error("\u6B63\u5F0F\u5199\u56DE\u5FC5\u987B\u5148\u5C06\u5F53\u524D\u5DEE\u5F02\u6807\u8BB0\u4E3A approved\uFF0C\u5E76\u4FDD\u7559\u7528\u6237\u5BA1\u6838\u8BB0\u5F55");
  if (!input.run.approvedBy || !input.run.approvedAt) throw new Error("approved \u72B6\u6001\u7F3A\u5C11\u5BA1\u6838\u4EBA\u6216\u5BA1\u6838\u65F6\u95F4");
  if (!input.canWriteBack) throw new Error("\u6CA1\u6709\u7ECF\u8FC7\u5BA1\u6838\u4E14\u5141\u8BB8\u53CC\u5411\u5199\u56DE\u7684\u5B57\u6BB5");
  return clone(input);
}

// lib/workbench-v2.ts
var clone2 = (value) => structuredClone(value);
var now = () => (/* @__PURE__ */ new Date()).toISOString();
var own3 = (value, key2) => Object.prototype.hasOwnProperty.call(value, key2);
var object7 = (value) => !!value && typeof value === "object" && !Array.isArray(value);
var canonical4 = (value) => value === void 0 ? "null" : JSON.stringify(value, (_key, item) => object7(item) ? Object.fromEntries(Object.keys(item).sort().map((key2) => [key2, item[key2]])) : item);
var same5 = (a, b) => canonical4(a) === canonical4(b);
var present = (value) => value === void 0 ? null : clone2(value);
var idValid = (value) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value);
var textValid = (value, max = 2e4) => typeof value === "string" && value.length <= max;
var protectedFields = /* @__PURE__ */ new Set(["riskTrackingItemId", "feishuFacts", "historicalGapDeferred", "workItem", "subjectAssociation", "riskEvidence", "riskEvent", "chatScope", "projectChat", "managementSignal", "ruleBundle", "ruleCheck", "dataPublication", "id", "workspaceId", "version", "updatedAt", "createdAt", "stale", "staleReasons", "confirmationHistory", "confirmedAt", "history", "__proto__", "prototype", "constructor"]);
var dateFields = /* @__PURE__ */ new Set(["committed", "forecast", "actual", "deadline", "neededBy", "dueAt", "checkAt", "lastContactAt", "validFrom", "validTo", "plannedStart", "plannedEnd", "dispatchDueDate", "expectedAt"]);
var eventFields = /* @__PURE__ */ new Set(["occurredAt", "collectedAt", "decidedAt", "dispatchPreparedAt"]);
var stringFields = /* @__PURE__ */ new Set(["title", "code", "phase", "owner", "nextAction", "goal", "health", "healthReason", "privateNote", "status", "acceptance", "acceptanceStatus", "acceptor", "reviewStatus", "deliveryReview", "type", "situation", "executor", "followUp", "executionStatus", "priority", "description", "projectProgress", "deliverableProgress", "progressNote", "impact", "trigger", "response", "conclusion", "basis", "options", "recommendation", "excerpt", "url", "author", "role", "creator", "feishuIdentity", "color", "department", "departmentOwner", "blocker", "blockerOwner", "blockerImpact", "processingStatus"]);
for (const field of ["projectCategory", "projectLevel", "sourceStage", "sourceStatus", "remotePriority", "nodeStatus", "deliverableType", "deliverableVersion", "submissionStatus", "executionChannel", "dispatchTitle", "dispatchDescription", "dispatchDateBasis", "meegleUserKey", "feishuUserId", "feishuIdType", "feishuAppId", "feishuTenantKey", "system", "remoteKind", "host", "spaceKey", "remoteId", "parentRemoteId"]) stringFields.add(field);
var referenceKinds = {
  projectIds: ["projects"],
  caseId: ["cases"],
  caseIds: ["cases"],
  sourceIds: ["sources"],
  milestoneIds: ["milestones"],
  deliverableIds: ["sources"],
  acceptanceEvidenceIds: ["sources"],
  predecessorIds: ["milestones", "actions", "dependencies", "resources"],
  affectedIds: null,
  objectIds: null,
  resourceIds: ["resources"],
  personIds: ["people"],
  ownerId: ["people"],
  executorId: ["people"],
  acceptorId: ["people"],
  followUpOwnerId: ["people"],
  deciderId: ["people"],
  authorId: ["people"],
  creatorId: ["people"],
  fromId: null,
  toId: null,
  supersedesId: ["sources"],
  mergedIntoId: null,
  flowNodeIds: ["flowNodes"],
  outputIds: ["deliverables"],
  evidenceIds: ["sources"],
  actionIds: ["actions"],
  parentDeliverableIds: ["deliverables"],
  localObjectId: null
};
stringFields.add("nodeType");
stringFields.add("nextGateId");
var versionOf = (item) => Number.isSafeInteger(item?.version) ? item.version : 1;
function fail7(errors, status2 = 422) {
  const error2 = new Error(errors[0]?.message || "\u64CD\u4F5C\u65E0\u6548");
  error2.errors = errors;
  error2.status = status2;
  throw error2;
}
function requireValid(errors, status2 = 422) {
  if (errors.length) fail7(errors, status2);
}
function lookupV2(s, id2) {
  for (const kind of v2Kinds) {
    const found = s[kind]?.find((row) => row.id === id2);
    if (found) return found;
  }
}
function kindOf(s, id2) {
  return v2Kinds.find((kind) => s[kind]?.some((row) => row.id === id2));
}
function validDate3(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const [year, month, day] = match.slice(1).map(Number);
  if (year < 1 || month < 1 || month > 12) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return day > 0 && day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}
function references(row) {
  const refs = [];
  for (const [field, kinds] of Object.entries(referenceKinds)) {
    const value = row[field];
    if (value == null || value === "") continue;
    for (const id2 of Array.isArray(value) ? value : [value]) refs.push({ field, id: id2, kinds });
  }
  for (const ref of Array.isArray(row.basisRefs) ? row.basisRefs : []) if (object7(ref)) refs.push({ field: "basisRefs", id: ref.objectId, kinds: null });
  return refs;
}
function fieldsValid(row, path, patch = false, legacyEventTimes = {}, kind) {
  const errors = [];
  for (const [field, value] of Object.entries(row)) {
    const at = `${path}.${field}`;
    if (field === "workItem" && (!object7(value) || value.schemaVersion !== 1 || !["progress", "action", "risk", "decision", "result", "reference", "noise"].includes(value.nature) || !object7(value.association) || !Array.isArray(value.evidence) || !Array.isArray(value.reviews) || !Array.isArray(value.history) || !Number.isInteger(value.semanticRevision) || value.semanticRevision < 1)) errors.push({ path: at, message: "\u6574\u5408\u4E8B\u9879\u53CA\u5386\u53F2\u683C\u5F0F\u65E0\u6548" });
    if (field === "workItem" && object7(value)) {
      const a = value.association;
      if (!object7(a) || !["project", "case", "personal", "unknown"].includes(a.kind) || typeof a.id !== "string" || typeof a.confirmed !== "boolean" || !Array.isArray(value.evidence) || value.evidence.some((proof) => !object7(proof) || !idValid(proof.sourceId) || typeof proof.key !== "string" || typeof proof.fingerprint !== "string") || !Array.isArray(value.reviews) || value.reviews.some((review) => !object7(review) || !["confirmed", "dismissed", "resolved"].includes(review.decision) || typeof review.basis !== "string" || !textValid(review.reason, 1e3) || !review.reason.trim()) || !object7(value.handling) || value.handling.state !== void 0 && !["attention", "waiting", "in_progress", "handled"].includes(value.handling.state)) errors.push({ path: at, message: "\u6574\u5408\u4E8B\u9879\u7684\u5F52\u5C5E\u3001\u8BC1\u636E\u6216\u5904\u7406\u7ED3\u8BBA\u65E0\u6548" });
    }
    if (field === "workItem" && object7(value)) {
      if (value.decisions !== void 0 && (!Array.isArray(value.decisions) || value.decisions.some((decision) => !object7(decision) || !textValid(decision.text, 1e3) || !decision.text.trim() || typeof decision.basis !== "string" || typeof decision.at !== "string"))) errors.push({ path: at, message: "\u51B3\u5B9A\u8BB0\u5F55\u65E0\u6548" });
      if (value.disposition !== void 0 && (!object7(value.disposition) || !["active", "ignored"].includes(value.disposition.state))) errors.push({ path: at, message: "\u4E8B\u9879\u5173\u6CE8\u72B6\u6001\u65E0\u6548" });
      if (value.human !== void 0 && (!object7(value.human) || !Array.isArray(value.human.fields) || value.human.fields.some((key2) => !["title", "summary", "nature", "impact", "nextStep", "urgency"].includes(key2)))) errors.push({ path: at, message: "\u4EBA\u5DE5\u66F4\u6B63\u8BB0\u5F55\u65E0\u6548" });
      if (value.pendingChange != null && (!object7(value.pendingChange) || !idValid(value.pendingChange.id) || !["progress", "action", "risk", "decision", "result", "reference", "noise"].includes(value.pendingChange.nature) || !textValid(value.pendingChange.summary, 1600) || !Array.isArray(value.pendingChange.sourceIds))) errors.push({ path: at, message: "\u5F85\u6838\u5BF9\u53D8\u5316\u65E0\u6548" });
    }
    if (field === "managementSignal" && (!object7(value) || value.schemaVersion !== 1 || !["rule", "agent", "dot"].includes(value.origin) || !["attention", "routine"].includes(value.priority) || ["originId", "title", "summary", "nextStep", "quote", "sourceId"].some((key2) => typeof value[key2] !== "string") || !Array.isArray(value.reviews) || value.reviews.some((review) => !object7(review) || !["confirmed", "dismissed", "resolved"].includes(review.decision) || !textValid(review.reason, 1e3) || !review.reason.trim() || typeof review.basis !== "string" || typeof review.at !== "string") || value.target !== null && (!object7(value.target) || !["projects", "flowNodes", "deliverables", "actions", "milestones", "risks", "decisions", "cases", "dependencies"].includes(value.target.kind) || !idValid(value.target.id)) || value.origin === "rule" && (!object7(value.rule) || !object7(value.rule.bundle) || !object7(value.rule.bundle.appliesTo) || !Array.isArray(value.rule.bundle.appliesTo.projectTypes) || !Array.isArray(value.rule.bundle.appliesTo.levels) || typeof value.rule.check !== "string") || ["agent", "dot"].includes(value.origin) && typeof value.sourceBasis !== "string")) errors.push({ path: at, message: "\u7BA1\u7406\u63D0\u793A\u53CA\u5904\u7406\u5386\u53F2\u683C\u5F0F\u65E0\u6548" });
    if (field === "managementSignal" && object7(value) && value.triage !== void 0) {
      const t = value.triage, a = t?.association;
      if (!object7(t) || !["risk", "intervention"].includes(t.kind) || !["normal", "urgent"].includes(t.urgency) || !textValid(t.title, 200) || !t.title.trim() || !textValid(t.impact, 1200) || !t.impact.trim() || !object7(a) || !["project", "case", "new_case", "unknown"].includes(a.kind) || !textValid(a.reason, 1e3) || !a.reason.trim() || ["project", "case"].includes(a.kind) && !idValid(a.id) || a.kind === "new_case" && (!textValid(a.title, 200) || !a.title.trim())) errors.push({ path: at, message: "\u98CE\u9669\u8BC6\u522B\u7684\u5F71\u54CD\u3001\u7D27\u8FEB\u5EA6\u6216\u5F52\u5C5E\u5EFA\u8BAE\u65E0\u6548" });
    }
    if (field === "riskEvidence" && (!object7(value) || value.schemaVersion !== 1 || typeof value.jobId !== "string" || !Array.isArray(value.bases) || !value.bases.length || value.bases.some((b) => !object7(b) || typeof b.sourceId !== "string" || typeof b.basis !== "string") || !Array.isArray(value.imageIds) || typeof value.complete !== "boolean" || !Array.isArray(value.limitations))) errors.push({ path: at, message: "\u98CE\u9669\u8865\u67E5\u4F9D\u636E\u683C\u5F0F\u65E0\u6548" });
    if (field === "managementSignal" && object7(value) && value.evidence !== void 0 && (!Array.isArray(value.evidence) || value.evidence.length > 8 || value.evidence.some((p) => !object7(p) || !idValid(p.sourceId) || typeof p.basis !== "string" || !["text", "image"].includes(p.kind) || !textValid(p.quote, 600) || !textValid(p.interpretation, 1e3)))) errors.push({ path: at, message: "\u98CE\u9669\u5F15\u7528\u683C\u5F0F\u65E0\u6548" });
    if (field === "subjectAssociation" && (!object7(value) || value.schemaVersion !== 1 || !textValid(value.key, 1024) || !value.key || !object7(value.target) || !["projects", "cases"].includes(value.target.kind) || !idValid(value.target.id) || !textValid(value.decidedAt, 64) || value.decidedBy !== "\u672C\u4EBA" || !Array.isArray(value.history))) errors.push({ path: at, message: "\u4E8B\u9879\u5F52\u5C5E\u8BB0\u5F55\u683C\u5F0F\u65E0\u6548" });
    if (field === "chatScope" && (!object7(value) || value.schemaVersion !== 1 || !["project", "manual"].includes(value.origin) || !["active", "disabled", "unknown", "historical"].includes(value.state) || ["chatId", "projectId", "scope", "accountId", "collectFrom"].some((key2) => typeof value[key2] !== "string") || value.state === "active" && !/^oc_[a-zA-Z0-9]{8,100}$/.test(value.chatId))) errors.push({ path: at, message: "\u7FA4\u91C7\u96C6\u8303\u56F4\u8BB0\u5F55\u65E0\u6548" });
    if (field === "projectChat" && (!object7(value) || value.schemaVersion !== 1 || !Array.isArray(value.scopeIds) || value.scopeIds.some((id2) => !idValid(id2)))) errors.push({ path: at, message: "\u9879\u76EE\u7FA4\u6765\u6E90\u8EAB\u4EFD\u65E0\u6548" });
    if (patch && protectedFields.has(field)) errors.push({ path: at, message: `${field} \u4E3A\u7CFB\u7EDF\u7EF4\u62A4\u5B57\u6BB5\uFF0C\u4E0D\u53EF\u76F4\u63A5\u4FEE\u6539` });
    if (field === "title" && (!textValid(value, 1e3) || !value.trim())) errors.push({ path: at, message: "\u6807\u9898\u987B\u4E3A 1\u20131000 \u4E2A\u5B57\u7B26" });
    if (stringFields.has(field) && typeof value !== "string") errors.push({ path: at, message: "\u6B64\u5B57\u6BB5\u987B\u4E3A\u6587\u5B57\uFF1B\u6E05\u7A7A\u8BF7\u4F7F\u7528\u7A7A\u5B57\u7B26\u4E32" });
    if (field === "priority" && kind === "projects" && !["", "\u5F85\u6392\u5E8F", "P1", "P2", "P3"].includes(value)) errors.push({ path: at, message: "\u9879\u76EE\u4F18\u5148\u7EA7\u987B\u4E3A P1\u3001P2\u3001P3 \u6216\u5F85\u6392\u5E8F" });
    if (field === "sortOrder" && (typeof value !== "number" || !Number.isFinite(value) || value < 0)) errors.push({ path: at, message: "\u6392\u5E8F\u4F4D\u7F6E\u987B\u4E3A\u6709\u9650\u7684\u975E\u8D1F\u6570\uFF1B\u672A\u6392\u5E8F\u65F6\u53EF\u7701\u7565\u6B64\u5B57\u6BB5" });
    if (field === "collaboratingDepartments" && (!Array.isArray(value) || value.some((name) => !textValid(name, 200) || !name.trim()) || new Set(value.map((name) => typeof name === "string" ? name.trim() : name)).size !== value.length)) errors.push({ path: at, message: "\u534F\u4F5C\u90E8\u95E8\u987B\u4E3A\u4E0D\u91CD\u590D\u7684\u975E\u7A7A\u6587\u5B57\u6570\u7EC4" });
    if (field === "processingStatus" && !["", "\u5F85\u6574\u7406", "\u5DF2\u6574\u7406"].includes(value)) errors.push({ path: at, message: "\u8D44\u6599\u6574\u7406\u72B6\u6001\u987B\u4E3A\u5F85\u6574\u7406\u6216\u5DF2\u6574\u7406" });
    if (field === "planTemplate" && (kind !== "projects" || !planTemplates.some((template) => template.id === value))) errors.push({ path: at, message: "\u8BF7\u9009\u62E9\u901A\u7528\u3001IPD \u6216 IRAD \u9879\u76EE\u6D41\u7A0B\u6846\u67B6" });
    if (field === "planStageId" && (!["milestones", "actions", "flowNodes"].includes(kind || "") || value !== "" && !planStageIds.has(value))) errors.push({ path: at, message: "\u8BF7\u9009\u62E9\u6709\u6548\u7684\u8BA1\u5212\u9636\u6BB5\uFF0C\u6216\u4FDD\u7559\u5F85\u5F52\u5165\u9636\u6BB5" });
    if (field === "planOrder" && (typeof value !== "number" || !Number.isFinite(value) || value < 0)) errors.push({ path: at, message: "\u8BA1\u5212\u6392\u5E8F\u987B\u4E3A\u975E\u8D1F\u6570" });
    if (typeof value === "string" && value.length > 2e5) errors.push({ path: at, message: "\u5B57\u6BB5\u5185\u5BB9\u8FC7\u957F" });
    if (dateFields.has(field) && value !== "" && value != null && (typeof value !== "string" || !validDate3(value))) errors.push({ path: at, message: "\u8BF7\u8F93\u5165\u6709\u6548\u7684\u672C\u5730\u65E5\u5386\u65E5\u671F YYYY-MM-DD" });
    const historicalLocalEvent = field !== "dispatchPreparedAt" && !patch && (legacyEventTimes[field] && legacyEventTimes[field] === value || !own3(row, "workspaceId") && !own3(row, "version")) && typeof value === "string" && /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?$/.test(value) && validDate3(value.slice(0, 10)) && Number.isFinite(Date.parse(value));
    if (eventFields.has(field) && value !== "" && value != null && !historicalLocalEvent && (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !validDate3(value.slice(0, 10)) || !Number.isFinite(Date.parse(value)))) errors.push({ path: at, message: "\u4E8B\u4EF6\u65F6\u95F4\u987B\u5305\u542B\u65F6\u533A\uFF0C\u5982 2026-09-15T09:30:00+08:00" });
    if (["confirmed", "archived", "verified", "identityVerified"].includes(field) && typeof value !== "boolean") errors.push({ path: at, message: "\u8BF7\u4F7F\u7528 true \u6216 false" });
    const enums = { nodeStatus: ["\u5F85\u5F00\u59CB", "\u8FDB\u884C\u4E2D", "\u5DF2\u5B8C\u6210", "\u5F85\u786E\u8BA4"], submissionStatus: ["\u672A\u63D0\u4EA4", "\u5DF2\u63D0\u4EA4", "\u9700\u8865\u5145", "\u514D\u4EA4\u4ED8"], executionChannel: ["local", "meegle_subtask", "meegle_workitem", "feishu_task"], dispatchDateBasis: ["", "planned", "committed", "custom"], feishuIdType: ["", "open_id", "user_id", "union_id"] };
    if (enums[field] && !enums[field].includes(value)) errors.push({ path: at, message: `${field} \u7684\u9009\u9879\u65E0\u6548` });
    if (field === "nodeType" && (kind !== "flowNodes" || !["", "\u6309\u9879\u76EE\u89C4\u5219", "\u5F85\u786E\u8BA4", "\u666E\u901A\u8282\u70B9", "\u91CC\u7A0B\u7891\u8282\u70B9"].includes(value))) errors.push({ path: at, message: "\u8282\u70B9\u7C7B\u578B\u987B\u4E3A\u6309\u9879\u76EE\u89C4\u5219\u3001\u666E\u901A\u8282\u70B9\u3001\u91CC\u7A0B\u7891\u8282\u70B9\u6216\u5F85\u786E\u8BA4\uFF0C\u4EC5\u7528\u4E8E\u6D41\u7A0B\u8282\u70B9" });
    if (field === "nextGateId" && (kind !== "projects" || value !== "" && !idValid(value))) errors.push({ path: at, message: "\u4E0B\u4E00\u5173\u53E3\u9009\u62E9\u53EA\u9002\u7528\u4E8E\u9879\u76EE\uFF0C\u987B\u4F7F\u7528\u6709\u6548\u8282\u70B9\u8EAB\u4EFD\u6216\u6E05\u7A7A\u4E3A\u6309\u8BA1\u5212\u9009\u53D6" });
    if (kind === "deliverables" && field === "acceptanceStatus" && !["\u5F85\u9A8C\u6536", "\u8BC1\u636E\u4E0D\u8DB3", "\u5DF2\u9A8C\u6536", "\u672A\u901A\u8FC7"].includes(value)) errors.push({ path: at, message: "\u4EA4\u4ED8\u7269\u9A8C\u6536\u72B6\u6001\u987B\u4E3A\u5F85\u9A8C\u6536\u3001\u8BC1\u636E\u4E0D\u8DB3\u3001\u5DF2\u9A8C\u6536\u6216\u672A\u901A\u8FC7" });
    if (kind === "deliverables" && field === "deliveryReview" && !["\u672A\u5BA1\u6838", "\u5DF2\u5BA1\u6838"].includes(value)) errors.push({ path: at, message: "\u4EA4\u4ED8\u7269\u5BA1\u6838\u987B\u4E3A\u672A\u5BA1\u6838\u6216\u5DF2\u5BA1\u6838" });
    if (kind === "deliverables" && field === "status" && !["\u672A\u5F00\u59CB", "\u8FDB\u884C\u4E2D", "\u5DF2\u7ED3\u675F"].includes(value)) errors.push({ path: at, message: "\u4EA4\u4ED8\u7269\u72B6\u6001\u987B\u4E3A\u672A\u5F00\u59CB\u3001\u8FDB\u884C\u4E2D\u6216\u5DF2\u7ED3\u675F" });
    if (field === "outputIds" && !["milestones", "actions"].includes(kind || "")) errors.push({ path: at, message: "\u4EA4\u4ED8\u7269\u5F15\u7528\u4EC5\u9002\u7528\u4E8E\u91CC\u7A0B\u7891\u548C\u884C\u52A8\u9879" });
    if (own3(referenceKinds, field)) {
      if (field.endsWith("Ids")) {
        if (!Array.isArray(value) || value.some((id2) => !idValid(id2)) || new Set(value).size !== value.length) errors.push({ path: at, message: "\u5173\u8054\u987B\u4E3A\u4E0D\u91CD\u590D\u7684\u5BF9\u8C61 ID \u6570\u7EC4" });
      } else if (value !== "" && value != null && !idValid(value)) errors.push({ path: at, message: "\u5173\u8054 ID \u683C\u5F0F\u65E0\u6548" });
    }
    if (field === "basisRefs" && (!Array.isArray(value) || value.some((ref) => !object7(ref) || !idValid(ref.objectId) || ref.field != null && (!textValid(ref.field, 100) || protectedFields.has(ref.field))))) errors.push({ path: at, message: "\u5224\u65AD\u4F9D\u636E\u987B\u4E3A\u542B objectId \u548C\u53EF\u9009 field \u7684\u5F15\u7528\u6570\u7EC4" });
    if (field === "url" && value && (typeof value !== "string" || !/^https?:\/\//i.test(value) && !(!patch && /^\/simulated-feishu\//.test(value)))) errors.push({ path: at, message: "\u539F\u59CB\u94FE\u63A5\u987B\u4E3A http \u6216 https" });
    if (field === "aliases" && (!Array.isArray(value) || value.some((alias) => !textValid(alias, 200)))) errors.push({ path: at, message: "\u522B\u540D\u987B\u4E3A\u6587\u5B57\u6570\u7EC4" });
    if (field === "classification" && !["fact", "suggestion", "hypothesis"].includes(value)) errors.push({ path: at, message: "\u5185\u5BB9\u6027\u8D28\u987B\u4E3A fact\u3001suggestion \u6216 hypothesis" });
    if (field === "attachments" && (!Array.isArray(value) || value.some((file) => !object7(file) || !idValid(file.id) || !textValid(file.name, 1e3) || typeof file.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(file.sha256)))) errors.push({ path: at, message: "\u9644\u4EF6\u987B\u4E3A\u672C\u5730\u5F52\u6863\u8FD4\u56DE\u7684\u8EAB\u4EFD\u3001\u540D\u79F0\u53CA SHA-256 \u6821\u9A8C\u8BB0\u5F55\u6570\u7EC4" });
    if (["__proto__", "prototype", "constructor"].includes(field)) errors.push({ path: at, message: "\u4E0D\u5141\u8BB8\u7684\u5B57\u6BB5" });
  }
  if (row.validFrom && row.validTo && row.validFrom > row.validTo) errors.push({ path: `${path}.validTo`, message: "\u9002\u7528\u7ED3\u675F\u65F6\u95F4\u4E0D\u80FD\u65E9\u4E8E\u5F00\u59CB\u65F6\u95F4" });
  if (row.plannedStart && row.plannedEnd && row.plannedStart > row.plannedEnd) errors.push({ path: `${path}.plannedEnd`, message: "\u8BA1\u5212\u5B8C\u6210\u65E5\u671F\u4E0D\u80FD\u65E9\u4E8E\u8BA1\u5212\u5F00\u59CB\u65E5\u671F" });
  return errors;
}
function relationTuple(row) {
  return canonical4([row.fromId, row.toId, row.type, row.role || "", row.validFrom || "", row.validTo || ""]);
}
function validateState(s) {
  const errors = [];
  if (!object7(s)) return [{ path: "state", message: "\u53F0\u8D26\u5FC5\u987B\u4E3A JSON \u5BF9\u8C61" }];
  s = hydrateStateCollections(s);
  if (!idValid(s.workspaceId)) errors.push({ path: "workspaceId", message: "\u5DE5\u4F5C\u533A ID \u65E0\u6548" });
  if (!textValid(s.workspaceName, 1e3) || !s.workspaceName.trim()) errors.push({ path: "workspaceName", message: "\u5DE5\u4F5C\u533A\u540D\u79F0\u65E0\u6548" });
  if (!["official", "demo", "legacy", "restored"].includes(s.workspaceType)) errors.push({ path: "workspaceType", message: "\u5DE5\u4F5C\u533A\u7C7B\u578B\u65E0\u6548" });
  if (s.schemaVersion !== 2) errors.push({ path: "schemaVersion", message: "\u4EC5\u652F\u6301\u6570\u636E\u7ED3\u6784\u7248\u672C 2" });
  if (!Number.isSafeInteger(s.revision) || s.revision < 0) errors.push({ path: "revision", message: "\u6570\u636E\u7248\u672C\u65E0\u6548" });
  for (const kind of v2Kinds) if (!Array.isArray(s[kind])) errors.push({ path: kind, message: "\u8BB0\u5F55\u96C6\u5408\u987B\u4E3A\u6570\u7EC4" });
  if (v2Kinds.some((kind) => !Array.isArray(s[kind]))) return errors;
  const index = /* @__PURE__ */ new Map();
  for (const kind of v2Kinds) s[kind].forEach((row, i) => {
    const path = `${kind}.${i}`;
    if (!object7(row)) {
      errors.push({ path, message: "\u8BB0\u5F55\u987B\u4E3A\u5BF9\u8C61" });
      return;
    }
    if (!idValid(row.id)) errors.push({ path: `${path}.id`, message: "\u5BF9\u8C61 ID \u65E0\u6548" });
    if (index.has(row.id)) errors.push({ path: `${path}.id`, message: "\u5BF9\u8C61 ID \u5728\u5DE5\u4F5C\u533A\u5185\u5FC5\u987B\u552F\u4E00" });
    else index.set(row.id, { kind, row });
    if (row.workspaceId && row.workspaceId !== s.workspaceId) errors.push({ path: `${path}.workspaceId`, message: "\u5BF9\u8C61\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A" });
    if (row.version != null && (!Number.isSafeInteger(row.version) || row.version < 1)) errors.push({ path: `${path}.version`, message: "\u5BF9\u8C61\u7248\u672C\u65E0\u6548" });
    if (!textValid(row.title, 1e3) || !row.title.trim()) errors.push({ path: `${path}.title`, message: "\u8BB0\u5F55\u7F3A\u5C11\u6807\u9898" });
    if (!Array.isArray(row.projectIds) || !Array.isArray(row.sourceIds)) errors.push({ path, message: "\u8BB0\u5F55\u7F3A\u5C11\u9879\u76EE\u6216\u6765\u6E90\u5F15\u7528\u6570\u7EC4" });
    errors.push(...fieldsValid(row, path, false, s.legacyEventTimes?.[row.id], kind));
  });
  const tuples = /* @__PURE__ */ new Set(), remoteBindings = /* @__PURE__ */ new Map();
  for (const kind of v2Kinds) s[kind].forEach((row, i) => {
    if (!object7(row)) return;
    const path = `${kind}.${i}`;
    for (const ref of references(row)) {
      const target = index.get(ref.id);
      if (!target) errors.push({ path: `${path}.${ref.field}`, message: `\u5173\u8054 ${String(ref.id)} \u4E0D\u5728\u5F53\u524D\u5DE5\u4F5C\u533A\u5185` });
      else if (ref.kinds && !ref.kinds.includes(target.kind)) errors.push({ path: `${path}.${ref.field}`, message: `\u5173\u8054 ${ref.id} \u7684\u5BF9\u8C61\u7C7B\u578B\u4E0D\u6B63\u786E` });
      else if (ref.field === "mergedIntoId" && (target.kind !== kind || target.row.id === row.id)) errors.push({ path: `${path}.${ref.field}`, message: "\u53EA\u80FD\u5408\u5E76\u5230\u540C\u7C7B\u578B\u7684\u53E6\u4E00\u5BF9\u8C61" });
    }
    if (kind === "relations") {
      if (!row.fromId || !row.toId || !textValid(row.type, 100) || !row.type.trim()) errors.push({ path, message: "\u5173\u7CFB\u987B\u6307\u5B9A\u8D77\u70B9\u3001\u7EC8\u70B9\u548C\u5173\u7CFB\u7C7B\u578B" });
      if (!row.archived) {
        const tuple = relationTuple(row);
        if (tuples.has(tuple)) errors.push({ path, message: "\u76F8\u540C\u65B9\u5411\u3001\u7C7B\u578B\u53CA\u9002\u7528\u65F6\u95F4\u7684\u5173\u7CFB\u5DF2\u5B58\u5728" });
        tuples.add(tuple);
      }
    }
    if (kind === "people") errors.push(...personIdentityErrors(row, path));
    if (kind === "externalLinks") {
      errors.push(...externalLinkErrors(row, path, index.get(row.localObjectId)?.kind));
      if (!row.archived) {
        const identity = externalIdentity(row), existing = remoteBindings.get(identity);
        if (existing) errors.push({ path: `${path}.remoteId`, message: existing === row.localObjectId ? "\u76F8\u540C\u5916\u90E8\u8EAB\u4EFD\u5DF2\u7ECF\u5173\u8054\u5230\u6B64\u672C\u5730\u5BF9\u8C61" : "\u76F8\u540C\u5916\u90E8\u8EAB\u4EFD\u4E0D\u80FD\u91CD\u590D\u7ED1\u5B9A\u5230\u4E0D\u540C\u672C\u5730\u5BF9\u8C61" });
        else remoteBindings.set(identity, row.localObjectId);
      }
    }
  });
  for (const field of ["candidates", "publications", "reports"]) if (!Array.isArray(s[field])) errors.push({ path: field, message: "\u5386\u53F2\u5019\u9009\u3001\u53D1\u5E03\u6216\u6C47\u62A5\u96C6\u5408\u683C\u5F0F\u65E0\u6548" });
  if (!Array.isArray(s.changeGroups) || !Array.isArray(s.audit) || !object7(s.receipts)) errors.push({ path: "state", message: "\u7F3A\u5C11\u8349\u7A3F\u3001\u5BA1\u8BA1\u6216\u8BF7\u6C42\u56DE\u6267" });
  else for (const [i, group] of s.changeGroups.entries()) {
    if (!object7(group) || group.workspaceId !== s.workspaceId) errors.push({ path: `changeGroups.${i}.workspaceId`, message: "\u4FEE\u6539\u7EC4\u4E0D\u5C5E\u4E8E\u672C\u5DE5\u4F5C\u533A" });
    else if (!Array.isArray(group.operations) || !Number.isSafeInteger(group.draftVersion) || group.draftVersion < 1) errors.push({ path: `changeGroups.${i}`, message: "\u8349\u7A3F\u64CD\u4F5C\u6216\u7248\u672C\u65E0\u6548" });
    else {
      if (!idValid(group.id) || !["pending", "partial", "accepted", "conflict", "rejected", "withdrawn"].includes(group.status) || !Array.isArray(group.history) || !Array.isArray(group.auditIds)) errors.push({ path: `changeGroups.${i}`, message: "\u4FEE\u6539\u7EC4\u8EAB\u4EFD\u3001\u72B6\u6001\u6216\u5386\u53F2\u65E0\u6548" });
      for (const error2 of group.operations.flatMap(operationShape)) errors.push({ ...error2, path: `changeGroups.${i}.${error2.path}` });
    }
  }
  if (object7(s.receipts)) {
    for (const [key2, value] of Object.entries(s.receipts)) if (!idValid(key2) || !object7(value) || typeof value.fingerprint !== "string" || !object7(value.result)) errors.push({ path: `receipts.${key2}`, message: "\u8BF7\u6C42\u56DE\u6267\u683C\u5F0F\u635F\u574F" });
  }
  if (s.viewed !== null && (!object7(s.viewed) || !textValid(s.viewed.at) || !Array.isArray(s.viewed.auditIds))) errors.push({ path: "viewed", message: "\u67E5\u770B\u57FA\u7EBF\u683C\u5F0F\u65E0\u6548" });
  errors.push(...caseStateErrors(s));
  errors.push(...weeklyStateErrors(s));
  errors.push(...validateMappingRegistry(s));
  return errors;
}
function emptyState(id2, name, type = "official") {
  const base = { schemaVersion: 2, revision: 0, demo: type === "demo", seedDate: "", workspaceId: id2, workspaceName: name, workspaceType: type, candidates: [], publications: [], audit: [], changeGroups: [], viewed: null, receipts: {}, reports: [] };
  for (const kind of v2Kinds) base[kind] = [];
  for (const kind of registryKinds) base[kind] = [];
  return base;
}
function normalizeState(old, id2, name, type) {
  if (!object7(old) || ![1, 2].includes(old.schemaVersion)) fail7([{ path: "schemaVersion", message: "\u4E0D\u652F\u6301\u7684\u5386\u53F2\u6570\u636E\u7248\u672C" }]);
  const state = { ...emptyState(id2, name, type), ...clone2(old), schemaVersion: 2, workspaceId: id2, workspaceName: name, workspaceType: type };
  if (old.schemaVersion === 1) {
    const times = {};
    for (const source of old.sources || []) for (const field of eventFields) {
      const value = source[field];
      if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?$/.test(value)) (times[source.id] ||= {})[field] = value;
    }
    if (Object.keys(times).length) state.legacyEventTimes = times;
  }
  for (const kind of v2Kinds) if (!Array.isArray(state[kind])) fail7([{ path: kind, message: "\u5386\u53F2\u6570\u636E\u7F3A\u5C11\u5FC5\u9700\u96C6\u5408" }]);
  const grouped = new Set(state.changeGroups.flatMap((group) => group.legacyCandidateIds || []));
  for (const candidate of state.candidates) {
    if (candidate.status !== "pending" || grouped.has(candidate.id)) continue;
    const target = lookupV2(state, candidate.targetId);
    const value = candidate.field === "confirmed" ? candidate.value === "true" : candidate.value;
    const before = target ? { [candidate.field]: candidate.field === "confirmed" ? candidate.baseValue === "true" : candidate.baseValue } : {};
    const after = target ? { [candidate.field]: value } : { title: candidate.value, projectIds: clone2(candidate.projectIds), sourceIds: candidate.sourceId ? [candidate.sourceId] : [], confirmed: false, [candidate.field]: value };
    if (!target && candidate.kind === "judgments") after.confirmed = false;
    const input = { workspaceId: id2, request: `\u5386\u53F2\u5019\u9009\uFF1A${candidate.category}`, purpose: "\u5C06\u5386\u53F2\u672C\u5730\u89C4\u5219\u5019\u9009\u63A5\u5165\u7EDF\u4E00\u5BA1\u6838\uFF1B\u5C1A\u672A\u5E94\u7528", creator: candidate.mode || "\u5386\u53F2\u672C\u5730\u89C4\u5219", baseRevision: state.revision, idempotencyKey: `legacy-${candidate.id}`, operations: [{ id: `op-${candidate.id}`, kind: candidate.kind, targetId: candidate.targetId, action: target ? "update" : "create", before, after, reason: candidate.evidence || "\u5386\u53F2\u5019\u9009\uFF0C\u539F\u59CB\u4F9D\u636E\u5F85\u68C0\u67E5", sourceIds: candidate.sourceId ? [candidate.sourceId] : [], classification: "suggestion", missingInfo: [], status: "pending" }] };
    const group = { ...input, id: `legacy-group-${candidate.id}`, createdAt: now(), draftVersion: 1, fingerprint: canonical4(input), status: "pending", auditIds: [], history: [], operations: input.operations.map((op) => ({ ...op, sourceVersions: sourceVersions(state, op, input.operations) })) };
    group.legacyCandidateIds = [candidate.id];
    state.changeGroups.push(group);
  }
  return state;
}
function recordSyncPreparation(inputState, input) {
  const source = hydrateStateCollections(inputState);
  if (!idValid(input?.workspaceId) || input.workspaceId !== source.workspaceId) fail7([{ path: "workspaceId", message: "\u540C\u6B65\u51C6\u5907\u5FC5\u987B\u5C5E\u4E8E\u5F53\u524D\u5DE5\u4F5C\u533A" }]);
  if (!idValid(input.externalObjectId)) fail7([{ path: "externalObjectId", message: "\u540C\u6B65\u51C6\u5907\u5FC5\u987B\u6307\u5B9A\u5916\u90E8\u5BF9\u8C61" }]);
  if (!source.externalObjects.some((row) => row.id === input.externalObjectId)) fail7([{ path: "externalObjectId", message: "\u5916\u90E8\u5BF9\u8C61\u5C1A\u672A\u6CE8\u518C\uFF0C\u4E0D\u80FD\u751F\u6210\u5199\u56DE\u8349\u7A3F" }], 404);
  if (!idValid(input.idempotencyKey)) fail7([{ path: "idempotencyKey", message: "\u540C\u6B65\u51C6\u5907\u5FC5\u987B\u63D0\u4F9B\u7A33\u5B9A\u5E42\u7B49\u952E" }]);
  const fingerprint = canonical4({ command: "syncPrepare", input });
  const receiptKey = `sync-${input.idempotencyKey}`;
  const existing = source.receipts[receiptKey];
  if (existing) {
    if (existing.fingerprint !== fingerprint) fail7([{ path: "idempotencyKey", message: "\u540C\u4E00\u540C\u6B65\u5E42\u7B49\u952E\u4E0D\u80FD\u7528\u4E8E\u4E0D\u540C\u5185\u5BB9" }], 409);
    const run = source.syncRuns.find((row) => row.id === existing.result?.runId);
    if (!run) fail7([{ path: "syncRuns", message: "\u540C\u6B65\u5E42\u7B49\u56DE\u6267\u635F\u574F" }], 500);
    return { state: source, prepared: { run, differences: source.syncReceipts.filter((row) => row.syncRunId === run.id).map((row) => ({ id: `receipt-diff-${row.id}`, externalObjectId: row.externalObjectId, remoteFieldKey: "", remoteFieldName: "", localField: "", before: row.before, baseline: row.before, currentRemote: row.currentRemote, localValue: row.proposed, local: row.proposed, remoteChanged: false, localChanged: true, conflict: row.status === "conflict", writable: row.status !== "conflict", requiresReview: true, bidirectional: true, reason: row.status === "conflict" ? "\u5DF2\u505C\u6B62\u5199\u56DE" : "\u5DF2\u4FDD\u5B58\u5BA1\u6838\u8349\u7A3F" })), receipts: source.syncReceipts.filter((row) => row.syncRunId === run.id), externalWriteExecuted: false, canWriteBack: run.status !== "conflict" } };
  }
  const prepared = prepareWriteback(input);
  const state = clone2(source);
  state.syncRuns.push(clone2(prepared.run));
  state.syncReceipts.push(...clone2(prepared.receipts));
  if (input.baselineId && source.syncBaselines.some((row) => row.id === input.baselineId)) {
    for (const receipt2 of state.syncReceipts.filter((row) => row.syncRunId === prepared.run.id)) receipt2.evidenceIds = [.../* @__PURE__ */ new Set([...receipt2.evidenceIds, input.baselineId])];
  }
  state.revision += 1;
  state.receipts[receiptKey] = { fingerprint, result: { runId: prepared.run.id, status: prepared.run.status } };
  requireValid(validateState(state));
  return { state, prepared };
}
function approveSyncPreparation(inputState, input) {
  const source = hydrateStateCollections(inputState);
  if (input.workspaceId !== source.workspaceId) fail7([{ path: "workspaceId", message: "\u5BA1\u6838\u8BB0\u5F55\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A" }]);
  if (!idValid(input.runId) || !idValid(input.requestId) || !textValid(input.approvedBy, 500) || !input.approvedBy.trim()) fail7([{ path: "approval", message: "\u5BA1\u6838\u5FC5\u987B\u63D0\u4F9B\u6709\u6548\u7684\u540C\u6B65\u8FD0\u884C ID\u3001\u8BF7\u6C42 ID \u548C\u5BA1\u6838\u4EBA" }]);
  const fingerprint = canonical4({ command: "syncApprove", runId: input.runId, approvedBy: input.approvedBy, approvalComment: input.approvalComment || "" });
  const prior = receipt(source, input.requestId, fingerprint);
  if (prior) {
    const run2 = source.syncRuns.find((row) => row.id === prior.result?.runId);
    if (!run2) fail7([{ path: "receipt", message: "\u540C\u6B65\u5BA1\u6838\u56DE\u6267\u635F\u574F" }], 500);
    return { state: source, run: run2 };
  }
  const current = source.syncRuns.find((row) => row.id === input.runId);
  if (!current) fail7([{ path: "runId", message: "\u540C\u6B65\u8FD0\u884C\u8BB0\u5F55\u4E0D\u5B58\u5728" }], 404);
  if (current.status === "conflict" || current.conflictIds.length) fail7([{ path: "runId", message: "\u5B58\u5728\u4E09\u65B9\u51B2\u7A81\uFF0C\u4E0D\u80FD\u5BA1\u6838\u901A\u8FC7\uFF1B\u8BF7\u91CD\u65B0\u8BFB\u53D6\u8FDC\u7AEF\u5E76\u751F\u6210\u65B0\u8349\u7A3F" }], 409);
  if (!["prepared", "pending_review"].includes(current.status)) fail7([{ path: "runId", message: `\u5F53\u524D\u540C\u6B65\u8FD0\u884C\u72B6\u6001\u4E3A ${current.status}\uFF0C\u4E0D\u80FD\u91CD\u590D\u5BA1\u6838` }], 409);
  const state = clone2(source);
  const run = state.syncRuns.find((row) => row.id === input.runId);
  run.status = "approved";
  run.approvedBy = input.approvedBy.trim();
  run.approvedAt = now();
  run.approvalComment = input.approvalComment || "";
  for (const receiptRow of state.syncReceipts.filter((row) => row.syncRunId === run.id && ["prepared", "pending_review"].includes(row.status))) receiptRow.status = "approved";
  finish(state, input.requestId, fingerprint, { runId: run.id, status: run.status, approvedBy: run.approvedBy, approvedAt: run.approvedAt });
  requireValid(validateState(state));
  return { state, run };
}
var registryHash = (value) => stableHash(canonical4(value));
var snapshotObjectKey = (kind, row) => kind === "projects" ? `project:${String(row.sourceId || "")}` : kind === "nodes" ? `node:${String(row.projectId || "")}:${String(row.sourceId || "")}` : `deliverable:${String(row.sourceId || "")}`;
var localObjectKey = (kind, row) => {
  const source = typeof row?.importedFrom?.sourceId === "string" ? row.importedFrom.sourceId : "";
  if (!source) return "";
  return kind === "projects" ? source.startsWith("project:") ? source : `project:${source}` : kind === "flowNodes" ? source.startsWith("node:") ? source : `node:${source}` : source.startsWith("deliverable:") ? source : `deliverable:${source}`;
};
var registryValueType = (value) => {
  if (value === null || value === void 0) return "unknown";
  if (Array.isArray(value)) return "multi_option";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return "number";
  if (typeof value === "string") return /^\d{4}-\d{2}-\d{2}(?:T|$)/.test(value) ? value.includes("T") ? "datetime" : "date" : "text";
  if (typeof value === "object") return "option";
  return "unknown";
};
var displayRemoteValue = (value) => {
  if (value === null || value === void 0) return "";
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const row = value;
    for (const key2 of ["label", "name", "display_name", "displayName", "value", "text"]) if (typeof row[key2] === "string") return row[key2];
  }
  return JSON.stringify(value);
};
var remoteOptionId = (value) => value && typeof value === "object" ? String(value.value || value.key || "") : "";
var mappedLocalField = (remoteKind, field) => ({
  "project:description": "description",
  "project:field_5a13c8": "projectProgress",
  "project:field_09e17e": "code",
  "project:field_3ee030": "projectCategory",
  "project:field_d72ed3": "sourceStage",
  "node:owner": "owner",
  "node:status": "nodeStatus",
  "node:sourceStage": "sourceStage",
  "node:sourceStatus": "sourceStatus",
  "deliverable:description": "description",
  "deliverable:field_d014b4": "deliverableProgress",
  "deliverable:field_b462b3": "deliveryReview",
  "deliverable:work_item_status": "status",
  "deliverable:field_a9eec5": "owner",
  "deliverable:field_663373": "plannedEnd",
  "deliverable:field_922242": "resultLink"
})[`${remoteKind}:${field}`] || "";
function registerRemoteSnapshot(inputState, input) {
  const source = hydrateStateCollections(inputState);
  if (input.workspaceId !== source.workspaceId) fail7([{ path: "workspaceId", message: "\u6CE8\u518C\u8868\u5BFC\u5165\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A" }]);
  if (!idValid(input.idempotencyKey) || !input.snapshot || typeof input.snapshot !== "object") fail7([{ path: "snapshot", message: "\u6CE8\u518C\u8868\u5BFC\u5165\u5FC5\u987B\u63D0\u4F9B\u5FEB\u7167\u548C\u7A33\u5B9A\u5E42\u7B49\u952E" }]);
  const sourceHash2 = registryHash(input.snapshot), receiptKey = `registry-${input.idempotencyKey}`, fingerprint = canonical4({ command: "registryRegister", workspaceId: input.workspaceId, sourceHash: sourceHash2 });
  const prior = receipt(source, receiptKey, fingerprint);
  if (prior) return { state: source, summary: prior.result };
  if (registryKinds.some((kind) => source[kind].length)) fail7([{ path: "registry", message: "\u5F53\u524D\u5DE5\u4F5C\u533A\u5DF2\u6709\u6620\u5C04\u6CE8\u518C\u8868\uFF1B\u8BF7\u4F7F\u7528\u540C\u4E00\u5E42\u7B49\u952E\u91CD\u8BD5\u6216\u5148\u751F\u6210\u5DEE\u5F02\uFF0C\u4E0D\u80FD\u8986\u76D6\u65E2\u6709\u8EAB\u4EFD" }], 409);
  const snapshot = input.snapshot, scope = snapshot.scope || {}, tenantKey = String(scope.projectKey || scope.tenant || ""), spaceKey = String(scope.simpleName || scope.spaceKey || ""), host = "project.feishu.cn";
  const localByKey = /* @__PURE__ */ new Map();
  for (const row of source.projects) {
    const key2 = localObjectKey("projects", row);
    if (key2) localByKey.set(key2, row);
  }
  for (const row of source.flowNodes) {
    const key2 = localObjectKey("flowNodes", row);
    if (key2) localByKey.set(key2, row);
  }
  for (const row of source.deliverables) {
    const key2 = localObjectKey("deliverables", row);
    if (key2) localByKey.set(key2, row);
  }
  const remoteRows = [
    ...Array.isArray(snapshot.projects) ? snapshot.projects.map((row) => ({ kind: "projects", row, remoteKind: "project" })) : [],
    ...Array.isArray(snapshot.nodes) ? snapshot.nodes.map((row) => ({ kind: "nodes", row, remoteKind: "node" })) : [],
    ...Array.isArray(snapshot.deliverables) ? snapshot.deliverables.map((row) => ({ kind: "deliverables", row, remoteKind: "deliverable" })) : []
  ];
  const externalObjects = [], remoteFieldValues = [], mappingRules = [], syncBaselines = [];
  const externalByKey = /* @__PURE__ */ new Map();
  const ruleByKey = /* @__PURE__ */ new Map();
  const quarantined = { projects: 0, nodes: 0, deliverables: 0 };
  const projectIdFor = (row, kind) => kind === "project" ? String(row.sourceId || "") : String(row.projectId || "");
  for (const entry of remoteRows) {
    const row = entry.row, remoteKey = snapshotObjectKey(entry.kind, row), local = localByKey.get(remoteKey), remoteId = entry.remoteKind === "project" ? String(row.sourceId || "") : entry.remoteKind === "node" ? String(row.sourceId || "") : String(row.sourceId || ""), projectId = projectIdFor(row, entry.remoteKind), nodeId = entry.remoteKind === "deliverable" ? String(row.nodeId || "") : "", parentDeliverableId = entry.remoteKind === "deliverable" ? String(row.parentDeliverableId || "") : "";
    if (!local) {
      quarantined[entry.kind]++;
      continue;
    }
    const localParentNode = entry.remoteKind === "deliverable" ? source.flowNodes.find((node) => (node.flowNodeIds || []).includes(local.id)) : void 0;
    const parentNodeRemoteId = entry.remoteKind === "deliverable" ? String((localParentNode?.importedFrom?.sourceId || "").replace(/^node:[^:]+:/, "")) || nodeId : "";
    const parentDeliverableRemoteId = entry.remoteKind === "deliverable" && local.parentDeliverableIds?.[0] ? String((source.deliverables.find((d) => d.id === local.parentDeliverableIds[0])?.importedFrom?.sourceId || "").replace(/^deliverable:/, "")) : "";
    const externalId = `external-${registryHash([host, tenantKey, spaceKey, entry.remoteKind, remoteId, projectId])}`;
    const object10 = { id: externalId, workspaceId: source.workspaceId, system: "meegle", host, tenantKey, spaceKey, remoteKind: entry.remoteKind, remoteId, parentRemoteId: entry.remoteKind === "project" ? "" : projectId, parentNodeRemoteId, parentDeliverableRemoteId, localObjectId: local.id, sourceId: local.sourceIds?.[0] || "", collectedAt: String(row.collectedAt || snapshot.collectedAt || ""), sourceHash: String(local.importedFrom?.contentSha256 || registryHash(row)), verificationStatus: "verified", mappingStatus: "mapped", raw: { ...row, registrySourcePath: input.sourcePath || "" }, url: String(row.url || local.importedFrom?.url || "") };
    externalObjects.push(object10);
    externalByKey.set(remoteKey, object10);
  }
  const allRemote = remoteRows.filter((entry) => externalByKey.has(snapshotObjectKey(entry.kind, entry.row)));
  for (const entry of allRemote) {
    const row = entry.row, remoteKey = snapshotObjectKey(entry.kind, row), object10 = externalByKey.get(remoteKey);
    const fields = { ...row.fields && typeof row.fields === "object" ? row.fields : {} };
    if (entry.remoteKind === "node" && row.raw && typeof row.raw === "object") {
      for (const key2 of ["basic", "schedule", "assignees"]) if (Object.hasOwn(row.raw, key2)) fields[`raw.${key2}`] = row.raw[key2];
    }
    const local = localByKey.get(remoteKey), localValues = {};
    for (const [field, value] of Object.entries(fields)) {
      const localField = mappedLocalField(entry.remoteKind, field), ruleKey = `meegle/${entry.remoteKind}/${field}`;
      let rule = ruleByKey.get(ruleKey);
      if (!rule) {
        rule = { id: `mapping-${registryHash(ruleKey)}`, workspaceId: source.workspaceId, system: "meegle", remoteKind: entry.remoteKind, remoteFieldKey: field, remoteFieldName: field, remoteValueType: registryValueType(value), localKind: entry.remoteKind === "project" ? "projects" : entry.remoteKind === "node" ? "flowNodes" : "deliverables", localField, conversionRule: localField ? "identity" : "preserve_raw", writable: !!localField && ["description", "projectProgress", "deliverableProgress", "title", "dispatchTitle", "dispatchDescription", "resultLink"].includes(localField), requiresReview: true, bidirectional: false, status: "active" };
        mappingRules.push(rule);
        ruleByKey.set(ruleKey, rule);
      }
      if (localField) localValues[localField] = local[localField];
      remoteFieldValues.push({ id: `remote-field-${registryHash([object10.id, field])}`, workspaceId: source.workspaceId, externalObjectId: object10.id, remoteFieldKey: field, remoteFieldName: field, valueType: registryValueType(value), rawValue: clone2(value), optionId: remoteOptionId(value), displayName: displayRemoteValue(value), localField, mappingRuleId: rule.id, collectedAt: object10.collectedAt, sourceHash: object10.sourceHash });
    }
    const remoteValues = Object.fromEntries(Object.entries(fields));
    syncBaselines.push({ id: `baseline-${registryHash(object10.id)}`, workspaceId: source.workspaceId, externalObjectId: object10.id, capturedAt: object10.collectedAt, sourceHash: object10.sourceHash, remoteValues, localValues, localRevision: source.revision, sourceId: object10.sourceId });
  }
  const state = clone2(source);
  state.externalObjects = externalObjects;
  state.remoteFieldValues = remoteFieldValues;
  state.mappingRules = mappingRules;
  state.syncBaselines = syncBaselines;
  state.syncRuns = [];
  state.syncReceipts = [];
  state.dispatchRecords = [];
  state.revision += 1;
  const summary = { externalObjects: externalObjects.length, remoteFieldValues: remoteFieldValues.length, mappingRules: mappingRules.length, syncBaselines: syncBaselines.length, quarantined, sourceHash: sourceHash2 };
  state.receipts[receiptKey] = { fingerprint, result: summary };
  state.audit.push({ id: uid("audit"), time: now(), operation: "registry.register", objectId: "registry", before: { externalObjects: 0 }, after: summary });
  requireValid(validateState(state));
  return { state, summary };
}
function recordDispatchPreparation(inputState, input) {
  const source = hydrateStateCollections(inputState);
  if (input.workspaceId !== source.workspaceId) fail7([{ path: "workspaceId", message: "\u6D3E\u53D1\u8BB0\u5F55\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A" }]);
  const actionId = input.actionId || input.localObjectId;
  if (!idValid(actionId) || !source.actions.some((row) => row.id === actionId && !row.archived)) fail7([{ path: "actionId", message: "\u6D3E\u53D1\u8BB0\u5F55\u5FC5\u987B\u5173\u8054\u6709\u6548\u884C\u52A8\u9879" }], 404);
  if (!idValid(input.localObjectId) || !lookupV2(source, input.localObjectId)) fail7([{ path: "localObjectId", message: "\u6D3E\u53D1\u8BB0\u5F55\u672C\u5730\u5BF9\u8C61\u4E0D\u5B58\u5728" }], 404);
  if (!idValid(input.idempotencyKey)) fail7([{ path: "idempotencyKey", message: "\u6D3E\u53D1\u8BB0\u5F55\u5FC5\u987B\u63D0\u4F9B\u7A33\u5B9A\u5E42\u7B49\u952E" }]);
  if (input.testSpaceOnly === false || (input.officialSpaceKeys || []).includes(input.spaceKey || "")) fail7([{ path: "spaceKey", message: "\u6D3E\u53D1\u51C6\u5907\u53EA\u5141\u8BB8\u72EC\u7ACB\u6D4B\u8BD5\u7A7A\u95F4\uFF0C\u6B63\u5F0F\u7A7A\u95F4\u5199\u5165\u8FB9\u754C\u5DF2\u505C\u6B62" }], 403);
  const fingerprint = canonical4({ command: "dispatchPrepare", input });
  const receiptKey = `dispatch-${input.idempotencyKey}`;
  const prior = source.receipts[receiptKey];
  if (prior) {
    if (prior.fingerprint !== fingerprint) fail7([{ path: "idempotencyKey", message: "\u540C\u4E00\u6D3E\u53D1\u5E42\u7B49\u952E\u4E0D\u80FD\u7528\u4E8E\u4E0D\u540C\u5185\u5BB9" }], 409);
    const record3 = source.dispatchRecords.find((row) => row.id === prior.result?.recordId);
    if (!record3) fail7([{ path: "dispatchRecords", message: "\u6D3E\u53D1\u5E42\u7B49\u56DE\u6267\u635F\u574F" }], 500);
    return { state: source, record: record3 };
  }
  const timestamp = (/* @__PURE__ */ new Date()).toISOString();
  const record2 = { id: `dispatch-${input.idempotencyKey}`, workspaceId: source.workspaceId, localObjectId: input.localObjectId, actionId, targetSystem: input.targetSystem || "feishu_tasks", spaceKey: input.spaceKey || "", recipient: input.recipient || null, idempotencyKey: input.idempotencyKey, status: input.status || "prepared", remoteId: "", notificationReceipt: null, attempts: 0, createdAt: timestamp, updatedAt: timestamp, readbackVerified: false, externalWriteExecuted: false, error: "" };
  const state = clone2(source);
  state.dispatchRecords.push(record2);
  state.revision += 1;
  state.receipts[receiptKey] = { fingerprint, result: { recordId: record2.id, status: record2.status } };
  requireValid(validateState(state));
  return { state, record: record2 };
}
function defaults(s, kind, id2, after) {
  const common = { workspaceId: s.workspaceId, version: 1, createdAt: now(), updatedAt: now(), archived: false };
  const fields = {
    cases: { caseType: "\u4E34\u65F6\u4E13\u9879", myRole: "\u534F\u52A9\u8DDF\u8E2A", status: "\u5F85\u660E\u786E", roleHistory: [], closureHistory: [], reportApproval: { status: "\u5F85\u6838\u5BF9" }, verification: { status: "\u5F85\u9A8C\u8BC1" }, closure: null },
    projects: { code: "", goal: "", owner: "", phase: "\u5F85\u542F\u52A8", health: "\u5F85\u786E\u8BA4", healthReason: "", nextAction: "", description: "", projectProgress: "", progressNote: "", comments: [] },
    milestones: { committed: "", forecast: "", actual: "", owner: "", acceptance: "", deliverableIds: [], outputIds: [] },
    actions: { executor: "", acceptor: "", followUp: "", priority: "P2", dueAt: "", checkAt: "", lastContactAt: "", status: "\u4ECA\u5929\u9700\u8981\u63A8\u52A8", executionStatus: "\u5F85\u786E\u8BA4", acceptanceStatus: "\u5F85\u9A8C\u6536", acceptance: "", acceptanceEvidenceIds: [], milestoneIds: [], executionChannel: "local", flowNodeIds: [], outputIds: [] },
    risks: { type: "\u98CE\u9669", status: "\u5F85\u786E\u8BA4", impact: "\u5F85\u786E\u8BA4", description: "", response: "", owner: "", checkAt: "", confirmed: false, milestoneIds: [] },
    decisions: { status: "\u5F85\u51B3\u7B56", conclusion: "", basis: "", owner: "", deadline: "", decidedAt: "", history: [], milestoneIds: [] },
    dependencies: { predecessorIds: [], affectedIds: [], status: "\u5F85\u786E\u8BA4", type: "\u4EA4\u4ED8\u4F9D\u8D56", neededBy: "", owner: "" },
    sources: { type: "\u7C98\u8D34\u6587\u5B57", excerpt: "", url: "", occurredAt: "", collectedAt: now(), confirmed: false, objectIds: [] },
    judgments: { confirmed: false, author: "\u9879\u76EE\u7ECF\u7406", basisRefs: [], confirmationHistory: [], stale: false },
    people: { aliases: [], role: "" },
    resources: { aliases: [], type: "\u5171\u4EAB\u8D44\u6E90" },
    relations: { confirmed: false, validFrom: "", validTo: "", creator: "\u9879\u76EE\u7ECF\u7406", role: "" },
    flowNodes: { owner: "", nodeType: "\u6309\u9879\u76EE\u89C4\u5219", nodeStatus: "\u5F85\u786E\u8BA4", plannedStart: "", plannedEnd: "", sourceStage: "", sourceStatus: "", milestoneIds: [], progressNote: "" },
    deliverables: { owner: "", acceptor: "", plannedEnd: "", deliverableType: "", deliverableVersion: "", submissionStatus: "\u672A\u63D0\u4EA4", reviewStatus: "\u672A\u5BA1\u6838", deliveryReview: "\u672A\u5BA1\u6838", status: "\u672A\u5F00\u59CB", acceptanceStatus: "\u5F85\u9A8C\u6536", acceptance: "", description: "", deliverableProgress: "", progressNote: "", evidenceIds: [], actionIds: [], flowNodeIds: [], parentDeliverableIds: [], attachments: [], comments: [] },
    externalLinks: { verified: false, system: "meegle", remoteKind: "project", host: "", spaceKey: "", remoteId: "", parentRemoteId: "", url: "" }
  };
  const item = rec(id2, String(after.title || ""), kind === "projects" ? [id2] : [], [], { ...fields[kind], ...common, ...clone2(after) });
  if (kind === "projects" && !item.projectIds.length) item.projectIds = [id2];
  return item;
}
function operationShape(op, index) {
  const path = `operations.${index}`;
  if (!object7(op)) return [{ path, message: "\u64CD\u4F5C\u5FC5\u987B\u4E3A\u5BF9\u8C61" }];
  const errors = [];
  if (!idValid(op.id)) errors.push({ path: `${path}.id`, message: "\u64CD\u4F5C ID \u65E0\u6548" });
  if (!v2Kinds.includes(op.kind)) errors.push({ path: `${path}.kind`, message: "\u672A\u77E5\u5BF9\u8C61\u7C7B\u578B" });
  if (!idValid(op.targetId)) errors.push({ path: `${path}.targetId`, message: "\u76EE\u6807 ID \u65E0\u6548" });
  if (!["create", "update"].includes(op.action)) errors.push({ path: `${path}.action`, message: "\u4EC5\u652F\u6301\u65B0\u589E\u6216\u66F4\u65B0\uFF1B\u79FB\u9664\u8BF7\u4F7F\u7528 archived" });
  if (!object7(op.before) || !object7(op.after) || !Object.keys(op.after || {}).length) errors.push({ path, message: "before \u548C\u975E\u7A7A after \u5FC5\u987B\u4E3A\u5B57\u6BB5\u5BF9\u8C61" });
  if (!textValid(op.reason) || !op.reason.trim()) errors.push({ path: `${path}.reason`, message: "\u8BF7\u63D0\u4F9B\u4FEE\u6539\u7406\u7531" });
  if (!Array.isArray(op.sourceIds) || op.sourceIds.some((id2) => !idValid(id2))) errors.push({ path: `${path}.sourceIds`, message: "\u6765\u6E90\u5F15\u7528\u987B\u4E3A\u5BF9\u8C61 ID \u6570\u7EC4" });
  if (!["fact", "suggestion", "hypothesis"].includes(op.classification)) errors.push({ path: `${path}.classification`, message: "\u8BF7\u533A\u5206\u4E8B\u5B9E\u3001\u5EFA\u8BAE\u6216\u5047\u8BBE" });
  if (!Array.isArray(op.missingInfo) || op.missingInfo.some((text15) => !textValid(text15))) errors.push({ path: `${path}.missingInfo`, message: "\u7F3A\u5931\u4FE1\u606F\u987B\u4E3A\u6587\u5B57\u6570\u7EC4" });
  if (op.atomicGroup != null && !idValid(op.atomicGroup)) errors.push({ path: `${path}.atomicGroup`, message: "\u4E0D\u53EF\u62C6\u5206\u7EC4 ID \u65E0\u6548" });
  if (op.sourceVersions != null && (!Array.isArray(op.sourceVersions) || op.sourceVersions.some((basis) => !object7(basis) || !idValid(basis.objectId) || !Number.isSafeInteger(basis.version) || basis.version < 1))) errors.push({ path: `${path}.sourceVersions`, message: "\u6765\u6E90\u7248\u672C\u5FEB\u7167\u683C\u5F0F\u65E0\u6548" });
  if (object7(op.after)) {
    errors.push(...fieldsValid(op.after, `${path}.after`, true, {}, op.kind));
    if (op.action === "create" && (!textValid(op.after.title, 1e3) || !op.after.title.trim())) errors.push({ path: `${path}.after.title`, message: "\u65B0\u589E\u5BF9\u8C61\u987B\u63D0\u4F9B\u6807\u9898" });
    if (op.action === "update" && object7(op.before)) {
      for (const key2 of Object.keys(op.after)) if (!own3(op.before, key2)) errors.push({ path: `${path}.before.${key2}`, message: "\u987B\u63D0\u4F9B\u4FEE\u6539\u524D\u5B57\u6BB5\u503C\uFF1B\u672A\u8BBE\u7F6E\u5B57\u6BB5\u7528 null \u8868\u793A" });
    }
  }
  return errors;
}
function operationErrors(s, operations, checkBefore = true) {
  const errors = operations.flatMap(operationShape);
  const ids8 = /* @__PURE__ */ new Set();
  const fields = /* @__PURE__ */ new Set();
  operations.forEach((op, i) => {
    if (!object7(op)) return;
    if (ids8.has(op.id)) errors.push({ path: `operations.${i}.id`, message: "\u64CD\u4F5C ID \u91CD\u590D" });
    ids8.add(op.id);
    const target = lookupV2(s, op.targetId);
    if (op.kind === "cases" && object7(op.after) && caseProtectedFields.some((field) => own3(op.after, field))) errors.push({ path: `operations.${i}.after`, message: "\u4E13\u9879\u804C\u8D23\u3001\u5BA1\u6279\u3001\u9A8C\u8BC1\u548C\u5173\u95ED\u8BF7\u901A\u8FC7\u4E13\u9879\u5165\u53E3\u8BB0\u5F55" });
    if (object7(op.after) && own3(op.after, "followupHandling")) errors.push({ path: `operations.${i}.after`, message: "\u8DDF\u8FDB\u5904\u7406\u8BB0\u5F55\u53EA\u8BFB\uFF0C\u8BF7\u4F7F\u7528\u4E8B\u9879\u5185\u8DDF\u8FDB\u5165\u53E3" });
    if (op.kind === "deliverables" && object7(op.after) && ["meetingSourceId", "meetingDocument", "meetingRemoteId"].some((field) => own3(op.after, field))) errors.push({ path: `operations.${i}.after`, message: "\u5DF2\u5F52\u6863\u7EAA\u8981\u7684\u8EAB\u4EFD\u4E0E\u5FEB\u7167\u53EA\u8BFB\uFF0C\u8BF7\u4ECE\u4F1A\u8BAE\u5165\u53E3\u6838\u5BF9\u540E\u66F4\u65B0" });
    if (op.kind === "sources" && object7(op.after)) {
      const approvalOnly = target?.meetingWorkflow?.preview && op.action === "update" && Object.keys(op.after).every((field) => ["meetingApprovalHash", "confirmed"].includes(field)) && op.after.meetingApprovalHash === target.meetingWorkflow.preview.fingerprint && op.after.confirmed === true;
      if (own3(op.after, "meetingWorkflow") || own3(op.after, "followupNotification") || (own3(op.after, "meetingApprovalHash") || target?.meetingWorkflow && Object.keys(op.after).some((field) => field !== "archived")) && !approvalOnly || target?.followupNotification && Object.keys(op.after).some((field) => field !== "archived")) errors.push({ path: `operations.${i}.after`, message: "\u4F1A\u8BAE\u6267\u884C\u548C\u672C\u4EBA\u901A\u77E5\u56DE\u6267\u53EA\u8BFB\uFF0C\u8BF7\u4F7F\u7528\u4E13\u7528\u5BA1\u9605\u4E0E\u56DE\u8BFB\u5165\u53E3" });
      if (target?.commentDispatch && ["sending", "sent", "needs_reconcile"].includes(target.commentDispatch.status) && op.after.archived === true) errors.push({ path: `operations.${i}.after`, message: "\u8BC4\u8BBA\u4ECD\u6709\u6267\u884C\u6216\u672A\u77E5\u7ED3\u679C\uFF0C\u5148\u56DE\u8BFB\u6838\u5BF9\u518D\u5F52\u6863" });
      if (target?.meetingWorkflow && ["executing", "unknown"].includes(target.meetingWorkflow.status) && op.after.archived === true) errors.push({ path: `operations.${i}.after`, message: "\u4F1A\u8BAE\u4ECD\u6709\u6267\u884C\u6216\u672A\u77E5\u7ED3\u679C\uFF0C\u5148\u56DE\u8BFB\u6838\u5BF9\u518D\u5F52\u6863" });
    }
    if (op.kind === "sources" && object7(op.after) && (own3(op.after, "resultReview") || own3(op.after, "reminderRun") || own3(op.after, "inputEnvelope") || own3(op.after, "workCalendar") || own3(op.after, "followupNotification") || own3(op.after, "commentDispatch") || own3(op.after, "taskContext") || own3(op.after, "meetingContext") || own3(op.after, "caseChat") || own3(op.after, "caseFile") || own3(op.after, "approvalEvidence") || own3(op.after, "intakeBatch") || own3(op.after, "intakeDocument") || own3(op.after, "collectedIntake") || target && (target.workItem || target.subjectAssociation || target.chatScope || target.projectChat || target.managementSignal || target.resultReview || target.reminderRun || target.inputEnvelope || target.workCalendar || target.followupNotification || target.commentDispatch || target.taskContext || target.meetingContext || target.caseChat || target.caseFile || target.approvalEvidence || target.intakeBatch || target.intakeDocument) && Object.keys(op.after).some((field) => !["archived"].includes(field)))) errors.push({ path: `operations.${i}.after`, message: "\u6210\u679C\u7248\u672C\u3001\u4EFB\u52A1\u80CC\u666F\u3001\u7FA4\u6587\u4EF6\u3001\u5BA1\u6279\u4F9D\u636E\u53CA\u91C7\u96C6\u8BB0\u5F55\u53EA\u8BFB\uFF0C\u8BF7\u4F7F\u7528\u4E13\u7528\u5165\u53E3" });
    if (object7(op.after) && own3(op.after, "intakeFeedback")) errors.push({ path: `operations.${i}.after`, message: "\u81EA\u52A8\u6574\u7406\u7684\u6765\u6E90\u4E0E\u5386\u53F2\u53EA\u8BFB" });
    if (op.kind === "sources" && target?.dataPublication?.status === "publishing") errors.push({ path: `operations.${i}.after`, message: "\u8D44\u6599\u6B63\u5728\u6302\u8F7D\uFF0C\u8BF7\u5148\u7B49\u5F85\u6267\u884C\u7ED3\u679C" });
    if (op.kind === "sources" && target?.intakeBatch && ["queued", "reading", "analysing"].includes(target.intakeBatch.status) && op.after?.archived === true) errors.push({ path: `operations.${i}.after`, message: "\u8BF7\u5148\u53D6\u6D88\u6B63\u5728\u5904\u7406\u7684\u8D44\u6599\u6279\u6B21\uFF0C\u518D\u5F52\u6863" });
    if (op.kind === "sources" && object7(op.after) && (own3(op.after, "feedback") || target && isCommentFeedback(target) && Object.keys(op.after).some((field) => !["archived"].includes(field)))) errors.push({ path: `operations.${i}.after`, message: "\u98DE\u4E66\u53CD\u9988\u539F\u6587\u4E0E\u6765\u6E90\u53EA\u8BFB\uFF1B\u6838\u5BF9\u53CD\u9988\u8BF7\u4F7F\u7528\u53CD\u9988\u5165\u53E3\uFF0C\u8865\u5145\u4FE1\u606F\u53EF\u53E6\u8BB0\u8D44\u6599" });
    if (op.kind === "sources" && object7(op.after) && (own3(op.after, "riskEvidence") || own3(op.after, "riskEvent") || target && (target.riskEvidence || target.riskEvent) && Object.keys(op.after).some((field) => field !== "archived"))) errors.push({ path: `operations.${i}.after`, message: "\u98CE\u9669\u8865\u67E5\u539F\u6587\u4E0E\u4E8B\u4EF6\u8EAB\u4EFD\u53EA\u8BFB\uFF0C\u8BF7\u4F7F\u7528\u4E13\u7528\u5165\u53E3" });
    if (op.kind === "sources" && object7(op.after) && (own3(op.after, "ruleBundle") || own3(op.after, "ruleCheck") || target && (target.ruleBundle || target.ruleCheck) && Object.keys(op.after).length > 0 || own3(op.after, "personalMessage") || target?.personalMessage && Object.keys(op.after).some((field) => field !== "archived"))) errors.push({ path: `operations.${i}.after`, message: "\u4E2A\u4EBA\u6D88\u606F\u539F\u6587\u4E0E\u8EAB\u4EFD\u53EA\u8BFB\uFF1B\u8865\u5145\u4FE1\u606F\u8BF7\u53E6\u8BB0\u8D44\u6599" });
    if (op.action === "create" && target) errors.push({ path: `operations.${i}.targetId`, message: "\u65B0\u589E\u5BF9\u8C61 ID \u5DF2\u5B58\u5728", current: target });
    if (op.action === "update" && (!target || kindOf(s, op.targetId) !== op.kind)) errors.push({ path: `operations.${i}.targetId`, message: "\u76EE\u6807\u5BF9\u8C61\u4E0D\u5728\u672C\u5DE5\u4F5C\u533A\u6216\u7C7B\u578B\u4E0D\u7B26" });
    if (object7(op.after)) for (const field of Object.keys(op.after)) {
      const key2 = `${op.targetId}/${field}`;
      if (fields.has(key2)) errors.push({ path: `operations.${i}.after.${field}`, message: "\u540C\u4E00\u4FEE\u6539\u7EC4\u4E0D\u80FD\u91CD\u590D\u4FEE\u6539\u540C\u4E00\u5B57\u6BB5" });
      fields.add(key2);
      if (checkBefore && target && object7(op.before) && own3(op.before, field) && !same5(op.before[field], target[field])) errors.push({ path: `operations.${i}.before.${field}`, message: "\u539F\u503C\u5DF2\u53D8\u5316\uFF0C\u8BF7\u67E5\u770B\u4E09\u65B9\u5DEE\u5F02\u540E\u7F16\u8F91\u8349\u7A3F", before: present(op.before[field]), current: present(target[field]), proposed: present(op.after[field]) });
    }
    if (target && object7(op.after)) {
      const flag = op.kind === "people" ? "identityVerified" : op.kind === "externalLinks" ? "verified" : "";
      const identityFields = op.kind === "people" ? ["feishuUserId", "feishuIdType", "feishuAppId", "feishuTenantKey"] : ["localObjectId", "system", "host", "spaceKey", "remoteKind", "remoteId", "parentRemoteId", "url"];
      if (flag && target[flag] === true && !own3(op.after, flag) && identityFields.some((field) => own3(op.after, field) && !same5(target[field], op.after[field]))) errors.push({ path: `operations.${i}.after.${flag}`, message: "\u8EAB\u4EFD\u6216\u5173\u8054\u8303\u56F4\u53D1\u751F\u53D8\u5316\uFF0C\u987B\u660E\u786E\u6807\u4E3A\u672A\u6838\u5B9E\u6216\u91CD\u65B0\u6838\u5B9E\uFF0C\u4E0D\u80FD\u6CBF\u7528\u65E7\u6838\u5B9E\u72B6\u6001" });
    }
    if (target?.archived && !own3(op.after || {}, "archived")) errors.push({ path: `operations.${i}.targetId`, message: "\u76EE\u6807\u5DF2\u5F52\u6863\uFF0C\u8BF7\u5148\u660E\u786E\u6062\u590D\u6216\u5728\u540C\u4E00\u64CD\u4F5C\u4E2D\u6062\u590D" });
    if (checkBefore) for (const basis of Array.isArray(op.sourceVersions) ? op.sourceVersions : []) {
      if (!object7(basis)) continue;
      const source = lookupV2(s, basis.objectId);
      const creatingHere = !source && operations.some((other) => other?.kind === "sources" && other.action === "create" && other.targetId === basis.objectId);
      if (!creatingHere && (!source || source.archived || versionOf(source) !== basis.version)) errors.push({ path: `operations.${i}.sourceIds`, message: "\u8349\u7A3F\u5F15\u7528\u7684\u6765\u6E90\u7248\u672C\u5DF2\u53D8\u5316\uFF0C\u8BF7\u91CD\u65B0\u68C0\u67E5\u4F9D\u636E\u5E76\u7F16\u8F91\u8349\u7A3F", before: basis.version, current: source ? versionOf(source) : null, proposed: { sourceId: basis.objectId, operationId: op.id } });
    }
  });
  if (errors.length) return errors;
  const proposed = clone2(s);
  for (const op of operations) {
    if (op.action === "create") proposed[op.kind].push(defaults(proposed, op.kind, op.targetId, op.after));
    else Object.assign(lookupV2(proposed, op.targetId), clone2(op.after));
  }
  errors.push(...validateState(proposed));
  for (const [i, op] of operations.entries()) {
    if (op.kind === "projects" && own3(op.after, "nextGateId") && op.after.nextGateId) {
      const project = proposed.projects.find((row) => row.id === op.targetId);
      if (!project || !getProjectGates(proposed, project).gates.some((gate) => gate.id === op.after.nextGateId && !gate.accepted)) errors.push({ path: `operations.${i}.after.nextGateId`, message: "\u8BF7\u9009\u62E9\u672C\u9879\u76EE\u5C1A\u672A\u9A8C\u6536\u7684\u6709\u6548\u91CC\u7A0B\u7891\uFF1B\u4E0D\u80FD\u9009\u62E9\u666E\u901A\u8282\u70B9\u3001\u5176\u4ED6\u9879\u76EE\u6216\u5DF2\u5931\u6548\u7684\u5173\u53E3" });
    }
    for (const sourceId of op.sourceIds) if (!proposed.sources.some((source) => source.id === sourceId && !source.archived)) errors.push({ path: `operations.${i}.sourceIds`, message: `\u6765\u6E90 ${sourceId} \u4E0D\u5728\u672C\u5DE5\u4F5C\u533A\u6216\u5DF2\u5F52\u6863` });
    for (const ref of references(op.after)) {
      const target = lookupV2(proposed, ref.id);
      if (target?.archived) errors.push({ path: `operations.${i}.after.${ref.field}`, message: `\u4E0D\u80FD\u65B0\u589E\u6307\u5411\u5DF2\u5F52\u6863\u5BF9\u8C61 ${ref.id} \u7684\u5F15\u7528` });
    }
    if (op.after.mergedIntoId) for (const kind of v2Kinds) for (const row of proposed[kind]) {
      if (!row.archived && row.id !== op.targetId && references(row).some((ref) => ref.id === op.targetId && ref.field !== "basisRefs")) errors.push({ path: `operations.${i}.after.mergedIntoId`, message: `\u5408\u5E76\u987B\u540C\u65F6\u8FC1\u79FB ${row.title} [${row.id}] \u7684\u6709\u6548\u5F15\u7528\uFF1B\u5386\u53F2\u5BA1\u8BA1\u4F1A\u539F\u6837\u4FDD\u7559` });
    }
    if (op.kind === "deliverables") {
      const deliverable = lookupV2(proposed, op.targetId);
      if (deliverable) {
        const review = own3(op.after, "deliveryReview") ? op.after.deliveryReview : own3(op.after, "reviewStatus") ? op.after.reviewStatus : deliverable.deliveryReview ?? deliverable.reviewStatus ?? "\u672A\u5BA1\u6838";
        const status2 = deliverable.status ?? "\u672A\u5F00\u59CB";
        const statusChangedToEnd = op.action === "create" || own3(op.after, "status");
        if (statusChangedToEnd && status2 === "\u5DF2\u7ED3\u675F" && review !== "\u5DF2\u5BA1\u6838") {
          errors.push({ path: `operations.${i}.after.status`, message: "\u4EA4\u4ED8\u7269\u53EA\u6709\u5728\u4EA4\u4ED8\u7269\u5BA1\u6838\u4E3A\u5DF2\u5BA1\u6838\u540E\u624D\u80FD\u6539\u4E3A\u5DF2\u7ED3\u675F" });
        }
        if (op.action === "create" || own3(op.after, "deliveryReview") || own3(op.after, "reviewStatus")) {
          const reviewChangedToAccepted = (own3(op.after, "deliveryReview") ? op.after.deliveryReview : op.after.reviewStatus) === "\u5DF2\u5BA1\u6838";
          if (reviewChangedToAccepted && (!Array.isArray(deliverable.attachments) || deliverable.attachments.length === 0)) {
            errors.push({ path: `operations.${i}.after.deliveryReview`, message: "\u4EA4\u4ED8\u7269\u5BA1\u6838\u4E3A\u5DF2\u5BA1\u6838\u524D\u5FC5\u987B\u4E0A\u4F20\u81F3\u5C11\u4E00\u4E2A\u4EA4\u4ED8\u7269\u9644\u4EF6" });
          }
        }
        if (statusChangedToEnd && status2 === "\u5DF2\u7ED3\u675F") {
          const children = proposed.deliverables.filter((child) => !child.archived && Array.isArray(child.parentDeliverableIds) && child.parentDeliverableIds.includes(deliverable.id));
          if (children.some((child) => (child.status ?? "\u672A\u5F00\u59CB") !== "\u5DF2\u7ED3\u675F" || (child.deliveryReview ?? child.reviewStatus ?? "\u672A\u5BA1\u6838") !== "\u5DF2\u5BA1\u6838")) {
            errors.push({ path: `operations.${i}.after.status`, message: "\u7236\u4EA4\u4ED8\u7269\u9700\u7B49\u5F85\u5168\u90E8\u5B50\u4EA4\u4ED8\u7269\u5BA1\u6838\u901A\u8FC7\u5E76\u5DF2\u7ED3\u675F\u540E\u624D\u80FD\u5B8C\u6210" });
          }
        }
      }
    }
    if (op.kind === "decisions" && (op.after.conclusion?.trim() || lookupV2(proposed, op.targetId).status === "\u5DF2\u51B3\u7B56")) {
      const decision = lookupV2(proposed, op.targetId);
      if (!decision.conclusion?.trim()) errors.push({ path: `operations.${i}.after.conclusion`, message: "\u6807\u4E3A\u5DF2\u51B3\u7B56\u65F6\u987B\u586B\u5199\u7ED3\u8BBA" });
      if (!decision.basis?.trim() && !decision.sourceIds.length && !op.sourceIds.length) errors.push({ path: `operations.${i}.after.basis`, message: "\u786E\u8BA4\u51B3\u7B56\u987B\u63D0\u4F9B\u4F9D\u636E\u6216\u6765\u6E90" });
      if (!decision.owner?.trim() && !decision.deciderId && !decision.ownerId) errors.push({ path: `operations.${i}.after.owner`, message: "\u786E\u8BA4\u51B3\u7B56\u987B\u6307\u5B9A\u51B3\u7B56\u4EBA" });
    }
  }
  return errors;
}
function validateDraft(s, input) {
  s = hydrateStateCollections(s);
  if (!object7(input)) return [{ path: "draft", message: "\u8349\u7A3F\u5FC5\u987B\u4E3A JSON \u5BF9\u8C61" }];
  const errors = [];
  if (input.workspaceId !== s.workspaceId) errors.push({ path: "workspaceId", message: "\u8349\u7A3F\u5C5E\u4E8E\u5176\u4ED6\u5DE5\u4F5C\u533A" });
  for (const field of ["request", "purpose", "creator"]) if (!textValid(input[field]) || !input[field].trim()) errors.push({ path: field, message: "\u8BF7\u586B\u5199\u539F\u59CB\u8981\u6C42\u3001\u76EE\u7684\u53CA\u521B\u5EFA\u8005" });
  if (!idValid(input.idempotencyKey)) errors.push({ path: "idempotencyKey", message: "\u5E42\u7B49\u6807\u8BC6\u987B\u4E3A\u7A33\u5B9A\u7684\u975E\u7A7A ID" });
  if (!Number.isSafeInteger(input.baseRevision) || input.baseRevision < 0 || input.baseRevision > s.revision) errors.push({ path: "baseRevision", message: "\u8BFB\u53D6\u65F6\u7684\u6570\u636E\u7248\u672C\u65E0\u6548\uFF1B\u8BF7\u91CD\u65B0\u8BFB\u53D6\u672C\u5DE5\u4F5C\u533A\u5FEB\u7167" });
  const migrationBatch = typeof input.idempotencyKey === "string" && input.idempotencyKey.startsWith("feishu-th2-full-");
  const maxOperations = migrationBatch ? 1200 : 500;
  if (!Array.isArray(input.operations) || !input.operations.length || input.operations.length > maxOperations) errors.push({ path: "operations", message: `\u6BCF\u7EC4\u987B\u6709 1\u2013${maxOperations} \u9879\u64CD\u4F5C` });
  else errors.push(...operationErrors(s, input.operations));
  return errors;
}
function receipt(s, key2, fingerprint) {
  if (!idValid(key2)) fail7([{ path: "requestId", message: "\u8BF7\u63D0\u4F9B\u7A33\u5B9A\u7684\u8BF7\u6C42 ID" }]);
  const existing = own3(s.receipts, key2) ? s.receipts[key2] : void 0;
  if (existing && existing.fingerprint !== fingerprint) fail7([{ path: "requestId", message: "\u540C\u4E00\u5E42\u7B49\u6807\u8BC6\u4E0D\u80FD\u7528\u4E8E\u4E0D\u540C\u8BF7\u6C42\u5185\u5BB9" }], 409);
  return existing;
}
function finish(state, key2, fingerprint, result) {
  state.revision += 1;
  state.receipts[key2] = { fingerprint, result };
  return state;
}
function submitDraft(s, input) {
  s = hydrateStateCollections(s);
  if (own3(input, "aiTriageSourceIds")) fail7([{ path: "draft", message: "AI\u5206\u6D41\u6765\u6E90\u7531\u7CFB\u7EDF\u7EF4\u62A4" }]);
  const fingerprint = canonical4({ command: "submit", input });
  const prior = receipt(s, input?.idempotencyKey, fingerprint);
  if (prior) {
    const group2 = s.changeGroups.find((group3) => group3.id === prior.result.groupId);
    if (!group2) fail7([{ path: "receipt", message: "\u8349\u7A3F\u56DE\u6267\u635F\u574F" }]);
    return { state: s, group: group2 };
  }
  requireValid(validateDraft(s, input));
  const state = clone2(s);
  const group = { ...clone2(input), id: uid("group"), createdAt: now(), draftVersion: 1, fingerprint, status: "pending", auditIds: [], history: [], operations: input.operations.map((op) => ({ ...clone2(op), sourceVersions: sourceVersions(s, op, input.operations), status: "pending" })) };
  state.changeGroups.push(group);
  finish(state, input.idempotencyKey, fingerprint, { groupId: group.id });
  return { state, group };
}
function editDraft(s, id2, draftVersion, operations) {
  s = hydrateStateCollections(s);
  const group = s.changeGroups.find((group2) => group2.id === id2);
  if (!group) fail7([{ path: "groupId", message: "\u4FEE\u6539\u7EC4\u4E0D\u5728\u672C\u5DE5\u4F5C\u533A" }], 404);
  if (group.draftVersion !== draftVersion) fail7([{ path: "draftVersion", message: "\u8349\u7A3F\u7248\u672C\u5DF2\u53D8\u5316\uFF0C\u8BF7\u91CD\u65B0\u6253\u5F00\u5BA1\u6838" }], 409);
  if (!["pending", "partial", "conflict"].includes(group.status)) fail7([{ path: "status", message: "\u5DF2\u7ED3\u675F\u7684\u4FEE\u6539\u7EC4\u4E0D\u80FD\u518D\u7F16\u8F91" }], 409);
  if (!Array.isArray(operations) || !operations.length || operations.length > 500) fail7([{ path: "operations", message: "\u8349\u7A3F\u987B\u6709 1\u2013500 \u9879\u64CD\u4F5C" }]);
  const completed4 = group.operations.filter((op) => op.status && op.status !== "pending");
  const pending3 = operations.filter((op) => !completed4.some((done) => done.id === op?.id)).map((op) => object7(op) ? { ...op, sourceVersions: void 0 } : op);
  for (const done of completed4) {
    const submitted = operations.find((op) => op?.id === done.id);
    if (submitted && !same5(submitted, done)) fail7([{ path: "operations", message: "\u5DF2\u5BA1\u6838\u64CD\u4F5C\u4E0D\u80FD\u901A\u8FC7\u7F16\u8F91\u8349\u7A3F\u6539\u5199" }], 409);
  }
  requireValid(validateDraft(s, { ...group, baseRevision: s.revision, operations: pending3 }));
  const state = clone2(s), updated = state.changeGroups.find((group2) => group2.id === id2);
  updated.history.push({ time: now(), operation: "edit", draftVersion: updated.draftVersion, operations: clone2(updated.operations) });
  updated.operations = [...completed4, ...pending3.map((op) => ({ ...clone2(op), sourceVersions: sourceVersions(s, op, pending3), status: "pending" }))];
  updated.draftVersion += 1;
  updated.baseRevision = s.revision;
  updated.status = completed4.length ? "partial" : "pending";
  updated.conflicts = [];
  updated.fingerprint = canonical4({ ...updated, history: void 0, fingerprint: void 0 });
  state.revision += 1;
  return state;
}
function addAudit(state, operation, kind, id2, before, after, actor, groupId, sourceIds = [], compensates) {
  const audit = { id: uid("audit"), time: now(), operation, kind, objectId: id2, before: clone2(before), after: clone2(after), actor, revision: state.revision + 1, sourceIds: clone2(sourceIds), ...groupId ? { groupId } : {}, ...compensates ? { compensates } : {} };
  state.audit.push(audit);
  return audit;
}
function sourceVersions(s, op, operations) {
  return [.../* @__PURE__ */ new Set([...op.sourceIds, ...op.after.sourceIds || []])].flatMap((id2) => {
    const source = s.sources.find((source2) => source2.id === id2);
    return source ? [{ objectId: id2, version: versionOf(source) }] : operations.some((other) => other.kind === "sources" && other.targetId === id2 && other.action === "create") ? [{ objectId: id2, version: 1 }] : [];
  });
}
function snapshotRefs(s, judgment) {
  const refs = judgment.basisRefs?.length ? judgment.basisRefs : judgment.sourceIds.map((objectId) => ({ objectId }));
  return refs.map((ref) => {
    const target = lookupV2(s, ref.objectId);
    return { ...clone2(ref), version: versionOf(target), value: ref.field ? present(target?.[ref.field]) : target ? clone2(target) : null };
  });
}
function basisReasons(state, judgment) {
  const reasons = [];
  for (const ref of judgment.basisRefs || []) {
    const current = lookupV2(state, ref.objectId);
    const currentValue = ref.field ? present(current?.[ref.field]) : current ? clone2(current) : null;
    const source = state.sources.some((source2) => source2.id === ref.objectId);
    const superseded = source && state.sources.some((source2) => source2.supersedesId === ref.objectId && source2.confirmed && !source2.archived);
    const unconfirmed2 = source && current?.confirmed !== true;
    const changed = !current || current.archived || superseded || unconfirmed2 || (ref.field ? !same5(ref.value, currentValue) : versionOf(current) !== ref.version);
    if (changed) reasons.push({ objectId: ref.objectId, field: ref.field || "(\u5BF9\u8C61\u7248\u672C)", before: present(ref.value), current: currentValue, version: ref.version, currentVersion: versionOf(current), message: !current ? "\u4F9D\u636E\u5BF9\u8C61\u5DF2\u4E0D\u5B58\u5728" : current.archived ? "\u4F9D\u636E\u5BF9\u8C61\u5DF2\u5F52\u6863" : superseded ? "\u4F9D\u636E\u5DF2\u88AB\u65B0\u7248\u672C\u66FF\u4EE3" : unconfirmed2 ? "\u4F9D\u636E\u6765\u6E90\u5C1A\u672A\u786E\u8BA4" : "\u4F9D\u636E\u5185\u5BB9\u5DF2\u53D8\u5316" });
  }
  if (!judgment.basisRefs?.length) reasons.push({ message: "\u7F3A\u5C11\u53EF\u8FFD\u6EAF\u7684\u786E\u8BA4\u4F9D\u636E" });
  return reasons;
}
function refreshJudgments(before, state, explicit, actor, groupId) {
  for (const judgment of state.judgments) {
    if (!judgment.confirmed || judgment.archived || explicit.has(judgment.id)) continue;
    const previous = lookupV2(before, judgment.id);
    if (!previous) continue;
    const basis = judgment.basisRefs?.length ? judgment.basisRefs : snapshotRefs(before, previous);
    const candidate = { ...judgment, basisRefs: basis };
    const reasons = basisReasons(state, candidate);
    if (reasons.length && (!judgment.stale || !same5(judgment.staleReasons, reasons))) {
      const old = clone2(judgment);
      judgment.basisRefs = basis;
      judgment.stale = true;
      judgment.staleReasons = reasons;
      judgment.confirmedAt ||= judgment.createdAt || "\u5386\u53F2\u786E\u8BA4\u65F6\u95F4\u672A\u8BB0\u5F55";
      judgment.version = versionOf(judgment) + 1;
      judgment.updatedAt = now();
      addAudit(state, "basisChanged", "judgments", judgment.id, old, judgment, actor, groupId, judgment.sourceIds);
    }
  }
}
function applyOperations(before, state, operations, actor, groupId) {
  const explicitJudgments = /* @__PURE__ */ new Set();
  for (const op of operations) {
    let target = lookupV2(state, op.targetId);
    const old = target ? clone2(target) : null;
    if (op.action === "create") {
      target = defaults(state, op.kind, op.targetId, { sourceIds: clone2(op.sourceIds), ...op.after });
      state[op.kind].push(target);
    } else {
      Object.assign(target, clone2(op.after));
      target.version = versionOf(target) + 1;
      target.updatedAt = now();
    }
    if (op.kind === "deliverables") {
      if (own3(op.after, "deliveryReview") && !own3(op.after, "reviewStatus")) target.reviewStatus = target.deliveryReview;
      if (own3(op.after, "reviewStatus") && !own3(op.after, "deliveryReview")) target.deliveryReview = target.reviewStatus;
    }
    if (op.classification === "hypothesis") {
      target.classification = "hypothesis";
      target.confirmed = false;
    }
    if (op.kind === "decisions" && target.conclusion && ["conclusion", "basis", "decidedAt"].some((field) => own3(op.after, field))) {
      target.decidedAt = own3(op.after, "decidedAt") && op.after.decidedAt ? op.after.decidedAt : now();
      target.sourceIds = [.../* @__PURE__ */ new Set([...target.sourceIds, ...op.sourceIds])];
      target.history = [...old?.history || [], { time: now(), decidedAt: target.decidedAt, conclusion: target.conclusion, basis: target.basis || "", decider: target.deciderId || target.ownerId || target.owner, sourceIds: clone2(target.sourceIds) }];
      target.status = "\u5DF2\u51B3\u7B56";
    }
    if (op.kind === "judgments" && (own3(op.after, "confirmed") || own3(op.after, "basisRefs") || own3(op.after, "title") || own3(op.after, "health"))) explicitJudgments.add(target.id);
    addAudit(state, groupId ? "draft.accept" : `manual.${op.action}`, op.kind, op.targetId, old, target, actor, groupId, op.sourceIds);
  }
  for (const id2 of explicitJudgments) {
    const judgment = lookupV2(state, id2);
    const old = lookupV2(before, id2);
    if (judgment.confirmed) {
      judgment.confirmationHistory = [...old?.confirmationHistory || [], ...old?.confirmed ? [{ title: old.title, health: old.health, confirmedAt: old.confirmedAt || old.createdAt || "", basisRefs: clone2(old.basisRefs || snapshotRefs(before, old)), stale: !!old.stale, staleReasons: clone2(old.staleReasons || []) }] : []];
      judgment.basisRefs = snapshotRefs(state, judgment);
      judgment.confirmedAt = now();
      judgment.staleReasons = basisReasons(state, judgment);
      judgment.stale = !!judgment.staleReasons.length;
    }
    const audit = [...state.audit].reverse().find((audit2) => audit2.objectId === id2 && audit2.revision === state.revision + 1);
    if (audit) audit.after = clone2(judgment);
  }
  refreshJudgments(before, state, explicitJudgments, actor, groupId);
}
function reviewDraft(s, input) {
  s = hydrateStateCollections(s);
  if (!object7(input)) fail7([{ path: "review", message: "\u5BA1\u6838\u8BF7\u6C42\u5FC5\u987B\u4E3A\u5BF9\u8C61" }]);
  const fingerprint = canonical4({ command: "review", input });
  if (receipt(s, input.requestId, fingerprint)) return s;
  const group = s.changeGroups.find((group2) => group2.id === input.groupId);
  if (!group) fail7([{ path: "groupId", message: "\u4FEE\u6539\u7EC4\u4E0D\u5728\u672C\u5DE5\u4F5C\u533A" }], 404);
  if (group.draftVersion !== input.draftVersion) fail7([{ path: "draftVersion", message: "\u8349\u7A3F\u5DF2\u7F16\u8F91\uFF0C\u65E7\u7248\u672C\u5BA1\u6838\u4E0D\u80FD\u751F\u6548", before: input.draftVersion, current: group.draftVersion }], 409);
  if (!["accept", "reject"].includes(input.decision)) fail7([{ path: "decision", message: "\u5BA1\u6838\u51B3\u5B9A\u65E0\u6548" }]);
  if (group.status === "withdrawn") fail7([{ path: "status", message: "\u4FEE\u6539\u7EC4\u5DF2\u64A4\u56DE" }], 409);
  const chosenIds = input.operationIds || group.operations.filter((op) => !op.status || op.status === "pending").map((op) => op.id);
  if (!Array.isArray(chosenIds) || new Set(chosenIds).size !== chosenIds.length || chosenIds.some((id2) => !group.operations.some((op) => op.id === id2))) fail7([{ path: "operationIds", message: "\u9009\u62E9\u7684\u64CD\u4F5C\u4E0D\u5B58\u5728\u6216\u91CD\u590D" }]);
  const chosen = group.operations.filter((op) => chosenIds.includes(op.id));
  const desired = input.decision === "accept" ? "accepted" : "rejected";
  if (chosen.some((op) => op.status && op.status !== "pending" && op.status !== desired)) fail7([{ path: "operationIds", message: "\u5DF2\u5BA1\u6838\u7684\u64CD\u4F5C\u4E0D\u80FD\u6539\u53D8\u51B3\u5B9A" }], 409);
  const pending3 = chosen.filter((op) => !op.status || op.status === "pending");
  for (const op of pending3) if (op.atomicGroup && group.operations.some((other) => other.atomicGroup === op.atomicGroup && (!other.status || other.status === "pending") && !chosenIds.includes(other.id))) fail7([{ path: "operationIds", message: `\u5173\u8054\u64CD\u4F5C ${op.atomicGroup} \u5FC5\u987B\u4E00\u8D77\u5BA1\u6838` }], 409);
  if (input.decision === "accept" && pending3.length) {
    const errors = operationErrors(s, pending3);
    requireValid(errors, errors.some((error2) => own3(error2, "current")) ? 409 : 422);
  }
  const state = clone2(s), updated = state.changeGroups.find((group2) => group2.id === input.groupId);
  const auditStart = state.audit.length;
  if (input.decision === "accept") applyOperations(s, state, pending3, "\u9879\u76EE\u7ECF\u7406", updated.id);
  for (const op of updated.operations) if (chosenIds.includes(op.id)) op.status = desired;
  const statuses = updated.operations.map((op) => op.status || "pending");
  updated.status = statuses.every((status2) => status2 === "accepted") ? "accepted" : statuses.every((status2) => status2 === "rejected") ? "rejected" : statuses.includes("pending") || statuses.includes("accepted") ? "partial" : "rejected";
  updated.conflicts = [];
  updated.reviewComment = input.comment || "";
  if (pending3.length) updated.history.push({ time: now(), operation: input.decision, draftVersion: input.draftVersion, operationIds: pending3.map((op) => op.id), comment: input.comment || "", actor: "\u9879\u76EE\u7ECF\u7406" });
  if (input.decision === "accept" && pending3.length) {
    updated.acceptedBy = "\u9879\u76EE\u7ECF\u7406";
    updated.acceptedAt = now();
  }
  updated.auditIds.push(...state.audit.slice(auditStart).map((audit) => audit.id));
  for (const candidateId of updated.legacyCandidateIds || []) {
    const candidate = state.candidates.find((candidate2) => candidate2.id === candidateId);
    if (candidate && !statuses.includes("pending")) {
      candidate.status = statuses.includes("accepted") ? "accepted" : "ignored";
      if (candidate.status === "accepted") {
        candidate.acceptedAt = now();
        candidate.appliedValue = String(updated.operations[0]?.after[candidate.field] ?? candidate.value);
      }
    }
  }
  requireValid(validateState(state));
  return finish(state, input.requestId, fingerprint, { groupId: updated.id, status: updated.status });
}
function manualEdit(s, input) {
  s = hydrateStateCollections(s);
  if (!object7(input)) fail7([{ path: "manual", message: "\u5F55\u5165\u8BF7\u6C42\u5FC5\u987B\u4E3A\u5BF9\u8C61" }]);
  const fingerprint = canonical4({ command: "manual", input });
  if (receipt(s, input.requestId, fingerprint)) return s;
  const op = { id: input.requestId, kind: input.kind, targetId: input.targetId, action: input.action, before: input.before, after: input.after, reason: "\u7528\u6237\u76F4\u63A5\u5F55\u5165", sourceIds: input.after?.sourceIds || [], classification: "fact", missingInfo: [] };
  const errors = operationErrors(s, [op]);
  requireValid(errors, errors.some((error2) => own3(error2, "current")) ? 409 : 422);
  const state = clone2(s);
  applyOperations(s, state, [op], "\u9879\u76EE\u7ECF\u7406");
  requireValid(validateState(state));
  return finish(state, input.requestId, fingerprint, { objectId: input.targetId });
}
function changedKeys(a, b) {
  return [.../* @__PURE__ */ new Set([...Object.keys(a || {}), ...Object.keys(b || {})])].filter((key2) => !["version", "updatedAt"].includes(key2) && !same5(a?.[key2], b?.[key2]));
}
function undo(s, input) {
  s = hydrateStateCollections(s);
  if (!object7(input)) fail7([{ path: "undo", message: "\u64A4\u56DE\u8BF7\u6C42\u5FC5\u987B\u4E3A\u5BF9\u8C61" }]);
  const fingerprint = canonical4({ command: "undo", input });
  if (receipt(s, input.requestId, fingerprint)) return s;
  if (!!input.groupId === !!input.auditId) fail7([{ path: "undo", message: "\u8BF7\u6307\u5B9A\u4E00\u4E2A\u4FEE\u6539\u7EC4\u6216\u5355\u6761\u5BA1\u8BA1" }]);
  const group = input.groupId ? s.changeGroups.find((group2) => group2.id === input.groupId) : void 0;
  if (input.groupId && !group) fail7([{ path: "groupId", message: "\u4FEE\u6539\u7EC4\u4E0D\u5728\u672C\u5DE5\u4F5C\u533A" }], 404);
  if (group?.status === "withdrawn") fail7([{ path: "groupId", message: "\u4FEE\u6539\u7EC4\u5DF2\u64A4\u56DE" }], 409);
  const audits = s.audit.filter((audit) => input.groupId ? audit.groupId === input.groupId && audit.operation === "draft.accept" : audit.id === input.auditId && /^(manual\.|draft\.accept)/.test(audit.operation));
  if (!audits.length) fail7([{ path: "auditId", message: "\u6CA1\u6709\u53EF\u64A4\u9500\u7684\u5DF2\u5E94\u7528\u4FEE\u6539" }], 404);
  if (audits.some((audit) => audit.undoneBy)) fail7([{ path: "auditId", message: "\u8BE5\u4FEE\u6539\u5DF2\u7ECF\u64A4\u9500" }], 409);
  const state = clone2(s);
  const errors = [];
  const compensations = [];
  for (const audit of [...audits].reverse()) {
    const current = lookupV2(state, audit.objectId);
    const after = audit.after;
    const before = audit.before;
    if (!current || !audit.kind) {
      errors.push({ path: audit.id, message: "\u76EE\u6807\u5DF2\u4E0D\u5B58\u5728\u6216\u5386\u53F2\u5BA1\u8BA1\u7F3A\u5C11\u53EF\u64A4\u9500\u7684\u5B57\u6BB5\u5FEB\u7167" });
      continue;
    }
    const keys = before ? changedKeys(before, after) : changedKeys({}, after).filter((key2) => !["createdAt", "workspaceId"].includes(key2));
    for (const key2 of keys) if (!same5(current[key2], after?.[key2])) errors.push({ path: `${audit.id}.${key2}`, message: "\u6B64\u5B57\u6BB5\u5728\u751F\u6548\u540E\u53C8\u88AB\u4FEE\u6539\uFF0C\u4E0D\u80FD\u8986\u76D6\u540E\u7EED\u5DE5\u4F5C", before: present(after?.[key2]), current: present(current[key2]), proposed: present(before?.[key2]) });
    const old = clone2(current);
    if (!before) {
      current.archived = true;
    } else for (const key2 of keys) {
      if (own3(before, key2)) current[key2] = clone2(before[key2]);
      else delete current[key2];
    }
    current.version = versionOf(current) + 1;
    current.updatedAt = now();
    compensations.push({ audit, before: old, after: clone2(current) });
  }
  for (const audit of audits.filter((audit2) => !audit2.before)) {
    for (const kind of v2Kinds) for (const row of state[kind]) if (!row.archived && row.id !== audit.objectId && references(row).some((ref) => ref.id === audit.objectId)) errors.push({ path: `${audit.id}.references`, message: `\u65B0\u589E\u5BF9\u8C61\u5DF2\u6709 ${row.title} [${row.id}] \u5F15\u7528\uFF1B\u8BF7\u51C6\u5907\u65B0\u7684\u5173\u8054\u5904\u7406\u8349\u7A3F`, current: row.id });
  }
  requireValid(errors, 409);
  requireValid(validateState(state));
  for (const compensation of compensations) {
    const audit = addAudit(state, "compensate", compensation.audit.kind, compensation.audit.objectId, compensation.before, compensation.after, "\u9879\u76EE\u7ECF\u7406", input.groupId, compensation.audit.sourceIds || [], compensation.audit.id);
    state.audit.find((row) => row.id === compensation.audit.id).undoneBy = audit.id;
  }
  refreshJudgments(s, state, /* @__PURE__ */ new Set(), "\u9879\u76EE\u7ECF\u7406", input.groupId);
  if (group) {
    const updated = state.changeGroups.find((row) => row.id === group.id);
    updated.status = "withdrawn";
    updated.history.push({ time: now(), operation: "withdraw", auditIds: compensations.map((value) => value.audit.id), actor: "\u9879\u76EE\u7ECF\u7406" });
    updated.auditIds.push(...state.audit.slice(s.audit.length).map((row) => row.id));
  }
  return finish(state, input.requestId, fingerprint, { groupId: input.groupId, auditId: input.auditId });
}
function markViewed(s, requestId) {
  s = hydrateStateCollections(s);
  const fingerprint = canonical4({ command: "viewed" });
  if (receipt(s, requestId, fingerprint)) return s;
  const state = clone2(s);
  state.viewed = { at: now(), auditIds: state.audit.map((audit) => audit.id) };
  return finish(state, requestId, fingerprint, { viewed: clone2(state.viewed) });
}
function graphEdges(s) {
  s = hydrateStateCollections(s);
  const edges = [], seen = /* @__PURE__ */ new Set(), day = today();
  const add = (edge) => {
    const from = lookupV2(s, edge.fromId), to = lookupV2(s, edge.toId);
    if (!from || !to || from.archived || to.archived || edge.fromId === edge.toId) return;
    const key2 = relationTuple(edge);
    if (seen.has(key2)) return;
    seen.add(key2);
    edges.push({ ...edge, confirmed: edge.confirmed === true, expired: !!(edge.archived || edge.stale || edge.validFrom && edge.validFrom > day || edge.validTo && edge.validTo < day), sourceIds: edge.sourceIds || [] });
  };
  for (const relation of s.relations) if (!relation.archived) add({ ...relation, recordId: relation.id, derived: false });
  for (const kind of v2Kinds) for (const row of s[kind]) {
    if (row.archived || kind === "relations") continue;
    const base = { confirmed: (kind === "externalLinks" ? row.verified === true : row.confirmed !== false) && !row.stale, sourceIds: row.sourceIds, recordId: row.id, derived: true, creator: "\u53F0\u8D26\u5173\u8054", createdAt: row.createdAt || "" };
    const edge = (fromId, toId, type, suffix, extra = {}) => add({ ...base, id: `derived:${row.id}:${suffix}`, fromId, toId, type, ...extra });
    for (const projectId of row.projectIds) edge(row.id, projectId, "\u5C5E\u4E8E\u9879\u76EE", `project:${projectId}`);
    for (const sourceId of row.sourceIds) edge(sourceId, row.id, kind === "judgments" ? "\u652F\u6301\u5224\u65AD" : "\u6765\u6E90\u4F9D\u636E", `source:${sourceId}`, { confirmed: lookupV2(s, sourceId)?.confirmed === true && !row.stale });
    for (const milestoneId of row.milestoneIds || []) edge(row.id, milestoneId, ["risks", "decisions"].includes(kind) ? "\u5F71\u54CD" : "\u63A8\u8FDB", `milestone:${milestoneId}`);
    for (const sourceId of [...row.deliverableIds || [], ...row.acceptanceEvidenceIds || [], ...row.evidenceIds || []]) edge(sourceId, row.id, "\u9A8C\u6536\u8BC1\u636E", `deliverable:${sourceId}`, { confirmed: lookupV2(s, sourceId)?.confirmed === true });
    for (const nodeId of row.flowNodeIds || []) edge(row.id, nodeId, "\u5173\u8054\u6D41\u7A0B\u8282\u70B9", `node:${nodeId}`);
    for (const outputId of row.outputIds || []) edge(outputId, row.id, "\u4EA4\u4ED8\u7269", `output:${outputId}`);
    for (const actionId of row.actionIds || []) edge(actionId, row.id, "\u4EA7\u51FA", `action:${actionId}`);
    if (kind === "externalLinks" && row.localObjectId) edge(row.id, row.localObjectId, "\u5916\u90E8\u5BF9\u8C61\u5173\u8054", "external", { confirmed: row.verified === true });
    for (const resourceId of row.resourceIds || []) edge(row.id, resourceId, "\u4F7F\u7528\u8D44\u6E90", `resource:${resourceId}`, { validFrom: row.validFrom || "", validTo: row.validTo || "" });
    for (const field of ["ownerId", "executorId", "acceptorId", "followUpOwnerId", "deciderId", "authorId", "creatorId"]) if (row[field]) edge(row[field], row.id, "\u8D1F\u8D23\u6216\u8DDF\u8FDB", field, { role: { ownerId: kind === "decisions" ? "\u51B3\u7B56" : "\u8D1F\u8D23", executorId: "\u6267\u884C", acceptorId: "\u9A8C\u6536", followUpOwnerId: "\u8DDF\u8FDB", deciderId: "\u51B3\u7B56", authorId: "\u786E\u8BA4", creatorId: "\u521B\u5EFA" }[field] });
    if (kind === "dependencies") {
      for (const predecessorId of row.predecessorIds || []) {
        edge(row.id, predecessorId, "\u4F9D\u8D56\u4E8E", `predecessor:${predecessorId}`);
        for (const affectedId of row.affectedIds || []) edge(affectedId, predecessorId, "\u4F9D\u8D56\u4E8E", `path:${affectedId}:${predecessorId}`);
      }
      for (const affectedId of row.affectedIds || []) edge(row.id, affectedId, "\u5F71\u54CD", `affected:${affectedId}`);
    }
    if (kind === "judgments") for (const ref of row.basisRefs || []) edge(ref.objectId, row.id, "\u652F\u6301\u5224\u65AD", `basis:${ref.objectId}:${ref.field || ""}`, { confirmed: row.confirmed === true, stale: row.stale, field: ref.field, version: ref.version });
    if (kind === "sources") {
      for (const objectId of row.objectIds || []) edge(row.id, objectId, "\u6765\u6E90\u4F9D\u636E", `object:${objectId}`, { confirmed: row.confirmed === true });
      if (row.supersedesId) edge(row.id, row.supersedesId, "\u66FF\u4EE3\u65E7\u7248\u672C", "supersedes", { confirmed: row.confirmed === true });
    }
  }
  return edges;
}
function report(s, projectId) {
  s = hydrateStateCollections(s);
  const project = s.projects.find((row) => row.id === projectId && !row.archived);
  if (!project) fail7([{ path: "projectId", message: "\u9879\u76EE\u4E0D\u5728\u5F53\u524D\u5DE5\u4F5C\u533A\u6216\u5DF2\u5F52\u6863" }], 404);
  const publicRow = (row) => !row.archived && !row.private && row.visibility !== "private" && !row.stale && row.classification !== "hypothesis";
  const related2 = (kind) => s[kind].filter((row) => row.projectIds.includes(projectId) && publicRow(row));
  const evidence = (row) => row.sourceIds.filter((id2) => s.sources.some((source) => source.id === id2 && publicRow(source) && source.confirmed));
  const cite = (row) => `[${row.id}] ${evidence(row).map((id2) => `[${id2}]`).join(" ")}`;
  const sources = related2("sources").filter((row) => row.confirmed === true);
  const judgments = related2("judgments").filter((row) => row.confirmed === true && (row.basisRefs?.length && !basisReasons(s, row).length || !row.basisRefs && evidence(row).length));
  const risks = related2("risks").filter((row) => row.confirmed === true && row.status !== "\u5DF2\u5173\u95ED" && evidence(row).length);
  const milestones = related2("milestones").filter((row) => row.confirmed !== false && row.classification !== "suggestion").sort((a, b) => (a.forecast || a.committed || "9999").localeCompare(b.forecast || b.committed || "9999"));
  const decisions = related2("decisions").filter((row) => row.status === "\u5F85\u51B3\u7B56" && row.confirmed !== false && evidence(row).length);
  const plans = related2("actions").filter((row) => row.status !== "\u5DF2\u5B8C\u6210" && row.confirmed !== false && evidence(row).length);
  const lines = (rows2) => rows2.length ? rows2.map((row) => `- ${row}`).join("\n") : "- \u6682\u65E0\u6EE1\u8DB3\u5F53\u524D\u786E\u8BA4\u4E0E\u4F9D\u636E\u6761\u4EF6\u7684\u5185\u5BB9";
  return `\u3010\u672C\u5730\u9879\u76EE\u6C47\u62A5${s.workspaceType === "demo" ? " \xB7 \u865A\u6784\u6F14\u793A" : ""}\u3011${project.title}
\u5DE5\u4F5C\u533A\uFF1A${s.workspaceName} [${s.workspaceId}]
\u751F\u6210\u65F6\u95F4\uFF1A${now()}
\u6570\u636E\u7248\u672C\uFF1A${s.revision}

\u5DF2\u786E\u8BA4\u6765\u6E90
${lines(sources.map((row) => `${row.excerpt || row.title} ${cite(row)}`))}

\u91CC\u7A0B\u7891\u53F0\u8D26
${lines(milestones.map((row) => `${row.title}\uFF1A\u627F\u8BFA ${row.committed || "\u5F85\u786E\u8BA4"}\uFF1B\u9884\u6D4B ${row.forecast || "\u5F85\u786E\u8BA4"}\uFF1B\u5B9E\u9645 ${row.actual || "\u672A\u8BB0\u5F55"} ${cite(row)}${evidence(row).length ? "" : "\uFF08\u7F3A\u5C11\u5DF2\u786E\u8BA4\u6765\u6E90\uFF0C\u65E5\u671F\u4E3A\u7528\u6237\u4FDD\u5B58\u7684\u53F0\u8D26\u503C\uFF09"}`))}

\u5F53\u524D\u6709\u6548\u5224\u65AD
${lines(judgments.map((row) => `${row.title}\uFF08\u786E\u8BA4 ${row.confirmedAt || row.createdAt || "\u5386\u53F2\u65F6\u95F4\u672A\u8BB0\u5F55"}\uFF09${cite(row)}`))}

\u5DF2\u786E\u8BA4\u98CE\u9669\u4E0E\u95EE\u9898
${lines(risks.map((row) => `${row.type}\uFF1A${row.title}\uFF1B\u5E94\u5BF9\uFF1A${row.response || "\u5F85\u8865\u5145"} ${cite(row)}`))}

\u5F85\u51B3\u7B56\u4E8B\u9879
${lines(decisions.map((row) => `${row.title}\uFF1B\u51B3\u7B56\u4EBA ${row.owner || "\u5F85\u6307\u5B9A"}\uFF1B\u671F\u9650 ${row.deadline || "\u5F85\u786E\u8BA4"} ${cite(row)}`))}

\u4E0B\u4E00\u6B65\u8DDF\u8FDB
${lines(plans.slice(0, 8).map((row) => `${row.followUp || row.title}\uFF1B\u6267\u884C ${row.executor || "\u5F85\u6307\u5B9A"}\uFF1B\u68C0\u67E5 ${row.checkAt || "\u5F85\u786E\u8BA4"}\uFF1B\u6267\u884C\u53CD\u9988 ${row.executionStatus || "\u5F85\u786E\u8BA4"}\uFF1B\u9A8C\u6536 ${row.acceptanceStatus || "\u5F85\u9A8C\u6536"} ${cite(row)}`))}

\u8303\u56F4\u8BF4\u660E\uFF1A\u4EC5\u4F7F\u7528\u672C\u5DE5\u4F5C\u533A\u6B63\u5F0F\u53F0\u8D26\u3002\u5F85\u5BA1\u6838\u4FEE\u6539\u3001\u5047\u8BBE\u3001\u4E2A\u4EBA\u5907\u6CE8\u53CA\u9700\u590D\u6838\u5224\u65AD\u672A\u7EB3\u5165\uFF1B\u672C\u8F93\u51FA\u4EC5\u4FDD\u5B58\u5728\u672C\u5730\u3002`;
}
function demoState(id2 = "demo") {
  const state = normalizeState(makeSeed(), id2, "\u6F14\u793A\u533A \xB7 \u865A\u6784\u9879\u76EE", "demo");
  state.people = [rec("person-zhou", "\u5468\u8861", ["p1", "p2"], ["s7"], { role: "\u6D4B\u8BD5\u6267\u884C", aliases: [] }), rec("person-zhao", "\u8D75\u603B", ["p1", "p2"], ["s8"], { role: "\u8D44\u6E90\u51B3\u7B56", aliases: [] }), rec("person-lin", "\u6797\u6668", ["p1", "p3"], ["s1"], { role: "\u9879\u76EE\u8DDF\u8FDB", aliases: [] })];
  state.resources = [rec("resource-rf", "\u5171\u4EAB\u5C04\u9891\u53F0\u67B6", ["p1", "p2"], ["s7"], { type: "\u6D4B\u8BD5\u8BBE\u5907", aliases: ["\u5C04\u9891\u53F0\u67B6 A"], description: "\u865A\u6784\u8BBE\u5907\uFF1B\u5177\u4F53\u5360\u7528\u987B\u6838\u5BF9\u65F6\u95F4\u548C\u6765\u6E90\u3002" })];
  lookupV2(state, "m2").resourceIds = ["resource-rf"];
  lookupV2(state, "m5").resourceIds = ["resource-rf"];
  lookupV2(state, "a1").executorId = "person-zhou";
  lookupV2(state, "a2").executorId = "person-zhou";
  lookupV2(state, "d1").deciderId = "person-zhao";
  lookupV2(state, "m2").followUpOwnerId = "person-lin";
  state.relations = [rec("relation-resource-decision", "\u53F0\u67B6\u501F\u7528\u9700\u8981\u8D44\u6E90\u51B3\u7B56", ["p1", "p2"], ["s8"], { fromId: "resource-rf", toId: "d1", type: "\u5F71\u54CD", confirmed: true, creator: "\u865A\u6784\u6F14\u793A", validFrom: "", validTo: "" }), rec("relation-unblocks", "\u501F\u7528\u5907\u7528\u53F0\u67B6\u53EF\u80FD\u89E3\u9664\u963B\u585E", ["p1", "p2"], ["s8"], { fromId: "d1", toId: "dep1", type: "\u89E3\u9664\u963B\u585E", confirmed: false, creator: "\u865A\u6784\u6F14\u793A", validFrom: "", validTo: "" })];
  const judgment = lookupV2(state, "j-p1");
  judgment.basisRefs = snapshotRefs(state, { ...judgment, basisRefs: [{ objectId: "m2", field: "forecast" }, { objectId: "m2", field: "committed" }, { objectId: "s2", field: "excerpt" }] });
  judgment.confirmedAt = judgment.createdAt;
  judgment.stale = false;
  judgment.confirmationHistory = [];
  requireValid(validateState(state));
  return state;
}

// lib/feishu-sync.ts
var own4 = (value, key2) => !!value && Object.prototype.hasOwnProperty.call(value, key2);
var object8 = (value) => !!value && typeof value === "object" && !Array.isArray(value);
var clone3 = (value) => structuredClone(value);
var canonical5 = (value) => value === void 0 ? "undefined" : JSON.stringify(value, (_key, item) => object8(item) ? Object.fromEntries(Object.keys(item).sort().map((key2) => [key2, item[key2]])) : item);
var same6 = (a, b) => canonical5(a) === canonical5(b);
var set = (target, key2, value) => Object.defineProperty(target, key2, { value: clone3(value), enumerable: true, configurable: true, writable: true });
var hash2 = (value) => {
  let result = 2166136261;
  for (const char of canonical5(value)) {
    result ^= char.charCodeAt(0);
    result = Math.imul(result, 16777619);
  }
  return (result >>> 0).toString(16).padStart(8, "0");
};
var kindFor = (kind) => ({ project: "projects", node: "flowNodes", deliverable: "deliverables" })[kind];
var inboundFields = /* @__PURE__ */ new Set(["title", "description", "projectProgress", "deliverableProgress", "code", "projectCategory", "sourceStage", "sourceStatus", "resultLink", "owner", "plannedStart", "plannedEnd"]);
var textConversions = /* @__PURE__ */ new Set(["identity", "text", "display_name", "option_label", "person_names", "date", "date_yyyy_mm_dd"]);
var types = /* @__PURE__ */ new Set(["text", "number", "boolean", "date", "datetime", "option", "multi_option", "person", "json", "unknown"]);
var guessedType = (value) => value == null ? "unknown" : typeof value === "string" ? "text" : typeof value === "number" ? "number" : typeof value === "boolean" ? "boolean" : "json";
var display2 = (value) => {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (object8(value)) {
    for (const key2 of ["label", "name", "display_name", "displayName", "text"]) if (typeof value[key2] === "string") return value[key2];
  }
  return JSON.stringify(value);
};
var asText = (value) => {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (object8(value)) {
    for (const key2 of ["text", "label", "name", "display_name", "displayName"]) if (typeof value[key2] === "string") return value[key2];
  }
  return void 0;
};
function converted(value, rule) {
  if (!textConversions.has(rule.conversionRule)) return void 0;
  if (["plannedStart", "plannedEnd"].includes(rule.localField)) {
    if (value == null || value === "") return "";
    const declared = object8(value) ? value.iso_time : value;
    if (typeof declared !== "string") return void 0;
    const calendarOnly = /^\d{4}-\d{2}-\d{2}$/.test(declared);
    const zonedISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})$/.test(declared);
    if (!calendarOnly && !zonedISO || object8(value) && !zonedISO) return void 0;
    const calendar = declared.slice(0, 10), day = /* @__PURE__ */ new Date(`${calendar}T00:00:00Z`);
    if (!Number.isFinite(day.getTime()) || Number(calendar.slice(0, 4)) < 1 || day.toISOString().slice(0, 10) !== calendar) return void 0;
    if (zonedISO) {
      const instant = Date.parse(declared);
      if (!Number.isFinite(instant)) return void 0;
      if (object8(value) && own4(value, "timestamp")) {
        if (typeof value.timestamp !== "number" || !Number.isFinite(value.timestamp)) return void 0;
        const samePrecision = declared.includes(".") ? value.timestamp === instant : Math.floor(value.timestamp / 1e3) === Math.floor(instant / 1e3);
        if (!samePrecision) return void 0;
      }
    }
    return calendar;
  }
  if (rule.localField === "owner" && Array.isArray(value)) {
    const names = value.map(asText);
    return names.every((name) => name !== void 0) ? names.join("\u3001") : void 0;
  }
  const result = asText(value);
  if (result === void 0 || result.length > 2e5) return void 0;
  if (rule.localField === "title" && (!result.trim() || result.length > 1e3)) return void 0;
  return result;
}
function metadataFor(read, key2) {
  const metadata = read.fieldMetadata;
  if (Array.isArray(metadata)) {
    const entry = metadata.find((row) => object8(row) && String(row.field_key ?? row.fieldKey ?? row.key ?? "") === key2);
    return object8(entry) ? entry : {};
  }
  return object8(metadata) && object8(metadata[key2]) ? metadata[key2] : {};
}
function pendingField(state, localObjectId, field) {
  return state.changeGroups.some((group) => ["pending", "partial", "conflict"].includes(group.status) && group.operations.some((operation) => operation.targetId === localObjectId && operation.action === "update" && operation.status !== "accepted" && operation.status !== "rejected" && own4(operation.after, field)));
}
function identityIssue(remote, read, workspaceId) {
  if (remote.workspaceId !== workspaceId || remote.system !== "meegle") return "\u5916\u90E8\u5BF9\u8C61\u4E0D\u5C5E\u4E8E\u5F53\u524D\u98DE\u4E66\u5DE5\u4F5C\u533A";
  for (const key2 of ["remoteId", "remoteKind", "parentRemoteId"]) if (typeof read[key2] !== "string" || read[key2] !== remote[key2]) return `\u8FDC\u7AEF\u8EAB\u4EFD\u4E0D\u5339\u914D\uFF1A${key2}`;
  for (const key2 of ["system", "host", "tenantKey", "spaceKey", "parentNodeRemoteId", "parentDeliverableRemoteId"]) {
    if (read[key2] !== void 0 && (key2 === "host" ? read[key2]?.toLowerCase() !== remote[key2].toLowerCase() : read[key2] !== remote[key2])) return `\u8FDC\u7AEF\u8EAB\u4EFD\u4E0D\u5339\u914D\uFF1A${key2}`;
  }
  return "";
}
function errorText(error2) {
  if (typeof error2 === "string") return error2.slice(0, 2e3);
  if (object8(error2) && typeof error2.message === "string") return error2.message.slice(0, 2e3);
  return error2 ? display2(error2).slice(0, 2e3) : "\u8FDC\u7AEF\u8BFB\u53D6\u4E0D\u5B8C\u6574\uFF0C\u4FDD\u7559\u5DF2\u6709\u6570\u636E";
}
function rawSemantic(raw) {
  return Object.fromEntries(Object.entries(raw).filter(([key2]) => !["collectedAt", "fetchedAt", "readAt", "textProof"].includes(key2)));
}
function mergeFeishuRead(input, reads, options = {}) {
  const state = clone3(input), timestamp = options.now || (/* @__PURE__ */ new Date()).toISOString();
  const conflicts = [], inaccessible = [];
  const changedObjects = /* @__PURE__ */ new Set(), unchangedObjects = /* @__PURE__ */ new Set();
  const externalById = new Map(state.externalObjects.map((row) => [row.id, row]));
  const fieldByKey = new Map(state.remoteFieldValues.map((row) => [`${row.externalObjectId}/${row.remoteFieldKey}`, row]));
  const ruleByKey = new Map(state.mappingRules.filter((row) => row.workspaceId === state.workspaceId && row.status === "active").map((row) => [`${row.system}/${row.remoteKind}/${row.remoteFieldKey}`, row]));
  const baselineById = new Map(state.syncBaselines.map((row) => [row.externalObjectId, row]));
  for (const read of reads) {
    const remote = externalById.get(read.externalObjectId);
    const reject2 = (reason, markInaccessible = true) => {
      inaccessible.push({ externalObjectId: read.externalObjectId, remoteId: read.remoteId, reason });
      if (remote && markInaccessible && remote.verificationStatus !== "inaccessible") {
        remote.verificationStatus = "inaccessible";
        changedObjects.add(remote.id);
      }
    };
    if (!remote) {
      reject2("\u5C1A\u672A\u7ED1\u5B9A\u7684\u8FDC\u7AEF\u5BF9\u8C61\uFF0C\u987B\u5148\u5BA1\u6838\u8EAB\u4EFD\u6620\u5C04");
      continue;
    }
    const mismatch = identityIssue(remote, read, state.workspaceId);
    if (mismatch) {
      reject2(mismatch);
      continue;
    }
    if (read.complete !== true || read.error || !object8(read.fields) || !object8(read.raw)) {
      reject2(errorText(read.error));
      continue;
    }
    if (!Number.isFinite(Date.parse(read.collectedAt))) {
      reject2("\u8FDC\u7AEF\u91C7\u96C6\u65F6\u95F4\u65E0\u6548");
      continue;
    }
    if (Number.isFinite(Date.parse(remote.collectedAt)) && Date.parse(read.collectedAt) < Date.parse(remote.collectedAt)) {
      reject2("\u65E7\u8BFB\u53D6\u665A\u5230\uFF0C\u4FDD\u7559\u8F83\u65B0\u7684\u8FDC\u7AEF\u955C\u50CF", false);
      continue;
    }
    const previousObject = clone3(remote), localKind = kindFor(remote.remoteKind);
    const local = localKind ? state[localKind].find((row) => row.id === remote.localObjectId) : void 0;
    const previousLocal = local ? clone3(local) : void 0;
    let baseline = baselineById.get(remote.id);
    const previousBaseline = baseline ? clone3(baseline) : void 0;
    if (!baseline) {
      baseline = { id: `baseline-sync-${hash2(remote.id)}`, workspaceId: state.workspaceId, externalObjectId: remote.id, capturedAt: read.collectedAt, sourceHash: "", remoteValues: {}, localValues: {}, localRevision: state.revision, sourceId: remote.sourceId };
      state.syncBaselines.push(baseline);
      baselineById.set(remote.id, baseline);
    }
    const fields = Object.fromEntries(Object.entries(read.fields).filter(([, value]) => value !== void 0));
    let mappingChanged = false;
    const nameMetadata = metadataFor(read, "name"), nameType = nameMetadata.valueType ?? nameMetadata.field_type ?? nameMetadata.type;
    const nameRuleKey = `${remote.system}/${remote.remoteKind}/name`, existingNameRule = ruleByKey.get(nameRuleKey);
    const historicalTitle = previousObject.raw?.title;
    const legacyNameProof = local && remote.remoteKind !== "node" && own4(fields, "name") && typeof nameType === "string" && ["_name", "text"].includes(nameType) && typeof historicalTitle === "string" && !!historicalTitle.trim() && historicalTitle.length <= 1e3 && historicalTitle === local.title && !own4(baseline.localValues, "title") && !["quarantined", "unmapped"].includes(remote.mappingStatus);
    if (legacyNameProof && (!existingNameRule || !existingNameRule.localField || existingNameRule.localField === "title")) {
      const inactiveNameRule = state.mappingRules.some((row) => row.system === remote.system && row.remoteKind === remote.remoteKind && row.remoteFieldKey === "name" && row.status !== "active");
      if (!inactiveNameRule) {
        if (!existingNameRule || !existingNameRule.localField) {
          const rule = {
            id: existingNameRule?.id || `mapping-sync-name-${hash2([state.workspaceId, remote.system, remote.remoteKind])}`,
            workspaceId: state.workspaceId,
            system: remote.system,
            remoteKind: remote.remoteKind,
            remoteFieldKey: "name",
            remoteFieldName: String(nameMetadata.name ?? nameMetadata.field_name ?? "\u540D\u79F0"),
            remoteValueType: "text",
            localKind,
            localField: "title",
            conversionRule: "identity",
            writable: nameMetadata.read_only !== true && nameMetadata.is_read_only !== true && nameMetadata.disabled !== true,
            requiresReview: true,
            bidirectional: false,
            status: "active"
          };
          if (existingNameRule) Object.assign(existingNameRule, rule);
          else state.mappingRules.push(rule);
          ruleByKey.set(nameRuleKey, existingNameRule || rule);
          mappingChanged = true;
        }
        set(baseline.remoteValues, "name", historicalTitle);
        set(baseline.localValues, "title", local.title);
      }
    }
    const allRawFields = Object.fromEntries(state.remoteFieldValues.filter((row) => row.externalObjectId === remote.id).map((row) => [row.remoteFieldKey, row.rawValue]));
    for (const [key2, value] of Object.entries(fields)) set(allRawFields, key2, value);
    const raw = { ...remote.raw || {}, ...clone3(read.raw), fields: clone3(allRawFields) };
    if (read.comments !== void 0) raw.comments = clone3(read.comments);
    const sourceHash2 = `fnv1a-${hash2(rawSemantic(raw))}`;
    let fieldsChanged = false, hasConflict = false;
    for (const [key2, value] of Object.entries(fields)) {
      const rule = ruleByKey.get(`${remote.system}/${remote.remoteKind}/${key2}`), metadata = metadataFor(read, key2);
      const fieldKey = `${remote.id}/${key2}`, previousField = fieldByKey.get(fieldKey);
      const metadataType = metadata.valueType ?? metadata.remoteValueType;
      const valueType = typeof metadataType === "string" && types.has(metadataType) ? metadataType : rule?.remoteValueType || previousField?.valueType || guessedType(value);
      const field = {
        id: previousField?.id || `remote-field-sync-${hash2([remote.id, key2])}`,
        workspaceId: state.workspaceId,
        externalObjectId: remote.id,
        remoteFieldKey: key2,
        remoteFieldName: String(metadata.name ?? metadata.field_name ?? metadata.fieldName ?? rule?.remoteFieldName ?? previousField?.remoteFieldName ?? key2),
        valueType,
        rawValue: clone3(value),
        optionId: object8(value) ? String(value.value ?? value.key ?? value.id ?? "").slice(0, 2e4) : "",
        displayName: display2(value).slice(0, 2e4),
        localField: rule?.localField || "",
        mappingRuleId: rule?.id || "",
        collectedAt: read.collectedAt,
        sourceHash: sourceHash2
      };
      const fieldSemantic = (row) => Object.fromEntries(Object.entries(row).filter(([name]) => name !== "collectedAt" && name !== "sourceHash"));
      if (!previousField || !same6(fieldSemantic(previousField), fieldSemantic(field))) {
        if (previousField) Object.assign(previousField, field);
        else {
          state.remoteFieldValues.push(field);
          fieldByKey.set(fieldKey, field);
        }
        fieldsChanged = true;
      }
      const canProject = local && rule && rule.localKind === localKind && inboundFields.has(rule.localField) && !["quarantined", "unmapped"].includes(remote.mappingStatus);
      if (!canProject) {
        const observedFact = remote.remoteKind === "deliverable" && ["field_b462b3", "work_item_status"].includes(key2) || remote.remoteKind === "node" && key2 === "status";
        if (!observedFact) set(baseline.remoteValues, key2, value);
        continue;
      }
      const localField = rule.localField, proposed = converted(value, rule);
      const currentLocal = converted(local[localField], rule), oldRemote = converted(baseline.remoteValues[key2], rule);
      const oldLocal = converted(baseline.localValues[localField], rule);
      const hasBaseline = own4(baseline.remoteValues, key2) && own4(baseline.localValues, localField);
      const remoteChanged = !own4(baseline.remoteValues, key2) || (proposed === void 0 || oldRemote === void 0 ? !same6(value, baseline.remoteValues[key2]) : proposed !== oldRemote);
      const localChanged = !own4(baseline.localValues, localField) || (currentLocal === void 0 || oldLocal === void 0 ? !same6(local[localField], baseline.localValues[localField]) : currentLocal !== oldLocal);
      const pending3 = pendingField(state, local.id, localField);
      const conflict = (reason) => {
        hasConflict = true;
        conflicts.push({
          id: `feishu-conflict-${hash2([remote.id, key2])}`,
          externalObjectId: remote.id,
          localObjectId: local.id,
          remoteFieldKey: key2,
          localField,
          reason,
          baselineLocal: clone3(baseline.localValues[localField] ?? null),
          baselineRemote: clone3(baseline.remoteValues[key2] ?? null),
          localValue: clone3(local[localField] ?? null),
          remoteValue: clone3(value)
        });
      };
      if (proposed === void 0) {
        if (remoteChanged) conflict("\u8FDC\u7AEF\u503C\u65E0\u6CD5\u5B89\u5168\u8F6C\u6362\uFF1B\u4FDD\u7559\u672C\u5730\u503C\u548C\u8FDC\u7AEF\u539F\u6587");
        continue;
      }
      if (pending3 && remoteChanged) {
        conflict("\u6B64\u5B57\u6BB5\u6709\u672A\u5BA1\u6838\u7684\u672C\u5730\u4FEE\u6539\uFF1B\u987B\u5148\u5904\u7406\u8349\u7A3F\u4E0E\u98DE\u4E66\u53D8\u5316");
        continue;
      }
      if (currentLocal === proposed && !pending3) {
        set(baseline.remoteValues, key2, value);
        set(baseline.localValues, localField, currentLocal);
        continue;
      }
      if (!remoteChanged) continue;
      if (!hasBaseline && currentLocal !== "") {
        conflict("\u7F3A\u5C11\u53EF\u6BD4\u8F83\u7684\u5B57\u6BB5\u57FA\u7EBF\uFF1B\u987B\u4EBA\u5DE5\u786E\u8BA4\u672C\u5730\u503C\u4E0E\u98DE\u4E66\u503C");
        continue;
      }
      if (hasBaseline && localChanged) {
        conflict("\u672C\u5730\u548C\u98DE\u4E66\u5747\u5DF2\u4FEE\u6539\u6B64\u5B57\u6BB5\uFF1B\u4FDD\u7559\u672C\u5730\u4FEE\u6539");
        continue;
      }
      const start = localField === "plannedStart" ? proposed : local.plannedStart;
      const end = localField === "plannedEnd" ? proposed : local.plannedEnd;
      if (start && end && start > end) {
        conflict("\u98DE\u4E66\u6392\u671F\u4F1A\u5BFC\u81F4\u672C\u5730\u8BA1\u5212\u5F00\u59CB\u665A\u4E8E\u5B8C\u6210\uFF1B\u987B\u4EBA\u5DE5\u786E\u8BA4");
        continue;
      }
      local[localField] = proposed;
      set(baseline.remoteValues, key2, value);
      set(baseline.localValues, localField, proposed);
    }
    if (previousObject.mappingStatus === "conflict" && local) for (const [key2, value] of Object.entries(allRawFields)) {
      if (own4(fields, key2)) continue;
      const rule = ruleByKey.get(`${remote.system}/${remote.remoteKind}/${key2}`);
      if (!rule || rule.localKind !== localKind || !inboundFields.has(rule.localField)) continue;
      const currentRemote = converted(value, rule), oldRemote = converted(baseline.remoteValues[key2], rule);
      const remoteChanged = !own4(baseline.remoteValues, key2) || (currentRemote === void 0 || oldRemote === void 0 ? !same6(value, baseline.remoteValues[key2]) : currentRemote !== oldRemote);
      if (!remoteChanged) continue;
      hasConflict = true;
      conflicts.push({
        id: `feishu-conflict-${hash2([remote.id, key2])}`,
        externalObjectId: remote.id,
        localObjectId: local.id,
        remoteFieldKey: key2,
        localField: rule.localField,
        reason: "\u672C\u6B21\u672A\u8FD4\u56DE\u6B64\u524D\u51B2\u7A81\u5B57\u6BB5\uFF1B\u4FDD\u7559\u5F85\u6838\u5BF9\u72B6\u6001",
        baselineLocal: clone3(baseline.localValues[rule.localField] ?? null),
        baselineRemote: clone3(baseline.remoteValues[key2] ?? null),
        localValue: clone3(local[rule.localField] ?? null),
        remoteValue: clone3(value)
      });
    }
    if (local) {
      const factConflicts = adoptFeishuFacts(state, local, remote, read, baseline);
      conflicts.push(...factConflicts);
      hasConflict ||= factConflicts.length > 0;
    }
    remote.verificationStatus = "verified";
    if (hasConflict) remote.mappingStatus = "conflict";
    else if (remote.mappingStatus === "conflict" && local) remote.mappingStatus = "mapped";
    const rawChanged = !same6(rawSemantic(remote.raw || {}), rawSemantic(raw));
    if (rawChanged) remote.raw = raw;
    if (local && !same6(previousLocal, local)) {
      local.version = (Number.isSafeInteger(local.version) ? local.version : 1) + 1;
      local.updatedAt = timestamp;
    }
    const baselineChanged = !previousBaseline || !same6(previousBaseline.remoteValues, baseline.remoteValues) || !same6(previousBaseline.localValues, baseline.localValues);
    const objectChanged = !same6(previousObject, remote) || mappingChanged || fieldsChanged || baselineChanged || !same6(previousLocal, local);
    if (objectChanged) {
      remote.collectedAt = read.collectedAt;
      remote.sourceHash = sourceHash2;
      if (baselineChanged) {
        baseline.capturedAt = read.collectedAt;
        baseline.sourceHash = sourceHash2;
        baseline.localRevision = input.revision + 1;
      }
      changedObjects.add(remote.id);
    } else unchangedObjects.add(remote.id);
  }
  if (changedObjects.size) {
    state.revision = input.revision + 1;
    state.audit.push({
      id: `audit-feishu-read-${state.revision}-${hash2([timestamp, [...changedObjects]])}`,
      time: timestamp,
      operation: "feishu.read.merge",
      objectId: "feishu-sync",
      before: { revision: input.revision },
      after: { changedObjects: [...changedObjects], conflicts: conflicts.map((row) => row.id), inaccessible: inaccessible.map((row) => row.externalObjectId) },
      actor: "\u98DE\u4E66\u53EA\u8BFB\u540C\u6B65",
      revision: state.revision
    });
  }
  return { state: changedObjects.size ? state : input, changes: changedObjects.size, conflicts, inaccessible, unchanged: [...unchangedObjects].filter((id2) => !changedObjects.has(id2)).length };
}
function resolveFeishuConflict(input, conflict, choice, options = {}) {
  const reject2 = (message) => {
    throw Object.assign(new Error(message), { status: 409 });
  };
  if (!["remote", "local"].includes(choice)) reject2("\u8BF7\u9009\u62E9\u91C7\u7528\u98DE\u4E66\u503C\u6216\u4FDD\u7559\u672C\u5730\u503C");
  const state = clone3(input), remote = state.externalObjects.find((row) => row.id === conflict.externalObjectId);
  if (!remote || remote.workspaceId !== state.workspaceId || remote.system !== "meegle" || remote.verificationStatus !== "verified" || remote.mappingStatus !== "conflict" || remote.localObjectId !== conflict.localObjectId) reject2("\u5BF9\u8C61\u6620\u5C04\u6216\u8BFB\u53D6\u72B6\u6001\u5DF2\u53D8\u5316\uFF0C\u8BF7\u91CD\u65B0\u8BFB\u53D6\u51B2\u7A81");
  const localKind = kindFor(remote.remoteKind), local = localKind ? state[localKind].find((row) => row.id === remote.localObjectId) : void 0;
  const rule = state.mappingRules.find((row) => row.workspaceId === state.workspaceId && row.system === remote.system && row.remoteKind === remote.remoteKind && row.remoteFieldKey === conflict.remoteFieldKey && row.status === "active");
  const fact = local?.feishuFacts?.[conflict.localField], observed = !!fact && fact.externalObjectId === remote.id && fact.fieldKey === conflict.remoteFieldKey && fact.state === "conflict" && !!fact.value;
  if (!local || !rule || rule.localKind !== localKind || rule.localField !== conflict.localField || !inboundFields.has(rule.localField) && !observed) reject2("\u6B64\u51B2\u7A81\u6CA1\u6709\u53EF\u5B89\u5168\u5E94\u7528\u7684\u5B57\u6BB5\u6620\u5C04");
  if (observed && choice === "local") reject2("\u8FD9\u662F\u98DE\u4E66\u4E8B\u5B9E\u5B57\u6BB5\uFF1B\u672C\u5730\u65E7\u503C\u5DF2\u4FDD\u5B58\u5728\u51B2\u7A81\u8BB0\u5F55\u4E2D\uFF0C\u8BF7\u91C7\u7528\u5DF2\u6838\u5BF9\u7684\u98DE\u4E66\u503C\u3002\u4FEE\u6539\u98DE\u4E66\u53E6\u8D70\u6B63\u5F0F\u5BA1\u6838\u3002");
  const baseline = state.syncBaselines.find((row) => row.externalObjectId === remote.id);
  const mirror = state.remoteFieldValues.find((row) => row.externalObjectId === remote.id && row.remoteFieldKey === conflict.remoteFieldKey);
  if (!baseline || !own4(baseline.remoteValues, conflict.remoteFieldKey) || !own4(baseline.localValues, conflict.localField) || !mirror) reject2("\u51B2\u7A81\u5B57\u6BB5\u7F3A\u5C11\u539F\u59CB\u57FA\u7EBF\uFF0C\u987B\u5148\u6838\u5B9E\u5B57\u6BB5\u6620\u5C04");
  if (!same6(mirror.rawValue, conflict.remoteValue) || !same6(local[conflict.localField] ?? null, conflict.localValue) || !same6(baseline.remoteValues[conflict.remoteFieldKey] ?? null, conflict.baselineRemote) || !same6(baseline.localValues[conflict.localField] ?? null, conflict.baselineLocal)) reject2("\u51B2\u7A81\u5185\u5BB9\u6216\u57FA\u7EBF\u5DF2\u53D8\u5316\uFF0C\u8BF7\u5237\u65B0\u540E\u91CD\u65B0\u9009\u62E9");
  if (pendingField(state, local.id, rule.localField)) reject2("\u6B64\u5B57\u6BB5\u4ECD\u6709\u672A\u5BA1\u6838\u8349\u7A3F\uFF0C\u8BF7\u5148\u63A5\u53D7\u6216\u9000\u56DE\u8349\u7A3F");
  const proposed = observed && same6(fact.raw, mirror.rawValue) ? fact.value : converted(mirror.rawValue, rule);
  if (proposed === void 0) reject2("\u8FDC\u7AEF\u503C\u65E0\u6CD5\u5B89\u5168\u8F6C\u6362\uFF0C\u4E0D\u80FD\u901A\u8FC7\u51B2\u7A81\u5904\u7406\u7ED5\u8FC7\u5B57\u6BB5\u6821\u9A8C");
  const timestamp = options.now || (/* @__PURE__ */ new Date()).toISOString(), before = clone3(local[rule.localField]);
  if (choice === "remote") {
    const start = rule.localField === "plannedStart" ? proposed : local.plannedStart;
    const end = rule.localField === "plannedEnd" ? proposed : local.plannedEnd;
    if (start && end && start > end) reject2("\u98DE\u4E66\u6392\u671F\u4F1A\u5BFC\u81F4\u672C\u5730\u8BA1\u5212\u5F00\u59CB\u665A\u4E8E\u5B8C\u6210");
    if (!same6(local[rule.localField], proposed)) {
      local[rule.localField] = proposed;
      if (observed) {
        local.feishuFacts[rule.localField] = { ...fact, state: "mapped" };
        if (rule.localField === "deliveryReview") local.reviewStatus = proposed;
      }
      local.version = (Number.isSafeInteger(local.version) ? local.version : 1) + 1;
      local.updatedAt = timestamp;
    }
    set(baseline.localValues, rule.localField, proposed);
  }
  set(baseline.remoteValues, rule.remoteFieldKey, mirror.rawValue);
  baseline.capturedAt = remote.collectedAt;
  baseline.sourceHash = remote.sourceHash;
  baseline.localRevision = input.revision + 1;
  const remainingConflict = state.remoteFieldValues.some((field) => {
    if (field.externalObjectId !== remote.id || field.remoteFieldKey === rule.remoteFieldKey) return false;
    const other = state.mappingRules.find((row) => row.workspaceId === state.workspaceId && row.system === remote.system && row.remoteKind === remote.remoteKind && row.remoteFieldKey === field.remoteFieldKey && row.status === "active");
    if (!other || other.localKind !== localKind || !inboundFields.has(other.localField)) return false;
    const incoming = converted(field.rawValue, other), oldRemote = converted(baseline.remoteValues[field.remoteFieldKey], other);
    const current = converted(local[other.localField], other), oldLocal = converted(baseline.localValues[other.localField], other);
    const remoteChanged = !own4(baseline.remoteValues, field.remoteFieldKey) || (incoming === void 0 || oldRemote === void 0 ? !same6(field.rawValue, baseline.remoteValues[field.remoteFieldKey]) : incoming !== oldRemote);
    if (!remoteChanged) return false;
    if (pendingField(state, local.id, other.localField) || incoming === void 0) return true;
    if (current === incoming) return false;
    return !own4(baseline.localValues, other.localField) || (current === void 0 || oldLocal === void 0 ? !same6(local[other.localField], baseline.localValues[other.localField]) : current !== oldLocal);
  });
  remote.mappingStatus = remainingConflict ? "conflict" : "mapped";
  state.revision = input.revision + 1;
  state.audit.push({
    id: `audit-feishu-resolve-${state.revision}-${hash2([timestamp, conflict.id, choice])}`,
    time: timestamp,
    operation: "feishu.conflict.resolve",
    objectId: local.id,
    before: { field: rule.localField, value: before, remote: conflict.baselineRemote },
    after: { field: rule.localField, value: local[rule.localField], remote: mirror.rawValue, choice, externalWriteExecuted: false },
    actor: "\u9879\u76EE\u7ECF\u7406",
    revision: state.revision
  });
  return state;
}

// lib/review-brief.ts
var same7 = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
var pending2 = (op) => !op.status || op.status === "pending";
var gapText = (text15) => text15.trim().replace(/[；;。\s]+$/g, "");
var unique4 = (values) => [...new Set(values.filter(Boolean))];
var nonempty = (value) => value !== null && value !== void 0 && value !== "" && (!Array.isArray(value) || value.length > 0);
var verificationFields = ["executor", "executorId", "dueAt", "committed", "forecast", "actual", "acceptor", "acceptorId"];
function reviewBrief(s, group) {
  const sources = new Map(s.sources.filter((row) => !row.archived).map((row) => [row.id, row]));
  const items = group.operations.map((operation) => {
    const op = operation;
    const current = s[op.kind].find((row) => row.id === op.targetId);
    const title2 = String(op.after.title || current?.title || op.targetId);
    const verification = op.kind === "actions" && op.action === "create" && op.classification !== "fact" && /^核实|^核对.*(?:身份|缺口|依据)/.test(title2);
    const identityCheck = verification && /身份|真实.*ID|对应|别名/i.test(title2);
    const conflictFields = !pending2(op) ? [] : op.action === "create" ? current ? ["id"] : [] : !current ? ["id"] : Object.keys(op.after).filter((field) => !same7(current[field], op.before[field]));
    const missingSources = unique4(op.sourceIds || []).filter((id2) => !sources.has(id2));
    const versions = op.sourceVersions || [];
    const changedSources = !pending2(op) ? [] : versions.filter((basis) => {
      const source = sources.get(basis.objectId);
      const creatingHere = !s.sources.some((row) => row.id === basis.objectId) && group.operations.some((other) => other.kind === "sources" && other.action === "create" && other.targetId === basis.objectId && pending2(other));
      return !creatingHere && (!source || (source.version || 1) !== basis.version);
    }).map((basis) => basis.objectId);
    const hasGaps = verification || (op.missingInfo || []).length > 0 || !op.sourceIds?.length || missingSources.length > 0 || op.classification === "hypothesis";
    const category = !pending2(op) ? "reviewed" : conflictFields.length || changedSources.length ? "conflict" : hasGaps ? "evidence" : "ready";
    const label2 = category === "reviewed" ? op.status === "accepted" ? "\u5DF2\u63A5\u53D7" : "\u5DF2\u62D2\u7EDD" : category === "conflict" ? "\u5148\u5904\u7406\u51B2\u7A81" : verification ? "\u62DF\u5EFA\u6838\u5B9E\u5F85\u529E" : category === "evidence" ? "\u5148\u8865\u4F9D\u636E" : "\u5F85\u4F60\u6838\u5BF9";
    const assigned = verificationFields.some((field) => nonempty(op.after[field]));
    const effect = verification ? "\u65B0\u589E 1 \u6761\u672C\u5730\u6838\u5B9E\u5F85\u529E" + (assigned ? "\uFF0C\u542B\u8D23\u4EFB\u6216\u65E5\u671F\u7B49\u5B89\u6392\uFF0C\u8BF7\u5C55\u5F00\u6838\u5BF9" : "\uFF0C\u6267\u884C\u4EBA\u4E0E\u65E5\u671F\u5F85\u5B9A") : (op.action === "create" ? "\u672C\u5730\u65B0\u589E 1 \u6761" : "\u4FEE\u6539\u672C\u5730") + v2Labels[op.kind] + (op.action === "update" ? "\u7684 " + Object.keys(op.after).length + " \u4E2A\u5B57\u6BB5" : "\u8BB0\u5F55");
    let conclusion = "\u5DF2\u6709\u5177\u4F53\u62DF\u4FEE\u6539\u5185\u5BB9\uFF0C\u8BF7\u6838\u5BF9\u4FEE\u6539\u503C\u4E0E\u6765\u6E90\u662F\u5426\u4E00\u81F4\u3002";
    if (category === "conflict") conclusion = changedSources.length ? "\u5F15\u7528\u6765\u6E90\u5DF2\u53D8\u5316\u6216\u5931\u6548\uFF0C\u9700\u8981\u91CD\u65B0\u6838\u5BF9\u4F9D\u636E\u5E76\u4FEE\u8BA2\u8349\u7A3F\u3002" : "\u53F0\u8D26\u5DF2\u53D8\u5316\uFF1B\u9700\u8981\u5BF9\u7167\u6700\u65B0\u503C\u91CD\u65B0\u6574\u7406\u8FD9\u9879\u4FEE\u6539\u3002";
    else if (verification) conclusion = identityCheck ? "\u5148\u6838\u5BF9\u65B0\u65E7\u8BB0\u5F55\u662F\u5426\u5BF9\u5E94\u540C\u4E00\u5BF9\u8C61\uFF0C\u518D\u51B3\u5B9A\u5982\u4F55\u5173\u8054\u3002" : "\u8349\u7A3F\u5217\u51FA\u4E86\u5F85\u67E5\u95EE\u9898\uFF0C\u5C1A\u672A\u7ED9\u51FA\u6838\u5B9E\u540E\u7684\u9879\u76EE\u4FEE\u6539\u503C\u3002";
    else if (missingSources.length) conclusion = "\u90E8\u5206\u5F15\u7528\u5C1A\u672A\u8FDB\u5165\u5F53\u524D\u8D44\u6599\u5E93\uFF0C\u9700\u5148\u6838\u5BF9\u6216\u63A5\u53D7\u5BF9\u5E94\u6765\u6E90\u3002";
    else if (!op.sourceIds?.length) conclusion = "\u5C1A\u65E0\u5F15\u7528\u6765\u6E90\uFF0C\u8BF7\u5148\u8865\u4F9D\u636E\u6216\u660E\u786E\u4EBA\u5DE5\u5224\u65AD\u7406\u7531\u3002";
    else if (hasGaps) conclusion = "\u8349\u7A3F\u4ECD\u6709\u672A\u786E\u8BA4\u5185\u5BB9\uFF0C\u5EFA\u8BAE\u8865\u9F50\u4F9D\u636E\u540E\u518D\u63A5\u53D7\u3002";
    if (category === "reviewed") conclusion = op.status === "accepted" ? "\u8FD9\u9879\u4FEE\u6539\u5DF2\u4FDD\u5B58\u5230\u672C\u5730\uFF0C\u53EF\u5C55\u5F00\u67E5\u770B\u5B57\u6BB5\u4E0E\u5BA1\u8BA1\u3002" : "\u8FD9\u9879\u5EFA\u8BAE\u5DF2\u62D2\u7EDD\uFF0C\u539F\u8349\u7A3F\u4FDD\u7559\u4F9B\u8FFD\u6EAF\u3002";
    const changes = Object.entries(op.after).filter(([field, value]) => !["projectIds", "sourceIds", "classification"].includes(field) && !(field === "title" && op.action === "create") && (op.action === "update" || nonempty(value))).sort(([a], [b]) => Number(["description", "resourceNote", "followUp"].includes(a)) - Number(["description", "resourceNote", "followUp"].includes(b))).map(([field, value]) => ({ field, before: pending2(op) ? current?.[field] : op.before[field], after: value }));
    return { operation: op, title: title2, category, label: label2, verification, identityCheck, conclusion, effect, conflictFields, missingSources, changedSources, changes };
  });
  const active5 = items.filter((item) => pending2(item.operation));
  const verificationCount = active5.filter((item) => item.verification).length;
  const conflictCount = active5.filter((item) => item.category === "conflict").length;
  const evidenceCount = active5.filter((item) => item.category === "evidence").length;
  const readyCount = active5.filter((item) => item.category === "ready").length;
  const identityCount = active5.filter((item) => item.identityCheck).length;
  const allVerification = active5.length > 0 && verificationCount === active5.length;
  const projectIds2 = unique4(active5.flatMap(({ operation: op }) => op.kind === "projects" ? [op.targetId] : op.after.projectIds || s[op.kind].find((row) => row.id === op.targetId)?.projectIds || []));
  const gaps = /* @__PURE__ */ new Map();
  for (const { operation: op } of active5) for (const raw of op.missingInfo || []) {
    const text15 = gapText(raw);
    if (!text15) continue;
    const ids8 = gaps.get(text15) || /* @__PURE__ */ new Set();
    ids8.add(op.id);
    gaps.set(text15, ids8);
  }
  const commonGaps = [...gaps].filter(([, ids8]) => ids8.size > 1).map(([text15, ids8]) => ({ text: text15, count: ids8.size })).sort((a, b) => b.count - a.count);
  const sourceIds = unique4(active5.flatMap((item) => item.operation.sourceIds || []));
  const savedSources = sourceIds.flatMap((id2) => sources.has(id2) ? [sources.get(id2)] : []);
  const dates = savedSources.map((source) => source.collectedAt || source.occurredAt || source.createdAt).filter((value) => value && Number.isFinite(Date.parse(value))).sort((a, b) => Date.parse(a) - Date.parse(b));
  const hasConflict = conflictCount > 0 || !!group.conflicts?.length;
  const title = !active5.length ? "\u8FD9\u6279\u4FEE\u6539\u5DF2\u5904\u7406" : hasConflict ? "\u5148\u5904\u7406\u51B2\u7A81\uFF0C\u518D\u51B3\u5B9A\u4FEE\u6539" : allVerification ? "\u5EFA\u8BAE\u5148\u8865\u4F9D\u636E\uFF0C\u518D\u51B3\u5B9A\u662F\u5426\u5EFA\u5F85\u529E" : evidenceCount ? "\u90E8\u5206\u5185\u5BB9\u9700\u8865\u4F9D\u636E\uFF0C\u5EFA\u8BAE\u5206\u5F00\u5904\u7406" : "\u5DF2\u6709\u5177\u4F53\u4FEE\u6539\uFF0C\u7B49\u5F85\u4F60\u6838\u5BF9";
  const summary = !active5.length ? "\u53EF\u67E5\u770B\u539F\u8349\u7A3F\u3001\u9010\u9879\u51B3\u5B9A\u548C\u4FDD\u5B58\u7ED3\u679C\u3002" : allVerification ? `\u8FD9\u6279\u62DF\u65B0\u589E ${verificationCount} \u6761\u6838\u5B9E\u5F85\u529E${projectIds2.length ? `\uFF0C\u6D89\u53CA ${projectIds2.length} \u4E2A\u9879\u76EE` : ""}\u3002\u8349\u7A3F\u5C1A\u672A\u63D0\u4F9B\u6838\u5B9E\u540E\u7684\u9879\u76EE\u5B57\u6BB5\u4FEE\u6539\u3002` : `\u672C\u6279 ${active5.length} \u9879\u5F85\u5904\u7406\uFF1A${[readyCount ? `${readyCount} \u9879\u53EF\u6838\u5BF9\u5177\u4F53\u4FEE\u6539` : "", evidenceCount ? `${evidenceCount} \u9879\u5EFA\u8BAE\u5148\u8865\u4F9D\u636E` : "", conflictCount ? `${conflictCount} \u9879\u5B58\u5728\u51B2\u7A81` : ""].filter(Boolean).join("\uFF1B")}\u3002`;
  const recommendation = !active5.length ? "\u67E5\u770B\u5DF2\u4FDD\u5B58\u7684\u5BA1\u6838\u7ED3\u679C\u3002" : hasConflict ? "\u5148\u67E5\u770B\u4E24\u4FA7\u503C\u4E0E\u5173\u8054\u8BB0\u5F55\uFF0C\u4FEE\u8BA2\u8349\u7A3F\u540E\u91CD\u65B0\u5BA1\u6838\u3002" : allVerification ? identityCount ? `\u4F18\u5148\u6838\u5BF9 ${identityCount} \u9879\u5BF9\u8C61\u8EAB\u4EFD\uFF1B\u5171\u6027\u7F3A\u53E3\u96C6\u4E2D\u8865\u67E5\u540E\uFF0C\u4EC5\u5C06\u4ECD\u9700\u8DDF\u8FDB\u7684\u4E8B\u9879\u52A0\u5165\u5F85\u529E\u3002` : "\u5148\u96C6\u4E2D\u8865\u67E5\u5171\u6027\u7F3A\u53E3\uFF0C\u4EC5\u5C06\u4ECD\u9700\u4EBA\u5DE5\u8DDF\u8FDB\u7684\u4E8B\u9879\u52A0\u5165\u5F85\u529E\u3002" : evidenceCount ? "\u5148\u6838\u5BF9\u6709\u5177\u4F53\u4FEE\u6539\u7684\u6761\u76EE\uFF1B\u672A\u786E\u8BA4\u7684\u5185\u5BB9\u4FDD\u7559\u5F85\u67E5\u3002" : "\u9010\u9879\u68C0\u67E5\u4FEE\u6539\u524D\u540E\u503C\uFF0C\u518D\u9009\u62E9\u63A5\u53D7\u8303\u56F4\u3002";
  return {
    items,
    active: active5,
    title,
    summary,
    recommendation,
    allVerification,
    verificationCount,
    identityCount,
    conflictCount,
    evidenceCount,
    readyCount,
    projectIds: projectIds2,
    commonGaps,
    sourceCount: sourceIds.length,
    availableSources: savedSources.length,
    earliestSourceAt: dates[0],
    latestSourceAt: dates.at(-1)
  };
}

// lib/risk-policy.ts
function adoptRiskPolicy(s, at) {
  if (s.workspaceType !== "official") return false;
  const first = s.riskPolicy?.version !== 1;
  const historicalProjects = s.projects.filter((p) => !p.archived).map((p) => p.id), deferred = [];
  for (const node of s.flowNodes) if (first && !node.archived && ["\u5DF2\u5B8C\u6210", "finished"].includes(node.nodeStatus)) {
    node.historicalGapDeferred = { at, reason: "2026\u5E7410\u670810\u65E5\u672C\u4EBA\u786E\u8BA4\uFF1A\u65E7\u9879\u76EE\u5386\u53F2\u7F3A\u53E3\u6682\u4E0D\u8FFD\u8865" };
    deferred.push(node.id);
  }
  const proposals = [];
  for (const group of s.changeGroups) {
    if (!["pending", "partial"].includes(group.status) || !reviewBrief(s, group).allVerification || group.aiTriageSourceIds?.length) continue;
    group.aiTriageSourceIds = [];
    group.history.push({ at, operation: "ai-triage", priorStatus: group.status, reason: "\u672C\u4EBA\u786E\u8BA4\uFF1A\u6838\u5B9E\u5EFA\u8BAE\u5148\u7ECFAI\u5224\u65AD\u5FC5\u8981\u6027\uFF0C\u6CBF\u7528\u540C\u4E00\u4E8B\u9879\u5904\u7406" });
    group.status = "withdrawn";
    for (const op of group.operations.filter((op2) => !op2.status || op2.status === "pending")) {
      const id2 = "risk-proposal-" + stableHash(group.id + ":" + op.id);
      if (!s.sources.some((row) => row.id === id2)) s.sources.push({ id: id2, title: op.after.title || "\u6838\u5B9E\u5EFA\u8BAE\u5FC5\u8981\u6027\u5F85\u5224\u65AD", type: "\u6838\u5B9E\u5EFA\u8BAE", projectIds: op.after.projectIds || [], sourceIds: op.sourceIds, objectIds: op.after.projectIds || [], excerpt: JSON.stringify({ kind: "\u5386\u53F2\u6838\u5B9E\u5EFA\u8BAE", proposedAt: group.createdAt, title: op.after.title, reason: op.reason, questions: op.missingInfo, proposedFields: op.after, nextStep: op.after.followUp || "", rule: "\u65E7\u9879\u76EE\u7684\u5386\u53F2\u8D44\u6599\u7F3A\u53E3\u6682\u4E0D\u8FFD\u8865\uFF1B\u53EA\u6709\u5F53\u524D\u4ECD\u6709\u660E\u786E\u5F71\u54CD\u6216\u9700\u672C\u4EBA\u63A8\u8FDB\u7684\u4E8B\u624D\u8FDB\u5165\u5F85\u529E\uFF1B\u68C0\u67E5\u662F\u5426\u5DF2\u6709\u540C\u4E00\u4E8B\u9879\u3002" }), collectedAt: at, occurredAt: at, version: 1, confirmed: false, riskEvent: { kind: "verification-proposal", groupId: group.id, operationId: op.id } });
      group.aiTriageSourceIds.push(id2);
      proposals.push(id2);
    }
  }
  if (!first && !proposals.length) return false;
  s.riskPolicy = { version: 1, adoptedAt: s.riskPolicy?.adoptedAt || at, historicalProjectIds: s.riskPolicy?.historicalProjectIds || historicalProjects, deferredNodeIds: s.riskPolicy?.deferredNodeIds || deferred, proposalSourceIds: [...s.riskPolicy?.proposalSourceIds || [], ...proposals] };
  s.audit.push({ id: "risk-policy-" + stableHash(at + proposals.join(",")), time: at, operation: "risk.policy.adopt", objectId: "risk-policy", actor: "\u672C\u4EBA\u5DF2\u786E\u8BA4\u89C4\u5219", before: null, after: { deferredNodeIds: deferred, proposalSourceIds: proposals }, revision: s.revision + 1 });
  return true;
}

// lib/collected-intake.ts
function collectedMaterial(s, src) {
  if (src.archived || src.intakeDocument || src.intakeBatch || !caseEvidenceAvailable(s, src)) return null;
  let kind = "", label2 = "", eventAt = "", rangeVerified = false;
  if (isCommentFeedback(src)) {
    if (src.feedback.deleted || src.feedback.outgoing || !feedbackTarget(s, src)) return null;
    kind = "feedback";
    label2 = src.type;
    eventAt = src.feedback.eventAt;
    rangeVerified = src.feedback.timeUncertain;
    if (!src.excerpt?.trim() && src.feedback.channel !== "feishu-task-attachment") return null;
  } else if (src.caseChat || src.caseFile) {
    const origin = src.caseChat ? src : s.sources.find((p) => p.id === src.caseFile.parentSourceId);
    if (!origin?.caseChat) return null;
    const projectScope = (origin.projectChat?.scopeIds || []).some((id2) => s.sources.some((scope) => scope.id === id2 && !scope.archived && scope.chatScope?.state === "active" && (!scope.chatScope.projectId || s.projects.some((p) => p.id === scope.chatScope.projectId && !p.archived)) && scope.chatScope.chatId === origin.caseChat.chatId && scope.chatScope.scope === origin.caseChat.scope && scope.chatScope.accountId === origin.caseChat.accountId));
    const caseScope = [...src.caseIds || [], ...origin.caseIds || []].some((id2) => {
      const c = s.cases.find((c2) => c2.id === id2 && !c2.archived && c2.status !== "\u5DF2\u5173\u95ED");
      return c?.chatBinding?.chatId === origin.caseChat.chatId && c?.chatBinding?.scope === origin.caseChat.scope && c?.chatBinding?.accountId === origin.caseChat.accountId;
    });
    if (!projectScope && !caseScope) return null;
    kind = src.caseFile ? "case-file" : projectScope ? "project-chat" : "case-chat";
    label2 = src.caseFile ? "\u7FA4\u6587\u4EF6\u6B63\u6587" : projectScope ? "\u9879\u76EE\u4E0E\u5DE5\u4F5C\u7FA4" : "\u4E13\u9879\u7FA4\u804A";
    eventAt = feedbackTime(origin.caseChat.raw.create_time);
    rangeVerified = origin.caseChat.rangeVerified === true;
    if (!src.excerpt?.trim() && !(src.caseFile && ["ready", "partial"].includes(src.readStatus) && src.attachments?.length)) return null;
  } else if (src.meetingContext) {
    const c = src.meetingContext;
    if (c.kind !== "work" || c.raw.status === "cancelled" || !c.association?.projectIds?.length || !["ready", "partial"].includes(c.minutes.status) || !c.minutes.documents?.some((doc) => !doc.stale && doc.content?.trim())) return null;
    kind = "meeting-minutes";
    label2 = "\u5DE5\u4F5C\u4F1A\u8BAE\u7EAA\u8981";
    eventAt = feedbackTime(src.occurredAt);
  } else return null;
  if (eventAt ? Date.parse(eventAt) < Date.parse(feedbackCollectFrom) || !feedbackTime(src.collectedAt) || Date.parse(eventAt) > Date.parse(src.collectedAt) : !rangeVerified) return null;
  const projectIds2 = src.projectIds.filter((id2) => s.projects.some((p) => p.id === id2 && !p.archived));
  return { kind, label: label2, eventAt, projectId: projectIds2.length === 1 ? projectIds2[0] : "", fingerprint: materialSourceIdentityKey(s, src) };
}
function collectedText(src) {
  if (src.meetingContext) return src.meetingContext.minutes.documents.filter((doc) => !doc.stale && doc.content?.trim()).map((doc) => "\u3010" + doc.title + "\u3011\n" + doc.content).join("\n\n");
  return src.excerpt || "";
}
function collectedLimitations(src) {
  const messages = [];
  if (src.meetingContext && (src.meetingContext.minutes.status !== "ready" || src.meetingContext.minutes.documents.some((d) => d.stale))) messages.push("\u90E8\u5206\u4F1A\u8BAE\u7EAA\u8981\u4E0D\u53EF\u7528\uFF0C\u4EC5\u6574\u7406\u672C\u6B21\u5DF2\u53D6\u5F97\u7684\u6B63\u6587");
  if (src.caseChat && chatFiles(src.caseChat.raw).length) messages.push("\u7FA4\u6D88\u606F\u5305\u542B\u6587\u4EF6\u5F15\u7528\uFF0C\u6587\u4EF6\u6B63\u6587\u9700\u5728\u539F\u8D44\u6599\u5165\u53E3\u8BFB\u53D6\u540E\u518D\u6574\u7406");
  return messages;
}
function intakeStaleDocuments(s, batch) {
  return (batch.intakeBatch?.documents || []).filter((id2) => {
    const doc = s.sources.find((src) => src.id === id2);
    return !doc || !caseEvidenceAvailable(s, doc);
  });
}
function intakeSourceWasReplaced(s, batch, documentId) {
  const doc = s.sources.find((src) => src.id === documentId), original = s.sources.find((src) => src.id === doc?.intakeDocument?.originalSourceId);
  return !!original?.collectedIntake?.batchId && original.collectedIntake.batchId !== batch.id;
}
function reuseCollectedFeedback(s, batchId, result, contexts, at) {
  const batch = s.sources.find((src) => src.id === batchId);
  for (const doc of result.documents) {
    const read = s.sources.find((src) => src.id === doc.sourceId), origin = s.sources.find((src) => src.id === read?.intakeDocument?.originalSourceId);
    if (!origin || !isCommentFeedback(origin) || origin.feedback.deleted || origin.collectedIntake?.batchId !== batchId) continue;
    const f = origin.feedback, candidates = contexts.get(origin.id) || [];
    const viewerAction = result.signals.some((v) => v.sourceId === doc.sourceId && v.viewerAction === true);
    const responseTo = viewerAction ? [] : candidates.filter((c) => {
      const row = s[c.kind].find((r) => r.id === c.id && !r.archived);
      return row && followupSignature(row, c.kind) === c.signature && doc.updates.some((u) => u.clearResponse && !u.conflict && u.progressQuote && u.targetId === intakeCanonicalTarget(s, c.id));
    }).map((c) => c.id);
    const evidence = [...new Set([...doc.updates.map((u) => u.progressQuote || u.forecastQuote), ...result.signals.filter((v) => v.sourceId === doc.sourceId).map((v) => v.quote)].filter((q) => typeof q === "string" && q && origin.excerpt.includes(q)))].slice(0, 3).map((q) => q.slice(0, 400));
    f.analysis = { status: "ready", summary: doc.summary.slice(0, 240), kind: viewerAction ? "needs_confirmation" : responseTo.length ? "response" : "progress", responseTo, evidence, uncertainties: [], contentVersion: f.contentVersion, analysedAt: at, error: "", provider: "\u7EDF\u4E00\u8D44\u6599\u6574\u7406", contexts: Object.fromEntries(candidates.map((c) => [c.id, c.signature])), viewerAction };
    origin.version++;
    origin.updatedAt = at;
    batch.sourceIds = [.../* @__PURE__ */ new Set([...batch.sourceIds, origin.id])];
  }
}

// lib/meeting-context.ts
var meetingKinds = {
  unknown: "\u662F\u5426\u5DE5\u4F5C\u4F1A\u8BAE\u5F85\u786E\u8BA4",
  work: "\u5DE5\u4F5C\u4F1A\u8BAE",
  other: "\u666E\u901A\u65E5\u7A0B / \u975E\u5DE5\u4F5C\u4F1A\u8BAE"
};
var minutesLabels = {
  unread: "\u7EAA\u8981\u5C1A\u672A\u8BFB\u53D6",
  ready: "\u7EAA\u8981\u5DF2\u8BFB\u53D6",
  partial: "\u7EAA\u8981\u90E8\u5206\u8BFB\u53D6",
  not_found: "\u5C1A\u672A\u627E\u5230\u7EAA\u8981",
  unavailable: "\u7EAA\u8981\u8BFB\u53D6\u53D7\u9650",
  generating: "\u7EAA\u8981\u751F\u6210\u4E2D",
  permission_denied: "\u65E0\u6743\u8BFB\u53D6\u7EAA\u8981",
  cancelled: "\u65E5\u7A0B\u5DF2\u53D6\u6D88",
  stale: "\u7EAA\u8981\u4E3A\u65E7\u7248\u672C\uFF0C\u9700\u91CD\u65B0\u8BFB\u53D6",
  mixed: "\u7EAA\u8981\u53EF\u80FD\u6DF7\u5165\u5176\u4ED6\u4F1A\u8BAE\uFF0C\u8BF7\u6838\u5BF9",
  unverified: "\u5B9E\u9645\u4F1A\u8BAE\u8EAB\u4EFD\u5C1A\u672A\u6838\u5BF9"
};
function isMeetingContext(row) {
  return row.meetingContext?.schemaVersion === 1;
}
function meetingNeedsConfirmation(s, row) {
  const c = row.meetingContext;
  if (!c || c.raw.status === "cancelled" || c.kind === "other") return false;
  if (c.kind === "unknown" || !c.association) return true;
  return c.association.projectIds.some((id2) => !s.projects.some((p) => p.id === id2 && !p.archived));
}
function meetingTime(value) {
  if (!value) return "";
  if (typeof value.timestamp === "string" && /^\d+$/.test(value.timestamp)) {
    const ms = Number(value.timestamp) * 1e3;
    return Number.isFinite(ms) && !Number.isNaN(new Date(ms).getTime()) ? new Date(ms).toISOString() : "";
  }
  if (typeof value.datetime === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value.datetime) && Number.isFinite(Date.parse(value.datetime))) return new Date(value.datetime).toISOString();
  if (typeof value.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value.date) && Number.isFinite(Date.parse(value.date))) return value.date + "T00:00:00.000Z";
  return "";
}
function safeFeishuUrl(value) {
  try {
    const u = new URL(String(value));
    if (u.protocol === "https:" && !u.username && !u.password && !u.port && (u.hostname === "feishu.cn" || u.hostname.endsWith(".feishu.cn"))) return u.href;
  } catch {
  }
  return "";
}

// lib/risk-management.ts
var metadataFields = {
  sources: /* @__PURE__ */ new Set(["title", "description", "excerpt", "summary", "type", "url", "author", "occurredAt", "collectedAt", "sourceIds", "objectIds", "projectIds", "processingStatus", "tags"]),
  projects: /* @__PURE__ */ new Set(["code", "description", "sourceIds", "aliases"]),
  flowNodes: /* @__PURE__ */ new Set(["description", "sourceIds"]),
  deliverables: /* @__PURE__ */ new Set(["description", "sourceIds"])
};
function isRoutineDataChange(group) {
  const pending3 = group.operations.filter((op) => !op.status || op.status === "pending");
  return pending3.length > 0 && pending3.every((op) => {
    const allowed = metadataFields[op.kind];
    if (!allowed || op.action !== "update") return false;
    const fields = Object.keys(op.after);
    return fields.length > 0 && fields.every((field) => allowed.has(field));
  });
}
function isBusinessIntakeSignal(signal) {
  return signal.kind === "risk" || signal.kind === "followup" || signal.urgency === "urgent";
}
function legacyRiskState(row) {
  const closed4 = ["\u5DF2\u9A8C\u6536", "\u9A8C\u6536\u901A\u8FC7", "\u5DF2\u901A\u8FC7", "\u901A\u8FC7"].includes(row.acceptanceStatus) || ["\u5DF2\u5173\u95ED", "\u5DF2\u89E3\u9664", "\u5DF2\u51B3\u7B56", "\u5DF2\u53D6\u6D88"].includes(row.status);
  const unconfirmed2 = row.confirmed === false || row.stale === true || ["suggestion", "hypothesis"].includes(row.classification || row.draftClassification);
  return { closed: closed4, confirmed: row.confirmed === true && !unconfirmed2 };
}

// lib/workbench-overview.ts
var text13 = (v) => typeof v === "string" ? v.trim() : "";
var ids7 = (v) => Array.isArray(v) ? v.filter((id2) => typeof id2 === "string") : [];
var live = (r) => !r.archived && !r.mergedIntoId;
var unique5 = (rows2) => [...new Map(rows2.filter(live).map((r) => [r.id, r])).values()];
var accepted4 = (r) => deliveryRecorded(r) || ["\u5DF2\u9A8C\u6536", "\u9A8C\u6536\u901A\u8FC7", "\u5DF2\u901A\u8FC7", "\u901A\u8FC7"].includes(text13(r.acceptanceStatus));
var completed3 = (r) => ["\u5DF2\u5B8C\u6210", "\u5B8C\u6210", "\u56E2\u961F\u53CD\u9988\u5B8C\u6210", "\u6267\u884C\u5B8C\u6210", "\u5DF2\u4EA4\u4ED8", "\u5DF2\u7ED3\u675F", "finished"].includes(text13(r.executionStatus || r.nodeStatus || r.status));
var closed3 = (r) => accepted4(r) || ["\u5DF2\u5173\u95ED", "\u5DF2\u89E3\u9664", "\u5DF2\u51B3\u7B56", "\u5DF2\u53D6\u6D88"].includes(text13(r.status));
var unconfirmed = (r) => r.confirmed === false || r.stale === true || ["suggestion", "hypothesis"].includes(r.classification || r.draftClassification);
function overviewDate(value) {
  const v = text13(value), n = Date.parse(v + "T12:00:00Z");
  return /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(n) && new Date(n).toISOString().slice(0, 10) === v ? v : "";
}
function overviewOwner(value, people) {
  if (Array.isArray(value)) return [...new Set(value.map((v2) => overviewOwner(v2, people)).filter(Boolean))].join("\u3001");
  if (value && typeof value === "object") {
    const row = value;
    return text13(row.name || row.display_name || row.displayName) || overviewOwner(row.id || row.key || row.open_id, people);
  }
  const v = text13(value);
  if (/^[\[{]/.test(v)) {
    try {
      return overviewOwner(JSON.parse(v), people);
    } catch {
      return "";
    }
  }
  const person = people.find((p) => live(p) && [p.id, p.meegleUserKey, p.feishuUserId].includes(v));
  return person?.title || (/^\d{7,}$|^(ou_|on_|user_|person-)/.test(v) ? "" : v);
}
function buildWorkbenchOverview(s, date4, clock, { includeDataReview = true } = {}) {
  const now2 = clock ?? (date4 ? Date.parse(date4 + "T12:00:00+08:00") : Date.now());
  date4 ??= followupDay(now2);
  const projects = unique5(sortProjectsByLevel(s)), projectIds2 = new Set(projects.map((p) => p.id));
  const summaries = new Map(buildWeeklyMeetingSnapshot(s).projects.map((p) => [p.id, p]));
  const attention = [];
  const feedbackConcerns = /* @__PURE__ */ new Map();
  const owner2 = (r) => overviewOwner(r.ownerId || r.owner || r.executorId || r.executor, s.people);
  const push = (r, kind, category, reasons, urgent = false, next = "\u67E5\u770B\u8BB0\u5F55") => {
    attention.push({
      id: kind + ":" + r.id,
      targetId: r.id,
      kind,
      title: r.title,
      projectIds: ids7(r.projectIds).filter((id2) => projectIds2.has(id2)),
      category,
      urgent,
      caseId: kind === "cases" ? r.id : r.caseId || r.caseIds?.[0],
      reason: reasons[0],
      reasons,
      summary: text13(r.deliverableProgress || r.progressNote || r.description || r.excerpt || r.situation || r.impact),
      next,
      owner: owner2(r),
      date: overviewDate(r.checkAt || r.deadline || r.dueAt || r.neededBy || r.plannedEnd || r.committed),
      sourceIds: ids7(r.sourceIds),
      relatedIds: []
    });
  };
  const eligible = (r) => !ids7(r.projectIds).length || ids7(r.projectIds).some((id2) => projectIds2.has(id2));
  const latestResultReviews = /* @__PURE__ */ new Map();
  for (const source of s.sources.filter((row) => !row.archived && row.resultReview).slice().sort((a, b) => String(a.collectedAt).localeCompare(String(b.collectedAt)))) latestResultReviews.set(source.resultReview.deliverableId, source);
  for (const kind of ["deliverables", "actions", "flowNodes", "milestones", "dependencies"]) {
    for (const row of unique5(s[kind]).filter(eligible)) {
      if (kind === "deliverables" && row.importedFrom?.system === "feishu" && !row.feishuFacts?.deliveryReview) continue;
      if (row.riskTrackingItemId && s.sources.some((source) => source.id === row.riskTrackingItemId && source.workItem && !source.archived)) continue;
      if (row.workItemId && s.sources.some((source) => source.id === row.workItemId && source.workItem?.actionTargets?.some((ref) => ref.id === row.id) && !source.archived)) continue;
      const resultReview = kind === "deliverables" ? latestResultReviews.get(row.id) : void 0, pendingResult = false;
      if (kind === "deliverables" && deliveryRecorded(row) && !isBlocked(row)) continue;
      if (kind === "flowNodes" && completed3(row) && !isBlocked(row) && !row.currentImpactConfirmed) continue;
      const parentCase = row.caseId ? (s.cases || []).find((c) => c.id === row.caseId) : void 0;
      if (row.caseId && (!parentCase || parentCase.archived || parentCase.status === "\u5DF2\u5173\u95ED" || parentCase.myRole === "\u5173\u6CE8")) continue;
      if (row.taskObservationOnly || closed3(row) && !pendingResult || row.submissionStatus === "\u514D\u4EA4\u4ED8") continue;
      const reasons = [];
      const due = overviewDate(row.checkAt || row.dueAt || row.neededBy || row.plannedEnd || row.committed || row.expectedAt);
      const returned = !pendingResult && (row.submissionStatus === "\u9700\u8865\u5145" || row.acceptanceStatus === "\u672A\u901A\u8FC7");
      const isGate = kind === "flowNodes" && ids7(row.projectIds).some((id2) => flowNodeTypeLabel(row, { isIpd: summaries.get(id2)?.isIpd }) === "\u91CC\u7A0B\u7891\u8282\u70B9");
      const submitted = pendingResult || !returned && (row.submissionStatus === "\u5DF2\u63D0\u4EA4" || kind !== "deliverables" && (kind !== "flowNodes" || isGate) && completed3(row));
      if (isBlocked(row)) reasons.push(text13(row.blocker) && !["\u65E0", "\u6682\u65E0", "\u5DF2\u89E3\u9664"].includes(row.blocker) ? "\u5DF2\u8BB0\u5F55\u5361\u70B9\uFF1A" + row.blocker : "\u5DF2\u8BB0\u5F55\u53D7\u963B\uFF0C\u9700\u8981\u8DDF\u8FDB");
      if (returned) reasons.push("\u6210\u679C\u9700\u8865\u5145\u6216\u91CD\u65B0\u63D0\u4EA4");
      if (row.status === "\u9700\u8981\u5347\u7EA7\u534F\u8C03") reasons.push("\u5DF2\u6807\u8BB0\u9700\u8981\u5347\u7EA7\u534F\u8C03");
      if (row.status === "\u4ECA\u5929\u9700\u8981\u63A8\u52A8") reasons.push("\u5DF2\u6807\u8BB0\u4ECA\u5929\u9700\u8981\u63A8\u52A8");
      if (submitted) reasons.push(kind === "deliverables" ? "\u5DE5\u7A0B\u5E08\u5DF2\u53CD\u9988\u63D0\u4EA4\uFF0C\u4EA4\u4ED8\u7269\u5BA1\u6838\u6807\u8BB0\u5F85\u540C\u6B65\u6838\u5BF9" : ["flowNodes", "milestones"].includes(kind) ? "\u8282\u70B9\u5DF2\u53CD\u9988\u5B8C\u6210\uFF0C\u4EA4\u4ED8\u7269\u5173\u8054\u6216\u4EA4\u4ED8\u6807\u8BB0\u9700\u8981\u6838\u5BF9" : "\u5DF2\u53CD\u9988\u5B8C\u6210\uFF0C\u9A8C\u6536\u7ED3\u8BBA\u5F85\u6838\u5BF9");
      if (due && due <= date4 && !submitted && !completed3(row)) {
        const label2 = row.caseId ? row.checkAt ? "\u53CD\u9988\u65F6\u95F4" : row.expectedAt ? "\u671F\u671B\u4EA4\u4ED8\u65F6\u95F4" : "\u627F\u8BFA\u5B8C\u6210\u65F6\u95F4" : "\u8BA1\u5212\u6216\u8DDF\u8FDB\u65E5\u671F";
        reasons.push((due < date4 ? label2 + "\u5DF2\u8FC7\uFF1A" : "\u4ECA\u5929\u5230\u8FBE" + label2 + "\uFF1A") + due);
      }
      if (!reasons.length) continue;
      const uncertain = unconfirmed(row);
      push(
        row,
        kind,
        uncertain || submitted && ["flowNodes", "milestones"].includes(kind) ? "confirmation" : submitted && !isBlocked(row) ? "acceptance" : "followup",
        uncertain ? ["\u8FD9\u6761\u8BB0\u5F55\u7684\u4E8B\u5B9E\u6216\u5224\u65AD\u5F85\u6838\u5BF9", ...reasons] : reasons,
        !uncertain && row.status === "\u9700\u8981\u5347\u7EA7\u534F\u8C03",
        submitted ? ["flowNodes", "milestones"].includes(kind) ? "\u6838\u5BF9\u8282\u70B9\u4F9D\u636E\u4E0E\u4EA4\u4ED8\u7269" : "\u6838\u5BF9\u6210\u679C\u4E0E\u9A8C\u6536" : "\u67E5\u770B\u5E76\u8DDF\u8FDB"
      );
      if (pendingResult && resultReview) {
        const item = attention.at(-1);
        item.summary = resultReview.resultReview.analysis?.summary || "\u6210\u679C\u7248\u672C\u5DF2\u8BFB\u53D6\uFF0C\u7B49\u5F85\u672C\u4EBA\u6838\u5BF9\u3002";
        item.sourceIds = [.../* @__PURE__ */ new Set([...item.sourceIds, resultReview.id])];
      }
    }
  }
  for (const row of unique5(s.cases || [])) {
    if (row.status === "\u5DF2\u5173\u95ED" && caseEvidenceChanged(s, row)) {
      push(row, "cases", "confirmation", ["\u5173\u95ED\u540E\u9A8C\u8BC1\u4F9D\u636E\u6709\u66F4\u65B0\uFF0C\u8BF7\u6838\u5BF9\u662F\u5426\u9700\u8981\u91CD\u65B0\u6253\u5F00"], false, "\u6838\u5BF9\u5DF2\u4FDD\u5B58\u7684\u9A8C\u8BC1\u7248\u672C");
      continue;
    }
    if (caseEvidenceChanged(s, row, "reportApproval")) {
      push(row, "cases", "confirmation", ["\u62A5\u544A\u5BA1\u6279\u4F9D\u636E\u6709\u66F4\u65B0\uFF0C\u8BF7\u6838\u5BF9\u5F53\u524D\u5BA1\u6279\u4E0E\u5DF2\u4FDD\u5B58\u7ED3\u8BBA"], false, "\u6838\u5BF9\u5BA1\u6279\u4F9D\u636E");
      continue;
    }
    if (row.status === "\u5DF2\u5173\u95ED" || row.myRole === "\u5173\u6CE8") continue;
    const reason = !row.owner ? "\u4E13\u9879\u8D1F\u8D23\u4EBA\u5F85\u660E\u786E" : row.status === "\u5F85\u6838\u9A8C" ? "\u4E13\u9879\u7B49\u5F85\u6838\u9A8C\u6574\u6539\u6548\u679C" : row.nextAction;
    if (reason) push(row, "cases", !row.owner || row.status === "\u5F85\u6838\u9A8C" ? "confirmation" : "followup", [reason], false, "\u6253\u5F00\u4E13\u9879\u5E76\u8DDF\u8FDB");
  }
  for (const row of unique5(s.risks).filter(eligible)) {
    const current = legacyRiskState(row);
    if (current.closed) continue;
    const confirmed = current.confirmed;
    push(row, "risks", confirmed ? "followup" : "confirmation", [confirmed ? "\u5DF2\u6709\u786E\u8BA4\u98CE\u9669\uFF1A" + (text13(row.impact) || "\u5F71\u54CD\u5F85\u8865\u5145") : "\u98CE\u9669\u4E8B\u5B9E\u6216\u5F71\u54CD\u5C1A\u5F85\u672C\u4EBA\u786E\u8BA4"], confirmed && row.impact === "\u9AD8", confirmed ? "\u67E5\u770B\u5E94\u5BF9\u4E0E\u8DDF\u8FDB" : "\u6838\u5BF9\u98CE\u9669\u4F9D\u636E");
  }
  for (const row of unique5(s.decisions).filter(eligible)) {
    if (closed3(row) || !["\u5F85\u51B3\u7B56", "\u6682\u7F13"].includes(row.status)) continue;
    const due = overviewDate(row.deadline), urgent = !!due && due <= date4 && !unconfirmed(row);
    push(row, "decisions", "confirmation", [urgent ? "\u5DF2\u5230\u6700\u665A\u51B3\u7B56\u65E5\u671F\uFF1A" + due : "\u9700\u8981\u672C\u4EBA\u6838\u5BF9\u65B9\u6848\u4E0E\u51B3\u5B9A"], urgent, "\u67E5\u770B\u51B3\u7B56\u4F9D\u636E");
  }
  const intakeStart = Date.parse("2026-09-28T13:47:33+08:00");
  for (const row of unique5(s.sources)) {
    if (row.workItem || row.managementSignal || row.riskEvidence || row.chatScope || row.subjectAssociation) continue;
    if (row.intakeBatch || row.intakeDocument) continue;
    if (workItemOwnsFeedback(s, row.id)) continue;
    if (row.collectedIntake && !row.collectedIntake.batchId && ["failed", "interrupted"].includes(row.collectedIntake.status)) {
      if (includeDataReview) push(row, "sources", "confirmation", ["\u91C7\u96C6\u8D44\u6599\u5C1A\u672A\u6574\u7406\uFF0C\u539F\u6587\u5DF2\u4FDD\u5B58\uFF0C\u53EF\u91CD\u8BD5"], false, "\u67E5\u770B\u91C7\u96C6\u8D44\u6599\u6574\u7406\u72B6\u6001");
      continue;
    }
    if (isMeetingContext(row)) {
      if (includeDataReview && meetingNeedsConfirmation(s, row)) push(row, "sources", "confirmation", ["\u4F1A\u8BAE\u7C7B\u578B\u6216\u9879\u76EE\u5F52\u5C5E\u5F85\u6838\u5BF9"], false, "\u67E5\u770B\u4F1A\u8BAE\u4E0E\u5F52\u5C5E\u4F9D\u636E");
      continue;
    }
    if (row.taskContext?.schemaVersion === 1) {
      if (row.taskContext.handling === "attention") push(row, "sources", "followup", ["\u8FD9\u9879\u4EFB\u52A1\u9700\u8981\u672C\u4EBA\u5904\u7406"], false, "\u67E5\u770B\u4EFB\u52A1\u4E0E\u8BF7\u6C42\u4F9D\u636E");
      continue;
    }
    if (isCommentFeedback(row)) {
      if (workItemOwnsFeedback(s, row.id)) continue;
      const f = row.feedback, a = f.analysis;
      if ((!f.observationOnly || a.viewerAction) && eligible(row) && a.status === "ready" && a.kind === "needs_confirmation" && a.contentVersion === f.contentVersion && f.reviewedVersion !== f.contentVersion) feedbackConcerns.set(f.targetId, [...feedbackConcerns.get(f.targetId) || [], row]);
      continue;
    }
    if ((row.caseIds || []).some((id2) => (s.cases || []).some((c) => c.id === id2 && !c.archived))) continue;
    if (ids7(row.projectIds).some((id2) => projectIds2.has(id2)) || ids7(row.objectIds).length || row.processingStatus === "\u5DF2\u6574\u7406") continue;
    const occurred = Date.parse(text13(row.occurredAt || row.collectedAt));
    if (!Number.isFinite(occurred) || occurred < intakeStart) continue;
    if (includeDataReview) push(row, "sources", "confirmation", ["\u65B0\u8D44\u6599\u5C1A\u672A\u786E\u8BA4\u9879\u76EE\u5F52\u5C5E"], false, "\u6838\u5BF9\u8D44\u6599\u5F52\u5C5E");
  }
  for (const group of s.changeGroups.filter((g) => ["pending", "partial", "conflict"].includes(g.status))) {
    if (group.aiTriageSourceIds?.length || !includeDataReview && isRoutineDataChange(group)) continue;
    const ops = group.operations.filter((op) => !op.status || op.status === "pending");
    if (!ops.length) continue;
    const affected = ops.flatMap((op) => op.kind === "projects" && projectIds2.has(op.targetId) ? [op.targetId] : ids7(op.after.projectIds).length ? ids7(op.after.projectIds) : ids7(s[op.kind].find((row2) => row2.id === op.targetId)?.projectIds));
    const row = { id: group.id, title: group.purpose || group.request || "\u5F85\u786E\u8BA4\u4FEE\u6539", projectIds: [...new Set(affected)], sourceIds: [...new Set(ops.flatMap((op) => op.sourceIds))], description: group.request };
    push(row, "changeGroups", "confirmation", [group.status === "conflict" ? "\u4FEE\u6539\u4E0E\u5F53\u524D\u53F0\u8D26\u6709\u51B2\u7A81\uFF0C\u9700\u8981\u6838\u5BF9" : `${ops.length} \u9879\u4FEE\u6539\u5C1A\u672A\u7531\u672C\u4EBA\u786E\u8BA4`], false, "\u5BA1\u6838\u5177\u4F53\u4FEE\u6539");
  }
  const deliveries = unique5(s.deliverables);
  const absorbed = /* @__PURE__ */ new Set();
  for (const item of attention.filter((item2) => item2.kind === "actions")) {
    const action = s.actions.find((row) => row.id === item.targetId);
    const matches = deliveries.filter((d2) => !closed3(d2) && d2.submissionStatus !== "\u514D\u4EA4\u4ED8" && ids7(d2.projectIds).some((id2) => item.projectIds.includes(id2)) && (ids7(action.outputIds).includes(d2.id) || ids7(d2.actionIds).includes(action.id)));
    if (matches.length !== 1) continue;
    const d = matches[0];
    let target = attention.find((candidate) => candidate.kind === "deliverables" && candidate.targetId === d.id);
    if (!target) {
      target = { ...item, id: "deliverables:" + d.id, targetId: d.id, kind: "deliverables", title: d.title, projectIds: ids7(d.projectIds).filter((id2) => projectIds2.has(id2)), owner: owner2(d), category: unconfirmed(d) || item.category === "confirmation" ? "confirmation" : "followup", next: "\u67E5\u770B\u4EA4\u4ED8\u7269\u53CA\u5173\u8054\u5DE5\u4F5C", summary: text13(d.deliverableProgress || d.description), reasons: [], sourceIds: ids7(d.sourceIds), relatedIds: [] };
      attention.push(target);
    }
    target.urgent = !unconfirmed(d) && (target.urgent || item.urgent);
    target.reasons = [.../* @__PURE__ */ new Set([...target.reasons, ...item.reasons.map((reason) => "\u5173\u8054\u5DE5\u4F5C\uFF1A" + reason)])];
    target.reason = target.reasons[0];
    target.sourceIds = [.../* @__PURE__ */ new Set([...target.sourceIds, ...item.sourceIds])];
    target.relatedIds.push(action.id);
    if (item.urgent || isBlocked(action)) {
      target.category = unconfirmed(d) || unconfirmed(action) ? "confirmation" : "followup";
      target.reason = "\u5173\u8054\u5DE5\u4F5C\uFF1A" + item.reason;
    }
    absorbed.add(item.id);
  }
  const actionable = attention.filter((item) => !absorbed.has(item.id));
  for (const [targetId, sources] of feedbackConcerns) {
    const originKind = sources[0].feedback.channel === "meegle-deliverable-comment" ? "deliverables" : "actions", ref = canonicalFollowupRef(s, { kind: originKind, targetId }), record2 = s[ref.kind].find((r) => r.id === ref.targetId);
    let item = actionable.find((item2) => item2.kind === ref.kind && item2.targetId === ref.targetId);
    if (!item) {
      push(record2 || sources[0], record2 ? ref.kind : "sources", "confirmation", ["\u53CD\u9988\u4E2D\u6709\u9700\u8981\u672C\u4EBA\u6838\u5BF9\u7684\u5185\u5BB9"], false, "\u67E5\u770B\u53CD\u9988\u539F\u6587");
      item = attention.at(-1);
      actionable.push(item);
    }
    item.feedbackSourceIds = sources.map((source) => source.id);
    item.sourceIds = [.../* @__PURE__ */ new Set([...item.sourceIds, ...sources.map((source) => source.id)])];
    if (!item.reasons.includes("\u53CD\u9988\u4E2D\u6709\u9700\u8981\u672C\u4EBA\u6838\u5BF9\u7684\u5185\u5BB9")) item.reasons.push("\u53CD\u9988\u4E2D\u6709\u9700\u8981\u672C\u4EBA\u6838\u5BF9\u7684\u5185\u5BB9");
  }
  for (const batch of unique5(s.sources).filter((src) => src.intakeBatch)) {
    const job = batch.intakeBatch, stale = intakeStaleDocuments(s, batch), current = (row) => !row.sourceId || !stale.includes(row.sourceId);
    const activeSignals = (job.signals || []).filter((signal, index) => !signal.workItemId && (!isRiskSignal(signal) || riskSignalState(s, batch, signal, index).open));
    const remainingRisks = activeSignals.filter(isRiskSignal);
    if (job.reviewedAt && (includeDataReview || !remainingRisks.length)) continue;
    const businessSignals = activeSignals.some(isBusinessIntakeSignal);
    const addIntake = (targetId, category, reason, urgent = false, business = false, verify = false) => {
      targetId = intakeCanonicalTarget(s, targetId);
      let item = actionable.find((a) => a.targetId === (targetId || batch.id) || targetId && a.relatedIds.includes(targetId));
      if (!item && !includeDataReview && !business) return;
      if (!item) {
        const target = intakeTargets(s).find((t) => t.id === targetId), record2 = target ? s[target.kind].find((r) => r.id === targetId) : batch;
        push(record2, target?.kind || "sources", category, [reason], urgent, "\u67E5\u770B\u8D44\u6599\u6574\u7406\u4F9D\u636E");
        item = attention.at(-1);
        actionable.push(item);
      }
      if (category === "confirmation" || item.category !== "confirmation") item.category = category;
      item.urgent ||= urgent;
      item.reason = reason;
      item.reasons = [.../* @__PURE__ */ new Set([reason, ...item.reasons])];
      item.sourceIds = [.../* @__PURE__ */ new Set([...item.sourceIds, batch.id])];
      item.relatedIds = [.../* @__PURE__ */ new Set([...item.relatedIds, batch.id])];
      if (verify) item.requiresVerification = true;
    };
    if (!includeDataReview && job.revertedAt && remainingRisks.length) {
      const verify = remainingRisks.some((signal) => riskSignalState(s, batch, signal, job.signals.indexOf(signal)).needsVerification);
      addIntake("", verify ? "confirmation" : "followup", verify ? "\u8BE5\u6279\u53CD\u9988\u66F4\u65B0\u5DF2\u64A4\u56DE\uFF0C\u98CE\u9669\u7591\u70B9\u9700\u8981\u91CD\u65B0\u6838\u5BF9" : "\u8BE5\u6279\u53CD\u9988\u66F4\u65B0\u5DF2\u64A4\u56DE\uFF0C\u5DF2\u6838\u5B9E\u98CE\u9669\u4ECD\u9700\u8DDF\u8FDB", false, true, verify);
      continue;
    }
    if (stale.length && stale.some((id2) => !intakeSourceWasReplaced(s, batch, id2))) addIntake("", "confirmation", "\u8D44\u6599\u6765\u6E90\u5DF2\u53D8\u5316\uFF0C\u5386\u53F2\u6574\u7406\u7ED3\u679C\u9700\u8981\u91CD\u65B0\u6838\u5BF9", false, businessSignals, businessSignals);
    if (["failed", "interrupted"].includes(job.status)) {
      if (stale.length && stale.every((id2) => intakeSourceWasReplaced(s, batch, id2))) continue;
      addIntake("", "confirmation", "\u8D44\u6599\u6574\u7406\u672A\u5B8C\u6210\uFF0C\u539F\u6587\u4E0E\u539F\u4EF6\u5DF2\u4FDD\u7559", false, businessSignals, businessSignals);
      continue;
    }
    if (!["ready", "partial"].includes(job.status)) continue;
    if (!job.reviewedAt && !job.revertedAt) {
      for (const update of [...job.autoUpdates || [], ...job.evidenceRefresh || []].filter(current)) if (actionable.some((item) => item.targetId === update.targetId || item.relatedIds.includes(update.targetId))) addIntake(update.targetId, "response", "\u539F\u8DDF\u8FDB\u4E8B\u9879\u5DF2\u6709\u76F8\u5173\u53CD\u9988\uFF0C\u5F85\u4F60\u6838\u5BF9");
    }
    if (!job.reviewedAt) for (const pending3 of (job.pending || []).filter(current)) addIntake(pending3.targetId, "confirmation", pending3.reason);
    if (!job.revertedAt) for (const signal of (job.reviewedAt ? remainingRisks : activeSignals).filter(current)) {
      if (signal.workItemId) continue;
      const review = isRiskSignal(signal) ? riskSignalState(s, batch, signal, job.signals.indexOf(signal)) : void 0;
      addIntake(signal.targetId, signal.kind === "followup" ? "followup" : "confirmation", (isRiskSignal(signal) ? review?.needsVerification ? "AI\u7591\u70B9\u5F85\u6838\u5B9E\uFF1A" : "\u5DF2\u6838\u5B9E\u98CE\u9669\uFF1A" : "") + signal.title, signal.urgency === "urgent", isBusinessIntakeSignal(signal), !!review?.needsVerification);
    }
    if (!job.reviewedAt && job.status === "partial" && !job.pending?.length) addIntake("", "confirmation", "\u672C\u6279\u8D44\u6599\u90E8\u5206\u8BFB\u53D6\uFF0C\u5C55\u5F00\u67E5\u770B\u672A\u8986\u76D6\u5185\u5BB9");
  }
  for (const kind of ["deliverables", "actions", "risks", "decisions", "cases"]) for (const row of unique5(s[kind] || [])) {
    const p = buildFollowup(s, { kind, targetId: row.id }, now2);
    if (p.kind !== kind || p.targetId !== row.id || !p.active || actionable.some((i) => i.kind === kind && i.targetId === row.id)) continue;
    if (!row.followupHandling && !p.pendingReply && !p.executionSourceIds.length && !p.nextCheckAt && !p.urgent) continue;
    push(row, kind, p.pendingReply ? "response" : "followup", [p.reason], p.urgent, "\u67E5\u770B\u5E76\u8DDF\u8FDB");
    actionable.push(attention.at(-1));
  }
  actionable.push(...workItemAttention(s, now2));
  const ranked2 = actionable.map((item) => {
    if (item.category !== "followup") return item;
    const sources = [...new Map([item.targetId, ...item.relatedIds].flatMap((id2) => pendingResponseSources(s, id2)).map((source) => [source.id, source])).values()];
    return sources.length ? { ...item, category: "response", reason: "\u5DF2\u6709\u76F8\u5173\u56DE\u590D\uFF0C\u5F85\u4F60\u6838\u5BF9", reasons: ["\u5DF2\u6709\u76F8\u5173\u56DE\u590D\uFF0C\u5F85\u4F60\u6838\u5BF9", ...item.reasons], feedbackSourceIds: [.../* @__PURE__ */ new Set([...item.feedbackSourceIds || [], ...sources.map((source) => source.id)])], sourceIds: [.../* @__PURE__ */ new Set([...item.sourceIds, ...sources.map((source) => source.id)])], next: "\u67E5\u770B\u539F\u8DDF\u8FDB\u8BB0\u5F55" } : item;
  }).map((item) => {
    if (item.kind === "changeGroups" || item.kind === "sources") return item;
    const p = buildFollowup(s, { kind: item.kind, targetId: item.targetId }, now2);
    return {
      ...item,
      itemKey: p.itemKey,
      handlingState: p.handlingState,
      nextCheckAt: p.nextCheckAt,
      waitingReason: p.waitingReason,
      primaryAction: p.primaryAction,
      followup: p,
      urgent: item.urgent || p.urgent,
      reason: p.reasons.length ? p.reason : item.reason,
      reasons: [.../* @__PURE__ */ new Set([...p.reasons, ...item.reasons])],
      sourceIds: [.../* @__PURE__ */ new Set([...item.sourceIds, ...p.sources.map((src) => src.id)])]
    };
  }).sort((a, b) => Number(b.urgent) - Number(a.urgent) || (a.date || "9999").localeCompare(b.date || "9999") || a.id.localeCompare(b.id));
  const waiting = ranked2.filter((i) => i.handlingState === "waiting" && !i.urgent), main = ranked2.filter((i) => !waiting.includes(i));
  const overview = projects.map((project) => {
    const summary = summaries.get(project.id);
    const nodes = unique5(s.flowNodes).filter((n) => ids7(n.projectIds).includes(project.id));
    const legacy = unique5(s.milestones).filter((n) => ids7(n.projectIds).includes(project.id) && !unconfirmed(n));
    const gateView = getProjectGates(s, project), gates = gateView.gates, nextGate = gateView.next;
    const acceptedGates = gates.filter((gate) => gate.accepted).map((gate) => gate.title);
    const items = main.filter((item) => item.kind !== "changeGroups" && item.projectIds.includes(project.id));
    const pendingGates = gates.filter((gate) => !gate.accepted);
    const gap = gateView.notice || (!nodes.length && !legacy.length ? "\u5C1A\u672A\u5F55\u5165\u6D41\u7A0B\u8282\u70B9\u6216\u91CC\u7A0B\u7891" : !gates.length ? "\u5173\u952E\u91CC\u7A0B\u7891\u5206\u7C7B\u5F85\u6838\u5BF9" : !nextGate && pendingGates.length ? "\u5F85\u9A8C\u6536\u5173\u53E3\u7684\u8BA1\u5212\u65E5\u671F\u5F85\u8865\u5145" : summary?.completedWithoutAcceptance ? `${summary.completedWithoutAcceptance} \u4E2A\u5DF2\u5B8C\u6210\u5173\u53E3\u7F3A\u5C11\u660E\u786E\u9A8C\u6536\u7ED3\u8BBA` : "");
    return { project, level: projectLevel(s, project), phase: gateView.phase, progress: summary?.progress || text13(project.projectProgress), owner: owner2(project), gates, gateView, nextGate, acceptedGates, gap, attention: items, urgent: items.filter((i) => i.urgent).length, nodeCount: nodes.length, deliverableCount: deliveries.filter((d) => ids7(d.projectIds).includes(project.id)).length };
  });
  return { projects: overview, attention: main, urgent: main.filter((item) => item.urgent), waiting, waitingCount: waiting.length, allAttention: ranked2, routine: overview.filter((p) => !p.attention.length), date: date4 };
}

// lib/risk-workflow.ts
function reconcileBusinessFollowups(s, at) {
  if (s.workspaceType === "restored") return false;
  let changed = false;
  const incoming = buildWorkbenchOverview(s, void 0, Date.parse(at), { includeDataReview: false }).allAttention.filter((item) => ["deliverables", "actions"].includes(item.kind));
  const targets = [...s.deliverables.filter((r) => r.riskTrackingItemId).map((r) => ({ kind: "deliverables", row: r })), ...s.actions.filter((r) => r.riskTrackingItemId).map((r) => ({ kind: "actions", row: r }))];
  for (const item of incoming) if (!targets.some((t) => t.row.id === item.targetId)) {
    const row = s[item.kind].find((r) => r.id === item.targetId);
    if (row && !row.workItemId) targets.push({ kind: item.kind, row });
  }
  for (const { kind, row } of targets) {
    if (row.archived || kind === "deliverables" && row.importedFrom?.system === "feishu" && !row.feishuFacts?.deliveryReview) continue;
    const sourceId = "business-signal-" + stableHash(kind + ":" + row.id), id2 = row.riskTrackingItemId || "business-followup-" + stableHash(kind + ":" + row.id);
    const facts = { kind, title: row.title, owner: row.owner || row.executor || "", plannedEnd: row.plannedEnd || row.dueAt || "", status: row.status || "", deliveryReview: kind === "deliverables" ? observedDeliveryReview(row) : "", nodeIds: row.flowNodeIds || [], progress: row.deliverableProgress || row.progressNote || "", blocker: row.blocker || "", rule: "\u5148\u5224\u65AD\u73B0\u5728\u662F\u5426\u6709\u5FC5\u8981\u63A8\u8FDB\uFF0C\u65E7\u9879\u76EE\u5386\u53F2\u8D44\u6599\u7F3A\u53E3\u4E0D\u8FFD\u8865\uFF1B\u5DF2\u5BA1\u6838\u662F\u5DE5\u7A0B\u5E08\u4EA4\u4ED8\u6807\u8BB0\u3002" };
    const excerpt = JSON.stringify(facts), old = s.sources.find((r) => r.id === sourceId), topic = s.sources.find((r) => r.id === id2 && r.workItem);
    if (old?.excerpt === excerpt) continue;
    const source = { id: sourceId, title: "\u4E1A\u52A1\u4E8B\u5B9E \xB7 " + row.title, projectIds: [...row.projectIds], sourceIds: row.sourceIds || [], objectIds: [row.id], excerpt, version: (old?.version || 0) + 1, collectedAt: at, occurredAt: at, createdAt: old?.createdAt || at, updatedAt: at, confirmed: false, riskEvent: { kind: "business-followup", targetKind: kind, targetId: row.id }, history: old ? [...old.history || [], { at: old.updatedAt, excerpt: old.excerpt }].slice(-30) : [] };
    if (old) Object.assign(old, source);
    else s.sources.push(source);
    if (!topic) {
      const association = row.caseId ? { kind: "case", id: row.caseId, confirmed: true, reason: "\u6CBF\u7528\u660E\u786E\u4E13\u9879" } : row.projectIds.length === 1 ? { kind: "project", id: row.projectIds[0], confirmed: true, reason: "\u6CBF\u7528\u4E1A\u52A1\u5DE5\u4F5C\u6240\u5C5E\u9879\u76EE" } : { kind: "unknown", id: "", confirmed: false, reason: "\u5F52\u5C5E\u9700\u8981\u6838\u5BF9" };
      applyWorkItemFindings(s, [{ id: id2, title: row.title, summary: incoming.find((i) => i.targetId === row.id)?.reason || "\u4E1A\u52A1\u5DE5\u4F5C\u6709\u53D8\u5316\uFF0C\u9700\u8981\u5224\u65AD\u662F\u5426\u8DDF\u8FDB", nextStep: "AI\u5148\u6838\u5BF9\u5FC5\u8981\u6027\u4E0E\u4E0B\u4E00\u6B65", nature: "action", urgency: "normal", sourceIds: [sourceId], association, businessTarget: { kind, id: row.id } }], at);
      const created = s.sources.find((r) => r.id === id2);
      created.workItem.provisional = true;
      created.workItem.nativeFollowup = true;
      row.riskTrackingItemId = id2;
      row.version++;
    } else if (kind === "deliverables" && deliveryRecorded(row) && row.flowNodeIds?.some((id3) => s.flowNodes.some((n) => n.id === id3 && !n.archived && n.projectIds.some((p) => row.projectIds.includes(p)))) && topic.workItem.nativeFollowup && topic.workItem.nature === "action" && !topic.workItem.human?.fields?.length) {
      const current = workItemState(s, topic, Date.parse(at));
      topic.workItem.handling = { state: "handled", basis: current.basis, evidenceBasis: current.liveEvidenceBasis, staleEvidenceBasis: current.staleEvidenceBasis, at, reason: "\u98DE\u4E66\u5DF2\u8BFB\u53D6\u5DE5\u7A0B\u5E08\u7684\u5DF2\u5BA1\u6838\u4EA4\u4ED8\u6807\u8BB0" };
      topic.workItem.history.push({ at, operation: "delivery-recorded", reason: "\u5DE5\u7A0B\u5E08\u5DF2\u4EA4\u4ED8\uFF0C\u7ED3\u675F\u672C\u6761\u4EA4\u4ED8\u8DDF\u8FDB\uFF1B\u6CA1\u6709\u4EE3\u66FF\u5185\u5BB9\u5BA1\u6838" });
      topic.version++;
      const core = ensureCore(topic);
      core.admission = core.admission === "candidate" ? "withdrawn" : core.admission;
      core.cycle.temp = null;
      core.need = { ...core.need, arranged: true, actor: "none" };
      topic.workItem.p1 ||= {};
      topic.workItem.p1.lifecycle = { state: "closed", owner: "auto", at, reason: "\u6709\u6548\u8282\u70B9\u5173\u8054\u53CA\u5DF2\u5BA1\u6838\u4EA4\u4ED8\u6807\u8BB0\u5DF2\u6838\u5B9E" };
      core.resultNotice = { id: coreDigest([topic.id, source.version, "delivered"]), at, text: core.admission === "withdrawn" ? "\u5DF2\u89E3\u51B3\uFF0C\u65E0\u9700\u7EB3\u5165" : "\u5DE5\u7A0B\u5E08\u4EA4\u4ED8\u5DF2\u8BB0\u5F55\uFF0C\u672C\u6761\u4EA4\u4ED8\u8DDF\u8FDB\u5DF2\u7ED3\u675F" };
    }
    changed = true;
  }
  return changed;
}

// lib/deliverable-documents.ts
var deliverableCarriers = {
  results: { key: "field_d06ce2", label: "\u6210\u679C\u6587\u6863" },
  templates: { key: "field_9eba44", label: "\u6A21\u677F\u53C2\u8003" },
  attachments: { key: "field_a38c57", label: "\u8865\u5145\u9644\u4EF6" },
  legacyTemplates: { key: "field_ba351a", label: "\u5386\u53F2\u6A21\u677F\u9644\u4EF6" }
};
var object9 = (v) => v && typeof v === "object" && !Array.isArray(v) ? v : {};
var text14 = (v) => typeof v === "string" ? v.trim() : "";
var own5 = (v, k) => Object.prototype.hasOwnProperty.call(v, k);
var fieldKeys = new Set(Object.values(deliverableCarriers).map((c) => c.key));
var date3 = (v) => Number.isFinite(Date.parse(v)) ? Date.parse(v) : 0;
function safeFeishuResource(value, attachment = false) {
  const raw = text14(value);
  if (!raw || raw.length > 6e3) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password || url.port || /[\u0000-\u0020]/.test(raw)) return null;
    const host = url.hostname.toLowerCase();
    if (attachment) return host === "project.feishu.cn" && /^\/goapi\/v\d+\/platform\/file\/stream\/download\/[A-Za-z0-9_-]+$/.test(url.pathname) ? { url: raw, type: "file", token: "" } : null;
    if (!(host === "feishu.cn" || host.endsWith(".feishu.cn") || host === "larksuite.com" || host.endsWith(".larksuite.com"))) return null;
    const match = url.pathname.match(/^\/(docx|wiki|docs|sheets|base|slides)\/([A-Za-z0-9_-]{5,200})\/?$/);
    return match ? { url: raw, type: match[1], token: match[2] } : null;
  } catch {
    return null;
  }
}
function rows(value) {
  if (value === null || value === "") return [];
  if (Array.isArray(value)) return value.flatMap(rows);
  if (typeof value === "string" && /^[\[{]/.test(value.trim())) {
    try {
      return rows(JSON.parse(value));
    } catch {
      return [value];
    }
  }
  return [value];
}
function parseCarrier(value, carrier) {
  const result = { state: "empty", items: [], rejected: 0, collectedAt: "", previous: false };
  if (value === void 0) return { ...result, state: "unread" };
  const attachment = carrier === "attachments" || carrier === "legacyTemplates";
  const seen = /* @__PURE__ */ new Set();
  for (const entry of rows(value)) {
    const row = object9(entry), url = safeFeishuResource(typeof entry === "string" ? entry : row.url || row.link || row.doc_url, attachment);
    if (!url) {
      result.rejected++;
      continue;
    }
    const identity = attachment ? url.url : url.type + ":" + url.token;
    if (seen.has(identity)) continue;
    seen.add(identity);
    const name = text14(row.name || row.title || row.label) || (attachment ? "\u672A\u547D\u540D\u9644\u4EF6" : deliverableCarriers[carrier].label);
    result.items.push({
      key: carrier + ":" + url.url,
      carrier,
      name,
      url: url.url,
      size: typeof row.size === "number" ? String(row.size) : text14(row.size),
      documentType: url.type,
      token: url.token,
      readable: attachment ? /\.(md|txt|csv|json|log)$/i.test(name) ? "text" : "" : ["docx", "wiki"].includes(url.type) ? "cloud" : "",
      sameAsTemplate: false
    });
  }
  result.state = result.items.length ? "ready" : result.rejected ? "invalid" : "empty";
  return result;
}
function rawFields(value, depth = 0) {
  if (depth > 4) return {};
  const raw = object9(value), fields = { ...rawFields(raw.raw, depth + 1) };
  for (const page of Array.isArray(raw.fieldPages) ? raw.fieldPages : []) Object.assign(fields, rawFields(page, depth + 1));
  for (const row of Array.isArray(raw.work_item_fields) ? raw.work_item_fields : []) {
    const field = object9(row), key2 = text14(field.key || field.field_key);
    if (fieldKeys.has(key2) && (own5(field, "value") || own5(field, "field_value"))) fields[key2] = own5(field, "value") ? field.value : field.field_value;
  }
  Object.assign(fields, object9(raw.fields));
  return fields;
}
function getDeliverableDocuments(s, record2) {
  const empty = () => ({ state: "unread", items: [], rejected: 0, collectedAt: "", previous: false });
  const result = { recordId: record2.id, remoteId: "", spaceKey: "", collectedAt: "", issue: "", carriers: { results: empty(), templates: empty(), attachments: empty(), legacyTemplates: empty() } };
  const candidates = s.externalObjects.filter((row) => row.workspaceId === s.workspaceId && row.localObjectId === record2.id && row.system === "meegle" && row.remoteKind === "deliverable" && row.host === "project.feishu.cn" && !["quarantined", "unmapped"].includes(row.mappingStatus));
  const identities = new Set(candidates.map((row) => row.spaceKey + ":" + row.remoteId));
  if (identities.size > 1) {
    result.issue = "\u4EA4\u4ED8\u7269\u5B58\u5728\u591A\u4E2A\u8FDC\u7AEF\u8EAB\u4EFD\uFF0C\u8BF7\u5148\u6838\u5BF9\u5173\u8054";
    return result;
  }
  const remote = candidates.sort((a, b) => date3(b.collectedAt) - date3(a.collectedAt))[0];
  let fields = {};
  const fieldDates = /* @__PURE__ */ new Map();
  if (remote) {
    if (remote.verificationStatus === "unverified") {
      result.issue = "\u8FDC\u7AEF\u4EA4\u4ED8\u7269\u5173\u8054\u5C1A\u672A\u6838\u9A8C";
      return result;
    }
    result.remoteId = remote.remoteId;
    result.spaceKey = remote.spaceKey;
    result.collectedAt = remote.collectedAt;
    if (remote.verificationStatus !== "verified") result.issue = "\u672C\u6B21\u6765\u6E90\u8BFB\u53D6\u672A\u5B8C\u6210\uFF0C\u4EE5\u4E0B\u4FDD\u7559\u4E0A\u6B21\u8BFB\u53D6\u5185\u5BB9";
    fields = rawFields(remote.raw);
    const known = s.remoteFieldValues.filter((row) => row.workspaceId === s.workspaceId && row.externalObjectId === remote.id).sort((a, b) => date3(a.collectedAt) - date3(b.collectedAt));
    for (const field of known) {
      fields[field.remoteFieldKey] = field.rawValue;
      fieldDates.set(field.remoteFieldKey, field.collectedAt);
    }
  } else {
    const meetingSource = s.sources.find((row) => row.id === record2.meetingSourceId && !row.archived), delivery = meetingSource?.meetingWorkflow?.delivery, document = record2.meetingDocument;
    if (delivery?.id === record2.id && delivery.remoteId === record2.meetingRemoteId && delivery.documentHash === document?.sha256 && typeof document?.content === "string" && safeFeishuResource(document.url)?.token === document.token) {
      const saved = parseCarrier({ url: document.url, name: document.title || record2.title }, "results");
      saved.items = saved.items.map((item) => ({ ...item, key: "results:meeting-snapshot:" + record2.id + ":" + document.sha256, readable: "snapshot" }));
      saved.collectedAt = document.readAt || meetingSource?.updatedAt || "";
      result.collectedAt = saved.collectedAt;
      result.carriers.results = saved;
      result.issue = "\u4F1A\u8BAE\u5F52\u6863\u65F6\u4FDD\u5B58\u7684\u7EAA\u8981\u7248\u672C\uFF1B\u5F53\u524D\u4E91\u6587\u6863\u53EF\u80FD\u5DF2\u6709\u66F4\u65B0\uFF0C\u6210\u679C\u9A8C\u6536\u4ECD\u987B\u5355\u72EC\u6838\u5BF9\u3002";
      return result;
    }
    const imported = object9(record2.importedFrom), remoteId = text14(imported.sourceId);
    if (!remoteId) return result;
    const source = s.sources.filter((row) => !row.archived && record2.sourceIds?.includes(row.id) && object9(row.importedFrom).sourceId === remoteId && object9(row.importedFrom).readonly === true).sort((a, b) => date3(text14(b.collectedAt)) - date3(text14(a.collectedAt)))[0];
    if (!source) return result;
    try {
      const envelope = JSON.parse(source.excerpt || "{}");
      if (String(envelope.sourceId) !== remoteId) return result;
      fields = rawFields(envelope);
      result.remoteId = remoteId;
      result.collectedAt = text14(source.collectedAt);
      result.spaceKey = text14(object9(envelope.raw).projectKey || object9(envelope.raw).spaceKey || object9(envelope.raw).project_key);
    } catch {
      return result;
    }
  }
  for (const [carrier, definition] of Object.entries(deliverableCarriers)) {
    if (!own5(fields, definition.key)) continue;
    const parsed = parseCarrier(fields[definition.key], carrier);
    parsed.collectedAt = fieldDates.get(definition.key) || result.collectedAt;
    parsed.previous = !!result.issue || date3(parsed.collectedAt) < date3(result.collectedAt);
    result.carriers[carrier] = parsed;
  }
  const templates = new Set(result.carriers.templates.items.map((item) => item.documentType + ":" + item.token));
  for (const item of result.carriers.results.items) item.sameAsTemplate = templates.has(item.documentType + ":" + item.token);
  return result;
}

// lib/task-context.ts
function taskRoles(task, userId) {
  return [...task.creator?.id === userId ? ["creator"] : [], ...(task.members || []).filter((m) => m.id === userId && ["assignee", "follower"].includes(m.role)).map((m) => m.role)];
}
var taskRoleLabels = { creator: "\u6211\u521B\u5EFA", assignee: "\u6211\u8D1F\u8D23", follower: "\u6211\u5173\u6CE8" };
function taskDefaultHandling(task, userId) {
  return taskRoles(task, userId).includes("assignee") && task.status !== "done" ? "attention" : "progress";
}
function isTaskContext(row) {
  return row.taskContext?.schemaVersion === 1;
}

// lib/meeting-workflow.ts
var meetingWorkflowLabels = {
  draft: "\u51C6\u5907\u4F1A\u524D\u6750\u6599",
  prepared: "\u5F85\u4F60\u5BA1\u9605",
  approved: "\u5DF2\u5BA1\u9605\uFF0C\u5F85\u6267\u884C",
  executing: "\u6267\u884C\u4E2D",
  partial: "\u90E8\u5206\u5B8C\u6210\uFF0C\u5F85\u7EED\u529E",
  unknown: "\u7ED3\u679C\u5F85\u6838\u5BF9",
  conflict: "\u4F9D\u636E\u5DF2\u53D8\u5316\uFF0C\u91CD\u65B0\u6838\u5BF9",
  scheduled: "\u65E5\u7A0B\u4E0E\u6750\u6599\u5DF2\u56DE\u8BFB",
  cancelled: "\u65E5\u7A0B\u5DF2\u53D6\u6D88\u5E76\u56DE\u8BFB",
  delivered: "\u7EAA\u8981\u5DF2\u5F52\u6863\u5E76\u56DE\u8BFB",
  restored: "\u6062\u590D\u7684\u4F1A\u8BAE\u5386\u53F2 \xB7 \u4E0D\u81EA\u52A8\u6267\u884C"
};
function meetingWorkflow(row) {
  return row.meetingWorkflow?.schemaVersion === 1 ? row.meetingWorkflow : void 0;
}
function meetingWorkflowProjection(s, sourceId) {
  const source = s.sources.find((r) => r.id === sourceId && !r.archived);
  const w = source && meetingWorkflow(source);
  if (!w) return null;
  const unfinished = Object.entries(w.execution?.steps || {}).filter(([, v]) => v.status !== "done");
  return {
    workspaceId: s.workspaceId,
    kind: "sources",
    id: sourceId,
    title: w.intent.title,
    projectId: w.intent.projectId,
    caseId: w.intent.caseId || "",
    mainNodeId: w.intent.mainNodeId,
    referenceNodeIds: w.intent.referenceNodeIds,
    label: meetingWorkflowLabels[w.status] || w.status,
    nextAction: w.status === "unknown" ? "\u56DE\u8BFB\u6838\u5BF9\u5916\u90E8\u7ED3\u679C" : w.status === "partial" ? "\u7EED\u529E\u672A\u5B8C\u6210\u6B65\u9AA4" : w.status === "prepared" ? "\u5BA1\u9605\u5177\u4F53\u9884\u89C8" : w.status === "scheduled" ? "\u4F1A\u540E\u6838\u5BF9\u7EAA\u8981\u4E0E\u8282\u70B9" : w.status === "delivered" ? "\u6309\u539F\u6D41\u7A0B\u8DDF\u8FDB\u884C\u52A8\u9879\u4E0E\u9A8C\u6536" : "\u7EE7\u7EED\u51C6\u5907",
    unfinished,
    event: w.event,
    minutesStatus: w.minutes?.status || "unread",
    delivery: w.delivery,
    // Scheduling, attendance, action items and node acceptance are independent.
    actualMeetingStatus: w.minutes?.meetingId ? "\u5DF2\u627E\u5230\u5B9E\u9645\u4F1A\u8BAE\u8EAB\u4EFD" : "\u5B9E\u9645\u53EC\u5F00\u60C5\u51B5\u672A\u6838\u5BF9"
  };
}

// lib/workbench-integration.ts
function integratedAttention(s, now2 = Date.now()) {
  const workflows = s.sources.filter((row) => row.meetingWorkflow && !row.archived);
  const groupIds = new Set(workflows.map((row) => row.meetingWorkflow.preview?.groupId).filter(Boolean));
  const capturedIds = new Set(s.sources.filter((row) => row.meetingContext?.workflowSourceId && workflows.some((w) => w.id === row.meetingContext.workflowSourceId)).map((row) => row.id));
  const items = buildWorkbenchOverview(s, void 0, now2, { includeDataReview: false }).allAttention.filter((item) => !groupIds.has(item.targetId) && !capturedIds.has(item.targetId));
  for (const source of workflows) {
    const projection = meetingWorkflowProjection(s, source.id);
    if (!projection) continue;
    const w = source.meetingWorkflow, waiting = w.status === "scheduled" && Date.parse(w.intent.end) > now2;
    const handled = ["delivered", "cancelled", "restored"].includes(w.status);
    items.push({
      id: "sources:" + source.id,
      targetId: source.id,
      kind: "sources",
      title: w.intent.title,
      projectIds: source.projectIds,
      caseId: w.intent.caseId || void 0,
      category: "confirmation",
      urgent: false,
      reason: projection.label,
      reasons: [projection.label],
      summary: "\u4F1A\u8BAE\u8D44\u6599\u3001\u65E5\u7A0B\u4E0E\u7EAA\u8981\u5728\u540C\u4E00\u4E8B\u9879\u6838\u5BF9\u3002",
      next: projection.nextAction,
      owner: "\u672C\u4EBA",
      date: w.intent.start,
      sourceIds: w.intent.sourceIds,
      relatedIds: [w.intent.mainNodeId, ...w.intent.referenceNodeIds].filter(Boolean),
      handlingState: handled ? "handled" : waiting ? "waiting" : "attention",
      nextCheckAt: waiting ? w.intent.end : void 0,
      waitingReason: waiting ? "\u7B49\u5F85\u4F1A\u8BAE\u7ED3\u675F\u540E\u6838\u5BF9\u7EAA\u8981" : void 0
    });
  }
  for (const source of s.sources.filter((row) => !row.archived && row.managementSignal)) {
    if (source.managementSignal.workItemId) continue;
    const c = managementSignalState(s, source);
    if (!c.open) continue;
    const kind = c.record && c.target ? c.target.kind : "sources", targetId = c.record && c.target ? c.target.id : source.id;
    const evidence = source.sourceIds.filter((id2) => s.sources.some((row) => row.id === id2));
    let item = items.find((row) => row.kind === kind && row.targetId === targetId);
    if (!item) {
      item = { id: kind + ":" + targetId, targetId, kind, title: c.record?.title || source.title, projectIds: kind === "projects" ? [targetId] : c.record?.projectIds || source.projectIds, category: c.review ? "followup" : "confirmation", urgent: false, reason: c.currentSummary, reasons: [c.currentSummary], summary: c.signal.summary, next: c.signal.nextStep, owner: c.record?.owner || "", date: c.record?.plannedEnd || "", sourceIds: [], relatedIds: [] };
      items.push(item);
    }
    if (kind === "cases") item.caseId = targetId;
    if (c.signal.triage && c.available && !c.stale) {
      item.urgent = item.urgent || c.signal.triage.urgency === "urgent";
      item.summary = c.signal.summary.split("\n\u5F85\u6838\u5B9E\uFF1A")[0] + "\n\u5F71\u54CD\uFF1A" + c.signal.triage.impact;
      item.reason = c.currentSummary.split("\n\u5F85\u6838\u5B9E\uFF1A")[0];
      item.next = c.signal.nextStep;
    }
    item.managementSourceIds = [...item.managementSourceIds || [], source.id];
    item.sourceIds = [.../* @__PURE__ */ new Set([...item.sourceIds, ...evidence])];
    item.relatedIds = [.../* @__PURE__ */ new Set([...item.relatedIds, source.id])];
    item.reasons = [.../* @__PURE__ */ new Set([...item.reasons, c.currentSummary])];
    if (!c.review) {
      item.category = "confirmation";
      item.requiresVerification = true;
      item.handlingState = "attention";
      if (!item.urgent) item.reason = c.signal.triage ? c.currentSummary.split("\n\u5F85\u6838\u5B9E\uFF1A")[0] : c.currentSummary;
    }
  }
  return [...items.filter((item) => item.urgent), ...items.filter((item) => !item.urgent)];
}
function integratedRecordItem(s, id2, items, forcedKind) {
  const linked = s.sources.find((row) => row.id === id2)?.managementSignal?.workItemId || s.sources.find((row) => row.id === id2)?.workItem?.mergedIntoId;
  if (linked && linked !== id2) return integratedRecordItem(s, linked, items, "sources");
  const signal = !forcedKind && s.sources.find((row) => row.id === id2 && !row.archived && row.managementSignal);
  if (signal) {
    const c = managementSignalState(s, signal);
    if (c.target && c.record) return integratedRecordItem(s, c.target.id, items, c.target.kind);
  }
  const existing = items.find((item) => item.targetId === id2 && (!forcedKind || item.kind === forcedKind));
  if (existing) return existing;
  const topic = s.sources.find((row) => row.id === id2 && row.workItem && !row.workItem.mergedIntoId);
  if (topic) return workItemRecordView(s, topic);
  if (s.changeGroups.some((group) => group.id === id2)) return buildWorkbenchOverview(s).allAttention.find((item) => item.kind === "changeGroups" && item.targetId === id2);
  const kind = forcedKind || v2Kinds.find((k) => s[k].some((row) => row.id === id2));
  if (!kind || !["projects", "flowNodes", "deliverables", "actions", "milestones", "risks", "decisions", "cases", "sources"].includes(kind)) return;
  const record2 = s[kind].find((row) => row.id === id2);
  const followup = !record2.archived && ["deliverables", "actions", "milestones", "cases"].includes(kind) ? buildFollowup(s, { kind, targetId: id2 }) : void 0;
  return {
    id: kind + ":" + id2,
    targetId: id2,
    kind,
    title: record2.title,
    projectIds: record2.projectIds,
    caseId: kind === "cases" ? id2 : record2.caseId,
    category: "followup",
    urgent: followup?.urgent || false,
    reason: followup?.reason || record2.nextAction || record2.followUp || "\u6838\u5BF9\u5F53\u524D\u8BB0\u5F55\u4E0E\u4F9D\u636E",
    reasons: followup?.reasons || [],
    summary: record2.description || record2.situation || "",
    next: record2.nextAction || record2.followUp || "\u67E5\u770B\u4F9D\u636E\u540E\u9009\u62E9\u4E0B\u4E00\u6B65",
    owner: record2.owner || "",
    date: record2.plannedEnd || record2.forecast || record2.expectedAt || "",
    sourceIds: record2.sourceIds || [],
    relatedIds: [],
    ...followup ? { followup, handlingState: followup.handlingState, nextCheckAt: followup.nextCheckAt, waitingReason: followup.waitingReason } : {}
  };
}

// lib/discovery-subjects.ts
function pendingDiscoverySubjects(s) {
  const live2 = s.sources.filter((source) => !source.archived && !source.subjectAssociation && !source.managementSignal);
  const signals = s.sources.filter((source) => !source.archived && ["agent", "dot"].includes(source.managementSignal?.origin)).map((source) => ({ source, ...managementSignalState(s, source) })).filter((entry) => !entry.signal.historical && !entry.target && (entry.signal.priority === "attention" || entry.signal.reviews.some((review) => review.decision === "confirmed")));
  const signalSources = new Set(signals.map((entry) => entry.signal.sourceId));
  const candidates = live2.filter((source) => (source.personalMessage?.channels?.includes("group-discovery") || signalSources.has(source.id)) && !inferredManagementTarget(s, source) && !sourceWorkItems(s, source.id).length);
  const members = /* @__PURE__ */ new Map();
  for (const source of live2) {
    const { key: key2 } = sourceSubjectIdentity(source);
    if (!members.has(key2)) members.set(key2, []);
    members.get(key2).push(source);
  }
  const groups = /* @__PURE__ */ new Map();
  for (const source of candidates) {
    const { key: key2 } = sourceSubjectIdentity(source);
    if (!groups.has(key2)) groups.set(key2, []);
    groups.get(key2).push(source);
  }
  return [...groups].map(([key2, seeds]) => {
    const sources = members.get(key2);
    const related2 = signals.filter((entry) => sources.some((source) => source.id === entry.signal.sourceId));
    const latest = [...seeds].sort((a, b) => String(b.occurredAt || b.collectedAt || "").localeCompare(String(a.occurredAt || a.collectedAt || "")))[0];
    const identity = sourceSubjectIdentity(latest), sourceIds = sources.map((row) => row.id).sort(), signalIds = related2.map((entry) => entry.source.id).sort();
    const basis = stableHash(JSON.stringify([key2, sources.map((source) => [source.id, source.version, inferredManagementTarget(s, source)]).sort(), related2.map((entry) => [entry.source.id, entry.source.version, entry.basis]).sort()]));
    return { key: key2, basis, title: (identity.chat ? latest.title : related2[0]?.signal.title || latest.title) || "\u65B0\u53D1\u73B0\u4E8B\u9879", summary: identity.chat ? "\u65B0\u53D1\u73B0\u7684\u7FA4\u804A\uFF0C\u6240\u5C5E\u9879\u76EE\u6216\u4E13\u9879\u5F85\u4F60\u786E\u8BA4\u3002" : related2[0]?.currentSummary || "\u6240\u5C5E\u9879\u76EE\u6216\u4E13\u9879\u5F85\u4F60\u786E\u8BA4\u3002", chat: identity.chat, sourceIds, signalIds, discoveredAt: sources.map((source) => String(source.personalMessage?.discovery?.discoveredAt || source.collectedAt || "")).sort()[0] || "" };
  }).sort((a, b) => a.discoveredAt.localeCompare(b.discoveredAt) || a.key.localeCompare(b.key));
}

// lib/workbench-statistics.ts
var unique6 = (rows2) => [...new Map(rows2.map((r) => [r.id, r])).values()];
var active4 = (r) => !r.archived && !r.mergedIntoId && !r.workItem?.mergedIntoId;
function workbenchStatistics(s, options = {}) {
  const now2 = options.now ?? Date.now(), q = options.query?.trim().toLocaleLowerCase() || "";
  const scoped = (r) => (!options.projectId || r.projectIds?.includes(options.projectId) || r.caseId === options.projectId) && (!q || r.title?.toLocaleLowerCase().includes(q));
  const sources = unique6(s.sources).filter(active4), allItems = sources.filter((r) => r.workItem);
  const refs = new Set(allItems.flatMap((r) => r.workItem.legacyRefs || []));
  const items = allItems.filter((r) => scoped({ ...r, caseId: r.workItem.association?.kind === "case" ? r.workItem.association.id : r.caseId }));
  const itemStates = items.map((row) => ({ row, state: workItemState(s, row, now2) }));
  const risks = [];
  for (const { row, state: c } of itemStates) {
    if (c.nature !== "risk") continue;
    const state = c.ignored ? "ignored" : c.review?.decision === "resolved" ? "resolved" : c.review?.decision === "dismissed" ? "dismissed" : c.needsVerification ? "pending" : c.review?.decision === "confirmed" ? "confirmed" : "pending";
    risks.push({ key: "sources:" + row.id, sourceId: row.id, title: row.title, projectIds: row.projectIds || [], caseId: c.item.association?.kind === "case" ? c.item.association.id : "", state, needsVerification: c.needsVerification });
  }
  const legacyTargets = new Set(allItems.filter((r) => r.workItem.nature === "risk" && r.workItem.businessTarget?.kind === "risks").map((r) => r.workItem.businessTarget.id));
  for (const row of unique6(s.risks).filter((r) => active4(r) && scoped(r) && !legacyTargets.has(r.id))) {
    const c = legacyRiskState(row), state = c.closed ? "resolved" : c.confirmed ? "confirmed" : "pending";
    risks.push({ key: "risks:" + row.id, sourceId: row.id, title: row.title, projectIds: row.projectIds || [], caseId: row.caseId || "", state, needsVerification: state === "pending" });
  }
  for (const row of sources) {
    const m = row.managementSignal;
    if (m && !m.workItemId && !refs.has(row.id) && !m.historical && (m.origin === "rule" || m.triage?.kind === "risk") && scoped(row)) {
      const c = managementSignalState(s, row);
      if (!c.open && !c.review) continue;
      const state = c.review?.decision === "resolved" ? "resolved" : c.review?.decision === "dismissed" ? "dismissed" : c.review?.decision === "confirmed" && !c.stale ? "confirmed" : "pending";
      risks.push({ key: "sources:" + row.id, sourceId: row.id, title: row.title, projectIds: row.projectIds || [], caseId: row.caseId || "", state, needsVerification: state === "pending" });
    }
    if (row.intakeBatch && !row.intakeBatch.revertedAt) for (const [index, signal] of (row.intakeBatch.signals || []).entries()) {
      if (signal.workItemId || refs.has(row.id + ":" + signal.id) || !isRiskSignal(signal)) continue;
      const c = riskSignalState(s, row, signal, index), target = [...s.projects, ...s.deliverables, ...s.actions, ...s.flowNodes, ...s.cases].find((r) => r.id === signal.targetId);
      const projectIds2 = target ? s.projects.includes(target) ? [target.id] : target.projectIds || [] : row.projectIds || [], caseId = target && s.cases.includes(target) ? target.id : target?.caseId || "";
      if (!scoped({ projectIds: projectIds2, caseId, title: signal.title })) continue;
      const state = c.review?.decision || "pending";
      risks.push({ key: "signal:" + c.key, sourceId: row.id, title: signal.title || row.title, projectIds: projectIds2, caseId, state, needsVerification: c.needsVerification });
    }
  }
  const riskRows = [...new Map(risks.map((r) => [r.key, r])).values()];
  const counts = { total: riskRows.length, open: 0, pending: 0, confirmed: 0, resolved: 0, dismissed: 0, ignored: 0 };
  for (const row of riskRows) counts[row.state]++;
  counts.open = counts.pending + counts.confirmed;
  const original = sources.filter((r) => !r.workItem && !r.intakeBatch && !r.managementSignal && !r.ruleBundle && !r.ruleCheck && !r.aiGenerated && !r.assistantAnswer && !r.chatScope && !r.subjectAssociation && scoped(r));
  return {
    schemaVersion: 1,
    items: { total: items.length, open: itemStates.filter((x) => !x.state.closed && !x.state.ignored).length, closed: itemStates.filter((x) => x.state.closed && !x.state.ignored).length, ignored: itemStates.filter((x) => x.state.ignored).length, actionable: itemStates.filter((x) => x.state.actionable && !x.state.closed && !x.state.ignored).length },
    sources: { records: unique6(s.sources).filter(active4).length, originals: new Set(original.map((r) => workSourceKey(s, r))).size },
    risks: counts
  };
}

// lib/work-item-dependencies.ts
function impactAwareness(proofs) {
  return proofs.some((proof) => {
    const clauses = proof.quote.split(/[。；\n]/);
    return clauses.some((clause, i) => {
      const text15 = clause + "\uFF1B" + (clauses[i + 1] || "");
      if (/(?:尚未|未|待|应该|需要|请|希望|可能|如果).{0,10}(?:知晓|知悉|了解|确认收到)/.test(text15)) return false;
      return /(?:影响|缺口|阻塞).{0,100}(?:已知晓|知晓并|知悉|确认收到|明确了解)|(?:已知晓|已知悉|已明确了解|确认收到).{0,100}(?:影响|缺口|阻塞)/.test(text15) || /acknowledged.{0,80}(?:impact|gap|blocker)|(?:impact|gap|blocker).{0,80}acknowledged/i.test(text15);
    });
  });
}
function evaluateDependency(s, w) {
  const gaps = [], edge = w.dependency;
  const answer = (status2, intervene, reason, extra = {}) => ({ status: status2, intervene, reason, gaps, dependencyId: edge?.id, ...extra });
  if (!edge || !edge.id || !edge.input || !edge.affectedWork || !edge.impact || edge.upstreamId === edge.downstreamId || !s.sources.some((r) => r.id === edge.upstreamId && r.workItem) || !s.sources.some((r) => r.id === edge.downstreamId && r.workItem) || !validCoreProofs(s, edge.proof)) return answer("unverified", false, "\u771F\u5B9E\u4F9D\u8D56\u5C1A\u672A\u6838\u5B9E\uFF1B\u76F8\u540C\u9879\u76EE\u3001\u6807\u9898\u6216\u8D23\u4EFB\u4EBA\u4E0D\u80FD\u8BC1\u660E\u4F9D\u8D56");
  if (w.readStatus !== "verified") return answer("unverified", false, "\u672C\u6B21\u5C1A\u672A\u5B8C\u6574\u6838\u5B9E\uFF1B\u4E0D\u80FD\u8BA4\u5B9A\u8D1F\u8D23\u4EBA\u672A\u63D0\u4F9B\u6216\u672A\u5171\u4EAB");
  if (edge.resolved) return answer("unblocked", false, "\u5171\u540C\u963B\u585E\u5DF2\u89E3\u9664\uFF1B\u4E0B\u6E38\u6309\u81EA\u8EAB\u5269\u4F59\u52A8\u4F5C\u7EE7\u7EED");
  const duration = w.duration, rangeValid = !!duration && Number.isFinite(duration.min) && Number.isFinite(duration.max) && duration.min >= 0 && duration.max >= duration.min && duration.unit === "hours" && !!duration.conditions && validCoreProofs(s, duration.proof);
  const shared = validCoreProofs(s, w.sharedProof), plan = w.planConfirmed && validCoreProofs(s, w.planProof);
  if (!rangeValid) gaps.push("\u6700\u77ED\u4E0E\u6700\u957F\u9884\u8BA1\u65F6\u957F\u5C1A\u672A\u6838\u5B9E");
  if (!shared) gaps.push("\u5C1A\u65E0\u65F6\u957F\u8303\u56F4\u5DF2\u5171\u4EAB\u7684\u6709\u6548\u4F9D\u636E");
  if (plan && gaps.length) return answer("needs-range", true, "\u5173\u952E\u6D4B\u8BD5\u8BA1\u5212\u5DF2\u786E\u8BA4\uFF0C\u8BF7\u63A8\u52A8\u660E\u786E\u5E76\u5171\u4EAB\u65F6\u957F\u8303\u56F4", { rangeExists: rangeValid, shared });
  const windowValid = Number.isFinite(w.availableHours) && w.availableHours !== null && w.availableHours >= 0 && !!w.calendarSource && validCoreProofs(s, w.windowProof);
  if (!windowValid) gaps.push("\u5F53\u524D\u6709\u6548\u53EF\u7528\u65F6\u95F4\u53CA\u65E5\u5386\u53E3\u5F84\u5C1A\u672A\u6838\u5B9E");
  const windowClosing = w.closingWindow && validCoreProofs(s, w.closingProof);
  if (!rangeValid || !windowValid || !duration.remaining) return answer(windowClosing ? "closing-window" : "needs-evidence", windowClosing, windowClosing ? "\u6709\u4F9D\u636E\u7684\u884C\u52A8\u7A97\u53E3\u6B63\u5728\u5173\u95ED\uFF0C\u8BF7\u53CA\u65F6\u4ECB\u5165\uFF1B\u7F3A\u53E3\u4ECD\u9700\u6838\u5B9E" : "\u8865\u67E5\u5F53\u524D\u5269\u4F59\u5FC5\u8981\u65F6\u957F\u53CA\u65F6\u95F4\u53E3\u5F84\uFF1B\u4E0D\u673A\u68B0\u6263\u51CF\u6700\u521D\u4F30\u8BA1");
  if (duration.min > w.availableHours) {
    const impossible = w.coordination === "impossible" && validCoreProofs(s, w.coordinationProof), known = w.knownByAffected && validCoreProofs(s, w.awarenessProof) && impactAwareness(w.awarenessProof);
    if (w.knownByAffected && !known) gaps.push("\u65F6\u957F\u8303\u56F4\u5171\u4EAB\u6216\u6D88\u606F\u5DF2\u53D1\u9001\uFF0C\u4E0D\u80FD\u66FF\u4EE3\u98CE\u9669\u5F71\u54CD\u5DF2\u88AB\u76F8\u5173\u4EBA\u660E\u786E\u77E5\u6653\u7684\u4F9D\u636E");
    const options = (w.options || []).filter((o) => o.title && o.impact && o.preconditions && validCoreProofs(s, o.proof));
    return answer(impossible ? known && !w.arrangementDecided ? "leader-decision" : "share-impact" : "coordinate", true, impossible ? known && !w.arrangementDecided ? "\u5F71\u54CD\u5DF2\u77E5\u6653\uFF0C\u5B89\u6392\u5C1A\u672A\u660E\u786E\uFF1B\u7531\u672C\u4EBA\u627E\u9886\u5BFC\u63A8\u52A8\u51B3\u5B9A" : "\u5DF2\u6838\u5B9E\u534F\u8C03\u4E0D\u80FD\u6D88\u9664\u7F3A\u53E3\uFF0C\u51C6\u5907\u5411\u53D7\u5F71\u54CD\u4EBA\u5458\u5171\u4EAB\u4E8B\u5B9E" : "\u5F53\u524D\u5269\u4F59\u6700\u77ED\u5FC5\u8981\u65F6\u957F\u8D85\u8FC7\u53EF\u7528\u65F6\u95F4\uFF0C\u9700\u8981\u672C\u4EBA\u534F\u8C03\u8D44\u6E90", {
      gapHours: duration.min - w.availableHours,
      brief: { blocker: edge.affectedWork, coordination: w.coordination === "impossible" ? "\u5DF2\u6838\u5B9E\u534F\u8C03\u4E0D\u80FD\u6D88\u9664\u7F3A\u53E3" : w.coordination === "possible" ? "\u4ECD\u6709\u53EF\u6838\u5B9E\u7684\u534F\u8C03\u7A7A\u95F4" : "\u5C1A\u672A\u8FDB\u884C\u8D44\u6E90\u534F\u8C03", impact: edge.impact, context: edge.input, window: "\u5269\u4F59\u6700\u77ED\u5FC5\u8981\u65F6\u957F " + duration.min + " \u5C0F\u65F6\uFF1B\u53EF\u7528 " + w.availableHours + " \u5C0F\u65F6\uFF1B\u7F3A\u53E3 " + Number((duration.min - w.availableHours).toFixed(6)) + " \u5C0F\u65F6", conditions: duration.conditions },
      options
    });
  }
  return answer(windowClosing ? "closing-window" : "observe", windowClosing, windowClosing ? "\u5176\u4ED6\u6709\u6548\u8BC1\u636E\u663E\u793A\u884C\u52A8\u7A97\u53E3\u6B63\u5728\u5173\u95ED\uFF0C\u9700\u53CA\u65F6\u4ECB\u5165" : "\u4ECD\u5B58\u5728\u6309\u65F6\u5B8C\u6210\u53EF\u80FD\uFF0C\u6301\u7EED\u5173\u6CE8\u5B9E\u9645\u8FC7\u7A0B\uFF1B\u5C1A\u672A\u5168\u90E8\u901A\u8FC7", { rangeExists: true, shared, availableHours: w.availableHours });
}
function saveDependencyWindow(s, row, w, at) {
  if (w.dependency.downstreamId !== row.id) throw Object.assign(Error("\u4F9D\u8D56\u76EE\u6807\u4E0E\u4E8B\u9879\u4E0D\u4E00\u81F4"), { status: 422 });
  const result = evaluateDependency(s, w), c = ensureCore(row);
  c.dependencies ||= [];
  const prior = c.dependencies.findIndex((x) => x.window.dependency.id === w.dependency.id);
  const value = { id: w.dependency.id, window: structuredClone(w), result, at, fingerprint: coreDigest(w) };
  if (prior < 0) c.dependencies.push(value);
  else c.dependencies[prior] = value;
  if (result.intervene) {
    const key2 = "dependency:" + w.dependency.id + ":" + result.status;
    if (c.need.key !== key2) {
      c.history.push({ at, kind: "dependency-need", previous: structuredClone(c.cycle), reason: result.reason });
      c.cycle = { id: coreDigest([row.id, key2, w]), needKey: key2, count: 0, epoch: c.cycle.epoch + 1, escalated: false, temp: null, notices: [] };
    }
    c.need = { key: key2, actor: "self", description: result.reason, arranged: false, remainingActions: [result.reason], at };
    c.dependencyUrgent = result.status === "closing-window";
  } else if (["unblocked", "observe"].includes(result.status) && c.need.key.startsWith("dependency:" + w.dependency.id + ":")) {
    c.need = { ...c.need, arranged: true, actor: "none", description: result.reason };
    c.cycle.temp = null;
    c.dependencyUrgent = false;
  }
  c.history.push({ at, kind: "dependency-evaluated", dependencyId: w.dependency.id, status: result.status });
  return result;
}
function recheckKnownDependencies(s, changedIds, at) {
  const affected = [];
  for (const row of s.sources.filter((r) => r.workItem && !r.archived)) {
    const c = row.workItem.core;
    if (!c?.dependencies) continue;
    for (const d of c.dependencies) {
      const edge = d.window.dependency;
      const serialized = JSON.stringify(d.window);
      if (!changedIds.some((id2) => edge.upstreamId === id2 || edge.downstreamId === id2 || serialized.includes(JSON.stringify(id2)))) continue;
      const result = evaluateDependency(s, d.window);
      d.result = result;
      d.at = at;
      c.checks = { ...c.checks, needsRecheck: true, reason: "\u76F8\u5173\u4F9D\u8D56\u4F9D\u636E\u53D1\u751F\u53D8\u5316" };
      c.history.push({ at, kind: "dependency-recheck", dependencyId: edge.id, status: result.status });
      if (!affected.includes(row.id)) affected.push(row.id);
    }
  }
  return affected;
}

// lib/work-item-collaboration.ts
function prepareDeliveryCollaboration(s, row, c) {
  const target = s.deliverables.find((d) => d.id === c.targetId && !d.archived), node = s.flowNodes.find((n) => n.id === c.nodeId && !n.archived);
  const base = { workItemId: row.id, targetId: c.targetId, nodeId: c.nodeId, projectIds: row.projectIds, proof: c.proof, fingerprint: coreDigest(c), messages: [], materials: [], gaps: [], decision: "", delivered: false };
  if (!target || !c.verified || !validCoreProofs(s, c.proof)) {
    base.gaps.push("\u771F\u5B9E\u4EA4\u4ED8\u7269\u53CA\u73B0\u884C\u8981\u6C42\u5C1A\u672A\u6838\u5B9E");
    return base;
  }
  if (!c.requirement?.trim()) {
    base.gaps.push("\u7F3A\u5C11\u9002\u7528\u4EA4\u4ED8\u8981\u6C42");
    return base;
  }
  if (c.requirementConflict && !validCoreProofs(s, c.exceptionProof)) {
    base.decision = "\u4EA4\u4ED8\u8981\u6C42\u51B2\u7A81\uFF0C\u8FDE\u540C\u53CC\u65B9\u4F9D\u636E\u4EA4\u672C\u4EBA\u5224\u65AD";
    return base;
  }
  if (c.responsibilityDisputed) {
    base.decision = "\u8D23\u4EFB\u5206\u5DE5\u5B58\u5728\u4E89\u8BAE\uFF0C\u8FDE\u540C\u5F53\u524D\u4F9D\u636E\u4E0E\u53CD\u9988\u4EA4\u672C\u4EBA\u534F\u8C03";
    return base;
  }
  if (!node || !row.projectIds.some((id2) => node.projectIds.includes(id2))) {
    base.decision = "\u5173\u8054\u8282\u70B9\u5C1A\u672A\u660E\u786E\uFF0C\u7531\u672C\u4EBA\u5224\u65AD\u5E76\u4EB2\u81EA\u5E2E\u52A9\u5173\u8054";
    return base;
  }
  if (c.templateUncertain) {
    base.decision = "\u6A21\u677F\u9002\u7528\u6027\u672A\u660E\u786E\uFF0C\u8BF7\u672C\u4EBA\u6309\u5DEE\u5F02\u4E0E\u4F9D\u636E\u9009\u62E9";
  }
  for (const template of c.templates || []) {
    const source = s.sources.find((x) => x.id === template.sourceId && !x.archived);
    if (source && (template.applicable || c.templateUncertain)) base.materials.push({ id: source.id, title: source.title, projectIds: source.projectIds, sourceIds: [source.id], reason: template.reason, role: c.templateUncertain ? "template-option" : "template" });
  }
  for (const id2 of c.materialSourceIds || []) {
    const source = s.sources.find((x) => x.id === id2 && !x.archived);
    if (source) base.materials.push({ id: id2, title: source.title, projectIds: source.projectIds, sourceIds: [id2], role: "reference" });
    else base.gaps.push("\u8D44\u6599\u6682\u4E0D\u53EF\u8BFB\uFF1A" + id2);
  }
  const linked = !!target.flowNodeIds?.includes(node.id), reviewValue = observedDeliveryReview(target);
  if (linked && reviewValue === "\u5DF2\u5BA1\u6838") {
    base.delivered = true;
    return base;
  }
  const person = (id2) => s.people.find((p) => p.id === id2 && !p.archived);
  const message = (recipientId, purpose, text15) => {
    const recipient = person(recipientId);
    if (!recipient) {
      base.gaps.push("\u63A5\u6536\u4EBA\u5C1A\u672A\u6838\u5B9E\uFF1A" + purpose);
      return;
    }
    base.messages.push({ id: coreDigest([row.id, c.targetId, purpose, recipientId]), title: target.title, projectIds: row.projectIds, sourceIds: c.proof.map((p) => p.sourceId), workItemId: row.id, targetId: c.targetId, nodeId: c.nodeId, recipientId, purpose, text: text15, channel: "private", requiresPreview: true });
  };
  if (c.accessDenied) {
    message(c.fileOwnerId, "access", "\u8BF7\u4E3A\u62A5\u544A\u8D23\u4EFB\u4EBA\u5F00\u653E\u300C" + target.title + "\u300D\u6240\u9700\u8D44\u6599\u7684\u8BBF\u95EE\u6743\u9650\u3002" + c.missing.join("\uFF1B"));
    return base;
  }
  if (c.missing?.length) {
    if (person(c.providerId)) message(c.providerId, "materials", "\u4E3A\u51C6\u5907\u300C" + target.title + "\u300D\uFF0C\u8BF7\u63D0\u4F9B\uFF1A" + c.missing.join("\uFF1B") + "\u3002\u73B0\u884C\u8981\u6C42\uFF1A" + c.requirement);
    else message(c.ownerCannotIdentifyProvider && validCoreProofs(s, c.providerLookupProof || []) ? c.teamOwnerId : c.ownerId, "provider", "\u300C" + target.title + "\u300D\u8FD8\u7F3A\uFF1A" + c.missing.join("\uFF1B") + "\u3002\u8BF7\u6838\u5B9E\u8FD9\u4E9B\u8D44\u6599\u7684\u5177\u4F53\u63D0\u4F9B\u65B9\u3002");
  } else if (!linked) message(c.ownerId, "link", "\u8BF7\u6309\u73B0\u884C\u8981\u6C42\u5C06\u300C" + target.title + "\u300D\u81EA\u884C\u5173\u8054\u5230\u300C" + node.title + "\u300D\u3002" + c.requirement);
  else if ((target.submissionStatus === "\u5DF2\u63D0\u4EA4" || c.submitted) && reviewValue !== "\u5DF2\u5BA1\u6838") message(c.ownerId, "review", "\u300C" + target.title + "\u300D\u5DF2\u63D0\u4EA4\uFF0C\u5F53\u524D\u4EA4\u4ED8\u5BA1\u6838\u5C1A\u672A\u56DE\u8BFB\u4E3A\u5DF2\u5BA1\u6838\uFF0C\u8BF7\u4F60\u63A8\u52A8\u76F8\u5E94\u5BA1\u6838\u3002");
  else if (!c.templateUncertain) message(c.ownerId, "prepare", "\u8BF7\u6309\u9002\u7528\u6A21\u677F\u548C\u5DF2\u63D0\u4F9B\u8D44\u6599\u7F16\u5199\u300C" + target.title + "\u300D\u3002" + c.requirement);
  return base;
}

// lib/core-reconcile.ts
function reconcileCoreLocals(s, at) {
  if (s.workspaceType === "restored") return false;
  let changed = false;
  for (const row of s.sources.filter((r) => r.workItem?.core && !r.archived)) {
    const c = row.workItem.core, before = JSON.stringify(c);
    if (c.assessment && !validCoreProofs(s, c.assessment.proof)) invalidateCoreDerivations(s, row, at, "\u5F53\u524D\u5F15\u7528\u5DF2\u7EA0\u6B63\u6216\u64A4\u56DE");
    if (c.delivery?.context) {
      const value = prepareDeliveryCollaboration(s, row, c.delivery.context), prior = Object.fromEntries(Object.entries(c.delivery).filter(([key2]) => !["context", "at"].includes(key2)));
      value.materials.push(...(c.delivery.materials || []).filter((m) => m.library));
      if (JSON.stringify(value) !== JSON.stringify(prior)) c.delivery = { ...value, context: c.delivery.context, at };
    }
    for (const dependency of [...c.dependencies || []]) {
      const result = evaluateDependency(s, dependency.window);
      if (JSON.stringify(result) !== JSON.stringify(dependency.result)) {
        saveDependencyWindow(s, row, dependency.window, at);
        c.checks = { ...c.checks, needsRecheck: true, reason: "\u5DF2\u6838\u5B9E\u4F9D\u8D56\u7684\u4F9D\u636E\u53D1\u751F\u53D8\u5316" };
      }
    }
    if (JSON.stringify(c) !== before) {
      row.version++;
      row.updatedAt = at;
      changed = true;
    }
  }
  for (const source of s.sources.filter((r) => r.reminderRun?.core && !r.archived)) {
    let updated = false;
    for (const m of source.reminderRun.items) {
      if (["sending", "unknown", "sent", "readback_verified", "cancelled", "stopped"].includes(m.stage)) continue;
      const row = s.sources.find((r) => r.id === m.workItemId && r.workItem && !r.archived), c = row?.workItem.core;
      if (!row) continue;
      const done = c?.delivery?.targetId === m.targetId && c.delivery.delivered && validCoreProofs(s, c.delivery.proof) || row.workItem.p1?.lifecycle?.state === "closed" && c?.assessment?.goalSatisfied && validCoreProofs(s, c.assessment.proof);
      const stale = !validCoreProofs(s, m.proof);
      const stage = done ? "stopped" : stale || row.workItem.p1?.lifecycle?.state === "closed" ? "needs_preview" : m.stage;
      if (stage === m.stage) continue;
      m.stage = stage;
      m.events.push({ at, kind: stage, reason: done ? "\u53EF\u9760\u65B0\u4E8B\u5B9E\u5DF2\u4F7F\u672C\u6761\u534F\u4F5C\u65E0\u5FC5\u8981" : "\u76F8\u5173\u539F\u6587\u5DF2\u53D8\u5316\uFF0C\u4FDD\u7559\u539F\u6279\u51C6\u5E76\u91CD\u65B0\u5B8C\u6574\u9884\u89C8" });
      updated = true;
    }
    if (updated) {
      source.reminderRun.messages = structuredClone(source.reminderRun.items);
      source.version++;
      source.updatedAt = at;
      changed = true;
    }
  }
  return changed;
}
export {
  addDays,
  adoptFeishuFacts,
  adoptRiskPolicy,
  applyCaseCommand,
  applyCoreDecision,
  applyEntryChanges,
  applyFeedbackAnalysis,
  applyFollowupOperation,
  applyIntakeAnalysis,
  applyNeedAssessment,
  applySourceSubjectAssociation,
  applyWeeklyReviewCommand,
  applyWorkItemFindings,
  applyWorkItemOperation,
  approvalStatusLabel,
  approveSyncPreparation,
  briefLabels,
  buildDispatchPreview,
  buildFollowup,
  buildThreeWayDiff,
  buildWeeklyReviewView,
  buildWorkbenchOverview,
  canWriteBack,
  canonicalFollowupRef,
  caseDateKinds,
  caseEvidenceAvailable,
  caseEvidenceChanged,
  caseProtectedFields,
  caseRoles,
  caseSources,
  caseStateErrors,
  caseStatuses,
  caseWorkDone,
  caseWorks,
  chatFiles,
  chinaDay,
  chinaInstant,
  chinaTime,
  collaborationSummary,
  collectedLimitations,
  collectedMaterial,
  collectedText,
  combineEntry,
  compareRemoteLocal,
  compareThreeWay,
  comparisonPoint,
  connectLegacyWorkItems,
  coreDigest,
  coreNotice,
  coreProofFingerprint,
  coreReopenProposal,
  coreState,
  coreTemporalTrigger,
  countCoreNotice,
  deliverableCarriers,
  deliverableReviews,
  deliverableStatuses,
  deliveryRecorded,
  demoState,
  editDraft,
  effectivePriority,
  emptyState,
  ensureCore,
  ensureReviewedWriteback,
  entryPatches,
  entryReceipts,
  evaluateCoreRule,
  evaluateDependency,
  externalObjectIdentity,
  feedbackCandidates,
  feedbackCollectFrom,
  feedbackRelated,
  feedbackTarget,
  feedbackTime,
  feishuFieldMap,
  followupContext,
  followupDay,
  followupFingerprint,
  followupItemKey,
  followupSignature,
  forecastVariance,
  gateDate,
  getDeliverableDocuments,
  getLegacyLink,
  getProjectGates,
  graphEdges,
  groundedForecast,
  hasSyncConflicts,
  hasTimeOverride,
  hydrateStateCollections,
  inferredManagementTarget,
  ingestCommentFeedback,
  intakeActive,
  intakeCanonicalTarget,
  intakeProgressField,
  intakeSignalMatches,
  intakeSourceWasReplaced,
  intakeStaleDocuments,
  intakeTargetKinds,
  intakeTargets,
  integratedAttention,
  integratedRecordItem,
  invalidateCoreDerivations,
  isCommentFeedback,
  isMeetingContext,
  isRiskSignal,
  isTaskContext,
  itemManagementSignals,
  itemRiskSignals,
  itemTiming,
  kindOf,
  lastWorkdayOfWeek,
  analyzeMock as legacyAnalyzeMock,
  answerMock as legacyAnswerMock,
  prepareSource as legacyPrepareSource,
  lookupV2,
  managementSignalState,
  managementTargets,
  manualEdit,
  markViewed,
  materialSourceContentKey,
  materialSourceIdentityKey,
  meetingKinds,
  meetingNeedsConfirmation,
  meetingTime,
  meetingWorkflow,
  meetingWorkflowLabels,
  meetingWorkflowProjection,
  mergeFeishuRead,
  minutesLabels,
  nextWorkMorning,
  normalizeDeliverableMigration,
  normalizeProjectMigration,
  normalizeState,
  normalizeTime,
  observedDeliveryReview,
  ownerAssignments,
  ownerChart,
  parseCarrier,
  parseSummaryBrief,
  pendingDiscoverySubjects,
  pendingResponseSources,
  planTemplates,
  prepareDeliveryCollaboration,
  prepareSyncRun,
  prepareWriteback,
  projectTime,
  receiptProgressId,
  recheckKnownDependencies,
  reconcileBusinessFollowups,
  reconcileCoreLocals,
  reconcileCoreReopenProposal,
  recordDispatchPreparation,
  recordSyncPreparation,
  registerRemoteSnapshot,
  registryCollections,
  report,
  resolveFeishuConflict,
  resumeDuePause,
  reuseCollectedFeedback,
  reviewCommentFeedback,
  reviewDraft,
  riskSignalState,
  ruleOwner,
  ruleProjectScope,
  safeFeishuResource,
  safeFeishuUrl,
  saveDependencyWindow,
  shanghaiDay,
  sourceSubjectIdentity,
  sourceWorkItems,
  subjectAssociationTarget,
  submitDraft,
  suggestedWeights,
  taskDefaultHandling,
  taskFeedbackLinks,
  taskRoleLabels,
  taskRoles,
  threeWayDiff,
  timeLabel,
  undo,
  undoEntry,
  validCoreProofs,
  validDay,
  validateDraft,
  validateManagementTarget,
  validateMappingRegistry,
  validateState,
  validateWorkCalendar,
  weeklyDelivery,
  weeklyScopeKey,
  weeklyStateErrors,
  weeklyStore,
  weightedProgress,
  workEvidenceSources,
  workItemAttention,
  workItemBrief,
  workItemCandidates,
  workItemFollowup,
  workItemLabels,
  workItemNatures,
  workItemOwnsFeedback,
  workItemRecordView,
  workItemState,
  workSourceFingerprint,
  workSourceKey,
  workSourceOriginal,
  workbenchStatistics,
  workingDay
};
//# sourceMappingURL=domain.mjs.map
