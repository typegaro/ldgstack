"""Local CI and PR checks (worktree mode): `ci` tiers per repo, merge-tree conflicts against main, and project hooks.

A tier run is recorded as the check `ci-<tier>` with its commands, exit codes, seconds, branch and main SHAs, and a log
under implementation/ci/<feature>/. CI is the writer's evidence; it never replaces the reviewer or the tester."""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any

from . import paths as lanes
from . import workspace
from .model import generation, latest_checks

Record = dict[str, Any]
CI_DIR = "implementation/ci"
OUTPUT_TAIL = 400


def names(config: Record | None) -> set[str]:
    return {f"ci-{tier}" for tier in (config or {}).get("ci", {})} | {"ci-fast", "ci-full"}


def heads(root: Path, config: Record, repos: list[str], branch: str) -> dict[str, str]:
    return {repo: workspace.head(root / repo / config["main"], branch) for repo in repos}


def main_heads(root: Path, config: Record, repos: list[str]) -> dict[str, str]:
    return {repo: workspace.head(root / repo / config["main"]) for repo in repos}


def shell(root: Path, config: Record, command: str, cwd: Path, branch: str | None, env: dict[str, str], timeout: int) -> tuple[int, str, float]:
    started = time.monotonic()
    try:
        process = subprocess.run(workspace.rewrite(config, command, branch or config["main"], root), shell=True, cwd=cwd,
                                 capture_output=True, text=True, timeout=timeout, env={**os.environ, **env})
        code, output = process.returncode, process.stdout + process.stderr
    except subprocess.TimeoutExpired as error:
        code, output = 124, f"{error.stdout or ''}{error.stderr or ''}\ntimed out after {timeout}s"
    return code, output if isinstance(output, str) else str(output), round(time.monotonic() - started, 1)


def run(root: Path, config: Record, feature: str, branch: str, repos: list[str], tier: str, timestamp: str) -> Record | None:
    """Run one tier in the spec's checkouts, stopping at the first failure. None when the tier names none of `repos`."""
    plan = [(repo, command) for repo in repos for command in config["ci"].get(tier, {}).get(repo, [])]
    if not plan:
        return None
    log = Path(CI_DIR) / feature / f"{re.sub(r'[^0-9A-Za-z]', '', timestamp)}-{tier}.log"
    (root / log).parent.mkdir(parents=True, exist_ok=True)
    result: Record = {"tier": tier, "result": "passed", "branch": branch, "branch_shas": heads(root, config, repos, branch),
                      "main_shas": main_heads(root, config, repos), "at": timestamp, "log": log.as_posix(), "commands": []}
    env = {"SPEC_FEATURE": feature, "SPEC_BRANCH": branch}
    with (root / log).open("w", encoding="utf-8") as stream:
        for repo, command in plan:
            code, output, spent = shell(root, config, command, root / repo / branch, branch, env, config["ci_timeout"])
            stream.write(f"$ [{repo}/{branch}] {command}\n{output}\n[exit {code} in {spent}s]\n\n")
            result["commands"].append({"repo": repo, "command": command, "exit": code, "seconds": spent})
            if code != 0:
                result.update(result="failed", failed={"repo": repo, "command": command, "exit": code, "tail": output.strip()[-OUTPUT_TAIL:]})
                break
    return result


def check_entry(result: Record, record: Record) -> Record:
    commands = "; ".join(f"[{item['repo']}] {item['command']} -> exit {item['exit']} ({item['seconds']}s)" for item in result["commands"])
    shas = ", ".join(f"{repo} {sha[:12]} on main {result['main_shas'][repo][:12]}" for repo, sha in result["branch_shas"].items())
    return {"name": f"ci-{result['tier']}", "method": f"tracker ci ({result['tier']} tier in {', '.join(result['branch_shas'])})",
            "result": result["result"], "evidence": f"{commands}. Branch {shas}. Log: {result['log']}", "role": record["current_role"],
            "generation": generation(record), "at": result["at"], "ci": {key: value for key, value in result.items() if key != "tier"}}


def failure_text(result: Record) -> str:
    failed = result["failed"]
    return (f"fast CI failed: `{failed['command']}` in {failed['repo']}/{result['branch']} exited {failed['exit']}; "
            f"log: {result['log']}; output tail: {failed['tail']}")


def gate_errors(root: Path, record: Record) -> list[str]:
    """Acceptance needs a passing `ci-fast` on the branch's current SHAs when workspace.json has a `ci.fast` tier."""
    try:
        config = workspace.load(root)
    except workspace.WorkspaceError as error:
        return [str(error)]
    tree = record.get("worktree")
    if not config or not config["ci"].get("fast") or not tree or tree.get("removed_at"):
        return []
    repos = [repo for repo in tree["repos"] if repo in config["ci"]["fast"]] or tree["repos"]
    rerun = f"`tracker ci run {record['feature']}` (or the writer's `tracker pr open`)"
    latest = {item["name"]: item for item in latest_checks(record)}.get("ci-fast")
    if latest is None or not latest.get("ci"):
        return [f"fast CI has not run on {tree['branch']}: {rerun}"]
    if latest["result"] != "passed":
        return []  # already reported as a failing check
    try:
        current = heads(root, config, tree["repos"], tree["branch"])
    except workspace.WorkspaceError as error:
        return [f"cannot read {tree['branch']}: {error}"]
    stale = [f"{repo} ran on {latest['ci']['branch_shas'].get(repo, 'nothing')[:12]}, branch is {current[repo][:12]}"
             for repo in repos if latest["ci"]["branch_shas"].get(repo) != current[repo]]
    return [f"fast CI is stale ({'; '.join(stale)}): {rerun}"] if stale else []


