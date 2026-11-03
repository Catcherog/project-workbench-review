import fcntl
from pathlib import Path
import tempfile
import unittest

from am_training_window.original_r4 import OriginalCoordinatorLock


class OriginalLockTests(unittest.TestCase):
    def test_same_real_inode_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "model-coordinator.lock"
            lock.touch()
            validator = lambda m: {"lease_file": lock}
            with OriginalCoordinatorLock({}, validate_paths=validator):
                with lock.open("rb") as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with OriginalCoordinatorLock({}, validate_paths=validator):
                pass

    def test_missing_or_wrong_lock_is_never_created(self):
        with tempfile.TemporaryDirectory() as root:
            wrong = Path(root) / "experiment.lock"
            with self.assertRaises(ValueError):
                with OriginalCoordinatorLock({}, validate_paths=lambda m: {"lease_file": wrong}):
                    pass
            self.assertFalse(wrong.exists())

    def test_validation_failure_after_lock_releases_it(self):
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "model-coordinator.lock"
            lock.touch()
            count = 0
            def validator(manifest):
                nonlocal count
                count += 1
                if count == 2:
                    raise RuntimeError("changed config")
                return {"lease_file": lock}
            with self.assertRaises(RuntimeError):
                with OriginalCoordinatorLock({}, validate_paths=validator):
                    pass
            with lock.open("rb") as other:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


if __name__ == "__main__":
    unittest.main()
