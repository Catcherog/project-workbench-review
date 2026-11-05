"""Owner web presentation/approval adapter inside the existing AM process.

No server, listener, polling loop, network client, task DB, or sender is created.
The original FollowupHost.operator_step invokes handle(); native prepare,
FollowupCoordinator.approve, FollowupHost.adopt and Scheduler remain the only
follow-up execution chain. HMAC assertions are issued only by the authenticated
Workbench BFF after its existing session and CSRF checks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any
from zoneinfo import ZoneInfo


AUDIENCE = "am-ledger-workbench"
SCHEMA = "am-workbench.rpc/v1"
RESULT_SCHEMA = "am-workbench.rpc-result/v1"
SCOPES = {"snapshot": "ledger:read", "status": "ledger:read",
          "prepare": "am:prepare", "revise": "am:prepare", "present": "am:prepare",
          "approve": "am:approve", "review": "review:resolve", "reminder": "reminder:manage"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SAFE_INTEGER = 9007199254740991
ASSOCIATION_GAP_CODES = {"subject_unresolved", "subject_binding_ambiguous", "subject_binding_mismatch"}


class WebBoundaryError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical(value: Any) -> str:
    # JSON.parse in the BFF represents an integral float as an integer. Native
    # AM timestamps often use float seconds, so canonicalize those identically.
    def integral(v):
        if type(v) is float and math.isfinite(v) and v.is_integer():
            return int(v)
        if type(v) is dict:
            return {k: integral(x) for k, x in v.items()}
        if type(v) in (list, tuple):
            return [integral(x) for x in v]
        return v
    return json.dumps(integral(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def signature(secret: bytes, value: dict) -> str:
    return hmac.new(secret, canonical(value).encode("utf-8"), hashlib.sha256).hexdigest()


def wire_value(value):
    """Integer-only signed JSON; preserve other native numbers as decimal text.

    This changes the transport representation only. Native FactEngine values,
    follow-up content hashes, dependency gates and database types are untouched.
    """
    if value is None or type(value) in (str, bool):
        return value
    if type(value) is int:
        return value if abs(value) <= MAX_SAFE_INTEGER else str(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise WebBoundaryError("WEB_NONFINITE_NUMBER")
        if value.is_integer() and abs(value) <= MAX_SAFE_INTEGER:
            return int(value)
        return format(Decimal(repr(value)), "f")
    if type(value) in (list, tuple):
        return [wire_value(v) for v in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: wire_value(v) for k, v in value.items()}
    raise WebBoundaryError("WEB_WIRE_VALUE_INVALID")


def _string(value, code="WEB_FIELD_INVALID", maximum=4000):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise WebBoundaryError(code)
    return value


def _keys(value, required, optional=()):
    if type(value) is not dict or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise WebBoundaryError("WEB_SCHEMA_INVALID")


class _OwnerContext(dict):
    """In-process capability; never deserialized from a request dictionary."""
    def __init__(self, proof, envelope, host):
        session = envelope["session"]
        super().__init__(id="web/" + envelope["requestId"], app=host.app,
            tenant=host.tenant, user=host.owner, chat="web/" + session["id"],
            chat_type="web", created=envelope["issuedAtMs"] / 1000,
            expires=min(envelope["expiresAtMs"], session["expiresAtMs"]) / 1000,
            kind="web", body="")
        self._proof = proof
        self.session_id = session["id"]
        self.session_expires = session["expiresAtMs"]
        self.request_id = envelope["requestId"]
        self.project_ids = frozenset(session["projectIds"])
        self.workspace_id = session["workspaceId"]

    def allows(self, project_id):
        return "*" in self.project_ids or project_id in self.project_ids


class WorkbenchAdapter:
    def __init__(self, host, secret: bytes, *, workspace_id=None):
        if type(secret) is not bytes or len(secret) < 32:
            raise WebBoundaryError("WEB_SIGNING_KEY_INVALID")
        self.host, self.s, self.secret = host, host.s, secret
        self.workspace_id = workspace_id or host.tenant
        self._proof = object()
        with self.s.lock:
            self.s.conn.executescript('''
            CREATE TABLE IF NOT EXISTS wb_rpc_requests(
              request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, method TEXT NOT NULL,
              fingerprint TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT,
              created_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS wb_web_previews(
              preview_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, item_id TEXT NOT NULL,
              content_hash TEXT NOT NULL, display_hash TEXT NOT NULL, display_json TEXT NOT NULL,
              expires_ms INTEGER NOT NULL, invalidated INTEGER NOT NULL DEFAULT 0,
              request_id TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS wb_presentations(
              presentation_id TEXT PRIMARY KEY, preview_id TEXT NOT NULL, session_id TEXT NOT NULL,
              display_hash TEXT NOT NULL, created_ms INTEGER NOT NULL, expires_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS wb_approval_requests(
              request_id TEXT PRIMARY KEY, preview_id TEXT UNIQUE NOT NULL,
              presentation_id TEXT NOT NULL, session_id TEXT NOT NULL, approved_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS wb_review_audit(
              review_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, object_id TEXT NOT NULL,
              source_version TEXT NOT NULL, subject_id TEXT NOT NULL, review_hash TEXT NOT NULL,
              fact_ids TEXT NOT NULL, actor TEXT NOT NULL, request_id TEXT NOT NULL, created_ms INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS wb_reminder_presentation(
              owner_id TEXT NOT NULL, reminder_id TEXT NOT NULL, basis TEXT NOT NULL,
              state TEXT NOT NULL, until_ms INTEGER, updated_ms INTEGER NOT NULL,
              PRIMARY KEY(owner_id,reminder_id,basis));
            CREATE TABLE IF NOT EXISTS wb_display_decisions(
              review_id TEXT PRIMARY KEY,review_hash TEXT NOT NULL,project_id TEXT NOT NULL,
              fact_ids TEXT NOT NULL,selected_fact_id TEXT NOT NULL,source_identity_hash TEXT NOT NULL,
              actor TEXT NOT NULL,request_id TEXT NOT NULL,created_ms INTEGER NOT NULL);
            ''')

    def now(self):
        return int(self.s.clock() * 1000)

    def is_context(self, row):
        return type(row) is _OwnerContext and row._proof is self._proof

    def actor(self, row, *, require_followup=True):
        if not self.is_context(row) or row["expires"] <= self.s.clock():
            raise WebBoundaryError("WEB_SESSION_EXPIRED")
        if (row["app"], row["tenant"], row["user"], row["chat_type"]) != (
                self.host.app, self.host.tenant, self.host.owner, "web"):
            raise WebBoundaryError("WEB_OWNER_SCOPE_REQUIRED")
        self.host.am.ledger.port.authorize_user(self.host.owner)
        if require_followup and (not self.host.am.flags["items"] or not self.host.am.flags["scheduler"]):
            raise WebBoundaryError("WEB_FOLLOWUP_NOT_ENABLED")
        from am_followup.followup import Actor
        return Actor(self.host.tenant, self.host.owner, row["id"],
                     datetime.fromtimestamp(row["expires"], timezone.utc))

    def _verify(self, envelope):
        _keys(envelope, ("schema", "requestId", "method", "issuedAtMs", "expiresAtMs",
                         "audience", "session", "params", "signature"))
        unsigned = {k: v for k, v in envelope.items() if k != "signature"}
        if len(canonical(envelope).encode("utf-8")) > 60000:
            raise WebBoundaryError("WEB_REQUEST_TOO_LARGE")
        if type(envelope["signature"]) is not str or not HASH_RE.fullmatch(envelope["signature"]) or not hmac.compare_digest(signature(self.secret, unsigned), envelope["signature"]):
            raise WebBoundaryError("WEB_SIGNATURE_INVALID")
        if envelope["schema"] != SCHEMA or envelope["audience"] != AUDIENCE:
            raise WebBoundaryError("WEB_AUDIENCE_INVALID")
        if type(envelope["requestId"]) is not str or not ID_RE.fullmatch(envelope["requestId"]):
            raise WebBoundaryError("WEB_REQUEST_ID_INVALID")
        method = envelope["method"]
        if method not in SCOPES or type(envelope["params"]) is not dict:
            raise WebBoundaryError("WEB_METHOD_INVALID")
        session = envelope["session"]
        _keys(session, ("id", "userId", "tenantId", "workspaceId", "projectIds", "expiresAtMs", "scopes"))
        if type(session["id"]) is not str or not ID_RE.fullmatch(session["id"]):
            raise WebBoundaryError("WEB_SESSION_INVALID")
        if (session["userId"], session["tenantId"]) != (self.host.owner, self.host.tenant):
            raise WebBoundaryError("WEB_OWNER_SCOPE_REQUIRED")
        if session["workspaceId"] != self.workspace_id:
            raise WebBoundaryError("WEB_WORKSPACE_SCOPE_REQUIRED")
        if type(session["projectIds"]) is not list or len(session["projectIds"]) > 1000 or any(type(v) is not str or not v or len(v) > 256 for v in session["projectIds"]):
            raise WebBoundaryError("WEB_PROJECT_SCOPE_INVALID")
        if type(session["scopes"]) is not list or any(type(v) is not str for v in session["scopes"]) or SCOPES[method] not in session["scopes"]:
            raise WebBoundaryError("WEB_SCOPE_DENIED")
        now = self.now()
        times = (envelope["issuedAtMs"], envelope["expiresAtMs"], session["expiresAtMs"])
        if any(type(t) is not int or abs(t) > MAX_SAFE_INTEGER for t in times):
            raise WebBoundaryError("WEB_TIME_INVALID")
        issued, expires, session_expiry = times
        if issued > now + 5000 or issued < now - 60000 or not issued < expires <= issued + 60000 or expires <= now or session_expiry <= now or expires > session_expiry:
            raise WebBoundaryError("WEB_REQUEST_EXPIRED")
        return _OwnerContext(self._proof, envelope, self.host)

    def _result(self, envelope, *, data=None, error=None):
        result = {"schema": RESULT_SCHEMA, "audience": AUDIENCE,
                  "requestId": envelope.get("requestId", "invalid"),
                  "method": envelope.get("method", "invalid"),
                  "ok": error is None, "serverTimeMs": self.now()}
        result["data" if error is None else "error"] = wire_value(data) if error is None else {"code": error}
        result["signature"] = signature(self.secret, result)
        return result

    def handle(self, envelope):
        """Called only by the original operator consumer. Never calls dispatch."""
        try:
            context = self._verify(envelope)
            self.actor(context, require_followup=envelope["method"] in {"prepare", "revise", "present", "approve"})
            fingerprint = digest({k: v for k, v in envelope.items() if k != "signature"})
            request_id, method = envelope["requestId"], envelope["method"]
            old = self.s.rows("SELECT * FROM wb_rpc_requests WHERE request_id=?", (request_id,))
            if old:
                old = old[0]
                if (old["session_id"], old["method"], old["fingerprint"]) != (context.session_id, method, fingerprint):
                    raise WebBoundaryError("WEB_REQUEST_ID_REUSED")
                # Reads are re-evaluated to retain current ACL and raw retention.
                if method not in {"snapshot", "status"}:
                    if old["result_json"]:
                        return json.loads(old["result_json"])
                    if method == "approve":
                        return self._result(envelope, data=self._receipt(context, request_id))
                    raise WebBoundaryError("WEB_REQUEST_INTERRUPTED")
            else:
                self.s.execute("INSERT INTO wb_rpc_requests VALUES(?,?,?,?, 'processing',NULL,?)",
                    (request_id, context.session_id, method, fingerprint, self.now()))
            try:
                data = getattr(self, "_" + method)(context, envelope["params"])
                result = self._result(envelope, data=data)
            except Exception as exc:
                code = getattr(exc, "code", None)
                if code is None and type(exc).__name__ == "BoundaryError":
                    code = str(exc)
                code = code if type(code) is str and re.fullmatch(r"[A-Za-z0-9_:-]{1,160}", code) else "WEB_OPERATION_FAILED"
                result = self._result(envelope, error=code)
            # Never create a second retained copy of source facts or review text.
            saved = None if method in {"snapshot", "status"} else canonical(result)
            self.s.execute("UPDATE wb_rpc_requests SET state=?,result_json=? WHERE request_id=?",
                ("done" if result["ok"] else "failed", saved, request_id))
            return result
        except Exception as exc:
            code = getattr(exc, "code", "WEB_REQUEST_REJECTED")
            safe = envelope if type(envelope) is dict else {}
            return self._result(safe, error=code)

    def _item(self, context, item_id):
        item = self.host.am.items.get(_string(item_id, maximum=256))
        if item["owner"] != self.host.owner:
            raise WebBoundaryError("WEB_ITEM_OWNER_MISMATCH")
        if not context.allows(item["project_ref"]):
            raise WebBoundaryError("WEB_PROJECT_SCOPE_DENIED")
        return item

    def _preview(self, context, preview_id, *, current=True):
        found = self.s.rows("SELECT * FROM wb_web_previews WHERE preview_id=?", (_string(preview_id, maximum=256),))
        if not found or found[0]["session_id"] != context.session_id:
            raise WebBoundaryError("WEB_PREVIEW_SESSION_MISMATCH")
        row = found[0]
        self._item(context, row["item_id"])
        if row["invalidated"] or (current and row["expires_ms"] <= self.now()):
            raise WebBoundaryError("WEB_PREVIEW_EXPIRED_OR_USED")
        if row["display_hash"] != digest(json.loads(row["display_json"])):
            raise WebBoundaryError("WEB_DISPLAY_CORRUPTED")
        native = self.s.rows("SELECT * FROM followup_previews WHERE preview_id=? AND tenant_id=?",
                             (preview_id, self.host.tenant))
        if len(native) != 1 or native[0]["content_hash"] != row["content_hash"]:
            raise WebBoundaryError("WEB_NATIVE_PREVIEW_CHANGED")
        bindings = self.s.rows("SELECT * FROM followup_bindings WHERE preview_id=?", (preview_id,))
        if len(bindings) != 1 or bindings[0]["invalidated"] or row["invalidated"]:
            raise WebBoundaryError("WEB_PREVIEW_INVALIDATED")
        if current and (row["expires_ms"] <= self.now() or native[0]["state"] != "prepared"):
            raise WebBoundaryError("WEB_PREVIEW_EXPIRED_OR_USED")
        return row, native[0], bindings[0]

    def _prepare(self, context, params):
        _keys(params, ("itemId", "expectedItemVersion", "expectedSemanticVersion"),
              ("channel", "recipientId", "body", "purpose"))
        item = self._item(context, params["itemId"])
        semantics = self.s.rows("SELECT * FROM action_semantics WHERE item_id=?", (item["id"],))
        semantic_version = semantics[0]["version"] if semantics else 0
        if type(params["expectedItemVersion"]) is not int or type(params["expectedSemanticVersion"]) is not int or (params["expectedItemVersion"], params["expectedSemanticVersion"]) != (item["version"], semantic_version):
            raise WebBoundaryError("WEB_ITEM_VERSION_CHANGED")
        if item["paused"] or item["state"] in {"closed", "cancelled"}:
            return {"kind": "wait", "recommendation": "保留原事项状态，目前无需新增跟进发送。",
                    "reason": "原事项已暂停或结束；本次没有修改事项或安排新的执行。"}
        if semantics:
            view = self.host.view(item["id"])
            current = {f["fact_id"] for f in self.host.sources.facts(item["project_ref"])["facts"] if f["evidence"]["raw_available"]}
            if view["needs_review"] or any(ref["fact_id"] not in current for ref in json.loads(semantics[0]["refs"])):
                raise WebBoundaryError("FOLLOWUP_SOURCE_REVIEW_REQUIRED")
            if item.get("next_check") and item["next_check"] > self.s.clock() and not view["stale_fields"] and item["state"] != "blocked" and view["fields"].get("execution") != "blocked" and not self.host.legacy_uncertain(item["id"], semantics[0]):
                prior = self.s.rows("SELECT state FROM followup_intents WHERE tenant_id=? AND state IN ('sending','unknown','accepted') AND intent_id IN (SELECT intent_id FROM followup_adoptions WHERE item_id=?)", (self.host.tenant, item["id"]))
                if not prior:
                    when = datetime.fromtimestamp(item["next_check"], ZoneInfo(item.get("timezone") or "Asia/Shanghai")).isoformat()
                    return {"kind": "wait", "recommendation": "保留原定检查点，目前等待进展即可。",
                            "reason": "原事项的下一检查点尚未到，当前未登记需提前介入的新卡点；没有新增发送或定时任务。",
                            "nextCheckAt": when}
        channel = params.get("channel")
        if channel is None:
            target = json.loads(item["source"]).get("target", {})
            if type(target) is dict and target.get("group", {}).get("id"):
                channel = "group"
            else:
                return {"kind": "choose_route", "reason": "原事项没有明确绑定的群聊，请选择已有负责人并核实机器人私聊。",
                        "allowedChannels": ["recipient_p2p"], "assigneeIds": json.loads(item["assignees"])}
        if channel not in {"group", "recipient_p2p"}:
            raise WebBoundaryError("WEB_CHANNEL_INVALID")
        body = params.get("body")
        if body is not None:
            _string(body)
        preview, target = self.host.prepare(context, item["id"], channel,
            purpose=params.get("purpose", "request_progress"), recipient=params.get("recipientId"), body=body)
        # Native gates already bind precise facts, item/semantic versions, ACL,
        # recipients and disclosure; preserve them and do not accept client refs.
        sem = self.host.semantic(item["id"])
        native_target = {"channel": channel, "id": preview.draft.target.target_id,
            "name": target["name"] if channel == "recipient_p2p" else target["payload"]["group"]["name"],
            "attention": ([{"id": target["user"], "name": target["name"]}] if channel == "recipient_p2p"
                          else [{"id": p["id"], "name": p["name"]} for p in target["payload"]["people"]])}
        facts = {fact["fact_id"]: fact for fact in self.host.sources.facts(item["project_ref"])["facts"]}
        source_expiries = []
        for ref in json.loads(sem["refs"]):
            fact = facts.get(ref["fact_id"])
            if not fact or not fact["evidence"]["raw_available"]:
                raise WebBoundaryError("FOLLOWUP_SOURCE_REVIEW_REQUIRED")
            source_expiries.append(fact["evidence"]["raw_expires_at_ms"])
        expires = min(int(preview.expires_at.timestamp() * 1000), context.session_expires, *source_expiries)
        display = {"schema": "am-workbench.preview/v1", "version": 1,
            "previewId": preview.preview_id, "contentHash": preview.content_hash,
            "itemId": item["id"], "projectId": item["project_ref"],
            "itemVersion": item["version"], "semanticVersion": sem["version"],
            "target": native_target, "body": preview.draft.body, "count": 1,
            "sendWindow": {"notBeforeMs": int(preview.draft.window.not_before.timestamp() * 1000),
                "expiresAtMs": int(preview.draft.window.expires_at.timestamp() * 1000),
                "immediate": True, "includesCurrentHours": True},
            "expiresAtMs": expires, "attachments": [],
            "followup": "核对发送回执并等待反馈；结果未知时不重发；发送和回复均不代表业务完成。",
            "dependenciesHash": digest({"versions": preview.draft.evidence.versions,
                "aclVersions": preview.draft.evidence.acl_versions,
                "taskVersion": preview.draft.evidence.task_version})}
        display_hash = digest(display)
        self.s.execute("INSERT INTO wb_web_previews VALUES(?,?,?,?,?,?,?,0,?)",
            (preview.preview_id, context.session_id, item["id"], preview.content_hash,
             display_hash, canonical(display), expires, context.request_id))
        return {**display, "displayHash": display_hash}

    def _revise(self, context, params):
        _keys(params, ("previousPreviewId", "itemId", "expectedItemVersion", "expectedSemanticVersion"),
              ("channel", "recipientId", "body", "purpose"))
        old, _, _ = self._preview(context, params["previousPreviewId"])
        if old["item_id"] != params["itemId"]:
            raise WebBoundaryError("WEB_REVISION_ITEM_MISMATCH")
        with self.s.tx() as db:
            db.execute("UPDATE wb_web_previews SET invalidated=1 WHERE preview_id=?", (old["preview_id"],))
            db.execute("UPDATE followup_bindings SET invalidated=1 WHERE preview_id=?", (old["preview_id"],))
        return self._prepare(context, {k: v for k, v in params.items() if k != "previousPreviewId"})

    def _present(self, context, params):
        _keys(params, ("previewId", "displayHash"))
        row, _, _ = self._preview(context, params["previewId"])
        if params["displayHash"] != row["display_hash"]:
            raise WebBoundaryError("WEB_DISPLAY_HASH_CHANGED")
        ident = "presentation_" + secrets.token_hex(16)
        self.s.execute("INSERT INTO wb_presentations VALUES(?,?,?,?,?,?)",
            (ident, row["preview_id"], context.session_id, row["display_hash"], self.now(), row["expires_ms"]))
        return {"presentationId": ident, "previewId": row["preview_id"],
                "displayHash": row["display_hash"], "expiresAtMs": row["expires_ms"], "approved": False}

    def _approve(self, context, params):
        _keys(params, ("previewId", "presentationId", "displayHash"), ("requestId",))
        if params.get("requestId", context.request_id) != context.request_id:
            raise WebBoundaryError("WEB_APPROVAL_REQUEST_MISMATCH")
        prior = self.s.rows("SELECT * FROM wb_approval_requests WHERE preview_id=?", (params["previewId"],))
        if prior:
            if prior[0]["session_id"] != context.session_id:
                raise WebBoundaryError("WEB_PREVIEW_SESSION_MISMATCH")
            return self._receipt(context, prior[0]["request_id"])
        row, _, binding = self._preview(context, params["previewId"])
        presented = self.s.rows("SELECT * FROM wb_presentations WHERE presentation_id=?", (params["presentationId"],))
        if not presented or (presented[0]["session_id"], presented[0]["preview_id"], presented[0]["display_hash"]) != (context.session_id, row["preview_id"], params["displayHash"]) or params["displayHash"] != row["display_hash"] or presented[0]["expires_ms"] <= self.now():
            raise WebBoundaryError("WEB_PRESENTATION_REQUIRED")
        self.s.execute("INSERT INTO wb_approval_requests VALUES(?,?,?,?,?)",
            (context.request_id, row["preview_id"], params["presentationId"], context.session_id, self.now()))
        # A distinct web channel admission: no synthetic Feishu callback or
        # delivered-card record. Reuse all native evidence/recipient gates.
        result = self.host.coordinator.approve(self.actor(context), row["preview_id"],
                                              binding["token"], row["content_hash"])
        if result.status != "already_reserved":
            self.host.adopt(result.intent_id)
        return self._receipt(context, context.request_id)

    def _receipt(self, context, request_id):
        approvals = self.s.rows("SELECT * FROM wb_approval_requests WHERE request_id=?", (request_id,))
        if not approvals:
            return {"requestId": request_id, "state": "unknown", "reason": "admission_not_recorded",
                    "messageId": None, "businessCompleted": False, "mayResend": False}
        approval = approvals[0]
        if approval["session_id"] != context.session_id:
            raise WebBoundaryError("WEB_RECEIPT_SESSION_MISMATCH")
        web_preview = self.s.rows("SELECT item_id FROM wb_web_previews WHERE preview_id=?", (approval["preview_id"],))
        if not web_preview:
            raise WebBoundaryError("WEB_NATIVE_RECEIPT_MISSING")
        self._item(context, web_preview[0]["item_id"])
        native = self.s.rows("SELECT * FROM followup_previews WHERE tenant_id=? AND preview_id=?",
                             (self.host.tenant, approval["preview_id"]))
        intent_id = native[0]["intent_id"] if native else None
        if not intent_id:
            return {"requestId": request_id, "previewId": approval["preview_id"],
                    "state": "blocked", "reason": "native_admission_not_completed",
                    "messageId": None, "businessCompleted": False, "mayResend": False}
        intents = self.s.rows("SELECT * FROM followup_intents WHERE tenant_id=? AND intent_id=?",
                              (self.host.tenant, intent_id))
        if not intents:
            raise WebBoundaryError("WEB_NATIVE_RECEIPT_MISSING")
        intent = intents[0]
        occurrences = self.s.rows("SELECT o.* FROM reminder_occurrences o JOIN followup_adoptions a ON a.occurrence_id=o.id WHERE a.intent_id=?", (intent_id,))
        o = occurrences[0] if occurrences else None
        state = intent["state"]
        if o:
            state = {"ready": "queued", "confirmed_not_sent": "queued", "sent": "sent_unverified"}.get(o["state"], o["state"])
            if o["state"] == "sent" and o["readback_state"] == "verified" and intent["state"] == "confirmed":
                # Validate the exact original saved proof; a UI boolean is not a receipt.
                with self.s.tx() as db:
                    proof, _ = self.host.recovery._proof(o["id"], db)
                if proof is not None and proof.message_id == o["message_id"]:
                    state = "sent_confirmed"
        if native[0]["state"] == "already_reserved":
            state = "already_reserved"
        binding = self.s.rows("SELECT item_id FROM followup_bindings WHERE preview_id=?", (approval["preview_id"],))
        item = self._item(context, binding[0]["item_id"])
        return {"requestId": request_id, "previewId": approval["preview_id"],
            "intentId": intent_id, "occurrenceId": o["id"] if o else None,
            "state": state, "nativeIntentState": intent["state"],
            "messageId": o.get("message_id") if o else None,
            "readbackState": o.get("readback_state") if o else None,
            "reason": intent.get("reason"), "businessState": item["state"],
            "businessCompleted": item["state"] == "closed" and bool(item["close_evidence"]),
            "mayResend": False}

    def _status(self, context, params):
        _keys(params, ("requestId",))
        return self._receipt(context, _string(params["requestId"], maximum=128))

    def _outside_subjects(self, context, connection):
        """Only host-registered outside subjects in currently readable source scope.

        A missing project binding never registers an outside subject. A catalog
        row or a wildcard web session alone does not grant source access.
        """
        from am_info_sync.models import Principal, Source
        from am_info_sync.policy import can_read
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "entity_catalog" not in tables:
            return []
        allowed = set()
        principal = Principal(self.host.owner, self.host.tenant)
        for row in connection.execute("SELECT config_json,availability FROM sources"):
            source = Source.from_dict(json.loads(row["config_json"]))
            if not source.enabled or row["availability"] == "denied" or not can_read(source, principal):
                continue
            listed = source.settings.get("subject_ids", [])
            fixed = source.settings.get("subject_id")
            subjects = ([fixed] if "subject_ids" not in source.settings or fixed in listed else []) if fixed is not None else listed
            if type(subjects) not in (list, tuple):
                continue
            allowed.update(s for s in subjects if type(s) is str and context.allows(s))
        result = []
        for row in connection.execute("SELECT subject_id,name FROM entity_catalog WHERE kind='outside' AND project_id IS NULL ORDER BY subject_id"):
            if row["subject_id"] in allowed:
                result.append({"key": row["subject_id"], "title": row["name"],
                    "kind": "outside", "status": "unknown", "catalogRegistered": True})
        return result

    def _snapshot(self, context, params):
        _keys(params, (), ("projectId",))
        from am_info_sync.models import Principal
        info = self.host.sources.info
        projects = [p for p in self.host.am.projects(context) if context.allows(p["key"])]
        with self.host.s.lock:
            with info.store.transaction() as connection:
                access = info.store.access_version()
                seen = {p["key"] for p in projects}
                projects += [p for p in self._outside_subjects(context, connection) if p["key"] not in seen]
                if "projectId" in params:
                    projects = [p for p in projects if p["key"] == params["projectId"]]
                    if not projects:
                        raise WebBoundaryError("WEB_PROJECT_NOT_AVAILABLE")
                queries = {p["key"]: info.service.query(p["key"], Principal(self.host.owner, self.host.tenant), connection=connection) for p in projects}
                for query in queries.values():
                    for fact in query["facts"]:
                        if fact["field"] == "reported_feedback" and fact["value"] == {"retentionBoundExcerpt": True}:
                            evidence = fact["evidence"]
                            fact["value"] = evidence["quote"] if evidence["raw_available"] else "原文已过保留期或不可用，内容待刷新。"
                            fact["retentionBoundExcerpt"] = True
                for project in projects:
                    current_rows = [f for f in queries[project["key"]]["facts"] if f["field"] == "ledger_record" and f["authority"] == "source_confirmed" and f["evidence"]["source_id"] == "th2-ledger" and f["evidence"]["raw_available"]]
                    project["ledgerProjectionVerified"] = any(type(f["value"]) is dict and f["value"].get("title") == project["title"] and all(f["value"].get("fields", {}).get(k, "") == project.get(k, "") for k in ("关键日期", "待办", "项目进展", "人员与职责")) for f in current_rows)
                    observed = project.get("_sync_observed_at")
                    if type(observed) in (int, float):
                        project["_sync_observed_at"] = datetime.fromtimestamp(observed, timezone.utc).isoformat()
                ids = {p["key"] for p in projects}
                items = self.s.rows("SELECT * FROM action_items WHERE owner=? ORDER BY created DESC", (self.host.owner,))
                items = [i for i in items if i["project_ref"] in ids]
                for item in items:
                    sem = self.s.rows("SELECT version FROM action_semantics WHERE item_id=?", (item["id"],))
                    item["semanticVersion"] = sem[0]["version"] if sem else 0
                    item["assignees"] = json.loads(item["assignees"])
                    item["view"] = self.host.view(item["id"], connection=connection) if sem else None
                    if item["view"]:
                        usable = {f["fact_id"] for f in queries[item["project_ref"]]["facts"] if f["evidence"]["raw_available"]}
                        if any(r["fact_id"] not in usable for r in item["view"]["source_refs"]):
                            item["view"]["needs_review"] = sorted(set(item["view"]["needs_review"] + ["source_refs"]))
                    item.pop("source", None)
                source_reviews = self._source_reviews(context, items, queries, access)
        extraction_gaps = self._reviews(context, include_processing=True)
        reviews = [r for r in extraction_gaps if r["kind"] == "association"]
        processing_gaps = [r for r in extraction_gaps if r["kind"] == "processing"]
        for project_id, query in queries.items():
            gaps = [r for r in processing_gaps if project_id in r["projectIds"]]
            if gaps:
                query.setdefault("coverage", {}).update(processing_pending=True, processingGaps=gaps)
                query["incomplete_reasons"] = list(dict.fromkeys(query.get("incomplete_reasons", []) + [r["reason"] for r in gaps]))
        if info.store.access_version() != access:
            raise WebBoundaryError("WEB_SOURCE_ACCESS_CHANGED")
        reminders = self._attention(items)
        expiries = [self.now() + 60000]
        expiries.extend(f["evidence"]["raw_expires_at_ms"] for q in queries.values() for f in q["facts"] if f["evidence"]["raw_available"])
        expiries.extend(r["expiresAtMs"] for r in reviews + source_reviews + processing_gaps if r.get("rawAvailable") and r.get("expiresAtMs"))
        return {"workspaceId": self.workspace_id, "viewerId": self.host.owner,
                "wireNumberEncoding": "integer-or-decimal-text/v1",
                "projects": projects, "items": items, "queries": queries,
                "semanticReviews": reviews + source_reviews, "processingGaps": processing_gaps,
                "reminders": reminders, "sourceAccessVersion": access,
                "reminderCoverage": {"status": "complete", "reasons": ["registered_owner_items_only"]},
                "reminderPresentation": self.s.rows("SELECT reminder_id AS reminderId,basis,state,until_ms AS untilMs FROM wb_reminder_presentation WHERE owner_id=?", (self.host.owner,)),
                "reviewDecisions": self._display_decisions(context, queries),
                "capturedAtMs": self.now(), "generatedAt": datetime.fromtimestamp(self.s.clock(), timezone.utc).isoformat(),
                "expiresAtMs": min(expiries), "complete": False}

    def _display_decisions(self, context, queries):
        result = []
        for row in self.s.rows("SELECT * FROM wb_display_decisions WHERE actor=?", (self.host.owner,)):
            if not context.allows(row["project_id"]) or row["project_id"] not in queries:
                continue
            ids = json.loads(row["fact_ids"])
            current = {f["fact_id"] for f in queries[row["project_id"]]["facts"] if f["evidence"]["raw_available"]}
            if not set(ids) <= current:
                continue
            result.append({"reviewId": row["review_id"], "reviewHash": row["review_hash"],
                "projectId": row["project_id"], "factIds": ids, "selectedFactId": row["selected_fact_id"],
                "sourceIdentityHash": row["source_identity_hash"], "actorId": row["actor"],
                "requestId": row["request_id"], "displayOnly": True})
        return result

    def _attention(self, items):
        """Read-only attention projection over registered native business items."""
        reminders = []
        displays = self.s.rows("SELECT * FROM wb_reminder_presentation WHERE owner_id=?", (self.host.owner,))
        displays = {(d["reminder_id"], d["basis"]): d for d in displays}
        for item in items:
            if item["state"] in {"closed", "cancelled"}:
                continue
            view = item.get("view") or {}
            receipts = self.s.rows("SELECT id,state,readback_state,message_id FROM reminder_occurrences WHERE item_id=? ORDER BY scheduled_at DESC", (item["id"],))
            uncertain = [r for r in receipts if r["state"] in {"unknown", "sending"} or r["state"] == "sent" and r["readback_state"] != "verified"]
            concerns = []
            if uncertain:
                concerns.append(("delivery_unknown", "跟进结果待核实", "原发送结果尚未独立核实，需关注原回执；不得据此重发或认定业务完成。", "P1"))
            if view.get("needs_review"):
                concerns.append(("source_changed", "跟进依据需要重审", "相关来源已变化或原文不可用，当前依据需要重新核对。", "P1"))
            if item["state"] == "blocked" or view.get("fields", {}).get("execution") == "blocked":
                concerns.append(("blocked", "事项受阻", "已登记事项处于受阻状态，请查看卡点与需协调内容。", "P1"))
            deadline = item.get("deadline")
            due = None
            if deadline:
                try:
                    due = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=ZoneInfo(item.get("timezone") or "Asia/Shanghai"))
                except (TypeError, ValueError, KeyError):
                    due = None
            if not item["paused"] and due is not None and due.timestamp() <= self.s.clock():
                kind = item.get("deadline_kind", "unspecified")
                label = {"estimate": "预计日期", "check": "检查日期", "commitment": "承诺日期", "requirement": "要求日期"}.get(kind, "已登记日期")
                concerns.append(("date_attention", label + "需要关注", label + "为 " + deadline + "，事项尚未核验关闭；请确认当前进展与下一步。", "P1"))
            elif not item["paused"] and item.get("next_check") is not None and item["next_check"] <= self.s.clock():
                concerns.append(("check_due", "已到跟进检查点", "原事项的下一检查点已到，需核对当前进展；原截止日期保持不变。", "P2"))
            for kind, title, body, priority in concerns:
                ident = "am-item:" + item["id"] + ":" + kind
                basis = digest({"itemVersion": item["version"], "semanticVersion": item.get("semanticVersion"),
                    "kind": kind, "receipts": uncertain if kind == "delivery_unknown" else [],
                    "deadline": deadline, "nextCheck": item.get("next_check"),
                    "sourceRefs": view.get("source_refs", []) if kind == "source_changed" else [],
                    "needsReview": view.get("needs_review", [])})
                display = displays.get((ident, basis), {})
                state = "read" if display.get("state") == "ack" else "unread"
                until = display.get("until_ms")
                if until and until > self.now():
                    state = "snoozed"
                reminders.append({"id": ident, "itemId": item["id"], "projectId": item["project_ref"],
                    "title": title + " · " + item["description"], "body": body, "kind": kind,
                    "priority": priority, "severity": "attention", "basis": basis,
                    "dueAt": deadline, "displayState": state,
                    "snoozedUntil": datetime.fromtimestamp(until / 1000, timezone.utc).isoformat() if state == "snoozed" else None,
                    "businessState": "paused" if item["paused"] else "waiting" if item["state"] == "waiting" else "open"})
        return reminders

    def _source_reviews(self, context, items, queries, access):
        result = []
        for item in items:
            if not item.get("view") or not item["view"].get("needs_review"):
                continue
            sem = self.host.semantic(item["id"])
            old = json.loads(sem["refs"])
            keys = {(r["source_id"], r["object_id"], r["field"]) for r in old}
            facts = [f for f in queries[item["project_ref"]]["facts"] if
                (f["evidence"]["source_id"], f["evidence"]["object_id"], f["field"]) in keys and f["evidence"]["raw_available"]]
            if not facts:
                continue  # Existing source-changed reminder preserves the unresolved state.
            payload = {"itemId": item["id"], "expectedItemVersion": item["version"],
                "expectedSemanticVersion": sem["version"], "oldRefsHash": digest(old),
                "sourceAccessVersion": access, "factIds": [f["fact_id"] for f in facts],
                "facts": facts}
            review_hash = digest(payload)
            result.append({"id": "sources:" + item["id"], "kind": "conflict", "projectId": item["project_ref"],
                "itemId": item["id"], "reviewHash": review_hash,
                "reason": "本事项的原依据已失效；确认仅更新所示依据，旧发送预览失效，业务状态不变。",
                "text": "\n".join(f["field"] + "：" + canonical(f["value"]) for f in facts),
                "rawAvailable": True, "expiresAtMs": min(f["evidence"]["raw_expires_at_ms"] for f in facts),
                "choices": [{"id": "current-sources", "label": "采用所示当前依据", "value": {
                    "kind": "sources", "itemId": item["id"], "expectedItemVersion": item["version"],
                    "expectedSemanticVersion": sem["version"], "factIds": payload["factIds"], "reviewHash": review_hash}}],
                "nativePayload": payload})
        return result

    def _reviews(self, context, *, include_processing=False):
        from am_info_sync.models import Principal, Source
        from am_info_sync.policy import can_read
        info = self.host.sources.info
        principal = Principal(self.host.owner, self.host.tenant)
        result = []
        with info.store.transaction() as db:
            epoch = info.store.access_version()
            rows = db.execute("""SELECT g.source_id,g.object_id,g.detail,s.config_json,s.availability,
                b.current_version,b.state AS object_state,o.text,o.url,o.raw_expires_at_ms,o.purged,o.deleted,o.completeness
                FROM gaps g JOIN sources s ON s.source_id=g.source_id
                LEFT JOIN objects b ON b.source_id=g.source_id AND b.object_id=g.object_id
                LEFT JOIN observations o ON o.source_id=b.source_id AND o.object_id=b.object_id AND o.version=b.current_version
                WHERE g.state='open' AND g.kind='extraction' ORDER BY g.last_seen_ms DESC""").fetchall()
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for r in rows:
                source = Source.from_dict(json.loads(r["config_json"]))
                if r["availability"] == "denied" or not can_read(source, principal):
                    continue
                allowed = source.settings.get("subject_ids", [])
                fixed = source.settings.get("subject_id")
                if fixed is not None:
                    allowed = [fixed] if "subject_ids" not in source.settings or fixed in allowed else []
                # An unassigned mixed-source excerpt cannot be safely scoped to
                # one project until its attribution is known.
                if not allowed or not all(context.allows(subject) for subject in allowed):
                    continue
                choices = []
                if "entity_catalog" in tables:
                    for subject in allowed:
                        entry = db.execute("SELECT subject_id,name,kind FROM entity_catalog WHERE subject_id=?", (subject,)).fetchone()
                        if entry:
                            choices.append({"subjectId": entry["subject_id"], "title": entry["name"], "kind": entry["kind"]})
                available = bool(r["object_state"] == "active" and r["raw_expires_at_ms"] and r["raw_expires_at_ms"] > self.now() and not r["purged"] and not r["deleted"] and r["completeness"] == "complete")
                ident = digest([r["source_id"], r["object_id"], r["current_version"], "extraction"])
                codes = {code.strip() for code in r["detail"].removeprefix("semantic_coverage_incomplete:").split(",")}
                association = bool(codes.intersection(ASSOCIATION_GAP_CODES))
                if not association and not include_processing:
                    continue
                reason = "资料中的项目归属尚未明确，需要核对" if association else "资料含义尚未完整处理，当前摘要未涵盖全部资料"
                record = {"id": ident, "sourceId": r["source_id"], "objectId": r["object_id"],
                    "sourceVersion": r["current_version"], "reason": reason, "gapCode": r["detail"],
                    "kind": "association" if association else "processing",
                    "text": r["text"] if available else "", "rawAvailable": available,
                    "expiresAtMs": r["raw_expires_at_ms"] if available else None,
                    "sourceAccessVersion": epoch}
                if association:
                    record["choices"] = choices
                    record["reviewHash"] = digest(record)
                else:
                    record["projectIds"] = allowed
                result.append(record)
        return result

    def _review(self, context, params):
        if "choice" in params:
            _keys(params, ("reviewId", "reviewHash", "choiceId", "choice", "evidence", "factIds", "projectId", "requestId"))
            if params["requestId"] != context.request_id or type(params["choice"]) is not dict:
                raise WebBoundaryError("WEB_REVIEW_REQUEST_INVALID")
            choice = params["choice"]
            if choice.get("kind") == "associate":
                _keys(choice, ("kind", "projectId"))
                return self._review(context, {"reviewId": params["reviewId"], "reviewHash": params["reviewHash"], "targetSubjectId": choice["projectId"]})
            if choice.get("kind") == "sources":
                if choice.get("reviewHash") != params["reviewHash"]:
                    raise WebBoundaryError("WEB_REVIEW_CHANGED")
                return self._review_sources(context, choice)
            if choice.get("kind") == "select":
                return self._review_display_choice(context, params)
            raise WebBoundaryError("WEB_REVIEW_TYPE_UNSUPPORTED")
        if params.get("kind") == "sources":
            return self._review_sources(context, params)
        _keys(params, ("reviewId", "reviewHash", "targetSubjectId"))
        info = self.host.sources.info
        # Keep the information lock across current-version validation, the
        # existing FactEngine commit and gap bookkeeping. No network in this scope.
        with info.store._lock:
            found = [r for r in self._reviews(context) if r["id"] == params["reviewId"]]
            if len(found) != 1 or found[0]["reviewHash"] != params["reviewHash"]:
                raise WebBoundaryError("WEB_REVIEW_CHANGED")
            r = found[0]
            if not r["rawAvailable"] or params["targetSubjectId"] not in {c["subjectId"] for c in r["choices"]}:
                raise WebBoundaryError("WEB_REVIEW_SCOPE_INVALID")
            if not r["text"].strip() or len(r["text"]) > 4000:
                raise WebBoundaryError("WEB_REVIEW_FULL_TEXT_REQUIRED")
            codes = set(r["gapCode"].removeprefix("semantic_coverage_incomplete:").split(","))
            assignment_codes = ASSOCIATION_GAP_CODES
            if not codes.intersection(assignment_codes):
                raise WebBoundaryError("WEB_REVIEW_REQUIRES_SEMANTIC_CORRECTION")
            obs = info.store.get_observation(r["sourceId"], r["objectId"], r["sourceVersion"])
            candidate = {"source_id": r["sourceId"], "object_id": r["objectId"], "version": r["sourceVersion"],
                "subject_id": params["targetSubjectId"], "field": "reported_feedback",
                "value": {"retentionBoundExcerpt": True}, "quote": r["text"], "assertion_type": "reported"}
            outcome = info.service.facts.process(obs, [candidate], extractor_version="workbench-attribution-v1")
            # The source statement remains unconfirmed. Assignment never affirms
            # execution, delivery, acceptance, approved dates, or permission to send.
            with info.store.transaction() as db:
                current = db.execute("SELECT current_version FROM objects WHERE source_id=? AND object_id=?", (r["sourceId"], r["objectId"])).fetchone()
                if not current or current[0] != r["sourceVersion"]:
                    raise WebBoundaryError("WEB_REVIEW_CHANGED")
                remaining = codes - assignment_codes
                if remaining:
                    db.execute("UPDATE gaps SET detail=? WHERE source_id=? AND object_id=? AND kind='extraction' AND state='open'",
                        ("semantic_coverage_incomplete:" + ",".join(sorted(remaining)), r["sourceId"], r["objectId"]))
                else:
                    db.execute("UPDATE gaps SET state='resolved',last_seen_ms=? WHERE source_id=? AND object_id=? AND kind='extraction' AND state='open'",
                        (self.now(), r["sourceId"], r["objectId"]))
        self.s.execute("INSERT OR IGNORE INTO wb_review_audit VALUES(?,?,?,?,?,?,?,?,?,?)",
            (r["id"], r["sourceId"], r["objectId"], r["sourceVersion"], params["targetSubjectId"],
             r["reviewHash"], canonical(outcome["fact_ids"]), self.host.owner, context.request_id, self.now()))
        return {"reviewId": r["id"], "subjectId": params["targetSubjectId"], "factIds": outcome["fact_ids"],
                "authority": "unconfirmed", "attributionResolved": True, "semanticReviewRemains": bool(remaining),
                "externalActions": 0}

    def _review_sources(self, context, params):
        _keys(params, ("kind", "itemId", "expectedItemVersion", "expectedSemanticVersion", "factIds", "reviewHash"))
        item = self._item(context, params["itemId"])
        snapshot = self._snapshot(context, {"projectId": item["project_ref"]})
        matches = [r for r in snapshot["semanticReviews"] if r.get("itemId") == item["id"] and r.get("nativePayload")]
        if len(matches) != 1 or matches[0]["reviewHash"] != params["reviewHash"]:
            raise WebBoundaryError("WEB_REVIEW_CHANGED")
        payload = matches[0]["nativePayload"]
        if any(params[k] != payload[k] for k in ("itemId", "expectedItemVersion", "expectedSemanticVersion", "factIds")):
            raise WebBoundaryError("WEB_REVIEW_CHANGED")
        refs = self.host.sources.resolve(item["project_ref"], params["factIds"])
        self.host.sources.refresh(refs)
        with self.host.state_transaction() as (db, information_db):
            if self.host.sources.info.store.access_version() != payload["sourceAccessVersion"]:
                raise WebBoundaryError("WEB_SOURCE_ACCESS_CHANGED")
            current = self.host.am.items.get(item["id"], db)
            sem = db.execute("SELECT * FROM action_semantics WHERE item_id=?", (item["id"],)).fetchone()
            if (current["version"], sem["version"], digest(json.loads(sem["refs"]))) != (
                    payload["expectedItemVersion"], payload["expectedSemanticVersion"], payload["oldRefsHash"]):
                raise WebBoundaryError("WEB_REVIEW_CHANGED")
            if self.host.sources.resolve(item["project_ref"], params["factIds"], connection=information_db) != refs:
                raise WebBoundaryError("WEB_REVIEW_CHANGED")
            self.host._bind_in_transaction(db, context, current, json.loads(sem["identity"]), refs,
                "am", item["id"], None, "", expected_version=sem["version"], force_review=True)
        return {"itemId": item["id"], "sourcesReviewed": True, "oldPreviewsInvalidated": True,
                "businessStateChanged": False, "externalActions": 0}

    def _review_display_choice(self, context, params):
        from am_info_sync.models import Principal
        _keys(params["choice"], ("kind", "factId"))
        project_id = _string(params["projectId"], maximum=256)
        if not context.allows(project_id):
            raise WebBoundaryError("WEB_PROJECT_SCOPE_DENIED")
        ids = params["factIds"]
        if type(ids) is not list or not ids or len(ids) > 100 or any(type(v) is not str for v in ids) or len(set(ids)) != len(ids):
            raise WebBoundaryError("WEB_REVIEW_FACTS_INVALID")
        info = self.host.sources.info
        with info.store.transaction() as connection:
            query = info.service.query(project_id, Principal(self.host.owner, self.host.tenant), connection=connection)
            conflicts = [c for c in query["conflicts"] if set(c["fact_ids"]) == set(ids)]
            selected = [f for f in query["facts"] if f["fact_id"] in ids]
            if len(conflicts) != 1 or len(selected) != len(ids) or any(not f["evidence"]["raw_available"] for f in selected):
                raise WebBoundaryError("WEB_REVIEW_CHANGED")
            chosen = params["choice"]["factId"]
            if chosen not in ids:
                raise WebBoundaryError("WEB_REVIEW_FACTS_INVALID")
            if any(f["fact_id"] != chosen and (f["protected"] or f["authority"] == "owner_confirmed") for f in selected):
                raise WebBoundaryError("PROTECTED_DECISION_REQUIRES_NATIVE_CORRECTION")
            expected_evidence = {(f["evidence"]["source_id"], f["evidence"]["object_id"], f["evidence"]["version"], f["evidence"]["quote"]) for f in selected}
            evidence = params["evidence"]
            if type(evidence) is not list or any(type(e) is not dict for e in evidence):
                raise WebBoundaryError("WEB_REVIEW_EVIDENCE_INVALID")
            supplied = {(e.get("sourceId"), e.get("objectId"), e.get("version"), e.get("quote")) for e in evidence}
            if supplied != expected_evidence:
                raise WebBoundaryError("WEB_REVIEW_CHANGED")
            identities = {canonical({"sourceId": e[0], "objectId": e[1], "version": e[2]}) for e in expected_evidence}
            ordered = [json.loads(value) for value in sorted(identities, key=lambda s: s.encode("utf-8"))]
            identity_hash = digest(ordered)
        review_id = _string(params["reviewId"], maximum=256)
        review_hash = _string(params["reviewHash"], maximum=256)
        self.s.execute("INSERT INTO wb_display_decisions VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(review_id) DO UPDATE SET review_hash=excluded.review_hash,project_id=excluded.project_id,fact_ids=excluded.fact_ids,selected_fact_id=excluded.selected_fact_id,source_identity_hash=excluded.source_identity_hash,actor=excluded.actor,request_id=excluded.request_id,created_ms=excluded.created_ms",
            (review_id, review_hash, project_id, canonical(sorted(ids)), chosen, identity_hash, self.host.owner, context.request_id, self.now()))
        return {"reviewId": review_id, "selectedFactId": chosen, "displayOnly": True,
                "formalConflictPreserved": True, "authorityChanged": False, "externalActions": 0}

    def _reminder(self, context, params):
        _keys(params, ("reminderId", "basis", "action"), ("untilMs", "requestId"))
        if params.get("requestId", context.request_id) != context.request_id:
            raise WebBoundaryError("WEB_REMINDER_REQUEST_INVALID")
        ident = _string(params["reminderId"], maximum=256)
        basis = _string(params["basis"], maximum=256)
        reminders = self._snapshot(context, {})["reminders"]
        if not any(r["id"] == ident and r["basis"] == basis for r in reminders):
            raise WebBoundaryError("WEB_REMINDER_CHANGED")
        action = params["action"]
        until = params.get("untilMs")
        if action not in {"ack", "snooze"}:
            raise WebBoundaryError("WEB_REMINDER_ACTION_INVALID")
        if action == "snooze" and (type(until) is not int or not self.now() < until <= self.now() + 31 * 86400000):
            raise WebBoundaryError("WEB_SNOOZE_TIME_INVALID")
        if action == "ack" and until is not None:
            raise WebBoundaryError("WEB_REMINDER_ACTION_INVALID")
        if action == "ack":
            previous = self.s.rows("SELECT until_ms FROM wb_reminder_presentation WHERE owner_id=? AND reminder_id=? AND basis=?",
                (self.host.owner, ident, basis))
            if previous and previous[0]["until_ms"] and previous[0]["until_ms"] > self.now():
                until = previous[0]["until_ms"]
        self.s.execute("INSERT INTO wb_reminder_presentation VALUES(?,?,?,?,?,?) ON CONFLICT(owner_id,reminder_id,basis) DO UPDATE SET state=excluded.state,until_ms=excluded.until_ms,updated_ms=excluded.updated_ms",
            (self.host.owner, ident, basis, action, until, self.now()))
        return {"reminderId": ident, "basis": basis, "state": action, "untilMs": until,
                "businessStateChanged": False, "deadlineChanged": False}

    def maintenance(self):
        """Called by the existing operator loop; no additional lifecycle/worker."""
        now = self.now()
        if getattr(self, "_next_maintenance", 0) > now:
            return
        self._next_maintenance = now + 15000
        # Purge only this adapter's presentation copies. Keep stable preview,
        # approval and occurrence identities for original receipt recovery.
        with self.s.tx() as db:
            db.execute("UPDATE wb_web_previews SET display_json='{}',invalidated=1 WHERE expires_ms<=?", (now,))
            for row in db.execute("SELECT request_id,method,result_json FROM wb_rpc_requests WHERE method IN ('prepare','revise') AND result_json IS NOT NULL").fetchall():
                saved = json.loads(row["result_json"])
                data = saved.get("data", {})
                if saved.get("ok") and data.get("previewId") and data.get("expiresAtMs", 0) <= now:
                    tombstone = self._result({"requestId": row["request_id"], "method": row["method"]}, error="WEB_PREVIEW_EXPIRED")
                    db.execute("UPDATE wb_rpc_requests SET result_json=? WHERE request_id=?", (canonical(tombstone), row["request_id"]))
        for path in self.host.operator_queue.glob("wb-*.result.json"):
            try:
                meta = path.lstat()
                if path.is_symlink() or meta.st_uid != os.getuid() or meta.st_mode & 0o077 or meta.st_size > 8 * 1024 * 1024:
                    continue
                outer = json.loads(path.read_text())
                result = outer.get("workbench", {})
                method = result.get("method")
                if method not in {"snapshot", "prepare", "revise"} or not result.get("ok"):
                    continue
                if method != "snapshot" and not result.get("data", {}).get("previewId"):
                    continue
                supplied = result.get("signature")
                unsigned = {k: v for k, v in result.items() if k != "signature"}
                if type(supplied) is not str or not hmac.compare_digest(supplied, signature(self.secret, unsigned)):
                    continue
                if result.get("data", {}).get("expiresAtMs", 0) > now:
                    continue
                tombstone = self._result(result, error="WEB_SNAPSHOT_EXPIRED" if method == "snapshot" else "WEB_PREVIEW_EXPIRED")
                self._replace_private(path, {"ok": False, "workbench": tombstone, "finished_at": self.s.clock()})
            except (OSError, ValueError, TypeError):
                continue
        # A crash before result publication may leave an already-expired claimed
        # request. Admission recovery remains in original native durable tables.
        for path in self.host.operator_queue.glob("wb-*.request.claimed"):
            try:
                meta = path.lstat()
                if path.is_symlink() or meta.st_uid != os.getuid() or meta.st_mode & 0o077 or meta.st_size > 64000:
                    continue
                value = json.loads(path.read_text())
                envelope = value.get("envelope", {})
                if value.get("operation") == "workbench" and type(envelope.get("expiresAtMs")) is int and envelope["expiresAtMs"] <= now:
                    path.unlink()
            except (OSError, ValueError, TypeError):
                continue

    @staticmethod
    def _replace_private(path, content):
        temporary = path.with_name(".wb-purge-" + secrets.token_hex(12))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(canonical(content))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()


def install_from_env(host):
    """Disabled unless an explicit private local key file is configured."""
    configured = os.environ.get("AM_WORKBENCH_KEY_FILE")
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute() or path.is_symlink():
        raise WebBoundaryError("WEB_SIGNING_KEY_FILE_INVALID")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_size > 4096:
            raise WebBoundaryError("WEB_SIGNING_KEY_FILE_INVALID")
        secret = os.read(fd, 4097)
    finally:
        os.close(fd)
    return WorkbenchAdapter(host, secret, workspace_id=os.environ.get("AM_WORKBENCH_WORKSPACE_ID"))
