"""0.10.7: m33 run feedback: late reviewer re-records, narrow restores, and parent-filed bugs."""
from __future__ import annotations

import json
import unittest

from test_workflow import FEATURE, CliTestCase


class LateReviewerCheckTest(CliTestCase):
    def to_parent_after_test(self) -> None:
        self.start()
        self.handoff("reviewer")
        self.check("code-review")
        self.check("determinism", "not_run")
        self.handoff("tester")
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")
        self.handoff("reviewer")

    def test_rerunning_a_not_run_reviewer_check_needs_no_new_test_round(self) -> None:
        self.to_parent_after_test()
        self.check("determinism")
        self.handoff("parent")
        self.assertTrue(self.tracker("gate", FEATURE, "acceptance")["result"]["passed"])

    def test_a_new_review_after_the_test_still_needs_a_test(self) -> None:
        self.to_parent_after_test()
        self.check("determinism")
        self.check("second-review")
        self.handoff("parent")
        errors = self.tracker("gate", FEATURE, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn("independent tester check must be recorded after the latest passing reviewer check", errors)


class NarrowRestoreTest(CliTestCase):
    def test_restore_touches_resets_only_the_named_requirements(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        for ref in ("Required behavior", "Second behavior"):
            self.tracker("requirement", "add", FEATURE, "--spec-ref", ref, "--verification", "API call")
        self.handoff("implementer")
        for identifier in ("REQ-001", "REQ-002"):
            self.tracker("requirement", "implemented", FEATURE, identifier, "--evidence", "done")
        self.check("unit")
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        for identifier in ("REQ-001", "REQ-002"):
            self.tracker("requirement", "tested", FEATURE, identifier, "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")
        self.tracker("archive", FEATURE, "--parent-confirmed")

        self.tracker("restore", FEATURE, "--touches", "REQ-009", "--parent-confirmed", succeeds=False)
        self.tracker("restore", FEATURE, "--touches", "REQ-002", "--parent-confirmed")
        record = json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))
        marks = {item["id"]: (item["implemented"], item["tested"]) for item in record["requirements"]}
        self.assertEqual(marks, {"REQ-001": (True, True), "REQ-002": (False, False)})
        self.assertEqual(record["generation"], 2)
        errors = self.tracker("gate", FEATURE, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn("REQ-002", errors)
        self.assertIn("no passing code review", errors)  # the fix still gets a fresh review and test


class ParentBugTest(CliTestCase):
    def add(self, *extra: str, succeeds: bool = True) -> dict:
        return self.tracker("bug", "add", FEATURE, "--title", "Escaped defect", "--severity", "medium", "--spec-ref", "R1",
                            "--environment", "local", "--reproduction", "run", "--expected", "a", "--actual", "b", "--evidence", "log",
                            *extra, succeeds=succeeds)

    def test_the_parent_files_final_review_findings(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.add(succeeds=False)  # the parent needs --parent-confirmed
        self.add("--parent-confirmed", succeeds=False)  # and names the finder
        self.add("--parent-confirmed", "--found-by", "final-review")
        record = json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))
        self.assertEqual(record["bugs"][0]["found_by"], "final-review")

    def test_reviewers_cannot_rename_the_finder(self) -> None:
        self.start()
        self.handoff("reviewer")
        self.add("--found-by", "someone-else", succeeds=False)
        self.add()


class RewriteTest(unittest.TestCase):
    def test_multi_directory_commands_keep_their_meaning(self) -> None:
        import sys
        from test_workflow import TRACKER
        sys.path.insert(0, str(TRACKER.parent))
        from tracker import workspace

        config = {"repos": ["be", "fe"], "main": "main"}
        command = "cd fe && npm test && cd .. && direnv exec fe npx x && (cd be && go test) && ls ../fe/src"
        once = workspace.rewrite(config, command, "main")
        self.assertEqual(once, "cd fe/main && npm test && cd ../.. && direnv exec fe/main npx x && (cd be/main && go test) && ls ../../fe/main/src")
        self.assertEqual(workspace.rewrite(config, once, "main"), once)  # idempotent
        explicit = "cd be/main && direnv exec ../fe/main node x"
        self.assertEqual(workspace.rewrite(config, explicit, "spec-1"), explicit)  # already names a checkout


if __name__ == "__main__":
    unittest.main()
