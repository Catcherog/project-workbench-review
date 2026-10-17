from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import BoundaryError, Config
from .feishu import SendRejected, SendUnknown
from .provider import group_alive, process_identity, stop_group
from .qwen_provider import api_request_unknown, discard_payload
from .store import Store

FIXTURES = {
    "doc": "合成资料：项目 Aurora 测试版；目标为验证离线文档流程；阶段一已完成接口草稿，阶段二正在补齐测试；无真实人员与业务信息。请整理为简洁中文摘要。",
    "progress": "合成项目 Aurora：总计 5 项，已完成 3 项，进行中 2 项，阻塞 0 项。请用中文说明当前进度，不编造信息。",
}


def menu_card(nonce):
    return {"config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "合成测试入口"}},
            "elements": [{"tag": "div", "text": {"tag": "plain_text", "content": "选择入口后发送 sample。仅使用固定合成数据。/chat 返回普通聊天。"}},
                         {"tag": "action", "actions": [
                             {"tag": "button", "text": {"tag": "plain_text", "content": label},
                              "type": "primary", "value": {"nonce": nonce, "route": route}}
                             for route, label in (("doc", "合成文档"), ("progress", "合成进度"))]}]}


class Gateway:
    def __init__(self, config: Config, store: Store, api, provider):
        self.config, self.store, self.api, self.provider = config, store, api, provider
        self.pool = ThreadPoolExecutor(max_workers=config.concurrency, thread_name_prefix="model")
        self.stopping = threading.Event()
        self.threads = []

    def ingest(self, payload: dict, *, on_insert=None) -> bool:
        """Only normalize, hard-allowlist and commit. No network/model work in the callback."""
        try:
            header, event = payload["header"], payload["event"]
            if header["app_id"] != self.config.app_id or header["tenant_key"] != self.config.tenant_key:
                return False
            row = {"app": header["app_id"], "tenant": header["tenant_key"], "event_id": header["event_id"]}
            if header["event_type"] == "im.message.receive_v1":
                sender, message = event["sender"], event["message"]
                if sender["sender_type"] != "user" or sender.get("tenant_key") != self.config.tenant_key:
                    return False
                user = sender["sender_id"]["open_id"]
                if user not in self.config.users or message["message_type"] != "text":
                    return False
                chat, chat_type = message["chat_id"], message["chat_type"]
                if chat_type not in ("p2p", "group") or (chat_type == "group" and chat not in self.config.chats):
                    return False
                content = json.loads(message["content"])["text"]
                if not isinstance(content, str) or len(content) > 2000:
                    return False
                mentions = [m for m in message.get("mentions", []) if m.get("id", {}).get("open_id") == self.config.bot_open_id]
                if chat_type == "group" and not mentions:
                    return False
                for mention in mentions:
                    content = content.replace(mention["key"], "")
                row.update(user=user, chat=chat, chat_type=chat_type, kind="message", body=content.strip(),
                           message_id=message["message_id"], source_time=int(message["create_time"]) / 1000)
            elif header["event_type"] == "card.action.trigger":
                user = event["operator"]["open_id"]
                value, context = event["action"]["value"], event["context"]
                if user not in self.config.users or value.get("route") not in FIXTURES:
                    return False
                menus = self.store.rows("SELECT o.chat_type FROM outbox o WHERE o.nonce=? AND o.user=? AND o.chat=? AND o.state='sent'",
                                        (value["nonce"], user, context["open_chat_id"]))
                if not menus:
                    return False
                row.update(user=user, chat=context["open_chat_id"], chat_type=menus[0]["chat_type"],
                           kind="card", body=value["route"], nonce=value["nonce"],
                           source_message=context["open_message_id"], source_time=self.store.clock())
            else:
                return False
        except (KeyError, ValueError, TypeError):
            return False
        return self.store.put(row, on_insert=on_insert)

    def authorized(self, row) -> bool:
        # Local invariants still hold with an injected/test transport.
        c = self.config
        origin_type = row.get("origin_chat_type", row["chat_type"])
        return (row["expires"] > self.store.clock() and row["app"] == c.app_id
                and row["tenant"] == c.tenant_key and row["user"] in c.users
                and (origin_type == "p2p" or origin_type == "group" and row["chat"] in c.chats)
                and self.api.authorized(row))

    def receive_one(self):
        rows = self.store.pending_inbox()
        if not rows:
            return False
        row = rows[0]
        if not self.authorized(row):
            self.store.execute("UPDATE inbox SET state='denied',body=NULL WHERE seq=?", (row["seq"],))
            return True
        if self.store.clock() >= row["received"] + 600:
            self.store.execute("UPDATE inbox SET state='queue_timeout',body=NULL WHERE seq=?", (row["seq"],))
            return True
        text = row["body"] or ""
        if text == "/chat" and row["kind"] == "message":
            self.store.select(row, None)
            self.store.add_outbox(row, text="已返回普通聊天。发送 /doc sample 或 /progress sample 可重新进入合成测试。")
        elif text in ("/help", "/status") and row["kind"] == "message":
            self.store.add_outbox(row, text="当前为两人合成测试。/doc sample 生成合成文档；/progress sample 查看合成进度；/menu 切换；/chat 返回普通聊天。")
        elif row["kind"] == "card":
            if self.store.valid_card(row):
                self.store.select(row, text)
                self.store.add_outbox(row, text=f"已选择 /{text}，发送 sample 运行合成样例。")
        elif text.startswith("/retry ") or text.startswith("/resend "):
            operation, task_id = text.split(maxsplit=1)
            ok = (self.store.retry if operation == "/retry" else self.store.resend)(row, task_id)
            self.store.add_outbox(row, text="已记录操作。" if ok else "当前不能执行该操作；任务可能已过期、超出排队期限，或发送回执仍未知。")
        else:
            parts = text.split(maxsplit=1)
            route = self.store.selection(row)["route"]
            argument = text
            if parts and parts[0] in ("/doc", "/progress"):
                route = parts[0][1:]
                self.store.select(row, route)
                argument = parts[1] if len(parts) == 2 else ""
            if text == "/menu" or not text or not route:
                nonce = self.store.menu(row)
                self.store.add_outbox(row, card=menu_card(nonce), nonce=nonce)
            elif argument == "sample":
                self.store.enqueue(row, route)
            else:
                self.store.add_outbox(row, text=f"当前为 /{route} 合成测试。发送 sample，或用 /menu 切换。")
        self.store.execute("UPDATE inbox SET state='handled',body=NULL WHERE seq=?", (row["seq"],))
        return True

    def run_task(self, task):
        try:
            if not self.authorized(task):
                raise BoundaryError("EXECUTION_AUTH_DENIED")
            if self.store.clock() >= task["queue_deadline"]:
                raise BoundaryError("QUEUE_TIMEOUT")
            history = self.store.history(task)
            # Bound context without copying old items into a new timestamp.
            history = history[-8:]
            while history and sum(len(r["body"]) for r in history) > 20000:
                history.pop(0)
            expires = min([task["expires"]] + [r["expires"] for r in history])
            prompt = FIXTURES[task["route"]]
            context = json.dumps([{k: r[k] for k in ("role", "body")} for r in history], ensure_ascii=False)
            full_prompt = "只处理以下合成文本。不调用工具，不决定权限、路由、路径或发送对象。\n历史合成上下文：" + context + "\n当前合成资料：" + prompt
            def started(pgid, identity):
                self.store.execute("UPDATE tasks SET pgid=?,process_identity=? WHERE id=? AND run_id=? AND state='running'",
                                   (pgid, identity, task["id"], task["run_id"]))
            result = self.provider.complete(full_prompt, run_id=task["run_id"],
                                            timeout=min(120, expires - self.store.clock()), on_start=started)
            if expires <= self.store.clock():
                raise BoundaryError("CONTENT_EXPIRED")
            artifact = None
            if task["route"] == "doc":
                path = self.config.root / "artifacts" / f"{task['id']}.md"
                if path.is_symlink():
                    raise BoundaryError("ARTIFACT_PATH_INVALID")
                # Model text is only content inside a fixed file, never a path or template instruction.
                path.write_text(f"# 合成文档\n\n任务编号：{task['id']}\n\n用途：PoC 合成测试\n\n## 整理结果\n\n{result.text}\n")
                path.chmod(0o600)
                artifact = str(path)
            if not self.store.complete(task, prompt, result, expires=expires, artifact=artifact):
                if artifact:
                    Path(artifact).unlink(missing_ok=True)
                raise BoundaryError("LATE_RESULT_REJECTED")
        except BoundaryError as exc:
            error = str(exc)
            state = "stop_unknown" if error == "STOP_UNKNOWN" else "timed_out" if error == "EXECUTION_TIMEOUT" else "failed"
            self.store.finish(task, state, error)
            if error in ("AUTH_FAILED", "QUOTA_EXHAUSTED", "RATE_LIMITED", "LOCAL_API_UNAVAILABLE",
                         "LOCAL_MODEL_CHANGED", "LOCAL_PROVIDER_PIN_CHANGED", "STOP_UNKNOWN"):
                self.store.set_meta("provider_pause", error)
                owner = dict(task, user=self.config.owner, chat_type="p2p")
                self.store.add_outbox(owner, text=f"测试入口的新推理已暂停：{error}。已有结果仍可交付。")
            self.store.add_outbox(task, text=f"任务 {task['id']} 未完成：{error}。")
        except Exception:
            self.store.finish(task, "failed", "INTERNAL_ERROR")

    def schedule_one(self):
        if self.stopping.is_set() or self.store.meta("provider_pause"):
            return False
        task = self.store.claim(self.config.concurrency)
        if not task:
            return False
        self.pool.submit(self.run_task, task)
        return True

    def deliver_one(self):
        rows = self.store.rows("SELECT * FROM outbox WHERE state='pending' AND expires>? ORDER BY created,rowid LIMIT 1", (self.store.clock(),))
        if not rows:
            return False
        row = rows[0]
        if row["nonce"]:
            menus = self.store.rows("SELECT m.version,s.version AS current FROM menus m JOIN selection s ON s.scope=m.scope WHERE m.nonce=?", (row["nonce"],))
            if not menus or menus[0]["version"] != menus[0]["current"]:
                self.store.execute("UPDATE outbox SET state='rejected',error='STALE_CARD' WHERE id=?", (row["id"],))
                return True
        if not self.authorized(row):
            self.store.execute("UPDATE outbox SET state='rejected',error='DELIVERY_AUTH_OR_TTL' WHERE id=?", (row["id"],))
            return True
        if not self.store.execute("UPDATE outbox SET state='sending' WHERE id=? AND state='pending'", (row["id"],)):
            return True
        try:
            message_id = self.api.send(row, lambda: self.authorized(row))
            with self.store.tx() as c:
                c.execute("UPDATE outbox SET state='sent',message_id=? WHERE id=?", (message_id, row["id"]))
                if row["nonce"]:
                    c.execute("UPDATE menus SET message_id=? WHERE nonce=?", (message_id, row["nonce"]))
        except SendRejected as exc:
            self.store.execute("UPDATE outbox SET state='rejected',error=? WHERE id=?", (str(exc), row["id"]))
        except (SendUnknown, Exception):
            self.store.execute("UPDATE outbox SET state='unknown',error='SEND_RECEIPT_UNKNOWN' WHERE id=?", (row["id"],))
        return True

    def recover(self):
        # Recovery never reruns inference. Kill only a journalled, still-identical owned leader.
        unknown_runs = set()
        known_api_runs = set()
        def clean_or_hold(directory):
            if self.config.provider_kind == "local_qwen_api":
                if api_request_unknown(directory):
                    discard_payload(directory)
                    unknown_runs.add(directory.name)
                    return
                known_api_runs.add(directory.name)
            shutil.rmtree(directory)
        for directory in (self.config.root / "tasks").iterdir():
            if directory.is_symlink() or not re.fullmatch(r"[a-f0-9]{32}", directory.name):
                self.store.set_meta("provider_pause", "UNRECOGNIZED_TASK_DIRECTORY")
                continue
            try:
                data = json.loads((directory / "process.json").read_text())
                pgid = data.get("pgid")
                if data["state"] == "stopped" or (pgid and not group_alive(pgid)):
                    clean_or_hold(directory)
                    continue
                identity = process_identity(pgid) if pgid else ""
                owned = identity.split()[:2] == [str(os.getuid()), str(pgid)]
                if pgid and owned and identity == data.get("identity") and stop_group(pgid):
                    clean_or_hold(directory)
                else:
                    unknown_runs.add(directory.name)
            except Exception:
                unknown_runs.add(directory.name)
        # A missing temporary directory is not evidence that a journalled process stopped.
        for task in self.store.rows("SELECT * FROM tasks WHERE state IN ('running','stop_unknown')"):
            pgid = task["pgid"]
            if pgid and group_alive(pgid):
                identity = process_identity(pgid)
                owned = identity.split()[:2] == [str(os.getuid()), str(pgid)]
                if not (owned and identity == task["process_identity"] and stop_group(pgid)):
                    unknown_runs.add(task["run_id"])
            if self.config.provider_kind == "local_qwen_api" and task["run_id"] not in known_api_runs:
                unknown_runs.add(task["run_id"])
        with self.store.tx() as c:
            for run_id in unknown_runs:
                c.execute("UPDATE tasks SET state='stop_unknown',error='STOP_UNKNOWN' WHERE run_id=?", (run_id,))
                if c.execute("SELECT changes()").fetchone()[0] == 0:
                    c.execute("INSERT INTO meta VALUES ('provider_pause','ORPHAN_STOP_UNKNOWN') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
            for task in c.execute("SELECT id,run_id FROM tasks WHERE state IN ('running','stop_unknown')").fetchall():
                if task["run_id"] not in unknown_runs:
                    c.execute("UPDATE tasks SET state='interrupted',error='RESTART_INTERRUPTED',pgid=NULL,process_identity=NULL WHERE id=?", (task["id"],))
            c.execute("UPDATE outbox SET state='unknown',error='RESTART_SEND_UNKNOWN' WHERE state='sending'")
        self.cleanup()

    def cleanup(self):
        for value in self.store.cleanup():
            path = Path(value)
            if path.parent == self.config.root / "artifacts" and re.fullmatch(r"[a-f0-9]{32}\.md", path.name):
                path.unlink(missing_ok=True)
        # Files created immediately before a crash but never committed are also reclaimed.
        live = {r["artifact"] for r in self.store.rows("SELECT artifact FROM outbox WHERE artifact IS NOT NULL AND expires>?", (self.store.clock(),))}
        active = {r["id"] + ".md" for r in self.store.rows("SELECT id FROM tasks WHERE state IN ('running','stop_unknown')")}
        for path in (self.config.root / "artifacts").glob("*.md"):
            if str(path) not in live and path.name not in active and not path.is_symlink():
                path.unlink()

    def start(self):
        self.recover()
        def loop(action, interval):
            while not self.stopping.is_set():
                try:
                    action()
                except Exception:
                    self.store.set_meta("worker_error", action.__name__)
                self.stopping.wait(interval)
        for action, interval in ((self.receive_one, .1), (self.schedule_one, .1), (self.deliver_one, .1), (self.cleanup, 1)):
            thread = threading.Thread(target=loop, args=(action, interval), daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self):
        self.stopping.set()
        # Running calls remain bounded by their original 120-second deadlines.
        self.pool.shutdown(wait=True)
        for thread in self.threads:
            thread.join(timeout=12)
