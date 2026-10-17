from __future__ import annotations

import base64
import http
import json
import time
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.contact.v3 import GetUserRequest
from lark_oapi.api.im.v1 import (CreateFileRequest, CreateFileRequestBody, CreateMessageRequest,
                                CreateMessageRequestBody)
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
from lark_oapi.ws import client as ws

from .config import BoundaryError, Config


class SendRejected(BoundaryError):
    pass


class SendUnknown(BoundaryError):
    pass


class CardAwareClient(ws.Client):
    """Narrow lark-oapi 1.7.5 CARD-frame fix; no payload or exception-body logging."""

    async def _handle_data_frame(self, frame):
        hs = frame.headers
        msg_id = ws._get_by_key(hs, ws.HEADER_MESSAGE_ID)
        count = int(ws._get_by_key(hs, ws.HEADER_SUM))
        seq = int(ws._get_by_key(hs, ws.HEADER_SEQ))
        kind = ws.MessageType(ws._get_by_key(hs, ws.HEADER_TYPE))
        payload = frame.payload
        if count > 1:
            payload = self._combine(msg_id, count, seq, payload)
            if payload is None:
                return
        if kind not in (ws.MessageType.EVENT, ws.MessageType.CARD):
            return
        response = ws.Response(code=http.HTTPStatus.OK)
        try:
            start = time.monotonic()
            result = self._event_handler._do_without_validation(payload)
            header = hs.add()
            header.key = ws.HEADER_BIZ_RT
            header.value = str(int((time.monotonic() - start) * 1000))
            if result is not None:
                response.data = base64.b64encode(lark.JSON.marshal(result).encode())
        except Exception:
            # A failed commit is not acknowledged as accepted; Feishu may redeliver.
            response = ws.Response(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)
        frame.payload = lark.JSON.marshal(response).encode()
        await self._write_message(frame.SerializeToString())


class Feishu:
    def __init__(self, config: Config, *, client=None):
        self.config = config
        if client is not None:
            self.client = client
            self.secret = None
            return
        self.secret = config.read_secret(config.app_secret_file)
        self.client = (lark.Client.builder().app_id(config.app_id).app_secret(self.secret)
                       .timeout(10).log_level(lark.LogLevel.CRITICAL).build())

    def authorized(self, row) -> bool:
        c = self.config
        origin_type = row.get("origin_chat_type", row["chat_type"])
        if (row["app"] != c.app_id or row["tenant"] != c.tenant_key or row["user"] not in c.users
                or row["chat_type"] not in ("p2p", "group")
                or (origin_type == "group" and row["chat"] not in c.chats)):
            return False
        try:
            request = (GetUserRequest.builder().user_id(row["user"]).user_id_type("open_id")
                       .department_id_type("open_department_id").build())
            response = self.client.contact.v3.user.get(request)
            if not response.success() or not response.data or not response.data.user:
                return False
            user = response.data.user
            if user.open_id != row["user"]:
                return False
            status = user.status
            if not status or status.is_activated is not True or any(
                    getattr(status, key, False) for key in ("is_resigned", "is_frozen", "is_exited")):
                return False
            departments = set(user.department_ids or [])
            allowed = set(c.departments)
            return bool(departments & allowed) if c.department_match == "any_exact" else bool(departments) and departments <= allowed
        except Exception:
            return False

    def send(self, row, guard):
        kind = row["kind"]
        if not guard():
            raise SendRejected("DELIVERY_AUTH_OR_TTL")
        if kind == "file":
            path = Path(row["artifact"])
            expected = self.config.root / "artifacts" / f"{row['task_id']}.md"
            if path != expected or path.is_symlink() or not path.is_file():
                raise SendRejected("ARTIFACT_PATH_INVALID")
            try:
                with path.open("rb") as stream:
                    body = (CreateFileRequestBody.builder().file_type("stream").file_name(path.name).file(stream).build())
                    response = self.client.im.v1.file.create(CreateFileRequest.builder().request_body(body).build())
            except Exception:
                # No message send was attempted. An orphan upload contains only synthetic data.
                raise SendRejected("FILE_UPLOAD_FAILED") from None
            if not response.success():
                raise SendRejected(f"FILE_UPLOAD_{response.code}")
            content = json.dumps({"file_key": response.data.file_key})
        elif kind == "interactive":
            content = row["body"]
        else:
            content = json.dumps({"text": row["body"]}, ensure_ascii=False)
        # Contact/TTL checked again after uploads and immediately before publishing.
        if not guard():
            raise SendRejected("DELIVERY_AUTH_OR_TTL")
        target_type = "open_id" if row["chat_type"] == "p2p" else "chat_id"
        target = row["user"] if target_type == "open_id" else row["chat"]
        request = (CreateMessageRequest.builder().receive_id_type(target_type).request_body(
            CreateMessageRequestBody.builder().receive_id(target).msg_type(kind)
            .content(content).uuid(row["id"]).build()).build())
        try:
            response = self.client.im.v1.message.create(request)
        except Exception:
            raise SendUnknown("SEND_RECEIPT_UNKNOWN") from None
        if not response.success():
            raise SendRejected(f"FEISHU_{response.code}")
        if not response.data or not response.data.message_id:
            raise SendUnknown("SEND_RECEIPT_MISSING")
        return response.data.message_id

    def socket(self, gateway):
        if self.config.event_transport == "existing_bridge":
            # AM221D221 already has a live consumer. Integration must dispatch
            # through that process instead of opening a competing connection.
            raise BoundaryError("EXISTING_BRIDGE_REQUIRED")
        def receive(data):
            gateway.ingest(json.loads(lark.JSON.marshal(data)))

        def card(data):
            accepted = gateway.ingest(json.loads(lark.JSON.marshal(data)))
            return P2CardActionTriggerResponse({"toast": {
                "type": "info", "content": "已记录，正在核验权限" if accepted else "已处理或不在测试范围"
            }})

        handler = (lark.EventDispatcherHandler.builder("", "", lark.LogLevel.CRITICAL)
                   .register_p2_im_message_receive_v1(receive).register_p2_card_action_trigger(card).build())
        return CardAwareClient(self.config.app_id, self.secret, event_handler=handler, log_level=lark.LogLevel.CRITICAL)
