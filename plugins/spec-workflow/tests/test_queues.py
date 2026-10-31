"""0.11.0: review, test and merge queues: auto-enqueue, slot classes, priority, leases, `queue wait`, and the merge queue."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest

from test_prs import PrCase
from test_workflow import FEATURE, TRACKER, spec_text
from test_worktrees import BRANCH, OTHER, git

THIRD = "0002-third"


class QueueCase(PrCase):
    workspace: dict = {"slots": {"review": 1, "test": {"stack": 1, "browser": 1}}}

    def setUp(self) -> None:
        super().setUp()
        self.write_spec(f"{THIRD}.md", spec_text(2, "third"))

    def to_review(self, feature: str) -> None:
        self.implement_in_branch(feature)
        self.handoff("reviewer")

    def to_tester(self, feature: str) -> None:
        self.to_review(feature)
        self.check("code-review")
        self.handoff("tester")

    def queue(self, name: str) -> dict:
        return self.tracker("queue", "status")["result"]["queues"][name]

    def claim(self, feature: str, role: str, agent: str) -> str:
        lane = next(item["id"] for item in self.record(feature)["assignments"] if item["status"] == "active" and item["role"] == role)
        markers = self.root / "implementation" / ".assignments"
        markers.mkdir(exist_ok=True)
        (markers / agent).write_text(lane + "\n", encoding="utf-8")
        return lane

    def finish_test(self, feature: str) -> None:
        self.feature = feature
        self.tracker("requirement", "tested", feature, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")


class SlotTest(QueueCase):
    def test_records_enqueue_themselves_and_take_slots_per_class(self) -> None:
        self.to_review(FEATURE)
        self.to_review(OTHER)
        review = self.queue("review")
        self.assertEqual(review["slots"], {"default": 1})
        self.assertEqual([(item["feature"], item["state"], item["assignment"]) for item in review["holders"]], [(FEATURE, "granted", None)])
        self.assertEqual([(item["feature"], item["position"], item["priority"]) for item in review["waiting"]], [(OTHER, 1, 0)])
        self.tracker("assign", OTHER, "--role", "reviewer", "--read-only", "--parent-confirmed")
        error = self.tracker("brief", OTHER, "--role", "reviewer", succeeds=False)["error"]["message"]
        self.assertIn(f"review slot busy: {FEATURE} holds the default slots", error)

        self.feature = FEATURE
        self.check("code-review")
        self.handoff("tester")  # frees the review slot, joins the test queue
        self.assertEqual([item["feature"] for item in self.queue("review")["holders"]], [OTHER])
        self.feature = OTHER
        self.check("code-review")
        self.handoff("tester")
        test = self.queue("test")
        self.assertEqual(test["slots"], {"stack": 1, "browser": 1})
        self.assertEqual([(item["feature"], item["class"]) for item in test["holders"]], [(FEATURE, "stack")])
        self.assertEqual([(item["feature"], item["class"]) for item in test["waiting"]], [(OTHER, "stack")])
        self.tracker("assign", OTHER, "--role", "tester", "--read-only", "--slot-class", "gpu", "--parent-confirmed", succeeds=False)
        self.tracker("assign", OTHER, "--role", "tester", "--read-only", "--slot-class", "browser", "--parent-confirmed")
        test = self.queue("test")
        self.assertEqual(sorted((item["feature"], item["class"]) for item in test["holders"]), [(FEATURE, "stack"), (OTHER, "browser")])
        self.tracker("brief", OTHER, "--role", "tester")

    def test_a_retest_goes_first(self) -> None:
        self.to_tester(FEATURE)
        self.to_tester(OTHER)
        self.to_tester(THIRD)
        self.report_bug()
        self.handoff("parent")
        self.tracker("bug", "assign", THIRD, f"BUG-{THIRD}-001", "--fixer", "fixer")
        self.handoff("fixer")
        self.tracker("bug", "fixed", THIRD, f"BUG-{THIRD}-001", "--fix", "f", "--regression", "r")
        self.check("unit")
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        self.assertEqual(self.record(THIRD)["status"], "ready_for_retest")
        waiting = self.queue("test")["waiting"]
        self.assertEqual([(item["feature"], item["priority"]) for item in waiting], [(THIRD, 1), (OTHER, 0)])
        self.finish_test(FEATURE)
        self.assertEqual([item["feature"] for item in self.queue("test")["holders"]], [THIRD])

    def test_json_shape(self) -> None:
        self.to_tester(FEATURE)
        lane = self.claim(FEATURE, "tester", "agent-t")
        result = self.tracker("queue", "status")["result"]
        self.assertEqual(set(result), {"queues", "agents"})
        self.assertEqual(set(result["queues"]), {"review", "test", "merge"})
        for name, entry in result["queues"].items():
            self.assertTrue({"slots", "holders", "waiting"} <= set(entry), name)
        self.assertIn("last", result["queues"]["merge"])
        holder = result["queues"]["test"]["holders"][0]
        self.assertEqual((holder["feature"], holder["class"], holder["assignment"], holder["state"]), (FEATURE, "stack", lane, "holding"))
        self.assertTrue({"feature", "class", "since", "assignment"} <= set(holder))
        agent = next(item for item in result["agents"] if item["assignment"] == lane)
        self.assertEqual(set(agent), {"assignment", "feature", "role", "model", "batch", "claimed_at"})
        self.assertEqual((agent["role"], agent["model"], agent["batch"]), ("tester", None, None))


class LeaseTest(QueueCase):
    workspace = {"slots": {"test": 1}, "lease": "2s"}

    def test_a_dead_agent_frees_its_slot(self) -> None:
        self.to_tester(FEATURE)
        self.to_tester(OTHER)
        self.tracker("brief", FEATURE, "--role", "tester")
        self.claim(FEATURE, "tester", "agent-dead")
        self.assertEqual(self.queue("test")["holders"][0]["state"], "holding")
        time.sleep(2.5)
        test = self.queue("test")
        self.assertEqual([item["feature"] for item in test["holders"]], [OTHER])
        self.assertEqual([item["feature"] for item in test["waiting"]], [FEATURE])
        state = json.loads((self.root / "implementation" / "queues.json").read_text(encoding="utf-8"))
        item = next(entry for entry in state["queues"]["test"]["items"] if entry["feature"] == FEATURE)
        self.assertEqual(item["lease_expired"][0]["state"], "holding")


class WaitTest(QueueCase):
    workspace = {"slots": {"test": 1}}

    def test_wait_exits_when_the_item_gets_its_slot(self) -> None:
        self.to_tester(FEATURE)
        self.to_tester(OTHER)
        error = self.tracker("queue", "wait", "test", "--feature", OTHER, "--timeout", "1", succeeds=False)["error"]["message"]
        self.assertIn("timed out after 1", error)
        self.assertIn("not in the review queue", self.tracker("queue", "wait", "review", "--feature", OTHER, succeeds=False)["error"]["message"])
        waiter = subprocess.Popen([sys.executable, str(TRACKER), "--json", "queue", "wait", "test", "--feature", OTHER, "--timeout", "60"],
                                  cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(1)
            self.assertIsNone(waiter.poll())
            self.finish_test(FEATURE)
            out, _ = waiter.communicate(timeout=20)
        finally:
            waiter.kill()
        self.assertEqual(waiter.returncode, 0)
        item = json.loads(out)["result"]
        self.assertEqual((item["queue"], item["feature"], item["state"]), ("test", OTHER, "granted"))
        self.assertIn(f"brief {OTHER} --role tester", item["next"])
        self.tracker("brief", OTHER, "--role", "tester")


class MergeQueueTest(PrCase):
    def run_merge(self) -> dict:
        return self.tracker("queue", "run", "merge", "--parent-confirmed")["result"]

    def test_merges_archives_and_rechecks_open_prs(self) -> None:
        self.implement_in_branch(FEATURE)
        self.tracker("queue", "add", "merge", FEATURE, "--parent-confirmed", succeeds=False)  # gate acceptance first
        self.feature = FEATURE
        self.open_pr(FEATURE)
        self.check("code-review")
        self.handoff("tester")
        self.finish()
        self.implement_in_branch(OTHER)
        self.branch_file(OTHER, "internal/b.go", "package other\n")
        self.open_pr(OTHER)
        self.main_commit("internal/z.go")  # main moved: merged into the branch first
        added = self.tracker("queue", "add", "merge", FEATURE, "--parent-confirmed")["result"]
        self.assertEqual((added["state"], added["position"]), ("granted", 0))
        result = self.run_merge()
        self.assertEqual(result["result"], "merged")
        main = self.root / "be" / "main"
        self.assertTrue((main / "internal" / "b.go").is_file() and (main / "internal" / "z.go").is_file())
        self.assertEqual(git(main, "log", "-1", "--format=%s"), f"Merge main into {BRANCH}")  # fast-forwarded
        self.assertFalse((self.root / "be" / BRANCH).exists())
        record = self.record(FEATURE, archived=True)
        self.assertEqual((record["status"], record["pr"]["state"]), ("accepted", "merged"))
        self.assertEqual(record["checks"][-1]["name"], "ci-fast")
        self.assertTrue((self.root / "post-merge-ran").is_file())
        self.assertEqual(result["spec_archive"], "archived")
        self.assertEqual(result["post_merge"][0]["exit"], 0)
        self.assertEqual([item["feature"] for item in result["conflicting_prs"]], [OTHER])
        self.assertEqual(result["conflicting_prs"][0]["blocking"], ["be/internal/b.go"])
        self.assertIsNone(result["queue_next"])
        last = self.queue_status()["merge"]["last"]
        self.assertEqual((last["feature"], last["result"]), (FEATURE, "merged"))
        prs = {item["feature"]: item for item in self.tracker("pr", "status")["result"]["prs"]}
        self.assertEqual((prs[FEATURE]["state"], prs[OTHER]["blocking"]), ("merged", ["be/internal/b.go"]))

    def finish(self) -> None:
        self.tracker("requirement", "tested", self.feature, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")

    def queue_status(self) -> dict:
        return self.tracker("queue", "status")["result"]["queues"]

    def test_conflict_returns_the_record_to_the_fixer(self) -> None:
        self.to_acceptance(FEATURE, "internal/a.go")
        before = self.main_commit("internal/a.go")
        self.tracker("queue", "add", "merge", FEATURE, "--parent-confirmed")
        result = self.run_merge()
        self.assertEqual((result["result"], result["files"]), ("conflict", ["be/internal/a.go"]))
        record = self.record()
        self.assertEqual((record["current_role"], record["status"]), ("fixer", "fixing"))
        self.assertEqual((record["bugs"][-1]["status"], record["bugs"][-1]["found_by"]), ("assigned", "merge-queue"))
        self.assertIn("be/internal/a.go", record["rereview_required"]["reason"])
        self.assertEqual(git(self.root / "be" / "main", "rev-parse", "HEAD"), before)
        self.assertEqual(self.queue_status()["merge"]["last"]["result"], "conflict")
        self.assertEqual(self.queue_status()["merge"]["waiting"] + self.queue_status()["merge"]["holders"], [])
        self.assertIn("fresh focused review", self.tracker("gate", FEATURE, "acceptance", succeeds=False)["error"]["message"])
        # The fixer merges main, resolves, and opens the PR again; the reviewer's brief points at the resolution.
        checkout = self.root / "be" / BRANCH
        subprocess.run(["git", "-C", str(checkout), "merge", "main"], capture_output=True, check=False)
        (checkout / "internal" / "a.go").write_text("package resolved\n", encoding="utf-8")
        git(checkout, "commit", "-qam", "Resolve")
        self.feature = FEATURE
        self.tracker("bug", "fixed", FEATURE, record["bugs"][-1]["id"], "--fix", "merged main", "--regression", "unit")
        self.check("unit")
        self.open_pr(FEATURE)
        self.tracker("assign", FEATURE, "--role", "reviewer", "--read-only", "--parent-confirmed")
        self.assertIn("Focus first on the merge with main an agent resolved", self.tracker("brief", FEATURE, "--role", "reviewer")["result"])

    def test_ci_failure_after_merging_main_returns_the_record(self) -> None:
        self.to_acceptance(FEATURE)
        before = self.main_commit("BREAK", "")
        self.tracker("queue", "add", "merge", FEATURE, "--parent-confirmed")
        result = self.run_merge()
        self.assertEqual(result["result"], "ci_failed")
        self.assertIn("`test ! -f BREAK`", result["failure"])
        record = self.record()
        self.assertEqual(record["current_role"], "fixer")
        self.assertNotIn("rereview_required", record)
        self.assertEqual(git(self.root / "be" / "main", "rev-parse", "HEAD"), before)
        self.assertTrue((self.root / "be" / BRANCH / "BREAK").is_file())  # the merge of main stays on the branch for the fixer
        self.assertEqual(self.queue_status()["merge"]["last"]["result"], "ci_failed")
        self.assertEqual(self.tracker("queue", "run", "merge", "--parent-confirmed")["result"]["message"], "merge queue is empty")


if __name__ == "__main__":
    unittest.main()
