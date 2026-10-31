"""Worktree mode (implementation/workspace.json): each code repo is a folder of branch checkouts, `<repo>/main` for
accepted code and `<repo>/<branch>` per spec. Shared by the tracker, the path-guard hook, and preflight.

    {"repos": ["be", "fe"], "main": "main", "branch": "spec-{id}-{slug}", "test_slots": 1,
     "copy": {"be": [".env"]}, "env": {"be": {".env": {"DATABASE_URL": "postgres://localhost/none"}}},
     "setup": {"fe": ["direnv allow", "direnv exec . npm ci"]},
     "slots": {"review": 2, "test": {"stack": 1, "browser": 2}}, "lease": "2h",
     "ci": {"fast": {"be": ["direnv exec . go build ./..."]}, "full": {...}}, "ci_timeout": 1800,
     "hooks": {"pre_merge": ["..."], "post_merge": ["..."], "pr_check": ["..."],
               "duplicate_numbers": [{"glob": "be/db/migrations/*.sql", "pattern": "^(\\d+)"}]}}

`env` overrides keys in copied dotenv files, so a spec checkout never points at shared dev or production state.
`slots` gives each queue (review, test, merge) its resource classes; a flat `{"stack": 1}` means test classes, and
`test_slots: N` is `{"test": {"default": N}}`. CI commands run in `<repo>/<branch>`, hooks from the project root.

Lane globs stay repo-relative (`be/internal/**`); in a worktree they select `be/<branch>/internal/**`."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

CONFIG = "implementation/workspace.json"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SETUP_TIMEOUT = 900
QUEUES = ("review", "test", "merge")
HOOKS = ("pre_merge", "post_merge", "pr_check")
DURATION = re.compile(r"^([0-9]+)\s*([smhd]?)$")


class WorkspaceError(ValueError):
    pass


def load(root: Path) -> dict[str, Any] | None:
    """The validated config, or None when the project has no workspace.json (one shared working tree)."""
    path = root / CONFIG
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise WorkspaceError(f"cannot read {CONFIG}: {error}") from error
    repos = data.get("repos") if isinstance(data, dict) else None
    if not isinstance(repos, list) or not repos or not all(isinstance(repo, str) and NAME.match(repo) for repo in repos):
        raise WorkspaceError(f'{CONFIG} needs "repos": ["<folder>", ...] (plain folder names)')
    config = {"repos": repos, "main": data.get("main", "main"), "branch": data.get("branch", "spec-{id}-{slug}"),
              "test_slots": data.get("test_slots", 1), "copy": data.get("copy") or {}, "setup": data.get("setup") or {},
              "env": data.get("env") or {}}
    if not isinstance(config["test_slots"], int) or config["test_slots"] < 1:
        raise WorkspaceError(f'{CONFIG}: "test_slots" must be a positive integer')
    config.update(slots=slot_config(data.get("slots") or {}, config["test_slots"]), lease=seconds(data.get("lease", "2h"), "lease"),
                  ci=ci_config(data.get("ci") or {}, repos), ci_timeout=seconds(data.get("ci_timeout", 1800), "ci_timeout"),
                  hooks=hook_config(data.get("hooks") or {}))
    return config


def seconds(value: Any, key: str) -> int:
    """A duration: seconds, or `90s`, `30m`, `2h`, `1d`."""
    match = DURATION.match(str(value).strip()) if isinstance(value, (int, str)) and not isinstance(value, bool) else None
    if not match or int(match.group(1)) < 1:
        raise WorkspaceError(f'{CONFIG}: "{key}" must be a positive duration such as 7200, "30m" or "2h"')
    return int(match.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]


def slot_classes(value: Any, key: str) -> dict[str, int]:
    classes = {"default": value} if isinstance(value, int) else value
    if not isinstance(classes, dict) or not classes or not all(
            isinstance(name, str) and NAME.match(name) and isinstance(count, int) and not isinstance(count, bool) and count >= 1
            for name, count in classes.items()):
        raise WorkspaceError(f'{CONFIG}: "slots.{key}" must be a positive integer or {{"<class>": <positive integer>, ...}}')
    return dict(classes)


def slot_config(raw: Any, test_slots: int) -> dict[str, dict[str, int]]:
    if not isinstance(raw, dict):
        raise WorkspaceError(f'{CONFIG}: "slots" must be an object')
    slots = {"review": {"default": 2}, "test": {"default": test_slots}, "merge": {"default": 1}}
    flat = {key: value for key, value in raw.items() if key not in QUEUES}
    for queue in QUEUES:
        if queue in raw:
            slots[queue] = slot_classes(raw[queue], queue)
    if flat:
        slots["test"] = {**(slots["test"] if "test" in raw else {}), **slot_classes(flat, "test")}
    return slots


def commands(value: Any, key: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise WorkspaceError(f'{CONFIG}: "{key}" must be a list of shell commands')
    return list(value)


def ci_config(raw: Any, repos: list[str]) -> dict[str, dict[str, list[str]]]:
    if not isinstance(raw, dict) or not all(isinstance(tier, str) and NAME.match(tier) and isinstance(per, dict) for tier, per in raw.items()):
        raise WorkspaceError(f'{CONFIG}: "ci" must be {{"<tier>": {{"<repo>": ["<command>", ...]}}}}, e.g. a "fast" tier')
    unknown = sorted({repo for per in raw.values() for repo in per if repo not in repos})
    if unknown:
        raise WorkspaceError(f'{CONFIG}: "ci" names unknown repos {", ".join(unknown)}; "repos" lists {", ".join(repos)}')
    return {tier: {repo: commands(per[repo], f"ci.{tier}.{repo}") for repo in repos if repo in per} for tier, per in raw.items()}


def hook_config(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkspaceError(f'{CONFIG}: "hooks" must be an object')
    unknown = sorted(set(raw) - set(HOOKS) - {"duplicate_numbers"})
    if unknown:
        raise WorkspaceError(f'{CONFIG}: unknown hooks {", ".join(unknown)}; use {", ".join(HOOKS)}, duplicate_numbers')
    hooks: dict[str, Any] = {name: commands(raw.get(name, []), f"hooks.{name}") for name in HOOKS}
    rules = raw.get("duplicate_numbers", [])
    if not isinstance(rules, list):
        raise WorkspaceError(f'{CONFIG}: "hooks.duplicate_numbers" must be a list of {{"glob": "<repo>/<dir>/*", "pattern": "^(\\d+)"}}')
    hooks["duplicate_numbers"] = []
    for rule in rules:
        glob = rule.get("glob") if isinstance(rule, dict) else None
        pattern = rule.get("pattern", r"^(\d+)") if isinstance(rule, dict) else None
        try:
            valid = isinstance(glob, str) and "/" in glob and isinstance(pattern, str) and re.compile(pattern).groups >= 1
        except re.error:
            valid = False
        if not valid:
            raise WorkspaceError(f'{CONFIG}: each "hooks.duplicate_numbers" rule needs "glob": "<repo>/<dir>/<pattern>" and an optional '
                                 f'"pattern" regex with one group for the number (default "^(\\d+)", matched on the file name)')
        hooks["duplicate_numbers"].append({"glob": glob, "pattern": pattern})
    return hooks


def default_class(config: dict[str, Any], queue: str) -> str:
    classes = config["slots"][queue]
    return "default" if "default" in classes else next(iter(classes))


def branch_name(config: dict[str, Any], feature: str) -> str:
    spec, _, slug = feature.partition("-")
    name = config["branch"].format(id=spec, slug=slug, feature=feature)
    if not NAME.match(name):
        raise WorkspaceError(f"branch {name!r} must be one plain folder name (no '/'); fix \"branch\" in {CONFIG}")
    return name


def split(config: dict[str, Any], relative: str) -> tuple[str, str, str] | None:
    """`be/<branch>/internal/x.go` -> ("be", "<branch>", "internal/x.go"); None outside a repo's checkouts."""
    parts = relative.split("/", 2)
    if len(parts) < 2 or parts[0] not in config["repos"]:
        return None
    return parts[0], parts[1], parts[2] if len(parts) == 3 else ""


