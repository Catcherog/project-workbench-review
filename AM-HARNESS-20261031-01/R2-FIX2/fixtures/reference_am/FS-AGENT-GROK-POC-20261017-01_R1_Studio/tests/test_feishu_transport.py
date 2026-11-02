import asyncio
import json
from types import SimpleNamespace

import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
from lark_oapi.ws import client as ws

from fs_agent.feishu import CardAwareClient, Feishu


def test_real_sdk_dispatches_card_frame_without_network():
    called, sent = [], []
    handler = (lark.EventDispatcherHandler.builder("", "", lark.LogLevel.CRITICAL)
               .register_p2_card_action_trigger(lambda event: (called.append(event),
                    P2CardActionTriggerResponse({"toast": {"type": "info", "content": "synthetic"}}))[1])
               .build())
    client = CardAwareClient("cli_synthetic", "synthetic-not-a-secret", event_handler=handler, log_level=lark.LogLevel.CRITICAL)
    async def write(data):
        sent.append(data)
    client._write_message = write
    frame = ws.Frame()
    frame.SeqID = 1
    frame.LogID = 1
    frame.service = 1
    frame.method = 1
    for key, value in ((ws.HEADER_MESSAGE_ID, "synthetic"), (ws.HEADER_TRACE_ID, "synthetic"),
                       (ws.HEADER_SUM, "1"), (ws.HEADER_SEQ, "0"), (ws.HEADER_TYPE, "card")):
        header = frame.headers.add()
        header.key, header.value = key, value
    frame.payload = json.dumps({"schema": "2.0", "header": {
        "event_id": "synthetic", "event_type": "card.action.trigger", "app_id": "cli_synthetic", "tenant_key": "synthetic"},
        "event": {"operator": {"open_id": "ou_synthetic"}, "action": {"value": {"route": "doc"}, "tag": "button"},
                  "context": {"open_message_id": "om_synthetic", "open_chat_id": "oc_synthetic"}}}).encode()
    asyncio.run(client._handle_data_frame(frame))
    assert len(called) == 1 and len(sent) == 1
    response = ws.Frame()
    response.ParseFromString(sent[0])
    body = json.loads(response.payload)
    assert body["code"] == 200 and body["data"]


def test_sdk_socket_can_be_constructed_without_connecting():
    api = object.__new__(Feishu)
    api.config = SimpleNamespace(app_id="cli_synthetic", event_transport="standalone")
    api.secret = "synthetic-not-a-secret"
    socket = api.socket(SimpleNamespace(ingest=lambda payload: True))
    assert isinstance(socket, CardAwareClient)
