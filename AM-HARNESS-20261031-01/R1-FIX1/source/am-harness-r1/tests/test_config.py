import unittest
from am_harness.config import HarnessConfig


class ConfigTests(unittest.TestCase):
    def test_default_is_opt_in(self):
        config = HarnessConfig()
        self.assertFalse(config.enabled)
        self.assertFalse(config.durable_queue_enabled)

    def test_fail_closed_bad_configuration(self):
        for values in ({"enabled": 1}, {"lease_seconds": float("nan")},
                       {"lease_seconds": 5, "heartbeat_seconds": 3},
                       {"enabledd": True}, {"fastpath_enabled": True},
                       {"max_queued": True}, {"execution_seconds": 121}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                HarnessConfig.from_mapping(values)
