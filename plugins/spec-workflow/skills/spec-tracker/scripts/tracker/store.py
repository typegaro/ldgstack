"""Project discovery and atomic persistence of implementation records."""
from __future__ import annotations

import hashlib
import json
import os
import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .render import markdown

ROOT_ENV = "SPEC_WORKFLOW_ROOT"
ROOT_MARKERS = ("CLAUDE.md", "AGENTS.md", ".git")
SCHEMA_VERSION = 1
FEATURE_CHARACTERS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


class TrackerError(Exception):
    pass


def find_root(start: Path | None = None) -> Path:
    override = os.environ.get(ROOT_ENV)
    if override:
        root = Path(override).resolve()
        if not (root / "specs").is_dir():
            raise TrackerError(f"{ROOT_ENV} has no specs/ directory: {root}")
        return root
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / "specs").is_dir() and any((directory / marker).exists() for marker in ROOT_MARKERS):
            return directory
    raise TrackerError(f"cannot find project root: need specs/ beside one of {', '.join(ROOT_MARKERS)}, or set {ROOT_ENV}")


def feature_name(value: str) -> str:
    name = Path(value).name
    if name.endswith((".md", ".json")):
        name = Path(name).stem
    if not name or not set(name) <= FEATURE_CHARACTERS:
        raise TrackerError("feature must be a lowercase kebab-case specification basename")
    return name


def spec_path(root: Path, value: str) -> Path:
    feature = feature_name(value)
    path = root / "specs" / f"{feature}.md"
    if not path.is_file():
        raise TrackerError(f"specification does not exist: specs/{feature}.md")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records_dir(root: Path, archived: bool = False) -> Path:
    return root / "implementation" / ("archive" if archived else "active")


def record_path(root: Path, feature: str, archived: bool = False) -> Path:
    return records_dir(root, archived) / f"{feature_name(feature)}.json"


def load(root: Path, feature: str, archived: bool = False) -> dict[str, Any]:
    path = record_path(root, feature, archived)
    if not path.is_file():
        raise TrackerError(f"implementation record does not exist: {path.relative_to(root)}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrackerError(f"cannot read implementation record: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise TrackerError("unsupported or malformed implementation record")
    return value


def load_all(root: Path) -> list[dict[str, Any]]:
    return [load(root, path.stem) for path in sorted(records_dir(root).glob("*.json"))]


def save(root: Path, record: dict[str, Any], archived: bool = False) -> None:
    directory = records_dir(root, archived)
    directory.mkdir(parents=True, exist_ok=True)
    feature = feature_name(str(record["feature"]))
    write_atomic(directory / f"{feature}.json", json.dumps(record, indent=2, sort_keys=True) + "\n")
    write_atomic(directory / f"{feature}.md", markdown(record))


def remove(root: Path, feature: str, archived: bool = False) -> None:
    for suffix in (".json", ".md"):
        path = records_dir(root, archived) / f"{feature}{suffix}"
        if path.exists():
            path.unlink()


def write_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def project_lock(root: Path):
    """Serialize spec/tracker reads and mutations across processes.

    Spec CLI operations may invoke the tracker CLI. The inherited marker makes
    that child reuse the parent's lock instead of deadlocking.
    """
    lock_path = (root / ".spec-workflow.lock").resolve()
    if os.environ.get("SPEC_WORKFLOW_LOCK_HELD") == str(lock_path):
        yield
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        previous = os.environ.get("SPEC_WORKFLOW_LOCK_HELD")
        os.environ["SPEC_WORKFLOW_LOCK_HELD"] = str(lock_path)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("SPEC_WORKFLOW_LOCK_HELD", None)
            else:
                os.environ["SPEC_WORKFLOW_LOCK_HELD"] = previous
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
