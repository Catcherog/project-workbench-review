"""Diagnostics reveal structure and fixed error codes, not received values."""
import json

from test_embedded import bridge_module


def test_post_metadata_contains_no_body_identity_or_unknown_tag_value():
    marker = 'SYNTHETIC_PRIVATE_VALUE'
    message = {'message_type': 'post', 'message_id': marker,
               'content': json.dumps({'title': marker, 'content': [[
                   {'tag': 'text', 'text': marker}, {'tag': marker, 'text': marker}]]})}
    result = bridge_module.incoming_metadata(message)
    assert result == {'normalization': 'UNSUPPORTED_POST_TAG',
                      'post_structure': 'paragraphs', 'post_node_types': ['other', 'text']}
    assert marker not in json.dumps(result)


def test_supported_post_and_invalid_json_metadata():
    result = bridge_module.incoming_metadata({'message_type': 'post',
        'content': json.dumps({'title': '', 'content': [[{'tag': 'text', 'text': '/doc sample'}]]})})
    assert result == {'normalization': 'ok', 'post_structure': 'paragraphs', 'post_node_types': ['text']}
    assert bridge_module.incoming_metadata({'message_type': 'post', 'content': '{invalid'}) == {
        'normalization': 'INVALID_JSON'}
