#!/usr/bin/env python3
"""PreToolUse guard: workflow state is CLI-only; specs are created and edited only by the spec CLI (accepted specs are
frozen); subagents never edit specs/ (except proposals in specs/.drafts/) or run spec-mutating commands; the plugin
cache is never edited; and a subagent with a lane assignment writes only inside its assigned paths.

Agent identity: Claude Code puts `agent_id` and `agent_type` in the hook input for tool calls inside a subagent (no
prompt, no environment variable). An assignment binds to an agent_id through the marker file
implementation/.assignments/<agent_id>: written when the agent runs `spec-tracker claim <assignment>` (the brief's
first command), or automatically when exactly one active assignment has the agent's role. Unknown → allowed, with a warning."""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "spec-tracker" / "scripts"))
from tracker import paths as lanes  # noqa: E402
from tracker import workspace  # noqa: E402

ROOT_MARKERS = ("CLAUDE.md", "AGENTS.md", ".git")
STATE_PATHS = ("implementation/active/", "implementation/archive/", "implementation/spec-archive.json", "implementation/toolkit.json",
               "implementation/.assignments/")
CACHE_ENV = "SPEC_WORKFLOW_PLUGIN_CACHE"
CACHE_DENIAL = ("The plugin cache is a release artifact; never patch it. Edit the plugin source, bump its version, then "
                "`claude plugin marketplace update <marketplace> && claude plugin update <plugin>@<marketplace>`.")
SPEC_FILE = re.compile(r"^specs/[0-9]{4}-[a-z0-9-]+\.md$")
TRACKER_COMMANDS = {"spec_tracker.py", "spec-tracker"}
AGENT_ROLES = {"spec-planner": "planner", "spec-implementer": "implementer", "spec-reviewer": "reviewer", "spec-tester": "tester",
               "spec-fixer": "fixer", "spec-toolsmith": "toolsmith"}
WARNINGS: list[str] = []
MANIFEST = "implementation/spec-archive.json"
DRAFTS = "specs/.drafts/"
SPEC_COMMANDS = {"spec.py", "spec"}
MUTATING_SPEC_COMMANDS = {"new", "edit", "archive", "restore", "unlock", "relock", "promote", "adopt", "defer", "undefer"}
# Commands whose path arguments are written; a best-effort net, since Bash can write files in many other ways.
WRITING_COMMANDS = {"mv", "rm", "touch", "tee", "truncate", "mkdir", "rmdir"}
DESTINATION_COMMANDS = {"cp", "install", "ln", "rsync"}  # only the last argument is written
IN_PLACE_COMMANDS = {"sed", "perl"}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", "1>", "2>", "1>>", "2>>"}
SUBAGENT_SPECS = "Subagents must not modify specs/. Write proposals to specs/.drafts/ and report them to the parent, or raise a blocker."


def project_root(path: Path) -> Path | None:
    for directory in path.parents:
        if (directory / "specs").is_dir() and any((directory / marker).exists() for marker in ROOT_MARKERS):
            return directory
    return None


def frozen(root: Path, name: str) -> bool:
    """Whether specs/<name> is archived and not unlocked. Fails open on an unreadable manifest."""
    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        entry = manifest["archived"].get(name)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
    return isinstance(entry, dict) and not entry.get("unlocked")


def in_drafts(relative: str) -> bool:
    return relative == DRAFTS.rstrip("/") or relative.startswith(DRAFTS)


def is_subagent(event: dict) -> bool:
    # Hook input carries agent_id only for tool calls made inside a subagent.
    return bool(event.get("agent_id"))


def spec_denial(root: Path, path: Path, relative: str, event: dict) -> str | None:
    if in_drafts(relative):
        return None
    if is_subagent(event):
        return SUBAGENT_SPECS
    if not path.exists():
        return "Do not create files in specs/ directly; create specs with `spec.py new --title ... --kind ... --from specs/.drafts/<file>.md`."
    spec_id = path.name.split("-", 1)[0]
    if relative.count("/") == 1 and frozen(root, path.name):
        return (
            f"Accepted spec is frozen; create a new spec with `spec.py new --amends {spec_id} --from specs/.drafts/<file>.md` "
            "(or the parent may `unlock` it with a user decision, then `spec.py edit`)."
        )
    return (f"Spec edits are audited: write the new body to specs/.drafts/<file>.md, then "
            f"`spec.py edit {spec_id} --from specs/.drafts/<file>.md --reason \"...\" [--user-decision \"...\"] --parent-confirmed`.")


def in_cache(target: str, event: dict) -> bool:
    cache = Path(os.environ.get(CACHE_ENV) or Path.home() / ".claude" / "plugins" / "cache").expanduser().resolve()
    path = Path(os.path.expanduser(target))
    if not path.is_absolute():
        path = Path(event.get("cwd") or ".") / path
    path = path.resolve()
    return path == cache or cache in path.parents


