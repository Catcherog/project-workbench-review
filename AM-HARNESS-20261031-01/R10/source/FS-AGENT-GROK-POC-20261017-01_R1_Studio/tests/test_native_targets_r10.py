"""Offline R10 native contracts. IDs are synthetic; no native acceptance is claimed."""
import copy
import time

import pytest

from fs_agent.config import BoundaryError
from fs_agent.document_delivery import discover_targets
from fs_agent.document_target import (binding_config, field_value, immutable_binding,
                                      validate_metadata, validate_project_metadata)
from fs_agent.meegle_port import BusinessNotStarted
from test_doc_logic import rig, ready
from test_gateway import rig as base_rig
from test_meegle_port import port_fixture


@pytest.fixture
def native_rig(rig):
    g, store, row, draft = ready(rig)
    port, state, settings = port_fixture(g)
    binding = settings['targets']['report']
    binding['project_code_field'] = 'project-code'
    state['project_attribute']['work_item_name'] = '合成项目名称不包含编号'
    state['project_fields'] = [{'key': 'project-code', 'value': 'IRAD-2099-001'}]
    state['project_metadata'] = [{'field_key': 'project-code', 'field_type': 'text'}]
    for field in state['metadata']:
        if field['field_key'] == 'files':field['field_type'] = 'multi-file'
        if field['field_key'] == 'parent':field['field_type'] = 'workitem_related_select'
        if field['field_type'] == 'select':
            field['option'] = [{'option_id': v['value'], 'option_name': v['label']}
                               for v in field.pop('options')]
    state['field_overrides']['parent'] = {'id': 100, 'name': '名称仅显示'}
    original = port._run
    def run(args, **kwargs):
        if args[:2] == ['workitem', 'meta-fields'] and args[args.index('--work-item-type') + 1] == 'project':
            state['calls'].append(args[:2]);state['commands'].append(list(args))
            return copy.deepcopy(state.get('project_metadata_response', {
                'list': state['project_metadata'], 'pagination': {'has_more': False}}))
        result = original(args, **kwargs)
        if args[:2] == ['workitem', 'get'] and args[args.index('--work-item-id') + 1] == '100':
            result['work_item_fields'] = copy.deepcopy(state['project_fields'])
        return result
    port._run = run
    return g, store, row, draft, port, state, binding


def discovery(native_rig):
    _, _, row, _, port, _, _ = native_rig
    return discover_targets(port, row, project_code='IRAD-2099-001', doc_type='charter',
                            guard=lambda: True, deadline=time.monotonic() + 10)


def no_writes(state):
    assert state['uploads'] == state['updates'] == 0
    assert ['attachment', '+upload'] not in state['calls']
    assert ['workitem', 'update'] not in state['calls']


def test_native_contract_resolves_by_exact_ids_and_independent_code_field(native_rig):
    _, _, row, _, port, state, binding = native_rig
    target = port.resolve(row, 'report')
    assert target['document_identity'] == {'project_code': 'IRAD-2099-001', 'doc_type': 'test'}
    assert target['project_id'] == '100' and target['deliverable_id'] == '200'
    assert target['project_metadata_fingerprint']
    assert target['professional_review_value'] == 'not_reviewed'
    request = next(args for args in state['commands'] if args[:2] == ['workitem', 'get'])
    assert request[-2:] == ['--fields', 'project-code']
    assert binding['project_code_field'] == 'project-code'
    no_writes(state)


def test_native_contract_never_falls_back_to_title_when_code_field_unconfigured(native_rig):
    *_, port, state, binding = native_rig
    binding.pop('project_code_field')
    state['project_attribute']['work_item_name'] = 'IRAD-2099-001 看似正确的名称'
    result = discovery(native_rig)
    assert result['state'] == 'unresolved' and result['targets'] == []
    assert result['diagnostics'][0]['detail']['missing_config'] == ['project_code_field']
    assert ['workitem', 'get'] not in state['calls']
    no_writes(state)


@pytest.mark.parametrize('value,error', [
    ('IRAD-2099-002', 'BUSINESS_PROJECT_CODE_MISMATCH'),
    ('IRAD-2099-001 合成名称', 'BUSINESS_PROJECT_CODE_UNVERIFIED'),
    ('IRAD-2099-001 / IRAD-2099-002', 'BUSINESS_PROJECT_CODE_UNVERIFIED'),
    (None, 'BUSINESS_PROJECT_CODE_UNVERIFIED'),
    (['IRAD-2099-001'], 'BUSINESS_PROJECT_CODE_UNVERIFIED')])
