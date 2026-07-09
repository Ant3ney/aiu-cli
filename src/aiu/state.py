"""Checkpoint state for resumable course generation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiu.artifact_store import ArtifactStore

STATE_REF = ".aiu/state.json"
STAGE_ORDER = (
    "project",
    "inputs",
    "context",
    "research",
    "blueprint",
    "approval",
    "syllabus",
    "lectures",
    "labs",
    "assessments",
    "rails",
    "validation",
    "export",
)
PENDING_STAGES = {"status": "pending", "artifacts": []}


def initialize_state(course_root: str | Path) -> None:
    """Create a fresh state file for a course project."""

    now = _iso_timestamp()
    state = {
        "artifacts": {},
        "created_at": now,
        "failures": [],
        "stages": {stage: {"artifacts": [], "status": "pending"} for stage in STAGE_ORDER},
        "updated_at": now,
        "version": 1,
    }
    state["stages"]["project"]["status"] = "complete"
    ArtifactStore(course_root).write_json(STATE_REF, state)


def load_state(course_root: str | Path) -> dict[str, Any]:
    """Load checkpoint state, creating it if missing."""

    store = ArtifactStore(course_root)
    if not store.course_path(STATE_REF).exists():
        initialize_state(course_root)
    state = store.read_json(STATE_REF)
    for stage in STAGE_ORDER:
        state.setdefault("stages", {}).setdefault(stage, {"artifacts": [], "status": "pending"})
    state.setdefault("artifacts", {})
    state.setdefault("failures", [])
    return state


def write_state(course_root: str | Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _iso_timestamp()
    ArtifactStore(course_root).write_json(STATE_REF, state)


def start_stage(course_root: str | Path, stage: str) -> None:
    state = load_state(course_root)
    state["stages"][stage]["status"] = "running"
    write_state(course_root, state)


def complete_stage(
    course_root: str | Path,
    stage: str,
    artifacts: list[str] | tuple[str, ...] = (),
) -> None:
    state = load_state(course_root)
    stage_state = state["stages"][stage]
    stage_state["status"] = "complete"
    stage_state["artifacts"] = sorted(set([*stage_state.get("artifacts", []), *artifacts]))
    for artifact in artifacts:
        _record_artifact(course_root, state, stage, artifact, status="complete")
    write_state(course_root, state)


def record_artifact_complete(course_root: str | Path, stage: str, artifact: str) -> None:
    """Checkpoint one completed artifact without marking the whole stage complete."""

    state = load_state(course_root)
    stage_state = state["stages"][stage]
    if stage_state["status"] == "pending":
        stage_state["status"] = "running"
    stage_state["artifacts"] = sorted(set([*stage_state.get("artifacts", []), artifact]))
    _record_artifact(course_root, state, stage, artifact, status="complete")
    write_state(course_root, state)


def fail_stage(course_root: str | Path, stage: str, error: str) -> None:
    state = load_state(course_root)
    state["stages"][stage]["status"] = "failed"
    state["failures"].append(
        {
            "error": error,
            "failed_at": _iso_timestamp(),
            "stage": stage,
        }
    )
    write_state(course_root, state)


def skip_stage(course_root: str | Path, stage: str, reason: str) -> None:
    state = load_state(course_root)
    state["stages"][stage]["status"] = "skipped"
    state["stages"][stage]["reason"] = reason
    write_state(course_root, state)


def stage_is_complete(
    course_root: str | Path,
    stage: str,
    required_artifacts: list[str] | tuple[str, ...] = (),
) -> bool:
    state = load_state(course_root)
    if state["stages"].get(stage, PENDING_STAGES)["status"] != "complete":
        return False
    store = ArtifactStore(course_root)
    return all(store.course_path(artifact).exists() for artifact in required_artifacts)


def status_lines(course_root: str | Path) -> list[str]:
    state = load_state(course_root)
    lines = ["Course generation status:"]
    for stage in STAGE_ORDER:
        stage_state = state["stages"].get(stage, PENDING_STAGES)
        lines.append(f"- {stage}: {stage_state['status']}")
    if state.get("failures"):
        lines.append("Failures:")
        for failure in state["failures"]:
            lines.append(f"- {failure['stage']}: {failure['error']}")
    return lines


def _record_artifact(
    course_root: str | Path,
    state: dict[str, Any],
    stage: str,
    artifact: str,
    *,
    status: str,
) -> None:
    path = ArtifactStore(course_root).course_path(artifact)
    record = {
        "stage": stage,
        "status": status,
        "updated_at": _iso_timestamp(),
    }
    if path.exists() and path.is_file():
        record["checksum"] = _sha256_file(path)
        record["size_bytes"] = path.stat().st_size
    state["artifacts"][artifact] = record


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _iso_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
