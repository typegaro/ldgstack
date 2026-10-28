"""End-to-end tests for the tracker CLI, spec CLI, and path guard hook."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
TRACKER = PLUGIN / "skills" / "spec-tracker" / "scripts" / "spec_tracker.py"
SPEC = PLUGIN / "skills" / "spec-cli" / "scripts" / "spec.py"
GUARD = PLUGIN / "hooks" / "guard_paths.py"
FEATURE = "0000-demo"
sys.path.insert(0, str(SPEC.parent))

from speclib import frontmatter  # noqa: E402


DEMO_BODY = "# Demo\n\n- **R1** Required behavior.\n"


def spec_text(number: int, slug: str, kind: str = "feature", body: str = DEMO_BODY, **relations: list[int]) -> str:
    meta = {"id": number, "slug": slug, "title": slug.replace("-", " ").capitalize(), "kind": kind, "created": "2026-10-22"}
    meta.update({key: relations.get(key, []) for key in frontmatter.RELATIONS})
    return frontmatter.serialize(meta) + "\n" + body


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CliTestCase(unittest.TestCase):
    feature = FEATURE

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "CLAUDE.md").write_text("# Test\n", encoding="utf-8")
        (self.root / "specs").mkdir()
        self.write_spec(f"{FEATURE}.md", spec_text(0, "demo"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_spec(self, name: str, content: str) -> Path:
        path = self.root / "specs" / name
        path.write_text(content, encoding="utf-8")
        return path

    def cli(self, script: Path, *arguments: str, succeeds: bool = True) -> dict:
        process = subprocess.run(
            [sys.executable, str(script), "--json", *arguments],
            cwd=self.root, text=True, capture_output=True, check=False,
        )
        if not process.stdout and process.returncode == 2:
            # argparse usage error: a required argument is missing.
            self.assertFalse(succeeds, process.stderr)
            return {"ok": False, "error": {"message": process.stderr}}
        payload = json.loads(process.stdout)
        self.assertEqual(payload["ok"], succeeds, payload)
        return payload

    def text(self, *arguments: str) -> str:
        process = subprocess.run([sys.executable, str(SPEC), *arguments], cwd=self.root, text=True, capture_output=True, check=True)
        return process.stdout

    def tracker(self, *arguments: str, succeeds: bool = True) -> dict:
        return self.cli(TRACKER, *arguments, succeeds=succeeds)

    def spec(self, *arguments: str, succeeds: bool = True) -> dict:
        return self.cli(SPEC, *arguments, succeeds=succeeds)

    def handoff(self, target: str, succeeds: bool = True) -> dict:
        return self.tracker("handoff", self.feature, "--to", target, "--completed", "work", "--remaining", "next", succeeds=succeeds)

    def check(self, name: str, result: str = "passed") -> None:
        self.tracker("check", "add", self.feature, "--name", name, "--method", "make test", "--result", result, "--evidence", "output")

    def start(self) -> None:
        self.tracker("init", f"specs/{self.feature}.md")
        self.handoff("parent")
        self.tracker("requirement", "add", self.feature, "--spec-ref", "Required behavior", "--verification", "API call")
        self.handoff("implementer")
        self.tracker("requirement", "implemented", self.feature, "REQ-001", "--evidence", "done", "--location", "be/demo")
        self.check("unit")

    def implement(self) -> None:
        self.start()
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")

    def report_bug(self) -> None:
        self.tracker(
            "bug", "add", self.feature, "--title", "Broken", "--severity", "high", "--spec-ref", "Required behavior",
            "--environment", "local", "--reproduction", "run", "--expected", "works", "--actual", "fails", "--evidence", "trace",
        )

    def accept(self) -> None:
        self.tracker("requirement", "tested", self.feature, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.handoff("parent")
        self.tracker("archive", self.feature, "--parent-confirmed")


class TrackerTest(CliTestCase):
    def test_concurrent_mutations_are_serialized(self) -> None:
        self.start()

        def add(index: int) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(TRACKER), "--json", "file", "add", FEATURE, f"src/file-{index}.go"],
                cwd=self.root, text=True, capture_output=True, check=False,
            )

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(add, range(30)))
        self.assertTrue(all(item.returncode == 0 for item in results), [item.stderr for item in results if item.returncode])
        record = json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))
        self.assertEqual(len([path for path in record["changed_files"] if path.startswith("src/file-")]), 30)

    def test_full_lifecycle_with_bug_archive_unlock_and_restore(self) -> None:
        bug = f"BUG-{FEATURE}-001"
        self.implement()
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.report_bug()
        self.assertEqual(self.handoff("parent")["result"]["status"], "bugs_found")
        self.tracker("bug", "assign", FEATURE, bug, "--fixer", "fixer-1")
        self.handoff("fixer")
        self.tracker("bug", "verify", FEATURE, bug, "--retest", "self-verify", succeeds=False)
        self.tracker("bug", "close", FEATURE, bug, "--reason", "x", "--parent-confirmed", succeeds=False)
        self.tracker("bug", "fixed", FEATURE, bug, "--fix", "patched", "--regression", "test added")
        self.check("unit")
        self.handoff("reviewer")
        self.check("code-review")
        self.assertEqual(self.handoff("tester")["result"]["status"], "ready_for_retest")
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "retested after fix")
        self.tracker("bug", "verify", FEATURE, bug, "--retest", "passes")
        self.check("independent")
        self.assertEqual(self.handoff("parent")["result"]["status"], "ready_for_acceptance")
        self.tracker("archive", FEATURE, "--parent-confirmed")
        self.spec("archive", "0", "--parent-confirmed")
        self.assertTrue(self.spec("validate")["result"]["valid"])
        self.assertIsNone(self.spec("next")["result"])

        self.spec("unlock", "0", "--reason", "typo", "--user-decision", "user approved", "--parent-confirmed")
        path = self.root / "specs" / f"{FEATURE}.md"
        path.write_text(path.read_text(encoding="utf-8") + "Typo fixed.\n", encoding="utf-8")
        self.spec("validate")
        self.spec("restore", "0", "--reason", "x", "--parent-confirmed", succeeds=False)
        self.spec("relock", "0", "--parent-confirmed")
        self.spec("validate")

        self.spec("restore", FEATURE, "--reason", "regression", "--parent-confirmed")
        restored = self.tracker("status", FEATURE)["result"]
        self.assertEqual(restored["current_role"], "parent")
        self.assertEqual(restored["generation"], 3)
        self.assertEqual(restored["requirements"]["implemented"], 0)
        self.tracker("gate", FEATURE, "acceptance", succeeds=False)
        self.tracker("spec-check", FEATURE)
        self.assertEqual(self.spec("next")["result"]["feature"], FEATURE)

    def test_not_run_check_blocks_only_acceptance_until_parent_waives(self) -> None:
        self.start()
        self.check("integration", "not_run")
        self.assertEqual(self.tracker("status", FEATURE)["result"]["checks_not_run"], ["integration"])
        self.handoff("reviewer")
        self.check("code-review")
        self.handoff("tester")
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "observed")
        self.check("independent")
        self.assertEqual(self.handoff("parent")["result"]["status"], "awaiting_parent")
        message = self.tracker("gate", FEATURE, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn("checks not run: integration", message)
        self.tracker("archive", FEATURE, "--parent-confirmed", succeeds=False)

        waive = ("check", "waive", FEATURE, "integration", "--reason", "n/a", "--user-decision", "user said skip")
        self.tracker(*waive, succeeds=False)
        self.tracker("check", "waive", FEATURE, "integration", "--reason", "n/a", "--parent-confirmed", succeeds=False)
        self.tracker("check", "waive", FEATURE, "unit", "--reason", "n/a", "--user-decision", "y", "--parent-confirmed", succeeds=False)
        self.tracker(*waive, "--parent-confirmed")
        self.tracker("gate", FEATURE, "acceptance")

    def test_acceptance_requires_reviewer_and_tester_checks(self) -> None:
        self.implement()
        self.tracker("requirement", "tested", FEATURE, "REQ-001", "--evidence", "read the code")
        message = self.tracker("gate", FEATURE, "acceptance", succeeds=False)["error"]["message"]
        self.assertIn("independent tester", message)
        self.assertNotIn("reviewer", message)
        self.check("independent")
        self.tracker("gate", FEATURE, "acceptance")

    def test_handoff_transitions_are_enforced(self) -> None:
        self.start()
        self.handoff("tester", succeeds=False)
        self.handoff("reviewer")
        self.handoff("implementer", succeeds=False)
        self.check("code-review")
        self.handoff("tester")
        self.handoff("fixer", succeeds=False)
        self.handoff("parent")
        self.handoff("fixer", succeeds=False)

    def test_only_parent_defines_requirements_and_list_hides_evidence(self) -> None:
        started = self.tracker("init", FEATURE)["result"]
        self.assertEqual((started["status"], started["current_role"]), ("new", "parent"))
        self.handoff("implementer")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "x", "--verification", "y", succeeds=False)
        self.handoff("parent")
        self.tracker("requirement", "add", FEATURE, "--spec-ref", "x", "--verification", "y")
        self.handoff("implementer")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "secret detail")
        listed = self.tracker("requirement", "list", FEATURE)["result"]
        self.assertEqual(listed[0]["id"], "REQ-001")
        self.assertNotIn("secret detail", json.dumps(listed))

    def test_reviewer_findings_go_to_parent(self) -> None:
        self.start()
        self.handoff("reviewer")
        self.report_bug()
        self.handoff("tester", succeeds=False)
        self.assertEqual(self.handoff("parent")["result"]["status"], "bugs_found")

    def test_blocker_history_and_spec_sync(self) -> None:
        self.tracker("init", FEATURE)
        self.handoff("implementer")
        self.tracker("blocker", "add", FEATURE, "--summary", "contradiction", "--report", "details")
        self.handoff("parent")
        self.assertEqual(self.tracker("status", FEATURE)["result"]["status"], "blocked")
        # Short form of the fully qualified BLOCKER-<feature>-001 is accepted.
        self.tracker("blocker", "resolve", FEATURE, "BLOCKER-001", "--resolution", "user decided", "--parent-confirmed")
        self.write_spec(f"{FEATURE}.md", spec_text(0, "demo", body="# Demo\n\nClarified behavior.\n"))
        self.tracker("spec-check", FEATURE, succeeds=False)
        self.tracker("spec-sync", FEATURE, "--reason", "user clarification", "--parent-confirmed")
        self.tracker("spec-check", FEATURE)
        record = json.loads((self.root / "implementation" / "active" / f"{FEATURE}.json").read_text(encoding="utf-8"))
        self.assertEqual((record["blockers"][0]["id"], record["blockers"][0]["status"]), (f"BLOCKER-{FEATURE}-001", "resolved"))
        self.assertEqual(len(record["specification"]["history"]), 1)


class SpecCliTest(CliTestCase):
    def history_fixture(self) -> None:
        """0 demo <- 1 amends 0 <- 2 supersedes 1; 3 references 0."""
        self.spec("new", "--title", "Paging", "--kind", "change", "--amends", "0")
        self.spec("new", "--title", "Paging v2", "--kind", "change", "--supersedes", "1", "--depends-on", "0")
        self.spec("new", "--title", "Unrelated", "--kind", "feature", "--references", "0")

    def test_new_numbering_and_frontmatter_round_trip(self) -> None:
        created = self.spec("new", "--title", "Chat pagination fix", "--kind", "change", "--amends", "0", "--references", "0")["result"]
        self.assertEqual(created["path"], "specs/0001-chat-pagination-fix.md")
        text = (self.root / created["path"]).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nid: 1\nslug: chat-pagination-fix\ntitle: Chat pagination fix\nkind: change\n"))
        self.assertIn("amends: [0]\nsupersedes: []\nreferences: [0]\n---\n\n# Chat pagination fix\n", text)
        self.assertIn("## Requirements\n\n- **R1** \n", text)
        meta, body = frontmatter.parse(text)
        self.assertEqual(frontmatter.serialize(meta) + body, text)
        self.spec("new", "--title", "Bad", "--kind", "change", "--amends", "7", succeeds=False)
        self.spec("new", "--title", "Odd", "--kind", "nope", succeeds=False)
        self.assertEqual(self.spec("next-number")["result"]["next_number"], 2)
        self.assertEqual(self.spec("new", "--title", "X", "--kind", "decision", "--slug", "x-y")["result"]["id"], 2)
        self.spec("validate")

    def assert_invalid(self, name: str, content: str, message: str) -> None:
        path = self.write_spec(name, content)
        self.assertIn(message, self.spec("validate", succeeds=False)["error"]["message"])
        path.unlink()
        self.spec("validate")

    def test_validate_errors(self) -> None:
        self.write_spec("README.md", "# Specs\n")
        self.spec("validate")
        self.assert_invalid("3-legacy.md", "# Legacy\n", "not a numbered spec")
        self.assert_invalid("notes.md", "# Notes\n", "not a numbered spec")
        self.assert_invalid("0001-Bad.md", spec_text(1, "bad"), "not a numbered spec")
        self.assert_invalid("0001-higher.md", spec_text(1, "higher", amends=[2]), "must link to a lower id")
        swapped = spec_text(1, "swapped").replace("kind: feature\ncreated: 2026-10-22\n", "created: 2026-10-22\nkind: feature\n")
        self.assert_invalid("0001-swapped.md", swapped, "keys must be exactly")
        self.assert_invalid("0001-nofront.md", "# No frontmatter\n", "frontmatter is missing")
        self.assert_invalid("0001-wrong.md", spec_text(2, "wrong"), "does not match file name number")
        self.assert_invalid("0001-slug.md", spec_text(1, "other"), "does not match file name slug")
        self.assert_invalid("0001-kind.md", spec_text(1, "kind", kind="epic"), "kind must be one of")
        self.assert_invalid("0000-duplicate.md", spec_text(0, "duplicate"), "duplicate spec id")
        self.assert_invalid("0001-unsorted.md", spec_text(1, "unsorted").replace("references: []", "references: [0, 0]"), "sorted")

    def test_status_derivation_and_decision_archive(self) -> None:
        self.spec("new", "--title", "Choose database", "--kind", "decision")
        self.spec("new", "--title", "Choose database again", "--kind", "decision", "--supersedes", "1", "--amends", "0")
        self.assertIn("no `- **R<n>** text`", self.spec("archive", "2", "--parent-confirmed", succeeds=False)["error"]["message"])
        self.write_spec("0002-choose-database-again.md", spec_text(2, "choose-database-again", "decision", "# D\n\n- **R1** Use Postgres.\n", supersedes=[1], amends=[0]))
        self.assertEqual(self.spec("list")["result"][1]["status"], "draft")
        self.tracker("init", FEATURE)
        self.spec("archive", "0", "--parent-confirmed", succeeds=False)
        self.spec("archive", "2", "--parent-confirmed")
        listed = {item["id"]: item for item in self.spec("list")["result"]}
        self.assertEqual(listed[0]["status"], "in_progress")
        self.assertEqual(listed[0]["amended_by"], [2])
        self.assertEqual(listed[1]["status"], "superseded")
        self.assertEqual(listed[1]["superseded_by"], [2])
        self.assertEqual(listed[2]["status"], "accepted")
        manifest = json.loads((self.root / "implementation" / "spec-archive.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["archived"]["0002-choose-database-again.md"]["implementation_record"])
        self.assertEqual(self.spec("next")["result"]["id"], 0)
        self.assertEqual([item["id"] for item in self.spec("list", "--status", "superseded")["result"]], [1])
        self.assertEqual([item["id"] for item in self.spec("list", "--kind", "decision")["result"]], [1, 2])
        status = self.spec("status")["result"]
        self.assertEqual((status["next"]["id"], status["next_number"], status["errors"]), (0, 3, []))
        self.spec("validate")

    def test_show_effective_is_transitive_and_ordered(self) -> None:
        self.history_fixture()
        parts = self.spec("show", "0", "--effective")["result"]
        self.assertEqual([(part["id"], part["relation"]) for part in parts], [(0, "self"), (1, "amends 0000"), (2, "supersedes 0001")])
        output = self.text("show", "0", "--effective")
        markers = [line for line in output.splitlines() if line.startswith("<!--")]
        self.assertEqual(markers, ["<!-- spec 0000 -->", "<!-- spec 0001 amends 0000 -->", "<!-- spec 0002 supersedes 0001 -->"])
        self.assertEqual(output, self.text("show", "0", "--effective"))
        self.assertIn("Required behavior.", self.spec("show", "0")["result"]["content"])

    def test_log_and_graph(self) -> None:
        self.history_fixture()
        log = self.spec("log", "1")["result"]
        self.assertEqual([node["id"] for node in log["ancestors"]], [0])
        self.assertEqual(log["ancestors"][0]["links"], [{"from": 1, "to": 0, "type": "amends"}])
        self.assertEqual([node["id"] for node in log["descendants"]], [2])
        descendants = self.spec("log", "0")["result"]["descendants"]
        self.assertEqual([node["id"] for node in descendants], [1, 2, 3])
        graph = self.spec("graph")["result"]
        self.assertEqual([node["id"] for node in graph["nodes"]], [0, 1, 2, 3])
        self.assertEqual(graph["edges"], [
            {"from": 1, "to": 0, "type": "amends"}, {"from": 2, "to": 0, "type": "depends_on"},
            {"from": 2, "to": 1, "type": "supersedes"}, {"from": 3, "to": 0, "type": "references"},
        ])
        self.assertIn("s0002 -->|supersedes| s0001", self.text("graph", "--mermaid"))

    def test_archived_spec_change_is_detected_and_unlock_relock(self) -> None:
        self.implement()
        self.accept()
        self.spec("archive", "0", "--parent-confirmed")
        path = self.root / "specs" / f"{FEATURE}.md"
        path.write_text(path.read_text(encoding="utf-8") + "Changed.\n", encoding="utf-8")
        self.assertIn("hash changed", self.spec("validate", succeeds=False)["error"]["message"])
        self.spec("unlock", "0", "--reason", "x", "--parent-confirmed", succeeds=False)
        self.spec("relock", "0", "--parent-confirmed", succeeds=False)
        self.spec("unlock", "0", "--reason", "fix", "--user-decision", "ok", "--parent-confirmed")
        self.assertTrue(self.spec("list")["result"][0]["unlocked"])
        self.spec("validate")
        self.spec("relock", "0", "--parent-confirmed")
        self.spec("validate")
        manifest = json.loads((self.root / "implementation" / "spec-archive.json").read_text(encoding="utf-8"))
        self.assertEqual([item["action"] for item in manifest["history"]], ["archive", "unlock", "relock"])
        self.assertNotIn("unlocked", manifest["archived"][f"{FEATURE}.md"])

    def test_preflight_runs_configured_commands(self) -> None:
        self.spec("preflight", succeeds=False)
        config = self.root / "implementation" / "preflight.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"commands": ["true", "false"]}), encoding="utf-8")
        self.assertIn("`false`", self.spec("preflight", succeeds=False)["error"]["message"])
        config.write_text(json.dumps({"commands": ["true"]}), encoding="utf-8")
        self.assertTrue(self.spec("preflight")["result"]["passed"])


LEGACY_BOOTSTRAP = """# Project bootstrap

