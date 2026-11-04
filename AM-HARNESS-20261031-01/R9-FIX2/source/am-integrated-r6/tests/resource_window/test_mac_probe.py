from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from am_training_window.mac_probe import (
    COMMANDS, ProbeError, collect_snapshot, compare_snapshots, parse_pages,
    parse_processes, parse_swap, run_readonly,
)


VM = '''Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free: 100.
Pages inactive: 200.
Pages speculative: 30.
Pages active: 2000.
Pages wired down: 400.
Pages occupied by compressor: 50.
Pages stored in compressor: 100.
Swapouts: 20.
'''


def fake_runner(argv):
    values = {
        "physical": str(64 * 1024**3),
        "swap": "total = 2048.00M used = 650.00M free = 1398.00M (encrypted)",
        "pressure": "1", "boot": "{ sec = 1234, usec = 0 } date",
        "pages": VM,
        "processes": "42 1 501 29000000 /private/user/path/llama-server\n43 1 501 100 /Applications/Some App Helper\n",
    }
    return values[next(k for k, value in COMMANDS.items() if value == tuple(argv))]


class MacProbeTests(unittest.TestCase):
    def snapshot(self, seconds=0):
        return collect_snapshot(fake_runner, system="Darwin", captured_at=datetime(2026, 11, 3, tzinfo=timezone.utc) + timedelta(seconds=seconds))

    def test_page_size_and_compressor_distinction(self):
        parsed = parse_pages(VM)
        self.assertEqual(parsed["diagnostic_free_inactive_speculative_bytes"], 330 * 16384)
        self.assertEqual(parsed["compressor_physical_bytes"], 50 * 16384)
        self.assertEqual(parsed["compressor_logical_bytes"], 100 * 16384)
        self.assertEqual(parsed["swapouts_pages_since_boot"], 20)

    def test_missing_counter_is_not_zero(self):
        with self.assertRaises(ProbeError):
            parse_pages(VM.replace("Pages inactive: 200.\n", ""))

    def test_units_and_rss_are_not_bytes(self):
        self.assertEqual(parse_swap("total = 2G used = 512M free = 1.5G")["used_bytes"], 512 * 1024**2)
        self.assertEqual(parse_processes("1 0 0 8 /usr/bin/a")[0]["rss_bytes"], 8192)

    def test_no_process_paths_or_arguments_in_output(self):
        result = self.snapshot()
        self.assertEqual(result["provider_candidates"][0]["executable"], "llama-server")
        self.assertNotIn("/private/user", str(result))
        self.assertFalse(result["model_identity_verified"])
        self.assertEqual(result["resource_gate_status"], "not_checked")

    def test_probe_failure_remains_unknown(self):
        def bad(argv):
            if tuple(argv) == COMMANDS["pressure"]:
                raise RuntimeError("secret local exception")
            return fake_runner(argv)
        report = collect_snapshot(bad, system="Darwin")
        self.assertEqual(report["status"], "partial")
        self.assertIsNone(report["pressure_level"])
        self.assertNotIn("secret local", str(report))

    def test_linux_never_reads_mac_commands(self):
        calls = []
        result = collect_snapshot(lambda argv: calls.append(argv), system="Linux")
        self.assertEqual(result["status"], "unsupported_platform")
        self.assertEqual(calls, [])

    def test_mutation_command_rejected_before_subprocess(self):
        for argv in [("/usr/bin/killall", "llama-server"), ("/usr/sbin/purge",), ("/usr/sbin/sysctl", "-w", "a=1")]:
            with self.subTest(argv=argv), self.assertRaises(ProbeError):
                run_readonly(argv)

    def test_delta_does_not_claim_attribution_or_admission(self):
        b, a = self.snapshot(), self.snapshot(60)
        a["memory"]["diagnostic_free_inactive_speculative_bytes"] += 20 * 1024**3
        a["provider_candidates"] = []
        delta = compare_snapshots(b, a)
        self.assertEqual(delta["diagnostic_page_estimate_change_bytes"], 20 * 1024**3)
        self.assertEqual(delta["causal_attribution"], "not_established")
        self.assertEqual(delta["resource_gate_status"], "not_checked")

    def test_delta_rejects_boot_time_or_partial_changes(self):
        for mutate in [lambda a: a.update(boot_identity_sha256="different"), lambda a: a.update(status="partial"), lambda a: a.update(captured_at="2026-01-01T00:00:00+00:00")]:
            b, a = self.snapshot(), self.snapshot(60)
            mutate(a)
            with self.subTest(a=a), self.assertRaises(ProbeError):
                compare_snapshots(b, a)


if __name__ == "__main__":
    unittest.main()
