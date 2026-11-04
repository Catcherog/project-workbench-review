"""Synthetic-only receive-event content and command-boundary regressions."""
import copy
import json

import pytest

from fs_agent.message_text import (
    MAX_CONTENT_BYTES, MAX_MENTIONS, MAX_NODES, MAX_PARAGRAPHS,
    MessageTextError, NormalizedMessage, normalize_message,
)


BOT = "ou_synthetic_bot"


def text_node(value, **kw):
    return {"tag": "text", "text": value, **kw}


def mention(key="@_user_1", open_id=BOT, **kw):
    return {"key": key, "id": {"open_id": open_id}, **kw}


def message(value, kind="post", mentions=None):
    out = {"message_type": kind, "content": json.dumps(value, ensure_ascii=False),
           "message_id": "om_synthetic", "create_time": "1792224000000"}
    if mentions is not None:
        out["mentions"] = mentions
    return out


def post(*paragraphs, title="", mentions=None):
    return message({"title": title, "content": list(paragraphs)}, mentions=mentions)


def normalize(value, **kw):
    return normalize_message(value, bot_open_id=BOT, **kw)


def test_received_post_extracts_split_text_and_code_style():
    msg = post([text_node("/doc", style=["codeInline"]), text_node(" sample", style=["code", "bold"])])
    assert normalize(msg) == NormalizedMessage("/doc sample", False)


def test_title_paragraphs_blank_lines_and_literal_unicode_are_preserved():
    msg = post([text_node("第一行\nsecond\tline")], [], [text_node("日本語 ／doc &amp; &#47;doc")], title="上下文")
    assert normalize(msg).text == "上下文\n第一行\nsecond\tline\n\n日本語 ／doc &amp; &#47;doc"
    assert normalize(post([text_node("&#47;doc sample", un_escape=True)])).text == "&#47;doc sample"


@pytest.mark.parametrize("target", ["@_user_1", BOT])
def test_post_bot_at_requires_structural_node_and_event_id_binding(target):
    msg = post([{"tag": "at", "user_id": target, "user_name": "任意显示名称"}, text_node("/doc sample")],
               mentions=[mention(name="显示名称也不参与判断")])
    result = normalize(msg)
    assert result.bot_mentioned and result.text.strip() == "/doc sample"
    assert normalize_message(msg).bot_mentioned is False


def test_metadata_only_or_typed_display_name_does_not_authorize_a_post():
    for value in ("/doc sample", "@机器人 /doc sample", "@_user_1 /doc sample", BOT + " /doc sample"):
        assert not normalize(post([text_node(value)], mentions=[mention()])).bot_mentioned


def test_other_at_and_all_are_not_removed_or_promoted_to_commands():
    other = post([{"tag": "at", "user_id": "@_user_2", "user_name": "/doc"}, text_node(" sample")],
                 mentions=[mention("@_user_2", "ou_other", name="/doc")])
    assert normalize(other) == NormalizedMessage("@_user_2 sample", False)
    assert normalize(post([{"tag": "at", "user_id": "all"}, text_node(" /doc sample")],
                          mentions=[mention("@_all")])) == NormalizedMessage("@all /doc sample", False)


def test_bot_removal_cannot_join_fragments_into_command():
    result = normalize(post([text_node("/d"), {"tag": "at", "user_id": "@_user_1"}, text_node("oc sample")],
                            mentions=[mention()]))
    assert result.text == "/d oc sample" and result.bot_mentioned


@pytest.mark.parametrize("tag", ["a", "img", "media", "emotion", "code_block", "md", "hr", "unknown"])
def test_non_text_tags_reject_whole_post_even_between_command_fragments(tag):
    for nodes in ([{"tag": tag, "text": "/doc sample"}],
                  [text_node("/d"), {"tag": tag, "text": "ignored"}, text_node("oc sample")],
                  [{"tag": tag}, text_node("/doc sample")]):
        with pytest.raises(MessageTextError, match="UNSUPPORTED_POST_TAG"):
            normalize(post(nodes))


def test_plain_text_exact_mention_tokens_and_other_mentions():
    result = normalize(message({"text": "@_user_1 /doc sample @_user_2"}, "text",
                               [mention(), mention("@_user_2", "ou_other")]))
    assert result == NormalizedMessage("  /doc sample @_user_2", True)
    assert normalize(message({"text": "@_user_1 /doc sample"}, "text")).bot_mentioned is False
    assert normalize(message({"text": "/doc sample"}, "text", [mention()])).bot_mentioned is False


@pytest.mark.parametrize("value", ["@_user_10 /doc sample", "x@_user_1 /doc sample", "@_user_1x /doc sample", "/d@_user_1oc sample"])
def test_plain_text_token_prefixes_are_never_partially_stripped(value):
    assert normalize(message({"text": value}, "text", [mention()])) == NormalizedMessage(value, False)


@pytest.mark.parametrize("target,mentions", [(BOT, None), (BOT, [mention(open_id="ou_other")]),
                                           ("@_user_1", [mention("@_user_2")])])
def test_post_unbound_bot_target_is_rejected(target, mentions):
    with pytest.raises(MessageTextError, match="UNBOUND_MENTION"):
        normalize(post([{"tag": "at", "user_id": target}, text_node("/doc sample")], mentions=mentions))