def test_exact_project_code_does_not_use_title_or_name_hints(native_rig, value, error):
    _, _, row, _, port, state, _ = native_rig
    state['project_attribute']['work_item_name'] = 'IRAD-2099-001 标题不纠正字段'
    state['project_fields'][0]['value'] = value
    with pytest.raises(BoundaryError, match=error):port.resolve(row, 'report')
    no_writes(state)


@pytest.mark.parametrize('rows', [[], [{'key': 'project-code', 'value': 'IRAD-2099-001'}] * 2])
def test_code_field_must_be_present_once(native_rig, rows):
    _, _, row, _, port, state, _ = native_rig
    state['project_fields'] = rows
    with pytest.raises(BoundaryError, match='BUSINESS_PROJECT_CODE_UNVERIFIED'):port.resolve(row, 'report')
    no_writes(state)


@pytest.mark.parametrize('rows,error', [
    ([], 'BUSINESS_FIELD_METADATA_MISSING'),
    ([{'field_key': 'project-code', 'field_type': 'select'}], 'BUSINESS_FIELD_TYPE_UNSUPPORTED'),
    ([{'field_key': 'project-code', 'field_type': 'text'}] * 2, 'BUSINESS_FIELD_METADATA_AMBIGUOUS')])
def test_project_metadata_verified_before_any_project_read(native_rig, rows, error):
    _, _, row, _, port, state, _ = native_rig
    state['project_metadata'] = rows
    with pytest.raises(BoundaryError, match=error):port.resolve(row, 'report')
    assert ['workitem', 'get'] not in state['calls']
    no_writes(state)


def test_project_metadata_requires_complete_page(native_rig):
    _, _, row, _, port, state, _ = native_rig
    state['project_metadata_response'] = {'list': state['project_metadata'], 'pagination': {}}
    with pytest.raises(BoundaryError, match='BUSINESS_METADATA_UNAVAILABLE'):port.resolve(row, 'report')
    no_writes(state)


@pytest.mark.parametrize('raw', [
    'not_reviewed', {'value': 'not_reviewed', 'label': '未审核'},
    {'option_id': 'not_reviewed', 'option_name': '未审核'}])
def test_native_candidate_ids_support_explicit_value_contracts(native_rig, raw):
    _, _, row, _, port, state, _ = native_rig
    state['field_overrides']['review'] = raw
    assert port.resolve(row, 'report')['professional_review_value'] == 'not_reviewed'
    no_writes(state)


@pytest.mark.parametrize('raw', [
    {'option_id': 'not_reviewed', 'option_name': '已审核'},
    {'value': 'not_reviewed', 'label': '已审核'},
    {'option_id': 'unlisted'}, ['not_reviewed'], {'name': '未审核'},
    {'value': 'not_reviewed', 'option_id': 'not_reviewed'}])
def test_select_names_and_ambiguous_shapes_do_not_establish_identity(native_rig, raw):
    _, _, row, _, port, state, _ = native_rig
    state['field_overrides']['review'] = raw
    with pytest.raises(BoundaryError, match='BUSINESS_FIELD_(CANDIDATE_MISMATCH|VALUE_UNVERIFIED)'):
        port.resolve(row, 'report')
    no_writes(state)


@pytest.mark.parametrize('options', [None, [], [{'option_id': 'x', 'option_name': '未审核'}] * 2,
                                      [{'option_id': ['x'], 'option_name': '未审核'}],
                                      [{'option_id': 'x', 'option_name': ''}]])
def test_native_candidates_are_bounded_unique_and_scalar(native_rig, options):
    _, _, row, _, port, state, _ = native_rig
    next(f for f in state['metadata'] if f['field_key'] == 'review')['option'] = options
    with pytest.raises(BoundaryError, match='BUSINESS_FIELD_CANDIDATES_UNVERIFIED'):port.resolve(row, 'report')
    no_writes(state)


def test_mixed_candidate_metadata_is_not_silently_merged(native_rig):
    _, _, row, _, port, state, _ = native_rig
    next(f for f in state['metadata'] if f['field_key'] == 'review')['options'] = [
        {'value': 'approved', 'label': '已审核'}]
    with pytest.raises(BoundaryError, match='BUSINESS_FIELD_CANDIDATES_UNVERIFIED'):port.resolve(row, 'report')
    no_writes(state)


