"""Final payload regression tests for the two host overlay seams.

Compile only the delivered functions/classes to avoid loading a production host.
The SQLite transaction is real; platform transport and business actions are not.
The separate native-host probe verifies the same insertion order with Store.
"""
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest

from am_style.contracts import digest


ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "overlay/am-conversation-r1/src/am_response/gateway.py"
TERMINAL = ROOT / "overlay/am-conversation-r1/src/am_conversation/terminal.py"


class ContractFailure(RuntimeError):
    """Stand-in exception class only; the gate's decisions are original code."""


namespace = {"json": json, "fingerprint": digest, "encode": lambda x: json.dumps(x, ensure_ascii=False),
             "ConversationError": ContractFailure}
tree = ast.parse(GATEWAY.read_text(encoding="utf-8"), filename=str(GATEWAY))
nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
         and node.name in ("require_terminal_rendered_payload", "GatewayProjection")]
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(GATEWAY), "exec"), namespace)
require_payload = namespace["require_terminal_rendered_payload"]
GatewayProjection = namespace["GatewayProjection"]

tree = ast.parse(TERMINAL.read_text(encoding="utf-8"), filename=str(TERMINAL))
terminal_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TerminalExpression")
finish = next(node for node in terminal_class.body if isinstance(node, ast.FunctionDef) and node.name == "finish")
finish_namespace = {}
exec(compile(ast.Module(body=[finish], type_ignores=[]), str(TERMINAL), "exec"), finish_namespace)
finish_under_review = finish_namespace["finish"]


TEXT = "演示项目由林工负责。\n尚待确认，未执行。\n给林工发送：请核对进度。"


def payload(selected="candidate", mode="enforce", text=TEXT):
    return {"schema_version": "am-terminal/3", "semantic_hash": digest(text),
            "expires_at": 4102444800,
            "prepared": {"text": text, "selected": selected,
                         "metrics_json": json.dumps({"mode": mode, "adopted": selected == "candidate"}),
                         "frame_fingerprint": "f"*64},
            "frame": {"test": "synthetic-final-payload"},
            "outcome": {"binding": {"origin_event_id": "event", "engine_event_id": "event",
                                      "scope": ["t", "a", "u", "c", ""]},
                        "completion": "awaiting_approval", "dependencies": {}}}


class StoreFixture:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE outbox(id TEXT PRIMARY KEY,state TEXT,kind TEXT,body TEXT,artifact TEXT,message_id TEXT,error TEXT)")
    clock = staticmethod(lambda: 100)
    @contextmanager
    def tx(self):
        with self.conn:
            yield self.conn


class FinalPayloadTests(unittest.TestCase):
    def test_candidate_and_canonical_require_identical_final_text(self):
        for selected in ("candidate", "canonical"):
            with self.subTest(selected=selected):
                self.assertTrue(require_payload(payload(selected), "text", TEXT, None))
                with self.assertRaisesRegex(ContractFailure, "TERMINAL_RENDERED_PAYLOAD_MISMATCH"):
                    require_payload(payload(selected), "text", "给林工发送：请核对进度。", None)

    def test_late_common_ui_phrase_rewrite_cannot_keep_old_semantic_hash(self):
        text = "请带上预览中的动作编号。"
        changed = text.replace("带上预览中的动作编号", "说明预览中的事项序号")
        with self.assertRaisesRegex(ContractFailure, "TERMINAL_RENDERED_PAYLOAD_MISMATCH"):
            require_payload(payload(text=text), "text", changed, None)

    def test_unsupported_transport_and_hash_rebinding_are_refused(self):
        for kind, body, artifact in (("interactive", TEXT, None), ("file", TEXT, "file.pdf"),
                                      ("text", TEXT, "file.pdf"), ("text", None, None)):
            with self.subTest(kind=kind, artifact=artifact, body=body), self.assertRaises(ContractFailure):
                require_payload(payload(), kind, body, artifact)
        changed = payload()
        changed["semantic_hash"] = digest("不同内容")
        with self.assertRaises(ContractFailure):
            require_payload(changed, "text", TEXT, None)
        changed = payload()
        changed["prepared"]["text"] = "变更后的正文"
        changed["semantic_hash"] = digest(TEXT)
        with self.assertRaises(ContractFailure):
            require_payload(changed, "text", TEXT, None)

    def test_legacy_shadow_retains_original_display_behavior(self):
        for mode in ("shadow", "off"):
            with self.subTest(mode=mode):
                self.assertFalse(require_payload(payload("legacy", mode), "text", "原 UI 改写正文", None))
        for selected, mode in (("unknown", "enforce"), ("legacy", "enforce"), ("candidate", "shadow")):
            with self.subTest(selected=selected, mode=mode), self.assertRaises(ContractFailure):
                require_payload(payload(selected, mode), "text", TEXT, None)

    def test_original_outbox_transaction_rolls_back_on_dropped_query_fact(self):
        store = StoreFixture()
        try:
            gateway = GatewayProjection(store)
            row = {"id": "event", "tenant": "t", "app": "a", "user": "u", "chat": "c",
                   "expires": 4102444800, "_response_v3": payload()}
            displayed = "给林工发送：请核对进度。"
            with self.assertRaisesRegex(ContractFailure, "TERMINAL_RENDERED_PAYLOAD_MISMATCH"):
                with store.tx() as conn:
                    # Same order as the original Store.add_outbox: insert then bind.
                    conn.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", ("out", "pending", "text", displayed, None, None, None))
                    gateway.bind(conn, row, "out", "text", displayed, None)
            self.assertEqual(store.conn.execute("SELECT count(*) FROM outbox").fetchone()[0], 0)
            self.assertEqual(store.conn.execute("SELECT count(*) FROM am_response_outbox_v2").fetchone()[0], 0)
            with store.tx() as conn:
                conn.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,?)", ("out", "pending", "text", TEXT, None, None, None))
                gateway.bind(conn, row, "out", "text", TEXT, None)
            self.assertEqual(store.conn.execute("SELECT count(*) FROM outbox").fetchone()[0], 1)
            self.assertEqual(store.conn.execute("SELECT state FROM am_response_outbox_v2").fetchone()[0], "queued")
        finally:
            store.conn.close()

    def test_both_preview_states_keep_legacy_and_receive_no_semantic_credit(self):
        for status in ("needs_confirmation", "knowledge_candidate"):
            with self.subTest(status=status):
                observations = []
                def forbidden():
                    raise AssertionError("UI preview states must stop before collection/projection/model")
                self_stub = SimpleNamespace(collector=SimpleNamespace(state=lambda: {}, envelope=forbidden),
                                            observer=observations.append)
                reply = SimpleNamespace(event_id="event", status=status, text=TEXT)
                actual = finish_under_review(self_stub, None, None, reply, deadline=30)
                self.assertIs(actual, reply)
                self.assertEqual(actual.text, TEXT)
                self.assertEqual(observations, [{"event_id": "event", "status": "unsupported",
                                  "reason": "legacy_ui_rewrite_requires_final_contract", "calls": 0}])


if __name__ == "__main__":
    unittest.main()
