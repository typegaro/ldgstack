"""0.8.4: briefs reissue claimed assignments (#46, #63); cross-spec overlap hints and `assign --carve` (#64)."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from test_enforcement import TRACKER_CMD, GuardCase, payload
from test_workflow import TRACKER, spec_text

OTHER = "0001-other"


class LaneCase(GuardCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / "implementation").mkdir(exist_ok=True)
        (self.root / "implementation" / "preflight.json").write_text(json.dumps({"commands": ["true"]}), encoding="utf-8")
        for relative in ("fe/tests/support/request.ts", "fe/tests/e2e/chat.spec.ts", "fe/tests/setup.ts", "fe/src/app.ts"):
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            (self.root / relative).write_text("x", encoding="utf-8")

    def record(self, feature: str) -> dict:
        return json.loads((self.root / "implementation" / "active" / f"{feature}.json").read_text(encoding="utf-8"))

    def brief(self, feature: str, role: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TRACKER), "brief", feature, "--role", role, "--parent-confirmed"],
                              cwd=self.root, text=True, capture_output=True, check=True)

    def claim(self, assignment: str, agent: str, role: str) -> subprocess.CompletedProcess:
        return self.bash(f"{TRACKER_CMD} claim {assignment}", agent=agent, role=role)


class StaleClaimTest(LaneCase):
    def test_brief_reissues_a_claimed_assignment(self) -> None:
        self.start()
        self.tracker("assign", self.feature, "--role", "implementer", "--paths", "fe/src/**", "--parent-confirmed")
        first = self.record(self.feature)["assignments"][-1]["id"]
        self.assertNotIn("warning", self.brief(self.feature, "implementer").stderr)  # unclaimed: the same assignment
        self.assertEqual(self.record(self.feature)["assignments"][-1]["id"], first)
        self.assertEqual(self.claim(first, "agent-1", "implementer").returncode, 0)
        refused = self.claim(first, "agent-2", "implementer")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("new brief", refused.stderr)

        process = self.brief(self.feature, "implementer")
        self.assertIn(f"warning: {first} was claimed", process.stderr)
        assignments = self.record(self.feature)["assignments"]
        second = assignments[-1]
        self.assertNotEqual(second["id"], first)
        self.assertEqual((second["paths"], second["status"]), (["fe/src/**"], "active"))
        self.assertEqual((assignments[-2]["status"], assignments[-2]["released_by"]), ("released", "brief: claimed by an earlier agent"))
        self.assertIn(f"claim {second['id']}", process.stdout)
        self.assertEqual(self.claim(second["id"], "agent-2", "implementer").returncode, 0)
        self.assertEqual(self.write("fe/src/app.ts", agent="agent-2").returncode, 0)


class CarveTest(LaneCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_spec(f"{OTHER}.md", spec_text(1, "other"))
        self.tracker("init", f"specs/{OTHER}.md")
        self.tracker("assign", OTHER, "--role", "implementer", "--paths", "fe/tests/**", "--parent-confirmed")
        self.source = self.record(OTHER)["assignments"][-1]["id"]
        self.tracker("init", f"specs/{self.feature}.md")

    def test_overlap_error_names_pairs_and_narrow_globs(self) -> None:
        message = self.tracker("assign", self.feature, "--role", "fixer", "--paths", "fe/tests/**", "fe/src/**",
                               "--parent-confirmed", succeeds=False)["error"]["message"]
        self.assertIn(f"fe/tests/** overlaps fe/tests/** in {self.source} ({OTHER}, implementer)", message)
        self.assertIn(f"--carve fe/tests/** --from {self.source}", message)
        message = self.tracker("assign", self.feature, "--role", "fixer", "--paths", "fe/**", "--parent-confirmed", succeeds=False)["error"]["message"]
        self.assertIn("non-overlapping globs under fe/**: fe/src/**", message)
        self.assertNotIn("--carve", message)  # fe/** is wider than the other lane

    def test_carve_moves_a_narrow_glob_between_lanes(self) -> None:
        self.tracker("assign", self.feature, "--role", "fixer", "--carve", "fe/**", "--from", self.source, "--parent-confirmed", succeeds=False)
        self.tracker("assign", self.feature, "--role", "fixer", "--carve", "fe/tests/support/**", "--parent-confirmed", succeeds=False)
        self.tracker("assign", self.feature, "--role", "fixer", "--carve", "fe/tests/support/**", "--from", self.source, succeeds=False)
        result = self.tracker("assign", self.feature, "--role", "fixer", "--paths", "fe/src/**", "--carve", "fe/tests/support/**",
                              "--from", self.source, "--parent-confirmed")["result"]
        self.assertEqual(result["paths"], ["fe/src/**", "fe/tests/support/**"])
        mine = self.record(self.feature)["assignments"][-1]
        self.assertEqual(mine["carved_from"], [{"glob": "fe/tests/support/**", "from": self.source, "feature": OTHER}])
        theirs = self.record(OTHER)["assignments"][-1]
        self.assertEqual((theirs["status"], theirs["paths"]), ("active", ["fe/tests/**"]))
        self.assertEqual([(item["glob"], item["to"]) for item in theirs["carved"]], [("fe/tests/support/**", mine["id"])])
        # The other lane still blocks the rest of fe/tests, and nobody else may take the carved glob.
        self.write_spec("0002-third.md", spec_text(2, "third"))
        self.tracker("init", "specs/0002-third.md")
        self.tracker("assign", "0002-third", "--role", "implementer", "--paths", "fe/tests/support/**", "--parent-confirmed", succeeds=False)

        self.handoff_other_and_claim(mine["id"])
        strict = {"SPEC_WORKFLOW_STRICT_LANES": "1"}
        source_write = self.run_guard(payload(self.root, "Write", {"file_path": str(self.root / "fe/tests/support/request.ts")}, "agent-a",
                                              "spec-workflow:spec-implementer"), env=strict)
        self.assertEqual(source_write.returncode, 2)
        self.assertIn(f"carved out of your assignment {self.source} to {mine['id']}", source_write.stderr)
        self.assertEqual(self.run_guard(payload(self.root, "Write", {"file_path": str(self.root / "fe/tests/e2e/chat.spec.ts")}, "agent-a",
                                                "spec-workflow:spec-implementer"), env=strict).returncode, 0)
        self.assertEqual(self.run_guard(payload(self.root, "Write", {"file_path": str(self.root / "fe/tests/support/request.ts")}, "agent-b",
                                                "spec-workflow:spec-fixer"), env=strict).returncode, 0)
        brief = self.brief(OTHER, "implementer").stdout
        self.assertIn(f"edit only fe/tests/**, except fe/tests/support/** (carved out to {mine['id']}, {self.feature})", brief)

    def handoff_other_and_claim(self, mine: str) -> None:
        self.tracker("handoff", OTHER, "--to", "implementer", "--completed", "c", "--remaining", "r", "--parent-confirmed", "--reason", "test")
        self.assertEqual(self.claim(self.source, "agent-a", "implementer").returncode, 0)
        self.assertEqual(self.claim(mine, "agent-b", "fixer").returncode, 0)


class AlongsideTest(LaneCase):
    """#52: a toolsmith on a disjoint lane works beside the fixer and joins before review and retest."""

    def test_toolsmith_alongside_fixer(self) -> None:
        self.implement()
        self.report_bug()
        self.tracker("tool-gap", "add", self.feature, "--capability", "be.fault", "--requirement", "REQ-001", "--why", "no fault injection")
        self.handoff("parent")
        self.tracker("bug", "assign", self.feature, "BUG-001", "--fixer", "fixer")
        self.handoff("fixer")
        self.tracker("assign", self.feature, "--role", "toolsmith", "--paths", "tools/fault/**", "--alongside", succeeds=False)  # parent only
        self.tracker("assign", self.feature, "--role", "fixer", "--paths", "fe/src/**", "--parent-confirmed")
        self.tracker("assign", self.feature, "--role", "toolsmith", "--paths", "fe/src/tools/**", "--alongside", "--parent-confirmed", succeeds=False)
        self.tracker("assign", self.feature, "--role", "fixer", "--paths", "tools/x/**", "--alongside", "--parent-confirmed", succeeds=False)
        self.tracker("assign", self.feature, "--role", "toolsmith", "--paths", "tools/fault/**", "--alongside", "--parent-confirmed")
        active = {item["role"]: item for item in self.record(self.feature)["assignments"] if item["status"] == "active"}
        self.assertEqual((active["fixer"]["paths"], active["toolsmith"]["paths"]), (["fe/src/**"], ["tools/fault/**"]))
        self.assertEqual(self.tracker("status", self.feature)["result"]["side_role"], "toolsmith")
        self.assertIn(f"join {self.feature}", self.brief(self.feature, "toolsmith").stdout)
        self.assertIn("handoff", self.brief(self.feature, "fixer").stdout)

        self.tracker("bug", "fixed", self.feature, "BUG-001", "--fix", "patched", "--regression", "test_x")
        self.check("unit-fix")
        self.assertIn("join", self.handoff("reviewer", succeeds=False)["error"]["message"])  # joined before review and retest
        (self.root / "tools" / "fault").mkdir(parents=True)
        self.tracker("toolkit", "add", "fault", "--capability", "be.fault", "--command", "tools/fault/run", "--location", "tools/fault",
                     "--smoke", "true", "--owner-spec", "0000", "--mode", "read-only")
        self.tracker("toolkit", "verify", "fault")
        self.tracker("tool-gap", "resolve", self.feature, "GAP-001", "--tool", "fault")  # side role may run toolsmith commands
        self.tracker("join", self.feature, "--completed", "fault tool")
        record = self.record(self.feature)
        self.assertNotIn("side_role", record)
        self.assertEqual([item["role"] for item in record["assignments"] if item["status"] == "active"], ["fixer"])
        self.assertEqual(record["side_handoffs"][0]["open_tool_gaps"], [])
        self.tracker("join", self.feature, "--completed", "again", succeeds=False)
        self.handoff("reviewer")


if __name__ == "__main__":
    unittest.main()
