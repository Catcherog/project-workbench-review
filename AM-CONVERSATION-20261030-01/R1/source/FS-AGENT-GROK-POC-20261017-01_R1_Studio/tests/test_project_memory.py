import json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-qwen3.8/feishu-bridge'))
from project_memory import ProjectMemory,extraction_prompt
from fs_agent.store import Store
from fs_agent.config import BoundaryError

def test_project_memory_isolated_deduped_and_review_never_means_acceptance(tmp_path):
    now=[1000];s=Store(tmp_path/'pilot.db',lambda:now[0]);m=ProjectMemory(s,'owner')
    args=dict(project='cert',allowed=['cert'],source_id='m1',source_at=900,observed_at=1000,expires=2000,body='仅草本证书，正式证书未签发。')
    a=m.ingest(**args);assert m.ingest(**args)==a
    with pytest.raises(BoundaryError):m.context('other',['cert'])
    with pytest.raises(BoundaryError):m.ingest(**dict(args,body='正式证书已签发。'))
    with pytest.raises(BoundaryError):m.propose('cert',['cert'],a,'进度','正式证书已签发','完成')
    c=m.propose('cert',['cert'],a,'待核','正式证书未签发','待确认正式证书签发情况')
    with pytest.raises(BoundaryError):m.review('other',c,1,'reviewed_report',['cert'])
    m.review('owner',c,1,'reviewed_report',['cert'])
    ctx=m.context('cert',['cert'],'certification');assert len(ctx['reviewed_reports'])==1 and '正式证书' in ctx['focus']
    assert '不等于' in ctx['boundary']
    with pytest.raises(BoundaryError):m.review('owner',c,1,'reviewed_report',['cert'])
    now[0]=2001;m.cleanup();assert not m.context('cert',['cert'])['sources']
    s.close()

def test_two_projects_and_conflicting_source_times_stay_separate(tmp_path):
    s=Store(tmp_path/'pilot.db',lambda:1000);m=ProjectMemory(s,'owner')
    for project,text,source_at in [('A','预计11月1日完成；尚未验收。',900),('A','预计11月5日完成，待批准。',800),('B','样机未完成。',950)]:
        m.ingest(project=project,allowed=['A','B'],source_id=str(source_at),source_at=source_at,observed_at=1000,expires=2000,body=text)
    ctx=m.context('A',['A'],'development');prompt=extraction_prompt(ctx)
    assert '样机未完成' not in prompt and '尚未验收' in prompt and '待批准' in prompt
    assert [e['source_time'] for e in ctx['sources']]==[900,800]
    s.close()
