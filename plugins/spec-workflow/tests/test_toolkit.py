"""Tests for the test toolkit manifest, tool gaps, the toolsmith handoff, the #17 regression, and the ad hoc tool retro metric.

Motivating examples come from a pilot run, where testers rebuilt throwaway tools in the scratchpad every round:
a mock OAuth server and ChatGPT backend, a mock MCP server, Playwright drivers, go -overlay DB planting, and seed scripts.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_improvements import COMPAT
from test_retro import RETRO, Transcript, usage
from test_workflow import GUARD, PLUGIN, CliTestCase

GAP = "GAP-0000-demo-001"


class ToolkitCase(CliTestCase):
    def setUp(self) -> None:
        super().setUp()
        for location in ("be/cmd/fake-oauth", "fe/tools/fe-drive", "tools/seed"):
            (self.root / location).mkdir(parents=True)

    def add_tool(self, name: str = "fake-oauth", *extra: str, capability: str = "ext.mock.oauth", location: str = "be/cmd/fake-oauth",
                 smoke: str = "true", mode: str = "read-only", succeeds: bool = True) -> dict:
        return self.tracker(
            "toolkit", "add", name, "--capability", capability, "--command", f"go run ./{location} serve --port 0",
            "--location", location, "--smoke", smoke, "--owner-spec", "0022", "--mode", mode, *extra, succeeds=succeeds,
        )

    def gap(self, capability: str = "ext.mock.oauth", succeeds: bool = True) -> dict:
        return self.tracker("tool-gap", "add", self.feature, "--capability", capability, "--requirement", "REQ-001",
                            "--why", "no deterministic OAuth server; tester wrote mockoauth/mock.py twice", succeeds=succeeds)


class ManifestTest(ToolkitCase):
    def test_add_list_update_verify_remove(self) -> None:
        tool = self.add_tool()["result"]
        self.assertEqual((tool["capabilities"], tool["mode"], tool["stale"]), (["ext.mock.oauth"], "read-only", True))
        self.add_tool("fe-drive", capability="fe.drive", location="fe/tools/fe-drive")
        self.add_tool("fe-drive", capability="fe.drive", location="fe/tools/fe-drive", succeeds=False)  # duplicate
        self.assertEqual([item["name"] for item in self.tracker("toolkit", "list", "--capability", "ext.mock.oauth")["result"]], ["fake-oauth"])
        self.assertEqual([item["name"] for item in self.tracker("toolkit", "list")["result"]], ["fake-oauth", "fe-drive"])

        verified = self.tracker("toolkit", "verify")["result"]
        self.assertEqual((verified["verified"], verified["failed"]), (2, []))
        self.assertFalse(any(item["stale"] for item in self.tracker("toolkit", "list")["result"]))

        # A change makes the tool stale until its smoke test passes again; a failing smoke fails verify.
        self.tracker("toolkit", "update", "fe-drive", "--capability", "fe.drive", "--capability", "fe.inspect", "--smoke", "printf b%sm oo; exit 3")
        failed = self.tracker("toolkit", "verify", "fe-drive", succeeds=False)
        self.assertIn("boom", failed["error"]["message"])
        listed = {item["name"]: item for item in self.tracker("toolkit", "list")["result"]}
        self.assertEqual((listed["fe-drive"]["capabilities"], listed["fe-drive"]["verified_result"], listed["fe-drive"]["stale"]),
                         (["fe.drive", "fe.inspect"], "failed", True))
        manifest = json.loads((self.root / "implementation" / "toolkit.json").read_text(encoding="utf-8"))
        self.assertNotIn("boom", json.dumps(manifest))  # smoke output is never stored

        summary = self.tracker("toolkit", "summary")["result"]
        self.assertEqual((summary["tools"], summary["stale"]), (2, ["fe-drive"]))
        self.tracker("toolkit", "remove", "fe-drive", "--reason", "feature removed")
        self.assertEqual([item["name"] for item in self.tracker("toolkit", "list")["result"]], ["fake-oauth"])

    def test_validation(self) -> None:
        self.add_tool(capability="ext.mock", succeeds=False)
        self.add_tool(capability="be.magic", succeeds=False)
        self.add_tool(location="/tmp/scratchpad/mockoauth", succeeds=False)  # throwaway locations are rejected
        self.add_tool(location="be/../../x", succeeds=False)
        self.add_tool(location="be/cmd/missing", succeeds=False)
        (self.root / "specs" / "tools").mkdir()
        self.add_tool(location="specs/tools", succeeds=False)
        self.add_tool("Bad_Name", succeeds=False)
        # Mutating tools must say how they refuse the dev database.
        self.add_tool("seed", capability="be.seed", location="tools/seed", mode="mutating", succeeds=False)
        self.add_tool("seed", "--guard", "refuses unless --target names a test DB created by env.isolate",
                      capability="be.seed", location="tools/seed", mode="mutating")

    def test_manifest_is_cli_only(self) -> None:
        target = str(self.root / "implementation" / "toolkit.json")
        for event in ({"tool_name": "Write", "tool_input": {"file_path": target}},
                      {"tool_name": "Bash", "tool_input": {"command": f"echo '{{}}' > {target}"}}):
            process = subprocess.run([sys.executable, str(GUARD)], input=json.dumps({**event, "cwd": str(self.root)}),
                                     text=True, capture_output=True, check=False)
            self.assertEqual(process.returncode, 2, process.stderr)


class ToolGapTest(ToolkitCase):
    def test_gap_lifecycle_blocks_acceptance_until_toolsmith_resolves(self) -> None:
        self.implement()
        self.tracker("tool-gap", "add", self.feature, "--capability", "fe.drive", "--requirement", "REQ-999", "--why", "x", succeeds=False)
        self.gap("ext.mock", succeeds=False)
        self.gap()
        self.tracker("requirement", "tested", self.feature, "REQ-001", "--evidence", "happy path only")
        self.check("independent")
        self.assertEqual(self.tracker("status", self.feature)["result"]["open_tool_gaps"], 1)
        self.assertEqual(self.handoff("parent")["result"]["status"], "needs_tooling")
        error = self.tracker("gate", self.feature, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn(f"open tool gaps: {GAP}", error)
        self.handoff("tester", succeeds=False)  # the tester can't resume until the toolsmith fills the gap

        self.assertEqual(self.handoff("toolsmith")["result"]["status"], "tooling")
        resolve = ("tool-gap", "resolve", GAP, "--tool", "fake-oauth", "--evidence", "authorize, token, refresh, error modes")
        self.tracker(*resolve, succeeds=False)  # not registered
        self.add_tool(capability="fe.drive", location="fe/tools/fe-drive")
        self.tracker(*resolve, succeeds=False)  # wrong capability
        self.tracker("toolkit", "update", "fake-oauth", "--capability", "ext.mock.oauth", "--location", "be/cmd/fake-oauth")
        self.tracker(*resolve, succeeds=False)  # never smoke-tested
        self.tracker("toolkit", "verify", "fake-oauth")
        self.tracker("check", "add", self.feature, "--name", "toolkit-smoke", "--method", "toolkit verify fake-oauth",
                     "--result", "passed", "--evidence", "1 tool passed")
        self.tracker(*resolve)
        self.tracker(*resolve, succeeds=False)  # already resolved
        self.assertEqual(self.handoff("tester")["result"]["status"], "ready_for_test")

        self.check("independent")
        self.assertEqual(self.handoff("parent")["result"]["status"], "ready_for_acceptance")
        gap = self.tracker("tool-gap", "list", self.feature)["result"][0]
        self.assertEqual((gap["status"], gap["tool"], gap["found_by"]), ("resolved", "fake-oauth", "tester"))
        self.assertIn("Tool gaps", (self.root / "implementation" / "active" / f"{self.feature}.md").read_text(encoding="utf-8"))
        self.tracker("archive", self.feature, "--parent-confirmed")

    def test_roles_defer_and_short_ids(self) -> None:
        self.start()
        self.gap(succeeds=False)  # implementer can't record gaps
        self.handoff("reviewer")
        self.gap()  # reviewer flags a missing coverage capability
        self.check("code-review")
        self.handoff("tester", succeeds=False)
        self.handoff("parent")
        self.tracker("tool-gap", "resolve", self.feature, "GAP-001", "--tool", "x", succeeds=False)  # parent is not the toolsmith
        self.tracker("tool-gap", "defer", self.feature, "GAP-001", "--reason", "r", "--user-decision", "u", succeeds=False)
        status = self.tracker("tool-gap", "defer", self.feature, "GAP-001", "--reason", "manual OAuth check",
                              "--user-decision", "User: defer the OAuth mock to the next spec", "--parent-confirmed")["result"]["status"]
        self.assertEqual(status, "awaiting_parent")
        self.handoff("toolsmith", succeeds=False)  # no open gaps left
        self.assertEqual(self.tracker("tool-gap", "list", "--open")["result"], [])
        self.handoff("tester")

    def test_tester_failed_check_blocks_acceptance_not_retest_handoff(self) -> None:
        """A tester failure remains re-runnable after the fix receives a fresh review."""
        self.implement()
        self.tracker("requirement", "tested", self.feature, "REQ-001", "--evidence", "observed")
        self.check("independent", "failed")
        self.report_bug()
        self.handoff("parent")
        self.tracker("bug", "assign", self.feature, "BUG-001", "--fixer", "fixer")
        self.handoff("fixer")
        self.tracker("bug", "fixed", self.feature, "BUG-001", "--fix", "f", "--regression", "test")
        self.check("unit")
        self.tracker("gate", self.feature, "ready-test")
        self.handoff("reviewer")
        self.check("code-review")
        self.assertEqual(self.handoff("tester")["result"]["status"], "ready_for_retest")
        self.tracker("requirement", "tested", self.feature, "REQ-001", "--evidence", "retested")
        self.tracker("bug", "verify", self.feature, "BUG-001", "--retest", "passes")
        error = self.tracker("gate", self.feature, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn("no passing check executed by the independent tester", error)
        self.check("independent")
        self.tracker("gate", self.feature, "acceptance")


@unittest.skipUnless((COMPAT / "specs").is_dir() and (COMPAT / "implementation").is_dir(), "no compatibility fixture")
class ToolkitCompatibilityTest(unittest.TestCase):
    """Records written before tool gaps and the toolkit existed keep working (copy of SPEC_WORKFLOW_COMPAT_ROOT)."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(COMPAT / "specs", self.root / "specs")
        shutil.copytree(COMPAT / "implementation", self.root / "implementation")
        (self.root / "AGENTS.md").write_text("# Copy\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str, succeeds: bool = True) -> dict:
        process = subprocess.run([str(PLUGIN / "bin" / "spec-tracker"), "--json", *arguments], cwd=self.root, text=True, capture_output=True)
        payload = json.loads(process.stdout)
        self.assertEqual(payload["ok"], succeeds, payload)
        return payload

    def test_old_records_gain_tool_gaps(self) -> None:
        # Every record reports tool gaps, older ones included (a live fixture may hold real open gaps).
        for record in self.run_cli("status")["result"]:
            self.assertIsInstance(record["open_tool_gaps"], int)
        self.assertIsInstance(self.run_cli("tool-gap", "list")["result"], list)
        self.assertIsInstance(self.run_cli("toolkit", "list")["result"], list)  # the fixture has registered tools
        archived = sorted((self.root / "implementation" / "archive").glob("*.json"))[0].stem
        self.run_cli("restore", archived, "--parent-confirmed")
        before = self.run_cli("gate", archived, "acceptance", succeeds=False)["error"]["message"] if not self.passes(archived) else ""
        self.run_cli("handoff", archived, "--to", "implementer", "--completed", "c", "--remaining", "r",
                     "--parent-confirmed", "--reason", "compatibility fixture")
        for item in self.run_cli("requirement", "list", archived)["result"]:
            self.run_cli("requirement", "implemented", archived, item["id"], "--evidence", "compatibility")
        self.run_cli("check", "add", archived, "--name", "compat-unit", "--method", "fixture", "--result", "passed", "--evidence", "ok")
        self.run_cli("handoff", archived, "--to", "reviewer", "--completed", "c", "--remaining", "r")
        self.run_cli("check", "add", archived, "--name", "compat-review", "--method", "fixture", "--result", "passed", "--evidence", "ok")
        self.run_cli("handoff", archived, "--to", "tester", "--completed", "c", "--remaining", "r")
        requirement = self.run_cli("requirement", "list", archived)["result"][0]["id"]
        self.run_cli("tool-gap", "add", archived, "--capability", "be.fault", "--requirement", requirement, "--why", "no crash injection")
        self.run_cli("handoff", archived, "--to", "parent", "--completed", "c", "--remaining", "r")
        self.assertIn(f"open tool gaps: GAP-{archived}-001", self.run_cli("gate", archived, "acceptance", succeeds=False)["error"]["message"])
        self.run_cli("tool-gap", "defer", f"GAP-{archived}-001", "--reason", "r", "--user-decision", "u", "--parent-confirmed")
        after = self.run_cli("gate", archived, "acceptance", succeeds=False)["error"]["message"] if not self.passes(archived) else ""
        self.assertNotIn(f"GAP-{archived}-001", after)
        self.assertNotEqual(before, after)  # the compatibility flow also recorded fresh implementation and review evidence

    def passes(self, feature: str) -> bool:
        process = subprocess.run([str(PLUGIN / "bin" / "spec-tracker"), "--json", "gate", feature, "acceptance"], cwd=self.root, text=True, capture_output=True)
        return json.loads(process.stdout)["ok"]


class AdhocToolRetroTest(unittest.TestCase):
    def test_scripts_outside_the_project_are_counted_and_repeats_named(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, transcripts = root / "project", root / "transcripts"
            (project / "specs").mkdir(parents=True)
            (project / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
            scratch = "/tmp/claude-1000/x/scratchpad"
            writes = {
                "a1": [f"cat > {scratch}/mockoauth/mock.py <<'EOF'\n" + "x = 1\n" * 40 + "EOF",
                       f"cd {scratch}/tscripts && cat > s1.py <<'EOF'\nprint(1)\nEOF", f"cat > {project}/fe/tools/drive.mjs <<'EOF'\nEOF"],
                "a2": [f"cat > {scratch}/rt/mock.py <<'EOF'\nprint(2)\nEOF", "go test ./... > out.log"],
            }
            for agent_id, commands in writes.items():
                run = Transcript()
                run.prompt("Role: tester. Record feature: 0001-demo.")
                for index, command in enumerate(commands):
                    run.assistant(f"{agent_id}-{index}", [run.tool(f"{agent_id}b{index}", "Bash", {"command": command})], usage(1, 100, 100, 10))
                    run.result(f"{agent_id}b{index}", "ok")
                run.assistant(f"{agent_id}-end", [{"type": "text", "text": "done"}], usage(1, 10, 10, 1), stop="end_turn")
                run.write(transcripts / "main-1" / "subagents" / f"agent-{agent_id}.jsonl")
                (transcripts / "main-1" / "subagents" / f"agent-{agent_id}.meta.json").write_text(
                    json.dumps({"agentType": "spec-workflow:spec-tester", "description": "Test spec 0001"}), encoding="utf-8")
            process = subprocess.run([sys.executable, str(RETRO), "--project", str(project), "--transcripts", str(transcripts), "--json"],
                                     text=True, capture_output=True, check=True)
            report = json.loads(process.stdout)
            counts = {run["id"]: run["adhoc_scripts"] for run in report["runs"]}
            self.assertEqual((counts["a1"]["count"], counts["a1"]["names"]), (2, ["mock.py", "s.py"]))
            self.assertEqual((counts["a2"]["count"], counts["a2"]["names"]), (1, ["mock.py"]))
            finding = next(item for item in report["findings"] if item["key"] == "tools.adhoc")
            self.assertEqual(finding["frequency"], 3)
            self.assertIn("rebuilt in several runs: mock.py", finding["evidence"])
            self.assertGreater(finding["estimated_savings"], 0)


if __name__ == "__main__":
    unittest.main()
