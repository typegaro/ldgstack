"""0.10.0: worktree mode (<repo>/main + <repo>/<branch> per spec), one test slot, parallel executors, risk tiers, follow-up bugs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from test_workflow import FEATURE, GUARD, CliTestCase, spec_text

BRANCH = "spec-0000-demo"
OTHER = "0001-other"


def git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True, check=True).stdout.strip()


class WorktreeCase(CliTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_spec(f"{OTHER}.md", spec_text(1, "other"))
        for repo, first in (("be", "internal/a.go"), ("fe", "src/app.ts")):
            main = self.root / repo / "main"
            (main / first).parent.mkdir(parents=True)
            (main / first).write_text("package a\n", encoding="utf-8")
            (main / ".gitignore").write_text(".env\n", encoding="utf-8")
            git(main.parent, "init", "-q", "-b", "main", "main")
            git(main, "config", "user.email", "t@example.com")
            git(main, "config", "user.name", "Test")
            git(main, "add", "-A")
            git(main, "commit", "-q", "-m", "Initial")
        (self.root / "be" / "main" / ".env").write_text("PORT=1\nexport DATABASE_URL=postgres://dev/m33\n", encoding="utf-8")
        implementation = self.root / "implementation"
        implementation.mkdir()
        (implementation / "workspace.json").write_text(json.dumps({"repos": ["be", "fe"], "copy": {"be": [".env"]},
                                                                           "env": {"be": {".env": {"DATABASE_URL": "postgres://localhost/none"}}}}), encoding="utf-8")
        (implementation / "preflight.json").write_text(json.dumps({"commands": ["cd be && test -f internal/a.go", "cd fe/src && ls"]}),
                                                      encoding="utf-8")

    def create(self, feature: str = FEATURE, *extra: str) -> dict:
        return self.tracker("worktree", "create", feature, "--parent-confirmed", *extra)["result"]

    def guard(self, relative: str, agent: str = "agent-1", env: dict | None = None) -> subprocess.CompletedProcess:
        event = {"tool_name": "Write", "tool_input": {"file_path": str(self.root / relative)}, "cwd": str(self.root),
                 "agent_id": agent, "agent_type": "spec-workflow:spec-implementer"}
        return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), text=True, capture_output=True,
                              env={**os.environ, **(env or {})}, check=False)


class WorktreeLifecycleTest(WorktreeCase):
    def test_create_copies_untracked_files_and_writers_need_a_worktree(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed", succeeds=False)
        result = self.create()
        self.assertEqual((result["branch"], result["base"]), (BRANCH, "main"))
        checkout = self.root / "be" / BRANCH
        self.assertEqual(git(checkout, "branch", "--show-current"), BRANCH)
        # Copied, but never pointing the checkout at the shared dev database.
        self.assertEqual((checkout / ".env").read_text(encoding="utf-8"), "PORT=1\nexport DATABASE_URL=postgres://localhost/none\n")
        self.assertTrue((self.root / "fe" / BRANCH / "src" / "app.ts").is_file())
        self.assertFalse(self.create()["checkouts"][0]["created"])  # idempotent
        lane = self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")["result"]
        record = json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))
        self.assertEqual(next(item for item in record["assignments"] if item["id"] == lane["assignment"])["branch"], BRANCH)

    def test_dependent_spec_starts_from_its_dependency_branch(self) -> None:
        self.write_spec("0002-next.md", spec_text(2, "next", depends_on=[0]))
        self.tracker("init", f"specs/{FEATURE}.md")
        self.create(FEATURE, "--repos", "be")
        self.tracker("init", "specs/0002-next.md", "--parent-confirmed", "--user-decision", "start on 0000's branch")
        result = self.create("0002-next", "--repos", "be", "fe")
        self.assertEqual(result["base"], BRANCH)
        self.assertEqual([item["base"] for item in result["checkouts"]], [BRANCH, "main"])  # fe has no 0000 branch

    def test_brief_points_the_toolchain_and_diff_at_the_worktree(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "Required behavior", "--verification", "API call")
        self.create()
        self.handoff("implementer")
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")
        brief = self.tracker("brief", FEATURE, "--role", "implementer", "--parent-confirmed")["result"]
        self.assertIn(f"cd be/{BRANCH} && test -f internal/a.go", brief)
        self.assertIn(f"cd fe/{BRANCH}/src && ls", brief)
        self.assertIn(f"Worktree: be/{BRANCH}/, fe/{BRANCH}/ (branch {BRANCH}, from main)", brief)
        self.assertIn("Risk: normal", brief)
        self.tracker("risk", FEATURE, "high", "--parent-confirmed")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "done")
        self.check("unit")
        self.handoff("reviewer")
        self.tracker("assign", FEATURE, "--role", "reviewer", "--read-only", "--parent-confirmed")
        review = self.tracker("brief", FEATURE, "--role", "reviewer")["result"]
        self.assertIn(f"git -C be/{BRANCH} diff main...HEAD", review)
        self.assertIn("Risk: high", review)

    def test_handoff_commits_merge_archives_and_removes(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "Required behavior", "--verification", "API call")
        self.create()
        self.handoff("implementer")
        (self.root / "be" / BRANCH / "internal" / "b.go").write_text("package a\n", encoding="utf-8")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "done")
        self.check("unit")
        self.handoff("reviewer")
        self.assertEqual(git(self.root / "be" / BRANCH, "log", "--format=%s", "main..HEAD"), f"{FEATURE} implementer 1")
        self.assertEqual(git(self.root / "fe" / BRANCH, "log", "--format=%s", "main..HEAD"), "")  # nothing to commit in fe
        self.tracker("worktree", "merge", FEATURE, "--parent-confirmed", succeeds=False)  # acceptance gate first
        self.check("code-review")
        self.handoff("tester")
        status = self.tracker("worktree", "status")["result"]
        self.assertEqual(status["worktrees"][0]["ahead"], 1)
        self.tracker("archive", FEATURE, "--parent-confirmed", succeeds=False)  # not merged yet
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")
        self.tracker("archive", FEATURE, "--parent-confirmed", succeeds=False)
        merged = self.tracker("worktree", "merge", FEATURE, "--parent-confirmed")["result"]
        self.assertEqual(merged["merged"], ["be"])  # fe has no new commits
        self.assertTrue((self.root / "be" / "main" / "internal" / "b.go").is_file())
        self.assertEqual(git(self.root / "be" / "main", "log", "-1", "--format=%s"), f"Merge {BRANCH}")
        archived = self.tracker("archive", FEATURE, "--parent-confirmed")["result"]
        self.assertEqual(archived["removed_worktrees"], [f"be/{BRANCH}", f"fe/{BRANCH}"])
        self.assertFalse((self.root / "be" / BRANCH).exists())
        self.assertEqual(git(self.root / "be" / "main", "branch", "--list", BRANCH), "")

    def test_conflicting_merge_changes_nothing(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "Required behavior", "--verification", "API call")
        self.create()
        self.handoff("implementer")
        (self.root / "be" / BRANCH / "internal" / "a.go").write_text("package branch\n", encoding="utf-8")
        main = self.root / "be" / "main"
        (main / "internal" / "a.go").write_text("package main\n", encoding="utf-8")
        git(main, "commit", "-q", "-am", "Accepted change")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "done")
        self.check("unit")
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")
        before = git(main, "rev-parse", "HEAD")
        error = self.tracker("worktree", "merge", FEATURE, "--parent-confirmed", succeeds=False)["error"]["message"]
        self.assertIn("be/internal/a.go", error)
        self.assertIn(f"git -C be/{BRANCH} rebase main", error)
        self.assertEqual(git(main, "rev-parse", "HEAD"), before)
        self.assertEqual(git(self.root / "fe" / "main", "log", "--format=%s"), "Initial")

    def test_preflight_runs_on_main(self) -> None:
        result = self.spec("preflight")["result"]
        self.assertEqual(result["commands"], ["cd be/main && test -f internal/a.go", "cd fe/main/src && ls"])


class ToolkitTest(WorktreeCase):
    def test_smokes_and_brief_lines_run_in_a_checkout(self) -> None:
        tool = self.root / "be" / "main" / "cmd" / "probe"
        tool.mkdir(parents=True)
        (tool / "main.sh").write_text("exit 0\n", encoding="utf-8")
        self.tracker("toolkit", "add", "be-probe", "--capability", "be.inspect", "--command", "cd be && sh cmd/probe/main.sh",
                     "--location", "be/cmd/probe", "--smoke", "cd be && test -f cmd/probe/main.sh", "--owner-spec", "0000", "--mode", "read-only")
        self.assertEqual(self.tracker("toolkit", "verify", "be-probe")["result"]["failed"], [])  # runs in be/main

        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "Required behavior", "--verification", "API call")
        self.create()
        branch_only = self.root / "be" / BRANCH / "cmd" / "fresh"
        branch_only.mkdir(parents=True)
        (branch_only / "main.sh").write_text("exit 0\n", encoding="utf-8")
        self.tracker("toolkit", "add", "be-fresh", "--capability", "be.seed", "--command", "cd be && sh cmd/fresh/main.sh",
                     "--location", "be/cmd/fresh", "--smoke", "cd be && test -f cmd/fresh/main.sh", "--owner-spec", "0000", "--mode", "read-only")
        self.tracker("toolkit", "verify", "be-fresh", succeeds=False)  # not on main yet
        self.assertEqual(self.tracker("toolkit", "verify", "be-fresh", "--feature", FEATURE)["result"]["failed"], [])

        self.handoff("implementer")
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")
        brief = self.tracker("brief", FEATURE, "--role", "implementer", "--parent-confirmed")["result"]
        self.assertIn(f"read-only: cd be/{BRANCH} && sh cmd/probe/main.sh", brief)


class AbandonTest(WorktreeCase):
    def test_a_split_spec_leaves_the_queue_with_its_history(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.create()
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")
        self.tracker("abandon", FEATURE, "--reason", "split", "--parent-confirmed", succeeds=False)  # needs the user's decision
        result = self.tracker("abandon", FEATURE, "--reason", "split into 0002 and 0003", "--user-decision", "split it",
                              "--superseded-by", "2", "--parent-confirmed")["result"]
        self.assertIn(f"kept: branch {BRANCH}", result["worktree"])
        self.assertIn("spec defer 0", result["next"])
        record = json.loads((self.root / "implementation" / "abandoned" / f"{FEATURE}.json").read_text(encoding="utf-8"))
        self.assertEqual((record["status"], record["abandoned"]["superseded_by"]), ("abandoned", ["0002"]))
        self.assertTrue(all(item["status"] == "released" for item in record["assignments"]))
        self.assertFalse((self.root / "implementation" / "active" / f"{FEATURE}.json").exists())
        self.spec("defer", "0", "--reason", "split into 0002 and 0003", "--parent-confirmed")
        self.assertNotEqual((self.spec("next")["result"] or {}).get("id"), 0)
        self.assertEqual(self.guard(f"implementation/abandoned/{FEATURE}.json").returncode, 2)


class SiblingRepoTest(WorktreeCase):
    def test_sibling_repo_paths_follow_the_checkout(self) -> None:
        self.tracker("toolkit", "add", "fe-drive", "--capability", "fe.drive", "--location", "fe/src",
                     "--command", "cd be && cat ../fe/src/app.ts", "--smoke", "cd be && test -f ../fe/src/app.ts && test -f internal/a.go",
                     "--owner-spec", "0000", "--mode", "read-only")
        self.assertEqual(self.tracker("toolkit", "verify", "fe-drive")["result"]["failed"], [])  # be/main → ../../fe/main

        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "Required behavior", "--verification", "API call")
        self.create(FEATURE, "--repos", "be")  # this spec has no fe checkout
        self.handoff("implementer")
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")
        brief = self.tracker("brief", FEATURE, "--role", "implementer", "--parent-confirmed")["result"]
        self.assertIn(f"cd be/{BRANCH} && cat ../../fe/main/src/app.ts", brief)
        self.create(FEATURE, "--repos", "fe")
        brief = self.tracker("brief", FEATURE, "--role", "implementer", "--parent-confirmed")["result"]
        self.assertIn(f"cd be/{BRANCH} && cat ../../fe/{BRANCH}/src/app.ts", brief)


class TestSlotTest(WorktreeCase):
    def to_tester(self, feature: str) -> None:
        self.feature = feature
        self.tracker("init", f"specs/{feature}.md", "--parent-confirmed", "--user-decision", "independent")
        self.handoff("parent")
        self.tracker("requirement", "add", feature, "--spec-ref", "Required behavior", "--verification", "API call")
        self.handoff("implementer")
        self.tracker("requirement", "implemented", feature, "REQ-001", "--evidence", "done")
        self.check("unit")
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")

    def test_one_tester_at_a_time(self) -> None:
        self.to_tester(FEATURE)
        self.to_tester(OTHER)
        self.tracker("brief", FEATURE, "--role", "tester")
        self.tracker("brief", OTHER, "--role", "tester")  # nobody has claimed a tester lane yet
        record = json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))
        tester = next(item["id"] for item in record["assignments"] if item["status"] == "active" and item["role"] == "tester")
        markers = self.root / "implementation" / ".assignments"
        markers.mkdir(exist_ok=True)
        (markers / "agent-a").write_text(tester + "\n", encoding="utf-8")
        error = self.tracker("brief", OTHER, "--role", "tester", succeeds=False)["error"]["message"]
        self.assertIn(f"test slot busy: {FEATURE}", error)
        self.assertEqual(self.tracker("worktree", "status")["result"]["testing"], [FEATURE])
        self.tracker("brief", OTHER, "--role", "tester", "--parent-confirmed", "--user-decision", "run both now")
        self.feature = FEATURE
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")
        self.tracker("brief", OTHER, "--role", "tester")


class GuardTest(WorktreeCase):
    def setUp(self) -> None:
        super().setUp()
        self.tracker("init", f"specs/{FEATURE}.md")
        self.create()
        lane = self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")["result"]
        markers = self.root / "implementation" / ".assignments"
        markers.mkdir(exist_ok=True)
        (markers / "agent-1").write_text(lane["assignment"] + "\n", encoding="utf-8")

    def test_main_is_read_only_for_subagents(self) -> None:
        result = self.guard("be/main/internal/x.go")
        self.assertEqual(result.returncode, 2)
        self.assertIn("accepted code", result.stderr)

    def test_lanes_are_repo_relative_inside_the_worktree(self) -> None:
        inside = self.guard(f"be/{BRANCH}/internal/x.go")
        self.assertEqual((inside.returncode, inside.stdout), (0, ""))
        outside = self.guard(f"be/{BRANCH}/cmd/x.go", env={"SPEC_WORKFLOW_STRICT_LANES": "1"})
        self.assertEqual(outside.returncode, 2)
        self.assertIn("be/internal/**", outside.stderr)
        foreign = self.guard("be/spec-0001-other/internal/x.go", env={"SPEC_WORKFLOW_STRICT_LANES": "1"})
        self.assertIn("another spec's checkout", foreign.stderr)

    def test_other_specs_do_not_contend_for_files(self) -> None:
        self.tracker("init", f"specs/{OTHER}.md")
        self.create(OTHER)
        result = self.tracker("assign", OTHER, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")["result"]
        self.assertEqual(result["merge_risk"], [f"be/internal/** ~ be/internal/** ({FEATURE})"])


class ParallelExecutorTest(WorktreeCase):
    def test_disjoint_executors_then_one_handoff(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "Required behavior", "--verification", "API call")
        self.create()
        self.handoff("implementer")
        first = self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")["result"]
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/x/**", "--parallel", "--parent-confirmed", succeeds=False)
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "fe/src/**", "--parallel", "--parent-confirmed")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "done")
        self.check("unit")
        self.assertIn("parallel executors still hold lanes", self.handoff("reviewer", succeeds=False)["error"]["message"])
        self.tracker("assign", FEATURE, "--release", "--assignment", first["assignment"], "--parent-confirmed")
        self.handoff("reviewer")


TWO_LANES = """## Ownership
- `be/internal/**`
- `fe/src/**`

