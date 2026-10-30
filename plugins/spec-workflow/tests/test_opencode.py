"""OpenCode adapter: generated agents and package version are current, and the Node suite (opencode.test.mjs) passes."""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]


class OpenCodeAdapterTest(unittest.TestCase):
    def test_generated_files_are_current(self) -> None:
        process = subprocess.run(["python3", str(PLUGIN / "opencode" / "build.py"), "--check"], text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_plugin(self) -> None:
        process = subprocess.run(["node", "--test", str(PLUGIN / "tests" / "opencode.test.mjs")], text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
