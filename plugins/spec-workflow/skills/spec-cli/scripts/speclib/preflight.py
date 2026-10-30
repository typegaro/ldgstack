"""Verify that every command in implementation/preflight.json runs."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .errors import SpecError

TIMEOUT_SECONDS = 300
WORKSPACE = "implementation/workspace.json"


def on_main(root: Path, command: str) -> str:
    """Worktree mode (spec-tracker's workspace.json): `cd <repo>` runs in the accepted `<repo>/<main>` checkout."""
    try:
        config = json.loads((root / WORKSPACE).read_text(encoding="utf-8"))
        repos, main = list(config["repos"]), str(config.get("main", "main"))
    except (OSError, ValueError, KeyError, TypeError):
        return command
    for repo in repos:
        command = re.sub(rf"(\bcd\s+){re.escape(repo)}(?=[/\s;&|)]|$)", rf"\g<1>{repo}/{main}", command)
    return command


def run(root: Path) -> dict[str, Any]:
    path = root / "implementation" / "preflight.json"
    if not path.is_file():
        raise SpecError("implementation/preflight.json is missing; list the toolchain commands every delegated agent must be able to run")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SpecError(f"cannot read preflight.json: {error}") from error
    commands = config.get("commands") if isinstance(config, dict) else None
    if not isinstance(commands, list) or not commands or not all(isinstance(item, str) and item.strip() for item in commands):
        raise SpecError('preflight.json must be {"commands": ["<shell command>", ...]} with at least one command')

    commands = [on_main(root, item) for item in commands]
    results = []
    for item in commands:
        try:
            process = subprocess.run(item, shell=True, cwd=root, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
            passed, output = process.returncode == 0, (process.stdout + process.stderr).strip()
        except subprocess.TimeoutExpired:
            passed, output = False, f"timed out after {TIMEOUT_SECONDS}s"
        results.append({"command": item, "passed": passed, "output": output[-400:]})
    failed = [item for item in results if not item["passed"]]
    if failed:
        raise SpecError("preflight failed: " + "; ".join(f"`{item['command']}`: {item['output']}" for item in failed))
    return {"passed": True, "commands": [item["command"] for item in results]}
