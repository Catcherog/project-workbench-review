"""Real isolated OS process control; no model, training, or business service."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from am_training_window.process_guard import BoundProcessGuard, private_json
from am_training_window.window import WindowError


class ProcessGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.python = os.environ.get('AM_R7_TEST_PYTHON', sys.executable)
        self.plan = self.root/'plan.json'; self.plan.write_text('{}')
        self.children = []
        self.addCleanup(self.cleanup_children)

    def cleanup_children(self):
        for p in self.children:
            if p.poll() is None:
                try: os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            p.wait(timeout=5)

    def start(self, argv):
        p = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.children.append(p)
        return p

    def guard(self, commands):
        return BoundProcessGuard.create(self.root/'processes.json', python=self.python,
            commands=commands, request_id=str(uuid.uuid4()), plan_path=self.plan,
            run_directory=self.root/'run', sources={'synthetic_process_control_only': True})

    def test_independent_fit_reload_groups_are_stopped_unrelated_process_survives(self):
        commands = {role: [self.python, '-c', 'import time;time.sleep(40)', role, str(self.root)]
                    for role in ('cli', 'fit', 'reload')}
        guard = self.guard(commands)
        owned = [self.start(argv) for argv in commands.values()]
        unrelated = self.start([self.python, '-c', 'import time;time.sleep(40)', 'unrelated', str(self.root)])
        guard.refresh()
        self.assertEqual({p['role'] for p in guard.data['processes']}, set(commands))
        self.assertEqual(len({p['pgid'] for p in guard.data['processes']}), 3)
        self.assertFalse(guard.stopped())
        self.assertTrue(guard.stop('synthetic_cancel', reap=lambda: [p.poll() for p in owned]))
        self.assertIsNone(unrelated.poll())
        self.assertTrue(BoundProcessGuard.load(guard.path).stopped())

    def test_new_interpreter_recovers_from_durable_ledger_without_resume(self):
        commands = {'fit': [self.python, '-c', 'import time;time.sleep(40)', str(self.root)]}
        guard = self.guard(commands); worker = self.start(commands['fit']); guard.refresh()
        # A separate interpreter reconstructs discovery/signalling from disk.
        code = ('import sys,json;from am_training_window.process_guard import BoundProcessGuard;'
                'g=BoundProcessGuard.load(sys.argv[1]);g.stop("synthetic_restart_recovery");'
                'print(json.dumps(g.data))')
        proc = subprocess.Popen([self.python, '-c', code, str(guard.path)],
            env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while proc.poll() is None:
            worker.poll(); time.sleep(.05)
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0, err)
        result = json.loads(out)
        self.assertEqual(result['stop_reason'], 'synthetic_restart_recovery')
        self.assertTrue(BoundProcessGuard.load(guard.path).stopped())
        self.assertEqual(len(result['processes']), 1)

    def test_pid_start_identity_mismatch_is_never_signalled(self):
        commands = {'fit': [self.python, '-c', 'import time;time.sleep(40)', str(self.root)]}
        guard = self.guard(commands); worker = self.start(commands['fit']); guard.refresh()
        guard.data['processes'][0]['start_time'] -= 10
        with self.assertRaisesRegex(WindowError, 'recorded_pid_reused'):
            guard.stop('synthetic_bad_identity')
        self.assertIsNone(worker.poll())
        self.assertEqual(guard.data['events'], [])

    def test_unknown_worker_state_does_not_allow_model_restoration(self):
        guard = self.guard({})
        (self.root/'run').mkdir()
        self.assertFalse(guard.stopped())

    def test_ledger_creation_cannot_overwrite_an_existing_request(self):
        guard = self.guard({})
        original = guard.path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.guard({})
        self.assertEqual(guard.path.read_bytes(), original)

    def test_immutable_return_snapshot_survives_later_fresh_stop_checks(self):
        guard = self.guard({})
        self.assertTrue(guard.stopped())
        path = self.root/'processes-at-return.json'
        private_json(path, guard.data, exclusive=True)
        saved = path.read_bytes()
        self.assertTrue(guard.stopped())
        self.assertEqual(path.read_bytes(), saved)
        self.assertNotEqual(guard.path.read_bytes(), saved)
