"""0.8.0: parallel scheduling (waves, defer), early start with batch gating, init state, and plan overlap."""
from __future__ import annotations

import json
import unittest

from test_workflow import CliTestCase, sha256, spec_text

EARLY = "0001-next"
PLAN = """## Ownership
- `be/internal/next/**`

## Findings
- be/internal/next/store.go:1 starts here.

## Batch 1: independent helpers
**Requirements:** REQ-001, REQ-002
**Requires:** none

## Batch 2: uses the dependency
**Requirements:** REQ-003, REQ-004
**Requires:** 0000

## Batch 3: unmarked
**Requirements:** REQ-005

## Stop conditions
- A listed file is missing.

## Out of scope
- Refactors.
"""


def body(count: int) -> str:
    return "# Demo\n\n" + "".join(f"- **R{n}** Behavior {n}.\n" for n in range(1, count + 1))


class ScheduleCase(CliTestCase):
    def accept(self, *names: str) -> None:
        """Mark specs accepted as baselines (no record needed) by writing the archive manifest directly."""
        path = self.root / "implementation" / "spec-archive.json"
        path.parent.mkdir(exist_ok=True)
        manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "archived": {}, "history": []}
        for name in names:
            manifest["archived"][name] = {"spec_sha256": sha256(self.root / "specs" / name), "implementation_record": None,
                                         "implementation_sha256": None, "archived_at": "2026-10-27T00:00:00Z", "baseline": True}
        path.write_text(json.dumps(manifest), encoding="utf-8")


