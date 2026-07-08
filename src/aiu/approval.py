"""Course blueprint approval gate."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore
from aiu.project import update_manifest_artifacts
from aiu.state import complete_stage


class ApprovalError(ValueError):
    """Raised when blueprint approval cannot be completed."""


def approve_course(course_root: str | Path, *, mode: str = "manual") -> dict[str, Any]:
    """Approve the current course blueprint by snapshotting it."""

    store = ArtifactStore(course_root)
    blueprint_path = store.course_path("course_blueprint.json")
    if not blueprint_path.exists():
        raise ApprovalError("Cannot approve before course_blueprint.json exists.")

    blueprint = store.read_json("course_blueprint.json")
    store.write_json("approved_course_blueprint.json", blueprint)
    metadata = {
        "approval_mode": mode,
        "approved_at": _iso_timestamp(),
        "blueprint_checksum": _checksum_json(blueprint),
        "blueprint_ref": "course_blueprint.json",
        "approved_blueprint_ref": "approved_course_blueprint.json",
    }
    store.write_json("approval_metadata.json", metadata)
    update_manifest_artifacts(
        course_root,
        [
            ("approved_course_blueprint", "json", "approved_course_blueprint.json"),
            ("approval_metadata", "json", "approval_metadata.json"),
        ],
    )
    complete_stage(
        course_root,
        "approval",
        ["approved_course_blueprint.json", "approval_metadata.json"],
    )
    return metadata


def is_course_approved(course_root: str | Path) -> bool:
    store = ArtifactStore(course_root)
    return store.course_path("approved_course_blueprint.json").is_file()


def _checksum_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _iso_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
