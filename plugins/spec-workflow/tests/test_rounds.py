"""0.12.0: light fix rounds, merge-queue flakes, registry files in lanes, next-batch lanes, and `queue hold`."""
from __future__ import annotations

import json
import unittest

from test_prs import PrCase
from test_workflow import FEATURE, TRACKER
from test_worktrees import BRANCH, TWO_LANES, WorktreeCase


class LightRoundCase(WorktreeCase):
    def to_fix(self, severity: str = "low") -> str:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "Required behavior", "--verification", "API call")
        self.create()
        self.handoff("implementer")
        self.write(f"be/{BRANCH}/internal/b.go", "package a\n")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "done")
        self.check("unit")
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        self.tracker("bug", "add", FEATURE, "--title", "Typo", "--severity", severity, "--spec-ref", "R1", "--environment", "local",
                     "--reproduction", "run", "--expected", "a", "--actual", "b", "--evidence", "log")
        self.handoff("parent")
        bug = f"BUG-{FEATURE}-001"
        self.tracker("bug", "assign", FEATURE, bug, "--fixer", "fixer")
        self.handoff("fixer")
        return bug

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def light(self, succeeds: bool = True) -> dict:
        return self.tracker("handoff", FEATURE, "--to", "tester", "--completed", "fixed", "--remaining", "retest",
                            "--light", "two-line test fix", succeeds=succeeds)

    def record(self) -> dict:
        return json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))


class LightRoundTest(LightRoundCase):
    def test_a_small_low_fix_goes_straight_to_retest(self) -> None:
        bug = self.to_fix()
        self.write(f"be/{BRANCH}/internal/b_test.go", "package a\n")
        self.tracker("bug", "fixed", FEATURE, bug, "--fix", "typo", "--regression", "unit")
        self.light()
        record = self.record()
        self.assertEqual((record["current_role"], record["status"]), ("tester", "ready_for_retest"))
        self.tracker("assign", FEATURE, "--role", "tester", "--read-only", "--parent-confirmed")
        self.assertIn(f"This round's fix diff: `git -C be/{BRANCH} diff {record['fix_round']['base']['be'][:12]}..HEAD`",
                      self.tracker("brief", FEATURE, "--role", "tester")["result"])
        skipped = record["checks"][-1]
        self.assertEqual((skipped["name"], skipped["role"], skipped["light"]["files"]), ("rereview-skipped", "fixer", ["be/internal/b_test.go"]))
        self.tracker("bug", "verify", FEATURE, bug, "--retest", "fixed")
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")
        self.assertTrue(self.tracker("gate", FEATURE, "acceptance")["result"]["passed"])

    def test_a_medium_bug_or_a_sensitive_path_needs_a_fresh_review(self) -> None:
        bug = self.to_fix("medium")
        self.write(f"be/{BRANCH}/internal/auth/check.go", "package auth\n")
        self.tracker("bug", "fixed", FEATURE, bug, "--fix", "typo", "--regression", "unit")
        error = self.light(succeeds=False)["error"]["message"]
        self.assertIn("not low severity", error)
        self.assertIn("be/internal/auth/check.go", error)
        self.assertEqual(self.record()["current_role"], "fixer")
        self.check("unit")
        self.handoff("reviewer")

    def test_a_large_code_diff_needs_a_fresh_review(self) -> None:
        bug = self.to_fix()
        self.write(f"be/{BRANCH}/internal/c.go", "package a\n" * 30)
        self.tracker("bug", "fixed", FEATURE, bug, "--fix", "typo", "--regression", "unit")
        self.assertIn("30 changed lines (limit 20)", self.light(succeeds=False)["error"]["message"])


class FlakeCase(PrCase):
    # Fails the first `fails` runs, then passes: a load-flaky test.
    fails = 1
    workspace: dict = {}

    def setUp(self) -> None:
        self.workspace = {"ci": {"fast": {"be": [f"n=$(cat ../../runs 2>/dev/null || echo 0); echo $((n+1)) > ../../runs; [ $n -ge {self.fails} ]"]}}}
        super().setUp()

    def accepted(self) -> None:
        self.implement_in_branch(FEATURE)
        (self.root / "runs").write_text(str(self.fails + 1), encoding="utf-8")  # pr open passes
        self.open_pr(FEATURE)
        self.check("code-review")
        self.handoff("tester")
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")
        (self.root / "runs").write_text("0", encoding="utf-8")
        self.tracker("queue", "add", "merge", FEATURE, "--parent-confirmed")


class FlakyMergeTest(FlakeCase):
    def test_a_flaky_command_passes_on_retry(self) -> None:
        self.accepted()
        result = self.tracker("queue", "run", "merge", "--parent-confirmed")["result"]
        self.assertEqual(result["result"], "merged")
        self.assertEqual(result["flaky"][0]["flaky"]["exit"], 1)
        self.assertIn("then passed on retry", self.record(FEATURE, archived=True)["checks"][-1]["evidence"])


