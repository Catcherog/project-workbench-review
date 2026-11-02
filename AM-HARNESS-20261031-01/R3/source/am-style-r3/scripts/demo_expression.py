"""Pure local demo. The sample response is a fixture, not a Qwen/Codex result."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "am-conversation-r1/src"))
import json
import time
from am_style.contracts import StylePolicy, ModelResult, canonical
from am_style.render import make_frame, render_canonical
from am_style.runtime import TerminalPresenter


class FixtureProvider:
    def generate(self, request):
        return ModelResult(canonical({"text": "林工负责星桥项目。\n测试复核需要在什么时间提醒？"}),
                           "fixture", "no-real-model", 0.0)


def main():
    frame = make_frame(
        binding={"turn_id": "synthetic-demo", "scope_id": "synthetic-owner",
                 "outcome_hash": "a"*64, "source_revision": "fixture-v1",
                 "revision": 1, "cancel_epoch": 0},
        expires_at=time.time()+60, question="星桥项目谁负责？再提醒我复核测试。",
        family="mixed",
        facts=[{"id": "owner", "kind": "owner", "subject": "星桥项目", "value": "林工"}],
        gaps=[{"id": "reminder-time", "slot": "time", "object": "测试复核"}],
    )
    presenter = TerminalPresenter(FixtureProvider(), mode="enforce", policy=StylePolicy())
    result = presenter.prepare(frame, legacy_text="旧回复", guard=lambda frame: None,
                               task_deadline_monotonic=time.monotonic()+3)
    print(json.dumps({"kind": "synthetic_fixture_only", "canonical": render_canonical(frame),
                      "prepared_text": result.text, "metrics": result.metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
