"""Worktree mode (implementation/workspace.json): each code repo is a folder of branch checkouts, `<repo>/main` for
accepted code and `<repo>/<branch>` per spec. Shared by the tracker, the path-guard hook, and preflight.

    {"repos": ["be", "fe"], "main": "main", "branch": "spec-{id}-{slug}", "test_slots": 1,
     "copy": {"be": [".env"]}, "setup": {"fe": ["direnv allow", "direnv exec . npm ci"]}}

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
              "test_slots": data.get("test_slots", 1), "copy": data.get("copy") or {}, "setup": data.get("setup") or {}}
    if not isinstance(config["test_slots"], int) or config["test_slots"] < 1:
        raise WorkspaceError(f'{CONFIG}: "test_slots" must be a positive integer')
    return config


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


def rewrite(config: dict[str, Any], command: str, branch: str) -> str:
    """Point `cd <repo>` (and `cd <repo>/sub`) at the `<repo>/<branch>` checkout."""
    for repo in config["repos"]:
        command = re.sub(rf"(\bcd\s+){re.escape(repo)}(?=[/\s;&|)]|$)", rf"\g<1>{repo}/{branch}", command)
    return command


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
            (target / name).write_bytes(source.read_bytes())
            copied.append(name)
    for command in config["setup"].get(repo, []):
        process = subprocess.run(command, shell=True, cwd=target, capture_output=True, text=True, timeout=SETUP_TIMEOUT)
        if process.returncode != 0:
            raise WorkspaceError(f"setup `{command}` failed in {repo}/{branch}: {(process.stderr or process.stdout).strip()[-400:]}")
    return {"repo": repo, "path": f"{repo}/{branch}", "created": True, "base": base, "copied": copied}


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