def agent_role(event: dict) -> str | None:
    return AGENT_ROLES.get(str(event.get("agent_type") or "").split(":")[-1])


def own_assignment(root: Path, event: dict, active: list[dict]) -> dict | None:
    agent = str(event.get("agent_id"))
    marker = lanes.marker(root, agent)
    try:
        bound = marker.read_text(encoding="utf-8").strip()
    except OSError:
        bound = ""
    if bound:
        return next((item for item in active if item.get("id") == bound), None)
    role = agent_role(event)
    candidates = [item for item in active if role and item.get("role") == role]
    if len(candidates) == 1 and not claimed_by_other(root, candidates[0]["id"], agent):
        bind(root, agent, candidates[0]["id"])
        return candidates[0]
    return None


def claimed_by_other(root: Path, assignment: str, agent: str) -> bool:
    directory = root / lanes.ASSIGNMENTS_DIR
    for path in directory.glob("*") if directory.is_dir() else []:
        try:
            if path.name != lanes.marker(root, agent).name and path.read_text(encoding="utf-8").strip() == assignment:
                return True
        except OSError:
            continue
    return False


def bind(root: Path, agent: str, assignment: str) -> None:
    marker = lanes.marker(root, agent)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(assignment + "\n", encoding="utf-8")
    except OSError as error:
        WARNINGS.append(f"cannot record assignment binding {assignment}: {error}")


def ownership_denial(root: Path, relative: str, event: dict) -> str | None:
    """Subagent writes must fall inside the agent's assignment and outside every other active assignment."""
    if not is_subagent(event) or relative.startswith("specs/") or relative.startswith("implementation/"):
        return None
    try:
        config = workspace.load(root)
    except workspace.WorkspaceError as error:
        WARNINGS.append(f"spec-workflow: {error}")
        config = None
    checkout = workspace.split(config, relative) if config else None
    if checkout and checkout[1] == config["main"]:
        return (f"{checkout[0]}/{config['main']}/ is accepted code, changed only by `spec-tracker worktree merge`; "
                f"work in your spec's checkout ({checkout[0]}/<branch>/, the brief's Worktree line).")
    active = lanes.active_assignments(root)
    if not active:
        return None
    own = own_assignment(root, event, active)
    if checkout and own is not None:
        branch = own.get("branch")
        if branch and checkout[1] != branch:
            problem = f"{relative} is in another spec's checkout; your assignment {own['id']} works in {checkout[0]}/{branch}/."
            if os.environ.get("SPEC_WORKFLOW_STRICT_LANES") == "1":
                return problem
            WARNINGS.append(f"spec-workflow (advisory): {problem} Mention this edit in your handoff.")
            return None
        # Lanes are repo-relative; only this checkout's lanes compete for the file.
        relative = workspace.logical(config, relative)
        active = [item for item in active if item.get("branch") == checkout[1]]
    if own is None:
        WARNINGS.append(f"spec-workflow: lane ownership not enforced for {relative}: this agent has no known assignment "
                        "(run `spec-tracker claim <assignment-id>` from the brief first)")
        return None
    fix = f"ask the parent to widen it (`spec-tracker assign {own['feature']} --role {own['role']} --paths ... --parent-confirmed`) or report the file"
    problem = None
    carved = [entry for entry in own.get("carved") or [] if lanes.matches([entry["glob"]], relative)]
    if carved:
        problem = (f"{relative} was carved out of your assignment {own['id']} to {carved[0]['to']} ({carved[0]['feature']}); "
                   "leave it to that agent or report the change to the parent.")
    elif not lanes.matches(own.get("paths") or [], relative):
        allowed = ", ".join(own.get("paths") or []) or "none (read-only)"
        problem = f"{relative} is outside your assignment {own['id']} (allowed: {allowed}); {fix}."
    else:
        clash = [item for item in active if item["id"] != own["id"] and lanes.owns(item, relative)]
        if clash:
            problem = f"{relative} is owned by {clash[0]['id']} ({clash[0]['feature']}, {clash[0]['role']}); {fix}."
    if problem is None:
        return None
    # Advisory by default: warn and let the subagent proceed; SPEC_WORKFLOW_STRICT_LANES=1 blocks instead.
    if os.environ.get("SPEC_WORKFLOW_STRICT_LANES") == "1":
        return problem
    WARNINGS.append(f"spec-workflow (advisory): {problem} Mention this edit in your handoff.")
    return None


