"""0.15.0: auto slot classes grant test slots while the machine has room for one more run."""
from __future__ import annotations

import json
import os
import unittest

from test_workflow import FEATURE
import test_worktrees
from test_worktrees import OTHER

AUTO = {"slots": {"test": {"default": {"auto": True, "max": 3, "memory": "4G", "cpus": 2}}},
        "capacity": {"reserve_memory": "2G", "reserve_cpus": 1, "warmup": "3m"}}


class AutoSlotTest(test_worktrees.TestSlotTest):
    def setUp(self) -> None:
        super().setUp()
        config = self.root / "implementation" / "workspace.json"
        config.write_text(json.dumps({**json.loads(config.read_text(encoding="utf-8")), **AUTO}), encoding="utf-8")
        self.addCleanup(os.environ.pop, "SPEC_WORKFLOW_MACHINE", None)

    def machine(self, free_mb: int, load: float = 1.0) -> None:
        os.environ["SPEC_WORKFLOW_MACHINE"] = json.dumps({"mem_available_mb": free_mb, "mem_total_mb": 32000, "cpus": 8, "load": load})

    def test_one_tester_at_a_time(self) -> None:
        self.skipTest("fixed-slot behavior; auto classes are covered below")

    def test_a_second_tester_waits_until_memory_covers_its_run(self) -> None:
        self.machine(7000)  # 7000 - 2048 reserved fits one 4G run
        self.to_tester(FEATURE)
        self.to_tester(OTHER)
        self.tracker("brief", FEATURE, "--role", "tester")
        error = self.tracker("brief", OTHER, "--role", "tester", succeeds=False)["error"]["message"]
        self.assertIn("test slot busy", error)
        report = self.tracker("capacity")["result"]["classes"]["test.default"]
        self.assertEqual((report["used"], report["more_now"], report["max"]), (1, 0, 3))
        self.assertTrue(report["limit"].startswith("memory"))
        self.machine(20000)  # room for the first run (still warming up) and two more
        self.tracker("brief", OTHER, "--role", "tester")

    def test_min_holds_even_on_a_busy_machine(self) -> None:
        self.machine(1000, load=8.0)
        self.to_tester(FEATURE)
        self.tracker("brief", FEATURE, "--role", "tester")
        self.assertEqual(self.tracker("capacity")["result"]["classes"]["test.default"]["more_now"], 0)

    def test_a_bad_auto_class_is_refused(self) -> None:
        config = self.root / "implementation" / "workspace.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        data["slots"]["test"]["default"] = {"auto": True, "max": 2}
        config.write_text(json.dumps(data), encoding="utf-8")
        self.assertIn("cost of one run", self.tracker("capacity", succeeds=False)["error"]["message"])


if __name__ == "__main__":
    unittest.main()