def logical(config: dict[str, Any], relative: str) -> str:
    """A worktree path as its lane path: `be/<branch>/internal/x.go` -> `be/internal/x.go`."""
    found = split(config, relative)
    return relative if found is None else "/".join(part for part in (found[0], found[2]) if part)


def rewrite(config: dict[str, Any], command: str, branch: str, root: Path | None = None) -> str:
    """Point `cd <repo>` (and `cd <repo>/sub`) at the `<repo>/<branch>` checkout, and a sibling `../<repo>` (used from inside a
    checkout) at `../../<repo>/<branch>`, or `../../<repo>/<main>` when that repo has no checkout for the branch."""
    end = r"(?=[/\s;&|)'\"]|$)"
    for repo in config["repos"]:
        # Paths that already name a checkout (`fe/main`, `fe/<branch>`) are left alone, so rewriting is idempotent.
        names = {config["main"], branch} | ({path.name for path in (root / repo).iterdir() if path.is_dir()}
                                             if root is not None and (root / repo).is_dir() else set())
        named = rf"(?!/(?:{'|'.join(re.escape(name) for name in sorted(names))}){end})"
        command = re.sub(rf"(\b(?:cd|direnv\s+exec)\s+){re.escape(repo)}{named}{end}", rf"\g<1>{repo}/{branch}", command)
        sibling = branch if root is None or (root / repo / branch).is_dir() else config["main"]
        command = re.sub(rf"(?<![\w./-])\.\./{re.escape(repo)}{named}{end}", f"../../{repo}/{sibling}", command)
    # `cd <repo>` now enters one level deeper, so a plain `cd ..` straight after it must climb two levels back to the root.
    checkouts = "|".join(re.escape(f"{repo}/{branch}") for repo in config["repos"])
    state = {"inside": False}

    def climb(match: re.Match[str]) -> str:
        target = match.group(2)
        if target == ".." and state["inside"]:
            state["inside"] = False
            return f"{match.group(1)}../.."
        state["inside"] = bool(re.fullmatch(checkouts, target))
        return match.group(0)

    return re.sub(r"(\bcd\s+)([^\s;&|)]+)", climb, command)


