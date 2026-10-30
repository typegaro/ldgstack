"""Tests for dependency ordering, requirement import, relaxed roles, the light path, the Bash guard, and papercuts."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_workflow import FEATURE, GUARD, PLUGIN, TRACKER, CliTestCase, spec_text

# Optional fixture: a real project with specs/ and implementation/ (its compatibility tests are skipped when unset).
COMPAT = Path(os.environ.get("SPEC_WORKFLOW_COMPAT_ROOT") or "/nonexistent")

AMENDING_BODY = """# Amendment

## Requirements

- **R1** [api] First line `code` and
  continuation with a [link](x.md).
  - nested detail
- **R16a** Suffixed requirement.
- **R2** (replaces 0:R1) New behavior.
- **R3** (amends 0:R2, R9) Amended behavior.
- **R4**

```text
- **R99** not a requirement
```
"""


class ReadyTest(CliTestCase):
    """0 demo; 1 A; 2 B depends on A; 3 C independent; 4 D amends B; 5 decision."""

    def setUp(self) -> None:
        super().setUp()
        self.spec("new", "--title", "A", "--kind", "feature")
        self.spec("new", "--title", "B", "--kind", "feature", "--depends-on", "1")
        self.spec("new", "--title", "C", "--kind", "feature")
        self.spec("new", "--title", "D", "--kind", "change", "--amends", "2")
        self.spec("new", "--title", "E", "--kind", "decision")
        for number, slug in ((1, "a"), (2, "b"), (3, "c")):
            path = self.root / "specs" / f"{number:04d}-{slug}.md"
            path.write_text(path.read_text(encoding="utf-8").replace("- **R1** \n", "- **R1** Required behavior.\n"), encoding="utf-8")

    def ready(self) -> list[int]:
        return [item["id"] for item in self.spec("ready")["result"]]

    def accept_feature(self, feature: str) -> None:
        self.feature = feature
        self.implement()
        self.accept()
        self.spec("archive", feature, "--parent-confirmed")
        self.feature = FEATURE

    def test_ready_follows_depends_on_and_amends(self) -> None:
        self.assertEqual(self.ready(), [0, 1, 3])
        listed = {item["id"]: item for item in self.spec("list")["result"]}
        self.assertEqual((listed[2]["waiting_on"], listed[4]["waiting_on"]), ([1], [2]))
        self.assertIn("(waiting on 0001)", self.text("list"))
        self.assertEqual(self.spec("status")["result"]["ready"], [0, 1, 3])

        self.accept_feature("0001-a")
        self.assertEqual(self.ready(), [0, 2, 3])
        self.assertEqual(self.spec("next")["result"]["id"], 0)
        self.accept_feature(FEATURE)
        self.assertEqual(self.spec("next")["result"]["id"], 2)
        self.accept_feature("0002-b")
        self.assertEqual(self.ready(), [3, 4])
        self.spec("validate")

    def test_in_progress_spec_with_unaccepted_dependency_is_not_ready(self) -> None:
        self.tracker("init", "0002-b", succeeds=False)  # 0.6.0: dependency start guard
        self.tracker("init", "0002-b", "--parent-confirmed", "--user-decision", "User: start 0002 early")
        self.assertEqual(self.ready(), [0, 1, 3])

    def test_cycle_is_reported_clearly(self) -> None:
        self.write_spec("0006-x.md", spec_text(6, "x", depends_on=[7]))
        self.write_spec("0007-y.md", spec_text(7, "y", depends_on=[6]))
        message = self.spec("ready", succeeds=False)["error"]["message"]
        self.assertIn("dependency cycle: 0006 -> 0007 -> 0006", message)
        self.spec("next", succeeds=False)
        self.assertIn("dependency cycle", " ".join(self.spec("status")["result"]["errors"]))
        self.spec("validate", succeeds=False)


PLAN_TWO_BATCHES = """## Ownership
- `be/internal/**`

## Findings
- be/internal/a.go:1 starts here.

## Batch 1: first
**Requirements:** REQ-001, REQ-002, REQ-003
**Requires:** none
**Files:** `be/internal/a.go`

