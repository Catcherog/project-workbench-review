"""Document state in the existing SQLite store. Business permissions stay server-owned."""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from .config import BoundaryError
from .doc_logic import (read_source, digest, build_prompt, parse_json, validate_analysis,
                        semantic_prompt, validate_semantics, render, MAX_BYTES, apply_program_findings)
from .store import scope_of
from .provider import Result

WORKFLOW_SHA256 = digest(Path(__file__).read_bytes())

SCHEMA = """
CREATE TABLE IF NOT EXISTS logic_drafts (
 id TEXT PRIMARY KEY, scope TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL,
 document_type TEXT NOT NULL, sources TEXT NOT NULL, answers TEXT NOT NULL,
 analysis TEXT, review TEXT, rules TEXT, content TEXT, content_hash TEXT, accepted_hash TEXT,
 target TEXT, expires REAL NOT NULL, stage INTEGER NOT NULL DEFAULT 0, error TEXT
);
CREATE INDEX IF NOT EXISTS logic_scope ON logic_drafts(scope,expires);
CREATE TABLE IF NOT EXISTS logic_jobs (
 task_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, revision INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS logic_receipts (
 inbox_seq INTEGER PRIMARY KEY, outbox_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS logic_writes (
 idem TEXT PRIMARY KEY, draft_id TEXT NOT NULL, revision INTEGER NOT NULL,
 target TEXT NOT NULL, content_hash TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT
);
"""
HELP = ("逻辑整理：/doc logic 8d 内容，或 /doc logic test 内容。也可先选文种后发 TXT、Markdown、HTML 文件。"
        "直接回复可补充同一稿；/doc 阶段稿、/doc 暂停、/doc 继续、/doc 采用、/doc 放弃。"
        "生成附件仅发本人。挂载需先选择可用目标，以实际回执为准。")

class MissingBusiness:
    """Fail explicitly: no invented project, platform receipt, approval or remote URL."""
    def resolve(self, principal, target_id):
        raise BoundaryError("BUSINESS_CONNECTION_UNAVAILABLE")
    def sources(self, principal, target):
        raise BoundaryError("BUSINESS_CONNECTION_UNAVAILABLE")
    def commit(self, principal, target, content, content_hash, idem, guard):
        raise BoundaryError("BUSINESS_CONNECTION_UNAVAILABLE")
    def reconcile(self, principal, idem):
        raise BoundaryError("BUSINESS_CONNECTION_UNAVAILABLE")

