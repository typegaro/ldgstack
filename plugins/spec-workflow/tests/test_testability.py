"""0.7.1: `## Testability` sections (validate, import, evidence), parent tool gaps (#36), `brief --fresh` (#37), planner guidance."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_improvements import M33
from test_planning import PLAN, PlanCase, body
from test_workflow import FEATURE, PLUGIN, SPEC, CliTestCase, spec_text

from speclib import frontmatter

TESTABILITY = "\n## Testability\n\n- **R3** [ops] Drivers: `demo-drive item create|show --id ID` drives any item, JSON, `--help`.\n"


def versioned(number: int, slug: str, body_text: str, kind: str = "feature", workflow: str | None = "0.7.1") -> str:
    meta = {"id": number, "slug": slug, "title": slug.capitalize(), "kind": kind, "created": "2026-10-26",
            **{key: [] for key in frontmatter.RELATIONS}}
    if workflow:
        meta[frontmatter.OPTIONAL] = workflow
    return frontmatter.serialize(meta) + "\n" + body_text


class ValidateTest(CliTestCase):
    def test_missing_section_warns_for_legacy_and_fails_from_0_7_1(self) -> None:
        result = self.spec("validate")["result"]  # legacy spec (no workflow key): warning only
        self.assertTrue(result["valid"])
        self.assertIn("0000-demo.md: feature spec has no `## Testability` section", result["warnings"][0])
        self.assertIn("testability", self.spec("validate", "--strict-testability", succeeds=False)["error"]["message"])

        self.write_spec("0001-new.md", versioned(1, "new", "# New\n\n- **R1** Behavior.\n"))
        message = self.spec("validate", succeeds=False)["error"]["message"]
        self.assertIn("0001-new.md: feature spec has no `## Testability` section", message)
        self.assertNotIn("0000-demo.md", message)

        self.write_spec("0001-new.md", versioned(1, "new", "# New\n\n- **R1** Behavior.\n\n## Testability\n\nSome prose.\n"))
        self.assertIn("no `- **R<n>**` bullets", self.spec("validate", succeeds=False)["error"]["message"])

        self.write_spec("0001-new.md", versioned(1, "new", "# New\n\n- **R1** Behavior.\n" + TESTABILITY))
        self.assertTrue(self.spec("validate")["result"]["valid"])
        self.write_spec("0002-docs.md", versioned(2, "docs", "# Docs\n\n- **R1** Wording.\n\n## Testability\n\nNot applicable: docs only.\n"))
        self.write_spec("0003-risk.md", versioned(3, "risk", "# Risk\n\n- **R1** Accepted.\n", kind="decision"))
        self.write_spec("0004-fenced.md", versioned(4, "fenced", "# F\n\n- **R1** B.\n\n```\n## Testability\n- **R2** x\n```\n"))
        message = self.spec("validate", succeeds=False)["error"]["message"]
        self.assertIn("0004-fenced.md", message)
        self.assertNotIn("0002-docs.md", message)
        self.assertNotIn("0003-risk.md", message)

    def test_new_stamps_the_workflow_version_and_a_testability_skeleton(self) -> None:
        created = self.spec("new", "--title", "Thing", "--kind", "feature")["result"]
        text = (self.root / created["path"]).read_text(encoding="utf-8")
        version = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertIn(f"\nworkflow: {version}\n", text)
        self.assertIn("## Testability", text)
        self.assertEqual(self.spec("show", "1")["result"]["content"], text)
        self.assertEqual(self.spec("list")["result"][1]["workflow"], version)
        decision = self.spec("new", "--title", "Accept x", "--kind", "decision")["result"]
        self.assertNotIn("## Testability", (self.root / decision["path"]).read_text(encoding="utf-8"))
        self.assertTrue(self.spec("validate")["result"]["valid"])

    def test_text_output_lists_warnings(self) -> None:
        output = subprocess.run(["python3", str(SPEC), "validate"], cwd=self.root, text=True, capture_output=True, check=True).stdout
        self.assertTrue(output.startswith("valid: True (1 specs)\nwarning: 0000-demo.md"))


class TestabilityEvidenceTest(PlanCase):
    requirements = 2

    def setUp(self) -> None:
        CliTestCase.setUp(self)
        self.write_spec(f"{FEATURE}.md", spec_text(0, "demo", body=body(2) + TESTABILITY))
        (self.root / "implementation").mkdir()
        (self.root / "implementation" / "preflight.json").write_text(json.dumps({"commands": ["true"]}), encoding="utf-8")
        (self.root / "tools" / "demo-drive").mkdir(parents=True)
        self.tracker("init", f"specs/{FEATURE}.md")
        self.handoff("parent")
        self.tracker("requirement", "import", FEATURE)

    def test_testability_requirements_need_a_verified_reusable_tool(self) -> None:
        flags = {item["spec_ref"]: item.get("testability") for item in self.record()["requirements"]}
        self.assertEqual(flags, {"0:R1": False, "0:R2": False, "0:R3": True})
        self.tracker("handoff", FEATURE, "--to", "implementer", "--completed", "c", "--remaining", "r", "--parent-confirmed", "--reason", "tiny")
        self.tracker("requirement", "implemented", FEATURE, "REQ-001", "--evidence", "done")  # ordinary requirement: free text
        message = self.tracker("requirement", "implemented", FEATURE, "REQ-003", "--evidence", "wrote a script", succeeds=False)["error"]["message"]
        self.assertIn("Testability requirement", message)
        self.assertIn("one-off scripts", message)
        self.tracker("toolkit", "add", "demo-drive", "--capability", "be.seed", "--command", "tools/demo-drive/run --help",
                     "--location", "tools/demo-drive", "--smoke", "true", "--owner-spec", "0000", "--mode", "mutating", "--guard", "refuses the dev DB without a test target")
        evidence = "tool demo-drive (`demo-drive item create --id X`); --help documents it; smoke: toolkit verify demo-drive passed"
        self.assertIn("toolkit verify demo-drive", self.tracker("requirement", "implemented", FEATURE, "REQ-003", "--evidence", evidence,
                                                              succeeds=False)["error"]["message"])  # stale: never verified
        self.tracker("toolkit", "verify", "demo-drive")
        self.assertIn("--help", self.tracker("requirement", "implemented", FEATURE, "REQ-003", "--evidence",
                                             "tool demo-drive; smoke passed", succeeds=False)["error"]["message"])
        self.tracker("requirement", "implemented", FEATURE, "REQ-003", "--evidence", evidence)
        item = self.record()["requirements"][2]
        self.assertEqual(item["testability_tools"][0]["name"], "demo-drive")
        self.assertTrue(item["implemented"])

    def test_parent_records_a_tool_gap_as_the_toolsmith_fallback(self) -> None:
        self.assertFalse(self.tracker("tool-gap", "add", FEATURE, "--capability", "be.fault", "--requirement", "REQ-003",
                                      "--why", "toolkit requirement", succeeds=False)["ok"])
        self.tracker("tool-gap", "add", FEATURE, "--capability", "be.fault", "--requirement", "REQ-003", "--why", "toolkit requirement",
                     "--parent-confirmed")
        gap = self.record()["tool_gaps"][0]
        self.assertEqual((gap["found_by"], gap["recorded_during_role"], gap["status"]), ("parent", "parent", "open"))
        self.handoff("toolsmith")
        self.assertEqual(self.record()["status"], "tooling")


class FreshBriefTest(PlanCase):
    def test_brief_fresh_issues_a_new_assignment(self) -> None:
        self.planned()
        self.handoff("implementer")
        first = self.tracker("assign", FEATURE, "--role", "implementer", "--from-plan", "--parent-confirmed")["result"]["assignment"]
        self.assertIn(first, self.brief("--role", "implementer", "--batch", "1")["result"])
        self.tracker("claim", first)
        second_brief = self.brief("--role", "implementer", "--batch", "2", "--fresh")["result"]
        assignments = [item for item in self.record()["assignments"] if item["role"] == "implementer"]
        self.assertEqual([item["status"] for item in assignments], ["released", "active"])
        second = assignments[-1]
        self.assertNotEqual(second["id"], first)
        self.assertEqual(second["paths"], assignments[0]["paths"])
        self.assertIn(f"claim {second['id']}", second_brief)
        self.tracker("claim", second["id"])
        self.tracker("claim", first, succeeds=False)
        self.brief("--role", "reviewer", "--fresh", succeeds=False)  # not the record's role


class GuidanceTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (PLUGIN / relative).read_text(encoding="utf-8")

    def test_planner_routes_testability_to_executor_batches(self) -> None:
        planning = self.read("skills/spec-implementer/references/planning.md")
        self.assertIn("## Testability requirements", planning)
        self.assertIn("Never route them to the toolsmith", planning)
        self.assertIn("tool-gap add --parent-confirmed", planning)
        self.assertIn("never for the toolsmith", self.read("agents/spec-planner.md"))
        self.assertIn("--fresh", self.read("skills/spec-orchestrator/SKILL.md"))

    def test_reusable_tool_rule_is_everywhere(self) -> None:
        question = "could a different tester reuse this tool for a new scenario without editing it"
        for relative in ("skills/write-specs/references/testability.md", "skills/adversarial-spec-review/SKILL.md",
                         "skills/spec-reviewer/SKILL.md"):
            self.assertIn(question, self.read(relative).lower(), relative)
        for relative in ("skills/write-specs/SKILL.md", "skills/spec-implementer/references/planning.md", "skills/test-toolkit/SKILL.md"):
            self.assertIn("reusable", self.read(relative), relative)
        template = self.read("skills/write-specs/references/testability.md")
        for label in ("Inspection:", "Drivers:", "Fault and mocks:", "Environment:", "Verification:", "## Example"):
            self.assertIn(label, template)


@unittest.skipUnless((M33 / "specs").is_dir(), "no compatibility fixture")
class TestabilityCompatibilityTest(unittest.TestCase):
    """Existing m33 specs (no `workflow:` key) only produce warnings."""

    def test_existing_specs_only_warn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(M33 / "specs", root / "specs")
            if (M33 / "implementation").is_dir():
                shutil.copytree(M33 / "implementation", root / "implementation")
            (root / "AGENTS.md").write_text("# Copy\n", encoding="utf-8")
            process = subprocess.run([str(PLUGIN / "bin" / "spec"), "--json", "validate"], cwd=root, text=True, capture_output=True,
                                     env={**os.environ, "SPEC_WORKFLOW_ROOT": str(root)})
            result = json.loads(process.stdout)
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["result"]["warnings"])


if __name__ == "__main__":
    unittest.main()
