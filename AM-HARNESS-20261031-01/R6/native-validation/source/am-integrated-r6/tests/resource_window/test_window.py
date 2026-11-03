from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from am_training_window.window import (ExecutionObservation, GateObservation, HostBinding,
    HostObservation, Journal, ModelIdentity, TrainingWindow, WindowError)


MODEL = ModelIdentity("qwen3.8:27b-bartowski-q8_0", "a" * 64)
BINDING = HostBinding("unique-consumer-1", "b" * 64, MODEL, "llamacpp")


class FakeHost:
    def __init__(self):
        self.value = HostObservation(BINDING, 1, True, True, 0, 0, (MODEL,), None)
        self.calls = []
        self.fail_suspend = False
        self.fail_restore = False
        self.locked = False
        self.pending_after_unload = False

    def inspect(self):
        return self.value

    def close_admission(self, owner):
        self.calls.append("fence")
        assert self.value.fence_owner is None
        self.value = replace(self.value, fence_owner=owner)

    def drain(self, owner):
        self.calls.append("drain")

    @contextmanager
    def lock(self):
        assert not self.locked, "double acquisition would deadlock real R4"
        self.locked = True
        self.calls.append("lock")
        try:
            yield
        finally:
            self.locked = False
            self.calls.append("unlock")

    def suspend_exact_model(self, owner, binding):
        assert self.locked and self.value.fence_owner == owner
        self.calls.append("unload")
        self.value = replace(self.value, loaded_models=(), pending_business=int(self.pending_after_unload))
        if self.fail_suspend:
            raise RuntimeError("failed after partial mutation")

    def restore_exact_model(self, owner, binding):
        assert self.locked
        self.calls.append("restore")
        if self.fail_restore:
            raise RuntimeError("restore unavailable")
        self.value = replace(self.value, loaded_models=(MODEL,))

    def open_admission(self, owner):
        self.calls.append("unfence")
        assert self.value.loaded_models == (MODEL,) and self.value.fence_owner == owner
        self.value = replace(self.value, fence_owner=None)


class TrainingWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.host = FakeHost()

    def window(self, mode="diagnostic"):
        path = Path(self.tmp.name) / "window.json"
        journal = Journal.create(path, mode, BINDING)
        return TrainingWindow(self.host, BINDING, self.host.lock,
            lambda: {"available_memory_GiB": 14 if self.host.value.loaded_models else 39}, journal)

    def executor(self):
        self.assertFalse(self.host.locked)
        self.assertIsNotNone(self.host.value.fence_owner)
        self.host.calls.append("trainer")
        return ExecutionObservation("completed", True, "e" * 64)

    def gate(self):
        return GateObservation(True, "c" * 64)

    def test_diagnostic_without_holdout_never_has_training_port(self):
        result = self.window().diagnostic()
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["trainer_invoked"])
        self.assertEqual(result["observations"]["after_unload"]["available_memory_GiB"], 39)
        self.assertEqual(self.host.value.loaded_models, (MODEL,))
        self.assertIsNone(self.host.value.fence_owner)

    def test_missing_holdout_leaves_original_model_untouched(self):
        result = self.window("training").train(lambda: GateObservation(False, "c" * 64, ("missing",)), self.executor, lambda: True)
        self.assertEqual(result["status"], "failed_restored")
        self.assertFalse(result["trainer_invoked"])
        self.assertEqual(self.host.calls, [])
        self.assertIn("missing", result["error_code"])

    def test_busy_before_unload_releases_our_fence_without_taking_model_lock(self):
        window = self.window()
        def busy(owner):
            raise WindowError("existing_inference_not_drained")
        @contextmanager
        def locked_by_existing_business():
            raise AssertionError("must not acquire an active business model lock")
            yield
        self.host.drain = busy
        window.original_lock = locked_by_existing_business
        result = window.diagnostic()
        self.assertEqual(result["status"], "failed_restored")
        self.assertIsNone(self.host.value.fence_owner)
        self.assertEqual(self.host.value.loaded_models, (MODEL,))
        self.assertNotIn("unload", self.host.calls)

    def test_train_releases_original_lock_before_original_r4(self):
        result = self.window("training").train(self.gate, self.executor, lambda: True)
        self.assertEqual(result["status"], "completed")
        self.assertLess(self.host.calls.index("unlock"), self.host.calls.index("trainer"))
        self.assertLess(self.host.calls.index("restore"), self.host.calls.index("unfence"))

    def test_changed_gate_during_drain_blocks_and_restores(self):
        gates = iter((GateObservation(True, "c" * 64), GateObservation(True, "d" * 64)))
        result = self.window("training").train(lambda: next(gates), self.executor, lambda: True)
        self.assertFalse(result["trainer_invoked"])
        self.assertEqual(result["status"], "failed_restored")
        self.assertIn("restore", self.host.calls)

    def test_unload_partial_failure_still_restores(self):
        self.host.fail_suspend = True
        result = self.window().diagnostic()
        self.assertEqual(result["status"], "failed_restored")
        self.assertEqual(self.host.value.loaded_models, (MODEL,))

    def test_restore_failure_keeps_fence_for_recovery(self):
        self.host.fail_restore = True
        window = self.window()
        result = window.diagnostic()
        self.assertEqual(result["status"], "recovery_required")
        self.assertIsNotNone(self.host.value.fence_owner)
        self.host.fail_restore = False
        recovered = TrainingWindow(self.host, BINDING, self.host.lock, lambda: {}, Journal.load(window.journal.path)).recover()
        self.assertEqual(recovered["status"], "recovered")
        self.assertIsNone(self.host.value.fence_owner)
        self.assertFalse(recovered["trainer_invoked"])

    def test_live_trainer_never_reloads_production(self):
        result = self.window("training").train(self.gate,
            lambda: ExecutionObservation("failed_or_stop_unconfirmed", False, "e" * 64), lambda: False)
        self.assertEqual(result["status"], "recovery_required")
        self.assertNotIn("restore", self.host.calls)
        self.assertIsNotNone(self.host.value.fence_owner)

    def test_new_business_before_launch_aborts_and_restores(self):
        self.host.pending_after_unload = True
        result = self.window("training").train(self.gate, self.executor, lambda: True)
        self.assertFalse(result["trainer_invoked"])
        self.assertEqual(result["status"], "failed_restored")

    def test_foreign_model_or_second_consumer_blocks_before_fence(self):
        self.host.value = replace(self.host.value, consumer_count=2)
        result = self.window().diagnostic()
        self.assertNotIn("unload", self.host.calls)
        self.assertFalse(result["trainer_invoked"])

    def test_keyboard_interrupt_restores_before_propagation(self):
        def interrupted():
            raise KeyboardInterrupt()
        window = self.window("training")
        with self.assertRaises(KeyboardInterrupt):
            window.train(self.gate, interrupted, lambda: True)
        self.assertEqual(self.host.value.loaded_models, (MODEL,))
        self.assertIsNone(self.host.value.fence_owner)

    def test_used_window_and_journal_cannot_overwrite_prior_run(self):
        window = self.window()
        window.diagnostic()
        with self.assertRaises(WindowError):
            window.diagnostic()
        with self.assertRaises(FileExistsError):
            Journal.create(window.journal.path, "diagnostic", BINDING)

    def test_journal_disk_failure_after_unload_does_not_skip_restore(self):
        window = self.window()
        original = window.journal.write
        def disk_full(state, **updates):
            if "unload" in self.host.calls:
                raise OSError("disk full")
            return original(state, **updates)
        window.journal.write = disk_full
        result = window.diagnostic()
        self.assertEqual(self.host.value.loaded_models, (MODEL,))
        self.assertIsNone(self.host.value.fence_owner)
        self.assertEqual(result["journal_error_type"], "OSError")
        self.assertEqual(result["status"], "failed_restored")
        self.assertFalse(result["journal_persistence_confirmed"])

    def test_crash_after_unfence_can_be_verified_without_mutation(self):
        window = self.window()
        window.diagnostic()
        window.journal.data["status"] = "in_progress"
        before = list(self.host.calls)
        result = window.recover()
        self.assertEqual(result["status"], "recovered")
        self.assertEqual(self.host.calls, before)
        again = window.recover()
        self.assertEqual(again["status"], "recovered")
        self.assertEqual(self.host.calls, before)


if __name__ == "__main__":
    unittest.main()