## Findings
- be/internal/a.go:1 is the store.

## Batch 1: backend
**Requirements:** REQ-001
**Requires:** none
**Files:** `be/internal/keys/store.go` (new), be/internal/a.go:12 (edit `Load`)
**Change shapes:** mirrors fe/src/app.ts.

## Batch 2: frontend
**Requirements:** REQ-002
**Requires:** none
**Parallel:** yes
**Files:**
- fe/src/keys/panel.tsx (new)
- fe/src/app.ts
**Commands:** cd fe && npm test

## Stop conditions
- A listed file is missing.

## Out of scope
- Refactors.
"""


class BatchLaneTest(WorktreeCase):
    def test_batches_claim_only_their_files_and_run_in_parallel(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        for ref in ("R1", "R2"):
            self.tracker("requirement", "add", FEATURE, "--spec-ref", ref, "--verification", "API call")
        self.handoff("planner")
        plan = self.root / "plan.md"
        plan.write_text(TWO_LANES, encoding="utf-8")
        self.tracker("plan", "add", FEATURE, "--from", str(plan))
        self.handoff("parent")
        self.create()
        self.handoff("implementer")
        first = self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--batch", "1", "--parent-confirmed")["result"]
        self.assertEqual(first["paths"], ["be/internal/keys/store.go", "be/internal/a.go"])  # fe/src/app.ts is outside **Files:**
        # A batch without its own lane is refused instead of borrowing, and reissuing, a sibling's lane.
        markers = self.root / "implementation" / ".assignments"
        markers.mkdir(exist_ok=True)
        (markers / "agent-b1").write_text(first["assignment"] + "\n", encoding="utf-8")
        loose = self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "fe/src/**", "--parallel", "--parent-confirmed")["result"]
        error = self.tracker("brief", FEATURE, "--role", "implementer", "--batch", "2", succeeds=False)["error"]["message"]
        self.assertIn("no lane for batch 2", error)
        self.tracker("assign", FEATURE, "--release", "--assignment", loose["assignment"], "--parent-confirmed")
        second =self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--batch", "2", "--parallel", "--parent-confirmed")["result"]
        self.assertEqual(second["paths"], ["fe/src/keys/panel.tsx", "fe/src/app.ts"])
        brief = self.tracker("brief", FEATURE, "--role", "implementer", "--batch", "2")["result"]
        self.assertIn(f"Assignment: {second['assignment']}", brief)
        self.assertIn("do not touch be/internal/a.go, be/internal/keys/store.go", brief)
        self.assertIn(f"join {FEATURE} --assignment {second['assignment']}", brief)

        # The batch-1 executor finishes first: a handoff would end batch 2's lane too, so only `join` is allowed (#78).
        lanes = lambda: {item["id"]: item["status"] for item in json.loads(  # noqa: E731
            (self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))["assignments"]}
        error = self.tracker("handoff", FEATURE, "--to", "parent", "--completed", "b1", "--remaining", "b2", succeeds=False)["error"]["message"]
        self.assertIn("--assignment <its ID>", error)
        self.assertEqual(lanes()[second["assignment"]], "active")
        self.tracker("join", FEATURE, "--assignment", first["assignment"], "--completed", "batch 1 done")
        self.assertEqual((lanes()[first["assignment"]], lanes()[second["assignment"]]), ("released", "active"))
        # A refused parallel assign stores nothing.
        before = lanes()
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "fe/src/**", "--parallel", "--parent-confirmed", succeeds=False)
        self.assertEqual(lanes(), before)
        # Batch 1's files are free again for a follow-up lane beside batch 2.
        third = self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--batch", "1", "--parallel", "--parent-confirmed")["result"]
        self.assertEqual(lanes()[third["assignment"]], "active")
        self.tracker("join", FEATURE, "--assignment", third["assignment"], "--completed", "follow-up done")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "done")
        self.tracker("requirement", "implemented", FEATURE, "REQ-002", "--evidence", "done")
        self.check("unit")
        self.handoff("reviewer")  # the last executor (one lane left) hands off


class FollowUpTest(WorktreeCase):
    def test_low_bugs_leave_the_gate(self) -> None:
        self.implement()
        for severity in ("low", "medium", "high"):
            self.tracker("bug", "add", FEATURE, "--title", f"{severity} issue", "--severity", severity, "--spec-ref", "R1",
                         "--environment", "local", "--reproduction", "run", "--expected", "a", "--actual", "b", "--evidence", "log")
        low, medium, high = (f"BUG-{FEATURE}-00{n}" for n in (1, 2, 3))
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")
        self.tracker("bug", "follow-up", FEATURE, low, "--reason", "cosmetic", "--parent-confirmed")
        self.tracker("bug", "follow-up", FEATURE, medium, "--reason", "later", "--parent-confirmed", succeeds=False)
        self.tracker("bug", "follow-up", FEATURE, medium, "--reason", "later", "--user-decision", "ship it", "--parent-confirmed")
        self.tracker("bug", "follow-up", FEATURE, high, "--reason", "later", "--user-decision", "ship it", "--parent-confirmed", succeeds=False)
        self.tracker("bug", "close", FEATURE, high, "--reason", "duplicate", "--user-decision", "dup", "--parent-confirmed")
        self.assertEqual(self.tracker("gate", FEATURE, "acceptance")["result"]["passed"], True)
        listed = self.tracker("follow-ups")["result"]
        self.assertEqual([(item["bug"], item["severity"]) for item in listed], [(low, "low"), (medium, "medium")])


if __name__ == "__main__":
    unittest.main()
