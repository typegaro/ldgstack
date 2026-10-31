"""0.7.0: planner/executor split (plans, batches, questions), retest check names, auto tester lanes, models, brief hook, retro."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_improvements import COMPAT
from test_retro import RETRO, Transcript, usage
from test_workflow import FEATURE, PLUGIN, TRACKER, CliTestCase, spec_text

HOOK = PLUGIN / "hooks" / "brief_check.py"
sys.path.insert(0, str(PLUGIN / "skills" / "workflow-retro" / "scripts"))

from retrolib import transcripts  # noqa: E402

PLAN = """## Ownership
- `be/internal/demo/**`
- `fe/src/demo/**`

## Findings
- be/internal/demo/store.go:12 loads rows; `LC_ALL=C date -d 2026-10-25 +%A` -> Sunday.

## Batch 1: storage
**Requirements:** REQ-001, REQ-002, REQ-003
**Files:** be/internal/demo/store.go
```go
## not a heading inside a fence
func Load() {}
```

## Batch 2: UI
**Requirements:** REQ-004, REQ-005
**Files:** fe/src/demo/page.tsx

## Stop conditions
- A listed file is missing.

## Out of scope
- Refactors.
"""


def body(count: int) -> str:
    return "# Demo\n\n" + "".join(f"- **R{n}** Behavior {n}.\n" for n in range(1, count + 1))


class PlanCase(CliTestCase):
    requirements = 5

    def setUp(self) -> None:
        super().setUp()
        self.write_spec(f"{FEATURE}.md", spec_text(0, "demo", body=body(self.requirements)))
        (self.root / "implementation").mkdir()
        (self.root / "implementation" / "preflight.json").write_text(json.dumps({"commands": ["cd be && go version"]}), encoding="utf-8")
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "import", FEATURE)

    def record(self) -> dict:
        return json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))

    def plan_add(self, text: str, succeeds: bool = True) -> dict:
        path = self.root / "plan.md"
        path.write_text(text, encoding="utf-8")
        return self.tracker("plan", "add", FEATURE, "--from", str(path), succeeds=succeeds)

    def brief(self, *arguments: str, succeeds: bool = True) -> dict:
        return self.tracker("brief", FEATURE, *arguments, succeeds=succeeds)

    def planned(self) -> None:
        self.handoff("planner")
        self.plan_add(PLAN)
        self.handoff("parent")


class PlanTest(PlanCase):
    def test_implementer_needs_a_plan_and_planner_stores_it(self) -> None:
        error = self.handoff("implementer", succeeds=False)["error"]["message"]
        self.assertIn("a plan is required before implementation (5 requirements", error)
        self.assertEqual(self.handoff("planner")["result"]["status"], "planning")
        lane = [item for item in self.record()["assignments"] if item["status"] == "active"]
        self.assertEqual([(item["role"], item["paths"]) for item in lane], [("planner", [])])
        prompt = self.brief("--role", "planner")["result"]
        self.assertIn("references/planning.md", prompt)
        self.assertIn(f"plan add {FEATURE} --from -", prompt)
        self.handoff("parent", succeeds=False)  # no plan stored yet
        missing = self.plan_add("## Ownership\n- `be/**`\n", succeeds=False)["error"]["message"]
        for heading in ("Findings", "Stop conditions", "Out of scope", "Batch 1"):
            self.assertIn(heading, missing)
        self.assertIn("unknown requirement IDs: REQ-009", self.plan_add(PLAN.replace("REQ-005", "REQ-009"), succeeds=False)["error"]["message"])
        self.assertIn("../x", self.plan_add(PLAN.replace("`fe/src/demo/**`", "`../x`"), succeeds=False)["error"]["message"])
        partial = self.plan_add(PLAN.replace(", REQ-003", ""))["result"]
        self.assertEqual(partial["warnings"], ["requirements in no batch: REQ-003"])
        stdin = subprocess.run([sys.executable, str(TRACKER), "--json", "plan", "add", FEATURE, "--from", "-"], input=PLAN,
                               cwd=self.root, text=True, capture_output=True, check=True)
        stored = json.loads(stdin.stdout)["result"]
        self.assertEqual(stored["plan_version"], 2)
        self.assertEqual(stored["batches"], ["1: REQ-001, REQ-002, REQ-003", "2: REQ-004, REQ-005"])
        self.assertEqual(stored["ownership"], ["be/internal/demo/**", "fe/src/demo/**"])
        self.assertEqual(self.handoff("parent")["result"]["status"], "plan_ready")
        self.assertEqual(self.tracker("status", FEATURE)["result"]["plan_version"], 2)
        self.handoff("implementer")

    def test_assign_from_plan_and_batch_briefs(self) -> None:
        self.planned()
        self.handoff("implementer")
        assigned = self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--parent-confirmed")["result"]
        self.assertEqual(assigned["paths"], ["be/internal/demo/**", "fe/src/demo/**"])
        self.assertIn("--batch 1 (plan has 2 batches)", self.brief("--role", "implementer", succeeds=False)["error"]["message"])
        self.assertIn("Plan: v1, follow it literally:", self.brief("--role", "implementer", "--parent-confirmed")["result"])
        first = self.brief("--role", "implementer", "--batch", "1")["result"]
        self.assertIn("plan v1 batch 1 of 2 (final batch: no): REQ-001, REQ-002, REQ-003", first)
        self.assertIn("be/internal/demo/store.go", first)
        self.assertIn("`fe/src/demo/**`", first)  # ownership travels with every batch
        self.assertNotIn("fe/src/demo/page.tsx", first)  # other batches don't
        self.assertNotIn("Refactors", first)
        self.assertIn("parent resumes you with the next batch", first)
        second = self.brief("--role", "implementer", "--batch", "2")["result"]
        self.assertIn("final batch: yes", second)
        self.assertIn("earlier batches not yet implemented: REQ-001, REQ-002, REQ-003", second)
        self.assertIn(f"handoff {FEATURE} --to reviewer", second)
        self.assertIn("fe/src/demo/page.tsx", self.tracker("plan", "show", FEATURE, "--batch", "2")["result"])
        self.brief("--role", "implementer", "--batch", "3", succeeds=False)

    def test_question_answer_and_replan_routing(self) -> None:
        self.planned()
        self.handoff("implementer")
        self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--parent-confirmed")
        asked = self.tracker("handoff", FEATURE, "--to", "parent", "--question", "store.go:12 has no loader; add one?")["result"]
        self.assertEqual((asked["status"], asked["current_role"]), ("needs_answer", "parent"))
        self.assertEqual(asked["open_questions"], [f"Q-{FEATURE}-001 (implementer): store.go:12 has no loader; add one?"])
        answered = self.tracker("answer", FEATURE, "--text", "yes, in store.go")["result"]
        self.assertEqual((answered["status"], answered["current_role"], answered["open_questions"]), ("implementing", "implementer", []))
        prompt = self.brief("--role", "implementer", "--batch", "1")["result"]
        self.assertIn("(implementer asked: store.go:12 has no loader; add one?): yes, in store.go", prompt)
        self.tracker("handoff", FEATURE, "--to", "parent", "--question", "backfill rewrites snapshots?")
        replanned = self.tracker("answer", FEATURE, "--text", "no rewrites; plan a read-time fallback", "--replan")["result"]
        self.assertEqual((replanned["status"], replanned["current_role"]), ("planning", "planner"))
        self.assertIn("replan v1: no rewrites; plan a read-time fallback", self.brief("--role", "planner")["result"])
        self.handoff("parent")
        self.assertIn("no open question", self.tracker("answer", FEATURE, "--text", "x", succeeds=False)["error"]["message"])
        self.handoff("parent", succeeds=False)  # parent -> parent is not a handoff

    def test_parent_may_skip_the_plan_with_a_reason(self) -> None:
        self.tracker("handoff", FEATURE, "--to", "implementer", "--completed", "c", "--remaining", "r", "--parent-confirmed", succeeds=False)
        self.tracker("handoff", FEATURE, "--to", "implementer", "--completed", "c", "--remaining", "r", "--parent-confirmed", "--reason", "mechanical rename")
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/**", "--parent-confirmed")
        self.assertIn("no plan required: mechanical rename", self.brief("--role", "implementer")["result"])
        self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--parent-confirmed", succeeds=False)


class SmallSpecTest(PlanCase):
    requirements = 3

    def test_areas_require_a_plan(self) -> None:
        self.handoff("implementer")  # 3 requirements, no lane yet: no plan needed
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/**", "fe/**", "--parent-confirmed")
        self.assertIn("areas: be, fe", self.brief("--role", "implementer", succeeds=False)["error"]["message"])
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/**", "--parent-confirmed")
        self.brief("--role", "implementer")


class LargeSpecTest(PlanCase):
    requirements = 11

    def test_large_specs_need_batched_briefs(self) -> None:
        self.tracker("handoff", FEATURE, "--to", "implementer", "--completed", "c", "--remaining", "r", "--parent-confirmed", "--reason", "plan in head")
        self.tracker("assign", FEATURE, "--role", "implementer", "--paths", "be/**", "--parent-confirmed")
        self.assertIn("brief one batch at a time", self.brief("--role", "implementer", succeeds=False)["error"]["message"])
        self.assertIn("REQ-001, REQ-002", self.brief("--role", "implementer", "--batch", "REQ-001..REQ-005")["result"])
        self.brief("--role", "implementer", "--parent-confirmed")


class RetestTest(CliTestCase):
    def test_check_names_supersede_and_gates_name_the_role(self) -> None:
        (self.root / "implementation").mkdir()
        (self.root / "implementation" / "preflight.json").write_text(json.dumps({"commands": ["true"]}), encoding="utf-8")
        self.start()
        self.check("lint", "not_run")
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        tester_lane = [item for item in json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text())["assignments"]
                       if item["status"] == "active"]
        self.assertEqual([(item["role"], item["paths"], item["auto"]) for item in tester_lane], [("tester", [], True)])
        self.assertIn("Ownership: read-only", self.tracker("brief", FEATURE, "--role", "tester")["result"])
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("e2e", "failed")
        self.handoff("parent")
        error = self.tracker("gate", FEATURE, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn(f"e2e (failed, recorded by tester; the tester re-records it: `tracker handoff {FEATURE} --to tester", error)
        self.assertIn("lint (not_run, recorded by implementer; the fixer re-records it", error)
        refused = self.tracker("check", "add", FEATURE, "--name", "e2e", "--method", "m", "--result", "passed", "--evidence", "e",
                               "--parent-confirmed", succeeds=False)["error"]["message"]
        self.assertIn(f"route it back: `tracker handoff {FEATURE} --to tester", refused)
        self.handoff("tester")
        self.assertIn("re-record these names: lint, e2e", self.tracker("brief", FEATURE, "--role", "tester")["result"])
        result = self.tracker("check", "add", FEATURE, "--name", "e2e", "--method", "m", "--result", "passed", "--evidence", "e")["result"]
        self.assertEqual(result["superseded"], {"name": "e2e", "result": "failed", "role": "tester"})
        self.check("lint")
        self.handoff("parent")
        self.tracker("gate", FEATURE, "acceptance")


class ModelAndHookTest(unittest.TestCase):
    def test_agent_models(self) -> None:
        expected = {"spec-planner": "opus", "spec-reviewer": "opus", "spec-implementer": "sonnet", "spec-fixer": "sonnet",
                    "spec-tester": "sonnet", "spec-toolsmith": "sonnet"}
        for name, model in expected.items():
            head = (PLUGIN / "agents" / f"{name}.md").read_text(encoding="utf-8").split("\n---\n", 1)[0]
            self.assertIn(f"\nmodel: {model}", head, name)
        planner = (PLUGIN / "agents" / "spec-planner.md").read_text(encoding="utf-8").split("\n---\n", 1)[0]
        self.assertNotIn("Edit", re.search(r"tools: (.*)", planner).group(1))
        self.assertNotIn("Write", re.search(r"tools: (.*)", planner).group(1))

    def hook(self, tool: str, data: dict) -> str:
        event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": data, "cwd": "/tmp"}
        process = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), text=True, capture_output=True, check=True)
        return process.stdout

    def test_brief_hook_is_advisory(self) -> None:
        warned = json.loads(self.hook("Agent", {"subagent_type": "spec-workflow:spec-implementer", "prompt": "Run brief for 0033 and follow it"}))
        self.assertIn("lacks the `[Generated by spec-tracker brief` marker", warned["systemMessage"])
        self.assertTrue(self.hook("Task", {"subagent_type": "spec-planner", "prompt": "plan it"}))
        self.assertEqual(self.hook("Agent", {"subagent_type": "spec-workflow:spec-tester", "prompt": "[Generated by spec-tracker brief; ...]\nSpec: x"}), "")
        self.assertEqual(self.hook("Agent", {"subagent_type": "general-purpose", "prompt": "anything"}), "")
        self.assertEqual(self.hook("Bash", {"command": "ls"}), "")


class RetroModelTest(unittest.TestCase):
    def test_tracker_feature_regex_and_roles(self) -> None:
        command = "spec-tracker bug verify 0033-run-panel BUG-0033-run-panel-002 --retest x # session b43fa2d7-4b54-4832-8661-4d119a4394da 0034-current-date-in-v2"
        self.assertEqual(sorted(set(transcripts.TRACKER_FEATURE.findall(command))), ["0033-run-panel", "0034-current-date-in-v2"])
        self.assertEqual(transcripts.SPEC_ROLES["spec-toolsmith"], "toolsmith")
        self.assertEqual(transcripts.SPEC_ROLES["spec-planner"], "planner")

    def test_cost_by_model_clipping_and_plugin_dev(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, logs = root / "project", root / "logs"
            (project / "specs").mkdir(parents=True)
            (project / "AGENTS.md").write_text("# T\n", encoding="utf-8")
            main = Transcript()
            main.lines.append({"type": "assistant", "timestamp": "2026-10-20T10:00:00.000Z", "message": {
                "id": "old", "model": "claude-opus-x", "content": [{"type": "text", "text": "x"}], "usage": usage(1000, 0, 0, 0), "stop_reason": "end_turn"}})
            main.assistant("m1", [{"type": "text", "text": "ok"}], usage(10, 0, 0, 0), stop="end_turn")  # 2026-10-22T16:...
            main.lines[-1]["message"]["model"] = "claude-opus-x"
            main.write(logs / "s1.jsonl")
            for name, model, description in (("a1", "claude-opus-x", "Plan 0001"), ("a2", "claude-sonnet-y", "Execute 0001"),
                                              ("a3", "claude-sonnet-y", "[plugin-dev] patch retro")):
                agent = Transcript()
                agent.prompt("Role: planner. Record feature: 0001-demo.")
                agent.assistant(f"{name}-1", [{"type": "text", "text": "done"}], usage(100, 0, 0, 0), stop="end_turn")
                agent.lines[-1]["message"]["model"] = model
                agent.write(logs / "s1" / "subagents" / f"agent-{name}.jsonl")
                agent_type = "spec-workflow:spec-planner" if name == "a1" else "spec-workflow:spec-implementer"
                (logs / "s1" / "subagents" / f"agent-{name}.meta.json").write_text(json.dumps({"agentType": agent_type, "description": description}))
            process = subprocess.run([sys.executable, str(RETRO), "--project", str(project), "--transcripts", str(logs), "--json",
                                      "--since", "2026-10-22T00:00", "--model-weight", "sonnet=0.5"], text=True, capture_output=True, check=True)
            report = json.loads(process.stdout)
        self.assertEqual(report["totals"]["parent"]["weighted_tokens"], 10)  # the 10-20 call is clipped
        self.assertEqual(report["totals"]["subagents"]["runs"], 2)
        self.assertEqual(report["totals"]["plugin_dev"]["runs"], 1)
        self.assertEqual(report["totals"]["subagents"]["cost_units"], 100 + 50)
        models = {item["model"]: item for item in report["by_model"]}
        self.assertEqual((models["claude-sonnet-y"]["cost_units"], models["claude-sonnet-y"]["roles"]), (50, {"implementer": 1}))
        self.assertEqual(models["claude-opus-x"]["roles"], {"parent": 1, "planner": 1})
        self.assertEqual({item["role"] for item in report["by_role"]}, {"implementer", "planner"})


@unittest.skipUnless((COMPAT / "specs").is_dir() and (COMPAT / "implementation").is_dir(), "no compatibility fixture")
class PlanningCompatibilityTest(unittest.TestCase):
    """0.6.x records (no plans, questions, or planner role) keep working: validate, status, list, brief."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(COMPAT / "specs", self.root / "specs")
        shutil.copytree(COMPAT / "implementation", self.root / "implementation")
        # Claims bind live agents of the real project (e.g. a tester holding the test slot); the copy has none.
        shutil.rmtree(self.root / "implementation" / ".assignments", ignore_errors=True)
        (self.root / "AGENTS.md").write_text("# Copy\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, script: str, *arguments: str, succeeds: bool = True) -> dict:
        process = subprocess.run([str(PLUGIN / "bin" / script), "--json", *arguments], cwd=self.root, text=True, capture_output=True,
                                 env={**os.environ, "SPEC_WORKFLOW_ROOT": str(self.root)})
        result = json.loads(process.stdout)
        self.assertEqual(result["ok"], succeeds, result)
        return result

    def test_old_records_validate_status_list_and_brief(self) -> None:
        self.assertTrue(self.run_cli("spec", "validate")["result"]["valid"])
        for command in ("status", "list"):
            for record in self.run_cli("spec-tracker", command)["result"]:
                self.assertIn("open_questions", record)
        # Newest archived record whose spec predates Testability requirements (0.7.1).
        archived = [path.stem for path in sorted((self.root / "implementation" / "archive").glob("*.json"))
                    if "## Testability" not in (self.root / "specs" / f"{path.stem}.md").read_text(encoding="utf-8")][-1]
        self.run_cli("spec-tracker", "restore", archived, "--parent-confirmed")
        status = self.run_cli("spec-tracker", "status", archived)["result"]
        self.assertEqual((status["plan_version"], status["open_questions"]), (None, []))
        self.run_cli("spec-tracker", "handoff", archived, "--to", "implementer", "--completed", "c", "--remaining", "r",
                     "--parent-confirmed", "--reason", "compatibility fixture")
        for item in self.run_cli("spec-tracker", "requirement", "list", archived)["result"]:
            self.run_cli("spec-tracker", "requirement", "implemented", archived, item["id"], "--evidence", "compatibility")
        self.run_cli("spec-tracker", "check", "add", archived, "--name", "compat-unit", "--method", "fixture", "--result", "passed", "--evidence", "ok")
        self.run_cli("spec-tracker", "handoff", archived, "--to", "reviewer", "--completed", "c", "--remaining", "r")
        self.run_cli("spec-tracker", "check", "add", archived, "--name", "compat-review", "--method", "fixture", "--result", "passed", "--evidence", "ok")
        self.run_cli("spec-tracker", "handoff", archived, "--to", "tester", "--completed", "c", "--remaining", "r")
        prompt = self.run_cli("spec-tracker", "brief", archived, "--role", "tester")["result"]  # auto tester lane
        self.assertIn("Plan: not shown to this role", prompt)
        self.assertIn("direnv exec . go version", prompt)


if __name__ == "__main__":
    unittest.main()


class ReviewerFailedCheckHandoffTest(PlanCase):
    def test_reviewer_owned_failed_check_does_not_block_handoff_to_reviewer(self) -> None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/spec-tracker/scripts'))
        from tracker.model import gate_errors
        record = {"feature": "0000-demo", "requirements": [{"id": "REQ-001", "spec_ref": "0:R1", "verification": "v", "implemented": True, "tested": False}], "tool_gaps": [], "plan": None,
                  "checks": [{"name": "ok", "result": "passed", "role": "implementer"},
                             {"name": "rev", "result": "failed", "role": "reviewer"}],
                  "blockers": [], "bugs": []}
        import tracker.model as m
        orig = m.spec_matches
        m.spec_matches = lambda root, record: True
        try:
            self.assertFalse(any("failing" in e for e in gate_errors(self.root, record, "ready-test", exempt_roles=("tester", "reviewer"))))
            self.assertTrue(any("failing" in e for e in gate_errors(self.root, record, "ready-test")))
            self.assertTrue(any("failing" in e for e in gate_errors(self.root, record, "acceptance", exempt_roles=("tester", "reviewer"))))
        finally:
            m.spec_matches = orig
