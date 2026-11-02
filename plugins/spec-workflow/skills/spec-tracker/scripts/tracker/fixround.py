"""Fix rounds in worktree mode: the branch heads a round starts from, its diff, and the light path (`handoff --light`)
that sends a small low-severity fix straight to retest without a fresh review."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import ci, workspace
from . import paths as lanes
from .model import generation, now

Record = dict[str, Any]


def start(root: Path, config: Record | None, record: Record) -> None:
    """Remember the branch heads a fix round starts from (called once the round's generation is set)."""
    tree = record.get("worktree")
    if config and tree and not tree.get("removed_at"):
        record["fix_round"] = {"generation": generation(record), "base": ci.heads(root, config, tree["repos"], tree["branch"]), "at": now()}


def diff(root: Path, config: Record, record: Record) -> tuple[list[str], int]:
    """Repo-prefixed files the round changed, and the lines added plus deleted (committed work only)."""
    tree, base = record["worktree"], record["fix_round"]["base"]
    files, lines = [], 0
    for repo in tree["repos"]:
        stat = workspace.git(root / repo / config["main"], "diff", "--numstat", "--no-renames", base[repo], tree["branch"]).stdout
        for line in stat.splitlines():
            added, deleted, path = line.split("\t", 2)
            files.append(f"{repo}/{path}")
            lines += sum(int(value) for value in (added, deleted) if value.isdigit())
    return files, lines


def light_errors(root: Path, config: Record | None, record: Record) -> tuple[list[str], Record]:
    """Why this fix round needs a fresh review, and what the tracker measured."""
    tree, round_ = record.get("worktree"), record.get("fix_round")
    if not config or not tree:
        return ["a light round needs worktree mode (the tracker measures the fix diff)"], {}
    if not round_ or round_["generation"] != generation(record):
        return ["no fix-round base recorded for this generation"], {}
    errors = []
    if record.get("risk") == "high":
        errors.append("the record is high risk")
    if record.get("rereview_required"):
        errors.append("an agent resolved a merge with main")
    fixed = [item for item in record["bugs"] if item["status"] == "fixed"]
    if not fixed:
        errors.append("no bug was fixed this round")
    heavy = [f"{item['id']} ({item['severity']})" for item in fixed if item["severity"] != "low"]
    if heavy:
        errors.append(f"not low severity: {', '.join(heavy)}")
    if not any(item.get("role") == "reviewer" for item in record["checks"]):
        errors.append("the code was never reviewed")
    for repo in tree["repos"]:
        workspace.checkpoint(root, repo, tree["branch"], f"{record['feature']} fixer {generation(record)}")
    files, lines = diff(root, config, record)
    rules = config["light_fix"]
    sensitive = [path for path in files if lanes.matches(rules["sensitive"], path)]
    if sensitive:
        errors.append(f"touches sensitive paths: {', '.join(sensitive)}")
    code = [path for path in files if not lanes.matches(rules["paths"], path)]
    if code and lines > rules["max_lines"]:
        errors.append(f"{lines} changed lines (limit {rules['max_lines']}) in code files: {', '.join(code)}")
    return errors, {"files": files, "lines": lines, "bugs": [item["id"] for item in fixed]}
