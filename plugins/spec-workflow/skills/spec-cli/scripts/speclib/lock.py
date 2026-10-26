"""The lock manifest (implementation/spec-archive.json): archive, restore, unlock, relock."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tracker import requirements, store
from tracker.model import now

from .catalog import Catalog, Spec
from .errors import SpecError

Manifest = dict[str, Any]


def manifest_path(root: Path) -> Path:
    return root / "implementation" / "spec-archive.json"


def load_manifest(root: Path) -> Manifest:
    path = manifest_path(root)
    if not path.exists():
        return {"schema_version": 1, "archived": {}, "history": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SpecError(f"cannot read archive manifest: {error}") from error
    valid = isinstance(value, dict) and value.get("schema_version") == 1
    if not valid or not isinstance(value.get("archived"), dict) or not isinstance(value.get("history"), list):
        raise SpecError("unsupported or malformed archive manifest")
    return value


def save_manifest(root: Path, manifest: Manifest) -> None:
    path = manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    store.write_atomic(path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def lock_errors(catalog: Catalog, manifest: Manifest) -> list[str]:
    errors: list[str] = []
    root = catalog.root
    for name, entry in sorted(manifest["archived"].items()):
        path = root / "specs" / name
        if not path.is_file():
            errors.append(f"archived specification is missing: {name}")
            continue
        if not entry.get("unlocked") and entry.get("spec_sha256") != store.digest(path):
            errors.append(f"archived specification hash changed: {name}")
        record_name = entry.get("implementation_record")
        if record_name is None:
            spec = next((item for item in catalog.specs.values() if item.name == name), None)
            if spec is not None and spec.kind != "decision" and not entry.get("baseline"):
                errors.append(f"archived specification has no implementation record but is not a decision: {name}")
            continue
        record = root / str(record_name)
        if not record.is_file():
            errors.append(f"archived implementation record is missing: {name}")
        elif entry.get("implementation_sha256") != store.digest(record):
            errors.append(f"archived implementation record hash changed: {name}")
    return errors


def require(confirmed: bool, operation: str) -> None:
    if not confirmed:
        raise SpecError(f"{operation} requires --parent-confirmed")


def read_record(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SpecError(f"cannot read implementation record: {error}") from error
    if not isinstance(value, dict):
        raise SpecError("malformed implementation record")
    return value


def accepted_record(root: Path, spec: Spec, spec_hash: str) -> tuple[str, str]:
    record_path = root / "implementation" / "archive" / f"{spec.feature}.json"
    if not record_path.is_file():
        raise SpecError("accepted archived implementation record is required")
    record = read_record(record_path)
    specification = record.get("specification", {})
    if record.get("status") != "accepted":
        raise SpecError("implementation record is not accepted")
    if specification.get("path") != f"specs/{spec.name}":
        raise SpecError("implementation record references a different specification")
    if specification.get("sha256") != spec_hash:
        raise SpecError("implementation record specification hash does not match")
    return record_path.relative_to(root).as_posix(), store.digest(record_path)


def archive(catalog: Catalog, manifest: Manifest, value: str, confirmed: bool) -> dict[str, Any]:
    require(confirmed, "archive")
    root = catalog.root
    spec = catalog.get(value)
    if spec.name in manifest["archived"]:
        raise SpecError("specification is already archived")
    own_errors = [error for error in catalog.errors if error.startswith(f"{spec.name}:")]
    if own_errors:
        raise SpecError("specification is invalid: " + "; ".join(own_errors))
    depends_on = spec.relations["depends_on"]
    pending = [target for target in depends_on if target not in catalog.specs or catalog.specs[target].name not in manifest["archived"]]
    if pending:
        raise SpecError(f"depends_on specs are not accepted yet: {pending}")
    if not requirements.has_requirements(spec.path.read_text(encoding="utf-8")):
        raise SpecError("specification has no `- **R<n>** text` requirement bullets; an empty spec cannot be accepted")
    spec_hash = store.digest(spec.path)
    record_name, record_hash = (None, None) if spec.kind == "decision" else accepted_record(root, spec, spec_hash)
    timestamp = now()
    entry = {
        "spec_sha256": spec_hash, "implementation_record": record_name,
        "implementation_sha256": record_hash, "archived_at": timestamp,
    }
    manifest["archived"][spec.name] = entry
    manifest["history"].append({"action": "archive", "specification": spec.name, "at": timestamp, **entry})
    save_manifest(root, manifest)
    return {"specification": spec.name, "status": "accepted", "archived_at": timestamp}


def archived_entry(manifest: Manifest, spec: Spec) -> dict[str, Any]:
    entry = manifest["archived"].get(spec.name)
    if not entry:
        raise SpecError("specification is not archived")
    return entry


def restore(catalog: Catalog, manifest: Manifest, value: str, reason: str, confirmed: bool) -> dict[str, Any]:
    require(confirmed, "restore")
    root = catalog.root
    spec = catalog.get(value)
    entry = archived_entry(manifest, spec)
    if entry["spec_sha256"] != store.digest(spec.path):
        raise SpecError("cannot restore a specification whose hash changed (relock it first)")
    if entry.get("implementation_record") is None and spec.kind != "decision":
        raise SpecError("cannot restore a baseline spec: it has no implementation record to reopen; amend it with a new spec instead")
    if entry.get("implementation_record") is not None:
        record = root / entry["implementation_record"]
        if not record.is_file() or entry["implementation_sha256"] != store.digest(record):
            raise SpecError("cannot restore because the archived implementation record changed or is missing")
        reactivate(root, spec.feature)
    del manifest["archived"][spec.name]
    manifest["history"].append({"action": "restore", "specification": spec.name, "at": now(), "reason": reason, "previous_archive": entry})
    save_manifest(root, manifest)
    return {"specification": spec.name, "status": "restored", "reason": reason}


def reactivate(root: Path, feature: str) -> None:
    tracker = Path(store.__file__).resolve().parents[1] / "spec_tracker.py"
    process = subprocess.run(
        [sys.executable, str(tracker), "--json", "restore", feature, "--parent-confirmed"],
        cwd=root, text=True, capture_output=True, check=False,
    )
    if process.returncode != 0:
        raise SpecError(f"cannot reactivate implementation record: {process.stdout or process.stderr}")


def unlock(catalog: Catalog, manifest: Manifest, value: str, reason: str, decision: str, confirmed: bool) -> dict[str, Any]:
    require(confirmed, "unlock")
    if not reason.strip() or not decision.strip():
        raise SpecError("unlock requires a non-empty --reason and --user-decision")
    spec = catalog.get(value)
    entry = archived_entry(manifest, spec)
    if entry.get("unlocked"):
        raise SpecError("specification is already unlocked")
    timestamp = now()
    entry["unlocked"] = {"reason": reason, "user_decision": decision, "at": timestamp}
    manifest["history"].append({"action": "unlock", "specification": spec.name, "at": timestamp, "reason": reason, "user_decision": decision})
    save_manifest(catalog.root, manifest)
    return {"specification": spec.name, "unlocked": True}


def resync_record(root: Path, feature: str, archived: bool, new_hash: str, reason: str) -> bool:
    """Point a tracker record at a new spec hash, keeping hash history. Returns whether it changed."""
    record = store.load(root, feature, archived)
    specification = record["specification"]
    if specification["sha256"] == new_hash:
        return False
    specification.setdefault("history", []).append(
        {"previous_sha256": specification["sha256"], "sha256": new_hash, "reason": reason, "at": now()}
    )
    specification["sha256"] = new_hash
    store.save(root, record, archived)
    return True


def relock(catalog: Catalog, manifest: Manifest, value: str, confirmed: bool) -> dict[str, Any]:
    require(confirmed, "relock")
    root = catalog.root
    spec = catalog.get(value)
    entry = archived_entry(manifest, spec)
    unlocked = entry.get("unlocked")
    if not unlocked:
        raise SpecError("specification is not unlocked")
    previous, current = entry["spec_sha256"], store.digest(spec.path)
    if entry.get("implementation_record") is not None:
        resync_record(root, spec.feature, True, current, f"relock: {unlocked['reason']}")
        entry["implementation_sha256"] = store.digest(root / entry["implementation_record"])
    entry["spec_sha256"] = current
    del entry["unlocked"]
    manifest["history"].append(
        {"action": "relock", "specification": spec.name, "at": now(), "previous_sha256": previous, "spec_sha256": current, "unlock": unlocked}
    )
    save_manifest(root, manifest)
    return {"specification": spec.name, "unlocked": False, "spec_sha256": current}
