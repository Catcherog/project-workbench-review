"""V02 false-positive fix and adjacent negative-scope regressions."""
import pytest
from info_semantics import coverage_report


def fact(field,quote,**values):
    return dict(subject_id='p',field=field,quote=quote,value=values.get('value',quote),assertion_type='reported')


@pytest.mark.parametrize('text', ['没有开测记录', '没有开测证据', '没有开始测试的记录'])
def test_lack_of_execution_evidence_can_remain_acceptance(text):
    report=coverage_report(text,[fact('acceptance',text)])
    assert report['issues']==[]
    assert report['semantic_acceptance']=='requires_review'


@pytest.mark.parametrize('text', ['尚未开测','没有开测','没有开始测试'])
def test_explicit_non_execution_still_requires_progress(text):
    assert 'execution_dimension' in coverage_report(text,[fact('acceptance',text)])['issues']
    assert 'execution_dimension' not in coverage_report(text,[fact('progress',text)])['issues']


def test_actual_non_execution_not_waived_by_evidence_clause_in_same_unit():
    text='没有开测记录且实际尚未开测'
    assert 'execution_dimension' in coverage_report(text,[fact('acceptance',text)])['issues']


def test_absent_evidence_cannot_drop_negation_or_attribution():
    text='工程师说没有开测记录'
    issues=coverage_report(text,[fact('acceptance','开测记录')])['issues']
    assert 'attribution_uncovered' in issues
    assert 'candidate_scope_incomplete' in issues


def test_correct_full_attribution_and_negation_remain_accepted_for_review():
    text='工程师说没有开测记录'
    assert coverage_report(text,[fact('acceptance',text)])['issues']==[]


def test_published_v02_output_replay_without_new_model_call():
    # Exact text/candidates from fixed R1-FIX2 V02_CONDITION evidence. This is
    # a development regression, not new gold or an independent test sample.
    text='演示项目温箱校准结束之后方能做耐久测试；校准尚未结束；目前没有开测记录。'
    values=[fact('constraint','温箱校准结束之后方能做耐久测试'),
            fact('progress','校准尚未结束'),fact('acceptance','目前没有开测记录')]
    assert coverage_report(text,values,subject_titles=('演示项目',))['issues']==[]
