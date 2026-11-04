"""Independent F02 audit probe. Uses original isolated synthetic host fixture."""
import json
import pytest
from test_harness_host import harness, convo, ux, service, am_rig, base_rig, execute, incoming, call, answer, project


@pytest.mark.parametrize('mode', ['prefetch', 'dynamic'])
def test_project_answer_source_versions_cover_dynamic_reads(harness, mode):
    conv, host = harness
    marker = '动态来源依赖审计唯一标记：旧记录中的进展尚待核实。'
    if mode == 'prefetch':
        _, run_id = execute(harness, '请分析需求75的情况', [answer(marker)])
    else:
        _, run_id = execute(harness, '请列出项目目录并分析第一个项目的情况', [
            call('list_projects', {}),
            call('read_project', {'project_id': project(conv)}),
            answer(marker),
        ])
    context = host.s.rows('SELECT * FROM am_harness_context_sources WHERE event_id=?',
                         ('harness:' + run_id + ':v1',))[0]
    output = host.s.rows('SELECT * FROM am_conversation_outputs WHERE json_extract(reply,\'$.event_id\')=?',
                        ('harness:' + run_id + ':v1',))[0]
    old_snapshot = host.service.snapshots.latest
    conv[0][5].values[1][4] = '更新后的来源记录：新进展已经替代旧记录。'
    host.service.snapshots.refresh().result(3)
    assert host.service.snapshots.latest != old_snapshot
    execute(harness, '请把上一条回答展开说明', [answer('依据当前可用内容进一步说明。')])
    present = marker in conv[1].prompts[-1]
    print(json.dumps({'mode': mode, 'dependencies': json.loads(context['dependencies']),
                      'project_refs': json.loads(output['project_refs']),
                      'old_snapshot': old_snapshot,
                      'new_snapshot': host.service.snapshots.latest,
                      'old_answer_in_next_actual_prompt': present}, ensure_ascii=False))
    assert not present, 'Source-version-invalid project answer reached next actual provider prompt'