## Batch 2: second
**Requirements:** REQ-004, REQ-005, REQ-006
**Requires:** none
**Files:** `be/internal/b.go:12`, `be/internal/c_test.go`, `be/internal/**`

## Stop conditions
- A listed file is missing.

## Out of scope
- Refactors.
"""


class ImportTest(CliTestCase):
    feature = "0001-amendment"

    def setUp(self) -> None:
        super().setUp()
        self.write_spec(f"{FEATURE}.md", spec_text(0, "demo", body="# Demo\n\n- **R1** Required behavior.\n- **R2** Second behavior.\n"))
        self.write_spec("0001-amendment.md", spec_text(1, "amendment", "change", AMENDING_BODY, amends=[0]))
        self.tracker("init", self.feature, "--parent-confirmed", "--user-decision", "User: start before 0000 is accepted")
        self.handoff("parent")

    def requirements(self) -> list[dict]:
        return self.tracker("requirement", "list", self.feature)["result"]

    def test_import_parses_bullets_and_is_idempotent(self) -> None:
        result = self.tracker("requirement", "import", self.feature, "--exclude-amended")["result"]
        self.assertEqual(result["added"], ["REQ-001 1:R1", "REQ-002 1:R16a", "REQ-003 1:R2", "REQ-004 1:R3"])
        self.assertIn("1:R4 has no text; skipped", result["warnings"])
        listed = self.requirements()
        self.assertEqual(listed[0]["verification"], "[api] First line code and continuation with a link. - nested detail")
        self.assertEqual(listed[2]["verification"], "(replaces 0:R1) New behavior.")

        again = self.tracker("requirement", "import", self.feature, "--exclude-amended")["result"]
        self.assertEqual((again["added"], again["skipped"]), ([], ["1:R1", "1:R16a", "1:R2", "1:R3"]))

        amended = self.tracker("requirement", "import", self.feature)["result"]  # 0.8.4: amended targets by default (#62)
        self.assertEqual(amended["added"], ["REQ-005 0:R1", "REQ-006 0:R2"])
        self.assertIn("1:R3 references 0:R9, which was not found; skipped", amended["warnings"])
        listed = self.requirements()
        self.assertEqual(listed[4]["verification"], "Replaced by 1:R2: the replacement holds and the original no longer applies where replaced. Original: Required behavior.")
        self.assertTrue(listed[5]["verification"].startswith("Amended by 1:R3"))
        self.assertEqual(self.tracker("requirement", "import", self.feature, "--include-amended")["result"]["added"], [])

    def test_import_roles_and_spec_hash(self) -> None:
        self.tracker("requirement", "add", self.feature, "--spec-ref", "1:R1", "--verification", "manual")
        self.handoff("implementer")
        self.tracker("requirement", "import", self.feature, succeeds=False)
        result = self.tracker("requirement", "import", self.feature, "--parent-confirmed")["result"]
        self.assertEqual(result["skipped"], ["1:R1"])
        record = json.loads((self.root / "implementation" / "active" / f"{self.feature}.json").read_text(encoding="utf-8"))
        self.assertEqual(record["requirements"][1]["added_during_role"], "implementer")

        path = self.root / "specs" / "0001-amendment.md"
        path.write_text(path.read_text(encoding="utf-8") + "- **R5** Late addition.\n", encoding="utf-8")
        self.handoff("parent")
        self.assertIn("spec-sync", self.tracker("requirement", "import", self.feature, succeeds=False)["error"]["message"])
        synced = self.tracker("spec-sync", self.feature, "--reason", "draft edit", "--parent-confirmed")["result"]
        self.assertEqual(synced["added"], ["REQ-007 1:R5"])  # spec-sync re-imports itself (0.8.4)
        self.assertEqual(self.tracker("requirement", "import", self.feature)["result"]["added"], [])

    def test_spec_sync_invalidates_only_changed_requirements(self) -> None:
        self.tracker("requirement", "import", self.feature)  # REQ-001..004 own, REQ-005 0:R1 (cited by 1:R2), REQ-006 0:R2 (cited by 1:R3)
        self.tracker("handoff", self.feature, "--to", "implementer", "--completed", "work", "--remaining", "next",
                     "--parent-confirmed", "--reason", "reconciliation test")
        for rid in ("REQ-001", "REQ-003", "REQ-004", "REQ-005", "REQ-006"):
            self.tracker("requirement", "implemented", self.feature, rid, "--evidence", f"old {rid}")
        self.check("unit")
        self.handoff("parent")
        path = self.root / "specs" / "0001-amendment.md"
        changed = path.read_text(encoding="utf-8").replace("First line `code` and", "Changed contract and").replace(
            "- **R16a** Suffixed requirement.\n", "").replace("New behavior.", "Newer behavior.")
        path.write_text(changed + "- **R9** Brand new.\n", encoding="utf-8")
        synced = self.tracker("spec-sync", self.feature, "--reason", "contract changed", "--parent-confirmed")["result"]
        self.assertEqual(synced["generation"], 1)
        self.assertEqual(synced["changed"], ["REQ-001 1:R1", "REQ-003 1:R2", "REQ-005 0:R1"])  # 0:R1 follows its citing 1:R2
        self.assertEqual((synced["added"], synced["retired"]), (["REQ-007 1:R9"], ["REQ-002 1:R16a"]))
        self.assertEqual(synced["pending"], [])
        record = json.loads((self.root / "implementation" / "active" / f"{self.feature}.json").read_text(encoding="utf-8"))
        marks = {item["id"]: (item["implemented"], item["implementation_evidence"]) for item in record["requirements"]}
        self.assertEqual(marks["REQ-004"], (True, "old REQ-004"))
        self.assertEqual(marks["REQ-006"], (True, "old REQ-006"))
        self.assertEqual((marks["REQ-001"], marks["REQ-003"], marks["REQ-007"]), ((False, ""), (False, ""), (False, "")))
        self.assertEqual(record["requirements"][0]["evidence_history"][-1]["implementation_evidence"], "old REQ-001")
        self.assertEqual(record["specification"]["history"][-1]["changed"], synced["changed"])
        self.assertEqual(self.tracker("requirement", "import", self.feature)["result"]["added"], [])
        listed = self.tracker("requirement", "list", self.feature)["result"]
        self.assertNotIn("1:R16a", {item["spec_ref"] for item in listed})
        self.assertEqual(listed[0]["verification"], "[api] Changed contract and continuation with a link. - nested detail")

    def test_spec_sync_keeps_the_plan_and_marks_it_stale(self) -> None:
        self.tracker("requirement", "import", self.feature)
        self.handoff("planner")
        plan = self.root / "plan.md"
        plan.write_text(PLAN_TWO_BATCHES, encoding="utf-8")
        self.tracker("plan", "add", self.feature, "--from", str(plan))
        self.handoff("parent")
        self.assertNotIn("plan_stale", self.tracker("status", self.feature)["result"])
        path = self.root / "specs" / "0001-amendment.md"
        path.write_text(path.read_text(encoding="utf-8").replace("Suffixed requirement.", "Suffixed requirement, amended."), encoding="utf-8")
        synced = self.tracker("spec-sync", self.feature, "--reason", "R16a amended", "--parent-confirmed")["result"]
        self.assertEqual((synced["changed"], synced["plan_version"]), (["REQ-002 1:R16a"], 1))
        self.assertIn("REQ-002 (batch 1)", synced["plan_stale"])
        self.assertIn("plan_stale", self.tracker("status", self.feature)["result"])
        (self.root / "implementation" / "preflight.json").write_text(json.dumps({"commands": ["true"]}), encoding="utf-8")
        self.handoff("implementer")
        self.tracker("assign", self.feature, "--role", "implementer", "--from-plan", "--parent-confirmed")
        process = subprocess.run([sys.executable, str(TRACKER), "brief", self.feature, "--role", "implementer", "--batch", "2"],
                                 cwd=self.root, text=True, capture_output=True, check=True)
        self.assertIn("WARNING: plan v1 is stale", process.stdout)
        self.assertIn("warning: plan v1 is stale", process.stderr)
        self.assertIn("be/internal/b.go", process.stdout.split("First turn:", 1)[1].splitlines()[0])
        self.handoff("parent")
        self.handoff("planner")
        self.tracker("plan", "add", self.feature, "--from", str(plan))
        self.handoff("parent")
        self.assertNotIn("plan_stale", self.tracker("status", self.feature)["result"])


class RoleTest(CliTestCase):
    def tested_round(self) -> None:
        self.implement()
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")

    def record(self) -> dict:
        return json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))

    def test_implementer_to_tester_only_after_review_for_new_requirements(self) -> None:
        self.start()
        self.assertIn("first round must go through the reviewer", self.handoff("tester", succeeds=False)["error"]["message"])
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")

        self.tracker("requirement", "add", FEATURE, "--spec-ref", "0:R2", "--verification", "amended")
        self.handoff("implementer")
        self.tracker("requirement", "implemented", FEATURE, "REQ-002", "--evidence", "done")
        self.assertEqual(self.handoff("tester")["result"]["status"], "ready_for_test")
        self.assertTrue(self.record()["handoff"]["review_skipped"])
        self.handoff("parent")

        self.handoff("implementer")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "reworked")
        self.check("unit")
        message = self.handoff("tester", succeeds=False)["error"]["message"]
        self.assertIn("first round must go through the reviewer", message)
        self.handoff("reviewer")

    def test_parent_adds_requirements_and_resolves_blockers_in_any_role(self) -> None:
        self.start()
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "x", "--verification", "y", succeeds=False)
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "x", "--verification", "y", "--parent-confirmed")
        self.tracker("blocker", "add", FEATURE, "--summary", "s", "--report", "r")
        self.tracker("blocker", "resolve", FEATURE, f"BLOCKER-{FEATURE}-001", "--resolution", "r", succeeds=False)
        self.tracker("blocker", "resolve", FEATURE, f"BLOCKER-{FEATURE}-001", "--resolution", "spec answers it", "--parent-confirmed")
        record = self.record()
        self.assertEqual(record["current_role"], "implementer")
        self.assertEqual(record["requirements"][1]["added_during_role"], "implementer")
        self.assertEqual(record["blockers"][0]["resolved_during_role"], "implementer")

    def test_light_path_needs_existing_independent_evidence(self) -> None:
        self.tested_round()
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "0:R1 detail", "--verification", "covered by unit")
        tested = ("requirement", "tested", FEATURE, "REQ-002", "--evidence", "covered")
        implemented = ("requirement", "implemented", FEATURE, "REQ-002", "--evidence", "existing code")
        self.tracker(*implemented, "--parent-confirmed", succeeds=False)
        self.tracker(*implemented, "--evidence-from", "unit", succeeds=False)
        self.tracker(*implemented, "--parent-confirmed", "--evidence-from", "missing", succeeds=False)
        self.tracker(*implemented, "--parent-confirmed", "--evidence-from", "unit")
        self.tracker(*tested, "--parent-confirmed", "--evidence-from", "unit", succeeds=False)
        message = self.tracker(*tested, "--parent-confirmed", "--evidence-from", "independent", succeeds=False)["error"]["message"]
        self.assertIn("ran before the requirement was implemented", message)

        self.handoff("tester")
        self.check("independent")
        self.tracker(*tested, "--parent-confirmed", "--evidence-from", "independent", succeeds=False)
        self.handoff("parent")
        self.tracker(*tested, "--parent-confirmed", "--evidence-from", "independent")
        gate = self.tracker("gate", FEATURE, "acceptance")["result"]
        self.assertEqual([(item["id"], sorted(item) ) for item in gate["parent_attested"]], [("REQ-002", ["id", "implemented", "spec_ref", "tested"])])
        markdown = (self.root / "implementation" / "active" / f"{FEATURE}.md").read_text(encoding="utf-8")
        self.assertIn("yes (parent, from independent)", markdown)

    def test_parent_checks_and_not_applicable(self) -> None:
        self.tested_round()
        self.handoff("implementer")
        self.check("lint", "failed")
        self.handoff("parent")
        self.tracker("check", "add", FEATURE, "--name", "lint", "--method", "make lint", "--result", "passed", "--evidence", "ok", succeeds=False)
        self.tracker("check", "add", FEATURE, "--name", "lint", "--method", "make lint", "--result", "passed", "--evidence", "ok", "--parent-confirmed")
        override = ("check", "add", FEATURE, "--name", "independent", "--method", "x", "--result", "passed", "--evidence", "x", "--parent-confirmed")
        self.assertIn("tester's check", self.tracker(*override, succeeds=False)["error"]["message"])
        self.tracker("check", "add", FEATURE, "--name", "inspect-check-all", "--method", "inspect check all", "--result", "not_applicable",
                     "--evidence", "the inspection CLI has no check all", "--parent-confirmed")
        gate = self.tracker("gate", FEATURE, "acceptance")["result"]
        self.assertEqual(gate["checks_not_applicable"], ["inspect-check-all"])


class PapercutTest(CliTestCase):
    def test_gate_accepts_both_argument_orders(self) -> None:
        self.start()
        process = subprocess.run([str(PLUGIN / "bin" / "spec-tracker"), "--json", "gate", "ready-test", FEATURE],
                                 cwd=self.root, text=True, capture_output=True, check=True)
        self.assertTrue(json.loads(process.stdout)["result"]["passed"])
        self.assertIn("deprecated", process.stderr)
        self.tracker("gate", FEATURE, "ready-test")
        self.tracker("gate", FEATURE, "nope", succeeds=False)

    def test_bug_ids_accept_short_form(self) -> None:
        self.implement()
        self.tracker("bug", "add", FEATURE, "--title", "t", "--severity", "low", "--spec-ref", "r", "--environment", "e",
                     "--reproduction", "r", "--expected", "e", "--actual", "a", "--evidence", "e")
        self.handoff("parent")
        self.tracker("bug", "assign", FEATURE, "BUG-001", "--fixer", "f")
        self.assertEqual(self.tracker("status", FEATURE)["result"]["bugs"], {"assigned": 1})

    def test_drafts_new_from_and_promote(self) -> None:
        drafts = self.root / "specs" / ".drafts"
        drafts.mkdir()
        (drafts / "proposal.md").write_text("# Proposal\n\n- **R1** Proposed behavior.\n\n## Testability\n\nNot applicable: test fixture.\n", encoding="utf-8")
        self.spec("new", "--title", "Proposal", "--kind", "feature", "--from", "README.md", succeeds=False)
        created = self.spec("new", "--title", "Proposal", "--kind", "feature", "--from", "specs/.drafts/proposal.md")["result"]
        self.assertTrue((self.root / created["path"]).read_text(encoding="utf-8").endswith("---\n\n# Proposal\n\n- **R1** Proposed behavior.\n\n## Testability\n\nNot applicable: test fixture.\n"))
        self.assertFalse((drafts / "proposal.md").exists())
        self.spec("validate")

        (drafts / "rewrite.md").write_text("# Demo v2\n\n- **R1** Better behavior.", encoding="utf-8")
        self.spec("promote", "0", "--from", "specs/.drafts/rewrite.md", succeeds=False)
        self.tracker("init", FEATURE)
        self.spec("promote", "0", "--from", "specs/.drafts/rewrite.md", "--parent-confirmed", succeeds=False)  # in progress: user decision
        result = self.spec("promote", "0", "--from", "specs/.drafts/rewrite.md", "--parent-confirmed", "--user-decision", "User: rewrite it")["result"]
        self.assertIn("spec-sync", result["next"])
        self.assertIn("Better behavior.\n", (self.root / "specs" / f"{FEATURE}.md").read_text(encoding="utf-8"))
        self.spec("validate")
        (drafts / "bad.md").write_text("---\nid: 0\n---\n", encoding="utf-8")
        self.spec("promote", "0", "--from", "specs/.drafts/bad.md", "--parent-confirmed", succeeds=False)


class BashGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
        (self.root / "specs").mkdir()
        (self.root / "implementation").mkdir()
        (self.root / "specs" / "0000-demo.md").write_text("# Spec\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_guard(self, event: dict) -> int:
        event = {"cwd": str(self.root), **event}
        return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), text=True, capture_output=True).returncode

    def bash(self, command: str, subagent: bool = True) -> int:
        event: dict = {"tool_name": "Bash", "tool_input": {"command": command}}
        if subagent:
            event["agent_id"] = "abc"
        return self.run_guard(event)

    def test_subagent_spec_cli_mutations_are_denied(self) -> None:
        for command in (
            "python3 /x/skills/spec-cli/scripts/spec.py new --title T --kind feature",
            "cd be && python3 /x/spec.py --json archive 3 --parent-confirmed",
            "spec restore 3 --reason r", "bin/spec unlock 3", "spec.py relock 3", "spec promote 3 --from x", "spec.py adopt --dry-run",
        ):
            self.assertEqual(self.bash(command), 2, command)
            self.assertEqual(self.bash(command, subagent=False), 0, command)
        for command in ("python3 /x/spec.py show 3 --effective", "spec.py --json ready", "spec validate", "go test ./... | grep spec"):
            self.assertEqual(self.bash(command), 0, command)

    def test_subagent_shell_writes_into_specs_are_denied_except_drafts(self) -> None:
        for command in ("echo x > specs/0001-a.md", "cat <<EOF > specs/0000-demo.md\nbody\nEOF", "sed -i s/a/b/ specs/0000-demo.md",
                        "cd specs && rm 0000-demo.md", "tee -a specs/x.md < y", "cp /tmp/a.md specs/", "rm -rf specs"):
            self.assertEqual(self.bash(command), 2, command)
        self.assertEqual(self.bash("FOO=1 rm specs/0000-demo.md"), 2)
        self.assertEqual(self.bash("dd if=/dev/zero of=specs/x.md"), 2)
        for command in ("mkdir -p specs/.drafts && echo x > specs/.drafts/a.md", "cat specs/0000-demo.md", "grep -r R1 specs > /tmp/out",
                        "echo x > be/out.txt", "cp -r specs /tmp/copy"):
            self.assertEqual(self.bash(command), 0, command)
        self.assertEqual(self.bash("echo x > specs/0001-a.md", subagent=False), 0)

    def test_shell_writes_into_state_are_denied_for_everyone(self) -> None:
        for subagent in (True, False):
            self.assertEqual(self.bash("echo {} > implementation/active/0000-demo.json", subagent), 2)
            self.assertEqual(self.bash("rm implementation/spec-archive.json", subagent), 2)
            self.assertEqual(self.bash("cat implementation/active/0000-demo.json", subagent), 0)
            self.assertEqual(self.bash("cp -r implementation/active /tmp/copy", subagent), 0)
            self.assertEqual(self.bash("cp /tmp/x.json implementation/active/0000-demo.json", subagent), 2)
            self.assertEqual(self.bash("echo {} > implementation/preflight.json", subagent), 0)

    def test_subagent_edits_allowed_only_in_drafts(self) -> None:
        def edit(relative: str) -> int:
            return self.run_guard({"tool_name": "Write", "tool_input": {"file_path": str(self.root / relative)}, "agent_id": "abc"})

        self.assertEqual(edit("specs/0000-demo.md"), 2)
        self.assertEqual(edit("specs/.drafts/proposal.md"), 0)
        self.assertEqual(self.run_guard({"tool_name": "Write", "tool_input": {"file_path": str(self.root / "specs/.drafts/p.md")}}), 0)


class SmokeTest(CliTestCase):
    """End to end in a fresh repo, using only the CLIs: dependency order, import, review, bugs, fix, retest, archive."""

    def setUp(self) -> None:
        super().setUp()
        (self.root / "specs" / f"{FEATURE}.md").unlink()
        drafts = self.root / "specs" / ".drafts"
        drafts.mkdir()
        bodies = {
            "core": "# Core\n\n## Requirements\n\n- **R1** [api] Create items.\n- **R2** List items\n  newest first.\n\n## Testability\n\nNot applicable: test fixture.\n",
            "ui": "# UI\n\n## Requirements\n\n- **R1** [ux] Show items. (amends 0:R2)\n\n## Testability\n\nNot applicable: test fixture.\n",
            "decision": "# Accept: no auth\n\n- **R1** Decision: single-user MVP.\n",
        }
        for name, body in bodies.items():
            (drafts / f"{name}.md").write_text(body, encoding="utf-8")
        self.spec("new", "--title", "Core", "--kind", "feature", "--from", "specs/.drafts/core.md")
        self.spec("new", "--title", "UI", "--kind", "feature", "--depends-on", "0", "--from", "specs/.drafts/ui.md")
        self.spec("new", "--title", "Accept no auth", "--kind", "decision", "--references", "0", "--from", "specs/.drafts/decision.md")

    def run_spec(self, feature: str, with_bug: bool) -> None:
        self.feature = feature
        self.tracker("init", feature)
        self.handoff("parent")
        self.tracker("requirement", "import", feature, "--include-amended", "--parent-confirmed")
        self.handoff("implementer")
        for item in self.tracker("requirement", "list", feature)["result"]:
            self.tracker("requirement", "implemented", feature, item["id"], "--evidence", "done")
        self.tracker("file", "add", feature, f"src/{feature}.py")
        self.check("unit")
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        for item in self.tracker("requirement", "list", feature)["result"]:
            self.tracker("requirement", "tested", feature, item["id"], "--evidence", "observed")
        self.check("api")
        if with_bug:
            self.report_bug()
            bug = f"BUG-{feature}-001"
            self.assertEqual(self.handoff("parent")["result"]["status"], "bugs_found")
            self.tracker("bug", "assign", feature, bug, "--fixer", "fixer")
            self.handoff("fixer")
            self.tracker("bug", "fixed", feature, bug, "--fix", "f", "--regression", "test")
            self.check("unit")
            self.handoff("reviewer")
            self.check("code-review")
            self.assertEqual(self.handoff("tester")["result"]["status"], "ready_for_retest")
            for item in self.tracker("requirement", "list", feature)["result"]:
                self.tracker("requirement", "tested", feature, item["id"], "--evidence", "retested")
            self.tracker("bug", "verify", feature, bug, "--retest", "passes")
            self.check("api")
        self.assertEqual(self.handoff("parent")["result"]["status"], "ready_for_acceptance")
        self.tracker("gate", feature, "acceptance")
        self.tracker("archive", feature, "--parent-confirmed")
        self.spec("archive", feature, "--parent-confirmed")

    def test_full_run(self) -> None:
        self.assertEqual([item["id"] for item in self.spec("ready")["result"]], [0])
        self.spec("archive", "2", "--parent-confirmed")
        self.spec("archive", "1", "--parent-confirmed", succeeds=False)
        self.run_spec("0000-core", with_bug=True)
        self.assertEqual(self.spec("next")["result"]["id"], 1)
        self.run_spec("0001-ui", with_bug=False)
        archived = json.loads((self.root / "implementation" / "archive" / "0001-ui.json").read_text(encoding="utf-8"))
        self.assertEqual([item["spec_ref"] for item in archived["requirements"]], ["1:R1", "0:R2"])
        self.assertEqual([item["status"] for item in self.spec("list")["result"]], ["accepted", "accepted", "accepted"])
        self.assertIsNone(self.spec("next")["result"])
        self.assertEqual(self.spec("validate")["result"], {"valid": True, "specification_count": 3})
        self.assertEqual(self.tracker("status")["result"], [])


@unittest.skipUnless((COMPAT / "specs").is_dir() and (COMPAT / "implementation").is_dir(), "no compatibility fixture")
class CompatibilityTest(unittest.TestCase):
    """Run read-only commands against a copy of a real project (SPEC_WORKFLOW_COMPAT_ROOT)."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(COMPAT / "specs", self.root / "specs")
        shutil.copytree(COMPAT / "implementation", self.root / "implementation")
        (self.root / "AGENTS.md").write_text("# Copy\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, script: str, *arguments: str) -> dict:
        process = subprocess.run([str(PLUGIN / "bin" / script), "--json", *arguments], cwd=self.root, text=True, capture_output=True)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["ok"], payload)
        return payload["result"]

    def test_existing_project_still_works(self) -> None:
        self.assertTrue(self.run_cli("spec", "validate")["valid"])
        self.run_cli("spec", "status")
        self.run_cli("spec", "ready")
        for record in self.run_cli("spec-tracker", "status"):
            self.run_cli("spec-tracker", "requirement", "list", record["feature"])
            self.run_cli("spec-tracker", "spec-check", record["feature"])
        self.run_cli("spec-tracker", "overlap")


if __name__ == "__main__":
    unittest.main()
