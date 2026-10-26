"""Tests for the workflow-retro script against synthetic transcripts and tracker records."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
RETRO = PLUGIN / "skills" / "workflow-retro" / "scripts" / "retro.py"
FAKE_TOKEN = "sk-abcdefghijklmnopqrstuvwx"
FAKE_PASSWORD = "hunter2xyz"
FAKE_EMAIL = "bob@example.com"
LARGE = "f" * 24_000
RESULT_TOKENS = (len("Exit code 1\n") + 24_000 + 3) // 4
SKILL_TEXT = "Base directory for this skill: /x/spec-workflow/0.2.0/skills/spec-tracker\n\n" + "y" * 400
HANDOFF_ERROR = 'Exit code 1\n{"ok":false,"error":{"code":"tracker_error","message":"implementer cannot hand off to tester: the first round must go through the reviewer"}}'


def usage(input_tokens: int, creation: int, read: int, output: int) -> dict:
    return {"input_tokens": input_tokens, "cache_creation_input_tokens": creation, "cache_read_input_tokens": read, "output_tokens": output}


class Transcript:
    def __init__(self) -> None:
        self.lines: list[dict] = []
        self.clock = 0

    def stamp(self) -> str:
        self.clock += 10
        return f"2026-10-22T16:{self.clock // 60:02d}:{self.clock % 60:02d}.000Z"

    def prompt(self, text: str) -> None:
        self.lines.append({"type": "user", "timestamp": self.stamp(), "message": {"role": "user", "content": text}})

    def assistant(self, message_id: str, blocks: list[dict], tokens: dict, stop: str = "tool_use") -> None:
        for block in blocks:  # one line per content block, like Claude Code
            self.lines.append({"type": "assistant", "timestamp": self.stamp(), "message": {
                "id": message_id, "role": "assistant", "content": [block], "usage": tokens, "stop_reason": stop}})

    def tool(self, call_id: str, name: str, data: dict) -> dict:
        return {"type": "tool_use", "id": call_id, "name": name, "input": data}

    def result(self, call_id: str, content: str, error: bool = False) -> None:
        self.lines.append({"type": "user", "timestamp": self.stamp(), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": content, "is_error": error}]}})

    def meta_text(self, source: str, text: str) -> None:
        self.lines.append({"type": "user", "isMeta": True, "sourceToolUseID": source, "timestamp": self.stamp(),
                           "message": {"role": "user", "content": [{"type": "text", "text": text}]}})

    def text(self, text: str) -> None:
        self.lines.append({"type": "user", "timestamp": self.stamp(), "message": {"role": "user", "content": [{"type": "text", "text": text}]}})

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in self.lines) + "not json\n", encoding="utf-8")


def notification(task_id: str, status: str, result: str) -> str:
    return f"<task-notification>\n<task-id>{task_id}</task-id>\n<status>{status}</status>\n<result>{result}</result>\n</task-notification>"


def build_fixture(root: Path) -> tuple[Path, Path]:
    project, transcripts = root / "project", root / "transcripts"
    (project / "specs").mkdir(parents=True)
    (project / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    (project / "specs" / "0001-demo.md").write_text("# Demo\n\n- **R1** One.\n- **R2** Two\n  continued.\n", encoding="utf-8")
    archive = project / "implementation" / "archive"
    archive.mkdir(parents=True)
    bugs = [
        {"id": "BUG-0001-demo-001", "found_by": "reviewer", "severity": "high", "status": "verified", "evidence": "e"},
        {"id": "BUG-0001-demo-002", "found_by": "tester", "severity": "medium", "status": "verified", "evidence": "e | Reopened: again"},
    ]
    record = {"feature": "0001-demo", "status": "accepted", "requirements": [{"id": "REQ-001"}, {"id": "REQ-002"}], "bugs": bugs,
              "checks": [{"name": "unit", "result": "passed"}, {"name": "it", "result": "waived"}], "blockers": [],
              "specification": {"history": []}, "handoff": {}}
    (archive / "0001-demo.json").write_text(json.dumps(record), encoding="utf-8")

    main = Transcript()
    main.prompt("implement all specs")
    main.assistant("m1", [main.tool("t1", "Agent", {"description": "Implement spec 0001", "prompt": "x"}), {"type": "text", "text": "ok"}], usage(10, 1000, 0, 50))
    main.result("t1", "Async agent launched")
    main.text(notification("a1", "completed", "r" * 16000))
    main.text(notification("a1", "completed", "done"))
    main.assistant("m2", [main.tool("t2", "Bash", {"command": "python3 /p/spec_tracker.py --json handoff 0001-demo --to tester"})], usage(5, 100, 1000, 20))
    main.result("t2", HANDOFF_ERROR, error=True)
    main.assistant("m3", [{"type": "text", "text": "done"}], usage(1, 10, 1100, 5), stop="end_turn")
    main.write(transcripts / "main-1.jsonl")

    agent = Transcript()
    agent.prompt(f"Role: implementer. Record feature: 0001-demo. Key {FAKE_TOKEN}. Port :8080.")
    agent.assistant("s1", [agent.tool("k1", "Skill", {"skill": "spec-workflow:spec-tracker"})], usage(2, 2000, 0, 10))
    agent.result("k1", "Launching skill")
    agent.meta_text("k1", SKILL_TEXT)
    agent.assistant("s2", [agent.tool("r1", "Read", {"file_path": "/p/be/a.go"})], usage(1, 100, 1000, 10))
    agent.result("r1", "z" * 400)
    agent.assistant("s3", [agent.tool("r2", "Read", {"file_path": "/p/be/a.go"})], usage(1, 100, 1000, 10))
    agent.result("r2", "z" * 400)
    command = f"cd be && PASSWORD={FAKE_PASSWORD} go test ./..."
    agent.assistant("s4", [agent.tool("b1", "Bash", {"command": command})], usage(1, 100, 1000, 10))
    agent.result("b1", "Exit code 1\n" + LARGE, error=True)
    agent.assistant("s5", [agent.tool("b2", "Bash", {"command": command})], usage(1, 100, 1000, 10))
    agent.result("b2", "ok")
    agent.lines.append({"type": "attachment", "attachment": {"type": "queued_command", "prompt": "more"}})
    agent.assistant("s6", [{"type": "text", "text": "report"}], usage(1, 100, 1000, 10), stop="end_turn")
    agent.write(transcripts / "main-1" / "subagents" / "agent-a1.jsonl")
    meta = {"agentType": "spec-workflow:spec-implementer", "description": f"Implement spec 0001 for {FAKE_EMAIL}"}
    (transcripts / "main-1" / "subagents" / "agent-a1.meta.json").write_text(json.dumps(meta), encoding="utf-8")

    other = Transcript()
    other.prompt("Audit the UI on :8080")
    other.assistant("o1", [{"type": "text", "text": "done"}], usage(1, 50, 0, 5), stop="end_turn")
    other.write(transcripts / "main-1" / "subagents" / "agent-b2.jsonl")
    (transcripts / "main-1" / "subagents" / "agent-b2.meta.json").write_text(json.dumps({"agentType": "general-purpose", "description": "Audit on :8080"}), encoding="utf-8")
    return project, transcripts


class RetroTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project, self.transcripts = build_fixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_retro(self, *arguments: str, env: dict | None = None) -> str:
        process = subprocess.run(
            [sys.executable, str(RETRO), "--project", str(self.project), "--transcripts", str(self.transcripts), *arguments],
            text=True, capture_output=True, check=True, env={**os.environ, **(env or {})},
        )
        return process.stdout

    def report(self, *arguments: str) -> dict:
        return json.loads(self.run_retro("--json", *arguments))

    def test_run_metrics_are_exact(self) -> None:
        report = self.report()
        runs = {run["id"]: run for run in report["runs"]}
        agent = runs["a1"]
        self.assertEqual((agent["role"], agent["spec"], agent["api_calls"], agent["tool_calls"]), ("implementer", 1, 6, 5))
        self.assertEqual(agent["tools"], {"Bash": 2, "Read": 2, "Skill": 1})
        self.assertEqual(agent["tokens"]["input"], 7)
        self.assertEqual(agent["tokens"]["cache_creation"], 2500)
        self.assertEqual(agent["tokens"]["cache_read"], 5000)
        self.assertEqual(agent["tokens"]["output"], 60)
        self.assertEqual(agent["tokens"]["processed"], 7567)
        self.assertEqual(agent["tokens"]["weighted"], int(7 + 2500 * 1.25 + 5000 * 0.1 + 60 * 5))
        self.assertEqual(agent["tokens"]["final_context"], 1111)
        self.assertEqual(agent["tokens"]["cache_read_ratio"], round(5000 / 7507, 4))
        self.assertEqual(agent["reads"]["duplicates"], 1)
        self.assertEqual(agent["reads"]["duplicate_tokens"], 100)
        self.assertEqual(agent["reads"]["rereads"], 1)
        self.assertEqual(agent["bash"], {"failures": 1, "exit_codes": {"1": 1}, "repeated_commands": 1, "retried_after_failure": 1,
                                         "failure_carry": int(RESULT_TOKENS * 1.25 + RESULT_TOKENS * 0.1 * 2)})
        self.assertEqual(agent["large_results"], [{"tool": "Bash", "category": "test", "tokens": RESULT_TOKENS, "position": 3,
                                                   "carry": int(RESULT_TOKENS * 1.25 + RESULT_TOKENS * 0.1 * 2)}])
        skill_tokens = (len(SKILL_TEXT) + 3) // 4
        self.assertEqual(agent["skills"]["loads"], {"spec-workflow:spec-tracker": skill_tokens})
        self.assertEqual(agent["skills"]["carry"], int(skill_tokens * 1.25 + skill_tokens * 0.1 * 5))
        self.assertEqual(agent["turns"]["batchable_turns"], 1)
        self.assertEqual(agent["turns"]["onboarding_calls"], 4)
        self.assertEqual((agent["resumed"], agent["early_stop"], agent["queued_messages"]), (True, False, 1))
        self.assertEqual(agent["notifications"], ["completed", "completed"])
        self.assertEqual(agent["plugin_versions"], ["0.2.0"])
        self.assertEqual(agent["wall_seconds"], 120)
        self.assertIsNone(runs["b2"]["spec"])

        main = runs["main-1"]
        self.assertEqual((main["kind"], main["role"], main["api_calls"]), ("main", "parent", 3))
        self.assertEqual(main["cli_errors"], {"role": 1})
        self.assertEqual(main["reports_received"], {"count": 2, "tokens": 4001, "max": 4000})

    def test_aggregates_effectiveness_and_findings(self) -> None:
        report = self.report()
        self.assertEqual(report["totals"]["subagents"]["runs"], 2)
        (spec,) = report["by_spec"]
        self.assertEqual((spec["spec"], spec["requirements"], spec["runs"], spec["runs_by_role"]), (1, 2, 1, {"implementer": 1}))
        self.assertEqual(spec["weighted_per_requirement"], spec["weighted_tokens"] // 2)
        effect = report["effectiveness"]
        self.assertEqual((effect["bugs"], effect["bugs_by_finder"], effect["reopens"], effect["waivers"]), (2, {"reviewer": 1, "tester": 1}, 1, 1))
        self.assertEqual(effect["bugs_by_severity"], {"high": 1, "medium": 1})
        keys = {item["key"] for item in report["findings"]}
        self.assertTrue({"turns.batching", "context.rereads", "bash.failures", "context.large-results", "skills.load", "parent.reports"} <= keys)
        rejections = next(item for item in report["findings"] if item["key"] == "cli.rejections")
        self.assertEqual((rejections["frequency"], rejections["section"]), (1, "Roles and handoffs"))
        self.assertEqual([item["rank"] for item in report["findings"]], list(range(1, len(report["findings"]) + 1)))
        savings = [item["estimated_savings"] for item in report["findings"]]
        self.assertEqual(savings, sorted(savings, reverse=True))
        for item in report["findings"]:
            self.assertTrue(item["skill_file"] and item["section"] and item["proposal"] and item["independence_risk"])

    def test_redaction_and_no_tool_output(self) -> None:
        for output in (self.run_retro("--json"), self.run_retro()):
            for secret in (FAKE_TOKEN, FAKE_PASSWORD, FAKE_EMAIL, "fffffffffffffff", "zzzzzzzzzzzzzzzz", "rrrrrrrrrrrrrrrr"):
                self.assertNotIn(secret, output)

    def test_deterministic_across_environments(self) -> None:
        first = self.run_retro("--json", env={"TZ": "UTC", "LANG": "C"})
        second = self.run_retro("--json", env={"TZ": "Asia/Tokyo", "LANG": "it_IT.UTF-8"})
        self.assertEqual(first, second)

    def test_window_session_filter_and_compare(self) -> None:
        self.assertEqual(self.report("--since", "2026-10-23")["inputs"]["run_count"], 0)
        self.assertEqual(self.report("--session", "nope")["inputs"]["run_count"], 0)
        out = Path(self.temporary.name) / "out"
        self.run_retro("--label", "0.1.0", "--out-dir", str(out))
        self.assertTrue((out / "retro.md").read_text(encoding="utf-8").startswith("# Workflow retro: 0.1.0"))
        report = self.report("--label", "0.2.0", "--compare", str(out / "retro.json"), "--large-tokens", "100000")
        comparison = report["comparison"]
        self.assertEqual(comparison["against"], "0.1.0")
        self.assertIn("context.large-results", comparison["resolved_findings"])
        row = next(item for item in comparison["metrics"] if item["metric"] == "subagents.weighted_tokens")
        self.assertEqual((row["before"], row["after"], row["change"]), (row["before"], row["before"], "+0.0%"))
        self.assertIn("## Comparison", self.run_retro("--compare", str(out / "retro.json")))


if __name__ == "__main__":
    unittest.main()
