import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from am_training_window.native_r5 import OriginalPilotExecutor,phase_stop_proof
from am_training_window.window import WindowError


class NativeR5Tests(unittest.TestCase):
    def test_missing_inputs_do_not_spawn_original_cli(self):
        with tempfile.TemporaryDirectory() as d:
            callback=OriginalPilotExecutor(Path(d)/'plan.json',Path(d)/'evidence')
            with patch('am_training_window.native_r5.OriginalR5InputGate') as gate,patch('subprocess.Popen') as spawn:
                gate.return_value.side_effect=WindowError('original_R5_input_gate_blocked: missing real holdout')
                with self.assertRaises(WindowError):callback()
                spawn.assert_not_called()
            self.assertEqual(callback.cli_start_attempts,0)
            self.assertTrue(callback.stopped())
            self.assertFalse((Path(d)/'evidence').exists())

    def test_phase_flags_alone_do_not_prove_process_groups_stopped(self):
        result={'phases':[{'phase':'fit','attempted':True,'pid':45,'stop_confirmed':True},
                          {'phase':'reload','attempted':True,'pid':46,'stop_confirmed':True}]}
        self.assertFalse(phase_stop_proof(result,lambda pid:pid==45))
        self.assertTrue(phase_stop_proof(result,lambda pid:True))
        result['phases'][0]['stop_confirmed']=False
        self.assertFalse(phase_stop_proof(result,lambda pid:True))

    def test_empty_or_unidentified_phase_results_fail_closed(self):
        for result in ({},{'phases':[]},{'phases':[{'phase':'reload','attempted':False}]}):
            self.assertFalse(phase_stop_proof(result,lambda pid:True))
