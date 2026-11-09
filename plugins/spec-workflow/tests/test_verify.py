"""0.14.0: parallel verify, verdicts bound to the patch, proven findings, main-red merges, stuck agents, the decision log."""
from __future__ import annotations

import json
import unittest

from test_prs import CI, HOOKS, PrCase
from test_workflow import FEATURE
from test_worktrees import BRANCH, git


class VerifyCase(PrCase):
    workspace: dict = {"ci": CI, "hooks": HOOKS, "verify": "parallel"}

    def record(self) -> dict:
        return json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))

    def act(self, role: str, *arguments: str, succeeds: bool = True) -> dict:
        return self.tracker(*arguments, "--as", role, succeeds=succeeds)

    def verified(self) -> None:
        self.implement_in_branch(FEATURE)
        self.open_pr(FEATURE)
        self.act("reviewer", "check", "add", FEATURE, "--name", "code-review", "--method", "read", "--result", "passed", "--evidence", "ok")
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.act("tester", "check", "add", FEATURE, "--name", "independent", "--method", "drive", "--result", "passed", "--evidence", "ok")
        self.act("tester", "handoff", FEATURE, "--to", "parent", "--completed", "tested", "--remaining", "none")
        self.handoff("parent")


class ParallelVerifyTest(VerifyCase):
    def test_review_and_test_run_at_once_on_one_patch(self) -> None:
        self.implement_in_branch(FEATURE)
        self.open_pr(FEATURE)
        record = self.record()
        self.assertEqual((record["status"], record["current_role"], record["side_role"]), ("ready_for_verify", "reviewer", "tester"))
        self.assertEqual(sorted(item["role"] for item in record["assignments"] if item["status"] == "active"), ["tester"])
        self.assertIn("pass --as reviewer or --as tester", self.tracker("check", "add", FEATURE, "--name", "code-review", "--method", "read",
                                                                        "--result", "passed", "--evidence", "ok", succeeds=False)["error"]["message"])
        self.act("reviewer", "check", "add", FEATURE, "--name", "code-review", "--method", "read", "--result", "passed", "--evidence", "ok")
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.act("tester", "check", "add", FEATURE, "--name", "independent", "--method", "drive", "--result", "passed", "--evidence", "ok")
        self.assertIn("each role ends with", self.act("tester", "handoff", FEATURE, "--to", "reviewer", "--completed", "x", "--remaining", "y",
                                                      succeeds=False)["error"]["message"])
        self.act("tester", "handoff", FEATURE, "--to", "parent", "--completed", "tested", "--remaining", "none")
        record = self.record()
        self.assertEqual((record["current_role"], record.get("side_role"), record["status"]), ("reviewer", None, "ready_for_review"))
        self.handoff("parent")
        record = self.record()
        self.assertNotIn("verify", record)
        self.assertEqual(record["checks"][-1]["patch"], record["checks"][-2]["patch"])
        self.assertTrue(self.tracker("gate", FEATURE, "acceptance")["result"]["passed"])

    def test_a_clean_merge_of_main_keeps_the_verdicts_and_a_new_commit_does_not(self) -> None:
        self.verified()
        self.main_commit("internal/z.go")
        git(self.root / "be" / BRANCH, "merge", "-q", "--no-edit", "main")
        self.tracker("ci", "run", FEATURE, "--parent-confirmed")
        self.assertTrue(self.tracker("gate", FEATURE, "acceptance")["result"]["passed"])
        self.branch_file(FEATURE, "internal/c.go")
        git(self.root / "be" / BRANCH, "add", "-A")
        git(self.root / "be" / BRANCH, "commit", "-q", "-m", "late")
        self.tracker("ci", "run", FEATURE, "--parent-confirmed")
        error = self.tracker("gate", FEATURE, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn("after the last passing review", error)


class ProvenFindingTest(VerifyCase):
    def bug(self, severity: str, *proof: str, succeeds: bool = True) -> dict:
        return self.act("reviewer", "bug", "add", FEATURE, "--title", f"{severity} {' '.join(proof)}", "--severity", severity, "--spec-ref", "R1",
                        "--environment", "local", "--reproduction", "go test ./...", "--expected", "a", "--actual", "b", "--evidence", "log",
                        *proof, succeeds=succeeds)

    def test_only_a_run_blocks(self) -> None:
        self.implement_in_branch(FEATURE)
        self.open_pr(FEATURE)
        self.assertIn("say how the finding is proven", self.bug("medium", succeeds=False)["error"]["message"])
        for severity, proof in (("medium", "--ran"), ("medium", "--unproven"), ("high", "--unproven"), ("high", "--preexisting")):
            self.bug(severity, proof)
        bugs = {item["title"]: (item["status"], item["proof"]) for item in self.record()["bugs"]}
        self.assertEqual(bugs, {"medium --ran": ("open", "ran"), "medium --unproven": ("follow_up", "unproven"),
                                "high --unproven": ("open", "unproven"), "high --preexisting": ("follow_up", "preexisting")})


class MainRedTest(PrCase):
    def setUp(self) -> None:
        self.workspace = {"ci": {"fast": {"be": ["test ! -f ../../red"]}}}
        super().setUp()

    def test_a_failure_main_shares_pauses_the_queue_instead_of_filing_a_bug(self) -> None:
        self.to_acceptance(FEATURE)
        self.tracker("queue", "add", "merge", FEATURE, "--parent-confirmed")
        (self.root / "red").write_text("", encoding="utf-8")
        result = self.tracker("queue", "run", "merge", "--parent-confirmed")["result"]
        self.assertEqual(result["result"], "main_red")
        self.assertEqual(self.record(FEATURE)["bugs"], [])
        self.assertEqual(self.tracker("queue", "status")["result"]["queues"]["merge"]["last"]["result"], "main_red")
        (self.root / "red").unlink()
        self.assertEqual(self.tracker("queue", "run", "merge", "--parent-confirmed")["result"]["result"], "merged")


class SupervisionTest(PrCase):
    def test_stuck_reports_each_active_lane_against_its_role(self) -> None:
        self.implement_in_branch(FEATURE)
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")
        rows = self.tracker("stuck")["result"]["active"]
        self.assertEqual([(row["role"], row["stuck"], row["stuck_after_seconds"]) for row in rows], [("implementer", False, 45 * 60)])

    def test_decisions_and_calls_waiting_on_the_user(self) -> None:
        self.tracker("decision", "add", "--decision", "picked the faster parser", "--why", "same output", "--evidence", "bench.log")
        self.assertIn("names your --pick", self.tracker("decision", "add", "--decision", "drop table", "--why", "x", "--evidence", "y", "--waiting",
                                                        succeeds=False)["error"]["message"])
        call = self.tracker("decision", "add", "--decision", "delete old rows?", "--why", "irreversible", "--evidence", "query.sql",
                            "--waiting", "--pick", "yes, after a backup", "--risk", "data loss")["result"]
        self.assertEqual([row["id"] for row in self.tracker("decision", "list")["result"]["waiting"]], [call["id"]])
        self.tracker("decision", "resolve", call["id"], "--answer", "go ahead")
        self.assertEqual(self.tracker("decision", "list")["result"]["waiting"], [])
        self.assertIn("already resolved", self.tracker("decision", "resolve", call["id"], "--answer", "again", succeeds=False)["error"]["message"])


if __name__ == "__main__":
    unittest.main()
