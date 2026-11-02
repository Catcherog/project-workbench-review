from dataclasses import dataclass
from types import SimpleNamespace
import time
import unittest
from am_style.contracts import digest, ContractError
from am_style.integration import prepare_terminal_reply
from am_style.render import make_frame
from am_style.runtime import TerminalPresenter, StaleFrame


@dataclass(frozen=True)
class Reply:
    text: str


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.binding = {"scope": ["a","b","c","d","e"], "engine_event_id": "event",
                        "source_access_version": "source", "revision": 1, "cancel_epoch": 0}
        self.envelope = SimpleNamespace(digest="a"*64, data={"binding": self.binding, "expires_at": 4102444800.0})
        self.calls = []
        self.agent = SimpleNamespace(
            response_pipeline=None,
            _guard=lambda *a: self.calls.append("guard"),
            _checkpoint=lambda *a: self.calls.append("checkpoint"))

    def projector(self, envelope):
        return make_frame(binding={"scope_id": digest(self.binding["scope"]), "turn_id": "event",
                                   "source_revision": "source", "revision": 1, "cancel_epoch": 0,
                                   "outcome_hash": envelope.digest},
                          expires_at=4102444800.0, question="谁负责？", family="query",
                          facts=[{"id": "f", "kind": "owner", "subject": "项目甲", "value": "林工"}])

    def args(self):
        return dict(presenter=TerminalPresenter(mode="shadow"), agent=self.agent,
                    ctx=SimpleNamespace(is_owner=True), reply=Reply("旧输出"), envelope=self.envelope,
                    frame_projector=self.projector, task_deadline_monotonic=time.monotonic()+3,
                    outcome_getter=lambda: self.envelope, require_current=lambda: None)

    def test_explicit_collector_operates_with_legacy_pipeline_none(self):
        reply, prepared, frame = prepare_terminal_reply(**self.args())
        self.assertEqual(reply.text, "旧输出")
        self.assertIsNotNone(prepared)
        self.assertGreater(len(self.calls), 0)

    def test_current_collector_change_prevents_fallback(self):
        args = self.args()
        args["outcome_getter"] = lambda: SimpleNamespace(digest="b"*64)
        with self.assertRaises(StaleFrame):
            prepare_terminal_reply(**args)

    def test_projector_cannot_change_scope(self):
        args = self.args()
        self.binding["scope"] = ["changed"]
        from am_style.contracts import SpeechFrame
        correct = self.projector(self.envelope).data
        correct["binding"]["scope_id"] = "wrong"
        args["frame_projector"] = lambda _: SpeechFrame.freeze(correct)
        with self.assertRaisesRegex(ContractError, "scope"):
            prepare_terminal_reply(**args)


if __name__ == "__main__":
    unittest.main()
