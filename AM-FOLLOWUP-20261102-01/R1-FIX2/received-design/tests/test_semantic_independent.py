import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from am_info_sync.extraction import ExtractionError
from am_info_sync.models import Observation
from info_extraction import BoundedCoordinatorExtractor


def fact(quote, value=None, *, field='progress', subject='a'):
    return dict(subject_id=subject, field=field, quote=quote,
                value=quote if value is None else value, assertion_type='reported')


def extract(text, candidates):
    provider = Mock()
    provider.complete.return_value = SimpleNamespace(text=json.dumps(
        dict(complete=True, candidates=candidates), ensure_ascii=False))
    extractor = BoundedCoordinatorExtractor(provider, lambda observation: {
        'allowed_subject_ids': ['a', 'b'],
        'subjects': [dict(subject_id='a', title='演示甲项目'),
                     dict(subject_id='b', title='演示乙项目')]})
    return extractor(Observation('synthetic', 'review', 'v1', 100, text=text))


@pytest.mark.parametrize(('text', 'candidate'), [
    ('设备到场后才能开始测试', fact('设备到场后才能开始测试', '开始测试')),
    ('评审通过后方可发出测试报告', fact('评审通过后方可发出测试报告', '发出测试报告')),
    ('审批通过才可以交付材料', fact('审批通过才可以交付材料', '审批通过', field='review')),
])
def test_implicit_condition_not_dropped_from_value(text, candidate):
    with pytest.raises(ExtractionError, match='semantic_coverage_incomplete'):
        extract(text, [candidate])


@pytest.mark.parametrize('text', ['尚未通过评审', '评审不通过'])
def test_negative_review_cannot_be_execution_progress(text):
    with pytest.raises(ExtractionError, match='semantic_coverage_incomplete'):
        extract(text, [fact(text, field='progress')])


def test_known_named_project_cannot_be_assigned_to_other_allowed_project():
    text = '演示甲项目材料已交付'
    with pytest.raises(ExtractionError, match='semantic_coverage_incomplete|subject_'):
        extract(text, [fact(text, subject='b', field='delivery')])


def test_random_unrelated_greeting_can_have_no_project_facts():
    assert extract('今天天气很好，祝你生日快乐。', []) == []


def test_empty_complete_cannot_hide_delivery():
    with pytest.raises(ExtractionError, match='semantic_coverage_incomplete'):
        extract('材料并未交付', [])


def test_unsupported_field_and_subject_are_rejected():
    for candidate in [fact('材料并未交付', field='bogus'),
                      fact('材料并未交付', subject='outside')]:
        with pytest.raises(ExtractionError, match='invalid_output_schema|subject_outside_context'):
            extract('材料并未交付', [candidate])
