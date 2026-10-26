"""0.6.0: rules enforced in code - lanes, dependency start guard, plugin cache, audited spec edits, briefs, conformance, size budget.

Motivated by the m33 run: 0026 started before 0025 was accepted, lane ownership was violated, the parent hot-patched the
plugin cache and edited draft specs without the user, and hand-written prompts carried uneven rules.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_improvements import M33
from test_retro import RETRO, Transcript, usage
from test_workflow import FEATURE, GUARD, PLUGIN, TRACKER, CliTestCase, spec_text

TRACKER_CMD = f"python3 {TRACKER}"


def payload(root: Path, tool: str, tool_input: dict, agent_id: str | None = None, agent_type: str | None = None) -> dict:
    """A PreToolUse hook input as Claude Code sends it (agent_id/agent_type only inside a subagent)."""
    event = {"session_id": "s-1", "transcript_path": "/tmp/t.jsonl", "cwd": str(root), "permission_mode": "default",
             "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "tool_use_id": "toolu_1"}
    if agent_id:
        event["agent_id"] = agent_id
    if agent_type:
        event["agent_type"] = agent_type
    return event


class GuardCase(CliTestCase):
    guard_env: dict = {}

    def run_guard(self, event: dict, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), text=True, capture_output=True,
                              env={**os.environ, **self.guard_env, **(env or {})}, check=False)

    def write(self, relative: str, agent: str | None = "agent-1", role: str | None = "implementer") -> subprocess.CompletedProcess:
        agent_type = f"spec-workflow:spec-{role}" if role else None
        return self.run_guard(payload(self.root, "Write", {"file_path": str(self.root / relative), "content": "x"}, agent, agent_type))

    def bash(self, command: str, agent: str | None = "agent-1", role: str | None = "implementer") -> subprocess.CompletedProcess:
        agent_type = f"spec-workflow:spec-{role}" if role else None
        return self.run_guard(payload(self.root, "Bash", {"command": command}, agent, agent_type))

    def record(self, number: int, slug: str, role: str, *assign: str) -> str:
        feature = f"{number:04d}-{slug}"
        if number:
            self.write_spec(f"{feature}.md", spec_text(number, slug))
        self.tracker("init", feature)
        self.tracker("assign", feature, "--role", role, *assign, "--parent-confirmed")
        return feature


class AdvisoryLaneTest(GuardCase):
    def test_lane_violations_warn_but_allow_by_default(self) -> None:
        self.record(0, "demo", "implementer", "--paths", "be/internal/chat/**")
        result = self.write("be/internal/agents/store.go")
        self.assertEqual(result.returncode, 0)
        self.assertIn("advisory", json.loads(result.stdout)["systemMessage"])


class LaneTest(GuardCase):
    guard_env = {"SPEC_WORKFLOW_STRICT_LANES": "1"}

    def test_unique_role_binds_automatically_and_paths_are_enforced(self) -> None:
        self.assertEqual(self.write("be/anything.go").returncode, 0)  # no assignments: legacy behavior
        self.record(0, "demo", "implementer", "--paths", "be/internal/chat/**", "be/cmd/chat")
        self.record(1, "ui", "tester", "--read-only")
        self.assertEqual(self.write("be/internal/chat/store.go").returncode, 0)
        self.assertTrue((self.root / "implementation" / ".assignments" / "agent-1").is_file())
        self.assertEqual(self.write("be/cmd/chat/main.go").returncode, 0)
        denied = self.write("be/internal/agents/store.go")
        self.assertEqual(denied.returncode, 2)
        self.assertIn("outside your assignment ASSIGN-0000-demo-001", denied.stderr)
        self.assertIn("spec-tracker assign 0000-demo", denied.stderr)
        self.assertEqual(self.bash("cd be && echo x > internal/agents/a.go").returncode, 2)
        self.assertEqual(self.bash("echo x > /tmp/scratch-out.txt").returncode, 0)  # outside the project
        self.assertEqual(self.write("specs/.drafts/proposal.md").returncode, 0)
        # The tester's lane is read-only.
        self.assertEqual(self.write("fe/app.tsx", agent="agent-2", role="tester").returncode, 2)
        self.assertEqual(self.bash("go test ./... > /tmp/out.log", agent="agent-2", role="tester").returncode, 0)
        # The main session is not lane-restricted.
        self.assertEqual(self.write("be/internal/agents/store.go", agent=None, role=None).returncode, 0)

    def test_claim_binds_ambiguous_agents_and_unknown_fails_open_with_warning(self) -> None:
        self.record(0, "demo", "implementer", "--paths", "be/**")
        self.record(1, "ui", "implementer", "--paths", "fe/**")
        unknown = self.write("be/a.go", agent="agent-a")
        self.assertEqual(unknown.returncode, 0)
        self.assertIn("lane ownership not enforced", json.loads(unknown.stdout)["systemMessage"])
        self.assertEqual(self.bash(f"{TRACKER_CMD} claim ASSIGN-0001-ui-001", agent="agent-a").returncode, 0)
        self.tracker("claim", "ASSIGN-0001-ui-001")
        self.assertEqual(self.write("fe/app.tsx", agent="agent-a").returncode, 0)
        owned = self.write("be/a.go", agent="agent-a")
        self.assertEqual(owned.returncode, 2)
        self.assertIn("ASSIGN-0001-ui-001", owned.stderr)
        self.assertEqual(self.bash(f"{TRACKER_CMD} claim ASSIGN-0001-ui-001", agent="agent-b").returncode, 2)  # already claimed
        self.assertEqual(self.bash(f"{TRACKER_CMD} claim ASSIGN-9999-x-001", agent="agent-b").returncode, 2)
        self.assertEqual(self.write("implementation/.assignments/agent-b", agent="agent-b").returncode, 2)  # markers are state

    def test_assign_validation_overlap_and_release(self) -> None:
        self.record(0, "demo", "implementer", "--paths", "be/internal/**")
        self.write_spec("0001-ui.md", spec_text(1, "ui"))
        self.tracker("init", "0001-ui")
        for paths in (["be/internal/chat"], ["be/**"], ["../x"], ["specs/**"], ["/abs"]):
            self.tracker("assign", "0001-ui", "--role", "implementer", "--paths", *paths, "--parent-confirmed", succeeds=False)
        self.tracker("assign", "0001-ui", "--role", "implementer", "--paths", "fe/**", succeeds=False)  # parent only
        result = self.tracker("assign", "0001-ui", "--role", "implementer", "--paths", "fe/**", "be/cmd/ui", "--parent-confirmed")["result"]
        self.assertEqual(result["assignment"], "ASSIGN-0001-ui-001")
        again = self.tracker("assign", "0001-ui", "--role", "reviewer", "--read-only", "--parent-confirmed")["result"]
        self.assertEqual(again["assignment"], "ASSIGN-0001-ui-002")
        self.tracker("assign", "0000-demo", "--release", "--parent-confirmed")
        self.tracker("assign", "0001-ui", "--role", "implementer", "--paths", "be/**", "--parent-confirmed")  # no lane left to clash with


class CacheAndSpecGuardTest(GuardCase):
    def test_plugin_cache_is_never_edited(self) -> None:
        cache = self.root / "cache"
        (cache / "ldgstack" / "spec-workflow" / "0.5.0").mkdir(parents=True)
        env = {"SPEC_WORKFLOW_PLUGIN_CACHE": str(cache)}
        target = cache / "ldgstack" / "spec-workflow" / "0.5.0" / "hooks" / "guard_paths.py"
        for agent in (None, "agent-1"):
            edit = self.run_guard(payload(self.root, "Edit", {"file_path": str(target)}, agent, None), env)
            self.assertEqual(edit.returncode, 2)
            self.assertIn("claude plugin update", edit.stderr)
            self.assertEqual(self.run_guard(payload(self.root, "Bash", {"command": f"sed -i s/a/b/ {target}"}, agent), env).returncode, 2)
            self.assertEqual(self.run_guard(payload(self.root, "Bash", {"command": f"cat {target}"}, agent), env).returncode, 0)

    def test_existing_spec_files_are_edited_only_through_spec_edit(self) -> None:
        denied = self.write(f"specs/{FEATURE}.md", agent=None, role=None)
        self.assertEqual(denied.returncode, 2)
        self.assertIn("spec.py edit 0000", denied.stderr)
        self.assertEqual(self.bash(f"echo x >> specs/{FEATURE}.md", agent=None, role=None).returncode, 2)
        self.assertEqual(self.bash("python3 /x/spec.py edit 0 --from specs/.drafts/a.md --reason r --parent-confirmed").returncode, 2)
        self.assertEqual(self.bash("python3 /x/spec.py edit 0 --from specs/.drafts/a.md --reason r", agent=None, role=None).returncode, 0)


class SpecEditTest(CliTestCase):
    def draft(self, body: str = "# Demo v2\n\n- **R1** Better behavior.\n- **R2** New behavior.\n") -> str:
        drafts = self.root / "specs" / ".drafts"
        drafts.mkdir(exist_ok=True)
        (drafts / "edit.md").write_text(body, encoding="utf-8")
        return "specs/.drafts/edit.md"

    def test_draft_edit_is_logged(self) -> None:
        self.spec("edit", "0", "--from", self.draft(), "--reason", "clarify", succeeds=False)  # parent only
        result = self.spec("edit", "0", "--from", self.draft(), "--reason", "clarify R1", "--parent-confirmed")["result"]
        self.assertTrue(result["logged"])
        self.assertNotIn("next", result)
        self.assertIn("New behavior.", (self.root / "specs" / f"{FEATURE}.md").read_text(encoding="utf-8"))
        self.spec("edit", "0", "--from", self.draft(), "--reason", "pick 4:R7", "--conflict", "4:R7,0:R1", "--parent-confirmed", succeeds=False)
        self.spec("edit", "0", "--from", self.draft(), "--reason", "pick 4:R7", "--conflict", "4:R7,0:R1",
                  "--user-decision", "User: 4:R7 wins", "--parent-confirmed")
        history = self.spec("log", "0")["result"]["history"]
        self.assertEqual([(item["action"], item["reason"]) for item in history], [("edit", "clarify R1"), ("edit", "pick 4:R7")])
        self.assertEqual(history[1]["user_decision"], "User: 4:R7 wins")
        self.assertIn("history:", self.text("log", "0"))
        (self.root / "notes.md").write_text("---\nid: 1\n---\n", encoding="utf-8")
        self.spec("edit", "0", "--from", "notes.md", "--reason", "r", "--parent-confirmed", succeeds=False)
        self.spec("validate")

    def test_in_progress_edit_needs_user_and_marks_record(self) -> None:
        self.start()
        self.spec("edit", "0", "--from", self.draft(), "--reason", "add R2", "--parent-confirmed", succeeds=False)
        result = self.spec("edit", "0", "--from", self.draft(), "--reason", "add R2", "--user-decision", "User: add R2", "--parent-confirmed")["result"]
        self.assertIn("spec-sync", result["next"])
        pending = self.tracker("status", self.feature)["result"]["pending"]
        self.assertTrue(pending and "spec-sync" in pending[0])
        self.assertIn("spec-sync", self.tracker("gate", self.feature, "ready-test", succeeds=False)["error"]["message"])
        self.handoff("parent")
        self.tracker("spec-sync", self.feature, "--reason", "add R2", "--parent-confirmed")
        pending = self.tracker("status", self.feature)["result"]["pending"]
        self.assertEqual(len(pending), 1)
        self.assertIn("requirement import", pending[0])
        self.assertIn("requirement import", self.tracker("gate", self.feature, "ready-test", succeeds=False)["error"]["message"])
        self.tracker("requirement", "import", self.feature)
        self.assertEqual(self.tracker("status", self.feature)["result"]["pending"], [])

    def test_accepted_spec_is_refused(self) -> None:
        self.implement()
        self.accept()
        self.spec("archive", "0", "--parent-confirmed")
        error = self.spec("edit", "0", "--from", self.draft(), "--reason", "r", "--user-decision", "u", "--parent-confirmed", succeeds=False)
        self.assertIn("--amends 0", error["error"]["message"])


class DependencyGuardTest(CliTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_spec("0001-next.md", spec_text(1, "next", depends_on=[0]))
        self.feature = "0001-next"

    def test_init_and_implementer_handoff_wait_for_dependencies(self) -> None:
        error = self.tracker("init", self.feature, succeeds=False)["error"]["message"]
        self.assertIn("0000-demo.md", error)
        self.assertIn("--user-decision", error)
        self.tracker("init", self.feature, "--parent-confirmed", succeeds=False)
        self.tracker("init", self.feature, "--parent-confirmed", "--user-decision", "User: start 0001 now")
        self.handoff("parent")
        self.tracker("requirement", "import", self.feature)
        self.handoff("implementer")  # the recorded override covers the same pending specs
        path = self.root / "implementation" / "active" / f"{self.feature}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["dependency_overrides"][0]["pending"], ["0000-demo.md"])
        record["dependency_overrides"] = []
        record["current_role"] = "parent"
        path.write_text(json.dumps(record), encoding="utf-8")
        self.handoff("implementer", succeeds=False)
        self.tracker("handoff", self.feature, "--to", "implementer", "--completed", "c", "--remaining", "r",
                     "--parent-confirmed", "--user-decision", "User: go ahead")

    def test_accepted_dependency_unblocks(self) -> None:
        self.feature = FEATURE
        self.implement()
        self.accept()
        self.spec("archive", "0", "--parent-confirmed")
        self.feature = "0001-next"
        self.tracker("init", self.feature)


class BriefTest(CliTestCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / "implementation").mkdir()
        (self.root / "implementation" / "preflight.json").write_text(json.dumps({"commands": ["cd be && go version"]}), encoding="utf-8")

    def test_brief_is_generated_from_state(self) -> None:
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", self.feature, "--spec-ref", "0:R1", "--verification", "API call")
        self.tracker("requirement", "add", self.feature, "--spec-ref", "0:R2", "--verification", "UI")
        self.tracker("brief", self.feature, "--role", "implementer", succeeds=False)  # still with the parent
        self.handoff("implementer")
        error = self.tracker("brief", self.feature, "--role", "implementer", succeeds=False)["error"]["message"]
        self.assertIn(f"assign {FEATURE} --role implementer", error)
        self.tracker("assign", self.feature, "--role", "implementer", "--paths", "be/**", "--parent-confirmed")
        prompt = self.tracker("brief", self.feature, "--role", "implementer")["result"]
        for expected in ("[Generated by spec-tracker brief", f"Spec: specs/{FEATURE}.md", "Role: implementer", "not yet implemented: REQ-001, REQ-002",
                         "  - cd be && go version", f"claim ASSIGN-{FEATURE}-001", "Ownership: edit only be/**",
                         f"handoff {FEATURE} --to reviewer", "Toolkit (stale tools marked):\n  none registered", "Efficiency:"):
            self.assertIn(expected, prompt)
        self.assertNotIn("{", prompt.split("Next command:")[0])  # every placeholder filled
        batch = self.tracker("brief", self.feature, "--role", "implementer", "--batch", "REQ-001..REQ-001")["result"]
        self.assertIn("final batch: no): REQ-001", batch)
        self.assertIn("end without a handoff", batch)
        self.tracker("brief", self.feature, "--role", "implementer", "--batch", "REQ-002..REQ-001", succeeds=False)
        text = subprocess.run([sys.executable, str(TRACKER), "brief", self.feature, "--role", "implementer"], cwd=self.root,
                              text=True, capture_output=True, check=True).stdout
        self.assertEqual(text, prompt)

    def test_fixer_and_tester_scopes(self) -> None:
        self.implement()
        self.report_bug()
        self.handoff("parent")
        self.tracker("bug", "assign", self.feature, "BUG-001", "--fixer", "fixer")
        self.handoff("fixer")
        self.tracker("assign", self.feature, "--role", "fixer", "--paths", "be/**", "--parent-confirmed")
        self.assertIn(f"assigned bugs: BUG-{FEATURE}-001 (high) Broken", self.tracker("brief", self.feature, "--role", "fixer")["result"])
        self.tracker("bug", "fixed", self.feature, "BUG-001", "--fix", "f", "--regression", "t")
        self.check("unit")
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        self.tracker("assign", self.feature, "--role", "tester", "--read-only", "--parent-confirmed")
        prompt = self.tracker("brief", self.feature, "--role", "tester")["result"]
        self.assertIn(f"retest BUG-{FEATURE}-001", prompt)
        self.assertIn("Ownership: read-only", prompt)
        self.assertIn(f"handoff {FEATURE} --to parent", prompt)


class ConformanceTest(unittest.TestCase):
    def test_fixture_violations_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project, transcripts = root / "project", root / "transcripts"
            (project / "specs").mkdir(parents=True)
            (project / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
            (project / "specs" / "0000-core.md").write_text(spec_text(0, "core"), encoding="utf-8")
            (project / "specs" / "0001-ui.md").write_text(spec_text(1, "ui", depends_on=[0]), encoding="utf-8")
            implementation = project / "implementation"
            (implementation / "archive").mkdir(parents=True)
            (implementation / "active").mkdir()
            (implementation / ".assignments").mkdir()
            (implementation / ".assignments" / "a1").write_text("ASSIGN-0001-ui-001\n", encoding="utf-8")
            manifest = {"schema_version": 1, "archived": {"0000-core.md": {"archived_at": "2026-10-23T12:00:00Z"}},
                        "history": [{"action": "archive", "specification": "0000-core.md", "at": "2026-10-23T12:00:00Z"},
                                    {"action": "edit", "specification": "0001-ui.md", "at": "2026-10-23T13:00:00Z", "reason": "r", "status_at_edit": "in_progress"}]}
            (implementation / "spec-archive.json").write_text(json.dumps(manifest), encoding="utf-8")
            record = {"feature": "0001-ui", "created_at": "2026-10-23T10:00:00Z", "specification": {"path": "specs/0001-ui.md"},
                      "checks": [{"name": "e2e", "result": "waived"}], "bugs": [], "tool_gaps": [],
                      "assignments": [{"id": "ASSIGN-0001-ui-001", "role": "implementer", "paths": ["fe/**"], "status": "active"}]}
            (implementation / "active" / "0001-ui.json").write_text(json.dumps(record), encoding="utf-8")

            def agent(agent_id: str, agent_type: str, prompt: str, calls: list[tuple[str, dict]]) -> None:
                run = Transcript()
                run.prompt(prompt)
                for index, (tool, data) in enumerate(calls):
                    run.assistant(f"{agent_id}-{index}", [run.tool(f"{agent_id}t{index}", tool, data)], usage(1, 10, 10, 1))
                    run.result(f"{agent_id}t{index}", "ok")
                run.assistant(f"{agent_id}-end", [{"type": "text", "text": "done"}], usage(1, 1, 1, 1), stop="end_turn")
                run.write(transcripts / "main-1" / "subagents" / f"agent-{agent_id}.jsonl")
                (transcripts / "main-1" / "subagents" / f"agent-{agent_id}.meta.json").write_text(
                    json.dumps({"agentType": agent_type, "description": "Run spec 0001"}), encoding="utf-8")

            agent("a1", "spec-workflow:spec-implementer", "[Generated by spec-tracker brief; send verbatim]\nRecord feature: 0001-ui",
                  [("Write", {"file_path": str(project / "fe" / "app.tsx"), "content": "x"}),
                   ("Write", {"file_path": str(project / "be" / "main.go"), "content": "x"}),
                   ("Bash", {"command": "cat > /tmp/sp/mock.py <<'EOF'\nx\nEOF"})])
            agent("a2", "spec-workflow:spec-tester", "Role: tester. Record feature: 0001-ui",
                  [("Edit", {"file_path": str(project / "fe" / "x.tsx")}),
                   ("Bash", {"command": "python3 /p/spec_tracker.py check add 0001-ui --name a"}),
                   ("Bash", {"command": "python3 /p/spec_tracker.py check add 0000-core --name a"}),
                   ("Bash", {"command": "cat > /tmp/sp/mock.py <<'EOF'\ny\nEOF"})])
            main = Transcript()
            main.prompt("implement all specs")
            main.assistant("m1", [main.tool("e1", "Edit", {"file_path": str(project / "specs" / "0001-ui.md")})], usage(1, 1, 1, 1))
            main.result("e1", "ok")
            main.assistant("m2", [{"type": "text", "text": "done"}], usage(1, 1, 1, 1), stop="end_turn")
            main.write(transcripts / "main-1.jsonl")

            process = subprocess.run([sys.executable, str(RETRO), "--project", str(project), "--transcripts", str(transcripts),
                                      "--conformance", "--json"], text=True, capture_output=True, check=True)
            checks = {item["key"]: item for item in json.loads(process.stdout)["conformance"]}
            self.assertEqual({key: item["violations"] for key, item in checks.items()}, {
                "deps.early-start": 1, "lanes.outside": 2, "verifiers.non-fresh": 1, "decisions.no-user": 3,
                "tools.reused-throwaway": 1, "prompts.not-brief": 1,
            })
            self.assertIn("outside ASSIGN-0001-ui-001", " ".join(checks["lanes.outside"]["evidence"]))
            markdown = subprocess.run([sys.executable, str(RETRO), "--project", str(project), "--transcripts", str(transcripts), "--conformance"],
                                      text=True, capture_output=True, check=True).stdout
            self.assertIn("## Conformance", markdown)


class SizeBudgetTest(unittest.TestCase):
    """Skills stay short; detail lives in references/ and in CLI error messages."""

    def test_skill_and_agent_lengths(self) -> None:
        for path in sorted((PLUGIN / "skills").glob("*/SKILL.md")):
            self.assertLess(len(path.read_text(encoding="utf-8").splitlines()), 120, path)
        for path in sorted((PLUGIN / "agents").glob("*.md")):
            self.assertLess(len(path.read_text(encoding="utf-8").splitlines()), 60, path)

    def test_template_placeholders_are_known(self) -> None:
        sys.path.insert(0, str(TRACKER.parent))
        from tracker import brief

        self.assertIn("{claim_command}", brief.template())


@unittest.skipUnless((M33 / "specs").is_dir() and (M33 / "implementation").is_dir(), "no compatibility fixture")
class EnforcementCompatibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(M33 / "specs", self.root / "specs")
        shutil.copytree(M33 / "implementation", self.root / "implementation")
        (self.root / "AGENTS.md").write_text("# Copy\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, script: str, *arguments: str, succeeds: bool = True) -> dict:
        process = subprocess.run([str(PLUGIN / "bin" / script), "--json", *arguments], cwd=self.root, text=True, capture_output=True)
        result = json.loads(process.stdout)
        self.assertEqual(result["ok"], succeeds, result)
        return result

    def test_m33_records_and_the_0026_early_start(self) -> None:
        self.assertTrue(self.run_cli("spec", "validate")["result"]["valid"])
        for record in self.run_cli("spec-tracker", "status")["result"]:
            self.assertIn("pending", record)
        self.assertIn("history", self.run_cli("spec", "log", "26")["result"])
        feature = "0026-modern-chat-layout"
        if not (self.root / "implementation" / "active" / f"{feature}.json").is_file():
            self.skipTest("0026 is archived in this copy")
        status = self.run_cli("spec-tracker", "status", feature)["result"]
        if status["current_role"] != "parent":
            self.skipTest("0026 is no longer with the parent in this copy")
        # m33 implemented 0026 before 0025 was accepted; the guard now refuses that without the user.
        error = self.run_cli("spec-tracker", "handoff", feature, "--to", "implementer", "--completed", "c", "--remaining", "r", succeeds=False)
        self.assertIn("0025-agent-overview-and-edit-separation.md", error["error"]["message"])
        self.run_cli("spec-tracker", "handoff", feature, "--to", "implementer", "--completed", "c", "--remaining", "r",
                     "--parent-confirmed", "--user-decision", "User: start 0026 early")
        self.run_cli("spec-tracker", "assign", feature, "--role", "implementer", "--paths", "fe/src/**", "--parent-confirmed")
        prompt = self.run_cli("spec-tracker", "brief", feature, "--role", "implementer")["result"]
        self.assertIn("started before 0025-agent-overview-and-edit-separation.md: User: start 0026 early", prompt)
        self.assertIn("direnv exec . go version", prompt)


if __name__ == "__main__":
    unittest.main()