@pytest.mark.parametrize('key,value,error', [
    ('parent', {'id': 101, 'name': '名称仅显示'}, 'BUSINESS_TARGET_CHANGED'),
    ('parent', {'name': '名称仅显示'}, 'BUSINESS_PROJECT_RELATION_UNVERIFIED'),
    ('parent', [{'id': 100}], 'BUSINESS_PROJECT_RELATION_UNVERIFIED'),
    ('parent', {'id': True}, 'BUSINESS_PROJECT_RELATION_UNVERIFIED'),
    ('node', '概念', 'BUSINESS_TARGET_CHANGED'),
    ('doc', '文档', 'BUSINESS_DOCUMENT_IDENTITY_UNVERIFIED')])
def test_membership_names_stage_and_generic_category_cannot_replace_identities(native_rig, key, value, error):
    _, _, row, _, port, state, _ = native_rig
    state['field_overrides'][key] = value
    with pytest.raises(BoundaryError, match=error):port.resolve(row, 'report')
    no_writes(state)


@pytest.mark.parametrize('key', ['node', 'doc', 'review', 'mode'])
def test_actual_missing_identity_or_selection_is_structured_unresolved(native_rig, key):
    _, _, _, _, _, state, binding = native_rig
    binding['document_type'] = 'charter';state['kind'] = '项目章程'
    state['missing_fields'] = [key]
    result = discovery(native_rig)
    assert result['state'] == 'unresolved' and result['targets'] == []
    assert result['diagnostics'][0]['error_code'] == 'BUSINESS_TARGET_FIELD_MISSING'
    assert result['diagnostics'][0]['detail']['field_key'] == key
    no_writes(state)


def test_node_membership_is_still_required_for_native_target(native_rig):
    _, _, row, _, port, state, _ = native_rig
    state['links'] = []
    with pytest.raises(BoundaryError, match='BUSINESS_PARENT_CHANGED'):port.resolve(row, 'report')
    no_writes(state)


def test_metadata_contract_and_project_code_field_participate_in_binding_hash(native_rig):
    _, _, _, _, _, state, binding = native_rig
    binding = binding_config(binding)
    meta = validate_metadata(binding, state['metadata'])
    project_meta = validate_project_metadata(binding, state['project_metadata'])
    identity = {'project_code': binding['project_code'], 'doc_type': 'test'}
    baseline = immutable_binding(binding, meta, identity, '测试报告', project_meta)
    changed = {**binding, 'project_code_field': 'other-code'}
    assert immutable_binding(changed, meta, identity, '测试报告', project_meta) != baseline
    changed_meta = copy.deepcopy(meta);changed_meta['files']['field_type'] = 'file'
    assert immutable_binding(binding, changed_meta, identity, '测试报告', project_meta) != baseline


def test_native_attachment_commit_normalizes_approval_and_verifies_readback(native_rig):
    g, _, row, draft, port, state, binding = native_rig
    state['field_overrides']['review'] = {'option_id': 'not_reviewed', 'option_name': '未审核'}
    g.logic.business = port
    target = port.resolve(row, 'report');binding['verified_empty_revision'] = target['revision']
    g.logic.select_target(row, draft['id'], 'report');g.logic.adopt(row, draft['id'])
    result = g.logic.mount(row, draft['id'])
    assert result['receipt'] and state['uploads'] == state['updates'] == 1
    assert g.logic.mount(row, draft['id'])['receipt'] == result['receipt']
    assert state['uploads'] == state['updates'] == 1


def test_reviewed_native_target_cannot_upload(native_rig):
    _, _, row, _, port, state, _ = native_rig
    state['field_overrides']['review'] = {'option_id': 'approved', 'option_name': '已审核'}
    target = port.resolve(row, 'report')
    with pytest.raises(BusinessNotStarted, match='BUSINESS_REVIEWED_CONTENT_PROTECTED'):
        port.commit(row, target, 'synthetic', 'unused', 'unused', lambda: True)
    no_writes(state)


@pytest.mark.parametrize('label', ['文档', '样机', 'bom', '评审纪要', '归档材料'])
def test_generic_category_is_not_an_independent_document_kind_even_with_mapping(native_rig, label):
    _, _, row, _, port, state, binding = native_rig
    state['kind'] = label
    binding['document_type'] = 'charter'
    binding['document_type_bindings'] = {label: 'charter'}
    with pytest.raises(BoundaryError, match='BUSINESS_DOCUMENT_IDENTITY_UNVERIFIED') as error:
        port.resolve(row, 'report')
    assert error.value.diagnostic['check'] == 'generic_document_category'
    no_writes(state)
