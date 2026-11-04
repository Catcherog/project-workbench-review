"""A busy BEGIN is deferred; other transaction faults still stop the PoC."""
from types import SimpleNamespace as NS
import sqlite3
import pytest
from fs_agent.store import Store,StoreBusyBeforeTransaction
from fs_agent.embedded import EmbeddedPoC


def test_external_writer_busy_never_permanently_suspends_consumer(tmp_path):
    (tmp_path/'state').mkdir()
    path=tmp_path/'gateway.sqlite3';s=Store(path);s.conn.execute('PRAGMA busy_timeout=1')
    other=sqlite3.connect(path,isolation_level=None)
    gate=NS(store=s,config=NS(root=tmp_path),stopping=NS(is_set=lambda:False))
    embedded=EmbeddedPoC(gate)
    embedded._step=lambda:s.execute("INSERT OR IGNORE INTO meta VALUES('synthetic-once','1')")
    try:
        other.execute('BEGIN IMMEDIATE')
        assert embedded.step() is False and not embedded.suspended
        assert not s.rows("SELECT * FROM meta WHERE key='synthetic-once'")
        other.execute('ROLLBACK')
        assert embedded.step()==1 and not embedded.suspended
        assert embedded.step()==0 and len(s.rows("SELECT * FROM meta WHERE key='synthetic-once'"))==1
    finally:other.close();s.close()


def test_nested_transaction_is_not_misreported_as_contention(tmp_path):
    (tmp_path/'state').mkdir();s=Store(tmp_path/'gateway.sqlite3')
    gate=NS(store=s,config=NS(root=tmp_path),stopping=NS(is_set=lambda:False))
    embedded=EmbeddedPoC(gate);embedded._step=lambda:s.execute("INSERT INTO meta VALUES('no','write')")
    try:
        s.conn.execute('BEGIN IMMEDIATE')
        assert embedded.step() is False and embedded.suspended
        assert not s.rows("SELECT * FROM meta WHERE key='no'")
    finally:s.conn.execute('ROLLBACK');s.close()