def stats(root: Path, config: Record, repo: str, branch: str) -> Record:
    main = root / repo / config["main"]
    behind, ahead = (int(value) for value in workspace.git(main, "rev-list", "--left-right", "--count", f"HEAD...{branch}").stdout.split())
    added = deleted = files = 0
    for line in workspace.git(main, "diff", "--numstat", f"HEAD...{branch}").stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            files += 1
            added += int(parts[0]) if parts[0].isdigit() else 0
            deleted += int(parts[1]) if parts[1].isdigit() else 0
    return {"branch": branch, "path": f"{repo}/{branch}", "head": workspace.head(main, branch), "main": workspace.head(main),
            "ahead": ahead, "behind": behind, "conflicts": workspace.conflicts(main, branch), "additions": added, "deletions": deleted, "files": files}


def added_files(main: Path, branch: str) -> list[str]:
    return [line for line in workspace.git(main, "diff", "--name-only", "--diff-filter=A", f"HEAD...{branch}").stdout.splitlines() if line]


def number_findings(root: Path, config: Record, branches: dict[str, Record]) -> dict[str, list[Record]]:
    """`hooks.duplicate_numbers`: a branch adds a numbered file (e.g. a migration) whose number main, or another open
    branch, already uses under a different name. `branches` maps feature -> its worktree record."""
    found: dict[str, list[Record]] = {feature: [] for feature in branches}
    for rule in config["hooks"]["duplicate_numbers"]:
        repo, glob = rule["glob"].split("/", 1)
        pattern = re.compile(rule["pattern"])

        def number(path: str) -> str | None:
            match = pattern.search(PurePosixPath(path).name)
            return match.group(1) if match else None

        main = root / repo / config["main"]
        if repo not in config["repos"] or not (main / ".git").exists():
            continue
        prefix = lanes.static_prefix(glob) or "."
        on_main: dict[str, set[str]] = {}
        for path in workspace.git(main, "ls-tree", "-r", "--name-only", "HEAD", "--", prefix).stdout.splitlines():
            if lanes.matches([glob], path) and number(path):
                on_main.setdefault(number(path) or "", set()).add(path)
        added: dict[str, dict[str, set[str]]] = {}
        for feature, tree in branches.items():
            if repo in tree["repos"]:
                for path in added_files(main, tree["branch"]):
                    if lanes.matches([glob], path) and number(path):
                        added.setdefault(feature, {}).setdefault(number(path) or "", set()).add(path)
        for feature, numbers in added.items():
            for value, mine in numbers.items():
                clash = sorted(on_main.get(value, set()) - mine)
                # Files sharing a stem (000057_x.up.sql, 000057_x.down.sql) are one numbered entry.
                if clash or len({PurePosixPath(path).name.split(".")[0] for path in mine}) > 1:
                    found[feature].append({"kind": "main", "text": f"{repo}: {', '.join(sorted(mine))} reuses number {value} "
                                                                   f"({', '.join(clash) or 'twice in this branch'}{' on main' if clash else ''}); renumber it"})
                for other, theirs in added.items():
                    if other != feature and value in theirs and theirs[value] != mine:
                        found[feature].append({"kind": "branch", "text": f"{repo}: {', '.join(sorted(mine))} and {other}'s "
                                                                         f"{', '.join(sorted(theirs[value]))} both take number {value}; "
                                                                         "the one merged second renumbers"})
    return found


def run_hooks(root: Path, config: Record, name: str, feature: str, branch: str | None) -> list[Record]:
    """Run `hooks.<name>` from the project root; repo paths point at `branch`'s checkouts (main when None)."""
    results = []
    for command in config["hooks"][name]:
        code, output, spent = shell(root, config, command, root, branch, {"SPEC_FEATURE": feature, "SPEC_BRANCH": branch or config["main"]},
                                    config["ci_timeout"])
        results.append({"command": command, "exit": code, "seconds": spent, **({"tail": output.strip()[-OUTPUT_TAIL:]} if code else {})})
        if code != 0:
            break
    return results


def check_branches(root: Path, config: Record, records: list[Record], only: str | None = None) -> dict[str, Record]:
    """Conflicts against current main, numbered-file clashes (across all `records`), and `hooks.pr_check`, for each
    record's branch (or `only` that feature's)."""
    trees = {record["feature"]: record["worktree"] for record in records}
    numbers = number_findings(root, config, trees)
    report = {}
    for feature, tree in trees.items():
        if only and feature != only:
            continue
        conflicts = {repo: workspace.conflicts(root / repo / config["main"], tree["branch"]) for repo in tree["repos"]}
        findings = list(numbers.get(feature, []))
        findings += [{"kind": "hook", "text": f"pr_check `{item['command']}` exited {item['exit']}: {item.get('tail', '')}"}
                     for item in run_hooks(root, config, "pr_check", feature, tree["branch"]) if item["exit"]]
        report[feature] = {"conflicts": {repo: files for repo, files in conflicts.items() if files}, "findings": findings,
                           "main_shas": main_heads(root, config, tree["repos"])}
    return report


def blocking(report: Record) -> list[str]:
    """What keeps a PR from review or merge: conflicts, and findings against main or from a hook (not branch-vs-branch)."""
    return [f"{repo}/{name}" for repo, files in report["conflicts"].items() for name in files] + \
        [item["text"] for item in report["findings"] if item["kind"] != "branch"]