@pytest.mark.parametrize("mentions", ["bad", [None], [{"key": "/doc", "id": {"open_id": BOT}}],
                                     [mention(), mention(open_id="ou_other")],
                                     [{"key": "@_user_1", "id": None}],
                                     [{"key": "@_user_1", "id": {"open_id": 7}}]])
def test_malformed_or_forged_mentions_are_rejected(mentions):
    with pytest.raises(MessageTextError, match="INVALID_MENTIONS"):
        normalize(message({"text": "/doc sample"}, "text", mentions))


@pytest.mark.parametrize("body", [{}, {"content": None}, {"content": [None]}, {"content": [[None]]},
                                  {"content": [[{"tag": "text", "text": 1}]]},
                                  {"content": [[text_node("/doc sample", href="https://invalid.example")]]},
                                  {"title": None, "content": []},
                                  {"zh_cn": {"content": [[text_node("/doc sample")]]}},
                                  {"zh_cn": {"content": [[text_node("/doc sample")]]},
                                   "en_us": {"content": [[text_node("/progress sample")]]}}])
def test_malformed_or_send_locale_shapes_are_rejected(body):
    with pytest.raises(MessageTextError):
        normalize(message(body))


@pytest.mark.parametrize("raw", [None, "not-json", "[]", '"string"', '{"text":"a","text":"/doc sample"}',
                                 '{"text":NaN}', '[' * 1500 + ']' * 1500])
def test_invalid_json_is_bounded_and_never_leaks_body(raw):
    with pytest.raises(MessageTextError) as caught:
        normalize({"message_type": "text", "content": raw})
    assert str(caught.value) == caught.value.code


def test_limits_are_distinct_and_preserve_exact_boundary():
    assert normalize(post([text_node("文" * 2000)])).text == "文" * 2000
    for msg in (post([text_node("文" * 2001)]), message({"text": "x" * 6001}, "text")):
        with pytest.raises(MessageTextError, match="INPUT_TOO_LONG"):
            normalize(msg, max_chars=2000 if msg["message_type"] == "post" else 6000)
    with pytest.raises(MessageTextError, match="INPUT_TOO_LONG"):
        normalize({"message_type": "text", "content": " " * (MAX_CONTENT_BYTES + 1)})
    for msg in (post(*([[]] * (MAX_PARAGRAPHS + 1))), post([text_node("")] * (MAX_NODES + 1))):
        with pytest.raises(MessageTextError, match="STRUCTURE_TOO_LARGE"):
            normalize(msg)
    with pytest.raises(MessageTextError, match="INVALID_MENTIONS"):
        normalize(post([], mentions=[mention(f"@_user_{n}") for n in range(MAX_MENTIONS + 1)]))


@pytest.mark.parametrize("node", [text_node("a\u0000b"), text_node("\ud800"), text_node("x", style="code"),
                                  text_node("x", style=["hidden"]), text_node("x", un_escape=1)])
def test_invalid_text_and_style_are_rejected(node):
    with pytest.raises(MessageTextError):
        normalize(post([node]))


def test_original_event_fields_and_mentions_remain_untouched():
    payload = {"event": {"sender": {"sender_id": {"open_id": "ou_sender"}},
                         "message": post([{"tag": "at", "user_id": "@_user_1"}, text_node(" /doc sample")],
                                         mentions=[mention()])}}
    before = copy.deepcopy(payload)
    normalize(payload["event"]["message"])
    assert payload == before


def test_only_text_and_post_are_supported_and_empty_text_remains_a_caller_decision():
    with pytest.raises(MessageTextError, match="UNSUPPORTED_MESSAGE_TYPE"):
        normalize(message({"text": "/doc sample"}, "image"))
    assert normalize(message({"text": "  \n"}, "text")).text == "  \n"
    assert normalize(post()).text == ""


def test_received_post_accepts_identical_content_v2_without_mutation():
    nodes = [[{"tag": "at", "user_id": "@_user_1"}, text_node(" /doc sample", style=[])]]
    msg = message({"title": "", "content": nodes, "content_v2": copy.deepcopy(nodes)},
                  mentions=[mention()])
    before = copy.deepcopy(msg)
    assert normalize(msg) == NormalizedMessage("  /doc sample", True)
    assert msg == before


@pytest.mark.parametrize("alternative", [None, {}, [], [[text_node("/progress sample")]],
    [[{"tag": "md", "text": "/doc sample"}]], [[{"tag": "img", "image_key": "synthetic"}]],
    [[{"tag": "text", "text": "/doc sample", "href": "https://example.invalid"}]]])
def test_content_v2_must_not_hide_different_or_unsupported_nodes(alternative):
    msg = message({"title": "", "content": [[text_node("/doc sample")]], "content_v2": alternative})
    with pytest.raises(MessageTextError, match="POST_REPRESENTATION_MISMATCH"):
        normalize(msg)


def test_v2_does_not_relax_primary_structure_and_unknown_field_checks():
    for body in [
        {"title": "", "content_v2": [[text_node("/doc sample")]]},
        {"title": "", "content": [], "content_v2": [], "unknown": "/doc sample"},
    ]:
        with pytest.raises(MessageTextError, match="UNSUPPORTED_POST_STRUCTURE"):
            normalize(message(body))
    both = [[{"tag": "md", "text": "/doc sample"}]]
    with pytest.raises(MessageTextError, match="UNSUPPORTED_POST_TAG"):
        normalize(message({"content": both, "content_v2": copy.deepcopy(both)}))