class FlakeRestoreTest(FlakeCase):
    fails = 2

    def test_closing_the_merge_bug_as_a_flake_restores_the_tested_generation(self) -> None:
        self.accepted()
        before = self.record()["generation"]
        result = self.tracker("queue", "run", "merge", "--parent-confirmed")["result"]
        self.assertEqual(result["result"], "ci_failed")
        self.assertEqual(self.record()["generation"], before + 1)
        self.feature = FEATURE
        self.handoff("parent")
        closed = self.tracker("bug", "close", FEATURE, result["bug"], "--reason", "load flake", "--user-decision", "it's a flake",
                              "--parent-confirmed")["result"]
        self.assertTrue(closed["restored"].startswith("yes"), closed["restored"])
        record = self.record()
        self.assertEqual((record["generation"], record["current_role"]), (before, "parent"))
        self.assertTrue(record["requirements"][0]["tested"])
        self.tracker("ci", "run", FEATURE, "--parent-confirmed")
        self.tracker("gate", FEATURE, "acceptance")
        self.tracker("queue", "add", "merge", FEATURE, "--parent-confirmed")
        self.assertEqual(self.tracker("queue", "run", "merge", "--parent-confirmed")["result"]["result"], "merged")

    def test_a_branch_changed_since_keeps_the_new_generation(self) -> None:
        self.accepted()
        result = self.tracker("queue", "run", "merge", "--parent-confirmed")["result"]
        self.branch_file(FEATURE, "internal/c.go")
        self.feature = FEATURE
        self.handoff("parent")  # the fixer's handoff commits the change
        closed = self.tracker("bug", "close", FEATURE, result["bug"], "--reason", "flake", "--user-decision", "flake",
                              "--parent-confirmed")["result"]
        self.assertTrue(closed["restored"].startswith("no"), closed["restored"])
        self.assertFalse(self.record()["requirements"][0]["tested"])


REGISTRY_PLAN = TWO_LANES.replace("**Files:** `be/internal/keys/store.go` (new)", "**Files:** `be/db/migrations/000002_keys.up.sql` (new), "
                                  "`be/internal/keys/store.go` (new)").replace("- `be/internal/**`", "- `be/internal/**`\n- `be/db/migrations/**`")


class PlanLaneTest(WorktreeCase):
    def planned(self, text: str) -> dict:
        config = self.root / "implementation" / "workspace.json"
        config.write_text(json.dumps({**json.loads(config.read_text(encoding="utf-8")),
                                      "registries": [{"when": ["be/db/migrations/*.sql"], "own": ["be/db/source.go"]}]}), encoding="utf-8")
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        for ref in ("R1", "R2"):
            self.tracker("requirement", "add", FEATURE, "--spec-ref", ref, "--verification", "API call")
        self.handoff("planner")
        plan = self.root / "plan.md"
        plan.write_text(text, encoding="utf-8")
        stored = self.tracker("plan", "add", FEATURE, "--from", str(plan))["result"]
        self.handoff("parent")
        self.create()
        self.handoff("implementer")
        return stored

    def test_registry_files_join_the_plan_and_the_batch_lane(self) -> None:
        stored = self.planned(REGISTRY_PLAN)
        self.assertEqual(stored["registries"], ["be/db/source.go"])
        self.assertIn("be/db/source.go", stored["ownership"])
        lane = self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--batch", "1", "--parent-confirmed")["result"]
        self.assertEqual(lane["paths"], ["be/db/migrations/000002_keys.up.sql", "be/internal/keys/store.go", "be/internal/a.go", "be/db/source.go"])
        second = self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--batch", "2", "--parent-confirmed")["result"]
        self.assertNotIn("be/db/source.go", second["paths"])

    def test_files_outside_ownership_join_it(self) -> None:
        stored = self.planned(TWO_LANES.replace("- `fe/src/**`\n", ""))
        self.assertIn("fe/src/keys/panel.tsx", stored["ownership"])
        self.assertTrue(any("outside Ownership" in item for item in stored["warnings"]))

    def test_the_next_batch_brief_gets_its_own_lane(self) -> None:
        self.planned(TWO_LANES)
        first = self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--batch", "1", "--parent-confirmed")["result"]
        self.tracker("brief", FEATURE, "--role", "implementer", "--batch", "1")
        brief = self.tracker("brief", FEATURE, "--role", "implementer", "--batch", "2")["result"]
        lanes = [item for item in json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))["assignments"]
                 if item["status"] == "active"]
        self.assertEqual([(item["batch"], item["paths"]) for item in lanes], [(2, ["fe/src/keys/panel.tsx", "fe/src/app.ts"])])
        self.assertNotIn(first["assignment"], brief.split("Assignment: ", 1)[1].split("\n", 1)[0])


class HoldTest(PrCase):
    workspace: dict = {"slots": {"test": {"stack": 1}}}

    def test_a_writer_holds_the_stack_slot_while_its_command_runs(self) -> None:
        self.implement_in_branch(FEATURE)
        status = f"python3 {TRACKER} --json queue status > held.json"
        result = self.tracker("queue", "hold", "test", "--feature", FEATURE, "--class", "stack", "--run", status)["result"]
        self.assertEqual((result["class"], result["exit"]), ("stack", 0))
        held = json.loads((self.root / "held.json").read_text(encoding="utf-8"))["result"]["queues"]["test"]["holds"]
        self.assertEqual([(item["feature"], item["class"]) for item in held], [(FEATURE, "stack")])
        self.assertNotIn("holds", self.tracker("queue", "status")["result"]["queues"]["test"])
        error = self.tracker("queue", "hold", "test", "--feature", FEATURE, "--run", "exit 3", succeeds=False)["error"]["message"]
        self.assertIn("exited 3", error)


if __name__ == "__main__":
    unittest.main()
