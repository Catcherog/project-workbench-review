"""PoC dispatch inside the existing AM bridge; never creates a socket or worker."""
from __future__ import annotations

import fcntl
import json
import time
from pathlib import Path

from .config import BoundaryError, Config
from .feishu import Feishu
from .gateway import Gateway
from .provider import atomic_json
from .qwen_provider import LocalQwenProvider
from .store import Store, scope_of

COMMANDS = {"/doc", "/progress", "/menu", "/retry", "/resend", "/chat"}


class EmbeddedPoC:
    def __init__(self, gateway: Gateway):
        self.gateway, self.store, self.config = gateway, gateway.store, gateway.config
        self.lock = None
        self.suspended = False

    @classmethod
    def open(cls, path: Path, client, *, app_id: str):
        config = Config.load(path)
        config.check_service()
        config.check_feishu()
        if (config.app_id != app_id or config.event_transport != "existing_bridge"
                or config.runtime_mode != "existing_login" or config.concurrency != 1):
            raise BoundaryError("EXISTING_BRIDGE_CONFIG_INVALID")
        lock = (config.root / "state" / "instance.lock").open("a+")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            store = Store(config.db)
            provider = LocalQwenProvider(config)
            gateway = Gateway(config, store, Feishu(config, client=client), provider)
            obj = cls(gateway)
            obj.lock = lock
            # Recover before accepting any new PoC input; no inference is rerun.
            gateway.recover()
            try:
                provider.pin()
            except BoundaryError as exc:
                store.set_meta("provider_pause", str(exc))
            obj.write_status()
            return obj
        except BaseException:
            if "gateway" in locals():
                gateway.stop()
            if "store" in locals():
                store.close()
            lock.close()
            raise

    def _mode(self, row):
        rows = self.store.rows("SELECT mode FROM bridge_mode WHERE scope=? AND expires>?",
                               (scope_of(row), self.store.clock()))
        return rows[0]["mode"] if rows else "chat"

    def ingest(self, payload) -> tuple[bool, bool]:
        """Return (belongs to PoC, newly persisted). Callback has no network I/O."""
        try:
            h, e = payload["header"], payload["event"]
            if h["app_id"] != self.config.app_id or h["tenant_key"] != self.config.tenant_key:
                return False, False
            if self.suspended:
                user = (e.get("operator", {}).get("open_id") if h["event_type"] == "card.action.trigger"
                        else e.get("sender", {}).get("sender_id", {}).get("open_id"))
                if user in self.config.users:
                    raise BoundaryError("POC_SUSPENDED")
            if h["event_type"] == "card.action.trigger":
                row = {"app": h["app_id"], "tenant": h["tenant_key"],
                       "user": e["operator"]["open_id"], "chat": e["context"]["open_chat_id"]}
                if row["user"] not in self.config.users or self._mode(row) != "poc":
                    return True, False
                return True, self.gateway.ingest(payload)
            if h["event_type"] != "im.message.receive_v1":
                return False, False
            message, sender = e["message"], e["sender"]
            if message["message_type"] != "text":
                return False, False
            text = json.loads(message["content"])["text"]
            if not isinstance(text, str):
                return False, False
            for mention in message.get("mentions", []):
                if mention.get("id", {}).get("open_id") == self.config.bot_open_id:
                    text = text.replace(mention["key"], "")
            parts = text.strip().split(maxsplit=1)
            command = parts[0] if parts else ""
            row = {"app": h["app_id"], "tenant": h["tenant_key"],
                   "user": sender["sender_id"]["open_id"], "chat": message["chat_id"]}
            if self.store.rows("SELECT 1 FROM inbox WHERE app=? AND tenant=? AND message_id=?",
                               (row["app"], row["tenant"], message["message_id"])):
                # An old PoC event cannot become a general chat after /chat or expiry.
                return True, False
            if row["user"] not in self.config.users:
                return command in COMMANDS, False
            if command not in COMMANDS and self._mode(row) != "poc":
                return False, False
            mode = "chat" if text.strip() == "/chat" else "poc"

            def save_mode(conn, event, expires):
                # Same transaction as durable receipt: a rapid next message cannot
                # escape into ordinary chat while /doc is waiting for its worker.
                if command in COMMANDS:
                    conn.execute("INSERT INTO bridge_mode VALUES (?,?,?) ON CONFLICT(scope) DO UPDATE SET "
                                 "mode=excluded.mode,expires=excluded.expires", (scope_of(event), mode, expires))

            return True, self.gateway.ingest(payload, on_insert=save_mode)
        except (KeyError, TypeError, ValueError):
            return False, False

    def step(self) -> bool:
        """Called synchronously by the one existing bridge worker, between chat jobs."""
        if self.gateway.stopping.is_set() or self.suspended:
            return False
        try:
            return self._step()
        except Exception:
            # A PoC storage/worker fault cannot terminate the existing chat worker.
            # Reject affected users' input until recovery instead of rerouting it.
            self.suspended = True
            atomic_json(self.config.root / "state" / "embedded-status.json", {
                "time": time.time(), "suspended": True, "error": "POC_WORKER_FAILED"})
            return False

    def _step(self):
        self.gateway.cleanup()
        worked = self.gateway.receive_one()
        worked = self.gateway.deliver_one() or worked
        if not self.store.meta("provider_pause"):
            task = self.store.claim(1)
            if task:
                self.gateway.run_task(task)
                worked = True
        if worked:
            self.write_status()
        return worked

    def write_status(self):
        atomic_json(self.config.root / "state" / "embedded-status.json", {
            "time": self.store.clock(), "transport": "existing_bridge", "concurrency": 1,
            "tasks": self.store.rows("SELECT state,COUNT(*) AS count FROM tasks GROUP BY state"),
            "deliveries": self.store.rows("SELECT state,COUNT(*) AS count FROM outbox GROUP BY state"),
            "provider_pause": self.store.meta("provider_pause"),
        })

    def close(self):
        self.gateway.stop()
        self.store.close()
        if self.lock:
            self.lock.close()
