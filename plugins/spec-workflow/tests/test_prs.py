"""0.11.0: local PRs in worktree mode: `pr open` (commits, merge-tree, PR checks, fast CI), `pr status`, CI checks and gate."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from test_workflow import FEATURE
from test_worktrees import BRANCH, OTHER, WorktreeCase, git

OTHER_BRANCH = "spec-0001-other"
CI = {"fast": {"be": ["test ! -f FAIL", "test ! -f BREAK"]}}
HOOKS = {"duplicate_numbers": [{"glob": "be/db/migrations/*.sql"}], "post_merge": ["touch post-merge-ran"]}


class PrCase(WorktreeCase):
    workspace: dict = {"ci": CI, "hooks": HOOKS}

    def setUp(self) -> None:
        super().setUp()
        config = self.root / "implementation" / "workspace.json"
        config.write_text(json.dumps({**json.loads(config.read_text(encoding="utf-8")), **self.workspace}), encoding="utf-8")

    def record(self, feature: str = FEATURE, archived: bool = False) -> dict:
        folder = "archive" if archived else "active"
        return json.loads((self.root / "implementation" / folder / f"{feature}.json").read_text(encoding="utf-8"))

    def branch_file(self, feature: str, relative: str, text: str = "package branch\n") -> None:
        branch = BRANCH if feature == FEATURE else OTHER_BRANCH
        path = self.root / "be" / branch / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def main_commit(self, relative: str, text: str = "package main\n") -> str:
        main = self.root / "be" / "main"
        (main / relative).parent.mkdir(parents=True, exist_ok=True)
        (main / relative).write_text(text, encoding="utf-8")
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", f"Accept {relative}")
        return git(main, "rev-parse", "HEAD")

    def implement_in_branch(self, feature: str, relative: str = "internal/b.go") -> None:
        self.feature = feature
        self.tracker("init", f"specs/{feature}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", feature, "--spec-ref", "Required behavior", "--verification", "API call")
        self.create(feature, "--repos", "be")
        self.handoff("implementer")
        self.branch_file(feature, relative)
        self.tracker("requirement", "implemented", feature, "REQ-001", "--evidence", "done")
        self.check("unit")

    def open_pr(self, feature: str, succeeds: bool = True) -> dict:
        return self.tracker("pr", "open", feature, "--completed", "work", "--remaining", "review", succeeds=succeeds)

    def to_acceptance(self, feature: str, relative: str = "internal/b.go") -> None:
        self.implement_in_branch(feature, relative)
        self.open_pr(feature) if self.workspace.get("ci") else self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        self.tracker("requirement", "tested", feature, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")


class PrOpenTest(PrCase):
    def test_conflict_refuses_and_keeps_the_record_with_the_writer(self) -> None:
        self.implement_in_branch(FEATURE, "internal/a.go")
        self.main_commit("internal/a.go")
        error = self.open_pr(FEATURE, succeeds=False)["error"]["message"]
        self.assertIn("be/internal/a.go", error)
        self.assertIn(f"git -C be/{BRANCH} merge main", error)
        record = self.record()
        self.assertEqual((record["current_role"], record["status"]), ("implementer", "implementing"))
        self.assertNotIn("ci-fast", [item["name"] for item in record["checks"]])  # refused before CI

    def test_failing_fast_ci_refuses_then_a_fix_opens_the_pr(self) -> None:
        self.implement_in_branch(FEATURE)
        self.branch_file(FEATURE, "FAIL", "")
        error = self.open_pr(FEATURE, succeeds=False)["error"]["message"]
        self.assertIn("`test ! -f FAIL` in be/spec-0000-demo exited 1", error)
        record = self.record()
        self.assertEqual(record["current_role"], "implementer")
        check = record["checks"][-1]
        self.assertEqual((check["name"], check["result"], check["role"]), ("ci-fast", "failed", "implementer"))
        self.assertEqual(check["ci"]["commands"], [{"repo": "be", "command": "test ! -f FAIL", "exit": 1, "seconds": check["ci"]["commands"][0]["seconds"]}])
        self.assertEqual(check["ci"]["branch_shas"]["be"], git(self.root / "be" / BRANCH, "rev-parse", "HEAD"))
        self.assertEqual(check["ci"]["main_shas"]["be"], git(self.root / "be" / "main", "rev-parse", "HEAD"))
        self.assertIn("[exit 1 in", (self.root / check["ci"]["log"]).read_text(encoding="utf-8"))
        self.assertTrue(check["ci"]["log"].startswith(f"implementation/ci/{FEATURE}/"))

        (self.root / "be" / BRANCH / "FAIL").unlink()
        result = self.open_pr(FEATURE)["result"]
        self.assertEqual((result["status"], result["current_role"], result["pr"]), ("ready_for_review", "reviewer", "open"))
        record = self.record()
        self.assertEqual((record["pr"]["state"], record["pr"]["rounds"]), ("open", 1))
        self.assertEqual(record["checks"][-1]["result"], "passed")
        self.assertEqual(git(self.root / "be" / BRANCH, "status", "--porcelain"), "")  # the deletion was committed

    def test_needs_commits_and_replaces_the_direct_handoff(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "Required behavior", "--verification", "API call")
        self.create(FEATURE, "--repos", "be")
        self.handoff("implementer")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "done")
        self.check("unit")
        self.assertIn("no commits on spec-0000-demo", self.open_pr(FEATURE, succeeds=False)["error"]["message"])
        self.assertIn("pr open", self.handoff("reviewer", succeeds=False)["error"]["message"])
        self.tracker("check", "add", FEATURE, "--name", "ci-fast", "--method", "x", "--result", "passed", "--evidence", "y", succeeds=False)
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/internal/**", "--parent-confirmed")
        brief = self.tracker("brief", FEATURE, "--role", "implementer", "--parent-confirmed")["result"]
        self.assertIn(f"pr open {FEATURE} --completed", brief)


class PrStatusTest(PrCase):
    def test_main_moving_flags_open_prs_in_the_contract_shape(self) -> None:
        self.implement_in_branch(FEATURE, "internal/a.go")
        self.open_pr(FEATURE)
        prs = self.tracker("pr", "status")["result"]["prs"]
        self.assertEqual(len(prs), 1)
        pr = prs[0]
        self.assertTrue({"feature", "spec_id", "title", "state", "opened_at", "merged_at", "record_status", "current_role", "repos",
                         "fast_ci", "review_rounds", "queue"} <= set(pr))
        self.assertEqual((pr["spec_id"], pr["state"], pr["merged_at"], pr["record_status"], pr["review_rounds"]),
                         ("0000", "open", None, "ready_for_review", 1))
        repo = pr["repos"]["be"]
        self.assertEqual(set(repo), {"branch", "path", "head", "main", "ahead", "behind", "conflicts", "additions", "deletions", "files"})
        self.assertEqual((repo["path"], repo["ahead"], repo["behind"], repo["files"], repo["conflicts"]), (f"be/{BRANCH}", 1, 0, 1, []))
        self.assertEqual(set(pr["fast_ci"]), {"result", "branch_shas", "main_shas", "at", "log", "commands"})
        self.assertEqual(pr["fast_ci"]["result"], "passed")
        self.assertEqual(pr["queue"], {"name": "review", "position": 0})

        self.main_commit("internal/a.go")
        pr = self.tracker("pr", "status", FEATURE)["result"]["prs"][0]
        self.assertEqual(pr["repos"]["be"]["conflicts"], ["internal/a.go"])
        self.assertEqual(pr["blocking"], ["be/internal/a.go"])
        status = self.tracker("queue", "status")["result"]["queues"]["review"]
        self.assertEqual(status["holders"][0]["feature"], FEATURE)  # granted before main moved; it keeps its slot
        returned = self.tracker("pr", "return", FEATURE, "--parent-confirmed")["result"]
        self.assertEqual((returned["current_role"], returned["status"]), ("fixer", "fixing"))
        record = self.record()
        self.assertEqual(record["bugs"][-1]["status"], "assigned")
        self.assertIn("internal/a.go", record["rereview_required"]["reason"])

    def test_text_output(self) -> None:
        import subprocess
        import sys
        from test_workflow import TRACKER
        self.implement_in_branch(FEATURE)
        self.open_pr(FEATURE)
        text = subprocess.run([sys.executable, str(TRACKER), "pr", "status"], cwd=self.root, text=True, capture_output=True, check=True).stdout
        self.assertIn(f"{FEATURE}: PR open, ready_for_review (reviewer), fast CI passed, rounds 1, review queue #0", text)


class MigrationNumberTest(PrCase):
    def test_same_number_against_main_and_between_branches(self) -> None:
        self.main_commit("db/migrations/000052_accounts.sql", "-- a\n")
        self.implement_in_branch(FEATURE, "db/migrations/000052_keys.sql")
        error = self.open_pr(FEATURE, succeeds=False)["error"]["message"]
        self.assertIn("db/migrations/000052_keys.sql reuses number 000052 (db/migrations/000052_accounts.sql on main)", error)
        (self.root / "be" / BRANCH / "db" / "migrations" / "000052_keys.sql").rename(self.root / "be" / BRANCH / "db" / "migrations" / "000053_keys.sql")
        self.open_pr(FEATURE)

        self.implement_in_branch(OTHER, "db/migrations/000053_jobs.sql")
        result = self.open_pr(OTHER)["result"]  # another open branch: a warning, the one merged second renumbers
        self.assertIn("000053_jobs.sql and 0000-demo's db/migrations/000053_keys.sql both take number 000053", result["warnings"][0])
        prs = {item["feature"]: item for item in self.tracker("pr", "status")["result"]["prs"]}
        self.assertEqual([item["kind"] for item in prs[FEATURE]["findings"]], ["branch"])
        self.assertEqual(prs[FEATURE]["blocking"], [])


class CiGateTest(PrCase):
    def test_acceptance_needs_fast_ci_on_the_current_branch(self) -> None:
        self.to_acceptance(FEATURE)
        self.assertTrue(self.tracker("gate", FEATURE, "acceptance")["result"]["passed"])
        self.branch_file(FEATURE, "internal/c.go")
        git(self.root / "be" / BRANCH, "add", "-A")
        git(self.root / "be" / BRANCH, "commit", "-q", "-m", "late change")
        error = self.tracker("gate", FEATURE, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn("fast CI is stale (be ran on", error)
        self.tracker("ci", "run", FEATURE, succeeds=False)  # parent needs --parent-confirmed
        result = self.tracker("ci", "run", FEATURE, "--parent-confirmed")["result"]
        self.assertEqual((result["check"], result["result"]), ("ci-fast", "passed"))
        self.assertTrue(self.tracker("gate", FEATURE, "acceptance")["result"]["passed"])


class WorkspaceConfigTest(PrCase):
    workspace = {"ci": {"fast": {"ops": ["true"]}}}

    def test_unknown_ci_repo_is_refused(self) -> None:
        error = self.tracker("worktree", "status", succeeds=False)["error"]["message"]
        self.assertIn('"ci" names unknown repos ops', error)


if __name__ == "__main__":
    unittest.main()
