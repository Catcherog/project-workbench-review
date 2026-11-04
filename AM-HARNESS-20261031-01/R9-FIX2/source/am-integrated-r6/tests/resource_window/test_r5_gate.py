from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from am_training_window.r5_gate import OriginalR5InputGate
from am_training_window.window import WindowError


class R5GateTests(unittest.TestCase):
    def modules(self, function):
        class R5Error(ValueError):
            pass
        parent = ModuleType("am_style_r5"); parent.__path__ = []
        pilot = ModuleType("am_style_r5.pilot"); pilot.execution_argv = function
        common = ModuleType("am_style_r5.common"); common.R5Error = R5Error
        return {"am_style_r5": parent, "am_style_r5.pilot": pilot, "am_style_r5.common": common}, R5Error

    def test_gate_never_caches_argv_or_old_green(self):
        calls = []
        def original(path):
            calls.append(path)
            return {"holdout_gate_sha256": str(len(calls)) * 64, "argv": ["never-retain-or-run"]}
        modules, _ = self.modules(original)
        with patch.dict(sys.modules, modules):
            gate = OriginalR5InputGate(Path("/synthetic/plan.json"))
            self.assertNotEqual(gate().binding_sha256, gate().binding_sha256)
            self.assertEqual(len(calls), 2)
            self.assertEqual(set(vars(gate)), {"plan_path"})

    def test_specific_original_blocker_survives_adapter(self):
        modules, error = self.modules(None)
        def original(path):
            raise error("pilot is blocked: holdout declaration original SHA mismatch")
        modules["am_style_r5.pilot"].execution_argv = original
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(WindowError, "declaration original SHA mismatch"):
                OriginalR5InputGate("/synthetic/plan.json")()


if __name__ == "__main__":
    unittest.main()