def git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    if check and process.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} in {path}: {(process.stderr or process.stdout).strip()}")
    return process


def main_checkout(root: Path, config: dict[str, Any], repo: str) -> Path:
    path = root / repo / config["main"]
    if not (path / ".git").exists():
        raise WorkspaceError(f"{repo}/{config['main']} is not a git checkout; move the clone into it first "
                             f"(`mv {repo} {repo}.tmp && mkdir {repo} && mv {repo}.tmp {repo}/{config['main']}`)")
    return path


def dirty(path: Path) -> list[str]:
    return [line[3:] for line in git(path, "status", "--porcelain").stdout.splitlines() if line.strip()]


def head(path: Path, ref: str = "HEAD") -> str:
    return git(path, "rev-parse", ref).stdout.strip()


def merged(main: Path, branch: str) -> bool:
    return git(main, "merge-base", "--is-ancestor", branch, "HEAD", check=False).returncode == 0


def create(root: Path, config: dict[str, Any], repo: str, branch: str, base: str) -> dict[str, Any]:
    """Add `<repo>/<branch>` (a new branch from `base`, or the existing branch), copy untracked files, run setup."""
    main = main_checkout(root, config, repo)
    target = root / repo / branch
    if target.exists():
        return {"repo": repo, "path": f"{repo}/{branch}", "created": False}
    exists = git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0
    if exists:
        git(main, "worktree", "add", str(target), branch)
    else:
        # A dependency's branch may exist only in the repos it touched; elsewhere start from main.
        if git(main, "rev-parse", "--verify", "--quiet", base, check=False).returncode != 0:
            base = config["main"]
        git(main, "worktree", "add", "-b", branch, str(target), base)
    copied = []
    for name in config["copy"].get(repo, []):
        source = main / name
        if source.is_file() and not (target / name).exists():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            overrides = config["env"].get(repo, {}).get(name)
            if overrides:
                (target / name).write_text(override_env(source.read_text(encoding="utf-8"), overrides), encoding="utf-8")
            else:
                (target / name).write_bytes(source.read_bytes())
            copied.append(name)
    for command in config["setup"].get(repo, []):
        process = subprocess.run(command, shell=True, cwd=target, capture_output=True, text=True, timeout=SETUP_TIMEOUT)
        if process.returncode != 0:
            raise WorkspaceError(f"setup `{command}` failed in {repo}/{branch}: {(process.stderr or process.stdout).strip()[-400:]}")
    return {"repo": repo, "path": f"{repo}/{branch}", "created": True, "base": base, "copied": copied}


def override_env(text: str, overrides: dict[str, str]) -> str:
    """Set each key in a dotenv text (`KEY=...` or `export KEY=...`), appending keys that are missing."""
    lines, seen = text.splitlines(), set()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match and match.group(2) in overrides:
            lines[index] = f"{match.group(1)}{match.group(2)}={overrides[match.group(2)]}"
            seen.add(match.group(2))
    lines += [f"{key}={value}" for key, value in overrides.items() if key not in seen]
    return "\n".join(lines) + "\n"


def checkpoint(root: Path, repo: str, branch: str, message: str) -> bool:
    """Commit every change in `<repo>/<branch>`; False when there was nothing to commit."""
    path = root / repo / branch
    if not path.is_dir() or not dirty(path):
        return False
    git(path, "add", "-A")
    git(path, "commit", "-q", "--no-verify", "-m", message)
    return True


def conflicts(main: Path, branch: str) -> list[str]:
    """Files that would conflict when merging `branch` into the main checkout (git merge-tree, nothing is touched)."""
    process = git(main, "merge-tree", "--write-tree", "--name-only", "HEAD", branch, check=False)
    if process.returncode == 0:
        return []
    if process.returncode != 1:
        raise WorkspaceError(f"git merge-tree failed in {main}: {process.stderr.strip()}")
    lines = process.stdout.splitlines()[1:]
    return [line for line in lines[: lines.index("") if "" in lines else len(lines)] if line]