class WavesTest(ScheduleCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_spec("0001-a.md", spec_text(1, "a", depends_on=[0]))
        self.write_spec("0002-b.md", spec_text(2, "b", depends_on=[1]))
        self.write_spec("0003-c.md", spec_text(3, "c", depends_on=[2]))
        self.write_spec("0004-d.md", spec_text(4, "d"))
        self.accept("0000-demo.md")

    def waves(self) -> dict:
        return self.spec("waves")["result"]

    def test_startable_plannable_levels(self) -> None:
        result = self.waves()
        self.assertEqual([item["id"] for item in result["startable"]], [1, 4])
        self.assertEqual([(item["id"], item["blocked_on"]) for item in result["plannable"]], [(2, [1])])
        self.assertEqual([[item["id"] for item in group] for group in result["waves"]], [[1, 4], [2], [3]])
        self.assertEqual(result["deferred"], [])
        self.assertEqual([item["id"] for item in self.spec("ready")["result"]], [1, 4])

    def test_in_progress_dependency_allows_planning_ahead(self) -> None:
        self.tracker("init", "specs/0001-a.md")
        result = self.waves()
        self.assertEqual([item["id"] for item in result["plannable"]], [2])
        self.assertIn(1, [item["id"] for item in result["startable"]])
        self.assertNotIn(3, [item["id"] for item in result["plannable"]])  # its dependency 0002 is neither started nor startable

    def test_deferred_specs_leave_every_list_and_stay_linkable(self) -> None:
        self.write_spec("0005-e.md", spec_text(5, "e", depends_on=[4]))
        self.spec("defer", "4", "--reason", "not ready", "--parent-confirmed")
        listed = {item["id"]: item["status"] for item in self.spec("list")["result"]}
        self.assertEqual(listed[4], "deferred")
        self.assertIn("[deferred]", self.text("list"))
        self.assertEqual([item["id"] for item in self.spec("ready")["result"]], [1])
        self.assertEqual(self.spec("next")["result"]["id"], 1)
        result = self.waves()
        self.assertEqual([(item["id"], item["reason"]) for item in result["deferred"]], [(4, "not ready")])
        everywhere = [item["id"] for key in ("startable", "plannable") for item in result[key]] + [item["id"] for group in result["waves"] for item in group]
        self.assertNotIn(4, everywhere)
        self.assertNotIn(5, [item["id"] for item in result["plannable"]])
        self.assertTrue(self.spec("validate")["result"]["valid"])
        self.tracker("init", "specs/0004-d.md", succeeds=False)
        self.spec("undefer", "4", "--parent-confirmed")
        self.assertEqual([item["id"] for item in self.waves()["startable"]], [1, 4])
        self.tracker("init", "specs/0004-d.md")

    def test_defer_rules(self) -> None:
        self.spec("defer", "4", "--reason", "x", succeeds=False)  # needs --parent-confirmed
        self.spec("defer", "4", "--reason", " ", "--parent-confirmed", succeeds=False)
        self.spec("defer", "0", "--reason", "x", "--parent-confirmed", succeeds=False)  # accepted
        self.spec("undefer", "4", "--parent-confirmed", succeeds=False)
        self.spec("defer", "4", "--reason", "x", "--parent-confirmed")
        self.spec("defer", "4", "--reason", "x", "--parent-confirmed", succeeds=False)
        self.tracker("init", "specs/0001-a.md")
        self.spec("defer", "1", "--reason", "x", "--parent-confirmed", succeeds=False)  # in progress

    def test_waves_text(self) -> None:
        self.spec("defer", "4", "--reason", "later", "--parent-confirmed")
        lines = self.text("waves").splitlines()
        self.assertEqual(lines[0], "startable: 0001 a")
        self.assertEqual(lines[1], "plannable: 0002 b (blocked on 0001)")
        self.assertIn("wave 1: 0002 b (waiting on 0001)", lines)
        self.assertEqual(lines[-1], "deferred: 0004 d (later)")


class EarlyCase(ScheduleCase):
    feature = EARLY

    def setUp(self) -> None:
        super().setUp()
        self.write_spec("0000-demo.md", spec_text(0, "demo", body=body(2)))
        self.write_spec(f"{EARLY}.md", spec_text(1, "next", body=body(5), depends_on=[0]))
        (self.root / "implementation").mkdir(exist_ok=True)
        (self.root / "implementation" / "preflight.json").write_text(json.dumps({"commands": ["cd be && go version"]}), encoding="utf-8")

    def record(self, feature: str = EARLY) -> dict:
        return json.loads((self.root / "implementation" / "active" / f"{feature}.json").read_text(encoding="utf-8"))

    def early_planned(self) -> None:
        self.tracker("init", f"specs/{EARLY}.md", "--early")
        self.tracker("requirement", "import", EARLY)
        self.handoff("planner")
        path = self.root / "plan.md"
        path.write_text(PLAN, encoding="utf-8")
        self.tracker("plan", "add", EARLY, "--from", str(path))
        self.handoff("parent")


class EarlyStartTest(EarlyCase):
    def test_init_early_allowed_when_dependency_is_startable(self) -> None:
        self.tracker("init", f"specs/{EARLY}.md", succeeds=False)
        result = self.tracker("init", f"specs/{EARLY}.md", "--early")["result"]
        self.assertEqual((result["early"], result["blocked_on"], result["blocked_on_pending"]), (True, ["0000"], ["0000"]))
        self.assertEqual(self.record()["blocked_on"], ["0000"])
        self.assertIn("[early, waiting on 0000]", self.cli_text("status"))

    def cli_text(self, *arguments: str) -> str:
        import subprocess
        import sys
        from test_workflow import TRACKER
        return subprocess.run([sys.executable, str(TRACKER), *arguments], cwd=self.root, text=True, capture_output=True, check=True).stdout

    def test_init_early_allowed_when_dependency_is_in_progress(self) -> None:
        self.write_spec("0002-more.md", spec_text(2, "more", depends_on=[1]))
        self.tracker("init", "specs/0002-more.md", "--early", succeeds=False)  # 0001 is neither started nor startable
        self.tracker("init", "specs/0000-demo.md")
        self.tracker("init", f"specs/{EARLY}.md", "--early")
        self.tracker("init", "specs/0002-more.md", "--early")
        self.assertEqual(self.record("0002-more")["blocked_on"], ["0001"])

    def test_init_early_refused_otherwise_and_user_decision_path_kept(self) -> None:
        self.write_spec("0002-more.md", spec_text(2, "more", depends_on=[1]))
        refused = self.tracker("init", "specs/0002-more.md", "--early", succeeds=False)
        self.assertIn("in progress or startable", refused["error"]["message"])
        self.tracker("init", "specs/0002-more.md", "--early", "--parent-confirmed", "--user-decision", "user said go")
        record = self.record("0002-more")
        self.assertNotIn("early", record)
        self.assertEqual(record["dependency_overrides"][0]["user_decision"], "user said go")

    def test_init_early_on_ready_spec_is_a_normal_init(self) -> None:
        result = self.tracker("init", "specs/0000-demo.md", "--early")["result"]
        self.assertNotIn("early", result)

    def test_requires_parsing(self) -> None:
        self.early_planned()
        batches = self.record()["plans"][0]["batches"]
        self.assertEqual([item["requires"] for item in batches], [[], ["0000"], None])

    def test_requires_must_name_specs(self) -> None:
        self.tracker("init", f"specs/{EARLY}.md", "--early")
        self.tracker("requirement", "import", EARLY)
        self.handoff("planner")
        path = self.root / "plan.md"
        path.write_text(PLAN.replace("**Requires:** 0000", "**Requires:** the loader"), encoding="utf-8")
        self.tracker("plan", "add", EARLY, "--from", str(path), succeeds=False)

    def test_batches_gate_on_requires_and_escape_hatch(self) -> None:
        self.early_planned()
        self.tracker("assign", EARLY, "--role", "implementer", "--from-plan", "--batch", "2", "--parent-confirmed", succeeds=False)
        self.tracker("assign", EARLY, "--role", "implementer", "--from-plan", "--parent-confirmed")  # batch 1 can run
        self.handoff("implementer")
        self.assertIn("**Requires:** none", self.tracker("brief", EARLY, "--role", "implementer", "--batch", "1")["result"])
        for number in ("2", "3"):  # explicit dependency, and no Requires line (counts as all of blocked_on)
            for extra in ((), ("--parent-confirmed",)):
                refused = self.tracker("brief", EARLY, "--role", "implementer", "--batch", number, *extra, succeeds=False)
                self.assertIn("early start", refused["error"]["message"])
        brief = self.tracker("brief", EARLY, "--role", "implementer", "--batch", "2", "--parent-confirmed", "--user-decision", "start now")["result"]
        self.assertIn("started before 0000: start now", brief)
        self.assertEqual(self.record()["dependency_overrides"][-1]["during"], "brief")

    def test_batches_unlock_when_required_specs_are_accepted(self) -> None:
        self.early_planned()
        self.handoff("implementer")
        refused = self.tracker("brief", EARLY, "--role", "implementer", "--batch", "2", succeeds=False)
        self.assertIn("early start", refused["error"]["message"])
        self.accept("0000-demo.md")
        self.tracker("assign", EARLY, "--role", "implementer", "--from-plan", "--parent-confirmed")
        for number in ("2", "3"):
            self.tracker("brief", EARLY, "--role", "implementer", "--batch", number)
        self.assertEqual(self.tracker("status", EARLY)["result"]["blocked_on_pending"], [])

    def test_acceptance_and_archive_wait_for_blocked_on(self) -> None:
        self.early_planned()
        failed = self.tracker("gate", EARLY, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn("early start: required specs are not accepted yet: 0000", failed)
        archived = self.tracker("archive", EARLY, "--parent-confirmed", succeeds=False)["error"]["message"]
        self.assertIn("0000", archived)
        self.accept("0000-demo.md")
        again = self.tracker("gate", EARLY, "acceptance", succeeds=False)["error"]["message"]
        self.assertNotIn("early start", again)


class InitStateTest(EarlyCase):
    def test_init_leaves_the_record_with_the_parent(self) -> None:
        result = self.tracker("init", "specs/0000-demo.md")["result"]
        self.assertEqual((result["status"], result["current_role"]), ("new", "parent"))
        self.assertEqual(self.record("0000-demo")["schema_version"], 1)

    def test_handoff_to_planner_from_new_and_back_to_parent(self) -> None:
        self.feature = "0000-demo"
        self.tracker("init", "specs/0000-demo.md")
        self.assertEqual(self.handoff("planner")["result"]["status"], "planning")

    def test_old_flow_handoff_to_parent_after_init_still_works(self) -> None:
        self.feature = "0000-demo"
        self.tracker("init", "specs/0000-demo.md")
        self.assertEqual(self.handoff("parent")["result"]["status"], "awaiting_parent")
        self.handoff("parent", succeeds=False)  # only the first look is a no-op

    def replan_args(self) -> tuple[str, ...]:
        return ("handoff", "0000-demo", "--to", "planner", "--completed", "none", "--remaining", "plan it")

    def implementing(self) -> None:
        self.feature = "0000-demo"
        self.tracker("init", "specs/0000-demo.md")
        self.tracker("requirement", "import", "0000-demo")
        self.handoff("implementer")

    def test_parent_replans_an_implementer_that_has_implemented_nothing(self) -> None:
        self.implementing()
        self.tracker(*self.replan_args(), succeeds=False)
        self.assertEqual(self.tracker(*self.replan_args(), "--parent-confirmed")["result"]["current_role"], "planner")

    def test_no_replan_once_a_requirement_is_implemented(self) -> None:
        self.implementing()
        self.tracker("requirement", "implemented", "0000-demo", "REQ-001", "--evidence", "done")
        self.tracker(*self.replan_args(), "--parent-confirmed", succeeds=False)

    def test_old_implementer_records_keep_working(self) -> None:
        self.feature = "0000-demo"
        self.tracker("init", "specs/0000-demo.md")
        self.tracker("requirement", "import", "0000-demo")
        path = self.root / "implementation" / "active" / "0000-demo.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record.update(status="implementing", current_role="implementer")  # as written by 0.7.x
        path.write_text(json.dumps(record), encoding="utf-8")
        self.tracker("requirement", "implemented", "0000-demo", "REQ-001", "--evidence", "done")
        self.assertEqual(self.tracker("status", "0000-demo")["result"]["current_role"], "implementer")


class OverlapPlansTest(EarlyCase):
    def test_overlapping_plans_and_lanes_are_reported(self) -> None:
        self.write_spec("0002-solo.md", spec_text(2, "solo"))
        self.write_spec("0003-side.md", spec_text(3, "side"))
        self.accept("0000-demo.md")
        self.tracker("init", f"specs/{EARLY}.md")
        self.tracker("requirement", "import", EARLY)
        self.handoff("planner")
        path = self.root / "plan.md"
        path.write_text(PLAN, encoding="utf-8")
        self.tracker("plan", "add", EARLY, "--from", str(path))
        self.tracker("init", "specs/0002-solo.md")
        self.tracker("assign", "0002-solo", "--role", "implementer", "--paths", "be/internal/next/sub/**", "--parent-confirmed")
        self.tracker("init", "specs/0003-side.md")
        self.tracker("assign", "0003-side", "--role", "implementer", "--paths", "fe/src/**", "--parent-confirmed")
        result = self.tracker("overlap", "--plans")["result"]
        self.assertEqual([item["features"] for item in result], [[EARLY, "0002-solo"]])
        self.assertEqual(result[0]["globs"], ["be/internal/next/** <-> be/internal/next/sub/**"])
        self.assertEqual(self.tracker("overlap")["result"], [])  # the changed-files mode is unchanged


if __name__ == "__main__":
    unittest.main()


class FixerPlanOwnershipTest(EarlyCase):
    def test_fixer_assignment_keeps_plan_ownership_after_generation_bump(self) -> None:
        self.early_planned()
        path = self.root / "implementation" / "active" / f"{EARLY}.json"
        record = self.record()
        record["generation"] = int(record.get("generation", 1)) + 1  # a fix round bumps the generation
        path.write_text(json.dumps(record), encoding="utf-8")
        self.tracker("assign", EARLY, "--role", "fixer", "--from-plan", "--parent-confirmed")
        self.assertEqual(self.record()["assignments"][-1]["paths"], ["be/internal/next/**"])


class HandoffReleasesLaneTest(EarlyCase):
    def test_writer_lane_released_on_handoff(self) -> None:
        self.early_planned()
        self.tracker("assign", EARLY, "--role", "implementer", "--paths", "be/internal/next/**", "--parent-confirmed", "--user-decision", "go")
        self.tracker("handoff", EARLY, "--to", "implementer", "--completed", "c", "--remaining", "r", "--parent-confirmed", "--user-decision", "go")
        self.handoff("parent")
        active = [a for a in self.record()["assignments"] if a["status"] == "active" and a["role"] == "implementer"]
        self.assertEqual(active, [])
