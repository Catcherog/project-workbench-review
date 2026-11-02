"""Pure preparation/rendering checks; no socket, model or Feishu calls."""
import copy
import json

import pytest

from fs_agent.config import BoundaryError
from fs_agent.qwen_provider import build_doc_prompt, synthetic_progress_result


def test_doc_prompt_keeps_content_without_identity_metadata_or_input_mutation():
    source = '合成项目 Aurora：阶段一已完成接口草稿；阶段二正在补齐测试。'
    history = [{"role": "user", "body": '合成资料含 "引号" 和\n换行',
                "expires": 1800086400, "scope": "synthetic-private-scope"},
               {"role": "assistant", "body": "上次合成整理结果", "task_id": "synthetic-task"}]
    original = copy.deepcopy(history)
    prompt = build_doc_prompt(source, history)
    payload = json.loads(prompt.split("\n", 1)[1])
    assert payload == {"history": [{"role": "user", "body": history[0]["body"]},
                                  {"role": "assistant", "body": history[1]["body"]}],
                       "source": source}
    assert "synthetic-private-scope" not in prompt and "synthetic-task" not in prompt
    assert "1800086400" not in prompt
    assert history == original


@pytest.mark.parametrize("source,history,error", [
    ("", [], "DOC_INPUT_INVALID"),
    ("x" * 2001, [], "DOC_INPUT_INVALID"),
    ("synthetic", [{"role": "system", "body": "untrusted instruction"}], "DOC_CONTEXT_INVALID"),
    ("synthetic", [{"role": "assistant", "body": {"text": "synthetic"}}], "DOC_CONTEXT_INVALID"),
    ("synthetic", [{"role": "user", "body": "x"}] * 9, "DOC_CONTEXT_INVALID"),
    ("synthetic", [{"role": "user", "body": "x" * 20001}], "DOC_CONTEXT_LIMIT"),
    ("synthetic", [{"role": "user", "body": '"' * 15000}], "PROMPT_INVALID"),
])
def test_doc_input_limits_fail_without_truncation(source, history, error):
    with pytest.raises(BoundaryError, match=error):
        build_doc_prompt(source, history)


def test_doc_context_at_existing_limit_is_preserved():
    history = [{"role": "assistant", "body": "合" * 2500} for _ in range(8)]
    prompt = build_doc_prompt("当前合成资料", history)
    payload = json.loads(prompt.split("\n", 1)[1])
    assert payload["history"] == history
    assert len(prompt) <= 30000


def test_progress_keeps_fixed_sample_and_identifies_code_source(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("pure progress rendering must not access the provider or network")
    monkeypatch.setattr("fs_agent.qwen_provider.LocalQwenProvider.pin", forbidden)
    monkeypatch.setattr("fs_agent.qwen_provider.LocalQwenProvider.complete", forbidden)
    monkeypatch.setattr("fs_agent.qwen_provider.LocalQwenClient.request", forbidden)
    result = synthetic_progress_result()
    assert result.text == "合成项目 Aurora：总计 5 项，已完成 3 项，进行中 2 项，阻塞 0 项，完成率 60%。"
    assert result.model == "python:synthetic-progress-v1"
    assert result.elapsed >= 0