def claim(event: dict, segment: list[str], cwd: Path) -> str | None:
    """Bind `spec-tracker claim <assignment>` to the calling subagent's agent_id."""
    for index, token in enumerate(segment):
        if Path(token).name not in TRACKER_COMMANDS:
            continue
        rest = [word for word in segment[index + 1:] if not word.startswith("-")]
        if len(rest) < 2 or rest[0] != "claim":
            return None
        root = project_root(cwd / "x")
        if root is None or not is_subagent(event):
            return None
        assignment, agent = rest[1], str(event.get("agent_id"))
        if not any(item.get("id") == assignment for item in lanes.active_assignments(root)):
            return f"unknown or released assignment {assignment}; ask the parent for a fresh brief (`spec-tracker brief <feature> --role <role>`)."
        if claimed_by_other(root, assignment, agent):
            return (f"assignment {assignment} is already claimed by another agent; ask the parent for a new brief "
                    "(`spec-tracker brief` reissues a claimed assignment with the same paths).")
        bind(root, agent, assignment)
    return None


def locate(target: str, event: dict) -> tuple[Path, Path, str] | None:
    path = Path(os.path.expanduser(target))
    if not path.is_absolute():
        path = Path(event.get("cwd") or ".") / path
    path = path.resolve()
    root = project_root(path)
    if root is None:
        return None
    return root, path, path.relative_to(root).as_posix()


def is_state(relative: str) -> bool:
    return any(relative == state.rstrip("/") or relative.startswith(state) for state in STATE_PATHS)


STATE_DENIAL = "Workflow state is managed only by the spec_tracker.py and spec.py CLIs; do not edit it directly."


def file_denial(event: dict) -> str | None:
    tool_input = event.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(target, str) or not target:
        return None
    if in_cache(target, event):
        return CACHE_DENIAL
    located = locate(target, event)
    if located is None:
        return None
    root, path, relative = located
    if is_state(relative):
        return STATE_DENIAL
    if relative.startswith("specs/"):
        return spec_denial(root, path, relative, event)
    return ownership_denial(root, relative, event)


def segments(command: str) -> list[list[str]]:
    """Split a shell command into simple-command token lists; unparsable input yields one raw split."""
    try:
        lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    found: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            found.append([])
        else:
            found[-1].append(token)
    return [segment for segment in found if segment]


def written_paths(segment: list[str]) -> list[str]:
    paths = [segment[index + 1] for index, token in enumerate(segment[:-1]) if token in REDIRECTS]
    words = [token for token in segment if not token.startswith("-") and token not in REDIRECTS]
    while words and ASSIGNMENT.match(words[0]):
        words.pop(0)
    name = Path(words[0]).name if words else ""
    in_place = name in IN_PLACE_COMMANDS and any(token.startswith("-i") or token == "--in-place" for token in segment)
    if name in WRITING_COMMANDS or in_place:
        paths.extend(words[1:])
    elif name in DESTINATION_COMMANDS and len(words) > 2:
        paths.append(words[-1])
    elif name == "dd":
        paths.extend(token[3:] for token in words if token.startswith("of="))
    return paths


def spec_cli_denial(segment: list[str]) -> str | None:
    for index, token in enumerate(segment):
        if Path(token).name not in SPEC_COMMANDS:
            continue
        rest = [word for word in segment[index + 1:] if not word.startswith("-")]
        if rest and rest[0] in MUTATING_SPEC_COMMANDS:
            return f"Subagents must not run `spec.py {rest[0]}`; only the parent creates, promotes, archives, or unlocks specs. " + SUBAGENT_SPECS
    return None


def bash_denial(event: dict) -> str | None:
    command = (event.get("tool_input") or {}).get("command")
    if not isinstance(command, str) or not command:
        return None
    subagent = is_subagent(event)
    cwd = Path(event.get("cwd") or ".")
    for segment in segments(command):
        if segment[0] == "cd" and len(segment) > 1:
            cwd = cwd / os.path.expanduser(segment[1])
            continue
        if subagent:
            reason = spec_cli_denial(segment) or claim(event, segment, cwd)
            if reason:
                return reason
        for target in written_paths(segment):
            scoped = {**event, "cwd": str(cwd)}
            if in_cache(target, scoped):
                return CACHE_DENIAL
            located = locate(target, scoped)
            if located is None:
                continue
            root, path, relative = located
            if is_state(relative):
                return STATE_DENIAL
            if subagent and (relative == "specs" or relative.startswith("specs/")) and not in_drafts(relative):
                return SUBAGENT_SPECS
            if SPEC_FILE.match(relative) and path.exists():
                return spec_denial(root, path, relative, scoped)
            reason = ownership_denial(root, relative, scoped)
            if reason:
                return reason
    return None


def denial(event: dict) -> str | None:
    if event.get("tool_name") == "Bash":
        return bash_denial(event)
    return file_denial(event)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    reason = denial(event) if isinstance(event, dict) else None
    if reason:
        print(reason, file=sys.stderr)
        return 2
    if WARNINGS:
        print(json.dumps({"systemMessage": "; ".join(dict.fromkeys(WARNINGS))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
