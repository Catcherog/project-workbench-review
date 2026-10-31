"""Recover native telemetry from ONLY this benchmark's closed synthetic stores."""
from pathlib import Path
import hashlib,json,re,sqlite3
TASK=Path(__file__).resolve().parents[1]
location=json.loads((TASK/'upload/primary-native-store-location.private.json').read_text())
root=Path(location['roots'][0]);out=TASK/'evidence/native-measurements';out.mkdir(exist_ok=True)
collected=[];pending=[]
for child in root.iterdir():
    if child.is_symlink() or not child.is_dir():continue
    match=re.match(r'test_full_task_(\d)_SYN_([A-Z]+)_(\d{2})_(le|en)',child.name)
    if not match:continue
    repeat,group,number,variant=match.groups();mode='legacy' if variant=='le' else 'enforce';case='SYN-'+group+'-'+number
    name=f'{repeat}-{case}-{mode}.json';source=TASK/'evidence/full-model'/name;target=out/name
    if not source.exists():continue
    try:record=json.loads(source.read_text())
    except json.JSONDecodeError:pending.append(name);continue
    if target.exists():
        assert json.loads(target.read_text())['observation_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
        collected.append(name);continue
    gateway=child/'state/gateway.sqlite3';conversation=child/'state/am-conversation-r1/conversation.sqlite3'
    paths=[p for p in (gateway,conversation) if p.exists()]
    if any(Path(str(p)+'-wal').exists() or Path(str(p)+'-journal').exists() for p in paths):pending.append(name);continue
    if not gateway.exists():pending.append(name);continue
    wanted=set(record.get('event_ids',[]))|{record.get('event_id')};wanted.discard(None)
    dbhashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with sqlite3.connect(gateway.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        db.row_factory=sqlite3.Row
        runs=[dict(r) for r in db.execute('SELECT id,event_id,input_text,state,error FROM am_harness_runs') if r['event_id'] in wanted]
        if str(record.get('run_id','')).startswith('run_'):
            assert any(r['id']==record['run_id'] and r['input_text']==record['question'] for r in runs),name
        timings=[]
        for row in db.execute('SELECT * FROM am_request_timings'):
            if row['event_id'] not in wanted:continue
            item=dict(row);item['stages']=json.loads(item['stages']);timings.append(item)
        origins=[dict(r) for r in db.execute('SELECT id,body FROM am_inbox') if r['id'] in wanted]
        if record.get('event_id'):
            assert any(r['id']==record['event_id'] and r['body']==record['question'] for r in origins),name
    replies=[]
    if conversation.exists():
        with sqlite3.connect(conversation.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
            db.row_factory=sqlite3.Row
            run_ids={r['id'] for r in runs}
            for row in db.execute('SELECT event_id,state,reply_json,error_code FROM conversation_events'):
                item=dict(row);ident=item['event_id']
                belongs=ident in wanted or any(run in ident for run in run_ids) or any(ident.endswith(':'+event) for event in wanted)
                if not belongs:continue
                item['reply']=json.loads(item.pop('reply_json')) if item['reply_json'] else None
                replies.append(item)
    for p in paths:assert hashlib.sha256(p.read_bytes()).hexdigest()==dbhashes[p.name],name
    payload={'case_id':case,'repeat':int(repeat),'mode':mode,'source_commit':record['source_commit'],'observation_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'scope':'closed synthetic databases of this exact fixed benchmark only','immutable_read_without_wal':True,'native_database_hashes':dbhashes,'native_runs':runs,'request_timings':timings,'conversation_results':replies,
        'epoch_fields_use_synthetic_fixture_clock':True,'stage_seconds_are_native_monotonic_measurements':True,'production_database_read':False}
    target.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n');collected.append(name)
index={'collected':len(collected),'files':sorted(collected),'pending':sorted(pending),'production_database_read':False,'contains_database_files':False}
(TASK/'evidence/native-measurement-index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'collected':len(collected),'pending':len(pending)}))