See [risks](risk-register.md#auth) and specs/1-chats.md.

- **R1** existing requirement
- build the CLI
  - nested detail stays
- add health check

```text
- not a requirement
```
"""

LEGACY_CHATS = "# Chats\n\nFollows [bootstrap](./0-project-bootstrap.md) and `specs/0-project-bootstrap.md`.\n\n- list chats\n"
LEGACY_RISKS = "# Risk register\n\n- accepted risk, see 1-chats.md\n"


class AdoptTest(CliTestCase):
    feature = "0-project-bootstrap"

    def setUp(self) -> None:
        super().setUp()
        (self.root / "specs" / f"{FEATURE}.md").unlink()
        self.write_spec("0-project-bootstrap.md", LEGACY_BOOTSTRAP)
        self.write_spec("1-chats.md", LEGACY_CHATS)
        self.write_spec("risk-register.md", LEGACY_RISKS)
        self.write_spec("README.md", "# Specs\n")
        self.implement()
        self.accept()
        self.tracker("init", "1-chats")
        manifest = {"schema_version": 1, "history": [], "archived": {"0-project-bootstrap.md": {
            "spec_sha256": sha256(self.root / "specs" / "0-project-bootstrap.md"),
            "implementation_record": "implementation/archive/0-project-bootstrap.json",
            "implementation_sha256": sha256(self.root / "implementation" / "archive" / "0-project-bootstrap.json"),
            "archived_at": "2026-01-01T00:00:00Z",
        }}}
        (self.root / "implementation" / "spec-archive.json").write_text(json.dumps(manifest), encoding="utf-8")

    def snapshot(self) -> dict[str, str]:
        return {path.relative_to(self.root).as_posix(): path.read_text(encoding="utf-8") for path in sorted(self.root.rglob("*")) if path.is_file()}

    def test_adopt_migrates_specs_records_and_manifest(self) -> None:
        before = self.snapshot()
        self.spec("adopt", "--parent-confirmed", succeeds=False)
        self.spec("adopt", "--dry-run", "--assign", "risk-register=decision", succeeds=False)
        dry = self.spec("adopt", "--parent-confirmed", "--dry-run", "--assign", "risk-register=decision")["result"]
        self.assertEqual(dry["mapping"], {
            "0-project-bootstrap.md": "0000-project-bootstrap.md", "1-chats.md": "0001-chats.md", "risk-register.md": "0002-risk-register.md",
        })
        self.assertEqual(self.snapshot(), before)

        self.spec("adopt", "--parent-confirmed", "--assign", "risk-register=decision")
        names = sorted(path.name for path in (self.root / "specs").iterdir())
        self.assertEqual(names, ["0000-project-bootstrap.md", "0001-chats.md", "0002-risk-register.md", "README.md"])
        bootstrap = (self.root / "specs" / "0000-project-bootstrap.md").read_text(encoding="utf-8")
        meta, body = frontmatter.parse(bootstrap)
        self.assertEqual((meta["title"], meta["kind"], meta["references"]), ("Project bootstrap", "feature", []))
        self.assertIn("[risks](0002-risk-register.md#auth) and specs/0001-chats.md.", body)
        self.assertIn("- **R1** existing requirement\n- **R2** build the CLI\n  - nested detail stays\n- **R3** add health check\n", body)
        self.assertIn("```text\n- not a requirement\n```", body)
        chats, _ = frontmatter.parse((self.root / "specs" / "0001-chats.md").read_text(encoding="utf-8"))
        self.assertEqual(chats["references"], [0])
        risks_text = (self.root / "specs" / "0002-risk-register.md").read_text(encoding="utf-8")
        risks, risks_body = frontmatter.parse(risks_text)
        self.assertEqual((risks["kind"], risks["references"]), ("decision", [1]))
        self.assertIn("- **R1** accepted risk, see 0001-chats.md", risks_body)

        archived = json.loads((self.root / "implementation" / "archive" / "0000-project-bootstrap.json").read_text(encoding="utf-8"))
        self.assertEqual(archived["feature"], "0000-project-bootstrap")
        self.assertEqual(archived["specification"]["history"][-1]["reason"], "adopt")
        self.assertFalse((self.root / "implementation" / "archive" / "0-project-bootstrap.json").exists())
        self.assertFalse((self.root / "implementation" / "active" / "1-chats.md").exists())
        self.assertTrue((self.root / "implementation" / "active" / "0001-chats.md").is_file())
        manifest = json.loads((self.root / "implementation" / "spec-archive.json").read_text(encoding="utf-8"))
        self.assertEqual(list(manifest["archived"]), ["0000-project-bootstrap.md"])
        self.assertEqual(manifest["history"][-1]["action"], "adopt")

        self.spec("validate")
        self.tracker("spec-check", "0001-chats")
        statuses = [item["status"] for item in self.spec("list")["result"]]
        self.assertEqual(statuses, ["accepted", "in_progress", "draft"])
        self.assertIn("already have frontmatter", self.spec("adopt", "--parent-confirmed", succeeds=False)["error"]["message"])


    def test_adopt_baseline_marks_specs_accepted_without_records(self) -> None:
        self.write_spec("2-search.md", "# Search\n\n- search chats\n")
        adopt = ("adopt", "--parent-confirmed", "--assign", "risk-register=decision")
        self.spec(*adopt, "--baseline", "1-chats", succeeds=False)
        self.spec(*adopt, "--baseline", "missing", succeeds=False)
        self.spec(*adopt, "--baseline", "0-project-bootstrap", succeeds=False)
        dry = self.spec(*adopt, "--dry-run", "--baseline", "2-search", "--baseline", "risk-register")["result"]
        self.assertEqual(dry["baseline"], ["0002-search.md", "0003-risk-register.md"])
        self.spec(*adopt, "--baseline", "2-search", "--baseline", "risk-register")

        manifest = json.loads((self.root / "implementation" / "spec-archive.json").read_text(encoding="utf-8"))
        entry = manifest["archived"]["0002-search.md"]
        self.assertTrue(entry["baseline"])
        self.assertIsNone(entry["implementation_record"])
        self.assertEqual([item["action"] for item in manifest["history"]], ["adopt", "baseline", "baseline"])
        self.spec("validate")
        statuses = [item["status"] for item in self.spec("list")["result"]]
        self.assertEqual(statuses, ["accepted", "in_progress", "accepted", "accepted"])
        message = self.spec("restore", "2", "--reason", "x", "--parent-confirmed", succeeds=False)["error"]["message"]
        self.assertIn("baseline", message)
        self.spec("restore", "3", "--reason", "revisit", "--parent-confirmed")
        self.assertEqual(self.spec("list", "--kind", "decision")["result"][0]["status"], "draft")


class GuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
        (self.root / "specs").mkdir()
        (self.root / "implementation").mkdir()
        for name in ("0000-demo.md", "0001-draft.md"):
            (self.root / "specs" / name).write_text("# Spec\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def guard(self, relative: str, **extra: str) -> int:
        event = {"tool_name": "Edit", "tool_input": {"file_path": str(self.root / relative)}, "cwd": str(self.root), **extra}
        return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), text=True, capture_output=True).returncode

    def write_manifest(self, entry: dict) -> None:
        manifest = {"schema_version": 1, "history": [], "archived": {"0000-demo.md": entry}}
        (self.root / "implementation" / "spec-archive.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_state_files_are_cli_only(self) -> None:
        self.assertEqual(self.guard("implementation/active/0000-demo.json"), 2)
        self.assertEqual(self.guard("implementation/spec-archive.json"), 2)
        self.assertEqual(self.guard("implementation/preflight.json"), 0)

    def test_specs_are_read_only_for_subagents(self) -> None:
        self.assertEqual(self.guard("specs/0000-demo.md"), 2)  # 0.6.0: everyone edits specs through `spec edit`
        self.assertEqual(self.guard("specs/0000-demo.md", agent_id="abc"), 2)
        self.assertEqual(self.guard("be/main.go", agent_id="abc"), 0)

    def test_new_spec_files_must_use_the_cli(self) -> None:
        self.assertEqual(self.guard("specs/0002-new.md"), 2)
        self.assertEqual(self.guard("specs/notes.md"), 2)

    def test_accepted_specs_are_frozen_until_unlocked(self) -> None:
        self.write_manifest({"spec_sha256": "x"})
        self.assertEqual(self.guard("specs/0000-demo.md"), 2)
        self.assertEqual(self.guard("specs/0001-draft.md"), 2)  # 0.6.0: drafts too, through `spec edit`
        self.write_manifest({"spec_sha256": "x", "unlocked": {"reason": "r", "user_decision": "u", "at": "t"}})
        self.assertEqual(self.guard("specs/0000-demo.md"), 2)
        (self.root / "implementation" / "spec-archive.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.guard("specs/0000-demo.md"), 2)


if __name__ == "__main__":
    unittest.main()
