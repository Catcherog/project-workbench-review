"""Small body-free request timings; durations are monotonic, anchors are UTC.

No monitoring service or model call. Stored beside the original inbox and
expired with it. Missing evidence stays missing rather than becoming zero.
"""
import json
import time
from contextlib import contextmanager


def initialize(store):
    with store.lock:
        store.conn.executescript('''
        CREATE TABLE IF NOT EXISTS am_request_timings(
          event_id TEXT PRIMARY KEY,received REAL NOT NULL,accepted REAL NOT NULL,
          started REAL,processed REAL,actionable REAL,finished REAL,readback_verified INTEGER,
          model_busy INTEGER NOT NULL,stages TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS am_outbox_events(outbox_id TEXT PRIMARY KEY,event_id TEXT NOT NULL);
        ''')


def add(store,event,name,seconds):
    if not event:return
    with store.tx() as c:
        old=c.execute('SELECT stages FROM am_request_timings WHERE event_id=?',(event,)).fetchone()
        if not old:return
        stages=json.loads(old['stages']);part=stages.setdefault(name,{'seconds':0,'calls':0})
        part['seconds']+=max(0,seconds);part['calls']+=1
        c.execute('UPDATE am_request_timings SET stages=? WHERE event_id=?',(json.dumps(stages),event))


@contextmanager
def measure(store,event,name):
    start=time.monotonic()
    try:yield
    finally:add(store,event,name,time.monotonic()-start)


def origin(store,outbox_id):
    rows=store.rows('SELECT event_id FROM am_outbox_events WHERE outbox_id=?',(outbox_id,))
    return rows[0]['event_id'] if rows else None