class LogicService:
    def __init__(self, gateway, business=None):
        self.g, self.s = gateway, gateway.store
        from .meegle_port import load_meegle_port
        self.business = business or MissingBusiness()
        if business is None:
            try:
                self.business = load_meegle_port(gateway) or MissingBusiness()
                self.s.set_meta("business_error", "")
            except (BoundaryError, KeyError, TypeError, OSError, ValueError):
                self.s.set_meta("business_error", "BUSINESS_CONNECTION_UNAVAILABLE")
        with self.s.lock:
            self.s.conn.executescript(SCHEMA)

    def current(self, row):
        items = self.s.rows("SELECT * FROM logic_drafts WHERE scope=? AND expires>? ORDER BY rowid DESC LIMIT 1",
                            (scope_of(row), self.s.clock()))
        return items[0] if items else None

    def get(self, row, draft_id):
        items = self.s.rows("SELECT * FROM logic_drafts WHERE id=? AND scope=? AND expires>?",
                            (draft_id, scope_of(row), self.s.clock()))
        if not items or not self.g.authorized(row):
            raise BoundaryError("LOGIC_SCOPE_DENIED")
        return items[0]

    def observe_ingress(self, conn, row, expires):
        """Called in the durable receipt transaction. Supersede before slow work returns."""
        if not self.g.config.document_logic:
            return
        body = row.get("body") or ""
        sel = conn.execute("SELECT route FROM selection WHERE scope=? AND expires>?", (scope_of(row), self.s.clock())).fetchone()
        current = conn.execute("SELECT id FROM logic_drafts WHERE scope=? AND expires>? ORDER BY rowid DESC LIMIT 1", (scope_of(row), self.s.clock())).fetchone()
        relevant = body.startswith("/doc logic") or row.get("kind") == "file" or (
            current and sel and sel[0] == "doc" and (body.startswith("/doc ") or not body.startswith("/")))
        if body in ("sample", "/doc sample") or not relevant:
            return
        # Receipt is in the same transaction as inbox insertion. Delivery still performs
        # the original live identity/department checks, before any document work.
        seq = conn.execute("SELECT seq FROM inbox WHERE app=? AND tenant=? AND event_id=?", (row["app"], row["tenant"], row["event_id"])).fetchone()[0]
        outbox = self.s.add_outbox(dict(row, expires=expires), text="已收到，正在核验权限与资料。", private=True, conn=conn)
        conn.execute("INSERT INTO logic_receipts VALUES (?,?)", (seq, outbox))
        if body in ("/doc 采用", "/doc adopt", "/doc 挂载", "/doc mount", "/doc 对账") or body.startswith("/doc target "):
            return
        state = "cancelled" if body in ("/doc 放弃", "/doc discard") else "paused" if body in ("/doc 暂停", "/doc pause") else "dirty"
        draft = conn.execute("SELECT id,state FROM logic_drafts WHERE scope=? AND expires>? AND state!='cancelled' ORDER BY rowid DESC LIMIT 1",
                             (scope_of(row), self.s.clock())).fetchone()
        if draft:
            if draft[1] == "paused" and body not in ("/doc 继续", "/doc resume", "/doc 阶段稿", "/doc stage", "/doc 放弃", "/doc discard") and not body.startswith("/doc logic"):
                return
            conn.execute("UPDATE logic_drafts SET revision=revision+1,state=?,accepted_hash=CASE WHEN ? IN ('paused','cancelled') THEN NULL ELSE accepted_hash END WHERE id=?", (state, state, draft[0]))
            conn.execute("UPDATE outbox SET state='rejected',error='DRAFT_SUPERSEDED' WHERE task_id IN "
                         "(SELECT task_id FROM logic_jobs WHERE draft_id=?) AND state='pending'", (draft[0],))

    def notify(self, row, text):
        self.s.add_outbox(row, text=text, private=True)

    def create(self, row, kind):
        draft = uuid.uuid4().hex
        with self.s.tx() as c:
            c.execute("UPDATE logic_drafts SET state='cancelled',revision=revision+1,accepted_hash=NULL WHERE scope=? AND state!='cancelled'",
                      (scope_of(row),))
            c.execute("INSERT INTO logic_drafts(id,scope,revision,state,document_type,sources,answers,expires) VALUES(?,?,1,'collecting',?,'[]','{}',?)",
                      (draft, scope_of(row), kind, row["expires"]))
        return self.get(row, draft)

    def add_source(self, row, draft, name, data, *, limitation=None):
        sources = json.loads(draft["sources"])
        if len(sources) >= 12:
            raise BoundaryError("LOGIC_SOURCE_LIMIT")
        source = read_source(name, data, source_id=f"S{len(sources)+1:02d}",
                             origin=row.get("message_id"), formed_at=None)
        if limitation:
            source.update(read_status="failed", limitation=limitation, segments=[], version=None, version_reason="文件读取失败，未获得内容指纹")
        if source["version"] is not None and any(s["version"] == source["version"] and s["name"] == source["name"] for s in sources):
            return False
        if sum(len(p["original"]) for s in sources + [source] for p in s["segments"]) > 12000:
            raise BoundaryError("LOGIC_INPUT_LIMIT")
        sources.append(source)
        answers = json.loads(draft["answers"])
        if draft["analysis"] and name == "补充.txt":
            questions = json.loads(draft["analysis"])["questions"]
            # Exact answer plus original question retained. No inferred factual answer.
            for q in questions:
                answers[q["key"]] = {"question": q["ask"], "reply_source": source["id"], "reply": data.decode("utf-8")}
        self.s.execute("UPDATE logic_writes SET target='{}',receipt=NULL WHERE draft_id IN (SELECT id FROM logic_drafts WHERE expires<=?)", (self.s.clock(),))
        self.s.execute("UPDATE logic_drafts SET sources=?,answers=?,revision=revision+1,state='collecting',"
                       "accepted_hash=NULL,expires=MIN(expires,?),error=NULL WHERE id=?",
                       (json.dumps(sources, ensure_ascii=False), json.dumps(answers, ensure_ascii=False), row["expires"], draft["id"]))
        if source["read_status"] != "complete":
            self.notify(row, "资料已记录：" + (source["limitation"] or "部分读取"))
        return True

    def queue(self, row, draft):
        receipts = self.s.rows("SELECT outbox_id FROM logic_receipts WHERE inbox_seq=?", (row["seq"],))
        task_id = self.s.enqueue(row, "doc", acknowledgement=not bool(receipts))
        self.s.execute("INSERT OR IGNORE INTO logic_jobs VALUES(?,?,?)", (task_id, draft["id"], draft["revision"]))
        if receipts:
            self.s.execute("UPDATE outbox SET task_id=? WHERE id=?", (task_id, receipts[0]["outbox_id"]))
        else:
            self.s.execute("UPDATE outbox SET body=? WHERE task_id=? AND kind='text' AND state='pending'",
                           ("已收到，正在整理；完成后交付候选稿、来源和待确认项。", task_id))
        return task_id

    def handle(self, row, argument, *, file=False):
        draft = self.current(row)
        parts = argument.split(maxsplit=2)
        if parts and parts[0] == "logic":
            kind = parts[1] if len(parts) > 1 else "8d"
            if kind not in ("8d", "test"):
                self.notify(row, HELP); return
            draft = self.create(row, kind)
            if len(parts) < 3:
                self.notify(row, "已开始" + ("测试报告" if kind == "test" else "异常分析") + "整理，请发送文字或 TXT、Markdown、HTML 文件。")
                return
            argument = parts[2]
        elif draft is None:
            self.notify(row, HELP); return
        elif argument in ("放弃", "discard"):
            self.cancel(row, draft["id"]); return
        elif argument in ("暂停", "pause"):
            self.s.execute("UPDATE logic_drafts SET state='paused',revision=revision+1,accepted_hash=NULL WHERE id=?", (draft["id"],))
            self.notify(row, "已暂停本稿，已有资料保留到原有效期。"); return
        elif argument in ("采用", "adopt"):
            self.adopt(row, draft["id"]); self.notify(row, "已记录采用当前文字；尚未挂载，不代表专业审核或节点完成。"); return
        elif argument.startswith("target "):
            self.select_target(row, draft["id"], argument.split(maxsplit=1)[1])
            current = self.get(row, draft["id"])
            if current["state"] == "collecting" and current["sources"] != "[]":
                self.queue(row, current)
            self.notify(row, "已选择目标，保存时仍会核对修订。"); return
        elif argument == "对账":
            self.notify(row, self.reconcile_draft(row, draft["id"])); return
        elif argument in ("挂载", "mount"):
            result = self.mount(row, draft["id"])
            message = result["message"]
            if result.get("receipt"):
                message += "\n查看已挂载的交付物：" + result["receipt"]["url"]
            self.notify(row, message); return
        elif argument in ("继续", "resume", "阶段稿", "stage"):
            if draft["state"] == "cancelled":
                raise BoundaryError("LOGIC_DRAFT_CANCELLED")
            stage = argument in ("阶段稿", "stage")
            if stage and draft["stage"] and draft["content"]:
                self.s.execute("UPDATE logic_drafts SET state='ready' WHERE id=?", (draft["id"],))
                self.notify(row, "已有阶段稿仍有效；没有新资料，不重复生成。")
                return
            self.s.execute("UPDATE logic_drafts SET state='collecting',stage=?,revision=revision+1,accepted_hash=NULL WHERE id=?",
                           (int(stage), draft["id"]))
            self.queue(row, self.get(row, draft["id"])); return
        elif draft["state"] == "cancelled":
            self.notify(row, "本稿已放弃；用 /doc logic 8d 或 /doc logic test 开始新稿。"); return
        elif draft["state"] == "paused":
            self.notify(row, "本稿已暂停；用 /doc 继续 恢复。"); return
        if file:
            info = json.loads(row["body"])
            try:
                data = self.g.api.read_file(row, info["file_key"], lambda: self.g.authorized(row), limit=MAX_BYTES)
                changed = self.add_source(row, draft, info["file_name"], data)
            except BoundaryError as exc:
                # Persist the specific unread source, so failure never becomes "not provided".
                self.add_source(row, draft, info["file_name"], b"", limitation="已提供文件，读取暂失败：" + str(exc))
                self.notify(row, "文件暂不可读，已保留本稿；可重发这一份文件或先形成阶段稿。")
                return
        else:
            if not argument.strip():
                self.notify(row, HELP); return
            changed = self.add_source(row, draft, "补充.txt" if draft["sources"] != "[]" else "输入.txt", argument.encode())
        if not changed:
            if draft["content"]:
                self.s.execute("UPDATE logic_drafts SET state='ready' WHERE id=?", (draft["id"],))
                self.notify(row, "这份内容已记录，继续使用已有候选稿；不重复生成或追问。")
            else:
                self.queue(row, self.get(row, draft["id"]))
            return
        self.queue(row, self.get(row, draft["id"]))

    def generate(self, task, started):
        jobs = self.s.rows("SELECT * FROM logic_jobs WHERE task_id=?", (task["id"],))
        if not jobs:
            return None
        job = jobs[0]; d = self.get(task, job["draft_id"])
        if d["revision"] != job["revision"] or d["state"] in ("cancelled", "paused"):
            raise BoundaryError("LATE_RESULT_REJECTED")
        sources, answers = json.loads(d["sources"]), json.loads(d["answers"])
        if d["target"]:
            target = json.loads(d["target"])
            # Adapter contract: authenticate and filter the exact project BEFORE fetching.
            current = self.business.resolve(task, target["id"])
            if current != target:
                raise BoundaryError("TARGET_REVISION_CHANGED")
            for source in self.business.sources(task, target):
                if source["provenance"] == "current_project" and source["id"] not in {s["id"] for s in sources}:
                    sources.append(source)
        if not any(s["segments"] for s in sources):
            raise BoundaryError("LOGIC_NO_READABLE_SOURCE")
        expires = min(task["expires"], d["expires"])
        deadline = time.monotonic() + min(120, expires - self.s.clock())
        model_elapsed = []
        def call(prompt):
            fresh = self.get(task, d["id"])
            if fresh["revision"] != job["revision"] or fresh["state"] in ("cancelled", "paused"):
                raise BoundaryError("LATE_RESULT_REJECTED")
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise BoundaryError("EXECUTION_TIMEOUT")
            response = self.g.provider.complete(prompt, run_id=task["run_id"], timeout=remaining, on_start=started)
            model_elapsed.append(response.elapsed)
            return response
        prompt, meta = build_prompt(sources, d["document_type"], bool(d["stage"]), answers)
        meta["workflow_sha256"] = WORKFLOW_SHA256
        meta["model"] = {"name": self.g.config.api_model, "digest": self.g.config.api_model_digest}
        result = call(prompt)
        try:
            analysis = validate_analysis(parse_json(result.text), sources, stage=bool(d["stage"]))
        except BoundaryError as exc:
            if str(exc) not in {"LOGIC_RELATION_INVALID", "LOGIC_SCHEMA_INVALID", "LOGIC_JSON_INVALID", "LOGIC_REFERENCE_INVALID"}:
                raise
            # One bounded schema repair; no side effect or automatic retry of a failed API call.
            repair = prompt + "\n上次JSON未通过程序检查：" + str(exc) + "。只修正结构或引用。关系只允许支持、反对、不足、冲突；不能写限制。"
            repair += "被检验命题的范围限制有原句支持时关系为支持；宽泛命题缺证时为不足。原句逐字引用对应ref，不补新事实。\n上次输出：" + result.text
            result = call(repair)
            analysis = validate_analysis(parse_json(result.text), sources, stage=bool(d["stage"]))
        analysis = apply_program_findings(analysis, sources)
        if d["stage"]:
            analysis["questions"] = []
        # Stable questions already answered are not asked again. Their gaps remain.
        analysis["questions"] = [q for q in analysis["questions"] if q["key"] not in answers]
        review_result = call(semantic_prompt(sources, analysis))
        review = validate_semantics(review_result.text)
        if not review["ok"]:
            self.s.execute("UPDATE logic_drafts SET review=?,error='LOGIC_SEMANTIC_REVIEW' WHERE id=? AND revision=?",
                           (json.dumps(review, ensure_ascii=False), d["id"], job["revision"]))
            raise BoundaryError("LOGIC_SEMANTIC_REVIEW")
        meta["model_calls"] = len(model_elapsed)
        content = render(sources, analysis, review, meta, document_type=d["document_type"],
                         stage=bool(d["stage"]), business="候选稿已生成；尚未采用／挂载；专业批准状态未从业务系统确认。")
        with self.s.tx() as c:
            changed = c.execute("UPDATE logic_drafts SET state='ready',analysis=?,review=?,rules=?,content=?,content_hash=?,error=NULL "
                                "WHERE id=? AND revision=? AND state NOT IN ('cancelled','paused') AND expires>?",
                                (json.dumps(analysis, ensure_ascii=False), json.dumps(review, ensure_ascii=False),
                                 json.dumps(meta), content, digest(content), d["id"], job["revision"], self.s.clock())).rowcount
            if not changed: raise BoundaryError("LATE_RESULT_REJECTED")
        text = analysis["assessment"] + "\n\n" + "\n".join(q["ask"] + " 影响：" + q["impact"] for q in analysis["questions"])
        text += "\n\n可直接回复补充，或 /doc 阶段稿。附件含原句、证据和关键修改。业务状态：尚未采用／挂载。"
        return content, Result(text, result.model, sum(model_elapsed)), expires

    def valid_job(self, task):
        rows = self.s.rows("SELECT d.revision,d.state,d.expires,j.revision AS expected FROM logic_jobs j "
                           "JOIN logic_drafts d ON d.id=j.draft_id WHERE j.task_id=?", (task["id"],))
        return not rows or (rows[0]["revision"] == rows[0]["expected"] and rows[0]["state"] == "ready" and rows[0]["expires"] > self.s.clock())

    def adopt(self, row, draft_id):
        d = self.get(row, draft_id)
        if d["state"] != "ready" or not d["content_hash"]: raise BoundaryError("LOGIC_NO_CURRENT_DRAFT")
        self.s.execute("UPDATE logic_drafts SET accepted_hash=content_hash WHERE id=? AND revision=?", (draft_id, d["revision"]))

    def select_target(self, row, draft_id, target_id):
        d = self.get(row, draft_id)
        if d["state"] == "cancelled":
            raise BoundaryError("LOGIC_DRAFT_CANCELLED")
        target = self.business.resolve(row, target_id)
        if not all(target.get(k) for k in ("id", "project_id", "node_id", "deliverable_id", "revision")):
            raise BoundaryError("TARGET_INCOMPLETE")
        encoded = json.dumps(target, sort_keys=True)
        if d["target"] != encoded:
            state = "collecting" if d["target"] and d["state"] != "paused" else d["state"]
            self.s.execute("UPDATE logic_drafts SET target=?,accepted_hash=NULL,revision=revision+1,state=? WHERE id=?",
                           (encoded, state, d["id"]))

    def mount(self, row, draft_id):
        d = self.get(row, draft_id)
        if not d["target"]: raise BoundaryError("BUSINESS_TARGET_MISSING")
        if d["state"] != "ready" or d["accepted_hash"] != d["content_hash"]:
            raise BoundaryError("CONTENT_ADOPTION_REQUIRED")
        target = json.loads(d["target"])
        idem = digest(json.dumps([d["id"], d["revision"], target, d["content_hash"]], sort_keys=True))
        old = self.s.rows("SELECT * FROM logic_writes WHERE idem=?", (idem,))
        if old:
            receipt = json.loads(old[0]["receipt"]) if old[0]["receipt"] else None
            if old[0]["state"] == "committed":
                current_receipt = self.business.reconcile(row, idem)
                if current_receipt != receipt:
                    return {"message": "原挂载回执已存在，但当前读回尚未确认；未重复写入。", "receipt": None}
                return {"message": "已挂载并重新读回，复用原回执；未改变专业审核状态。", "receipt": receipt}
            # Never submit again after an ambiguous dispatch, even if reconcile is unavailable.
            receipt = self.business.reconcile(row, idem)
            if receipt:
                self._receipt(idem, receipt, target, d["content_hash"])
                return {"message": "对账确认已挂载；未重复写入。", "receipt": receipt}
            return {"message": "挂载结果待确认；保留候选稿，未再次写入。", "receipt": None}
        if self.business.resolve(row, target["id"]) != target:
            raise BoundaryError("TARGET_REVISION_CHANGED")
        fresh = self.get(row, draft_id)
        if fresh["revision"] != d["revision"] or fresh["state"] != "ready":
            raise BoundaryError("LATE_RESULT_REJECTED")
        # Journal BEFORE dispatch; the port must enforce revision and idempotency atomically.
        self.s.execute("INSERT INTO logic_writes VALUES(?,?,?,?,?,'unknown',NULL)",
                       (idem, d["id"], d["revision"], json.dumps(target), d["content_hash"]))
        try:
            def guard():
                fresh = self.get(row, draft_id)
                return fresh["revision"] == d["revision"] and fresh["state"] == "ready" and fresh["accepted_hash"] == d["content_hash"]
            receipt = self.business.commit(row, target, d["content"], d["content_hash"], idem, guard)
        except Exception:
            return {"message": "挂载结果待确认；先对账，未盲目重试。", "receipt": None}
        verified = self.business.reconcile(row, idem)
        if verified != receipt:
            return {"message": "已收到提交回执，但平台读回尚未一致，结果待确认。", "receipt": None}
        self._receipt(idem, receipt, target, d["content_hash"])
        cancelled = self.get(row, draft_id)["state"] == "cancelled"
        return {"message": ("已提交后收到撤销，保留真实挂载结果并停止后续动作；未删除历史。"
                            if cancelled else "已挂载并取得回执；不代表专业审核通过。"), "receipt": receipt}

    def reconcile_draft(self, row, draft_id):
        self.get(row, draft_id)
        writes = self.s.rows("SELECT * FROM logic_writes WHERE draft_id=?", (draft_id,))
        if not writes:
            return "本稿没有已发起的业务挂载。"
        unknown = False
        for write in writes:
            if write["state"] == "committed":
                continue
            receipt = self.business.reconcile(row, write["idem"])
            if receipt:
                self._receipt(write["idem"], receipt, json.loads(write["target"]), write["content_hash"])
            else:
                unknown = True
        return "仍有挂载结果待确认；未再次写入。" if unknown else "已对账确认原挂载结果；未删除历史或改变审核状态。"

    def _receipt(self, idem, receipt, target, content_hash):
        if (not isinstance(receipt, dict) or receipt.get("target_id") != target["id"]
                or receipt.get("content_hash") != content_hash or not receipt.get("object_id")
                or not receipt.get("url")):
            raise BoundaryError("MOUNT_RECEIPT_UNVERIFIED")
        self.s.execute("UPDATE logic_writes SET state='committed',receipt=? WHERE idem=?",
                       (json.dumps(receipt), idem))

    def cancel(self, row, draft_id):
        self.get(row, draft_id)
        self.s.execute("UPDATE logic_drafts SET state='cancelled',revision=revision+1,accepted_hash=NULL WHERE id=?", (draft_id,))
        states = self.s.rows("SELECT state FROM logic_writes WHERE draft_id=?", (draft_id,))
        self.notify(row, "已放弃本稿的后续动作。"
                    + ("曾提交挂载；实际结果保留，未知结果仍需对账，不删除历史。" if states else "尚未发起业务挂载。"))

    def cleanup(self):
        self.s.execute("DELETE FROM logic_receipts WHERE inbox_seq IN (SELECT seq FROM inbox WHERE expires<=?)", (self.s.clock(),))
        self.s.execute("UPDATE logic_drafts SET sources='[]',answers='{}',analysis=NULL,review=NULL,rules=NULL,content=NULL,"
                       "content_hash=NULL,accepted_hash=NULL,target=NULL,state='expired' WHERE expires<=?", (self.s.clock(),))
