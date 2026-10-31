"""Old direct sender receipts cannot become verified business completion."""
import json
from am_outcome.types import fingerprint


def test_ordinary_final_body_history_and_protected_snapshot_are_identical():
    import test_bridge
    case = test_bridge.BridgeTests(); case.setUp()
    try:
        assert case.bridge.ingest(case.event())
        assert case.bridge.process_one()
        row = case.bridge.db.execute('SELECT * FROM response_channel_v2').fetchone()
        outcome = json.loads(row['outcome_json'])
        history = case.bridge.db.execute('SELECT answer FROM turns').fetchone()[0]
        assert row['state'] == 'accepted'
        assert outcome['binding']['origin_event_id'] == 'om_1'
        assert outcome['binding']['scope'] == ['tenant', 'cli_test', 'ou_owner', 'oc_1', '']
        assert row['semantic_hash'] == fingerprint(history)
        assert outcome['protected_blocks'][0]['text'] == history == case.sent[0][1]
        assert not outcome['generation_adopted']
    finally: case.tearDown()


def test_ordinary_unknown_send_is_not_replayed_or_promoted_to_history():
    import test_bridge
    case = test_bridge.BridgeTests(); case.setUp()
    try:
        calls = []
        def unknown(*a):
            calls.append(a)
            raise TimeoutError('synthetic')
        case.bridge.reply = unknown
        assert case.bridge.ingest(case.event())
        case.bridge.process_one(); case.bridge.process_one()
        assert len(calls) == 1
        assert case.bridge.db.execute('SELECT state FROM response_channel_v2').fetchone()[0] == 'unknown'
        assert not case.bridge.db.execute('SELECT * FROM turns').fetchall()
    finally: case.tearDown()


def test_legacy_group_preserves_thread_scope_and_retention():
    import test_group_ledger
    case = test_group_ledger.LedgerTests(); case.setUp()
    try:
        case.ask()
        row = case.route.db.execute('SELECT * FROM response_channel_v2').fetchone()
        outcome = json.loads(row['outcome_json'])
        assert outcome['binding']['scope'] == ['tenant','cli_test','ou_member','oc_one','']
        assert row['state'] == 'accepted' and row['semantic_hash'] == fingerprint(case.sent[0][1])
        assert outcome['business_completion'] == 'unclassified'
        case.now += 86401; case.route.cleanup()
        assert not case.route.db.execute('SELECT * FROM response_channel_v2').fetchall()
    finally: case.tearDown()
